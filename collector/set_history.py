"""Lange Near Mint-geschiedenis voor de belangrijkste kaarten van recente sets, met de credits die aan het einde van de dag
overblijven. Doel: precies kunnen zien hoe kaarten na de release van hun set dalen en weer stijgen (zie set_lifecycle.py),
zodat het advies de leeftijd van een set correct kan meewegen.

Per set van de laatste SET_HISTORY_YEARS jaar de SET_HISTORY_TOP duurste kaarten, nieuwste sets eerst, met
SET_HISTORY_DAYS dagen geschiedenis. Wat al zo diep is opgehaald (products.nm_hist_days) wordt overgeslagen, dus het
gaat elke dag verder waar het gebleven was, tot alles binnen is.
"""
from datetime import date, timedelta

import card_history
import config


def targets(store, today, log=print):
    t = date.fromisoformat(today)
    first = (t - timedelta(days=int(config.SET_HISTORY_YEARS * 365))).isoformat()
    sets = {sid: s for sid, s in store.known_sets().items()
            if s.get("release_date") and str(s["release_date"]) >= first and not config.is_digital_set(sid)}
    since = (t - timedelta(days=5)).isoformat()
    price = {}
    for r in store.select("prices", {"select": "product_id,price", "grade_key": "eq.raw", "date": f"gte.{since}", "price": "gte.2", "order": "product_id.asc"}):
        price[r["product_id"]] = max(price.get(r["product_id"], 0), float(r["price"]))
    by_set = {}
    for p in store.products("card"):
        if p.get("set_id") in sets and p["product_id"] in price and p.get("pk_id"):
            by_set.setdefault(p["set_id"], []).append(p["product_id"])
    # eerst de SET_HISTORY_FIRST duurste kaarten van elke set (zo is er snel van elke set iets), daarna de rest tot SET_HISTORY_TOP
    ranked = {sid: sorted(pids, key=lambda pid: -price[pid])[:config.SET_HISTORY_TOP] for sid, pids in by_set.items()}
    newest = sorted(by_set, key=lambda s: str(sets[s]["release_date"]), reverse=True)
    order = [pid for sid in newest for pid in ranked[sid][:config.SET_HISTORY_FIRST]]
    order += [pid for sid in newest for pid in ranked[sid][config.SET_HISTORY_FIRST:]]
    log(f"Set-geschiedenis: {len(order)} kaarten uit {len(by_set)} sets van de laatste {config.SET_HISTORY_YEARS:g} jaar "
        f"(top {config.SET_HISTORY_TOP} per set), tot {config.SET_HISTORY_DAYS} dagen terug.")
    return order


def supported_period(store, pk, pid, log=print):
    """Welke diepte PkmnPrices aanvaardt: eerst SET_HISTORY_DAYS, anders korter. Eén goedkope proef (1 rij)."""
    p = (store.products("card", {"product_id": f"eq.{pid}"}) or [{}])[0]
    for days in (config.SET_HISTORY_DAYS, 365, 180):
        try:
            pk.call(f"/cards/{p['pk_id']}/prices/history", {"currency": "eur", "condition": "Near Mint", "period": f"{days}d", "limit": 1})
            return days
        except Exception as e:
            log(f"  PkmnPrices aanvaardt {days} dagen niet ({str(e)[:80]}); korter proberen")
    return None


def run(store, pk, today, log=print, deadline=None, budget=None):
    """budget: hooguit zoveel credits van deze run (bovenop wat al gebruikt is); None = wat er nog over is."""
    if budget is not None:
        original_budget = pk.budget
        pk.budget = min(original_budget, pk.credits + budget)
        try:
            return run(store, pk, today, log=log, deadline=deadline)
        finally:
            pk.budget = original_budget
    order = targets(store, today, log=log)
    if not order or pk.over_budget():
        return 0
    days = supported_period(store, pk, order[0], log=log)
    if not days:
        return 0
    original = config.HISTORY_PERIOD
    config.HISTORY_PERIOD = f"{days}d"   # tijdelijk dieper, alleen voor deze kaarten
    try:
        return card_history.run(store, pk, today, log=log, deadline=deadline, only=order)
    finally:
        config.HISTORY_PERIOD = original
