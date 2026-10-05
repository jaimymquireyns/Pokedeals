"""Laagste live aanbiedingen (Cardmarket, alleen Near Mint) via PkmnPrices' '/cards/{id}/listings/cardmarket'.
Kost 20 credits per kaart per keer, dus dit gebeurt niet dagelijks per kaart: alleen voor je collectie en de
beste kansen, en een kaart wordt pas opnieuw ververst als de vorige keer een paar dagen geleden is. Staat in de
dagelijkse volgorde na sealed-geschiedenis, zodat dit profiteert van budget dat overblijft zodra de opbouw van de
Near Mint-geschiedenis (nm.py/card_history.py) grotendeels klaar is."""
import os
import time
from datetime import date, timedelta

import config
import nm
from pkmnprices import PkmnPrices
from store import SupabaseStore

REFRESH_DAYS = 3   # een kaart wordt pas opnieuw ververst als het langer dan dit geleden is
TOP_N = 300         # 'de beste kansen': zelfde top als bij het koppelen van Near Mint-prijzen
LIMIT = 8            # zoveel aanbiedingen bewaren we per kaart (de opvraging kost per teruggegeven rij, niet per opgeslagen rij)
MAX_SAVE_FAILS = 5   # zoveel keer achter elkaar opslaan mislukken = de database is echt weg: stoppen


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def top_expensive_ids(store, max_price, limit):
    """De duurste kaarten onder max_price, voor een aparte 'goedkope aanbiedingen'-ronde: dure kaarten waar een
    opvallend lage aanbieding het meeste uitmaakt, en die anders vrijwel nooit in de 'beste kansen'-lijst
    voorkomen (die selecteert op verwachte procentuele stijging, niet op prijs op zich)."""
    fc = store.select("forecasts", {"select": "product_id,price", "horizon_days": f"eq.{config.STANDARD[0]}", "threshold_pct": f"eq.{config.STANDARD[1]}"})
    price_by_pid = {f["product_id"]: float(f["price"]) for f in fc if f.get("price") is not None and ":" not in f["product_id"]}
    ids = [pid for pid, price in price_by_pid.items() if price <= max_price]
    ids.sort(key=lambda pid: -price_by_pid[pid])
    return ids[:limit]


def deal_targets(store):
    """Kaarten voor 'Goedkope aanbiedingen' op Home: de beroemde Pokémon vanaf config.DEALS_FAMOUS_MIN_PRICE (goedkoper
    heeft geen zin: na commissie en verzending blijft er niets over), plus de config.DEALS_TOP_N duurste kaarten onder
    config.DEALS_MAX_PRICE. Duurste eerst, zonder dubbels."""
    fc = store.select("forecasts", {"select": "product_id,price", "horizon_days": f"eq.{config.STANDARD[0]}", "threshold_pct": f"eq.{config.STANDARD[1]}"})
    price = {f["product_id"]: float(f["price"]) for f in fc if f.get("price") is not None and ":" not in f["product_id"]}
    famous = {p["product_id"] for p in store.products("card") if p.get("dex_id") in config.FAMOUS_DEX_IDS}
    fam = sorted((pid for pid in famous if price.get(pid, 0) >= config.DEALS_FAMOUS_MIN_PRICE), key=lambda pid: -price[pid])
    top = top_expensive_ids(store, config.DEALS_MAX_PRICE, config.DEALS_TOP_N)
    seen, out = set(), []
    for pid in sorted(set(fam) | set(top), key=lambda pid: -price.get(pid, 0)):
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def candidates(store):
    """Collectie, prijsmeldingen, en de beste kansen — niet de zich uitbreidende 'extra'-lijst van nm.py."""
    order, seen = [], set()

    def add(pid):
        if pid and ":" not in pid and pid not in seen:
            seen.add(pid)
            order.append(pid)

    for c in store.select("collection", {"select": "product_id"}):
        add(c["product_id"])
    for a in store.select("alerts", {"select": "product_id", "active": "eq.true"}):
        add(a["product_id"])
    fc = store.select("forecasts", {"select": "product_id,p_up,p_down",
                                    "horizon_days": f"eq.{config.STANDARD[0]}", "threshold_pct": f"eq.{config.STANDARD[1]}"})
    for f in sorted(fc, key=lambda f: float(f["p_up"]) - float(f["p_down"]), reverse=True)[:TOP_N]:
        add(f["product_id"])
    return order


