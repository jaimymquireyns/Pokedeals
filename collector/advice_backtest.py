"""Terugtest van het advies op de Near Mint-geschiedenis (PkmnPrices): hoe vaak klopte 'ver onder normaal -> herstelt' en
'ver boven normaal -> zakt terug' in het verleden? De uitkomst gaat naar advice_stats (bron 'backtest'), waar de app het
kansbalkje op afstelt zolang er nog te weinig echte (live) uitkomsten zijn.

Zelfde regels als assess_nm in advice.py, dag per dag nagespeeld zonder in de toekomst te kijken:
  normaal = mediaan van de Near Mint-prijs over 90 dagen, zonder de laatste week (pieken eruit, zie analysis.clean_nm_rows)
  laag    = de hele laatste week minstens 20% onder normaal;  hoog = de hele week minstens 25% erboven
Uitkomst na 30 dagen (ADVICE_HORIZON_DAYS):
  laag: kopen tegen de prijs van toen plus verzending, verkopen na 30 dagen. Omdat dit vraagprijzen zijn en je bij verkopen
        meestal iets onder de vraagprijs zit, rekenen we voorzichtig met 90% van de latere vraagprijs, min commissie en
        verpakking. Klopte als er dan winst is.
  hoog: klopte als de prijs na 30 dagen lager staat (verkopen was dus beter dan houden).
  controle: willekeurige gewone momenten (niet laag of hoog) van kaarten vanaf ADVICE_MIN_BUY, gekocht zoals bij 'laag'.
Eén signaal per kaart per 28 dagen, zodat een kaart die lang laag staat niet tientallen keren meetelt.

Wat dit niet kan: de geschiedenis bevat vraagprijzen, geen verkopen, dus de controle 'bevestigen echte verkopen het?' en de
controles op manipulatie kunnen we niet naspelen. Dit meet het basisidee, niet het volledige advies.

    python advice_backtest.py --out ../reports/advice_backtest.md
"""
import argparse
import os
import zlib
from datetime import date, timedelta
from statistics import median

import analysis
import config
from store import SupabaseStore

SELL_HAIRCUT = 0.90   # je verkoopt meestal iets onder de laagste vraagprijs
STEP_DAYS = 7
GAP_DAYS = 28


def _d(s):
    return date.fromisoformat(str(s)[:10])


def depth_key(ratio):
    return "laag_diep" if ratio <= 0.65 else "laag_mild"


def age_key(age_days):
    if age_days is None:
        return None
    return "laag_jong" if age_days < config.ADVICE_YOUNG_SET_DAYS else "laag_oud"


