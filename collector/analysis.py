"""Kansberekening voor prijstrends.

Model: we behandelen de log-prijs als een Brownse beweging met drift (mu) en schommeling (sigma) per dag.
Dan is de kans dat de prijs binnen H dagen met minstens x% stijgt (of daalt) een normale verdeling:
    P(stijging >= x) = 1 - Phi( (ln(1+x) - mu*H) / (sigma*sqrt(H)) )
    P(daling   >= x) =     Phi( (ln(1-x) - mu*H) / (sigma*sqrt(H)) )

Twee modi, afhankelijk van hoeveel eigen data er is:
  * "snel":      één snapshot. Cardmarket geeft gemiddelden over 30/7/1 dagen; daaruit maken we 4 punten in
                 de tijd (ongeveer -15, -3.5, -0.5 en 0 dagen) en schatten daar de drift uit.
  * "historie":  >= MIN_HISTORY_POINTS eigen dagstanden. Drift en sigma komen uit de echte prijsreeks.
In beide modi trekken we de gemeten drift richting 0 (shrinkage): trends zetten zich in de praktijk
minder vaak door dan ze lijken.
"""
import math
from datetime import date

import config


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _dedupe_by_date(rows):
    by_day = {}
    for r in rows:
        prev = by_day.get(r["date"])
        if prev is None or (prev["avg1"] is None and r["avg1"] is not None):
            by_day[r["date"]] = r
    return [by_day[d] for d in sorted(by_day)]


def _history_points(rows):
    d0 = date.fromisoformat(rows[-1]["date"])
    return [((date.fromisoformat(r["date"]) - d0).days, r["trend"])
            for r in rows if r["trend"] and r["trend"] > 0]


def _pseudo_points(last):
    pts = []
    for t, key in ((-15, "avg30"), (-3.5, "avg7"), (-0.5, "avg1"), (0, "trend")):
        v = last[key]
        if v and v > 0:
            pts.append((t, v))
    return pts


def _drift_history(pts):
    """Maximum-likelihood schatting voor Brownse beweging met drift uit onregelmatige dagstanden."""
    pts = pts[-45:]  # laatste ~6 weken
    t0, p0 = pts[0]
    t1, p1 = pts[-1]
    span = t1 - t0
    mu = math.log(p1 / p0) / span
    ss, total_dt = 0.0, 0.0
    for (ta, pa), (tb, pb) in zip(pts, pts[1:]):
        dt = tb - ta
        r = math.log(pb / pa)
        ss += (r - mu * dt) ** 2
        total_dt += dt
    sigma = math.sqrt(ss / total_dt) if total_dt else config.SIGMA_FLOOR
    return mu, sigma


def _drift_regression(pts):
    """Lineaire regressie van ln(prijs) tegen tijd -> (helling, residu-spreiding)."""
    xs = [t for t, _ in pts]
    ys = [math.log(p) for _, p in pts]
    n = len(pts)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    resid = [y - (my + slope * (x - mx)) for x, y in zip(xs, ys)]
    sd = math.sqrt(sum(e * e for e in resid) / max(n - 2, 1))
    return slope, sd


def forecast(rows, horizon=None, threshold=None):
    """rows: prijsrijen van één kaart (gesorteerd op datum). Geeft dict of None als er te weinig data is."""
    horizon = horizon or config.HORIZON_DAYS
    threshold = threshold or config.MOVE_THRESHOLD
    rows = _dedupe_by_date(rows)
    if not rows:
        return None
    last = rows[-1]
    price = last["trend"]
    if not price or price <= 0:
        return None

    hist = _history_points(rows)
    if len(hist) >= config.MIN_HISTORY_POINTS and hist[-1][0] - hist[0][0] >= config.MIN_HISTORY_POINTS - 1:
        mode = "historie"
        mu, sigma = _drift_history(hist)
        n = len(hist)
        mu *= n / (n + config.SHRINK_K)
        sigma = max(sigma, 0.005)
    else:
        pts = _pseudo_points(last)
        if len(pts) < 3:
            return None
        mode = "snel"
        mu, fit_sd = _drift_regression(pts)
        mu *= config.AVG_MODE_SHRINK
        sigma = max(fit_sd, config.SIGMA_FLOOR)
        n = len(hist)

    mu = max(-config.MAX_DAILY_DRIFT, min(config.MAX_DAILY_DRIFT, mu))
    sd_h = sigma * math.sqrt(horizon)
    p_up = 1.0 - norm_cdf((math.log(1 + threshold) - mu * horizon) / sd_h)
    p_down = norm_cdf((math.log(1 - threshold) - mu * horizon) / sd_h)
    # Het model is een schatting: nooit 0% of 100% zeker tonen.
    p_up = min(max(p_up, 0.02), 0.98)
    p_down = min(max(p_down, 0.02), 0.98)

    if mode == "historie":
        confidence = "hoog" if n >= 30 else "middel"
    else:
        confidence = "laag"

    avg30 = last["avg30"]
    return {
        "price": price,
        "avg7": last["avg7"],
        "avg30": avg30,
        "mom30": (price / avg30 - 1) if avg30 else None,
        "p_up": p_up,
        "p_down": p_down,
        "exp_change": math.exp(mu * horizon) - 1,   # mediane verwachte verandering over de horizon
        "sigma": sigma,
        "mu": mu,
        "mode": mode,
        "n": n,
        "confidence": confidence,
        "signal": _signal(p_up, p_down),
        "updated": last["date"],
    }


