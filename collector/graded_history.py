"""Geschiedenis van gegradeerde kaarten (PSA, BGS, CGC), alleen voor de beroemde Pokémon (config.FAMOUS_DEX_IDS).
Per graad een aparte opvraging bij PkmnPrices' eBay-verkopen (er bestaat geen verzamel-'geschiedenis'-endpoint
voor gegradeerde kaarten zoals bij Near Mint, dus we lezen de losse verkopen met hun eigen verkoopdatum uit).

Bewust weggelaten: BGS Black Label en CGC Pristine 10. Dat zijn geen gewone cijfergraden maar aparte labels, en
we weten nog niet zeker hoe je die specifiek bij PkmnPrices opvraagt. Liever leeg laten dan een verkeerde
aanname doen. De gewone graad 10 van beide bedrijven wordt wel gewoon opgehaald.
"""
import time
from datetime import date, timedelta

import config

GRADES = {
    "PSA": ["1", "7", "8", "9", "10"],
    "BGS": ["1", "7", "7.5", "8", "8.5", "9", "9.5", "10"],
    "CGC": ["1", "7", "7.5", "8", "8.5", "9", "9.5", "10"],
}


def famous_graded_targets(store):
    """Kaarten van de beroemde Pokémon die al aan PkmnPrices gekoppeld zijn (koppelen gebeurt al bij de gewone
    geschiedenis hiervoor, dus deze stap koppelt zelf niets nieuws)."""
    return [p for p in store.products("card", extra={"dex_id": f"in.({','.join(str(d) for d in sorted(config.FAMOUS_DEX_IDS))})"})
            if p.get("pk_id") and not config.is_digital_set(p.get("set_id"))]


def oldest_date(store, product_id, grade_key):
    """De oudste datum die we al hebben voor deze kaart/graad, of None als we er nog niets van hebben."""
    rows = store.select("prices", {"select": "date", "product_id": f"eq.{product_id}", "grade_key": f"eq.{grade_key}",
                                   "source": "eq.pkmnprices_ebay", "order": "date.asc", "limit": 1})
    return rows[0]["date"] if rows else None


def deep_enough(store, product_id, grade_key, today, days):
    d = oldest_date(store, product_id, grade_key)
    if not d:
        return False
    cutoff = (date.fromisoformat(today) - timedelta(days=days - 5)).isoformat()   # 5 dagen speling, net als bij de gewone geschiedenis
    return d <= cutoff


def parse_sales(product_id, grader, grade, rows, today):
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = r.get("date") or r.get("sale_date") or r.get("soldDate")
        price = r.get("price") or r.get("sale_price") or r.get("salePrice")
        if not d or price is None:
            continue
        d = str(d)[:10]
        if d > today:
            continue
        try:
            out.append({"date": d, "price": round(float(price), 2)})
        except (TypeError, ValueError):
            continue
    by_date = {}   # per dag maar één prijs (het gemiddelde), anders klopt de upsert-sleutel (product_id,date,source,grade_key) niet
    for r in out:
        by_date.setdefault(r["date"], []).append(r["price"])
    return [{"product_id": product_id, "date": d, "source": "pkmnprices_ebay", "grade_key": f"{grader}-{grade}", "price": round(sum(ps) / len(ps), 2)}
            for d, ps in by_date.items()]