def signals(points, release=None, fee_pct=None):
    """points: [(datum, prijs)] van één kaart, opgeschoond en gesorteerd. Geeft [(sleutels, klopte, rendement)]."""
    fee = config.DEFAULT_FEE_PCT if fee_pct is None else fee_pct
    if len(points) < 40:
        return []
    days = [_d(d) for d, _ in points]
    out, last_sig = [], {}
    t = days[0] + timedelta(days=config.ADVICE_NORMAL_DAYS + 7)
    end = days[-1] - timedelta(days=config.ADVICE_HORIZON_DAYS)
    while t <= end:
        win = [p for d, p in zip(days, (x[1] for x in points)) if t - timedelta(days=config.ADVICE_NORMAL_DAYS) <= d < t - timedelta(days=config.ADVICE_CONFIRM_DAYS)]
        rec = [p for d, p in zip(days, (x[1] for x in points)) if t - timedelta(days=config.ADVICE_CONFIRM_DAYS) < d <= t]
        if len(win) >= config.ADVICE_MIN_NM_POINTS and len(rec) >= config.ADVICE_MIN_RECENT:
            normal, price = median(win), rec[-1]
            target = t + timedelta(days=config.ADVICE_HORIZON_DAYS)
            later = next((p for d, p in zip(days, (x[1] for x in points)) if target <= d <= target + timedelta(days=7)), None)
            ratio = median(rec) / normal
            if later and 1 / config.ADVICE_MAX_RATIO <= ratio <= config.ADVICE_MAX_RATIO:
                age = (t - release).days if release else None
                cost = price + config.ship_cost(price)
                buy_ret = (later * SELL_HAIRCUT * (1 - fee / 100) - config.PACKAGING - cost) / cost
                gain = (normal * (1 - fee / 100) - config.PACKAGING - cost) / cost   # wat herstel tot normaal zou opleveren
                if all(p <= config.ADVICE_LOW * normal for p in rec) and price >= config.ADVICE_MIN_BUY and gain >= config.ADVICE_BUY_GAIN:
                    keys = ["laag", depth_key(ratio)] + ([age_key(age)] if age_key(age) else [])
                    if (t - last_sig.get("laag", date.min)).days >= GAP_DAYS:
                        out.append((keys, buy_ret > 0, buy_ret)); last_sig["laag"] = t
                elif all(p >= config.ADVICE_HIGH * normal for p in rec):
                    if (t - last_sig.get("hoog", date.min)).days >= GAP_DAYS:
                        out.append((["hoog"], later < price, later / price - 1)); last_sig["hoog"] = t
                elif price >= config.ADVICE_MIN_BUY and zlib.crc32(f"{price}|{t}".encode()) % 4 == 0:   # steekproef van gewone momenten
                    if (t - last_sig.get("controle", date.min)).days >= GAP_DAYS:
                        out.append((["controle"], buy_ret > 0, buy_ret)); last_sig["controle"] = t
        t += timedelta(days=STEP_DAYS)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/advice_backtest.md")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today().isoformat()
    sets = {s["set_id"]: s for s in store.select("sets", {"select": "set_id,release_date"})}
    prods = {p["product_id"]: p for p in store.select("products", {"select": "product_id,set_id,kind", "kind": "eq.card"})}
    # alleen kaarten met lange genoeg geschiedenis: eerst kijken wie een punt heeft van minstens 130 dagen geleden
    cutoff = (date.today() - timedelta(days=config.ADVICE_NORMAL_DAYS + config.ADVICE_HORIZON_DAYS + 10)).isoformat()
    ids = sorted({r["product_id"] for r in store.select("prices", {"select": "product_id", "source": "eq.pkmnprices", "grade_key": "eq.nm",
                                                                    "date": f"lt.{cutoff}", "order": "product_id.asc"})} & set(prods))
    print(f"{len(ids)} kaarten met Near Mint-geschiedenis van voor {cutoff}")
    res = {}
    n_cards = 0
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        rows = {}
        for r in store.select("prices", {"select": "product_id,date,price", "source": "eq.pkmnprices", "grade_key": "eq.nm",
                                         "product_id": f"in.({','.join(chunk)})", "order": "product_id.asc,date.asc"}):
            if r.get("price") and float(r["price"]) > 0:
                rows.setdefault(r["product_id"], []).append({"date": str(r["date"])[:10], "price": float(r["price"])})
        for pid, pts in rows.items():
            kept, _ = analysis.clean_nm_rows(pts)
            st = sets.get(prods[pid].get("set_id")) or {}
            rel = _d(st["release_date"]) if st.get("release_date") else None
            sig = signals([(r["date"], r["price"]) for r in kept], rel)
            n_cards += bool(sig)
            for keys, ok, ret in sig:
                for k in keys:
                    res.setdefault(k, []).append((ok, ret))
    keys = ["laag", "laag_diep", "laag_mild", "laag_jong", "laag_oud", "hoog", "controle"]
    stats = []
    for k in keys:
        xs = res.get(k, [])
        n, hits = len(xs), sum(1 for ok, _ in xs if ok)
        stats.append({"source": "backtest", "state": k, "n": n, "hits": hits, "avg_ret": round(sum(r for _, r in xs) / n, 4) if n else None, "updated": today})
    names = {"laag": "Good buy (ver onder normaal)", "laag_diep": "  waarvan diep (35%+ onder normaal)", "laag_mild": "  waarvan mild (20-35% onder)",
             "laag_jong": "  waarvan set jonger dan 6 maanden", "laag_oud": "  waarvan set ouder dan 6 maanden",
             "hoog": "Sell now (ver boven normaal: zakte daarna)", "controle": "Toeval: willekeurige kaarten gekocht"}
    lines = [f"# Terugtest advies op Near Mint-geschiedenis ({today})", "",
             f"{len(ids)} kaarten met genoeg geschiedenis, {n_cards} daarvan gaven minstens één signaal. Uitkomst na {config.ADVICE_HORIZON_DAYS} dagen, "
             f"verkoop voorzichtig gerekend op {SELL_HAIRCUT:.0%} van de latere vraagprijs, min commissie, verpakking en verzending bij aankoop.", "",
             "| advies | aantal | klopte | gemiddeld rendement |", "|---|---|---|---|"]
    for s in stats:
        pct = f"{s['hits'] / s['n']:.0%}" if s["n"] else "–"
        avg = f"{s['avg_ret'] * 100:+.1f}%" if s["avg_ret"] is not None else "–"
        lines.append(f"| {names[s['state']]} | {s['n']} | {pct} | {avg} |")
    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(text)
    print(text)
    if not args.no_save:
        store.upsert("advice_stats", stats, "source,state")


if __name__ == "__main__":
    main()
