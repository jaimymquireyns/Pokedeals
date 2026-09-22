"""Trackrecord: houdt per periode (bijv. '30 dagen, 10%') bij hoe vaak voorspellingen uitkwamen (live en via backtest)."""
from datetime import date, timedelta
from itertools import groupby

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
    """Beoordeelt voorspellingen die oud genoeg zijn om na te kijken: steeg de prijs minstens de drempel?
    Doet dit per periode apart (7/14/30/60 dagen); lange periodes (3-24 maanden) duren te lang om hier op te wachten,
    daarvoor is de backtest de enige praktische bron."""
    pending = store.select("forecast_history", {"select": "*", "resolved": "eq.false", "order": "horizon_days.asc,product_id.asc,date.asc"})
    if not pending:
        return 0
    latest = store.latest_prices()
    names = {}
    ids = sorted({r["product_id"] for r in pending})
    for ch in _chunks(ids, 80):
        for p in store.select("products", {"select": "product_id,name", "product_id": f"in.({','.join(ch)})"}):
            names[p["product_id"]] = p["name"]

    existing = {(r["source"], r["horizon_days"], r["threshold_pct"], r["bucket"]): r
                for r in store.select("trackrecord_stats", {"select": "*", "source": "eq.live"})}
    all_add, all_signals, done, stat_rows = {}, [], [], []
    for (horizon, pct), grp in groupby(pending, key=lambda r: (r["horizon_days"], r["threshold_pct"])):
        cutoff = (date.fromisoformat(today) - timedelta(days=horizon)).isoformat()
        add = {}
        for r in grp:
            if r["date"] > cutoff:
                continue    # nog niet oud genoeg voor deze periode
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
                all_signals.append({"product_id": r["product_id"], "name": names.get(r["product_id"]),
                                    "signal_date": r["date"], "horizon_days": horizon, "threshold_pct": pct,
                                    "p_up": p, "change": round(change, 4), "hit": hit, "resolved_on": today})
            done.append({**r, "resolved": True})
        for bucket, d in add.items():
            e = existing.get(("live", horizon, pct, bucket), {"n": 0, "hits": 0, "sum_p": 0})
            stat_rows.append({"source": "live", "horizon_days": horizon, "threshold_pct": pct, "bucket": bucket,
                              "n": e["n"] + d["n"], "hits": e["hits"] + d["hits"], "sum_p": round(float(e["sum_p"]) + d["sum_p"], 4)})
        all_add[(horizon, pct)] = add

    if stat_rows:
        store.upsert("trackrecord_stats", stat_rows, "source,horizon_days,threshold_pct,bucket")
    if all_signals:
        store.insert("trackrecord_signals", all_signals)
    if done:
        store.upsert("forecast_history", done, "product_id,date,horizon_days,threshold_pct")
    store.delete("forecast_history", {"resolved": "eq.true",
                                      "date": f"lt.{(date.fromisoformat(today) - timedelta(days=45)).isoformat()}"})
    n_combos = len([k for k, v in all_add.items() if v])
    log(f"Trackrecord: {len(done)} voorspellingen beoordeeld over {n_combos} periodes, {len(all_signals)} koop-signalen")
    return len(done)


def backtest(store, today, days=200, step=5, combos=None, log=print):
    """Speelt het model na op historische data: voor elke (product, dag, periode) de kans voorspellen met alleen
    de data tot dan, en vergelijken met wat er echt gebeurde. Dit is de enige praktische manier om lange periodes
    (3-24 maanden) te controleren zonder daadwerkelijk jaren te wachten."""
    combos = combos or (config.GRID + config.LONG_GRID)
    since = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    rows = store.price_rows(since)
    series_by_pid = {}
    for pid, grp in groupby(rows, key=lambda r: r["product_id"]):
        by_source = {}
        for r in grp:
            by_source.setdefault(r["source"], []).append(
                {**r, "price": float(r["price"]) if r.get("price") is not None else None,
                 "avg1": None, "avg7": None, "avg30": None})
        series_by_pid[pid] = analysis.series_for(pid, by_source)

    all_stats = {}
    for horizon, pct in combos:
        stats = {}
        for pid, series in series_by_pid.items():
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
        if stats:
            all_stats[(horizon, pct)] = stats

    for horizon, pct in combos:
        store.delete("trackrecord_stats", {"source": "eq.backtest", "horizon_days": f"eq.{horizon}", "threshold_pct": f"eq.{pct}"})
    out_rows = [{"source": "backtest", "horizon_days": h, "threshold_pct": p, "bucket": b,
                "n": d["n"], "hits": d["hits"], "sum_p": round(d["sum_p"], 4)}
                for (h, p), stats in all_stats.items() for b, d in stats.items()]
    if out_rows:
        store.insert("trackrecord_stats", out_rows)
    for (h, p), stats in sorted(all_stats.items()):
        log(f"Backtest {h}d/{p}%: " + ", ".join(f"{b}: {d['hits']}/{d['n']}" for b, d in sorted(stats.items())))
    return all_stats
