"""Geschiedenis van gegradeerde kaarten (PSA, BGS, CGC), alleen voor de beroemde Pokémon (config.FAMOUS_DEX_IDS).

Bron: PkmnPrices' echte eBay-verkopen ('/cards/{id}/listings/ebay'). Een antwoord ziet er (gezien op 6 okt) zo uit:
  {"data": [{"id", "title", "price": 500.0, "currency": "USD", "grader": "PSA", "grade": "10", "grade_qualifier": null,
             "variant": "Normal" | "Reverse Holofoil", "attribution": "exact", "sold_at": "2026-06-27", ...}],
   "pagination": {"has_more": true, "next_cursor": "...", "count": 20}}
Belangrijk daarbij:
  * de datum heet 'sold_at', en de prijs staat in dollars: een Normal PSA 10 Lapras ging voor $500, de Reverse Holofoil voor $3.300;
    uitvoeringen mogen dus nooit door elkaar. We kiezen per opvraging één uitvoering (normal > holofoil > reverse holofoil, net als
    bij de Near Mint-prijs), en bewaren de prijs in euro (de oorspronkelijke dollarprijs gaat mee in 'native').
  * 'grade_qualifier' (bijv. een Pristine of Black Label) krijgt een eigen sleutel ('CGC-10-Pristine'), zodat hij de gewone 10 niet vervuilt.
  * de opvraging kost 1 credit per teruggegeven verkoop (maximaal 20 per pagina) en pagineert met een cursor, niet met paginanummers.
  * een opvraging per kaart/graad; wanneer we die voor het laatst deden en wat eruit kwam, staat in 'graded_checks', zodat we niet elke
    nacht dezelfde (vaak lege) opvragingen herhalen.
"""
import re
import time
from datetime import date, timedelta

import config

GRADES = {
    "PSA": ["1", "7", "8", "9", "10"],
    "BGS": ["1", "7", "7.5", "8", "8.5", "9", "9.5", "10"],
    "CGC": ["1", "7", "7.5", "8", "8.5", "9", "9.5", "10"],
}
GRADE_PRIORITY = {"10": 0, "9": 1, "9.5": 2, "8": 3, "8.5": 4, "7": 5, "7.5": 6, "1": 7}   # de best verhandelde graden eerst: bij een beperkt budget levert dat het meeste op
VARIANT_RANK = {"normal": 0, "holofoil": 1, "reverse holofoil": 2}   # zelfde voorkeur als nm.VARIANT_ORDER; andere uitvoeringen (1st edition, ...) komen daarna


def famous_graded_targets(store):
    """Kaarten van de beroemde Pokémon die al aan PkmnPrices gekoppeld zijn (koppelen gebeurt al bij de gewone
    geschiedenis hiervoor, dus deze stap koppelt zelf niets nieuws)."""
    return [p for p in store.products("card", extra={"dex_id": f"in.({','.join(str(d) for d in sorted(config.FAMOUS_DEX_IDS))})"})
            if p.get("pk_id") and not config.is_digital_set(p.get("set_id"))]


def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _same_grade(a, b):
    x, y = _num(a), _num(b)
    return x is not None and y is not None and abs(x - y) < 1e-9


def pick_variant(rows):
    """De uitvoering die we bewaren: de beste volgens VARIANT_RANK die in deze rijen voorkomt."""
    best = None
    for r in rows:
        v = str(r.get("variant") or "").strip().lower()
        rank = VARIANT_RANK.get(v, 9)
        if best is None or rank < best[0]:
            best = (rank, v)
    return best[1] if best else None


def qualifier_key(grader, grade, qualifier):
    base = f"{grader}-{grade}"
    q = re.sub(r"[^A-Za-z0-9]+", "_", str(qualifier or "")).strip("_")
    return f"{base}-{q}" if q else base


def parse_sales(product_id, grader, grade, rows, today, usd_eur=None, stats=None):
    """Verkopen -> prijsrijen (één per dag en sleutel: het gemiddelde van die dag, in euro). stats telt wat er is overgeslagen en waarom:
    unreadable = geen herkenbare datum of prijs (dan klopt onze uitlezing niet), foreign = andere munt dan USD/EUR, other = andere
    kaart of graad, attribution = niet 'exact' toegewezen aan deze kaart, variant = een andere uitvoering dan de gekozen."""
    st = stats if stats is not None else {}
    for k in ("unreadable", "foreign", "other", "attribution", "variant"):
        st.setdefault(k, 0)
    good = []
    for r in rows:
        if not isinstance(r, dict):
            st["unreadable"] += 1
            continue
        d = str(r.get("sold_at") or r.get("date") or "")[:10]
        price = _num(r.get("price"))
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d) or not price or price <= 0:
            st["unreadable"] += 1
            continue
        if d > today:
            continue
        if (r.get("grader") and str(r["grader"]).upper() != grader.upper()) or (r.get("grade") is not None and not _same_grade(r["grade"], grade)):
            st["other"] += 1
            continue
        if r.get("attribution") not in (None, "exact"):
            st["attribution"] += 1
            continue
        cur = str(r.get("currency") or "USD").upper()
        if cur == "USD":
            if not usd_eur:
                st["foreign"] += 1
                continue
            eur = price * usd_eur
        elif cur == "EUR":
            eur = price
        else:
            st["foreign"] += 1
            continue
        good.append((r, d, price, eur, cur))
    if not good:
        return []
    chosen = pick_variant([g[0] for g in good])
    by_key = {}
    for r, d, price, eur, cur in good:
        if str(r.get("variant") or "").strip().lower() != chosen:
            st["variant"] += 1
            continue
        key = (d, qualifier_key(grader, grade, r.get("grade_qualifier")))
        by_key.setdefault(key, []).append((price, eur, cur))
    out = []
    for (d, gk), vals in by_key.items():
        out.append({"product_id": product_id, "date": d, "source": "pkmnprices_ebay", "grade_key": gk,
                    "price": round(sum(v[1] for v in vals) / len(vals), 2),
                    "native": round(sum(v[0] for v in vals) / len(vals), 2), "currency": vals[0][2]})
    return out


