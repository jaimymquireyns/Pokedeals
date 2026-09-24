"""Near Mint-prijsgeschiedenis per kaart, via PkmnPrices (bron: Cardmarket). Vervangt voor kaarten die dit hebben
de gemengde Cardmarket-trend als basis van de kansberekening (zie analysis.series_for). Geen vaste einddatum of
maximum aantal kaarten: gaat elke dag net zo ver als het gedeelde PkmnPrices-budget toelaat, in dezelfde volgorde
als de Near Mint-prijzen zelf (collectie, prijsmeldingen, beste kansen, dan de rest op prijs), en onthoudt vanzelf
waar het gebleven is doordat al bijgewerkte kaarten worden overgeslagen.
"""
import os
import time
from datetime import date, timedelta

import nm
from pkmnprices import PkmnPrices
from store import SupabaseStore

BACKFILLED_ENOUGH_DAYS = 60


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def parse_rows(product_id, data, today):
    """PkmnPrices' '/cards/{id}/prices/history?condition=Near Mint' -> prijsrijen, in dezelfde vorm als de
    dagelijkse Near Mint-prijs (source='pkmnprices', grade_key='nm'), zodat beide reeksen naadloos aansluiten."""
    out = []
    for d in data:
        if not isinstance(d, dict):
            continue
        if (d.get("source") or "").lower() != "cardmarket" or (d.get("currency") or "").upper() != "EUR":
            continue
        if (d.get("condition") or "").lower() != "near mint":
            continue
        price = _num(d.get("avg") or d.get("market_price") or d.get("price"))
        dt = str(d.get("date") or "")[:10]
        if not price or not dt or dt >= today:
            continue
        out.append({"product_id": product_id, "date": dt, "source": "pkmnprices", "grade_key": "nm",
                    "price": price, "native": price, "currency": "EUR"})
    return out


def already_backfilled(store, product_ids, today):
    """Kaarten die al oude (60+ dagen) Near Mint-historie hebben, hoeven niet opnieuw. Eén blik per stapel
    kaarten in plaats van per kaart, om het aantal databaseverzoeken laag te houden."""
    cutoff = (date.fromisoformat(today) - timedelta(days=BACKFILLED_ENOUGH_DAYS)).isoformat()
    done = set()
    try:
        for ch in _chunks(sorted(product_ids), 150):
            rows = store.select("prices", {"select": "product_id", "product_id": f"in.({','.join(ch)})",
                                           "source": "eq.pkmnprices", "grade_key": "eq.nm", "date": f"lt.{cutoff}"})
            done.update(r["product_id"] for r in rows)
    except Exception as e:
        print(f"  (kon niet controleren wie al genoeg historie heeft, ga gewoon door: {e})")
    return done


def candidates(store):
    """Zelfde volgorde als de Near Mint-prijzen (collectie, prijsmeldingen, beste kansen, duurste kaarten),
    maar zonder maximum: gaat gewoon door tot alle geprijsde kaarten aan bod zijn geweest."""
    targets, fc = nm.pick_targets(store, limit=10 ** 9)
    order = targets + nm.extra_targets(fc, exclude=set(targets), cap=10 ** 9)
    return order


def run(store, pk, today, log=print, deadline=None):
    order = candidates(store)
    products = {p["product_id"]: p for p in store.products("card") if p.get("pk_id")}
    order = [pid for pid in order if pid in products]
    done_already = already_backfilled(store, order, today)
    todo = [pid for pid in order if pid not in done_already]
    log(f"Kaartgeschiedenis: {len(order)} gekoppelde kaarten, {len(done_already)} hebben al genoeg oude Near Mint-historie")

    done, rows_total = 0, 0
    for pid in todo:
        if pk.over_budget():
            log(f"Credit-budget bereikt ({pk.credits}). Morgen gaat het verder waar het nu stopt.")
            break
        if deadline and time.time() >= deadline:
            log("Tijdslimiet van deze run bereikt. Morgen gaat het verder waar het nu stopt.")
            break
        p = products[pid]
        try:
            data = pk.list_all(f"/cards/{p['pk_id']}/prices/history", {"currency": "eur", "condition": "Near Mint"}, per_page=100)
        except Exception as e:
            log(f"  {p['name']}: {e}")
            continue
        rows = parse_rows(pid, data, today)
        if rows:
            store.upsert_prices(rows)
            rows_total += len(rows)
        done += 1
    log(f"Kaartgeschiedenis: {done} kaarten bijgewerkt, {rows_total} prijspunten toegevoegd ({pk.credits} credits tot nu toe)")
    return rows_total


def main():
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    run(store, PkmnPrices(os.environ["PKMN_API_KEY"]), date.today().isoformat())


if __name__ == "__main__":
    main()
