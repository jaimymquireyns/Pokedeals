"""Kloppen de kansen? Meetlat voor p_up / p_down (kans op +10% / -10% in 30 dagen) uit de dagelijkse controle (model_checks).

Twee vragen, want een gemiddelde alleen zegt te weinig (een model dat voor elke kaart '15%' zegt, klopt gemiddeld ook):
  1. IJking: zegt het model 30%, gebeurt het dan ook ongeveer 30% van de keren? Per kansvak: gezegd tegen gebeurd.
  2. Onderscheid: krijgen de kaarten die echt stijgen een hogere kans dan de rest? Gemeten met de Brier-score (gemiddelde
     van (kans - uitkomst)^2, lager is beter) tegen de domme gok 'voor elke kaart hetzelfde basispercentage'.
     Vaardigheid = 1 - Brier(model) / Brier(basis): boven 0 weet het model iets, 0 of minder: niet beter dan de gok.
Het basispercentage komt uit de eerste helft van de dagen en wordt gemeten op de tweede helft (anders kijkt de gok vooruit).

    python calibration.py --out ../reports/calibration.md
"""
import argparse
import os
from datetime import date

BINS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.60, 1.01]
MIN_BIN = 20   # minder metingen in een vak: getoond, maar niet meegeteld in het oordeel


def _f(x):
    return float(x) if x is not None else None


def pairs(rows, p_key, hit_key):
    return [(_f(r[p_key]), bool(r[hit_key])) for r in rows if r.get(p_key) is not None and r.get(hit_key) is not None]


def brier(ps):
    return sum((p - y) ** 2 for p, y in ps) / len(ps) if ps else None


def skill(rows, p_key, hit_key):
    """Vaardigheid op de tweede helft van de dagen, met het basispercentage uit de eerste helft. (skill, n_test, basis)"""
    days = sorted({r["check_date"] for r in rows})
    if len(days) < 4:
        return None, 0, None
    split = days[len(days) // 2]
    train = pairs([r for r in rows if r["check_date"] < split], p_key, hit_key)
    test = pairs([r for r in rows if r["check_date"] >= split], p_key, hit_key)
    if not train or not test:
        return None, len(test), None
    base = sum(y for _, y in train) / len(train)
    b_model, b_base = brier(test), brier([(base, y) for _, y in test])
    return (1 - b_model / b_base if b_base else None), len(test), base


def table(ps):
    out = []
    for lo, hi in zip(BINS, BINS[1:]):
        xs = [(p, y) for p, y in ps if lo <= p < hi]
        if xs:
            out.append((lo, hi, len(xs), sum(p for p, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs)))
    return out


def verdict(tab, sk):
    big = [t for t in tab if t[2] >= MIN_BIN]
    off = [t for t in big if abs(t[3] - t[4]) > max(0.05, 0.5 * t[3])]
    parts = []
    if sk is None:
        parts.append("Nog te weinig dagen om het onderscheid te meten.")
    elif sk > 0.02:
        parts.append(f"Het model onderscheidt kaarten beter dan de gok (vaardigheid {sk:+.1%}).")
    else:
        parts.append(f"Het model onderscheidt kaarten niet beter dan voor elke kaart hetzelfde percentage te zeggen (vaardigheid {sk:+.1%}).")
    if off:
        parts.append("Scheef in: " + ", ".join(f"{lo:.0%}-{min(hi, 1):.0%} (zegt {s:.0%}, gebeurt {g:.0%})" for lo, hi, _, s, g in off) + ".")
    elif big:
        parts.append("Waar genoeg metingen zijn, liggen gezegd en gebeurd dicht bij elkaar.")
    return " ".join(parts)


def report(rows, today):
    days = sorted({r["check_date"] for r in rows})
    lines = [f"# Kloppen de kansen? ({today})", "",
             f"{len(rows)} controles op {len(days)} dagen ({days[0] if days else '-'} t/m {days[-1] if days else '-'}). "
             "Elke controle: het model ziet de prijs van 30 dagen geleden en zegt hoe groot de kans is op +10% en op -10%; "
             "daarna kijken we wat er echt gebeurde.", ""]
    for title, pk, hk in (("Kans op +10% in 30 dagen", "p_up", "up10"), ("Kans op -10% in 30 dagen", "p_down", "down10")):
        ps = pairs(rows, pk, hk)
        if not ps:
            lines += [f"## {title}", "", "Nog geen metingen.", ""]
            continue
        tab = table(ps)
        sk, n_test, base = skill(rows, pk, hk)
        lines += [f"## {title}", "",
                  f"Gemiddeld gezegd {sum(p for p, _ in ps) / len(ps):.1%}, gebeurd {sum(y for _, y in ps) / len(ps):.1%} ({len(ps)} metingen).", "",
                  verdict(tab, sk), "",
                  "| model zegt | aantal | gemiddeld gezegd | echt gebeurd |", "|---|---|---|---|"]
        for lo, hi, n, s, g in tab:
            mark = "" if n >= MIN_BIN else " (weinig)"
            lines.append(f"| {lo:.0%}-{min(hi, 1):.0%} | {n}{mark} | {s:.1%} | {g:.1%} |")
        if sk is not None:
            lines += ["", f"Onderscheid (Brier-vaardigheid, tweede helft van de dagen, {n_test} metingen, basis {base:.1%}): {sk:+.1%}."]
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/calibration.md")
    args = ap.parse_args()
    from store import SupabaseStore
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    rows = store.select("model_checks", {"select": "check_date,product_id,basis,p_up,p_down,up10,down10", "order": "check_date.asc"})
    text = report(rows, date.today().isoformat())
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
