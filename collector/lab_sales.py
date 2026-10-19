"""Testlab op ECHTE VERKOPEN: kansen die één verkoper niet kan sturen.

Waarom apart van lab.py: de Near Mint-reeks (sinds 11 juni) is de goedkoopste aanbieding. Die springt mee met één verkoper, en
elke test daarop leek te mooi (zie README, 5-8 okt, en de controle in lab.md van 19 okt: 89-99% van de toplijst waren grillige,
dunne markten). Cardmarket geeft elke dag, voor elke kaart, gratis (via TCGdex, bron 'tcgdex'):
    price = trendprijs, avg1/avg7/avg30 = gemiddelde verkoopprijs van gisteren / 7 / 30 dagen, low = goedkoopste aanbieding.
Die bewaren we sinds 21 september. Een verkoopgemiddelde kan niemand met een vraagprijs verschuiven.

Uitkomst: steeg het 30-dagen-verkoopgemiddelde (avg30) van t naar t+30 met minstens 10% (en apart 20%)? Die twee vensters
overlappen niet: de verkopen van de 30 dagen voor t tegen die van de 30 dagen daarna.

Kenmerken op moment t (alleen wat op t bekend was): prijsniveau, recente verkopen tegen de maand (avg7/avg30, avg1/avg30),
trendprijs en goedkoopste aanbieding tegen de maand, verkocht gisteren of niet, beweging van de trend over 7 dagen,
leeftijd van de set, herdrukken, en de hele markt.

Toetsen zoals in lab.py: op de andere helft van de kaarten, en (zodra er genoeg dagen zijn) op latere dagen. Een methode telt
alleen als ze beter is dan 'voor elke kaart hetzelfde percentage'. Extra: wat had je verdiend met de toplijst, als je kocht tegen
de goedkoopste aanbieding plus verzending en later verkocht tegen het verkoopgemiddelde min commissie en verpakking?

    python lab_sales.py --out-dir ../reports
"""
import argparse
import json
import math
import os
import random
from datetime import date, timedelta
from statistics import median

import config

H = 30            # dagen vooruit
TOL = 3           # uitkomst mag tot zoveel dagen na t+30 liggen (de taak draait niet elke dag op precies hetzelfde moment)
STEP = 2          # om de zoveel dagen een testmoment per kaart
MIN_AVG30 = 3.0
TARGETS = (0.10, 0.20)
TOP_FRAC = 0.05
MIN_TIME_DAYS = 6
FEATS = ["lp", "r7", "r1", "has1", "rtrend", "rlow", "dtrend7", "age", "printings", "newer", "mkt7"]


def _d(s):
    return date.fromisoformat(str(s)[:10])


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def features(row, prev7, info):
    a30, a7 = _f(row.get("avg30")), _f(row.get("avg7"))
    if not a30 or a30 < MIN_AVG30 or not a7:
        return None
    a1, tr, lo = _f(row.get("avg1")), _f(row.get("price")), _f(row.get("low"))
    tr_prev = _f(prev7.get("price")) if prev7 else None
    rel = info.get("release")
    t = _d(row["date"])
    return {"a30": a30, "low": lo, "lp": math.log(a30), "r7": a7 / a30, "r1": (a1 / a30) if a1 else 1.0, "has1": 1.0 if a1 else 0.0,
            "rtrend": (tr / a30) if tr else 1.0, "rlow": (lo / a30) if lo else 1.0,
            "dtrend7": (tr / tr_prev) if tr and tr_prev else 1.0,
            "age": math.log1p(max((t - rel).days, 0)) if rel else -1.0,
            "printings": float(info.get("printings") or 1), "newer": 1.0 if info.get("newer") else 0.0}


def card_moments(rows, info, today=None):
    """rows: dagrijen van één kaart (bron tcgdex), gesorteerd. Geeft testmomenten met uitkomst, of met today het moment van vandaag."""
    by = {_d(r["date"]): r for r in rows}
    days = sorted(by)
    if not days:
        return []

    def near(t, back=0, fwd=0):
        for k in range(0, max(back, fwd) + 1):
            for d in ((t + timedelta(days=k)) if k <= fwd else None, (t - timedelta(days=k)) if k <= back else None):
                if d in by:
                    return by[d]
        return None

    if today:
        r = near(today, back=3)
        if not r:
            return []
        f = features(r, near(_d(r["date"]) - timedelta(days=7), back=2, fwd=2), info)
        return [{**f, "t": r["date"]}] if f else []
    out = []
    t = days[0]
    while t <= days[-1] - timedelta(days=H):
        r = by.get(t)
        if r:
            f = features(r, near(t - timedelta(days=7), back=2, fwd=2), info)
            later = near(t + timedelta(days=H), fwd=TOL)
            a30_later = _f(later.get("avg30")) if later else None
            if f and a30_later:
                ret = a30_later / f["a30"] - 1
                out.append({**f, "t": t.isoformat(), "ret": ret, "a30_later": a30_later,
                            **{f"up{int(k * 100)}": ret >= k for k in TARGETS}})
        t += timedelta(days=STEP)
    return out