def fetch_sales(pk, pk_id, grader, grade, cutoff, max_pages, state):
    """Haalt verkopen op, nieuwste eerst, en volgt de cursor tot de oudste verkoop de grens 'cutoff' (datum) haalt, er niets meer is,
    of max_pages bereikt is. Werkt de cursor niet (pagina 2 is gelijk aan pagina 1), dan onthouden we dat in 'state' en vragen we
    daarna alleen nog de eerste pagina op. Geeft (rijen, klaar) terug: klaar = er is niets ouders meer te halen."""
    rows, cursor, pages, complete = [], None, 0, True
    while pages < max_pages and not pk.over_budget():
        params = {"graded": "true", "grader": grader, "grade": grade}
        if cursor:
            params["cursor"] = cursor
        body = pk.call(f"/cards/{pk_id}/listings/ebay", params)
        data = body.get("data") if isinstance(body, dict) else None
        data = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
        if cursor and data and rows and data[0].get("id") == rows[0].get("id"):
            state["cursor_ok"] = False    # de cursor werd genegeerd: hetzelfde antwoord als pagina 1
            break
        rows += data
        pages += 1
        pag = (body.get("pagination") or {}) if isinstance(body, dict) else {}
        if not data or not pag.get("has_more") or not pag.get("next_cursor"):
            complete = True
            break
        complete = False
        dates = [str(r.get("sold_at") or "")[:10] for r in data if r.get("sold_at")]
        if (dates and min(dates) <= cutoff) or state.get("cursor_ok") is False:
            break
        cursor = pag["next_cursor"]
    return rows, complete


def load_checks(store, product_ids):
    """Wat we eerder opgevraagd hebben: {(product_id, grade_key): rij}."""
    out, ids = {}, sorted(product_ids)
    for i in range(0, len(ids), 100):
        for r in store.select("graded_checks", {"select": "*", "product_id": f"in.({','.join(ids[i:i + 100])})"}):
            out[(r["product_id"], r["grade_key"])] = r
    return out


def _due(check, today):
    if not check:
        return True
    try:
        age = (date.fromisoformat(today) - date.fromisoformat(str(check["checked_on"])[:10])).days
    except (KeyError, ValueError):
        return True
    return age >= (config.GRADED_RECHECK_DAYS if (check.get("n_rows") or 0) > 0 else config.GRADED_RECHECK_EMPTY_DAYS)


def _flush(store, checks, log):
    if not checks:
        return
    try:
        store.upsert("graded_checks", checks, "product_id,grade_key")
    except Exception as e:
        log(f"  (kon niet onthouden wat er opgevraagd is: {type(e).__name__}; draai supabase/schema.sql opnieuw, tabel graded_checks)")
    checks.clear()


def _process(store, pk, today, combos, memory, horizon, usd_eur, log, deadline, state):
    """Eén doorgang over 'combos' [(product, grader, grade)]. Geeft (aantal opgevraagd, aantal prijspunten, noodrem) terug."""
    done = rows_total = unreadable_run = save_fails = 0
    pending, stuck = [], False
    for p, grader, grade in combos:
        if pk.over_budget():
            log(f"Credit-budget bereikt ({pk.credits}). Morgen gaat het verder waar het nu stopt.")
            break
        if deadline and time.time() >= deadline:
            log("Tijdslimiet van deze run bereikt. Morgen gaat het verder waar het nu stopt.")
            break
        gk = f"{grader}-{grade}"
        prev = memory.get((p["product_id"], gk))
        if prev:   # herhaling: alleen wat sinds de vorige keer is bijgekomen
            cutoff = (date.fromisoformat(str(prev["checked_on"])[:10]) - timedelta(days=2)).isoformat()
        else:
            cutoff = (date.fromisoformat(today) - timedelta(days=horizon - 5)).isoformat()
        try:
            data, complete = fetch_sales(pk, p["pk_id"], grader, grade, cutoff, config.GRADED_MAX_PAGES, state)
        except Exception as e:
            log(f"  {p['name']} {grader} {grade}: {e}")
            if pk.blocked:
                break
            continue
        stats = {}
        rows = parse_sales(p["product_id"], grader, grade, data, today, usd_eur=usd_eur, stats=stats)
        if data and stats["unreadable"] == len(data):   # de API gaf verkopen terug (en rekende er credits voor), maar de uitlezing herkent er niets in
            unreadable_run += 1
            if unreadable_run >= config.GRADED_MAX_UNPARSED:
                log(f"NOODREM: {unreadable_run} opvragingen achter elkaar gaven verkopen terug waar de uitlezing geen datum of prijs in herkent "
                    f"(laatste: {p['name']} {grader} {grade}, velden: {sorted(data[0])}). Gestopt om geen credits te verspillen; "
                    "draai check_card met --graded om een echt antwoord te zien.")
                stuck = True
                break
        else:
            unreadable_run = 0
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
        rec = {"product_id": p["product_id"], "grade_key": gk, "checked_on": today, "n_rows": len(data),
               "horizon_days": max(horizon, (prev or {}).get("horizon_days") or 0), "complete": bool(complete)}
        memory[(p["product_id"], gk)] = rec
        pending.append(rec)
        done += 1
        if len(pending) >= 200:
            _flush(store, pending, log)
    _flush(store, pending, log)
    return done, rows_total, stuck


