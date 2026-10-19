"""Testlab voor de kansen: elke nacht strijden verschillende voorspelmethodes tegen elkaar op de Near Mint-geschiedenis.

Hoe het werkt (zonder in de toekomst te kijken):
  1. Testmomenten: voor elke kaart met Near Mint-geschiedenis, elke 7 dagen een moment t. Het model ziet alleen de prijzen
     tot en met t (60 dagen terug), de uitkomst is de prijs rond t+30 (mediaan van dag 28-35, zodat één verkoper die
     even spotgoedkoop of duur staat het niet beslist). Doel: steeg de kaart minstens 10% (en apart: 20%)?
  2. Kenmerken per moment: afstand tot de normale prijs, trend over 7 en 30 dagen, beweeglijkheid, sprongen, prijsniveau,
     afstand tot het minimum en maximum, aantal prijspunten, leeftijd van de set, herdrukken, en de hele markt.
  3. Methodes: 'basis' (voor elke kaart hetzelfde percentage), 'tabel' (zoals nu in de app: trend x beweeglijkheid),
     'afstand' (afstand tot normaal x beweeglijkheid), 'logistisch' (alle kenmerken, lineair) en 'boom' (gradient boosting,
     alle kenmerken, ook niet-lineair).
  4. Eerlijk toetsen, op twee manieren:
       kaarten:  trainen op de ene helft van de kaarten, meten op de andere helft (welke KAARTEN stijgen?)
       tijd:     trainen op de vroegste momenten, meten op de laatste (werkt het ook later nog?)
     Maatstaven: Brier-vaardigheid tegen 'basis' (boven 0 = weet iets), en vooral de toplijst: van de 5% kaarten met de
     hoogste kans, hoeveel stegen er echt minstens 10%? Dat is precies de lijst die de app moet tonen.
  5. De winnaar (beste toplijst op de kaarten-toets, mits beter dan basis op beide toetsen) wordt op alles getraind en
     geeft de kansen voor vandaag: reports/lab_top.json en een verslag reports/lab.md (branch reports).

    python lab.py --out-dir ../reports
"""
import argparse
import json
import math
import os
import random
from datetime import date, timedelta
from statistics import median

import analysis

STEP_DAYS = 7
HIST_DAYS = 60
H_START, H_END = 28, 35     # uitkomstvenster na t
MIN_POINTS = 15             # prijspunten in de 60 dagen voor t
MIN_PRICE = 3.0
TARGETS = (0.10, 0.20)
TOP_FRAC = 0.05
FEATS = ["r_norm", "r_7", "r_30", "vol", "jumps", "lp", "r_min", "r_max", "n_pts", "age", "printings", "newer", "mkt_30"]


def _d(s):
    return date.fromisoformat(str(s)[:10])


def _med(xs):
    return median(xs) if xs else None


def card_moments(pts, info, today=None):
    """pts: [(date, prijs)] opgeschoond en gesorteerd. Geeft testmomenten (met uitkomst) of, met today, alleen het moment van vandaag."""
    if len(pts) < MIN_POINTS:
        return []
    days = [_d(d) for d, _ in pts]
    px = [p for _, p in pts]

    def window(a, b):   # prijzen met a <= dag <= b
        return [p for d, p in zip(days, px) if a <= d <= b]

    def feats(t):
        hist = window(t - timedelta(days=HIST_DAYS), t)
        last = window(t - timedelta(days=7), t)
        if len(hist) < MIN_POINTS or not last:
            return None
        p0 = _med(last[-3:])
        if p0 < MIN_PRICE:
            return None
        norm = _med(window(t - timedelta(days=HIST_DAYS), t - timedelta(days=7)))
        p7 = _med(window(t - timedelta(days=10), t - timedelta(days=5)))
        p30 = _med(window(t - timedelta(days=35), t - timedelta(days=25)))
        lr = [math.log(b / a) for a, b in zip(hist, hist[1:]) if a > 0 and b > 0]
        vol = (sum(x * x for x in lr) / len(lr)) ** 0.5 if lr else 0.0
        rel = info.get("release")
        return {"p0": p0, "r_norm": p0 / norm if norm else 1.0, "r_7": p0 / p7 if p7 else 1.0, "r_30": p0 / p30 if p30 else 1.0,
                "vol": vol, "jumps": sum(1 for x in lr if abs(x) > 0.4), "lp": math.log(p0), "r_min": p0 / min(hist), "r_max": p0 / max(hist),
                "n_pts": len(hist), "age": math.log1p(max((t - rel).days, 0)) if rel else -1.0,
                "printings": float(info.get("printings") or 1), "newer": 1.0 if info.get("newer") else 0.0}

    if today:
        f = feats(today)
        return [{**f, "t": today.isoformat()}] if f else []
    out = []
    t = days[0] + timedelta(days=HIST_DAYS)
    end = days[-1] - timedelta(days=H_END)
    while t <= end:
        f = feats(t)
        if f:
            after = window(t + timedelta(days=H_START), t + timedelta(days=H_END))
            if len(after) >= 2:
                ret = _med(after) / f["p0"] - 1
                out.append({**f, "t": t.isoformat(), "ret": ret, **{f"up{int(k * 100)}": ret >= k for k in TARGETS}})
        t += timedelta(days=STEP_DAYS)
    return out


