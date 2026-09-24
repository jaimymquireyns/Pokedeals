"""Laagste live aanbiedingen (Cardmarket, alleen Near Mint) via PkmnPrices' '/cards/{id}/listings/cardmarket'.
Kost 20 credits per kaart per keer, dus dit gebeurt niet dagelijks per kaart: alleen voor je collectie en de
beste kansen, en een kaart wordt pas opnieuw ververst als de vorige keer een paar dagen geleden is. Staat in de
dagelijkse volgorde na sealed-geschiedenis, zodat dit profiteert van budget dat overblijft zodra de opbouw van de
Near Mint-geschiedenis (nm.py/card_history.py) grotendeels klaar is."""
import os
import time
from datetime import date, timedelta

import config
import nm
from pkmnprices import PkmnPrices
from store import SupabaseStore

REFRESH_DAYS = 3   # een kaart wordt pas opnieuw ververst als het langer dan dit geleden is
TOP_N = 300         # 'de beste kansen': zelfde top als bij het koppelen van Near Mint-prijzen
LIMIT = 5            # zoveel aanbiedingen bewaren we per kaart


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def candidates(store):
    """Collectie, prijsmeldingen, en de beste kansen — niet de zich uitbreidende 'extra'-lijst van nm.py."""
    order, seen = [], set()

    def add(pid):
        if pid and ":" not in pid and pid not in seen:
            seen.add(pid)
            order.append(pid)

    for c in store.select("collection", {"select": "product_id"}):
        add(c["product_id"])
    for a in store.select("alerts", {"select": "product_id", "active": "eq.true"}):
        add(a["product_id"])
    fc = store.select("forecasts", {"select": "product_id,p_up,p_down",
                                    "horizon_days": f"eq.{config.STANDARD[0]}", "threshold_pct": f"eq.{config.STANDARD[1]}"})
    for f in sorted(fc, key=lambda f: float(f["p_up"]) - float(f["p_down"]), reverse=True)[:TOP_N]:
        add(f["product_id"])
    return order


def stale(store, product_ids, today, max_age_days=REFRESH_DAYS):
    """Kaarten die nog nooit, of langer dan max_age_days geleden, zijn ververst."""
    cutoff = (date.fromisoformat(today) - timedelta(days=max_age_days)).isoformat()
    fresh = set()
    try:
        for ch in _chunks(sorted(product_ids), 150):
            rows = store.select("offers", {"select": "product_id", "product_id": f"in.({','.join(ch)})", "date": f"gte.{cutoff}"})
            fresh.update(r["product_id"] for r in rows)
    except Exception as e:
        print(f"  (kon niet controleren welke kaarten al vers zijn, ga gewoon door: {e})")
    return [pid for pid in product_ids if pid not in fresh]


def parse_offers(product_id, rows, today, limit=LIMIT):
    """Alleen Near Mint, goedkoopste eerst. De API kan al filteren op conditie (we sturen 'condition' mee), maar
    voor de zekerheid filteren we het hier ook nog eens zelf."""
    nm_rows = [r for r in rows if isinstance(r, dict) and (r.get("condition") or "").lower() == "near mint" and r.get("price")]
    nm_rows.sort(key=lambda r: float(r["price"]))
    out = []
    for i, r in enumerate(nm_rows[:limit], 1):
        out.append({"product_id": product_id, "rank": i, "price": round(float(r["price"]), 2),
                    "seller": r.get("seller"), "quantity": r.get("quantity"), "language": r.get("language"), "date": today})
    return out


def run(store, pk, today, log=print, deadline=None):
    cands = candidates(store)
    products = {p["product_id"]: p for p in store.products("card") if p.get("pk_id")}
    cands = [pid for pid in cands if pid in products]
    todo = stale(store, cands, today)
    log(f"Laagste aanbiedingen: {len(cands)} kaarten in aanmerking, {len(todo)} zijn aan de beurt (ouder dan {REFRESH_DAYS} dagen of nog nooit opgehaald)")

    done, rows_total = 0, 0
    for pid in todo:
        if pk.over_budget():
            log(f"Credit-budget bereikt ({pk.credits}). Morgen gaat het verder waar het nu stopt.")
            break
        if deadline and time.time() >= deadline:
            log("Tijdslimiet van deze run bereikt. Morgen gaat het verder waar het nu stopt.")
            break
        p = products[pid]
        try:
            data = pk.list_all(f"/cards/{p['pk_id']}/listings/cardmarket", {"condition": "Near Mint"}, per_page=20, max_pages=1)
        except Exception as e:
            log(f"  {p['name']}: {e}")
            continue
        rows = parse_offers(pid, data, today)
        store.delete("offers", {"product_id": f"eq.{pid}"})
        if rows:
            store.upsert("offers", rows, "product_id,rank")
        done += 1
        rows_total += len(rows)
    log(f"Laagste aanbiedingen: {done} kaarten ververst, {rows_total} aanbiedingen opgeslagen ({pk.credits} credits tot nu toe)")
    return rows_total


def main():
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    run(store, PkmnPrices(os.environ["PKMN_API_KEY"]), date.today().isoformat())


if __name__ == "__main__":
    main()