def run(store, pk, today, log=print, deadline=None, target_days=None, usd_eur=None):
    """Eerst alle kaart/graad-combinaties die nog nooit of al een tijd niet zijn opgevraagd, tot config.HISTORY_PERIOD terug; is er daarna
    nog budget en tijd, dan de combinaties met veel verkopen (niet 'klaar') verder terug tot target_days."""
    cards = famous_graded_targets(store)
    log(f"Gegradeerde geschiedenis (beroemde Pokémon): {len(cards)} kaarten in aanmerking.")
    if not cards:
        return 0
    try:
        memory = load_checks(store, [c["product_id"] for c in cards])
    except Exception as e:
        log(f"! tabel graded_checks niet te lezen ({type(e).__name__}); draai supabase/schema.sql opnieuw. Zonder dit geheugen zou elke nacht hetzelfde "
            "worden opgevraagd, dus ik sla deze stap over.")
        return 0
    if usd_eur is None:
        import fx
        import requests
        usd_eur, src = fx.usd_to_eur(requests.Session())
        log(f"Gegradeerde geschiedenis: USD->EUR {usd_eur:.4f} ({src}).")

    todo = [(c, grader, grade) for c in cards for grader, grades in GRADES.items() for grade in grades]
    due = [t for t in todo if _due(memory.get((t[0]["product_id"], f"{t[1]}-{t[2]}")), today)]
    due.sort(key=lambda t: (str((memory.get((t[0]["product_id"], f"{t[1]}-{t[2]}")) or {}).get("checked_on") or ""),   # nooit opgevraagd eerst, dan het langst geleden
                            GRADE_PRIORITY.get(t[2], 9)))                                                                  # en dan de best verhandelde graden
    base_days = int(config.HISTORY_PERIOD.rstrip("d"))
    log(f"Gegradeerde geschiedenis: {len(due)} van {len(todo)} combinaties zijn aan de beurt; budget voor deze stap maximaal {config.GRADED_BUDGET} credits.")
    original_budget = pk.budget
    pk.budget = min(original_budget, pk.credits + config.GRADED_BUDGET)   # eigen plafond: dit mag de rest van de nacht nooit meer opslokken
    state = {}
    rows_total = 0
    try:
        done, rows, stuck = _process(store, pk, today, due, memory, base_days, usd_eur, log, deadline, state)
        rows_total += rows
        log(f"Gegradeerde geschiedenis: {done} combinaties opgevraagd, {rows} prijspunten toegevoegd ({pk.credits} credits tot nu toe)"
            + ("; de cursor werkt niet (alleen de eerste pagina per opvraging)" if state.get("cursor_ok") is False else "") + ".")
        if target_days and not stuck and not pk.over_budget() and not (deadline and time.time() >= deadline):
            deep = int(str(target_days).rstrip("d"))
            more = [t for t in todo if (m := memory.get((t[0]["product_id"], f"{t[1]}-{t[2]}"))) and not m.get("complete")
                    and (m.get("horizon_days") or 0) < deep and (m.get("n_rows") or 0) >= 20 and state.get("cursor_ok") is not False]
            if more:
                log(f"Gegradeerde geschiedenis: budget/tijd over, {len(more)} drukke combinaties verder terug tot {deep} dagen.")
                for t in more:
                    memory.pop((t[0]["product_id"], f"{t[1]}-{t[2]}"), None)   # zonder vorige opvraging: tot de nieuwe grens terug
                done2, rows2, _ = _process(store, pk, today, more, memory, deep, usd_eur, log, deadline, state)
                rows_total += rows2
                log(f"Gegradeerde geschiedenis (verdieping): {done2} combinaties, {rows2} extra prijspunten ({pk.credits} credits tot nu toe).")
    finally:
        pk.budget = original_budget
    return rows_total