def add_market(moments):
    """Beweging van de hele markt op elk moment: mediaan van r_30 over alle kaarten die dag."""
    by = {}
    for m in moments:
        by.setdefault(m["t"], []).append(m["r_30"])
    mk = {t: median(v) for t, v in by.items()}
    for m in moments:
        m["mkt_30"] = mk[m["t"]]
    return moments


# ------------------------------------------------------------------ methodes: fit(train, target) -> predict(rows) -> kansen
def _bins(x, bounds):
    return sum(1 for b in bounds if x >= b)


def table_model(k1, b1, k2, b2, shrink=50):
    """Kans per vak (k1 x k2), naar het basispercentage getrokken als een vak weinig metingen heeft."""
    def fit(train, y):
        base = sum(y) / len(y)
        cnt = {}
        for m, yy in zip(train, y):
            c = cnt.setdefault((_bins(m[k1], b1), _bins(m[k2], b2)), [0, 0])
            c[0] += 1; c[1] += yy
        tab = {k: (h + shrink * base) / (n + shrink) for k, (n, h) in cnt.items()}
        return lambda rows: [tab.get((_bins(m[k1], b1), _bins(m[k2], b2)), base) for m in rows]
    return fit


def base_model(train, y):
    p = sum(y) / len(y)
    return lambda rows: [p] * len(rows)


def _X(rows):
    import numpy as np
    return np.array([[m[f] for f in FEATS] for m in rows], dtype=float)


def logit_model(train, y):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)).fit(_X(train), y)
    return lambda rows: list(clf.predict_proba(_X(rows))[:, 1])


def tree_model(train, y):
    from sklearn.ensemble import HistGradientBoostingClassifier
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=250, min_samples_leaf=80, l2_regularization=1.0,
                                         random_state=0).fit(_X(train), y)
    return lambda rows: list(clf.predict_proba(_X(rows))[:, 1])


VOL_B = (0.05, 0.12)
METHODS = {
    "basis": base_model,
    "tabel": table_model("r_30", (0.74, 0.90, 1.11, 1.35), "vol", VOL_B),
    "afstand": table_model("r_norm", (0.65, 0.80, 0.95, 1.10, 1.30), "vol", VOL_B),
    "logistisch": logit_model,
    "boom": tree_model,
}


# ------------------------------------------------------------------ toetsen
def score(p, y, rets):
    n = len(y)
    base = sum(y) / n
    br = sum((a - b) ** 2 for a, b in zip(p, y)) / n
    order = sorted(range(n), key=lambda i: -p[i])
    k = max(1, int(n * TOP_FRAC))
    top = order[:k]
    return {"n": n, "brier": br, "base": base, "top_n": k, "top_hit": sum(y[i] for i in top) / k,
            "top_p": sum(p[i] for i in top) / k, "top_ret": median(rets[i] for i in top)}


