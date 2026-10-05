"""Diagnose: laat zien wat er bij PkmnPrices achter de koppeling (pk_id) van een kaart zit, om te controleren of
die koppeling klopt. Ontstaan uit een vreemde prijssprong bij ecard3-71 (Lapras, Skyridge): staat de koppeling
misschien op de verkeerde kaart?

    python check_card.py ecard3-71
    python check_card.py ecard3-71 lc-64 hgss4-18   # meerdere tegelijk
    python check_card.py ecard3-71 --no-listings    # alleen de koppeling controleren, geen aanbiedingen opvragen

Na de koppeling laat het ook zien waar de prijs vandaan komt, om te beoordelen of die betrouwbaar is:
  - onze eigen Near Mint-reeks (laatste 60 dagen): hoeveel verschillende waarden, en hoe lang de prijs vastzat
  - het verkoopgemiddelde en de laagste prijs van Cardmarket zelf (gratis dagelijkse bestand)
  - de goedkoopste Near Mint-aanbiedingen op Cardmarket nu (via PkmnPrices; maximaal 10 credits per kaart)

Nodig: SUPABASE_URL, SUPABASE_SECRET_KEY, PKMN_API_KEY.
"""
import argparse
import os
from datetime import date, timedelta

import cm_links
from pkmnprices import PkmnPrices
from store import SupabaseStore


def check(store, pk, product_id, log=print, today=None, listings=True):
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
    url, cm_id = cm_links.extract(card)
    log(f"  Cardmarket-pagina: {url or '(geen)'}" + (f"   (product {cm_id})" if cm_id else ""))
    if not url and not cm_id:
        log(f"  velden van de kaart bij PkmnPrices: {', '.join(sorted(card)) if isinstance(card, dict) else type(card).__name__}")
    ok = (name or "").strip().lower() == (p.get("name") or "").strip().lower()
    log("  --> lijkt te KLOPPEN (zelfde naam)" if ok else "  --> LIJKT NIET TE KLOPPEN: andere naam dan bij ons!")
    try:
        inspect_prices(store, pk, product_id, p["pk_id"], today or date.today().isoformat(), listings=listings, log=log)
    except Exception as e:   # de koppelingscontrole hierboven staat er dan al; dit deel mag haar niet onderuit halen
        log(f"  ! prijsonderzoek mislukt: {type(e).__name__}: {e}")


def longest_flat_run(values):
    """Langste reeks opeenvolgende dagen met exact dezelfde prijs."""
    best = cur = 1 if values else 0
    for a, b in zip(values, values[1:]):
        cur = cur + 1 if abs(a - b) < 0.005 else 1
        best = max(best, cur)
    return best


def inspect_prices(store, pk, product_id, pk_id, today, listings=True, log=print):
    """Toont waar de prijs van een kaart vandaan komt en of die betrouwbaar lijkt. Alleen waarnemingen: wat het
    betekent beoordelen we samen."""
    since = (date.fromisoformat(today) - timedelta(days=60)).isoformat()
    nm = store.select("prices", {"select": "date,price", "product_id": f"eq.{product_id}", "grade_key": "eq.nm",
                                 "date": f"gte.{since}", "order": "date.asc"})
    vals = [float(r["price"]) for r in nm if r.get("price") is not None]
    log("  Near Mint-reeks (eigen data, laatste 60 dagen):")
    if vals:
        flat = longest_flat_run(vals)
        log(f"    {len(vals)} dagen, {len(set(round(v, 2) for v in vals))} verschillende waarden, laagste EUR{min(vals):.2f}, hoogste EUR{max(vals):.2f}, laatste EUR{vals[-1]:.2f}")
        log(f"    langste stuk met exact dezelfde prijs: {flat} dagen" + ("   <-- prijs staat vast" if flat >= 7 else ""))
    else:
        log("    geen gegevens")

    raw = store.select("prices", {"select": "date,price,avg1,avg7,avg30,low", "product_id": f"eq.{product_id}", "grade_key": "eq.raw",
                                  "source": "eq.tcgdex", "order": "date.desc", "limit": 1})
    avg7 = None
    if raw:
        r = raw[0]
        f = lambda k: (f"EUR{float(r[k]):.2f}" if r.get(k) is not None else "-")
        avg7 = float(r["avg7"]) if r.get("avg7") else None
        log(f"  Cardmarket zelf ({r['date']}): trend {f('price')}, verkocht 1 dag {f('avg1')}, 7 dagen {f('avg7')}, 30 dagen {f('avg30')}, laagste prijs {f('low')}")
    else:
        log("  Cardmarket zelf: geen gegevens")

    lowest = None
    if listings:
        try:
            data = pk.list_all(f"/cards/{pk_id}/listings/cardmarket", {"condition": "Near Mint"}, per_page=10, max_pages=1)
        except Exception as e:
            log(f"  ! aanbiedingen ophalen mislukt: {e}")
            data = []
        offers = sorted((float(x["price"]), x.get("seller"), x.get("quantity")) for x in data
                        if isinstance(x, dict) and x.get("price") and (x.get("condition") or "").lower() == "near mint")
        if offers:
            lowest = offers[0][0]
            sellers = {o[1] for o in offers if o[1]}
            log(f"  Goedkoopste Near Mint-aanbiedingen nu ({len(offers)} opgehaald, {len(sellers)} verschillende verkopers):")
            by_key = {(float(x["price"]), x.get("seller"), x.get("quantity")): x for x in data if isinstance(x, dict) and x.get("price")}
            for p, seller, qty in offers[:6]:
                extra = {k: v for k, v in by_key.get((p, seller, qty), {}).items()
                         if k not in ("price", "seller", "quantity", "condition", "id") and v not in (None, "", [], {})}
                log(f"    EUR{p:>9.2f}  {seller or '?'}" + (f"  (x{qty})" if qty else "") + (f"   {str(extra)[:140]}" if extra else ""))
            first = next((x for x in data if isinstance(x, dict)), None)
            if first:
                log(f"    velden per aanbieding: {', '.join(sorted(first))}")
            if len(sellers) <= 2:
                log("    <-- erg weinig verkopers: de laagste prijs kan door een of twee verkopers bepaald worden")
        else:
            log("  Goedkoopste Near Mint-aanbiedingen nu: geen gevonden")

    if avg7 and lowest:
        ratio = lowest / avg7
        log(f"  Laagste aanbieding is {ratio:.1f}x het verkoopgemiddelde van 7 dagen" + ("   <-- aanbod ver boven wat er echt verkocht wordt" if ratio > 3 else ""))
    if avg7 and vals:
        ratio = vals[-1] / avg7
        log(f"  Onze Near Mint-prijs is {ratio:.1f}x het verkoopgemiddelde van 7 dagen" + ("   <-- ver boven de verkopen" if ratio > 3 else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("product_ids", nargs="+", help="een of meer product_id's uit onze eigen database, bijv. ecard3-71")
    ap.add_argument("--no-listings", action="store_true", help="geen aanbiedingen opvragen (kost dan vrijwel geen credits)")
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    pk = PkmnPrices(os.environ["PKMN_API_KEY"])
    for pid in args.product_ids:
        check(store, pk, pid, listings=not args.no_listings)
    print(f"\n({pk.credits} credits gebruikt)")


if __name__ == "__main__":
    main()
