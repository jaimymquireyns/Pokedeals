"""Legt twee dingen naast elkaar, alleen voor de 65 beroemde Pokémon (config.FAMOUS_DEX_IDS):
1. De backtest (kwamen kansen ook echt uit?), zonder de echte kalibratie te overschrijven.
2. Voor de grootste prijssprongen die de backtest tegenkwam: de Google-zoekinteresse (via Scrape.do) eromheen,
   om met het blote oog te zien of interesse al meesteeg vóór zo'n sprong, of dat hij op zichzelf stond.

    python famous_analysis.py                 # standaard: top 5 sprongen, kost dus zo'n 50 credits bij Scrape.do
    python famous_analysis.py --n 10 --geo NL

Nodig: SUPABASE_URL, SUPABASE_SECRET_KEY. Voor stap 2 ook: SCRAPEDO_API_KEY (ontbreekt hij, dan wordt alleen
stap 1 gedaan).
"""
import argparse
import math
import os
from datetime import date, timedelta
from itertools import groupby

import analysis
import config
import trackrecord
import trends_probe as tp
from store import SupabaseStore


def famous_series(store, today, days=200):
    """Dezelfde opbouw als trackrecord.backtest, maar hier teruggegeven per kaart, zodat we ook zelf de grootste
    prijssprong per kaart kunnen opzoeken (dat doet backtest() zelf niet, die telt alleen kansen/uitkomsten)."""
    since = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    products = {p["product_id"]: p for p in store.products("card") if p.get("dex_id") in config.FAMOUS_DEX_IDS}
    if not products:
        return {}, {}
    rows = [r for r in store.price_rows(since) if r["product_id"] in products]
    nm_by_pid = {}
    for r in store.price_rows(since, grade_key="nm"):
        if r["product_id"] in products:
            nm_by_pid.setdefault(r["product_id"], []).append({**r, "price": float(r["price"]) if r.get("price") is not None else None})
    for pid in nm_by_pid:
        nm_by_pid[pid].sort(key=lambda r: r["date"])
    series_by_pid = {}
    for pid, grp in groupby(sorted(rows, key=lambda r: r["product_id"]), key=lambda r: r["product_id"]):
        by_source = {}
        for r in grp:
            by_source.setdefault(r["source"], []).append(
                {**r, "price": float(r["price"]) if r.get("price") is not None else None, "anchor": r.get("avg30") or r.get("avg7"),
                 "avg1": None, "avg7": None, "avg30": None})
        series_by_pid[pid] = analysis.series_for(pid, by_source, nm_rows=nm_by_pid.get(pid))
    return series_by_pid, products


def biggest_jumps(series_by_pid, products, n, min_points=config.MIN_HISTORY_POINTS + 2):
    """Voor elke kaart de grootste stap-over-30-dagen (ongeveer) in de eigen prijsreeks; de n grootste in totaal."""
    found = []
    for pid, series in series_by_pid.items():
        if len(series) < min_points:
            continue
        for i in range(min_points, len(series)):
            d0 = date.fromisoformat(series[i - 1]["date"])
            j = i
            while j < len(series) and (date.fromisoformat(series[j]["date"]) - d0).days < 30:
                j += 1
            if j >= len(series):
                continue
            p0, p1 = series[i - 1]["price"], series[j]["price"]
            if p0 and p0 >= config.MIN_PRICE:
                change = p1 / p0 - 1
                found.append((abs(change), change, pid, series[i - 1]["date"], series[j]["date"], p0, p1))
    found.sort(key=lambda x: -x[0])
    seen_pids, out = set(), []
    for _, change, pid, d0, d1, p0, p1 in found:
        if pid in seen_pids:   # per kaart maar 1x, anders domineert 1 volatiele kaart de hele top n
            continue
        seen_pids.add(pid)
        out.append({"product_id": pid, "name": products[pid]["name"], "change": change, "d0": d0, "d1": d1, "p0": p0, "p1": p1})
        if len(out) >= n:
            break
    return out


def run(store, today, n=5, geo="", log=print):
    log("=== 1. Backtest, alleen de 65 beroemde Pokémon (write=False: raakt de echte kalibratie niet aan) ===")
    famous_ids = [p["product_id"] for p in store.products("card") if p.get("dex_id") in config.FAMOUS_DEX_IDS]
    if not famous_ids:
        log("Nog geen enkele kaart van de 65 beroemde Pokémon gevonden (koppeling/geschiedenis moet nog beginnen).")
        return
    stats = trackrecord.backtest(store, today, combos=config.GRID, product_ids=famous_ids, write=False, log=log)
    if not stats:
        log("Nog te weinig geschiedenis voor een zinnige backtest. Probeer het over een paar dagen opnieuw.")

    token = os.environ.get("SCRAPEDO_API_KEY")
    if not token:
        log("\nSCRAPEDO_API_KEY ontbreekt: stap 2 (zoekinteresse naast de grootste sprongen) wordt overgeslagen.")
        return
    log(f"\n=== 2. Zoekinteresse rond de {n} grootste prijssprongen (elk ~10 credits bij Scrape.do) ===")
    series_by_pid, products = famous_series(store, today)
    jumps = biggest_jumps(series_by_pid, products, n)
    if not jumps:
        log("Geen dubbelzinnige sprongen gevonden in de huidige geschiedenis.")
        return
    for j in jumps:
        richting = "steeg" if j["change"] > 0 else "daalde"
        log(f"\n--- {j['name']} ({j['product_id']}): {richting} {abs(j['change']) * 100:.0f}% tussen {j['d0']} en {j['d1']} (EUR{j['p0']:.2f} -> EUR{j['p1']:.2f}) ---")
        data = tp.fetch(token, j["name"], "today 12-m", geo, log=log)
        if not data:
            continue
        pts = tp.extract_points(data)
        if not pts:
            log("  geen tijdreeks herkend in het antwoord")
            continue
        vals = [v for _, v in pts]
        log(f"  zoekinteresse (12 mnd, {len(vals)} punten): {tp.sparkline(vals)}  (gemiddeld {sum(vals) / len(vals):.0f} van 100)")
        window = [v for t, v in pts if j["d0"] <= t <= j["d1"]]
        before = [v for t, v in pts if t < j["d0"]][-max(2, len(pts) // 8):]
        if window and before:
            log(f"  interesse voor de sprong: gem. {sum(before) / len(before):.0f}   tijdens de sprong: gem. {sum(window) / len(window):.0f}")
        else:
            log("  (te weinig meetpunten rond dit specifieke sprongvenster om voor/tijdens te vergelijken)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=5, help="hoeveel prijssprongen (elk ~10 credits bij Scrape.do)")
    ap.add_argument("--geo", default="")
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    run(store, date.today().isoformat(), n=args.n, geo=args.geo)


if __name__ == "__main__":
    main()