def evaluate(moments, target, split, seed=0):
    """split: 'kaarten' of 'tijd'. Geeft {methode: score} met vaardigheid tegen basis."""
    key = f"up{int(target * 100)}"
    if split == "kaarten":
        ids = sorted({m["pid"] for m in moments})
        random.Random(seed).shuffle(ids)
        test_ids = set(ids[: len(ids) // 2])
        train = [m for m in moments if m["pid"] not in test_ids]
        test = [m for m in moments if m["pid"] in test_ids]
    else:
        ts = sorted({m["t"] for m in moments})
        if len(ts) < 3:
            return {}
        cut = ts[int(len(ts) * 0.6)]
        train = [m for m in moments if m["t"] < cut]
        test = [m for m in moments if m["t"] >= cut]
    if len(train) < 200 or len(test) < 200:
        return {}
    y_tr, y_te = [m[key] for m in train], [m[key] for m in test]
    rets = [m["ret"] for m in test]
    res = {}
    for name, fit in METHODS.items():
        try:
            p = fit(train, y_tr)(test)
        except Exception as e:   # bijv. scikit-learn ontbreekt
            res[name] = {"error": f"{type(e).__name__}: {e}"[:120]}
            continue
        res[name] = score(p, y_te, rets)
    b = res.get("basis", {}).get("brier")
    for r in res.values():
        if "brier" in r:
            r["skill"] = 1 - r["brier"] / b if b else 0.0
    return res


def choose(results):
    """Winnaar: beste toplijst (kaarten-toets) onder de methodes die op beide toetsen beter dan basis zijn."""
    ok = []
    for name in METHODS:
        if name == "basis":
            continue
        a, b = results["kaarten"].get(name, {}), results["tijd"].get(name, {})
        if a.get("skill", -1) > 0 and b.get("skill", -1) > 0:
            ok.append((a["top_hit"], name))
    return max(ok)[1] if ok else None


# ------------------------------------------------------------------ gegevens
def load(store, today):
    sets = {s["set_id"]: s for s in store.select("sets", {"select": "set_id,release_date"})}
    prods = {p["product_id"]: p for p in store.select("products", {"select": "product_id,name,set_id,number,printings,newer_printing", "kind": "eq.card"})}
    since = (today - timedelta(days=200)).isoformat()
    recent = (today - timedelta(days=7)).isoformat()
    ids = sorted({r["product_id"] for r in store.select("prices", {"select": "product_id", "source": "eq.pkmnprices", "grade_key": "eq.nm",
                                                                    "date": f"gte.{recent}"})} & set(prods))
    old = sorted({r["product_id"] for r in store.select("prices", {"select": "product_id", "source": "eq.pkmnprices", "grade_key": "eq.nm",
                                                                    "date": f"lt.{(today - timedelta(days=HIST_DAYS + H_END)).isoformat()}"})} & set(prods))
    ids = sorted(set(ids) | set(old))
    series = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        rows = {}
        for r in store.select("prices", {"select": "product_id,date,price", "source": "eq.pkmnprices", "grade_key": "eq.nm",
                                         "product_id": f"in.({','.join(chunk)})", "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
            if r.get("price") and float(r["price"]) > 0:
                rows.setdefault(r["product_id"], []).append({"date": str(r["date"])[:10], "price": float(r["price"])})
        for pid, pts in rows.items():
            kept, _ = analysis.clean_nm_rows(pts)
            series[pid] = [(r["date"], r["price"]) for r in kept]
    info = {}
    for pid, p in prods.items():
        st = sets.get(p.get("set_id")) or {}
        info[pid] = {"release": _d(st["release_date"]) if st.get("release_date") else None, "printings": p.get("printings"),
                     "newer": p.get("newer_printing"), "name": p.get("name"), "set_id": p.get("set_id"), "number": p.get("number")}
    return series, info


def run(series, info, today):
    moments, now = [], []
    for pid, pts in series.items():
        for m in card_moments(pts, info.get(pid, {})):
            m["pid"] = pid
            moments.append(m)
        for m in card_moments(pts, info.get(pid, {}), today=today):
            m["pid"] = pid
            now.append(m)
    add_market(moments)
    mk_now = median([m["r_30"] for m in now]) if now else 1.0
    for m in now:
        m["mkt_30"] = mk_now
    out = {"today": today.isoformat(), "moments": len(moments), "cards": len({m["pid"] for m in moments}),
           "dates": sorted({m["t"] for m in moments}), "now_cards": len(now), "targets": {}}
    for tg in TARGETS:
        key = f"up{int(tg * 100)}"
        res = {"kaarten": evaluate(moments, tg, "kaarten"), "tijd": evaluate(moments, tg, "tijd")}
        win = choose(res) if res["kaarten"] and res["tijd"] else None
        top, sets = [], []
        if win and now:
            p = METHODS[win](moments, [m[key] for m in moments])(now)
            # sets met veel kansrijke kaarten: zo kun je bij één verkoper meerdere kaarten kopen en verzending sparen
            cut = sorted(p, reverse=True)[max(0, int(len(p) * 0.10) - 1)]
            by_set = {}
            for m, pp in zip(now, p):
                if pp >= cut:
                    sid = info.get(m["pid"], {}).get("set_id")
                    if sid:
                        by_set.setdefault(sid, []).append(pp)
            sets = sorted(({"set_id": k, "cards": len(v), "avg_chance": round(sum(v) / len(v), 3)} for k, v in by_set.items()),
                          key=lambda x: (-x["cards"], -x["avg_chance"]))[:20]
            for m, pp in sorted(zip(now, p), key=lambda x: -x[1])[:50]:
                i = info.get(m["pid"], {})
                top.append({"product_id": m["pid"], "name": i.get("name"), "set_id": i.get("set_id"), "number": i.get("number"),
                            "price": round(m["p0"], 2), "chance": round(pp, 3)})
        out["targets"][key] = {"results": res, "winner": win, "top": top, "sets": sets,
                               "proof": res["kaarten"].get(win, {}) if win else None}
    return out


def report(o):
    pct = lambda x: f"{x:.0%}" if x is not None else "–"
    L = [f"# Testlab kansen ({o['today']})", "",
         f"{o['moments']} testmomenten van {o['cards']} kaarten, op {len(o['dates'])} data "
         f"({o['dates'][0] if o['dates'] else '-'} t/m {o['dates'][-1] if o['dates'] else '-'}). Vandaag te beoordelen: {o['now_cards']} kaarten.", "",
         "Toplijst = de 5% kaarten met de hoogste kans. 'Stegen echt' is hoeveel daarvan na 30 dagen echt minstens zoveel hoger stonden. "
         "Vaardigheid boven 0 = de methode weet iets dat 'voor elke kaart hetzelfde percentage' niet weet.", ""]
    for key, t in o["targets"].items():
        L += [f"## Kans op +{key[2:]}% in 30 dagen", ""]
        for split, res in t["results"].items():
            if not res:
                L += [f"Toets op {split}: te weinig metingen.", ""]
                continue
            base = next((r["base"] for r in res.values() if "base" in r), None)
            L += [f"**Toets op {split}** (basis: {pct(base)} van alle kaarten steeg zoveel)", "",
                  "| methode | vaardigheid | toplijst: kans gezegd | toplijst: stegen echt | toplijst: mediaan rendement |", "|---|---|---|---|---|"]
            for name, r in res.items():
                if "error" in r:
                    L.append(f"| {name} | fout: {r['error']} | | | |")
                else:
                    L.append(f"| {name} | {r['skill']:+.1%} | {pct(r['top_p'])} | {pct(r['top_hit'])} ({r['top_n']}) | {r['top_ret']:+.1%} |")
            L.append("")
        if t["winner"]:
            pr = t["proof"]
            L += [f"**Winnaar: {t['winner']}.** In de toets stegen {pct(pr['top_hit'])} van de toplijst minstens {key[2:]}% (basis {pct(pr['base'])}).", ""]
            if t["top"]:
                L += ["Toplijst van vandaag (eerste 15):", "", "| kaart | prijs | kans |", "|---|---|---|"]
                L += [f"| {x['name']} ({x['set_id']} {x['number']}) | EUR {x['price']:.2f} | {pct(x['chance'])} |" for x in t["top"][:15]]
                L.append("")
            if t.get("sets"):
                L += ["Sets met de meeste kansrijke kaarten (bij de 10% hoogste kansen van vandaag):", "", "| set | kaarten | gemiddelde kans |", "|---|---|---|"]
                L += [f"| {x['set_id']} | {x['cards']} | {pct(x['avg_chance'])} |" for x in t["sets"][:10]]
                L.append("")
        else:
            L += ["**Geen winnaar:** geen enkele methode was op beide toetsen beter dan voor elke kaart hetzelfde percentage. Nog geen toplijst.", ""]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="../reports")
    args = ap.parse_args()
    from store import SupabaseStore
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today()
    series, info = load(store, today)
    o = run(series, info, today)
    os.makedirs(args.out_dir, exist_ok=True)
    text = report(o)
    with open(os.path.join(args.out_dir, "lab.md"), "w") as f:
        f.write(text)
    slim = {"today": o["today"], **{k: {"winner": t["winner"], "proof": t["proof"], "top": t["top"], "sets": t["sets"]} for k, t in o["targets"].items()}}
    with open(os.path.join(args.out_dir, "lab_top.json"), "w") as f:
        json.dump(slim, f, indent=1)
    print(text)


if __name__ == "__main__":
    main()
