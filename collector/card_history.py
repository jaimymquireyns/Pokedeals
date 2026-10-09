"""Near Mint-prijsgeschiedenis per kaart, via PkmnPrices (bron: Cardmarket). Vervangt voor kaarten die dit hebben
de gemengde Cardmarket-trend als basis van de kansberekening (zie analysis.series_for). Geen vaste einddatum of
maximum aantal kaarten: gaat elke dag net zo ver als het gedeelde PkmnPrices-budget toelaat, in dezelfde volgorde
als de Near Mint-prijzen zelf (collectie, prijsmeldingen, beste kansen, dan de rest op prijs), en onthoudt vanzelf
waar het gebleven is doordat al bijgewerkte kaarten worden overgeslagen.
"""
import os
import time
from datetime import date, timedelta

import config
import nm
from pkmnprices import PkmnPrices
from store import SupabaseStore

BACKFILLED_ENOUGH_DAYS = 60   # bij de standaard 90 dagen: ruim eronder, anders blijft een kaart net-niet 'genoeg' hebben en wordt hij steeds opnieuw opgehaald


def period_days(period=None):
    return int(str(period or config.HISTORY_PERIOD).rstrip("d"))


def enough_days(period=None):
    """Vanaf hoeveel dagen oude historie een kaart 'klaar' is, afhankelijk van hoe ver we terugvragen: dezelfde
    verhouding als de beproefde 60 bij 90 dagen (2/3), dus 120 bij 180 dagen. Zo telt een kaart met 90 dagen
    niet meer als klaar zodra hij 180 dagen hoort te krijgen (de fout van 30 sep bij de beroemde Pokémon)."""
    return max(1, round(period_days(period) * 2 / 3))


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


US_FX = 0.92   # vaste omrekening USD -> EUR voor de Amerikaanse reeks (alleen om te vergelijken; 'native' bewaart de dollars)


def parse_us_rows(product_id, data, today):
    """Dezelfde geschiedenis bevat ook TCGplayer (Amerika, USD). Die bewaren we apart (source 'tcgplayer', grade_key 'us'), om
    de Amerikaanse en Europese markt te kunnen vergelijken. Kost niets extra: PkmnPrices stuurt ze toch mee. Eén uitvoering
    per kaart (de meest voorkomende), zodat Normal en Reverse Holofoil niet door elkaar lopen."""
    by_var = {}
    for d in data:
        cur = (d.get("currency") or "USD").upper()
        if not isinstance(d, dict) or (d.get("source") or "").lower() != "tcgplayer" or cur not in ("USD", "EUR"):
            continue
        if (d.get("condition") or "near mint").lower() != "near mint":
            continue
        price = _num(d.get("market_price") or d.get("avg") or d.get("price"))
        dt = str(d.get("date") or "")[:10]
        if price and dt and dt < today:
            by_var.setdefault(d.get("variant") or "", {})[dt] = price if cur == "USD" else price / US_FX
    if not by_var:
        return []
    var = max(by_var, key=lambda v: len(by_var[v]))
    return [{"product_id": product_id, "date": dt, "source": "tcgplayer", "grade_key": "us", "price": round(p * US_FX, 4), "native": p, "currency": "USD"}
            for dt, p in sorted(by_var[var].items())]


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


def already_backfilled(store, product_ids, today, products=None):
    """Kaarten die al oud genoeg Near Mint-historie hebben (zie enough_days), of die al eens tot de gevraagde
    diepte zijn opgehaald (products[..]['nm_hist_days']), hoeven niet opnieuw. Dat laatste voorkomt dat een
    kaart met weinig verkopen, waarvan domweg geen oudere prijzen bestaan, elke nacht opnieuw credits kost.
    Eén blik per stapel kaarten in plaats van per kaart, om het aantal databaseverzoeken laag te houden."""
    cutoff = (date.fromisoformat(today) - timedelta(days=enough_days())).isoformat()
    want = period_days()
    done = {pid for pid in product_ids if products and (products.get(pid) or {}).get("nm_hist_days") and int(products[pid]["nm_hist_days"]) >= want}
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


MAX_SAVE_FAILS = 5   # zoveel keer achter elkaar opslaan mislukken = de database is echt weg: stoppen


def run(store, pk, today, log=print, deadline=None, only=None):
    """only: als je maar een specifieke, kleine lijst kaarten wilt (bijv. alleen je collectie, als eerste
    prioriteitsronde), geef die dan hier mee in plaats van de volledige prioriteitslijst te gebruiken."""
    order = only if only is not None else candidates(store)
    products = {p["product_id"]: p for p in store.products("card") if p.get("pk_id")}
    order = [pid for pid in order if pid in products]
    done_already = already_backfilled(store, order, today, products)
    todo = [pid for pid in order if pid not in done_already]
    log(f"Kaartgeschiedenis: {len(order)} gekoppelde kaarten, {len(done_already)} hebben al genoeg oude Near Mint-historie")

    done, rows_total, save_fails, marker_ok = 0, 0, 0, True
    for pid in todo:
        if pk.over_budget():
            log(f"Credit-budget bereikt ({pk.credits}). Morgen gaat het verder waar het nu stopt.")
            break
        if deadline and time.time() >= deadline:
            log("Tijdslimiet van deze run bereikt. Morgen gaat het verder waar het nu stopt.")
            break
        p = products[pid]
        try:
            data = pk.list_all(f"/cards/{p['pk_id']}/prices/history", {"currency": "eur", "condition": "Near Mint", "period": config.HISTORY_PERIOD}, per_page=100)
        except Exception as e:
            log(f"  {p['name']}: {e}")
            continue
        rows = parse_rows(pid, data, today) + parse_us_rows(pid, data, today)
        if rows:
            try:
                store.upsert_prices(rows)
            except Exception as e:   # bijv. een time-out bij Supabase: deze kaart slaan we over (de volgende run pakt 'm weer op), de rest gaat door
                save_fails += 1
                log(f"  {p['name']}: opslaan mislukt ({type(e).__name__}); de volgende run probeert deze kaart opnieuw")
                if save_fails >= MAX_SAVE_FAILS:
                    log(f"Database reageert niet meer ({MAX_SAVE_FAILS}x achter elkaar); gestopt om geen credits te verspillen. Morgen gaat het verder.")
                    break
                continue
            save_fails = 0
            rows_total += len(rows)
        if marker_ok:   # onthouden tot hoe ver deze kaart is opgehaald, ook als er (nog) geen oude verkopen bestaan
            try:
                store.patch("products", {"product_id": f"eq.{pid}"}, {"nm_hist_days": period_days()})
            except Exception as e:
                marker_ok = False
                log(f"  (kon de opgehaalde diepte niet onthouden, draai supabase/schema.sql opnieuw: {type(e).__name__})")
        done += 1
    log(f"Kaartgeschiedenis: {done} kaarten bijgewerkt, {rows_total} prijspunten toegevoegd ({pk.credits} credits tot nu toe)")
    return rows_total


def main():
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    run(store, PkmnPrices(os.environ["PKMN_API_KEY"]), date.today().isoformat())


if __name__ == "__main__":
    main()
