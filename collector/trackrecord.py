"""Trackrecord: houdt bij hoe vaak voorspellingen uitkwamen (live en via backtest)."""
from datetime import date, timedelta

import analysis
import config


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _add(stats, bucket, p, hit):
    s = stats.setdefault(bucket, {"n": 0, "hits": 0, "sum_p": 0.0})
    s["n"] += 1
    s["hits"] += 1 if hit else 0
    s["sum_p"] += p


def resolve(store, today, log=print):
    """Beoordeelt voorspellingen van 30+ dagen geleden: steeg de prijs minstens 10%?"""
    horizon, pct = config.STANDARD
    cutoff = (date.fromisoformat(today) - timedelta(days=horizon)).isoformat()
    pending = store.select("forecast_history", {"select": "*", "resolved": "eq.false", "date": f"lte.{cutoff}",
                                                "order": "product_id.asc,date.asc"})
    if not pending:
        return 0
    latest = store.latest_prices()
    ids = sorted({r["product_id"] for r in pending if r["signal"] == "koop"})
    names = {}
    for ch in _chunks(ids, 80):
        for p in store.select("products", {"select": "product_id,name", "product_id": f"in.({','.join(ch)})"}):
            names[p["product_id"]] = p["name"]

    add, signals, done = {}, [], []
    for r in pending:
        cur = latest.get(r["product_id"])
        if not cur or not r["price"] or not cur["price"]:
            continue
        change = float(cur["price"]) / float(r["price"]) - 1
        hit = change >= pct / 100
        p = float(r["p_up"])
        _add(add, analysis.bucket_of(p), p, hit)
        _add(add, "all", p, hit)
        if r["signal"] == "koop":
            _add(add, "koop", p, hit)
            signals.append({"product_id": r["product_id"], "name": names.get(r["product_id"]),
                            "signal_date": r["date"], "p_up": p, "change": round(change, 4), "hit": hit,
                            "resolved_on": today})
        done.append({**r, "resolved": True})

    existing = {r["bucket"]: r for r in store.select("trackrecord_stats", {"select": "*", "source": "eq.live"})}
    rows = []
    for bucket, d in add.items():
        e = existing.get(bucket, {"n": 0, "hits": 0, "sum_p": 0})
        rows.append({"source": "live", "bucket": bucket, "n": e["n"] + d["n"], "hits": e["hits"] + d["hits"],
                     "sum_p": round(float(e["sum_p"]) + d["sum_p"], 4)})
    if rows:
        store.upsert("trackrecord_stats", rows, "source,bucket")
    if signals:
        store.insert("trackrecord_signals", signals)
    if done:
        store.upsert("forecast_history", done, "product_id,date")
    store.delete("forecast_history", {"resolved": "eq.true",
                                      "date": f"lt.{(date.fromisoformat(today) - timedelta(days=45)).isoformat()}"})
    log(f"Trackrecord: {len(done)} voorspellingen beoordeeld, {len(signals)} koop-signalen")
    return len(done)


def backtest(store, today, days=200, step=5, log=print):
    """Speelt het model na op historische data: voor elke (product, dag) de kans op +10% in 30 dagen
    voorspellen met alleen de data tot dan, en vergelijken met wat er echt gebeurde."""
    horizon, pct = config.STANDARD
    since = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    rows = store.price_rows(since)
    from itertools import groupby
    stats = {}
    for pid, grp in groupby(rows, key=lambda r: r["product_id"]):
        by_source = {}
        for r in grp:
            by_source.setdefault(r["source"], []).append(
                {**r, "price": float(r["price"]) if r.get("price") is not None else None,
                 "avg1": None, "avg7": None, "avg30": None})
        series = analysis.series_for(pid, by_source)
        for idx in range(config.MIN_HISTORY_POINTS + 2, len(series) - 1, step):
            d0 = date.fromisoformat(series[idx]["date"])
            future = next((s for s in series[idx + 1:] if (date.fromisoformat(s["date"]) - d0).days >= horizon), None)
            if not future or series[idx]["price"] < config.MIN_PRICE:
                continue
            f = analysis.forecast(series[:idx + 1], horizon, pct / 100)
            if not f or f["mode"] != "historie":
                continue
            hit = future["price"] / series[idx]["price"] - 1 >= pct / 100
            _add(stats, analysis.bucket_of(f["p_up"]), f["p_up"], hit)
            _add(stats, "all", f["p_up"], hit)
            if analysis._signal(f["p_up"], f["p_down"]) == "koop":
                _add(stats, "koop", f["p_up"], hit)
    store.delete("trackrecord_stats", {"source": "eq.backtest"})
    if stats:
        store.insert("trackrecord_stats", [{"source": "backtest", "bucket": b, "n": d["n"], "hits": d["hits"],
                                            "sum_p": round(d["sum_p"], 4)} for b, d in stats.items()])
    log("Backtest: " + ", ".join(f"{b}: {d['hits']}/{d['n']}" for b, d in sorted(stats.items())))
    return stats
