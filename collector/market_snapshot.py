"""Stap 1 van het meersignalenplan: dagelijkse momentopname van aanbod en liquiditeit, via PkmnPrices'
'/cards/{id}/listings/cardmarket' (de losse aanbiedingen op Cardmarket, met verkoper).
  - listings  totaal aantal aanbiedingen                                  (aanbod)
  - sellers   verschillende verkopers binnen de opgevraagde aanbiedingen  (liquiditeit)
Vraag (recente verkopen) zit hier niet in; die kolom blijft leeg.

PkmnPrices rekent per teruggegeven rij, dus per kaart vragen we maar één kleine pagina op (config.SNAPSHOT_PER_PAGE,
standaard 20 = maximaal 20 credits) en halen het totaal uit de paginagegevens. Daardoor is 'sellers' een ondergrens
(verschillende verkopers binnen die eerste pagina): genoeg om een dunne markt (1 of 2 verkopers) te herkennen.

Niet voor alle kaarten, alleen voor kandidaten, binnen een eigen budget (config.SNAPSHOT_PK_BUDGET):
  1. kaarten die de laatste 14 dagen al een momentopname kregen (zodat hun trend niet onderbroken wordt);
  2. nieuwe kandidaten: vandaag onder hun gemiddelde en geen negatief signaal, duurste eerst (daar is na
     commissie en verzending de meeste winst mogelijk).
"""
import time
from datetime import date, timedelta

import config


def _total(body, rows, per_page):
    pag = (body or {}).get("pagination") or {} if isinstance(body, dict) else {}
    for k in ("total", "total_count", "total_items", "count"):
        if isinstance(pag.get(k), (int, float)):
            return int(pag[k])
    tp = pag.get("total_pages")
    if isinstance(tp, (int, float)) and tp > 1:
        return int(tp) * per_page   # schatting: het precieze aantal op de laatste pagina weten we niet
    return len(rows)


def snapshot_row(product_id, rows, body, today, per_page):
    sellers = {r.get("seller") for r in rows if isinstance(r, dict) and r.get("seller")}
    return {"product_id": product_id, "date": today, "listings": _total(body, rows, per_page),
            "sellers": len(sellers), "recent_sales": None, "price_usd": None}


def candidates(store, today):
    """(al gevolgde kaarten, nieuwe kandidaten) als lijsten product_id's, in volgorde van voorrang."""
    since = (date.fromisoformat(today) - timedelta(days=14)).isoformat()
    tracked = sorted({r["product_id"] for r in store.select("market_snapshots", {"select": "product_id", "date": f"gte.{since}"})})
    sig = store.select("card_signals", {"select": "product_id,price,s_onder_gemiddelde,n_negative", "date": f"eq.{today}"})
    new = [r for r in sig if r.get("s_onder_gemiddelde") == 1 and not r.get("n_negative") and r["product_id"] not in set(tracked)]
    new.sort(key=lambda r: -float(r.get("price") or 0))
    return tracked, [r["product_id"] for r in new]


def run(store, pk, today, log=print, deadline=None, only=None, budget=None):
    """only: een eigen lijst kaarten (bijv. de kaarten met een advies), in plaats van de gewone kandidaten; budget: eigen creditlimiet."""
    if pk is None:
        log("Marktmomentopname: geen PKMN_API_KEY, overgeslagen.")
        return 0
    start = pk.credits
    budget, per_page = (budget or config.SNAPSHOT_PK_BUDGET), config.SNAPSHOT_PER_PAGE
    over = lambda: pk.over_budget() or pk.credits - start + per_page > budget or (deadline is not None and time.time() >= deadline)
    tracked, new = (list(only), []) if only is not None else candidates(store, today)
    done_today = {r["product_id"] for r in store.select("market_snapshots", {"select": "product_id", "date": f"eq.{today}"})}
    products = {p["product_id"]: p for p in store.products("card") if p.get("pk_id")}
    order = [pid for pid in tracked + new if pid in products and pid not in done_today]
    log(f"Marktmomentopname: {len(tracked)} kaarten al gevolgd, {len(new)} nieuwe kandidaten; {len(order)} aan de beurt (met koppeling).")
    rows, n = [], 0
    for pid in order:
        if over():
            log(f"  budget of tijd voor de momentopname op ({pk.credits - start} credits); de rest morgen.")
            break
        try:
            body = pk.call(f"/cards/{products[pid]['pk_id']}/listings/cardmarket", {"per_page": per_page, "page": 1})
        except Exception as e:
            log(f"  {products[pid]['name']}: {e}")
            if pk.blocked:
                break
            continue
        data = (body or {}).get("data") if isinstance(body, dict) else body
        data = data if isinstance(data, list) else []
        rows.append(snapshot_row(pid, data, body, today, per_page))
        n += 1
        if len(rows) >= 100:
            store.upsert("market_snapshots", rows, "product_id,date")
            rows = []
    if rows:
        store.upsert("market_snapshots", rows, "product_id,date")
    used = pk.credits - start
    log(f"Marktmomentopname: {n} kaarten vastgelegd, {used} credits" + (f" (~{used / n:.1f} per kaart)." if n else "."))
    return n