def _round(store, pk, today, todo, days, log, deadline, save_fails_start=0):
    """Eén doorgang over 'todo' (lijst van (product, grader, grade)), tot 'days' dagen terug, met vangnetten
    net als de gewone kaartgeschiedenis. Geeft (aantal bijgewerkt, aantal prijspunten, laatste save_fails) terug."""
    done, rows_total, save_fails, unparsed, stuck = 0, 0, save_fails_start, 0, False
    period = f"{days}d"
    for p, grader, grade in todo:
        if pk.over_budget():
            log(f"Credit-budget bereikt ({pk.credits}). Morgen gaat het verder waar het nu stopt.")
            break
        if deadline and time.time() >= deadline:
            log("Tijdslimiet van deze run bereikt. Morgen gaat het verder waar het nu stopt.")
            break
        grade_key = f"{grader}-{grade}"
        if deep_enough(store, p["product_id"], grade_key, today, days):
            continue
        try:
            data = pk.list_all(f"/cards/{p['pk_id']}/listings/ebay", {"graded": "true", "grader": grader, "grade": grade, "period": period}, per_page=50)
        except Exception as e:
            log(f"  {p['name']} {grader} {grade}: {e}")
            continue
        rows = parse_sales(p["product_id"], grader, grade, data, today)
        if data and not rows:   # de API gaf wel verkopen terug (en rekende er credits voor), maar de uitlezing herkent er niets in
            unparsed += 1
            if unparsed >= config.GRADED_MAX_UNPARSED:
                log(f"NOODREM: {unparsed} opvragingen achter elkaar gaven verkopen terug waar de uitlezing geen prijs of datum in herkent "
                    f"(laatste: {p['name']} {grader} {grade}, velden: {sorted(data[0]) if isinstance(data[0], dict) else type(data[0]).__name__}). "
                    "Gestopt om geen credits te verspillen; draai check_card met --graded om een echt antwoord te zien.")
                stuck = True
                break
        elif rows:
            unparsed = 0
        if rows:
            try:
                store.upsert_prices(rows)
            except Exception as e:
                save_fails += 1
                log(f"  {p['name']} {grader} {grade}: opslaan mislukt ({type(e).__name__}); de volgende run probeert het opnieuw")
                if save_fails >= 5:
                    log("Database reageert niet meer (5x achter elkaar); gestopt om geen credits te verspillen.")
                    break
                continue
            save_fails = 0
            rows_total += len(rows)
        done += 1
    return done, rows_total, save_fails, stuck


def run(store, pk, today, log=print, deadline=None, target_days=None):
    """target_days: als er nog budget/tijd over is nadat de standaardperiode (config.HISTORY_PERIOD) overal is
    gehaald, mag er verder teruggekeken worden tot dit aantal dagen (bijv. 90 -> 180)."""
    cards = famous_graded_targets(store)
    log(f"Gegradeerde geschiedenis (beroemde Pokémon): {len(cards)} kaarten in aanmerking.")
    if not cards:
        return 0

    todo = [(c, grader, grade) for c in cards for grader, grades in GRADES.items() for grade in grades]
    base_days = int(config.HISTORY_PERIOD.rstrip("d"))
    original_budget = pk.budget
    pk.budget = min(original_budget, pk.credits + config.GRADED_BUDGET)   # eigen plafond: dit mag de rest van de nacht nooit meer opslokken
    log(f"Gegradeerde geschiedenis: budget voor deze stap maximaal {config.GRADED_BUDGET} credits.")
    try:
        done, rows_total, save_fails, stuck = _round(store, pk, today, todo, base_days, log, deadline)
        log(f"Gegradeerde geschiedenis: {done} kaart/graad-combinaties bijgewerkt, {rows_total} prijspunten toegevoegd ({pk.credits} credits tot nu toe).")
        if not stuck:
            rows_total += _deeper(store, pk, today, todo, base_days, target_days, log, deadline, save_fails)
    finally:
        pk.budget = original_budget
    return rows_total


def _deeper(store, pk, today, todo, base_days, target_days, log, deadline, save_fails):
    rows_total = 0
    if target_days and not pk.over_budget() and not (deadline and time.time() >= deadline):
        deep_days = int(target_days) if not isinstance(target_days, str) else int(target_days.rstrip("d"))
        remaining = [(c, grader, grade) for c, grader, grade in todo
                    if not deep_enough(store, c["product_id"], f"{grader}-{grade}", today, base_days)]
        if not remaining:   # de standaardperiode is overal gehaald: nu pas mag het dieper, tot deep_days
            log(f"Standaardperiode ({base_days}d) is overal gehaald voor gegradeerde kaarten; budget/tijd over, dus verder terug tot {deep_days}d.")
            done2, rows2, _, _ = _round(store, pk, today, todo, deep_days, log, deadline, save_fails_start=save_fails)
            rows_total += rows2
            log(f"Gegradeerde geschiedenis (verdieping): {done2} kaart/graad-combinaties bijgewerkt, {rows2} extra prijspunten ({pk.credits} credits tot nu toe).")
    return rows_total