def add_market(moments):
    by = {}
    for m in moments:
        by.setdefault(m["t"], []).append(m["r7"])
    mk = {t: median(v) for t, v in by.items()}
    for m in moments:
        m["mkt7"] = mk[m["t"]]


# ------------------------------------------------------------------ methodes
def _bins(x, bounds):
    return sum(1 for b in bounds if x >= b)


def table_model(k1, b1, k2, b2, shrink=50):
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
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=3000)).fit(_X(train), y)
    return lambda rows: list(clf.predict_proba(_X(rows))[:, 1])


def tree_model(train, y):
    from sklearn.ensemble import HistGradientBoostingClassifier
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=250, min_samples_leaf=200, l2_regularization=1.0,
                                         random_state=0).fit(_X(train), y)
    return lambda rows: list(clf.predict_proba(_X(rows))[:, 1])


METHODS = {
    "basis": base_model,
    "verkopen": table_model("r7", (0.85, 0.95, 1.05, 1.15), "lp", (math.log(10), math.log(30), math.log(100))),
    "aanbod": table_model("rlow", (0.6, 0.8, 0.95), "r7", (0.95, 1.05)),
    "logistisch": logit_model,
    "boom": tree_model,
}


# ------------------------------------------------------------------ toetsen
def trade_ret(m, fee=None):
    """Kopen tegen de goedkoopste aanbieding van toen (plus verzending), verkopen tegen het latere verkoopgemiddelde."""
    fee = config.DEFAULT_FEE_PCT if fee is None else fee
    buy = m["low"] if m.get("low") else m["a30"]
    cost = buy + config.ship_cost(buy)
    return (m["a30_later"] * (1 - fee / 100) - config.PACKAGING - cost) / cost


def score(p, y, test):
    n = len(y)
    base = sum(y) / n
    br = sum((a - b) ** 2 for a, b in zip(p, y)) / n
    order = sorted(range(n), key=lambda i: -p[i])
    k = max(1, int(n * TOP_FRAC))
    top = order[:k]
    tr = [trade_ret(test[i]) for i in top]
    tr_all = [trade_ret(m) for m in test]
    return {"n": n, "brier": br, "base": base, "top_n": k, "top_hit": sum(y[i] for i in top) / k, "top_p": sum(p[i] for i in top) / k,
            "top_ret": median(test[i]["ret"] for i in top), "top_trade": median(tr), "top_trade_win": sum(1 for x in tr if x > 0) / k,
            "all_trade": median(tr_all), "all_trade_win": sum(1 for x in tr_all if x > 0) / n}


