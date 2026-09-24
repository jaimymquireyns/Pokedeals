"""Historie voor sealed producten: PkmnPrices geeft per product een dagboek van Cardmarket-prijzen terug
(gezien in de test: bron 'cardmarket', euro's). Cardmarkets eigen bestand heeft dat niet, dus zonder dit
begint elk sealed product vanaf nul. Alleen mogelijk voor producten die al aan PkmnPrices gekoppeld zijn
(via enrich.py, kolom products.pk_id).
"""
import os
import time
from datetime import date, timedelta

import config

from pkmnprices import PkmnPrices
from store import SupabaseStore

BACKFILLED_ENOUGH_DAYS = 60   # ruim onder de 90 dagen die we opvragen, anders blijft een sealed product net-niet 'genoeg' hebben


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def parse_rows(product_id, data, today):
    """PkmnPrices' '/sealed/{id}/prices/history' -> prijsrijen voor de database. We nemen alleen Cardmarket/EUR
    (dezelfde bron als de dagelijkse update), en pakken 'avg' als dagprijs (er is geen 'trend' in de historie)."""
    out = []
    for d in data:
        if not isinstance(d, dict):
            continue
        if (d.get("source") or "").lower() != "cardmarket" or (d.get("currency") or "").upper() != "EUR":
            continue
        price = _num(d.get("avg") or d.get("market_price") or d.get("price"))
        dt = str(d.get("date") or "")[:10]
        if not price or not dt or dt >= today:
            continue
        out.append({"product_id": product_id, "date": dt, "source": "cardmarket", "grade_key": "raw",
                    "price": price, "low": _num(d.get("low")), "native": price, "currency": "EUR"})
    return out


def needs_backfill(store, product_id, today):
    """Al genoeg oude data? Dan hoeft dit product niet opnieuw (voorkomt dat we steeds dezelfde dagen opnieuw kopen)."""
    cutoff = (date.fromisoformat(today) - timedelta(days=BACKFILLED_ENOUGH_DAYS)).isoformat()
    rows = store.select("prices", {"select": "date", "product_id": f"eq.{product_id}", "source": "eq.cardmarket",
                                   "date": f"lt.{cutoff}", "limit": 1})
    return not rows


def run(store, pk, today, log=print, limit=10_000, deadline=None):
    """limit: zoveel sealed producten per run (elke dag opnieuw, tot alles is bijgewerkt)."""
    products = [p for p in store.products("sealed") if p.get("pk_id")]
    todo = [p for p in products if needs_backfill(store, p["product_id"], today)]
    log(f"Sealed-geschiedenis: {len(products)} gekoppelde sealed producten, {len(todo)} hebben nog geen oude historie")
    done, rows_total = 0, 0
    for p in todo[:limit]:
        if pk.over_budget():
            log(f"Credit-budget bereikt ({pk.credits}). De rest volgt een volgende keer.")
            break
        if deadline and time.time() >= deadline:
            log("Tijdslimiet van deze run bereikt. De rest volgt een volgende keer.")
            break
        try:
            data = pk.list_all(f"/sealed/{p['pk_id']}/prices/history", {"currency": "eur", "period": config.HISTORY_PERIOD}, per_page=100)
        except Exception as e:
            log(f"  {p['name']}: {e}")
            continue
        rows = parse_rows(p["product_id"], data, today)
        if rows:
            store.upsert_prices(rows)
            rows_total += len(rows)
        done += 1
    log(f"Sealed-geschiedenis: {done} producten bijgewerkt, {rows_total} prijspunten toegevoegd ({pk.credits} credits)")
    return rows_total


def main():
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    run(store, PkmnPrices(os.environ["PKMN_API_KEY"], budget=15000), date.today().isoformat())


if __name__ == "__main__":
    main()
