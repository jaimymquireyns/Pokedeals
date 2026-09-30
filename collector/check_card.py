"""Diagnose: laat zien wat er bij PkmnPrices achter de koppeling (pk_id) van een kaart zit, om te controleren of
die koppeling klopt. Ontstaan uit een vreemde prijssprong bij ecard3-71 (Lapras, Skyridge): staat de koppeling
misschien op de verkeerde kaart?

    python check_card.py ecard3-71
    python check_card.py ecard3-71 lc-64 hgss4-18   # meerdere tegelijk

Nodig: SUPABASE_URL, SUPABASE_SECRET_KEY, PKMN_API_KEY.
"""
import argparse
import os

from pkmnprices import PkmnPrices
from store import SupabaseStore


def check(store, pk, product_id, log=print):
    rows = store.products("card", extra={"product_id": f"eq.{product_id}"})
    if not rows:
        log(f"{product_id}: onbekend in onze eigen database.")
        return
    p = rows[0]
    log(f"\n=== {product_id} ===")
    log(f"  bij ons:        {p.get('name')} — {p.get('set_name')} #{p.get('number')} (dex {p.get('dex_id')})")
    if not p.get("pk_id"):
        log("  nog niet gekoppeld aan PkmnPrices.")
        return
    log(f"  pk_id:          {p['pk_id']}")
    try:
        card = pk.call(f"/cards/{p['pk_id']}")
    except Exception as e:
        log(f"  ! kon PkmnPrices niet raadplegen: {e}")
        return
    name = card.get("name") or card.get("card_name")
    setinfo = card.get("set") if isinstance(card.get("set"), dict) else {}
    set_name = setinfo.get("name") or card.get("set_name")
    number = card.get("number") or card.get("card_number")
    log(f"  bij PkmnPrices: {name} — {set_name} #{number}")
    ok = (name or "").strip().lower() == (p.get("name") or "").strip().lower()
    log("  --> lijkt te KLOPPEN (zelfde naam)" if ok else "  --> LIJKT NIET TE KLOPPEN: andere naam dan bij ons!")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("product_ids", nargs="+", help="een of meer product_id's uit onze eigen database, bijv. ecard3-71")
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    pk = PkmnPrices(os.environ["PKMN_API_KEY"])
    for pid in args.product_ids:
        check(store, pk, pid)
    print(f"\n({pk.credits} credits gebruikt)")


if __name__ == "__main__":
    main()
