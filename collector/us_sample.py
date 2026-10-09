"""Eenmalige steekproef: voor US_SAMPLE_N kaarten met lange Near Mint-geschiedenis ook de Amerikaanse prijzen (TCGplayer) van
dezelfde periode ophalen, om te kunnen zien of de Amerikaanse en Europese markt samen bewegen en of de ene voorloopt.
Eigen budget (US_SAMPLE_BUDGET per dag); stopt vanzelf zodra de steekproef compleet is."""
from datetime import date, timedelta

import card_history
import config


def todo(store, today):
    old = (date.fromisoformat(today) - timedelta(days=100)).isoformat()
    have_nm = {r["product_id"] for r in store.select("prices", {"select": "product_id", "source": "eq.pkmnprices", "grade_key": "eq.nm",
                                                                 "date": f"lt.{old}", "order": "product_id.asc"})}
    have_us = {r["product_id"] for r in store.select("prices", {"select": "product_id", "source": "eq.tcgplayer", "grade_key": "eq.us",
                                                                 "date": f"lt.{old}", "order": "product_id.asc"})}
    since = (date.fromisoformat(today) - timedelta(days=5)).isoformat()
    price = {}
    for r in store.select("prices", {"select": "product_id,price", "grade_key": "eq.raw", "date": f"gte.{since}", "price": "gte.5", "order": "product_id.asc"}):
        price[r["product_id"]] = max(price.get(r["product_id"], 0), float(r["price"]))
    prods = {p["product_id"]: p for p in store.products("card") if p.get("pk_id")}
    pool = sorted((pid for pid in have_nm if pid in prods and pid in price), key=lambda pid: -price[pid])
    # verspreid over prijsklassen: om en om uit de dure en de goedkopere helft
    half = len(pool) // 2
    mixed = [x for pair in zip(pool[:half], pool[half:]) for x in pair]
    sample = mixed[:config.US_SAMPLE_N]
    return [pid for pid in sample if pid not in have_us], prods


def run(store, pk, today, log=print, deadline=None):
    if not config.US_SAMPLE_N:
        return 0
    ids, prods = todo(store, today)
    if not ids:
        return 0
    original_budget = pk.budget
    pk.budget = min(original_budget, pk.credits + config.US_SAMPLE_BUDGET)
    n = rows_total = 0
    try:
        log(f"Amerikaanse steekproef: nog {len(ids)} kaarten, budget {config.US_SAMPLE_BUDGET}.")
        for pid in ids:
            if pk.over_budget() or (deadline and __import__("time").time() >= deadline):
                break
            try:
                data = pk.list_all(f"/cards/{prods[pid]['pk_id']}/prices/history", {"condition": "Near Mint", "period": "180d"}, per_page=100)
            except Exception as e:
                log(f"  {pid}: {e}")
                continue
            rows = card_history.parse_us_rows(pid, data, today) + card_history.parse_rows(pid, data, today)
            if rows:
                store.upsert_prices(rows)
                rows_total += len(rows)
            n += 1
    finally:
        pk.budget = original_budget
    log(f"Amerikaanse steekproef: {n} kaarten opgehaald, {rows_total} prijspunten.")
    return n