def stale(store, product_ids, today, max_age_days=REFRESH_DAYS):
    """Kaarten die nog nooit, of langer dan max_age_days geleden, zijn ververst."""
    cutoff = (date.fromisoformat(today) - timedelta(days=max_age_days)).isoformat()
    fresh = set()
    try:
        for ch in _chunks(sorted(product_ids), 150):
            rows = store.select("offers", {"select": "product_id", "product_id": f"in.({','.join(ch)})", "date": f"gte.{cutoff}"})
            fresh.update(r["product_id"] for r in rows)
    except Exception as e:
        print(f"  (kon niet controleren welke kaarten al vers zijn, ga gewoon door: {e})")
    return [pid for pid in product_ids if pid not in fresh]


def _flag(v):
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def usable(r):
    """Alleen gewone Near Mint-aanbiedingen. Gegradeerde, getekende en bewerkte kaarten horen daar niet bij: ze hebben
    een heel andere prijs. De API kan al filteren op conditie, maar voor de zekerheid filteren we hier nog eens zelf."""
    return (isinstance(r, dict) and (r.get("condition") or "").lower() == "near mint" and bool(r.get("price"))
            and not _flag(r.get("graded")) and not _flag(r.get("signed")) and not _flag(r.get("altered")))


def parse_offers(product_id, rows, today, limit=LIMIT):
    """Goedkoopste eerst, met de uitvoering ('variant': Normal, Reverse Holofoil, ...): die verschillen soms een factor
    10 in prijs en horen niet door elkaar vergeleken te worden."""
    nm_rows = [r for r in rows if usable(r)]
    nm_rows.sort(key=lambda r: float(r["price"]))
    out = []
    for i, r in enumerate(nm_rows[:limit], 1):
        out.append({"product_id": product_id, "rank": i, "price": round(float(r["price"]), 2),
                    "seller": r.get("seller"), "quantity": r.get("quantity"), "language": r.get("language"),
                    "variant": r.get("variant"), "date": today})
    return out


def run(store, pk, today, log=print, deadline=None, only=None):
    """only: als je maar een specifieke, kleine lijst kaarten wilt (bijv. alleen je collectie, als eerste
    prioriteitsronde), geef die dan hier mee in plaats van de volledige prioriteitslijst te gebruiken."""
    cands = only if only is not None else candidates(store)
    products = {p["product_id"]: p for p in store.products("card") if p.get("pk_id")}
    cands = [pid for pid in cands if pid in products]
    todo = stale(store, cands, today)
    log(f"Laagste aanbiedingen: {len(cands)} kaarten in aanmerking, {len(todo)} zijn aan de beurt (ouder dan {REFRESH_DAYS} dagen of nog nooit opgehaald)")

    done, rows_total, save_fails = 0, 0, 0
    for pid in todo:
        if pk.over_budget():
            log(f"Credit-budget bereikt ({pk.credits}). Morgen gaat het verder waar het nu stopt.")
            break
        if deadline and time.time() >= deadline:
            log("Tijdslimiet van deze run bereikt. Morgen gaat het verder waar het nu stopt.")
            break
        p = products[pid]
        try:
            data = pk.list_all(f"/cards/{p['pk_id']}/listings/cardmarket", {"condition": "Near Mint"}, per_page=20, max_pages=1)
        except Exception as e:
            log(f"  {p['name']}: {e}")
            continue
        rows = parse_offers(pid, data, today)
        try:
            if rows:
                store.upsert("offers", rows, "product_id,rank")
            store.delete("offers", {"product_id": f"eq.{pid}", "rank": f"gt.{len(rows)}"})   # pas ná het opslaan: oude, niet meer bestaande regels opruimen
        except Exception as e:
            save_fails += 1
            log(f"  {p['name']}: opslaan mislukt ({type(e).__name__}); de volgende run probeert deze kaart opnieuw")
            if save_fails >= MAX_SAVE_FAILS:
                log(f"Database reageert niet meer ({MAX_SAVE_FAILS}x achter elkaar); gestopt om geen credits te verspillen.")
                break
            continue
        save_fails = 0
        done += 1
        rows_total += len(rows)
    log(f"Laagste aanbiedingen: {done} kaarten ververst, {rows_total} aanbiedingen opgeslagen ({pk.credits} credits tot nu toe)")
    return rows_total


def main():
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    run(store, PkmnPrices(os.environ["PKMN_API_KEY"]), date.today().isoformat())


if __name__ == "__main__":
    main()
