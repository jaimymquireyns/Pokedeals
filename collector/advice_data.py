"""Gegevens ophalen die het advies betrouwbaarder maken (PkmnPrices-credits), voor precies de kaarten waar het om draait:
je eigen kaarten en watchlist, en alle kaarten die vandaag hoog, laag of verdacht staan (vanaf ADVICE_MIN_BUY).

  1. koppelen aan PkmnPrices en de actuele Near Mint-prijs (een tweede, eerlijke prijs naast Cardmarkets trend)
  2. de goedkoopste aanbiedingen, elke dag (verkopers tellen, verdacht goedkope aanbiedingen, trend tegen echte vraagprijs)
  3. het aantal aanbiedingen (marktmomentopname), elke dag: alleen zo zie je dat iemand het aanbod opkoopt

Daarna rekent de dagelijkse update het advies opnieuw uit met deze verse gegevens (zie run.daily).
"""
from datetime import date

import config


def targets(store, today, log=print):
    """Volgorde: eigen kaarten en watchlist, dan koopkandidaten (laag, duurste eerst), dan hoog, dan verdacht."""
    personal = []
    for table in ("collection", "watch_items"):
        try:
            personal += [r["product_id"] for r in store.select(table, {"select": "product_id"})]
        except Exception:
            pass
    rows = store.select("advice", {"select": "product_id,state,price", "date": f"eq.{today}", "state": "in.(laag,hoog,verdacht)",
                                   "price": f"gte.{config.ADVICE_MIN_BUY}"})
    rank = {"laag": 0, "hoog": 1, "verdacht": 2}
    rows.sort(key=lambda r: (rank[r["state"]], -float(r.get("price") or 0)))
    out, seen = [], set()
    for pid in personal + [r["product_id"] for r in rows]:
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    log(f"Advies-gegevens: {len(set(personal))} eigen kaarten/watchlist + {len(rows)} kaarten met een advies = {len(out)} kaarten.")
    return out


def run(store, pk, today=None, log=print, deadline=None):
    today = today or date.today().isoformat()
    ids = targets(store, today, log=log)
    cards = {p["product_id"]: p for p in store.products("card") if p["product_id"] in set(ids) and not config.is_digital_set(p.get("set_id"))}
    card_ids = [pid for pid in ids if pid in cards]
    if not card_ids:
        return
    start = pk.credits
    import nm
    nm._map_and_refresh(store, pk, today, card_ids, cards, log, deadline=deadline, refresh_price=True)
    log(f"Advies-gegevens: koppelen en Near Mint-prijs klaar ({pk.credits - start} credits).")
    import offers
    offers.run(store, pk, today, log=log, deadline=deadline, only=card_ids, max_age_days=1)
    log(f"Advies-gegevens: aanbiedingen klaar ({pk.credits - start} credits).")
    import market_snapshot
    market_snapshot.run(store, pk, today, log=log, deadline=deadline, only=card_ids, budget=config.ADVICE_SNAPSHOT_BUDGET)
    log(f"Advies-gegevens: klaar, {pk.credits - start} credits gebruikt.")
