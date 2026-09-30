"""Stap 2 van het meersignalenplan: elke kaart van de beroemde Pokémon krijgt een aantal losse signalen, elk
+1 (gunstig om te kopen), 0 (neutraal) of -1 (ongunstig). Home gaat later alleen kaarten tonen waar meerdere
signalen tegelijk positief zijn, maar pas nadat de backtest hieronder laat zien dat zo'n combinatie ook echt
vaker uitkomt dan gemiddeld.

Signalen uit de prijsgeschiedenis (ook terug in de tijd te testen):
  onder_gemiddelde   prijs t.o.v. het gemiddelde van de laatste 180 dagen (eronder = positief, ver erboven = negatief;
                     de backtest liet al zien dat net gestegen kaarten vaker terugzakken dan doorstijgen)
  momentum           verandering over 14 dagen: licht herstel = positief, piek of nog vallend = negatief
  stabiliseert       onder het gemiddelde en de laatste 14 dagen rustig = de daling lijkt voorbij
Uit de kaartgegevens:
  reprint            er bestaat een nieuwere druk van dezelfde kaart = negatief
Uit de dagelijkse marktmomentopname (market_snapshot.py), pas na SIG_MIN_SNAPSHOT_DAYS dagen:
  aanbod             aantal listings neemt af = positief, neemt toe = negatief
  vraag              recente verkopen nemen toe = positief, nemen af = negatief
  liquiditeit        te weinig verkopers = negatief (dunne markt, prijs kan door 1 verkoper bepaald worden)

    python signals.py                 # momentopname + signalen van vandaag berekenen en opslaan (de dagelijkse taak)
    python signals.py --backtest      # per signaal nagaan hoe vaak een +10% stijging binnen 30 dagen volgde
    python signals.py --skip-snapshot # alleen signalen, zonder PokemonPriceTracker
"""
import argparse
import math
import os
import time
from datetime import date, timedelta

import analysis
import config
from store import SupabaseStore

PRICE_SIGNALS = ("onder_gemiddelde", "momentum", "stabiliseert")
MARKET_SIGNALS = ("aanbod", "vraag", "liquiditeit")


# ---------------- gegevens laden ----------------
def famous_products(store):
    return {p["product_id"]: p for p in store.products("card") if p.get("dex_id") in config.FAMOUS_DEX_IDS}


