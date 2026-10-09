"""Hoe verlopen de prijzen van kaarten na het uitkomen van hun set? Analyse, niets wordt opgeslagen behalve het verslag.

Per kaart nemen we de langste prijsreeks die we hebben (TCGplayer-historie, Near Mint van PkmnPrices of Cardmarket) en
zetten de prijs uit tegen de leeftijd van de set (dagen sinds de release). Omdat niet elke kaart elke leeftijd beslaat,
rekenen we per stap: de mediaan van (prijs in leeftijdsvak k / prijs in vak k-1) over alle kaarten die beide vakken
hebben. Die stappen vermenigvuldigd geven een index (100 = de prijs in de eerste twee weken).

Tegen 'de hele markt beweegt' corrigeren we met oude sets (ouder dan 2 jaar) als ijkpunt: per kalendermaand hun
mediane prijsverandering. De gecorrigeerde curve laat zien wat de leeftijd van de set zelf doet.

Uitsplitsingen: prijsklasse (prijs rond 1 maand na release) en soort kaart (jachtkaarten zoals Illustration Rares en
Special Illustration Rares tegenover gewone holo's en ex'en).

    python set_lifecycle.py --out ../reports/set_lifecycle.md
"""
import argparse
import os
from datetime import date, timedelta
from statistics import median

from store import SupabaseStore

BUCKETS = [(0, 14), (14, 30), (30, 60), (60, 90), (90, 120), (120, 180), (180, 270), (270, 365), (365, 540), (540, 730), (730, 1100)]
LABEL = ["0-2 wk", "2-4 wk", "1-2 mnd", "2-3 mnd", "3-4 mnd", "4-6 mnd", "6-9 mnd", "9-12 mnd", "12-18 mnd", "18-24 mnd", "2-3 jaar"]
SOURCES = ("tcgplayer", "ppt", "pkmnprices", "tcgdex", "cardmarket")   # bij gelijke lengte telt de volgorde
CHASE = ("special illustration", "illustration rare", "hyper", "secret", "gold", "rainbow", "alternate", "shiny", "character")
MIN_PRICE = 2.0


def _d(s):
    return date.fromisoformat(str(s)[:10])


def bucket_of(age):
    for i, (a, b) in enumerate(BUCKETS):
        if a <= age < b:
            return i
    return None


def tier_of(p):
    return "< €5" if p < 5 else "€5-20" if p < 20 else "€20-100" if p < 100 else "> €100"


def kind_of(rarity):
    r = (rarity or "").lower()
    return "jachtkaart" if any(k in r for k in CHASE) else "gewoon"


def best_series(rows):
    """rows: [{date, source, grade_key, price}] van één kaart. Kiest de bron met de langste reeks (raw, of nm bij PkmnPrices)."""
    by = {}
    for r in rows:
        src = r["source"]
        if src == "pkmnprices" and r["grade_key"] != "nm":
            continue
        if src != "pkmnprices" and r["grade_key"] != "raw":
            continue
        p = r.get("price")
        if p is None or float(p) <= 0:
            continue
        by.setdefault(src, []).append((str(r["date"])[:10], float(p)))
    if not by:
        return None, []
    def span(src):
        xs = by[src]
        return (_d(max(x[0] for x in xs)) - _d(min(x[0] for x in xs))).days
    src = max(by, key=lambda s: (span(s), -SOURCES.index(s) if s in SOURCES else -99))
    return src, sorted(by[src])


def per_bucket(series, release):
    vals = {}
    for d, p in series:
        b = bucket_of((_d(d) - release).days)
        if b is not None:
            vals.setdefault(b, []).append(p)
    return {b: median(v) for b, v in vals.items() if len(v) >= 2}


def market_index(old_series):
    """Per kalendermaand de mediane prijsverandering van kaarten uit oude sets: de beweging van de hele markt."""
    monthly = {}
    for series in old_series:
        m = {}
        for d, p in series:
            m.setdefault(d[:7], []).append(p)
        months = sorted(m)
        for a, b in zip(months, months[1:]):
            pa, pb = median(m[a]), median(m[b])
            if pa > 0:
                monthly.setdefault(b, []).append(pb / pa)
    idx, level = {}, 1.0
    for month in sorted(monthly):
        if len(monthly[month]) >= 20:
            level *= median(monthly[month])
        idx[month] = level
    return idx


