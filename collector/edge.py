"""Een eigen, eenvoudig voorspelmodel, gebouwd op wat de backtest (8 okt) liet zien.

Wat de backtest liet zien: prijzen keren terug naar hun gemiddelde ('onder het 6-maandsgemiddelde' voorspelt iets), terwijl
trendsignalen (piek, valt nog, stabiliseert) niets voorspellen. Het oude model (analysis.forecast) rekent juist de trend uit
het verleden door; dat verklaart waarschijnlijk waarom zijn kansen omgekeerd uitpakten. Dit model is bewust klein:

  verwachte koersverandering over 30 dagen = een lineaire combinatie van
      depth   hoe ver de prijs onder zijn 6-maandsgemiddelde ligt (log)
      mom14   de verandering van de laatste 14 dagen (log)
      logp    het prijsniveau (log): de kosten (verzending, commissie) wegen bij goedkope kaarten zwaarder
      mkt30   hoe de hele markt (mediaan van alle beroemde kaarten) de laatste 30 dagen bewoog
      cv14    hoe onrustig de laatste 14 dagen waren
      jumps   hoeveel dagen met een sprong van meer dan 50% in de laatste 60 dagen (een teken van een onbetrouwbare prijs)
  met de gewichten uit de eigen geschiedenis (kleinste kwadraten met een lichte rem), en de overgebleven afwijkingen
  (residuen) als verdeling om uit te rekenen hoe groot de kans is dat de prijs genoeg stijgt.

Twee kansen: p_win = kopen nu (laagste prijs incl. verzending) en over 30 dagen verkopen (na commissie en verpakking) levert winst op;
p_up10 = de prijs staat over 30 dagen minstens 10% hoger.

Het model wordt eerlijk getoetst: walk_forward() traint op het begin van de geschiedenis en meet op het deel dat het model nog
nooit zag (met een gat van 30 dagen ertussen, zodat de uitkomst van een trainingsmoment niet in de testperiode valt). Elke dag worden de
voorspellingen ook opgeslagen (card_signals.p_win e.a.) en na 30 dagen vergeleken met wat er echt gebeurde (evaluate_stored).

Let op, een valkuil die de test met zuivere random walks aan het licht bracht: de kans op winst hangt al van het PRIJSNIVEAU af, want een
dure kaart hoeft minder te stijgen om de verzend- en verkoopkosten te dekken. Een model dat alleen dure kaarten hoger inschat lijkt dan beter
dan 'het basispercentage' zonder iets over prijzen te weten. Daarom vergelijken we steeds met een KOSTENBEWUST BASISMODEL (p_win0): dezelfde
kosten en hetzelfde prijsniveau, maar zonder enig kenmerk (geen terugkeer, geen trend, geen markt). Alleen wat het model daarboven weet telt.
"""
import math
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from functools import lru_cache

import config

HORIZON = 30
VERSION = "edge-1"
FEATURES = ("depth", "mom14", "logp", "mkt30", "cv14", "jumps")
MAX_PRED = 0.40          # een verwachte verandering van meer dan +/-40% in 30 dagen tonen we nooit
EDGE_COLS = ("p_win", "p_win0", "p_up10", "exp_ret", "model")   # kolommen in card_signals (supabase/schema.sql)


@lru_cache(maxsize=None)
def _d(s):
    return date.fromisoformat(s)


