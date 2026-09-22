"""Eenmalig (en zo nodig herhalen): oude prijshistorie van kaarten ophalen bij PokemonPriceTracker (betaald plan)
en het model testen. Sealed komt voortaan van Cardmarket en heeft hier geen historie.

    python backfill.py --cards-sets 12          # historie voor kaarten uit de 12 nieuwste sets
    python backfill.py --backtest               # test het model op de historie en vul het trackrecord
Alles is hervatbaar: draai het gerust opnieuw als het budget van een dag op is.
"""
import argparse
import os
from datetime import date

import config
import run
from ppt import PPT, clean_card_name, norm, norm_number
from providers import TCGdex
from store import SupabaseStore


def history_rows(pid, points, fx, source, today):
    return [{"product_id": pid, "date": d, "source": source, "grade_key": "raw", "price": round(p * fx, 4),
             "native": p, "currency": "USD"} for d, p in points if d <= today]


def find_ppt_set(tcg_set, ppt_sets):
    """Zoekt de PPT-set bij een TCGdex-set. PPT noemt sets bijv. 'SV03: Obsidian Flames' of 'XY - Roaring Skies'."""
    n = norm(tcg_set["name"])
    exact = [s for s in ppt_sets if norm(s["name"]) == n]
    if exact:
        return exact[0]
    part = [s for s in ppt_sets if n and (n in norm(s["name"]) or norm(s["name"]) in n)]
    return min(part, key=lambda s: len(norm(s["name"]))) if part else None


def backfill_cards(ppt, store, today, fx, n_sets, days=None, log=print):
    days = days or config.PPT_HISTORY_DAYS
    tcg_sets = sorted([s for s in store.known_sets().values() if s.get("release_date")],
                      key=lambda s: s["release_date"], reverse=True)[:n_sets]
    ppt_sets = ppt.sets()
    matched = unmatched = 0
    for ts in tcg_sets:
        if ppt.over_budget():
            log(f"Budget bereikt ({ppt.credits} credits). Draai later opnieuw.")
            break
        ps = find_ppt_set(ts, ppt_sets)
        if not ps:
            log(f"  geen PPT-set gevonden voor {ts['name']}")
            continue
        index = {}
        for p in store.products("card", {"set_id": f"eq.{ts['set_id']}"}):
            index.setdefault(norm_number(p["number"]), []).append(p)
        items = ppt.cards_in_set(ps["set_id"], history_days=days)
        prods, hist = [], []
        for it in items:
            name = norm(clean_card_name(it["name"]))
            p = next((c for c in index.get(norm_number(it["number"]), []) if norm(c["name"]) == name or (name and (norm(c["name"]) in name or name in norm(c["name"])))), None)
            if not p or not it["ppt_id"]:
                unmatched += 1
                continue
            matched += 1
            prods.append({"product_id": p["product_id"], "kind": "card", "name": p["name"], "ppt_id": it["ppt_id"]})
            hist += history_rows(p["product_id"], it["history"], fx, "ppt_hist", today)
        if prods:
            store.upsert_products(prods)
        if hist:
            store.upsert_prices(hist)
        log(f"{ts['name']}: {len(prods)} kaarten gekoppeld, {len(hist)} historiepunten")
    log(f"Koppeling: {matched} gekoppeld, {unmatched} niet gevonden; {ppt.credits} credits")
    return matched


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sealed", action="store_true")
    ap.add_argument("--cards-sets", type=int)
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--days", type=int, default=config.PPT_HISTORY_DAYS)
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today().isoformat()
    if args.sealed:
        from pkmnprices import PkmnPrices
        if not os.environ.get("PKMN_API_KEY"):
            print("Sealed-geschiedenis heeft PKMN_API_KEY nodig (PkmnPrices); overgeslagen.")
        else:
            import sealed_history
            sealed_history.run(store, PkmnPrices(os.environ["PKMN_API_KEY"]), today, limit=10_000)
    if args.cards_sets:
        import fx as fxmod
        rate, _ = fxmod.usd_to_eur(TCGdex().session)
        backfill_cards(PPT(os.environ["PPT_API_KEY"]), store, today, rate, args.cards_sets, args.days)
    if args.backtest:
        import trackrecord
        trackrecord.backtest(store, today)
    run.build_forecasts(store, today)


if __name__ == "__main__":
    main()