def curve(cards, adjust=None):
    """cards: [(bucketprijzen, release)]. Geeft (index per vak, aantal kaarten per stap)."""
    steps, ns = [1.0], [None]
    for k in range(1, len(BUCKETS)):
        ratios = []
        for bp, release in cards:
            if k in bp and k - 1 in bp and bp[k - 1] > 0:
                r = bp[k] / bp[k - 1]
                if adjust:
                    mid = lambda i: (release + timedelta(days=(BUCKETS[i][0] + BUCKETS[i][1]) // 2)).isoformat()[:7]
                    a, b = adjust.get(mid(k - 1)), adjust.get(mid(k))
                    if a and b:
                        r /= b / a
                if 0.1 < r < 10:
                    ratios.append(r)
        if len(ratios) >= 15:
            steps.append(median(ratios)); ns.append(len(ratios))
        else:
            steps.append(None); ns.append(len(ratios))
    idx, level, out = [], 100.0, []
    for s in steps:
        if s is None:
            out.append(None)
            continue
        level *= s
        out.append(level)
    return out, ns


def fmt_curve(name, c, ns):
    cells = []
    for i, v in enumerate(c):
        cells.append("–" if v is None else f"{v:.0f}")
    low = min((v, i) for i, v in enumerate(c) if v is not None)
    n_txt = max((n for n in ns if n), default=0)
    return f"| {name} | " + " | ".join(cells) + f" | {LABEL[low[1]]} | {n_txt} |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/set_lifecycle.md")
    ap.add_argument("--years", type=float, default=3.0)
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today()
    sets = {s["set_id"]: s for s in store.select("sets", {"select": "set_id,name,release_date"}) if s.get("release_date")}
    young = {sid for sid, s in sets.items() if (today - _d(s["release_date"])).days <= args.years * 365}
    old = {sid for sid, s in sets.items() if (today - _d(s["release_date"])).days > 730}
    products = [p for p in store.select("products", {"select": "product_id,set_id,rarity,kind,name", "kind": "eq.card"}) if p.get("set_id") in young | old]
    print(f"{len(young)} jonge sets, {len(old)} oude sets, {len(products)} kaarten")
    by_pid = {p["product_id"]: p for p in products}
    rows = {}
    ids = sorted(by_pid)
    for i in range(0, len(ids), 40):
        chunk = ids[i:i + 40]
        for r in store.select("prices", {"select": "product_id,date,source,grade_key,price", "product_id": f"in.({','.join(chunk)})",
                                         "grade_key": "in.(raw,nm)", "order": "product_id.asc,date.asc"}):
            rows.setdefault(r["product_id"], []).append(r)
        if i % 2000 == 0:
            print(f"  prijzen geladen voor {i + len(chunk)} van {len(ids)} kaarten")
    src_count, cards, old_series = {}, [], []
    for pid, rs in rows.items():
        p = by_pid[pid]
        src, series = best_series(rs)
        if not series or max(x[1] for x in series) < MIN_PRICE:
            continue
        src_count[src] = src_count.get(src, 0) + 1
        if p["set_id"] in old:
            old_series.append(series)
            continue
        release = _d(sets[p["set_id"]]["release_date"])
        bp = per_bucket(series, release)
        if len(bp) < 2:
            continue
        ref = bp.get(2) or bp.get(1) or bp.get(3)
        cards.append({"bp": bp, "release": release, "tier": tier_of(ref) if ref else None, "kind": kind_of(p.get("rarity")), "set": p["set_id"]})
    mkt = market_index(old_series)
    print(f"{len(cards)} kaarten uit jonge sets met genoeg prijzen; bronnen {src_count}; marktindex over {len(mkt)} maanden")

    head = "| groep | " + " | ".join(LABEL) + " | laagste punt | kaarten |\n|" + "---|" * (len(LABEL) + 3)
    lines = [f"# Prijsverloop na de release van een set ({today.isoformat()})", "",
             f"{len(cards)} kaarten uit {len({c['set'] for c in cards})} sets van de laatste {args.years:g} jaar; bronnen: {src_count}.",
             "Index: 100 = de prijs in de eerste 2 weken na de release. 'Gecorrigeerd' haalt de beweging van de hele markt eruit (oude sets als ijkpunt).", ""]
    for title, adj in (("Ruw", None), ("Gecorrigeerd voor de hele markt", mkt)):
        lines += [f"## {title}", "", head]
        allc = [(c["bp"], c["release"]) for c in cards]
        c, ns = curve(allc, adj); lines.append(fmt_curve("alle kaarten", c, ns))
        for kind in ("jachtkaart", "gewoon"):
            sub = [(x["bp"], x["release"]) for x in cards if x["kind"] == kind]
            c, ns = curve(sub, adj)
            if any(v is not None for v in c[1:]):
                lines.append(fmt_curve(kind, c, ns))
        for tier in ("< €5", "€5-20", "€20-100", "> €100"):
            sub = [(x["bp"], x["release"]) for x in cards if x["tier"] == tier]
            c, ns = curve(sub, adj)
            if any(v is not None for v in c[1:]):
                lines.append(fmt_curve(tier, c, ns))
        lines.append("")
    lines += ["## Per set (ruw)", "", head]
    for sid in sorted({c["set"] for c in cards}, key=lambda s: sets[s]["release_date"]):
        sub = [(x["bp"], x["release"]) for x in cards if x["set"] == sid]
        c, ns = curve(sub)
        if any(v is not None for v in c[1:]):
            lines.append(fmt_curve(f"{sets[sid]['name']} ({sets[sid]['release_date']})", c, ns))
    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
