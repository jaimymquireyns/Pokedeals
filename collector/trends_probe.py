"""Test: loopt de zoekinteresse (Google Trends, via Scrape.do) vooruit op de prijs?

Voor een paar kaarten halen we de zoekinteresse op en leggen die naast onze eigen prijsgeschiedenis. Vooral de
Electivire LV.X is interessant: de trendprijs stond rond €22 en er werd ineens €205 gevraagd. Zat daar in de
weken ervoor al meer zoekinteresse in? Kost 10 credits per opzoeking (gratis laag: 1.000 credits per maand).

    python trends_probe.py                          # standaard: 4 zoektermen x 2 periodes = 80 credits
    python trends_probe.py --terms "Mew ex,Lugia"    # eigen zoektermen (dan geen prijsvergelijking)

Nodig: SCRAPEDO_API_KEY. Optioneel (voor de prijsvergelijking): SUPABASE_URL en SUPABASE_SECRET_KEY.
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone

import requests

ENDPOINT = "https://api.scrape.do/plugin/google/trends"
SPARK = "▁▂▃▄▅▆▇█"

# term = wat mensen in Google zouden typen; name/number = hoe de kaart in onze eigen database staat (voor de prijs)
CASES = [
    {"term": "Electivire LV.X", "name": "Electivire", "number": "121", "set": "Mysterious Treasures"},
    {"term": "Charizard ex Obsidian Flames", "name": "Charizard ex", "number": "125", "set": "Obsidian Flames"},
    {"term": "Lugia Secret Wonders", "name": "Lugia", "number": "14", "set": "Secret Wonders"},
    {"term": "Pokemon cards", "name": None, "number": None},   # algemene 'achtergrondruis' ter vergelijking
]
WINDOWS = ["today 3-m", "today 12-m"]   # 3 maanden = dagcijfers, 12 maanden = weekcijfers


# ---------- antwoord uitlezen (bewust ruim: het exacte formaat kennen we pas na de eerste echte run) ----------
def _time_of(d):
    for k in ("time", "timestamp"):
        v = d.get(k)
        if v not in (None, ""):
            try:
                return datetime.fromtimestamp(int(v), tz=timezone.utc).date().isoformat()
            except (TypeError, ValueError, OverflowError):
                pass
    for k in ("date", "formattedTime", "formattedAxisTime", "day"):
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _value_of(d):
    for k in ("extracted_value", "value", "values", "formattedValue"):
        v = d.get(k)
        while isinstance(v, list) and v:
            v = v[0]
        if isinstance(v, dict):
            v = v.get("extracted_value", v.get("value"))
        try:
            if v is not None and v != "":
                return float(str(v).replace("<", "").replace(",", "."))
        except ValueError:
            continue
    return None


def extract_points(obj):
    """Zoekt in een willekeurig JSON-antwoord de langste lijst waarvan elk element een tijdstip én een waarde heeft."""
    best = []

    def walk(x):
        nonlocal best
        if isinstance(x, list) and x and all(isinstance(i, dict) for i in x):
            pts = [(t, v) for i in x for t, v in [(_time_of(i), _value_of(i))] if t is not None and v is not None]
            if len(pts) >= 4 and len(pts) > len(best):
                best = pts
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return best


def sparkline(values):
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return SPARK[0] * len(values)
    return "".join(SPARK[min(len(SPARK) - 1, int((v - lo) / (hi - lo) * (len(SPARK) - 1) + 0.5))] for v in values)


def resample(values, n):
    """Middelt een lange reeks terug naar n gelijke stukken, zodat twee reeksen onder elkaar te vergelijken zijn."""
    if not values or n <= 0:
        return []
    out = []
    for i in range(n):
        chunk = values[int(i * len(values) / n): max(int((i + 1) * len(values) / n), int(i * len(values) / n) + 1)]
        out.append(sum(chunk) / len(chunk))
    return out


def interest_change(values):
    """Recente zoekinteresse (laatste kwart) ten opzichte van de periode daarvoor (de middelste helft)."""
    n = len(values)
    if n < 8:
        return None
    recent = values[int(n * 0.75):]
    before = values[int(n * 0.25): int(n * 0.75)]
    if not before or sum(before) == 0:
        return None
    return (sum(recent) / len(recent)) / (sum(before) / len(before))


def jump_context(interest, prices):
    """Voor de grootste stap omhoog in de prijs: hoe stond de zoekinteresse in de stukken ervoor en erna?
    Beide reeksen zijn al op dezelfde lengte gebracht."""
    n = min(len(interest), len(prices))
    if n < 8:
        return None
    steps = [(prices[i] / prices[i - 1] - 1 if prices[i - 1] else 0, i) for i in range(1, n)]
    change, i = max(steps)
    if change <= 0.15:
        return {"jump": change, "at": i, "note": "geen duidelijke prijssprong (>15%) in deze periode"}
    w = max(2, n // 8)
    before = interest[max(0, i - w): i]
    after = interest[i: i + w]
    return {"jump": change, "at": i, "before": sum(before) / len(before) if before else None,
            "after": sum(after) / len(after) if after else None, "of": n}


# ---------- ophalen ----------
def fetch(token, term, date, geo="", session=None, tries=3, log=print):
    s = session or requests
    for attempt in range(tries):
        r = s.get(ENDPOINT, params={"token": token, "q": term, "date": date, "geo": geo, "data_type": "TIMESERIES"}, timeout=90)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 502 and attempt < tries - 1:   # 'upstream mislukt, probeer opnieuw' (staat in hun documentatie)
            time.sleep(3)
            continue
        log(f"  ! {term} ({date}): HTTP {r.status_code}: {r.text[:200]}")
        return None
    return None


def own_prices(store, name, number, set_name=None):
    """Onze eigen dagelijkse Cardmarket-trendprijs voor deze kaart (laatste 12 maanden), of [] als niet te vinden."""
    if not (store and name and number):
        return []
    extra = {"name": f"ilike.{name}", "number": f"eq.{number}"}
    if set_name:
        extra["set_name"] = f"ilike.{set_name}"
    prods = store.products("card", extra=extra)
    if not prods:
        return []
    rows = store.select("prices", {"select": "date,price", "product_id": f"eq.{prods[0]['product_id']}", "grade_key": "eq.raw", "order": "date.asc"})
    best = {}
    for r in rows:
        if r.get("price") is not None:
            best[r["date"]] = float(r["price"])   # bij meerdere bronnen op één dag: de laatste wint, voor dit doel goed genoeg
    return [best[d] for d in sorted(best)]


def run(token, cases=None, windows=None, store=None, geo="", log=print, session=None):
    cases, windows = cases or CASES, windows or WINDOWS
    first = True
    for case in cases:
        prices = own_prices(store, case.get("name"), case.get("number"), case.get("set"))
        log(f"\n=== {case['term']} ===")
        if prices:
            log(f"prijs (eigen data, {len(prices)} dagen): {sparkline(resample(prices, 40))}  van €{prices[0]:.2f} naar €{prices[-1]:.2f}")
        for date in windows:
            data = fetch(token, case["term"], date, geo, session=session, log=log)
            if data is None:
                continue
            if first:
                log("(ruwe structuur van het allereerste antwoord, voor controle)")
                log("  " + json.dumps(data, ensure_ascii=False)[:900])
                first = False
            pts = extract_points(data)
            if not pts:
                log(f"  {date}: geen tijdreeks herkend in het antwoord (sleutels: {list(data)[:8] if isinstance(data, dict) else type(data).__name__})")
                continue
            vals = [v for _, v in pts]
            ch = interest_change(vals)
            log(f"  zoekinteresse {date} ({len(vals)} punten, {pts[0][0]} t/m {pts[-1][0]}): {sparkline(vals)}")
            log(f"    recent t.o.v. daarvoor: " + (f"x{ch:.2f}" if ch is not None else "n.v.t.") + f"   (gemiddeld {sum(vals) / len(vals):.0f} van 100)")
            if prices and date == windows[-1]:
                jc = jump_context(resample(vals, 40), resample(prices, 40))
                if jc and "before" in jc:
                    log(f"    grootste prijssprong: +{jc['jump'] * 100:.0f}% (stap {jc['at']} van {jc['of']}); zoekinteresse ervoor {jc['before']:.0f}, erna {jc['after']:.0f}")
                elif jc:
                    log(f"    {jc['note']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terms", help="komma-gescheiden eigen zoektermen (dan geen prijsvergelijking)")
    ap.add_argument("--geo", default="", help="landcode, bijv. NL of US (standaard: wereldwijd)")
    args = ap.parse_args()
    token = os.environ.get("SCRAPEDO_API_KEY")
    if not token:
        raise SystemExit("SCRAPEDO_API_KEY ontbreekt (GitHub → Settings → Secrets and variables → Actions).")
    store = None
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SECRET_KEY"):
        from store import SupabaseStore
        store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    cases = [{"term": t.strip(), "name": None, "number": None} for t in args.terms.split(",") if t.strip()] if args.terms else None
    run(token, cases=cases, store=store, geo=args.geo)


if __name__ == "__main__":
    main()