def _signal(p_up, p_down):
    if p_up >= config.BUY_MIN_P_UP and p_down <= config.BUY_MAX_P_DOWN:
        return "koop"
    if p_down >= config.SELL_MIN_P_DOWN and p_up <= config.SELL_MAX_P_UP:
        return "verkoop"
    return "afwachten"


# ---------------------------------------------------------------------------
# Reeksen samenstellen, kalibreren
# ---------------------------------------------------------------------------
def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


def splice(own, hist):
    """Plakt oude historie (andere bron, ander prijsniveau) vóór onze eigen reeks.

    own, hist: lijsten dicts met 'date' en 'price'. De historie wordt geschaald zodat het niveau aansluit op
    onze eigen prijzen (mediaan van de verhoudingen op overlappende dagen, anders de laatste eigen prijs tegenover
    de dichtstbijzijnde historiepunt). Alleen de procentuele bewegingen doen ertoe voor de kansberekening.
    """
    if not own:
        return []
    if not hist:
        return list(own)
    first_own = own[0]["date"]
    hist_by_day = {h["date"]: h["price"] for h in hist if h["price"]}
    ratios = [o["price"] / hist_by_day[o["date"]] for o in own if o["price"] and hist_by_day.get(o["date"])]
    if not ratios:
        ref = min(hist_by_day, key=lambda d: abs((date.fromisoformat(d) - date.fromisoformat(own[-1]["date"])).days))
        ratios = [own[-1]["price"] / hist_by_day[ref]]
    ratio = _median(ratios)
    older = [{"date": d, "price": p * ratio, "avg1": None, "avg7": None, "avg30": None}
             for d, p in sorted(hist_by_day.items()) if d < first_own]
    return older + list(own)


def fill_avgs(rows):
    """Vult avg1/avg7/avg30 van de laatste rij zelf in als de bron ze niet levert."""
    if not rows:
        return rows
    last = rows[-1]
    d_last = date.fromisoformat(last["date"])
    for key, span in (("avg1", 1), ("avg7", 7), ("avg30", 30)):
        if last.get(key):
            continue
        vals = [r["price"] for r in rows if r["price"] and (d_last - date.fromisoformat(r["date"])).days < span]
        last[key] = sum(vals) / len(vals) if vals else None
    return rows


BUCKETS = [(0.0, 0.2, "0-20"), (0.2, 0.4, "20-40"), (0.4, 0.6, "40-60"), (0.6, 0.8, "60-80"), (0.8, 1.01, "80-100")]


def bucket_of(p):
    for lo, hi, name in BUCKETS:
        if lo <= p < hi:
            return name
    return "80-100"


def calibrate(p, stats):
    """Trekt een voorspelde kans naar de werkelijk waargenomen frequentie zodra er genoeg uitkomsten zijn.

    stats: {bucket: {"n": .., "hits": ..}} (bij voorkeur live, anders backtest).
    """
    st = stats.get(bucket_of(p)) if stats else None
    if not st or st["n"] < config.CALIBRATE_MIN_N:
        return p
    obs = st["hits"] / st["n"]
    k = config.CALIBRATE_MIN_N
    return min(max((st["n"] * obs + k * p) / (st["n"] + k), 0.02), 0.98)


def series_for(product_id, by_source):
    """De reeks waarop het model draait. Sealed: PPT-reeks. Kaarten: eigen Cardmarket-reeks, met oude
    PPT-historie (bron 'ppt_hist') eraan vastgeplakt."""
    if ":" in product_id:      # sealed (bijv. 'cm:12345'): de eigen reeks van die bron
        own = [v for k, v in by_source.items() if k != "ppt_hist"]
        series = max(own, key=len) if own else []
    else:
        series = splice(by_source.get("tcgdex", []), by_source.get("ppt_hist", []))
    rows = [{"date": r["date"], "trend": r["price"], "price": r["price"], "avg1": r.get("avg1"),
             "avg7": r.get("avg7"), "avg30": r.get("avg30")} for r in series if r["price"]]
    return fill_avgs(rows)