def _median(xs):
    s = sorted(xs)
    return s[len(s) // 2] if s else None


# ---------------- kosten ----------------
def net_profit(p0, end):
    """Kopen voor p0 (incl. verzending), verkopen voor 'end' (na commissie en verpakking). Zelfde som als signals._outcomes."""
    fee = config.DEFAULT_FEE_PCT / 100
    return end * (1 - fee) - config.PACKAGING - (p0 + config.ship_cost(p0))


def breakeven_log(p0):
    """De koersverandering (log) die nodig is om na alle kosten precies op nul uit te komen."""
    fee = config.DEFAULT_FEE_PCT / 100
    need = (p0 + config.ship_cost(p0) + config.PACKAGING) / (1 - fee)
    return math.log(need / p0)


# ---------------- de markt ----------------
def market_returns(series, lag=30, min_cards=5):
    """Per datum: de mediaan van de koersverandering (log) over de afgelopen 'lag' dagen, over alle kaarten. Kijkt nooit vooruit."""
    by_date = {}
    for pts in series.values():
        dates = [d for d, _ in pts]
        for i, (d, p) in enumerate(pts):
            if p <= 0:
                continue
            target = (_d(d) - timedelta(days=lag)).isoformat()
            j = bisect_right(dates, target) - 1
            if j < 0 or pts[j][1] <= 0 or (_d(target) - _d(dates[j])).days > 10:
                continue   # geen punt in de buurt van 'lag' dagen terug
            by_date.setdefault(d, []).append(math.log(p / pts[j][1]))
    return {d: _median(v) for d, v in by_date.items() if len(v) >= min_cards}


def market_at(mk, day, back=6):
    """De marktbeweging op 'day', of de laatste dag daarvoor waarvoor we hem hebben (max 'back' dagen terug)."""
    if not mk:
        return None
    d = _d(day)
    for k in range(back):
        v = mk.get((d - timedelta(days=k)).isoformat())
        if v is not None:
            return v
    return None


def jump_count(points, days=60, thr=0.5):
    """Aantal keren in de laatste 'days' dagen dat de prijs tussen twee opeenvolgende punten met meer dan 'thr' (50%) sprong."""
    if len(points) < 2:
        return 0
    start = (_d(points[-1][0]) - timedelta(days=days)).isoformat()
    n, prev = 0, None
    for d, p in points[-120:]:
        if d >= start and prev and prev > 0 and abs(p / prev - 1) > thr:
            n += 1
        prev = p
    return n


def features(pp, points, mk):
    """pp: uitkomst van signals.price_signals; points: de prijsreeks tot en met nu. None als er iets niet te berekenen valt."""
    price, vs, m14 = pp["price"], pp["vs_avg"], pp["momentum_14d"]
    if not price or price <= 0 or vs <= -0.99 or m14 <= -0.99:
        return None
    mkt = market_at(mk, points[-1][0])
    jn = jump_count(points)
    return {"depth": -math.log(1 + vs), "mom14": math.log(1 + m14), "logp": math.log(price), "mkt30": mkt if mkt is not None else 0.0,
            "cv14": pp.get("cv_14d"), "jumps": math.log1p(jn), "_jn": jn, "_vs": vs, "_mkt": mkt}


# ---------------- metingen verzamelen ----------------
def collect_samples(series, horizon=HORIZON, step=5):
    """Dezelfde meetmomenten als signals.backtest (per kaart niet-overlappend), maar dan met alle kenmerken en uitkomsten erbij."""
    from signals import price_signals   # pas hier: signals importeert zelf dit bestand
    mk = market_returns(series)
    out = []
    for pid, pts in series.items():
        next_ok = ""
        for i in range(20, len(pts), step):
            if pts[i][0] < next_ok:
                continue
            target = (_d(pts[i][0]) + timedelta(days=horizon)).isoformat()
            if pts[-1][0] < target:
                break
            later = [(d, p) for d, p in pts[i + 1:] if d <= target]
            pp = price_signals(pts[: i + 1])
            if not later or not pp:
                continue
            f = features(pp, pts[: i + 1], mk)
            if not f:
                continue
            p0, end = pp["price"], later[-1][1]
            out.append({"pid": pid, "date": pts[i][0], "end_date": later[-1][0], "p0": p0, "end": end, "f": f, "y": math.log(end / p0),
                        "up": end >= p0 * 1.10, "win": net_profit(p0, end) > 0, "top": max(p for _, p in later)})
            next_ok = target
    return out


# ---------------- het model ----------------
def _val(f, k, cv_fill):
    v = f.get(k)
    return cv_fill if v is None else v


def _solve(a, b):
    """Gauss-eliminatie met pivotering voor een klein stelsel (6 onbekenden): geen numpy nodig."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c:
                fac = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= fac * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit(samples, ridge=0.02):
    """Kleinste kwadraten met een lichte rem (ridge, als deel van het aantal metingen). None als er te weinig metingen zijn."""
    rows = [s for s in samples if s.get("f")]
    if len(rows) < 30:
        return None
    cv_fill = _median([s["f"]["cv14"] for s in rows if s["f"].get("cv14") is not None]) or 0.03
    X = [[_val(s["f"], k, cv_fill) for k in FEATURES] for s in rows]
    y = [s["y"] for s in rows]
    n, k = len(X), len(FEATURES)
    mean = [sum(r[j] for r in X) / n for j in range(k)]
    std = [math.sqrt(sum((r[j] - mean[j]) ** 2 for r in X) / n) or 1.0 for j in range(k)]
    Z = [[(r[j] - mean[j]) / std[j] for j in range(k)] for r in X]
    ybar = sum(y) / n
    lam = ridge * n
    a = [[sum(z[i] * z[j] for z in Z) + (lam if i == j else 0.0) for j in range(k)] for i in range(k)]
    b = [sum(z[i] * (yy - ybar) for z, yy in zip(Z, y)) for i in range(k)]
    beta = _solve(a, b)
    if beta is None:
        return None
    resid = sorted(yy - (ybar + sum(bj * zj for bj, zj in zip(beta, z))) for z, yy in zip(Z, y))
    return {"names": FEATURES, "mean": mean, "std": std, "beta": beta, "intercept": ybar, "resid": resid, "cv_fill": cv_fill, "n": n, "version": VERSION,
            "base": fit_baseline(rows)}


def fit_baseline(samples):
    """Het kostenbewuste basismodel: elke kaart krijgt dezelfde verwachte verandering (het gemiddelde uit de training); de kosten
    (en dus het prijsniveau) zitten wel in de kans. Alles wat het echte model hierboven uit de kenmerken haalt is dus 'extra'."""
    rows = [s for s in samples if s.get("f")]
    if len(rows) < 30:
        return None
    y = [s["y"] for s in rows]
    ybar = sum(y) / len(y)
    k = len(FEATURES)
    return {"names": FEATURES, "mean": [0.0] * k, "std": [1.0] * k, "beta": [0.0] * k, "intercept": ybar,
            "resid": sorted(v - ybar for v in y), "cv_fill": 0.03, "n": len(rows), "version": VERSION + "-basis"}


def predict_return(model, f):
    z = [(_val(f, k, model["cv_fill"]) - model["mean"][j]) / model["std"][j] for j, k in enumerate(FEATURES)]
    yhat = model["intercept"] + sum(b * zj for b, zj in zip(model["beta"], z))
    return max(-MAX_PRED, min(MAX_PRED, yhat))


def prob_ge(model, f, thr_log):
    """Kans dat de koersverandering (log) minstens thr_log is, volgens de verdeling van de afwijkingen uit de training (licht afgevlakt)."""
    need = thr_log - predict_return(model, f)
    res = model["resid"]
    above = len(res) - bisect_left(res, need)
    return (above + 0.5) / (len(res) + 1)


def predict(model, pp, points, mk):
    f = features(pp, points, mk)
    if not f:
        return None
    p0 = pp["price"]
    out = {"p_win": prob_ge(model, f, breakeven_log(p0)), "p_up10": prob_ge(model, f, math.log(1.10)),
           "exp_ret": math.exp(predict_return(model, f)) - 1}
    if model.get("base"):
        out["p_win0"] = prob_ge(model["base"], f, breakeven_log(p0))
    return out


# ---------------- eerlijk toetsen ----------------
def _split(samples, train_frac=0.6, min_train=100, min_test=50, why=None):
    """Kiest een splitsdatum: train = metingen waarvan de uitkomst op die datum al bekend was (einddatum <= splitsdatum), test = metingen
    vanaf die datum. Het oog valt alleen op AANTALLEN, nooit op uitkomsten: van alle datums waarbij beide kanten groot genoeg zijn pakken we
    die waarbij het trainingsdeel het dichtst bij train_frac van alles ligt. (Eerdere versie nam de datum bij 60% van de metingen en eiste
    einddatum < splitsdatum: bij een scheve verdeling, met de meeste metingen in de eerste meetronde, bleef er dan niets over om op te trainen.)"""
    s = sorted(samples, key=lambda x: x["date"])
    n = len(s)
    if n < min_train + min_test:
        if why is not None:
            why.append(f"{n} metingen in totaal; minimaal {min_train + min_test} nodig")
        return None, None, None
    best = None
    most = (0, "")
    for cut in sorted({x["date"] for x in s}):
        train = [x for x in s if x["end_date"] <= cut]
        test = [x for x in s if x["date"] >= cut]
        most = max(most, (min(len(train), len(test)), cut))
        if len(train) < min_train or len(test) < min_test:
            continue
        score = abs(len(train) / n - train_frac)
        if best is None or score < best[0]:
            best = (score, cut, train, test)
    if not best:
        if why is not None:
            why.append(f"{n} metingen, maar op geen enkele splitsdatum zijn er minstens {min_train} om op te trainen en {min_test} om op te toetsen "
                       f"(de meeste metingen vallen op te weinig verschillende dagen; beste splitsing: {most[0]} aan de kleinste kant)")
        return None, None, None
    return best[2], best[3], best[1]


def _brier(ps, outs):
    return sum((p - (1.0 if o else 0.0)) ** 2 for p, o in zip(ps, outs)) / len(outs)


def walk_forward(samples, train_frac=0.6, rule_depth=-math.log(0.85), why=None):
    """Traint op het begin, meet op het eind. Alles wordt vergeleken met het kostenbewuste basismodel (zie boven). None als er te weinig
    metingen zijn voor een eerlijke toets."""
    train, test, cut = _split(samples, train_frac, why=why)
    if not train:
        return None
    model = fit(train)
    if not model:
        if why is not None:
            why.append("het model kon niet worden aangepast op de trainingsmetingen")
        return None
    base = model["base"]
    for s in test:
        s["p_win"] = prob_ge(model, s["f"], breakeven_log(s["p0"]))
        s["p_up10"] = prob_ge(model, s["f"], math.log(1.10))
        s["p_win0"] = prob_ge(base, s["f"], breakeven_log(s["p0"]))
        s["p_up0"] = prob_ge(base, s["f"], math.log(1.10))
    res = {"cut": cut, "n_train": len(train), "n_test": len(test), "coef": dict(zip(FEATURES, model["beta"])), "model": model,
           "train_days": len({x["date"] for x in train}), "test_days": len({x["date"] for x in test})}
    wins = [s["win"] for s in test]
    ups = [s["up"] for s in test]
    res["win_rate"] = sum(wins) / len(test)
    res["up_rate"] = sum(ups) / len(test)
    bb = _brier([s["p_win0"] for s in test], wins)
    res["skill_win"] = 1 - _brier([s["p_win"] for s in test], wins) / bb if bb else 0.0
    bu = _brier([s["p_up0"] for s in test], ups)
    res["skill_up"] = 1 - _brier([s["p_up10"] for s in test], ups) / bu if bu else 0.0
    # de 20% waar het model het meest MEER verwacht dan het basismodel: haalt dat groepje meer dan het basismodel verwachtte?
    ranked = sorted(test, key=lambda s: -(s["p_win"] - s["p_win0"]))
    k = max(10, len(ranked) // 5)
    top, rest = ranked[:k], ranked[k:]
    res["top_n"] = len(top)
    res["top_win"] = sum(s["win"] for s in top) / len(top)
    res["top_exp"] = sum(s["p_win0"] for s in top) / len(top)
    res["rest_win"] = sum(s["win"] for s in rest) / max(len(rest), 1)
    res["rest_exp"] = sum(s["p_win0"] for s in rest) / max(len(rest), 1)
    var = sum(s["p_win0"] * (1 - s["p_win0"]) for s in top) / len(top)
    res["z"] = (res["top_win"] - res["top_exp"]) / math.sqrt(max(var, 1e-9) / len(top))
    # Werkt het model ook in rustige reeksen (zonder sprongen)? De uitsplitsing liet zien dat 'onder het gemiddelde' bijna alleen bij springerige reeksen werkte.
    calm = [s for s in test if s["f"]["_jn"] < 2]
    if len(calm) >= 30:
        cb = _brier([s["p_win0"] for s in calm], [s["win"] for s in calm])
        res["calm_n"] = len(calm)
        res["calm_skill"] = 1 - _brier([s["p_win"] for s in calm], [s["win"] for s in calm]) / cb if cb else 0.0
    rule = [s for s in test if s["f"]["depth"] >= rule_depth]
    res["rule_n"] = len(rule)
    res["rule_win"] = sum(s["win"] for s in rule) / len(rule) if rule else None
    res["rule_exp"] = sum(s["p_win0"] for s in rule) / len(rule) if rule else None
    edges = [0.0, 0.05, 0.10, 0.20, 0.35, 1.01]
    res["calib"] = []
    for lo, hi in zip(edges, edges[1:]):
        g = [s for s in test if lo <= s["p_win"] < hi]
        if g:
            res["calib"].append((lo, min(hi, 1.0), len(g), sum(s["p_win"] for s in g) / len(g), sum(s["win"] for s in g) / len(g)))
    return res


def report_walk_forward(res, log=print, why=None):
    if not res:
        log("  Eigen model: geen eerlijke toets mogelijk" + (": " + "; ".join(why) if why else " (te weinig metingen)") + ".")
        return
    log(f"  Eigen model, getraind op {res['n_train']} metingen (op {res['train_days']} verschillende dagen) tot {res['cut']}, "
        f"getoetst op {res['n_test']} metingen (op {res['test_days']} verschillende dagen) daarna, die het nooit zag:")
    names = {"depth": "onder gemiddelde", "mom14": "trend 14 dagen", "logp": "prijsniveau", "mkt30": "markt 30 dagen", "cv14": "onrust", "jumps": "sprongen"}
    log("    gewichten (positief = hoger kenmerk, hogere verwachte stijging): " + ", ".join(f"{names[k]} {v * 100:+.1f}" for k, v in res["coef"].items()))
    log(f"    Alles hieronder wordt vergeleken met het kostenbewuste basismodel: dezelfde verzend- en verkoopkosten en hetzelfde prijsniveau, maar zonder enig kenmerk.")
    log(f"    winst na kosten bij alle testmomenten: {res['win_rate'] * 100:.1f}%. De 20% waar het model het meest méér verwacht dan het basismodel ({res['top_n']}): "
        f"basismodel verwachtte {res['top_exp'] * 100:.1f}%, echt {res['top_win'] * 100:.1f}% (z = {res['z']:.1f}); de rest: verwacht {res['rest_exp'] * 100:.1f}%, echt {res['rest_win'] * 100:.1f}%")
    if res.get("rule_win") is not None:
        log(f"    ter vergelijking, de simpele regel 'minstens 15% onder het gemiddelde' ({res['rule_n']} momenten): basismodel verwachtte {res['rule_exp'] * 100:.1f}%, echt {res['rule_win'] * 100:.1f}%")
    log(f"    Brier-voorsprong op het basismodel (0 = geen, positief = beter): winst {res['skill_win'] * 100:+.1f}%, +10% {res['skill_up'] * 100:+.1f}%")
    if res.get("calm_n"):
        log(f"    alleen rustige reeksen (zonder sprongen, {res['calm_n']} metingen): Brier-voorsprong op het basismodel {res['calm_skill'] * 100:+.1f}%")
    log("    kalibratie van p_win (voorspeld -> echt, per groep):  " + "  ".join(f"{lo * 100:.0f}-{hi * 100:.0f}%: n={n} {pm * 100:.0f}->{rl * 100:.0f}%" for lo, hi, n, pm, rl in res["calib"]))
    if res["skill_win"] > 0 and res["z"] >= 2:
        verdict = "Het model weet op ongeziene data meer dan het kostenbewuste basismodel."
    else:
        verdict = "Geen aantoonbaar voordeel op het kostenbewuste basismodel."
    log(f"    Oordeel: {verdict} (let op: metingen van dezelfde dag delen dezelfde markt, dus {res['test_days']} testdagen zijn minder bewijs dan {res['n_test']} metingen doen lijken; z >= 2 is nodig, niet genoeg.)")


# ---------------- uitsplitsingen ----------------
def _line(label, g, base_win, base_up):
    if not g:
        return f"  {label:<28}{0:>5}"
    w = sum(s["win"] for s in g) / len(g)
    u = sum(s["up"] for s in g) / len(g)
    return f"  {label:<28}{len(g):>5}  na 30d +10%: {u * 100:5.1f}% ({(u - base_up) * 100:+.0f})  winst na kosten: {w * 100:5.1f}% ({(w - base_win) * 100:+.0f})"


def report_splits(samples, log=print):
    """Waar werkt 'onder het gemiddelde' wel en niet: per prijsklasse, hoe diep, bij welke markt, en bij springerige reeksen."""
    if not samples:
        log("  Uitsplitsing: nog te weinig metingen.")
        return
    base_win = sum(s["win"] for s in samples) / len(samples)
    base_up = sum(s["up"] for s in samples) / len(samples)
    below = lambda s, pct=0.15: s["f"]["_vs"] <= -pct
    log(f"  Uitsplitsing van 'onder het gemiddelde' (minstens 15% onder het 6-maandsgemiddelde); tussen haakjes het verschil met alle {len(samples)} metingen:")
    log("  per prijsklasse (de verzend- en verkoopkosten wegen bij goedkope kaarten zwaarder); de tweede regel vergelijkt met de eigen klasse:")
    for label, lo, hi in (("onder € 25", 0, 25), ("€ 25 tot € 100", 25, 100), ("vanaf € 100", 100, 1e9)):
        cls = [s for s in samples if lo <= s["p0"] < hi]
        cw = sum(s["win"] for s in cls) / len(cls) if cls else 0
        cu = sum(s["up"] for s in cls) / len(cls) if cls else 0
        log(_line(label + ", alle", cls, base_win, base_up))
        log(_line("   waarvan onder gem.", [s for s in cls if below(s)], cw, cu))
    log("  hoe diep onder het gemiddelde:")
    for pct in (0.15, 0.25, 0.35):
        log(_line(f"minstens {int(pct * 100)}% eronder", [s for s in samples if below(s, pct)], base_win, base_up))
    log("  marktbeweging van de laatste 30 dagen (mediaan van alle kaarten), alleen 'onder gemiddelde':")
    for label, ok in (("markt daalt (< -3%)", lambda m: m is not None and m < -0.03), ("markt vlak (-3% tot +3%)", lambda m: m is not None and -0.03 <= m <= 0.03),
                      ("markt stijgt (> +3%)", lambda m: m is not None and m > 0.03)):
        log(_line(label, [s for s in samples if below(s) and ok(s["f"]["_mkt"])], base_win, base_up))
    log("  springerige reeksen (2 of meer dagen met een sprong van > 50% in 60 dagen), alleen 'onder gemiddelde':")
    log(_line("springerig", [s for s in samples if below(s) and s["f"]["_jn"] >= 2], base_win, base_up))
    log(_line("rustig", [s for s in samples if below(s) and s["f"]["_jn"] < 2], base_win, base_up))


# ---------------- elke nacht: voorspellingen vastleggen ----------------
def shadow(series, today, log=print, min_samples=300):
    """Traint op alle beschikbare metingen en voorspelt voor elke kaart van vandaag. Geeft {product_id: {kolommen voor card_signals}}."""
    from signals import price_signals
    samples = collect_samples(series)
    model = fit(samples)
    if not model or model["n"] < min_samples:
        log(f"Eigen model: te weinig metingen om te trainen ({len(samples)}; minimaal {min_samples}); vandaag geen voorspellingen vastgelegd.")
        return {}
    mk = market_returns(series)
    out = {}
    for pid, pts in series.items():
        pp = price_signals(pts)
        if not pp:
            continue
        pr = predict(model, pp, pts, mk)
        if pr:
            out[pid] = {"p_win": round(pr["p_win"], 4), "p_win0": round(pr["p_win0"], 4), "p_up10": round(pr["p_up10"], 4),
                        "exp_ret": round(pr["exp_ret"], 4), "model": VERSION}
    hi = sum(1 for v in out.values() if v["p_win"] >= 0.30)
    log(f"Eigen model ({VERSION}): getraind op {model['n']} metingen; vandaag voorspeld voor {len(out)} kaarten, waarvan {hi} met minstens 30% kans op winst na kosten.")
    rows = [s for s in samples if s.get("f")]
    if rows and out:
        tr_pred = sum(prob_ge(model, s["f"], breakeven_log(s["p0"])) for s in rows) / len(rows)
        tr_real = sum(1 for s in rows if s["win"]) / len(rows)
        today_pred = sum(v["p_win"] for v in out.values()) / len(out)
        log(f"  ter controle: op de trainingsmetingen voorspelde het model gemiddeld {tr_pred * 100:.0f}% (echt {tr_real * 100:.0f}%); vandaag voorspelt het gemiddeld {today_pred * 100:.0f}%. "
            "Staat dat laatste veel hoger, dan wijken de kaarten van vandaag af van wat het model kent.")
    return out


def evaluate_stored(store, today, series, log=print, horizon=HORIZON):
    """De echte toets: voorspellingen van minstens 'horizon' dagen geleden (zoals opgeslagen in card_signals) naast wat er daarna gebeurde,
    vergeleken met het kostenbewuste basismodel (p_win0) dat ze toen ook kregen."""
    cutoff = (_d(today) - timedelta(days=horizon + 1)).isoformat()
    try:
        rows = store.select("card_signals", {"select": "product_id,date,price,p_win,p_win0,p_up10", "date": f"lte.{cutoff}", "order": "date.asc"})
    except Exception as e:
        log(f"  Opgeslagen voorspellingen: nog niet te lezen ({type(e).__name__}); is supabase/schema.sql opnieuw gedraaid (kolommen p_win en p_win0)?")
        return None
    rows = [r for r in rows if r.get("p_win") is not None and r.get("price")]
    if not rows:
        log("  Opgeslagen voorspellingen: er zijn er nog geen van minstens 31 dagen oud; deze toets begint zodra de eerste 30 dagen voorbij zijn.")
        return None
    done = []
    for r in rows:
        pts = series.get(r["product_id"])
        if not pts:
            continue
        target = (_d(r["date"]) + timedelta(days=horizon)).isoformat()
        if pts[-1][0] < target:
            continue
        later = [(d, p) for d, p in pts if r["date"] < d <= target]
        if not later:
            continue
        p0, end = float(r["price"]), later[-1][1]
        done.append({"p_win": float(r["p_win"]), "p_win0": float(r["p_win0"]) if r.get("p_win0") is not None else None, "win": net_profit(p0, end) > 0})
    if not done:
        log("  Opgeslagen voorspellingen: geen enkele kon al worden vergeleken met de prijs 30 dagen later.")
        return None
    n = len(done)
    out = {"n": n, "win_rate": sum(d["win"] for d in done) / n}
    log(f"  Opgeslagen voorspellingen (echt vooruit getoetst): {n} voorspellingen van minstens 31 dagen oud; winst na kosten bij {out['win_rate'] * 100:.1f}%.")
    both = [d for d in done if d["p_win0"] is not None]
    if len(both) >= 20:
        ranked = sorted(both, key=lambda d: -(d["p_win"] - d["p_win0"]))
        k = max(5, len(ranked) // 5)
        top, rest = ranked[:k], ranked[k:]
        var = sum(d["p_win0"] * (1 - d["p_win0"]) for d in top) / len(top)
        top_win, top_exp = sum(d["win"] for d in top) / len(top), sum(d["p_win0"] for d in top) / len(top)
        z = (top_win - top_exp) / math.sqrt(max(var, 1e-9) / len(top))
        bb = _brier([d["p_win0"] for d in both], [d["win"] for d in both])
        skill = 1 - _brier([d["p_win"] for d in both], [d["win"] for d in both]) / bb if bb else 0.0
        out.update({"top_win": top_win, "top_exp": top_exp, "z": z, "skill": skill})
        log(f"    de 20% waar het model het meest méér verwachtte dan het basismodel ({len(top)}): basismodel {top_exp * 100:.1f}%, echt {top_win * 100:.1f}% (z = {z:.1f}); "
            f"de rest: basismodel {sum(d['p_win0'] for d in rest) / max(len(rest), 1) * 100:.1f}%, echt {sum(d['win'] for d in rest) / max(len(rest), 1) * 100:.1f}%; "
            f"Brier-voorsprong op het basismodel {skill * 100:+.1f}%")
    edges = [0.0, 0.05, 0.10, 0.20, 0.35, 1.01]
    cells = []
    for lo, hi in zip(edges, edges[1:]):
        g = [d for d in done if lo <= d["p_win"] < hi]
        if g:
            cells.append(f"{lo * 100:.0f}-{min(hi, 1) * 100:.0f}%: n={len(g)} {sum(d['p_win'] for d in g) / len(g) * 100:.0f}->{sum(d['win'] for d in g) / len(g) * 100:.0f}%")
    log("    kalibratie (voorspeld -> echt): " + "  ".join(cells))
    return out
