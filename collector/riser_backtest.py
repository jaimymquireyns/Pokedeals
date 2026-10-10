"""Backtest 'gestage stijgers': blijven kaarten die al maanden rustig stijgen daarna doorstijgen?
Alleen samenvattingen (geen persoonlijke gegevens) naar ../reports/riser_backtest.md."""
import math, os, statistics as st
from collections import defaultdict
from datetime import date, timedelta
from store import SupabaseStore

store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
out = []; p = lambda *a: (print(*a), out.append(" ".join(str(x) for x in a)))

cards = store.select("v_search", {"select": "product_id,price", "kind": "eq.card", "price": "gte.5"})
ids = [c["product_id"] for c in cards]
p(f"# Backtest gestage stijgers\n\nKaarten met prijs >= 5 euro: {len(ids)}")
# dekking per (grade_key, bron) op een steekproef
from collections import Counter
smp = ids[::max(1, len(ids)//300)][:300]
cov = defaultdict(list)
for i in range(0, len(smp), 60):
    rows = store.select("prices", {"select": "product_id,date,source,grade_key", "product_id": "in.(" + ",".join(f'"{x}"' for x in smp[i:i+60]) + ")"})
    g = defaultdict(list)
    for r in rows: g[(r["grade_key"], r["source"], r["product_id"])].append(r["date"])
    for (gk, src, pid), ds in g.items(): cov[(gk, src)].append((len(ds), min(ds)))
for k, v in sorted(cov.items(), key=lambda kv: -len(kv[1])):
    v.sort(); p(f"- dekking {k}: {len(v)} kaarten, dagen mediaan {v[len(v)//2][0]}, max {v[-1][0]}, vroegste {min(x[1] for x in v)}")
GK = os.environ.get("GK", "nm")
series = {}
for i in range(0, len(ids), 80):
    chunk = ids[i:i + 80]
    rows = store.select("prices", {"select": "product_id,date,source,price", "grade_key": f"eq.{GK}",
                                   "product_id": "in.(" + ",".join(f'"{x}"' for x in chunk) + ")", "order": "product_id.asc,date.asc"})
    by = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        if r["price"] and float(r["price"]) > 0:
            by[r["product_id"]][r["source"]][r["date"]] = float(r["price"])
    for pid, srcs in by.items():
        merged = {}
        for src in sorted(srcs, key=lambda s: len(srcs[s])):   # langste reeks wint, kortere vullen gaten
            merged.update({d: v for d, v in srcs[src].items()})
        series[pid] = merged
lens = sorted(len(s) for s in series.values())
alld = [d for s in series.values() for d in s]
p(f"Reeksen: {len(series)}; dagen per kaart mediaan {lens[len(lens)//2] if lens else 0}, max {lens[-1] if lens else 0}; vroegste datum {min(alld) if alld else '-'}, laatste {max(alld) if alld else '-'}")

def daily(s):
    ds = sorted(s); d0, d1 = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
    out_, last, gap = {}, None, 0
    d = d0
    while d <= d1:
        k = d.isoformat()
        if k in s: last, gap = s[k], 0
        else: gap += 1
        if last is not None and gap <= 7: out_[d] = last
        d += timedelta(days=1)
    return out_

def reg(xs, ys):
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0: return 0, 0
    b = sxy / sxx; ssr = sum((y - my - b * (x - mx)) ** 2 for x, y in zip(xs, ys)); sst = sum((y - my) ** 2 for y in ys)
    return b, (1 - ssr / sst) if sst > 0 else 0

LOOK, HS = int(os.environ.get("LOOK", 45)), tuple(int(x) for x in os.environ.get("HS", "14,30").split(","))
obs = []
for pid, s in series.items():
    if len(s) < LOOK // 2 + 20: continue
    dd = daily(s); days = sorted(dd)
    if len(days) < LOOK + 30: continue
    first, last = days[0], days[-1]
    t = first + timedelta(days=LOOK)
    while t <= last - timedelta(days=30):
        if t in dd:
            win = [(k, dd[k]) for k in (t - timedelta(days=j) for j in range(LOOK, -1, -3)) if k in dd]
            if len(win) >= LOOK // 6:
                xs = [(k - t).days / 30 for k, _ in win]; ys = [math.log(v) for _, v in win]
                slope, r2 = reg(xs, ys)
                pt = dd[t]
                def back(n):
                    k = t - timedelta(days=n); return dd.get(k)
                p30 = back(30)
                jumps = []
                for j in range(0, LOOK - 14, 3):
                    k = t - timedelta(days=j); k0 = k - timedelta(days=14)
                    if k in dd and k0 in dd: jumps.append(dd[k] / dd[k0])
                maxjump = max(jumps) if jumps else 1
                fut = {h: dd.get(t + timedelta(days=h)) for h in HS}
                obs.append({"pid": pid, "t": t, "p": pt, "slope": slope, "r2": r2, "r30": (pt / p30 - 1) if p30 else None, "jump": maxjump, "fut": fut})
        t += timedelta(days=7)
p(f"Meetmomenten: {len(obs)} (elke 14 dagen per kaart, met {LOOK} dagen verleden)\n")

def stats(name, group):
    p(f"## {name}: {len(group)} momenten, {len({o['pid'] for o in group})} kaarten")
    for h in HS:
        rs = [o["fut"][h] / o["p"] - 1 for o in group if o["fut"][h]]
        if len(rs) < 20: p(f"- na {h} dagen: te weinig gegevens ({len(rs)})"); continue
        rs.sort()
        p(f"- na {h} dagen (n={len(rs)}): mediaan {st.median(rs):+.1%}, gemiddeld {st.mean(rs):+.1%}, "
          f">= +10%: {sum(r >= .10 for r in rs) / len(rs):.0%}, >= +25%: {sum(r >= .25 for r in rs) / len(rs):.0%}, "
          f"verlies > 10%: {sum(r <= -.10 for r in rs) / len(rs):.0%}")
    p("")

stats("Alle kaarten (vergelijkingsbasis)", obs)
steady = [o for o in obs if o["slope"] >= 0.02 and o["r2"] >= 0.6 and o["jump"] < 1.25 and o["r30"] is not None and -0.05 <= o["r30"] <= 0.15]
stats("Gestage stijgers (>= +2%/maand, R2 >= 0.6, geen piek > 25% in 14 d, laatste maand -5..+15%)", steady)
strong = [o for o in steady if o["slope"] >= 0.04 and o["r2"] >= 0.75]
stats("Sterke gestage stijgers (>= +4%/maand, R2 >= 0.75)", strong)
fast = [o for o in obs if o["r30"] is not None and o["r30"] >= 0.25]
stats("Snelle stijgers (laatste maand >= +25%)", fast)
falling = [o for o in obs if o["slope"] <= -0.02 and o["r2"] >= 0.6]
stats("Gestage dalers (<= -2%/maand, R2 >= 0.6)", falling)
for lo, hi in ((5, 20), (20, 75), (75, 10**9)):
    g = [o for o in steady if lo <= o["p"] < hi]
    stats(f"Gestage stijgers, prijs {lo}-{hi if hi < 10**9 else '...'} euro", g)
# lijst van nu: gestage stijgers over de laatste LOOK dagen
names = {r["product_id"]: r for r in store.select("v_search", {"select": "product_id,name,set_name,number,price", "kind": "eq.card", "price": "gte.10"})}
now = []
for pid, s_ in series.items():
    if pid not in names: continue
    dd = daily(s_); days = sorted(dd)
    if not days: continue
    t = days[-1]
    win = [(k, dd[k]) for k in (t - timedelta(days=j) for j in range(LOOK, -1, -3)) if k in dd]
    if len(win) < LOOK // 6 or (t - win[0][0]).days < LOOK - 10: continue
    xs = [(k - t).days / 30 for k, _ in win]; ys = [math.log(v) for _, v in win]
    b, r2 = reg(xs, ys)
    jumps = [dd[k] / dd[k - timedelta(days=14)] for k in (t - timedelta(days=j) for j in range(0, LOOK - 14, 3)) if k in dd and (k - timedelta(days=14)) in dd]
    if b >= 0.02 and r2 >= 0.6 and (max(jumps) if jumps else 1) < 1.25:
        n = names[pid]; now.append((b * r2, b, r2, n))
now.sort(key=lambda x: -x[0])
p(f"\n## Gestage stijgers nu (laatste {LOOK} dagen, prijs >= 10 euro): {len(now)}\n")
p("| kaart | set | nr | prijs | stijging/maand | rechtlijnigheid |\n|---|---|---|---|---|---|")
for sc, b, r2, n in now[:60]:
    p(f"| {n['name']} | {n['set_name']} | {n['number']} | {float(n['price']):.2f} | {math.exp(b) - 1:+.1%} | {r2:.2f} |")
os.makedirs("../reports", exist_ok=True)
open("../reports/riser_backtest.md", "w").write("\n".join(out) + "\n")