def load_series(store, product_ids, since):
    """Prijsreeks per kaart, op dezelfde manier opgebouwd als de kansberekening (Near Mint als die er is, anders de
    trend). In stukjes van 150 kaarten opgehaald, zodat het nooit de hele prijzentabel doorbladert."""
    raw, nm = {}, {}
    ids = sorted(product_ids)
    for i in range(0, len(ids), 150):
        ch = ",".join(ids[i:i + 150])
        for gk, target in (("raw", raw), ("nm", nm)):
            for r in store.select("prices", {"select": "product_id,date,source,price", "product_id": f"in.({ch})",
                                             "grade_key": f"eq.{gk}", "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
                if r.get("price") is not None:
                    target.setdefault(r["product_id"], []).append({**r, "price": float(r["price"]), "avg1": None, "avg7": None, "avg30": None})
    out = {}
    for pid in ids:
        by_source = {}
        for r in raw.get(pid, []):
            by_source.setdefault(r["source"], []).append(r)
        s = analysis.series_for(pid, by_source, nm_rows=nm.get(pid))
        if s:
            out[pid] = [(x["date"], float(x["price"])) for x in s if x.get("price")]
    return out


def load_snapshots(store, product_ids, since):
    out = {}
    ids = sorted(product_ids)
    for i in range(0, len(ids), 150):
        for r in store.select("market_snapshots", {"select": "*", "product_id": f"in.({','.join(ids[i:i + 150])})",
                                                    "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
            out.setdefault(r["product_id"], []).append(r)
    return out


# ---------------- signalen ----------------
def _price_on_or_before(points, day):
    best = None
    for d, p in points:
        if d <= day:
            best = p
        else:
            break
    return best


def price_signals(points):
    """points: [(datum, prijs)] tot en met 'vandaag', oplopend. Geeft None als er te weinig geschiedenis is."""
    if len(points) < 20:
        return None
    today = date.fromisoformat(points[-1][0])
    first = date.fromisoformat(points[0][0])
    if (today - first).days < 60:
        return None
    since = (today - timedelta(days=180)).isoformat()
    hist = [p for d, p in points if d >= since]
    p = points[-1][1]
    avg = sum(hist) / len(hist)
    vs_avg = p / avg - 1 if avg else 0.0
    p14 = _price_on_or_before(points, (today - timedelta(days=14)).isoformat())
    m14 = p / p14 - 1 if p14 else 0.0
    last14 = [x for d, x in points if d > (today - timedelta(days=14)).isoformat()]
    mean14 = sum(last14) / len(last14) if last14 else p
    cv14 = (math.sqrt(sum((x - mean14) ** 2 for x in last14) / len(last14)) / mean14) if len(last14) >= 3 and mean14 else None

    s = {}
    s["onder_gemiddelde"] = 1 if vs_avg <= -config.SIG_BELOW_AVG else (-1 if vs_avg >= config.SIG_BELOW_AVG else 0)
    s["momentum"] = 1 if 0 <= m14 <= config.SIG_MOM_MAX else (-1 if m14 > config.SIG_MOM_SPIKE or m14 < config.SIG_MOM_FALLING else 0)
    s["stabiliseert"] = 1 if (vs_avg <= -0.10 and cv14 is not None and cv14 <= config.SIG_STABLE_CV and m14 >= -0.03) else 0
    return {"signals": s, "vs_avg": round(vs_avg, 4), "momentum_14d": round(m14, 4), "cv_14d": round(cv14, 4) if cv14 is not None else None, "price": p}


def market_signals(snaps):
    """snaps: momentopnames van één kaart, oplopend op datum. Signalen pas na SIG_MIN_SNAPSHOT_DAYS dagen."""
    out = {}
    if snaps:
        sellers = snaps[-1].get("sellers")
        if sellers is not None:
            out["liquiditeit"] = -1 if sellers < config.SIG_MIN_SELLERS else (1 if sellers >= 10 else 0)
    if len(snaps) < config.SIG_MIN_SNAPSHOT_DAYS:
        return out

    def trend(key):
        vals = [s.get(key) for s in snaps[-14:] if s.get(key) is not None]
        if len(vals) < 10:
            return None
        a, b = vals[: len(vals) // 2], vals[len(vals) // 2:]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        return (mb / ma - 1) if ma else None

    lt, st = trend("listings"), trend("recent_sales")
    if lt is not None:
        out["aanbod"] = 1 if lt <= -0.10 else (-1 if lt >= 0.10 else 0)
    if st is not None:
        out["vraag"] = 1 if st >= 0.10 else (-1 if st <= -0.10 else 0)
    return out


def combine(price_part, product, snaps):
    sig = dict(price_part["signals"]) if price_part else {}
    sig["reprint"] = -1 if product.get("newer_printing") else 0
    sig.update(market_signals(snaps or []))
    return {"signals": sig, "n_positive": sum(1 for v in sig.values() if v > 0), "n_negative": sum(1 for v in sig.values() if v < 0),
            "score": sum(sig.values())}


# ---------------- dagelijks berekenen en opslaan ----------------
def compute_today(store, today, log=print):
    products = famous_products(store)
    if not products:
        log("Signalen: nog geen kaarten van beroemde Pokémon gevonden.")
        return 0
    series = load_series(store, products, (date.fromisoformat(today) - timedelta(days=200)).isoformat())
    snaps = load_snapshots(store, products, (date.fromisoformat(today) - timedelta(days=30)).isoformat())
    rows = []
    for pid, pts in series.items():
        pp = price_signals(pts)
        if not pp:
            continue
        c = combine(pp, products[pid], snaps.get(pid))
        sig = c["signals"]
        rows.append({"product_id": pid, "date": today, "price": pp["price"], "vs_avg": pp["vs_avg"], "momentum_14d": pp["momentum_14d"],
                     "cv_14d": pp["cv_14d"], **{f"s_{k}": sig.get(k) for k in PRICE_SIGNALS + ("reprint",) + MARKET_SIGNALS},
                     "n_positive": c["n_positive"], "n_negative": c["n_negative"], "score": c["score"]})
    if rows:
        store.upsert("card_signals", rows, "product_id,date")
    n_multi = sum(1 for r in rows if r["n_positive"] >= 3 and r["n_negative"] == 0)
    n_market = sum(1 for r in rows if r["s_aanbod"] is not None)
    log(f"Signalen: {len(rows)} kaarten beoordeeld ({len(series) - len(rows)} met te weinig geschiedenis); "
        f"{n_multi} kaarten met 3+ positieve en geen negatieve signalen; aanbod/vraag al meegeteld bij {n_market} kaarten.")
    return len(rows)


# ---------------- backtest per signaal ----------------
def backtest(store, today, horizon=30, threshold=0.10, step=5, log=print, series=None):
    """Loopt terug in de tijd: op elke 'step' dagen de prijssignalen berekenen met alleen de data tot dan, en kijken
    of de prijs daarna binnen 'horizon' dagen minstens 'threshold' hoger stond. Alleen de prijssignalen: aanbod,
    vraag en liquiditeit hebben (nog) geen geschiedenis, en reprint verandert niet in de tijd."""
    if series is None:
        products = famous_products(store)
        series = load_series(store, products, (date.fromisoformat(today) - timedelta(days=400)).isoformat())
    tally = {}

    def add(key, hit):
        n, h = tally.get(key, (0, 0))
        tally[key] = (n + 1, h + (1 if hit else 0))

    for pid, pts in series.items():
        for i in range(20, len(pts), step):
            d0 = date.fromisoformat(pts[i][0])
            target = (d0 + timedelta(days=horizon)).isoformat()
            later = [p for d, p in pts[i + 1:] if d <= target]
            if not later or pts[-1][0] < target:
                continue
            pp = price_signals(pts[: i + 1])
            if not pp:
                continue
            hit = max(later) >= pp["price"] * (1 + threshold)     # ergens binnen de periode minstens +threshold
            sig = pp["signals"]
            add("alle momenten", hit)
            for name, v in sig.items():
                if v:
                    add(f"{name} {'+' if v > 0 else '-'}", hit)
            npos = sum(1 for v in sig.values() if v > 0)
            nneg = sum(1 for v in sig.values() if v < 0)
            if npos >= 2 and nneg == 0:
                add("2+ positief, geen negatief", hit)
            if npos >= 3:
                add("alle 3 positief", hit)
    if not tally:
        log("Signalen-backtest: nog te weinig geschiedenis.")
        return tally
    base_n, base_h = tally["alle momenten"]
    base = base_h / base_n
    log(f"Signalen-backtest (kaarten van beroemde Pokémon): kwam er binnen {horizon} dagen een stijging van {threshold * 100:.0f}%?")
    for key in ["alle momenten"] + sorted(k for k in tally if k != "alle momenten"):
        n, h = tally[key]
        rate = h / n
        verschil = "" if key == "alle momenten" else f"   ({(rate - base) * 100:+.1f} procentpunt t.o.v. gemiddeld)"
        log(f"  {key:<30} {h:>6}/{n:<6} = {rate * 100:5.1f}%{verschil}")
    return tally


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--skip-snapshot", action="store_true")
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today().isoformat()
    if not args.skip_snapshot:
        import market_snapshot
        ppt = None
        if os.environ.get("PPT_API_KEY"):
            from ppt import PPT
            ppt = PPT(os.environ["PPT_API_KEY"])
        try:
            market_snapshot.run(store, ppt, today, deadline=time.time() + config.SNAPSHOT_MAX_MINUTES * 60)
        except Exception as e:   # de signalen zelf kunnen ook zonder de momentopname van vandaag
            print(f"! marktmomentopname mislukt: {type(e).__name__}: {e}")
    compute_today(store, today)
    if args.backtest:
        backtest(store, today)


if __name__ == "__main__":
    main()