def split(moments, how, seed=0):
    if how == "kaarten":
        ids = sorted({m["pid"] for m in moments})
        random.Random(seed).shuffle(ids)
        test_ids = set(ids[: len(ids) // 2])
        return [m for m in moments if m["pid"] not in test_ids], [m for m in moments if m["pid"] in test_ids]
    ts = sorted({m["t"] for m in moments})
    if len(ts) < MIN_TIME_DAYS:
        return [], []
    cut = ts[int(len(ts) * 0.6)]
    return [m for m in moments if m["t"] < cut], [m for m in moments if m["t"] >= cut]


def evaluate(moments, target, how):
    key = f"up{int(target * 100)}"
    train, test = split(moments, how)
    if len(train) < 500 or len(test) < 500:
        return {}
    y_tr, y_te = [m[key] for m in train], [m[key] for m in test]
    res = {}
    for name, fit in METHODS.items():
        try:
            res[name] = score(fit(train, y_tr)(test), y_te, test)
        except Exception as e:
            res[name] = {"error": f"{type(e).__name__}: {e}"[:120]}
    b = res.get("basis", {}).get("brier")
    for r in res.values():
        if "brier" in r:
            r["skill"] = 1 - r["brier"] / b if b else 0.0
    return res


def choose(res):
    """Winnaar: beste toplijst op de kaarten-toets, mits beter dan basis op de kaarten-toets én (als die er al is) op de tijd-toets."""
    ok = []
    for name in METHODS:
        if name == "basis":
            continue
        a = res["kaarten"].get(name, {})
        b = res["tijd"].get(name, {}) if res["tijd"] else None
        if a.get("skill", -1) > 0.01 and (b is None or b.get("skill", -1) > 0):
            ok.append((a["top_hit"], name))
    return max(ok)[1] if ok else None


# ------------------------------------------------------------------ gegevens en verslag
def load(store, today):
    sets = {s["set_id"]: s for s in store.select("sets", {"select": "set_id,name,release_date"})}
    prods = {p["product_id"]: p for p in store.select("products", {"select": "product_id,name,set_id,number,printings,newer_printing", "kind": "eq.card"})}
    rows = {}
    since = (today - timedelta(days=120)).isoformat()
    ids = sorted(prods)
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        for r in store.select("prices", {"select": "product_id,date,price,avg1,avg7,avg30,low", "source": "eq.tcgdex", "grade_key": "eq.raw",
                                         "product_id": "in.(" + ",".join(f'"{x}"' for x in chunk) + ")", "date": f"gte.{since}",
                                         "order": "product_id.asc,date.asc"}):
            rows.setdefault(r["product_id"], []).append(r)
    info = {}
    for pid, p in prods.items():
        st = sets.get(p.get("set_id")) or {}
        info[pid] = {"release": _d(st["release_date"]) if st.get("release_date") else None, "printings": p.get("printings"),
                     "newer": p.get("newer_printing"), "name": p.get("name"), "set_id": p.get("set_id"), "set_name": st.get("name"),
                     "number": p.get("number")}
    return rows, info


def run(rows, info, today):
    moments, now = [], []
    for pid, rs in rows.items():
        for m in card_moments(rs, info.get(pid, {})):
            m["pid"] = pid
            moments.append(m)
        for m in card_moments(rs, info.get(pid, {}), today=today):
            m["pid"] = pid
            now.append(m)
    add_market(moments)
    mk = median([m["r7"] for m in now]) if now else 1.0
    for m in now:
        m["mkt7"] = mk
    all_days = sorted({str(r["date"])[:10] for rs in rows.values() for r in rs})
    out = {"today": today.isoformat(), "cards_with_prices": len(rows), "price_days": [all_days[0], all_days[-1]] if all_days else None,
           "moments": len(moments), "cards": len({m["pid"] for m in moments}), "dates": sorted({m["t"] for m in moments}),
           "now_cards": len(now), "targets": {}}
    for tg in TARGETS:
        key = f"up{int(tg * 100)}"
        res = {"kaarten": evaluate(moments, tg, "kaarten"), "tijd": evaluate(moments, tg, "tijd")}
        win = choose(res) if res["kaarten"] else None
        top, sets = [], []
        if win and now:
            p = METHODS[win](moments, [m[key] for m in moments])(now)
            for m, pp in sorted(zip(now, p), key=lambda x: -x[1])[:50]:
                i = info.get(m["pid"], {})
                top.append({"product_id": m["pid"], "name": i.get("name"), "set_id": i.get("set_id"), "set_name": i.get("set_name"),
                            "number": i.get("number"), "sales_avg30": round(m["a30"], 2), "low": m["low"], "chance": round(pp, 3)})
            cut = sorted(p, reverse=True)[max(0, int(len(p) * 0.10) - 1)]
            by_set = {}
            for m, pp in zip(now, p):
                if pp >= cut and info.get(m["pid"], {}).get("set_id"):
                    by_set.setdefault(m["pid"] and info[m["pid"]]["set_id"], []).append(pp)
            sets = sorted(({"set_id": k, "set_name": (next((info[x]["set_name"] for x in info if info[x].get("set_id") == k), None)),
                            "cards": len(v), "avg_chance": round(sum(v) / len(v), 3)} for k, v in by_set.items()),
                          key=lambda x: (-x["cards"], -x["avg_chance"]))[:20]
        out["targets"][key] = {"results": res, "winner": win, "proof": res["kaarten"].get(win) if win else None, "top": top, "sets": sets}
    return out


def report(o):
    pct = lambda x: f"{x:.0%}" if x is not None else "–"
    L = [f"# Testlab op echte verkopen ({o['today']})", "",
         f"Cardmarket-verkoopgemiddelden van {o['cards_with_prices']} kaarten, van {o['price_days'][0] if o['price_days'] else '-'} "
         f"t/m {o['price_days'][1] if o['price_days'] else '-'}. Testmomenten met een uitkomst na {H} dagen: {o['moments']} "
         f"({o['cards']} kaarten, {len(o['dates'])} data{', ' + o['dates'][0] + ' t/m ' + o['dates'][-1] if o['dates'] else ''}). "
         f"Vandaag te beoordelen: {o['now_cards']} kaarten.", "",
         "Uitkomst: steeg het verkoopgemiddelde van 30 dagen (echte verkopen, niet te sturen met een vraagprijs). "
         "Handel = kopen tegen de goedkoopste aanbieding plus verzending, na 30 dagen verkopen tegen het verkoopgemiddelde min commissie en verpakking.", ""]
    if not o["moments"]:
        L += [f"Nog geen testmomenten: de eerste uitkomsten komen {H} dagen na de eerste dag met verkoopgemiddelden.", ""]
    for key, t in o["targets"].items():
        L += [f"## Kans dat de verkoopprijs +{key[2:]}% stijgt in 30 dagen", ""]
        for how, res in t["results"].items():
            if not res:
                L += [f"Toets op {how}: nog te weinig metingen" + (f" (vanaf {MIN_TIME_DAYS} data)." if how == "tijd" else "."), ""]
                continue
            base = next((r["base"] for r in res.values() if "base" in r), None)
            L += [f"**Toets op {how}** (basis: {pct(base)} steeg zoveel)", "",
                  "| methode | vaardigheid | toplijst: kans | stegen echt | mediaan stijging | handel: mediaan | handel: met winst |", "|---|---|---|---|---|---|---|"]
            for name, r in res.items():
                if "error" in r:
                    L.append(f"| {name} | fout: {r['error']} | | | | | |")
                else:
                    L.append(f"| {name} | {r['skill']:+.1%} | {pct(r['top_p'])} | {pct(r['top_hit'])} ({r['top_n']}) | {r['top_ret']:+.1%} | "
                             f"{r['top_trade']:+.1%} | {pct(r['top_trade_win'])} |")
            r0 = res.get("basis", {})
            if "all_trade" in r0:
                L += ["", f"Ter vergelijking, alle testkaarten: handel mediaan {r0['all_trade']:+.1%}, met winst {pct(r0['all_trade_win'])}."]
            L.append("")
        if t["winner"]:
            pr = t["proof"]
            L += [f"**Winnaar: {t['winner']}.** Toplijst in de toets: {pct(pr['top_hit'])} steeg minstens {key[2:]}% (basis {pct(pr['base'])}); "
                  f"handel met winst {pct(pr['top_trade_win'])}.", ""]
            if t["top"]:
                L += ["Toplijst van vandaag (eerste 15):", "", "| kaart | verkoopgemiddelde 30d | goedkoopste | kans |", "|---|---|---|---|"]
                L += [f"| {x['name']} ({x['set_name'] or x['set_id']} {x['number']}) | EUR {x['sales_avg30']:.2f} | "
                      f"{'EUR %.2f' % x['low'] if x['low'] else '–'} | {pct(x['chance'])} |" for x in t["top"][:15]]
                L.append("")
            if t["sets"]:
                L += ["Sets met de meeste kansrijke kaarten:", "", "| set | kaarten | gemiddelde kans |", "|---|---|---|"]
                L += [f"| {x['set_name'] or x['set_id']} | {x['cards']} | {pct(x['avg_chance'])} |" for x in t["sets"][:10]]
                L.append("")
        elif t["results"]["kaarten"]:
            L += ["**Geen winnaar:** geen methode is beter dan voor elke kaart hetzelfde percentage. Geen toplijst.", ""]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="../reports")
    args = ap.parse_args()
    from store import SupabaseStore
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today()
    rows, info = load(store, today)
    o = run(rows, info, today)
    text = report(o)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "lab_sales.md"), "w") as f:
        f.write(text)
    slim = {"today": o["today"], "moments": o["moments"], **{k: {"winner": t["winner"], "proof": t["proof"], "top": t["top"], "sets": t["sets"]}
                                                             for k, t in o["targets"].items()}}
    with open(os.path.join(args.out_dir, "lab_sales.json"), "w") as f:
        json.dump(slim, f, indent=1)
    print(text)


if __name__ == "__main__":
    main()
