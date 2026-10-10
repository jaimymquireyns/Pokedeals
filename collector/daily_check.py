"""Dagelijkse controle van het model. Elke dag willekeurige kaarten: het model ziet alleen de prijzen tot 30 dagen geleden
en voorspelt de prijs van vandaag. Daarna vergelijken met de echte prijs van vandaag:
  - richting juist: voorspeld 'stijgt' / 'daalt' / 'blijft gelijk' (binnen 3%) en zo gebeurde het ook
  - prijs juist:    de echte prijs ligt binnen 10% van de voorspelde prijs
Ter vergelijking ook de domme gok 'de prijs blijft gelijk' (naive_ok: binnen 10% van de prijs van toen). Het model is pas
nuttig als het vaker juist is dan die gok. Resultaten in tabel model_checks (één rij per kaart per dag)."""
import random
from datetime import date, timedelta

import analysis
import config

N = 200            # zoveel kaarten per dag
HORIZON = 30       # zo ver terug krijgt het model zijn laatste prijs
FLAT = 0.03        # binnen +-3% telt als 'blijft gelijk'
PRICE_TOL = 0.10   # prijs juist = binnen 10%
MIN_PRICE = 3.0


def direction(change):
    return "up" if change > FLAT else "down" if change < -FLAT else "flat"


def _rows(store, ids, since):
    """Prijsrijen (Cardmarket-trend en Near Mint) voor een kleine lijst kaarten."""
    q = {"select": "product_id,date,source,grade_key,price,avg1,avg7,avg30,low", "grade_key": "in.(raw,nm)", "date": f"gte.{since}",
         "product_id": "in.(" + ",".join(f'"{x}"' for x in ids) + ")", "order": "product_id.asc,date.asc"}
    num = lambda v: float(v) if v is not None else None
    raw, nm = {}, {}
    for r in store.select("prices", q):
        r = {**r, **{k: num(r.get(k)) for k in ("price", "avg1", "avg7", "avg30", "low")}}
        if r["grade_key"] == "nm":
            nm.setdefault(r["product_id"], []).append(r)
        else:
            raw.setdefault(r["product_id"], {}).setdefault(r["source"], []).append(r)
    return raw, nm


def check_card(pid, by_source, nm_rows, today):
    """Eén kaart nakijken. Geeft een rij voor model_checks, of None als er te weinig gegevens zijn."""
    cut = (date.fromisoformat(today) - timedelta(days=HORIZON)).isoformat()
    recent = (date.fromisoformat(today) - timedelta(days=3)).isoformat()
    nm_past = [r for r in (nm_rows or []) if r["date"] <= cut]
    use_nm = len(nm_past) >= config.MIN_HISTORY_POINTS
    past_src = {s: [r for r in rs if r["date"] <= cut] for s, rs in by_source.items()}
    past = analysis.series_for(pid, past_src, nm_rows=nm_past if use_nm else None)
    # zelfde soort reeks voor 'nu' als voor 'toen', anders vergelijk je appels met peren
    now = analysis.series_for(pid, by_source, nm_rows=nm_rows if use_nm else None)
    if not past or not now or past[-1]["date"] < (date.fromisoformat(cut) - timedelta(days=3)).isoformat() or now[-1]["date"] < recent:
        return None
    try:
        f = analysis.forecast(past, HORIZON, PRICE_TOL)
    except (ArithmeticError, ValueError):
        return None
    if not f:
        return None
    then, actual = f["price"], now[-1]["trend"]
    if not then or not actual or then < MIN_PRICE:
        return None
    predicted = then * (1 + f["exp_change"])
    dp, da = direction(f["exp_change"]), direction(actual / then - 1)
    return {"check_date": today, "product_id": pid, "basis": "nm" if use_nm else "trend",
            "price_then": round(then, 2), "predicted": round(predicted, 2), "actual": round(actual, 2),
            "dir_pred": dp, "dir_actual": da, "dir_ok": dp == da,
            "price_ok": abs(actual / predicted - 1) <= PRICE_TOL, "naive_ok": abs(actual / then - 1) <= PRICE_TOL}


def run(store, today, log=print, n=N):
    rnd = random.Random(f"check-{today}")   # elke dag andere kaarten, maar dezelfde als je de dag opnieuw draait
    cands = [r["product_id"] for r in store.select("v_search", {"select": "product_id", "kind": "eq.card", "price": f"gte.{MIN_PRICE}"})]
    rnd.shuffle(cands)
    since = (date.fromisoformat(today) - timedelta(days=HORIZON + config.HISTORY_DAYS)).isoformat()
    out, tried = [], 0
    for i in range(0, len(cands), 60):
        if len(out) >= n or tried >= n * 8:
            break
        ids = cands[i:i + 60]
        tried += len(ids)
        raw, nm = _rows(store, ids, since)
        for pid in ids:
            row = check_card(pid, raw.get(pid, {}), nm.get(pid), today)
            if row:
                out.append(row)
            if len(out) >= n:
                break
    if out:
        store.upsert("model_checks", out, "check_date,product_id")
    k = len(out) or 1
    log(f"Dagelijkse controle: {len(out)} kaarten (van {tried} geprobeerd). Richting juist {sum(r['dir_ok'] for r in out)}/{len(out)} "
        f"({sum(r['dir_ok'] for r in out) / k:.0%}), prijs binnen 10% {sum(r['price_ok'] for r in out) / k:.0%} "
        f"(gok 'blijft gelijk': {sum(r['naive_ok'] for r in out) / k:.0%})")
    return out


if __name__ == "__main__":
    import os
    from store import SupabaseStore
    run(SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"]), date.today().isoformat())
