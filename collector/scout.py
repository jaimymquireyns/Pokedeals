"""Los scouten: aanbiedingen ophalen voor de kaarten met een levendige markt (offers.liquid_ids), zonder op de dagelijkse update
te wachten. Kaarten die nog niet aan PkmnPrices gekoppeld zijn, worden eerst gekoppeld (nodig voor de aanbiedingen).

    python scout.py --budget 36000 --minutes 50
"""
import argparse
import os
import time
from datetime import date

import config
import nm
import offers
from pkmnprices import PkmnPrices
from store import SupabaseStore


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=config.DEALS_BUDGET)
    ap.add_argument("--minutes", type=int, default=50)
    ap.add_argument("--n", type=int, default=config.SCOUT_N)
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    pk = PkmnPrices(os.environ["PKMN_API_KEY"], budget=args.budget)
    today = date.today().isoformat()
    deadline = time.time() + args.minutes * 60
    targets = offers.liquid_ids(store, today)[:args.n]
    cards = {p["product_id"]: p for p in store.products("card")}
    unmapped = [pid for pid in targets if pid in cards and not cards[pid].get("pk_id")]
    print(f"Scouten: {len(targets)} kaarten met een levendige markt, {len(unmapped)} nog niet gekoppeld aan PkmnPrices.")
    if unmapped:
        # eerst de aanbiedingen van wat al gekoppeld is (goedkoper), daarna koppelen met wat er overblijft
        offers.run(store, pk, today, deadline=deadline, only=targets)
        nm._map_and_refresh(store, pk, today, unmapped, {pid: cards[pid] for pid in unmapped}, print, deadline=deadline, refresh_price=False)
    offers.run(store, pk, today, deadline=deadline, only=targets)
    print(f"Klaar: {pk.credits} credits gebruikt.")


if __name__ == "__main__":
    import traceback
    os.makedirs("../reports", exist_ok=True)
    try:
        main()
        msg = "ok"
    except Exception:
        msg = traceback.format_exc()
        print(msg)
    with open("../reports/scout.md", "w") as f:
        f.write(f"# Scouten {date.today().isoformat()}\n\n```\n{msg}\n```\n")
    if msg != "ok":
        raise SystemExit(1)
