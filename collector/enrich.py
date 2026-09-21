"""Verrijkt onze sealed producten (uit de Cardmarket-prijslijst) met plaatjes en setnamen van PkmnPrices (Pro).

Eenmalig draaien (en af en toe opnieuw voor nieuwe producten). Hervatbaar: producten die al gekoppeld zijn worden overgeslagen.
    python enrich.py --sealed
PkmnPrices rekent één credit per teruggegeven rij. Ongeveer 6.000 producten in de lijst plus 6.000 detailverzoeken.
"""
import argparse
import os

from pkmnprices import PkmnPrices
from store import SupabaseStore


def enrich_sealed(store, pk, log=print):
    ours = {}
    for p in store.products("sealed"):
        if p["product_id"].startswith("cm:"):
            ours[int(p["product_id"].split(":")[1])] = p
    done_pk = {str(p["pk_id"]) for p in ours.values() if p.get("pk_id")}
    log(f"{len(ours)} sealed producten in de database, {len(done_pk)} al gekoppeld")

    items = pk.list_all("/sealed", per_page=100)
    log(f"{len(items)} sealed producten bij PkmnPrices ({pk.credits} credits)")
    matched = skipped = 0
    batch = []
    for it in items:
        if pk.over_budget():
            log(f"Credit-budget bereikt ({pk.credits}). Draai later opnieuw; er wordt verdergegaan waar hij was.")
            break
        pid = str(it.get("id"))
        if pid in done_pk:
            continue
        try:
            d = pk.detail(f"/sealed/{pid}")
        except Exception as e:
            log(f"  {pid}: {e}")
            continue
        cm = d.get("cardmarket_product_id")
        mine = ours.get(int(cm)) if cm else None
        if not mine:
            skipped += 1
            continue
        st = d.get("set") or it.get("set") or {}
        batch.append({"product_id": mine["product_id"], "kind": "sealed", "name": mine["name"],
                      "image": d.get("image_url") or it.get("image_url") or mine.get("image"),
                      "set_name": st.get("name") or mine.get("set_name"), "pk_id": pid})
        matched += 1
        if len(batch) >= 100:
            store.upsert_products(batch)
            batch.clear()
            log(f"  {matched} gekoppeld ({pk.credits} credits)")
    if batch:
        store.upsert_products(batch)
    log(f"Klaar: {matched} producten voorzien van plaatje en setnaam, {skipped} zonder Cardmarket-koppeling; {pk.credits} credits")
    return matched


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sealed", action="store_true")
    ap.add_argument("--max-credits", type=int, default=15000)
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    pk = PkmnPrices(os.environ["PKMN_API_KEY"], budget=args.max_credits)
    if args.sealed:
        enrich_sealed(store, pk)
    else:
        ap.error("kies --sealed")


if __name__ == "__main__":
    main()
