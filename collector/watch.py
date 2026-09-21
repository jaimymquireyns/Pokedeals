"""Tussentijdse controle (3x per dag, naast de dagelijkse taak): ververst alleen wat je volgt
(collectie en kaarten met een prijsmelding) en verstuurt prijsmeldingen."""
import os
from datetime import date

import alerts
import cardmarket
import run
from providers import TCGdex
from store import SupabaseStore


def watched_keys(store):
    keys = set()
    for c in store.select("collection", {"select": "product_id,grade_company,grade"}):
        keys.add((c["product_id"], alerts.grade_key(c)))
    for a in store.select("alerts", {"select": "product_id,grade_key", "active": "eq.true"}):
        keys.add((a["product_id"], a["grade_key"]))
    return keys


def refresh(store, tcg, ppt, today, fx, keys, log=print):
    if not keys:
        return 0
    products = {}
    ids = sorted({k[0] for k in keys})
    for i in range(0, len(ids), 80):
        for p in store.select("products", {"select": "*", "product_id": f"in.({','.join(ids[i:i + 80])})"}):
            products[p["product_id"]] = p
    rows, guide = [], None
    for pid, gk in sorted(keys):
        p = products.get(pid)
        if not p:
            continue
        try:
            if gk == "raw" and p["kind"] == "card":
                res = tcg.get_card(pid)
                if res and res["price"]:
                    rows.append({"product_id": pid, "date": today, "source": "tcgdex", "grade_key": "raw", **res["price"]})
            elif gk == "raw" and p["kind"] == "sealed" and pid.startswith("cm:"):
                if guide is None:
                    guide = cardmarket.load_price_guide(tcg.session)
                g = guide.get(int(pid.split(":")[1]))
                if g:
                    rows.append({"product_id": pid, "date": today, "source": "cardmarket", "grade_key": "raw",
                                 "price": g["price"], "avg1": g["avg1"], "avg7": g["avg7"], "avg30": g["avg30"], "low": g["low"],
                                 "native": g["price"], "currency": "EUR"})
            elif gk != "raw" and ppt and p.get("ppt_id"):
                it = ppt.card(p["ppt_id"], ebay=True)
                usd = (it or {}).get("graded", {}).get(gk)
                if usd:
                    rows.append({"product_id": pid, "date": today, "source": "ppt", "grade_key": gk,
                                 "price": round(usd * fx, 4), "native": usd, "currency": "USD"})
                else:
                    log(f"  geen prijs voor {pid} {gk}")
        except Exception as e:
            log(f"  {pid} {gk}: {e}")
    if rows:
        store.upsert_prices(rows)
    log(f"Volglijst ververst: {len(rows)} prijzen")
    return len(rows)


def main():
    import fx as fxmod
    url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"]
    store, tcg, today = SupabaseStore(url, key), TCGdex(), date.today().isoformat()
    ppt = None
    if os.environ.get("PPT_API_KEY"):
        from ppt import PPT
        ppt = PPT(os.environ["PPT_API_KEY"])
    rate, _ = fxmod.usd_to_eur(tcg.session)
    refresh(store, tcg, ppt, today, rate, watched_keys(store))
    alerts.evaluate(store, run.make_sender(), today)


if __name__ == "__main__":
    main()
