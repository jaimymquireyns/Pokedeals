"""Verband tussen de Amerikaanse (TCGplayer, via PokemonPriceTracker: bron ppt_hist) en de Europese markt (Cardmarket Near Mint
via PkmnPrices; Cardmarket-trend via TCGdex). Per week: bewegen ze samen, en loopt de ene voor op de andere?"""
import math
import os
import sys
from datetime import date
from statistics import median

from store import SupabaseStore

store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
L = ["# Amerikaanse tegenover Europese markt", ""]


def load(source, grade):
    out = {}
    for r in store.select("prices", {"select": "product_id,date,price", "source": f"eq.{source}", "grade_key": f"eq.{grade}", "order": "product_id.asc,date.asc"}):
        if r.get("price") and float(r["price"]) > 0:
            out.setdefault(r["product_id"], []).append((str(r["date"])[:10], float(r["price"])))
    return out


def weekly(series):
    w = {}
    for d, p in series:
        y, wk, _ = date.fromisoformat(d).isocalendar()
        w.setdefault((y, wk), []).append(p)
    return {k: median(v) for k, v in w.items()}


def corr(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


us = load("tcgplayer", "us")
L.append(f"- Amerikaanse geschiedenis (TCGplayer via PkmnPrices): {len(us)} kaarten" + (f", van {min(s[0][0] for s in us.values())} tot {max(s[-1][0] for s in us.values())}" if us else ""))
eu_nm = load("pkmnprices", "nm") if us else {}
eu_tr = load("tcgdex", "raw") if us else {}
for name, eu in (("Cardmarket Near Mint (PkmnPrices)", eu_nm), ("Cardmarket trend (TCGdex)", eu_tr)):
    both = sorted(set(us) & set(eu))
    L += ["", f"## Tegenover {name}", "", f"- kaarten met beide reeksen: {len(both)}"]
    if not both:
        continue
    pooled = {lag: ([], []) for lag in range(-3, 4)}   # lag > 0: Amerika week t tegenover Europa week t+lag (Amerika loopt voor)
    mkt_us, mkt_eu, ratios = {}, {}, []
    for pid in both:
        wu, we = weekly(us[pid]), weekly(eu[pid])
        weeks = sorted(set(wu) | set(we))
        ru = {weeks[i]: math.log(wu[weeks[i]] / wu[weeks[i - 1]]) for i in range(1, len(weeks)) if weeks[i] in wu and weeks[i - 1] in wu}
        re_ = {weeks[i]: math.log(we[weeks[i]] / we[weeks[i - 1]]) for i in range(1, len(weeks)) if weeks[i] in we and weeks[i - 1] in we}
        idx = {w: i for i, w in enumerate(weeks)}
        for w, x in ru.items():
            mkt_us.setdefault(w, []).append(x)
            for lag in pooled:
                j = idx[w] + lag
                if 0 <= j < len(weeks) and weeks[j] in re_ and abs(x) < 1 and abs(re_[weeks[j]]) < 1:
                    pooled[lag][0].append(x); pooled[lag][1].append(re_[weeks[j]])
        for w, x in re_.items():
            mkt_eu.setdefault(w, []).append(x)
        common = set(wu) & set(we)
        if common:
            ratios.append(median(we[w] / wu[w] for w in common))
    L.append(f"- prijsniveau: Europa is gemiddeld {median(ratios):.2f}x de Amerikaanse prijs (in euro), mediaan over {len(ratios)} kaarten")
    L.append("- per kaart, week op week (correlatie, 1 = perfect samen, 0 = geen verband):")
    for lag, (xs, ys) in pooled.items():
        c = corr(xs, ys)
        what = "zelfde week" if lag == 0 else (f"Amerika {lag} week eerder" if lag > 0 else f"Europa {-lag} week eerder")
        L.append(f"  - {what}: {('%.2f' % c) if c is not None else '–'} (n={len(xs)})")
    wk = sorted(set(mkt_us) & set(mkt_eu))
    mu = [median(mkt_us[w]) for w in wk]; me = [median(mkt_eu[w]) for w in wk]
    L.append(f"- hele markt (mediaan van alle kaarten per week), {len(wk)} weken:")
    for lag in (-2, -1, 0, 1, 2):
        xs = [mu[i] for i in range(len(wk)) if 0 <= i + lag < len(wk)]
        ys = [me[i + lag] for i in range(len(wk)) if 0 <= i + lag < len(wk)]
        c = corr(xs, ys) if len(xs) >= 6 else None
        what = "zelfde week" if lag == 0 else (f"Amerika {lag} week eerder" if lag > 0 else f"Europa {-lag} week eerder")
        L.append(f"  - {what}: {('%.2f' % c) if c is not None else '–'} (weken={len(xs)})")
text = "\n".join(L) + "\n"
os.makedirs("../reports", exist_ok=True)
open(sys.argv[1] if len(sys.argv) > 1 else "../reports/diag_today.md", "w").write(text)
print(text)
