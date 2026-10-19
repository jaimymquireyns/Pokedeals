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
import market_value
from store import SupabaseStore

SELL_HAIRCUT = 0.90   # oude aanname (onder de laagste vraagprijs verkopen); alleen nog als er geen aanbiedingen bekend zijn
SELL_ABOVE = 1.00     # de gebruiker verkoopt rond EUR 1 boven de 10e goedkoopste aanbieding
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


PRICE_BANDS = [(10, 25), (25, 50), (50, 100), (100, 250), (250, None)]


def band_key(price):
    for lo, hi in PRICE_BANDS:
        if price >= lo and (hi is None or price < hi):
            return f"EUR {lo}-{hi}" if hi else f"EUR {lo}+"
    return f"onder EUR {PRICE_BANDS[0][0]}"


def sell_price(later, ratio):
    """Verkoopprijs na 30 dagen: met een verhouding 10e/goedkoopste wordt dat later x verhouding + EUR 1, anders de oude 90%."""
    return later * ratio + SELL_ABOVE if ratio else later * SELL_HAIRCUT


def signals(points, release=None, fee_pct=None, detail=None, sell_ratio=None):
    """points: [(datum, prijs)] van één kaart, opgeschoond en gesorteerd. Geeft [(sleutels, klopte, rendement)].
    detail: optionele lijst; per signaal komt er (soort, prijs, kale prijsverandering, rendement na kosten, klopte) bij."""
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
                buy_ret = (sell_price(later, sell_ratio) * (1 - fee / 100) - config.PACKAGING - cost) / cost
                gain = (normal * (1 - fee / 100) - config.PACKAGING - cost) / cost   # wat herstel tot normaal zou opleveren
                if all(p <= config.ADVICE_LOW * normal for p in rec) and price >= config.ADVICE_MIN_BUY and gain >= config.ADVICE_BUY_GAIN:
                    keys = ["laag", depth_key(ratio)] + ([age_key(age)] if age_key(age) else [])
                    if (t - last_sig.get("laag", date.min)).days >= GAP_DAYS:
                        out.append((keys, buy_ret > 0, buy_ret)); last_sig["laag"] = t
                        if detail is not None:
                            detail.append(("laag", price, later / price - 1, buy_ret, buy_ret > 0))
                elif all(p >= config.ADVICE_HIGH * normal for p in rec):
                    if (t - last_sig.get("hoog", date.min)).days >= GAP_DAYS:
                        out.append((["hoog"], later < price, later / price - 1)); last_sig["hoog"] = t
                        if detail is not None:
                            detail.append(("hoog", price, later / price - 1, later / price - 1, later < price))
                elif price >= config.ADVICE_MIN_BUY and zlib.crc32(f"{price}|{t}".encode()) % 4 == 0:   # steekproef van gewone momenten
                    if (t - last_sig.get("controle", date.min)).days >= GAP_DAYS:
                        out.append((["controle"], buy_ret > 0, buy_ret)); last_sig["controle"] = t
                        if detail is not None:
                            detail.append(("controle", price, later / price - 1, buy_ret, buy_ret > 0))
        t += timedelta(days=STEP_DAYS)
    return out


def band_report(detail):
    """Per prijsklasse: werkt het signaal zelf (kale prijsverandering), en blijft er na kosten iets over?"""
    def cell(xs, i):
        return f"{sum(x[i] for x in xs) / len(xs) * 100:+.1f}%" if xs else "–"
    out = ["", "## Per prijsklasse (prijs op het moment van het signaal)", "",
           "Kale verandering = de vraagprijs 30 dagen later tegen die van toen, zonder kosten. Na kosten = zoals hierboven. "
           "Toont Good buy een betere kale verandering dan Toeval, dan werkt het signaal; is het na kosten toch negatief, dan eten de kosten het op.", "",
           "| prijsklasse | Good buy: aantal | klopte | kaal | na kosten | Toeval: aantal | klopte | kaal | na kosten | Sell now: aantal | klopte | kaal |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    bands = [band_key(0)] + [band_key(lo) for lo, _ in PRICE_BANDS]
    for b in bands:
        row = [b]
        for kind in ("laag", "controle", "hoog"):
            xs = [x for x in detail if x[0] == kind and band_key(x[1]) == b]
            hit = f"{sum(1 for x in xs if x[4]) / len(xs):.0%}" if xs else "–"
            row += [str(len(xs)), hit, cell(xs, 2)] + ([] if kind == "hoog" else [cell(xs, 3)])
        if any(c not in ("0", "–") for c in row[1:]):
            out.append("| " + " | ".join(row) + " |")
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
    # verkoopprijs: hoe ver ligt de 10e goedkoopste aanbieding boven de goedkoopste? Per kaart uit de huidige aanbiedingen,
    # anders de mediaan van zijn prijsklasse (de spreiding van nu, toegepast op het verleden: een benadering)
    own = [r.get("cm_name") for r in store.select("user_settings", {"select": "cm_name", "cm_name": "not.is.null"})]
    offs = {}
    for o in store.select("offers", {"select": "product_id,rank,price,seller,language,variant", "order": "product_id.asc,rank.asc"}):
        offs.setdefault(o["product_id"], []).append(o)
    ratios = {pid: r for pid, o in offs.items() if (r := market_value.tenth_ratio(o, own))}
    band_vals = {}
    for pid, r in ratios.items():
        lo = min(float(o["price"]) for o in offs[pid])
        band_vals.setdefault(band_key(lo), []).append(r)
    band_ratio = {b: median(v) for b, v in band_vals.items() if len(v) >= 5}
    all_ratio = median(ratios.values()) if ratios else None
    print(f"10e/goedkoopste: {len(ratios)} kaarten met aanbiedingen; per prijsklasse " +
          ", ".join(f"{b} x{r:.2f}" for b, r in sorted(band_ratio.items())))
    res = {}
    detail = []
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
            last_price = kept[-1]["price"] if kept else 0
            ratio = ratios.get(pid) or band_ratio.get(band_key(last_price)) or all_ratio
            sig = signals([(r["date"], r["price"]) for r in kept], rel, detail=detail, sell_ratio=ratio)
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
             f"Verkoop gerekend op EUR {SELL_ABOVE:.0f} boven de 10e goedkoopste aanbieding (de 10e ligt nu gemiddeld "
             f"x{all_ratio or 0:.2f} boven de goedkoopste), min commissie en verpakking; aankoop plus verzending.", "",
             "| advies | aantal | klopte | gemiddeld rendement |", "|---|---|---|---|"]
    for s in stats:
        pct = f"{s['hits'] / s['n']:.0%}" if s["n"] else "–"
        avg = f"{s['avg_ret'] * 100:+.1f}%" if s["avg_ret"] is not None else "–"
        lines.append(f"| {names[s['state']]} | {s['n']} | {pct} | {avg} |")
    lines += band_report(detail)
    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(text)
    print(text)
    if not args.no_save:
        store.upsert("advice_stats", stats, "source,state")


if __name__ == "__main__":
    main()
