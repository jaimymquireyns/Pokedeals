"""Dagelijkse taak: prijzen ophalen, kansen berekenen, trackrecord bijwerken, meldingen sturen.

Lokaal proberen:
    export SUPABASE_URL=https://xxxx.supabase.co
    export SUPABASE_SECRET_KEY=...          # de GEHEIME sleutel
    export PPT_API_KEY=...                  # optioneel: sealed, graded en historie
    python run.py --list-sets
    python run.py --recent 3
    python run.py --probe-ppt               # test wat PokemonPriceTracker teruggeeft
"""
import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from itertools import groupby

import analysis
import config
from providers import TCGdex
from store import SupabaseStore


# ---------------------------------------------------------------------------
# Kaarten (TCGdex)
# ---------------------------------------------------------------------------
def _should_skip(last, today, min_track, force):
    if not last:
        return False
    if last["date"] == today and not force:
        return True
    if last["price"] is not None and float(last["price"]) < min_track:
        age = (date.fromisoformat(today) - date.fromisoformat(last["date"])).days
        return age < config.RECHECK_CHEAP_DAYS
    return False


def collect_cards(provider, store, set_ids, today, min_track=None, workers=None, force=False, log=print):
    min_track = config.MIN_TRACK_PRICE if min_track is None else min_track
    workers = workers or config.WORKERS
    last = store.latest_prices()
    stats = {"cards": 0, "prices": 0, "skipped": 0, "errors": 0}

    def flush(products, prices):
        if products:
            store.upsert_products(products)
        if prices:
            store.upsert_prices(prices)
        products.clear()
        prices.clear()

    for set_id in set_ids:
        s = provider.get_set(set_id)
        if not s:
            log(f"! set {set_id} niet gevonden")
            continue
        store.upsert_sets([{"set_id": s["set_id"], "name": s["name"], "release_date": s.get("release_date"),
                            "card_total": s.get("card_total")}])
        todo = [c for c in s["cards"] if not _should_skip(last.get(c["card_id"]), today, min_track, force)]
        stats["skipped"] += len(s["cards"]) - len(todo)
        log(f"{s['name']} ({set_id}): {len(todo)} ophalen, {len(s['cards']) - len(todo)} overgeslagen")

        products, prices = [], []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(provider.get_card, c["card_id"]): c for c in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                try:
                    res = fut.result()
                except Exception as e:
                    stats["errors"] += 1
                    log(f"  fout bij {futures[fut]['card_id']}: {e}")
                    continue
                if not res:
                    continue
                products.append(res["product"])
                stats["cards"] += 1
                if res["price"]:
                    prices.append({"product_id": res["product"]["product_id"], "date": today, "source": "tcgdex",
                                   "grade_key": "raw", **res["price"]})
                    stats["prices"] += 1
                if i % 100 == 0:
                    flush(products, prices)
                    log(f"  {i}/{len(todo)}")
        flush(products, prices)
    log(f"Kaarten klaar: {stats}")
    return stats


def newest_sets(provider, store, n, workers=None, log=print):
    known = store.known_sets()
    missing = [s["set_id"] for s in provider.list_sets() if s["set_id"] not in known]
    if missing:
        log(f"Releasedatums ophalen voor {len(missing)} sets (eenmalig)...")
        with ThreadPoolExecutor(max_workers=workers or config.WORKERS) as ex:
            rows = [s for s in ex.map(provider.get_set, missing) if s]
        store.upsert_sets([{"set_id": s["set_id"], "name": s["name"], "release_date": s.get("release_date"),
                            "card_total": s.get("card_total")} for s in rows])
    rows = [r for r in store.known_sets().values() if r.get("release_date")]
    rows.sort(key=lambda r: r["release_date"], reverse=True)
    return [r["set_id"] for r in rows[:n]]


# ---------------------------------------------------------------------------
# Sealed (Cardmarket, openbare prijslijst)
# ---------------------------------------------------------------------------
def scan_sealed(session, store, today, log=print):
    import cardmarket
    guide = cardmarket.load_price_guide(session)
    products = cardmarket.load_sealed(session)
    set_names = cardmarket.resolve_set_names(products, store.known_sets())
    prods, prices = cardmarket.sealed_rows(products, guide, today, set_names)
    # Wat de verrijking (enrich.py) al heeft ingevuld mag niet worden overschreven door een dagelijkse gok
    existing = {p["product_id"]: p for p in store.products("sealed")}
    has_pk = any("pk_id" in o for o in existing.values())      # kolom pk_id bestaat pas na de SQL-aanvulling
    for p in prods:
        old = existing.get(p["product_id"], {})
        p["set_name"] = old.get("set_name") or p.get("set_name")
        p["image"] = old.get("image")
        if has_pk:
            p["pk_id"] = old.get("pk_id")
    if prods:
        store.upsert_products(prods)
        store.upsert_prices(prices)
    log(f"Sealed van Cardmarket: {len(prods)} producten met prijs (van {len(products)} herkend)")
    return len(prods)


# ---------------------------------------------------------------------------
# Kansen
# ---------------------------------------------------------------------------
def choose_stats_all(rows):
    """Kalibratiegegevens per periode (horizon_days, threshold_pct): live-uitkomsten als er genoeg zijn, anders de backtest.
    Geeft {(horizon, pct): {bucket: {n, hits}}}."""
    by = {}
    for r in rows:
        key = (r["horizon_days"], r["threshold_pct"])
        by.setdefault(key, {"live": {}, "backtest": {}})
        if r["source"] in by[key]:
            by[key][r["source"]][r["bucket"]] = r
    out = {}
    for key, srcs in by.items():
        combo = {}
        for _, _, b in analysis.BUCKETS:
            live, back = srcs["live"].get(b), srcs["backtest"].get(b)
            pick = live if live and live["n"] >= config.CALIBRATE_MIN_N else back
            if pick:
                combo[b] = {"n": pick["n"], "hits": pick["hits"]}
        out[key] = combo
    return out


def build_forecasts(store, today, log=print, combos=None):
    combos = combos or config.GRID
    since = (date.fromisoformat(today) - timedelta(days=config.HISTORY_DAYS)).isoformat()
    stats_all = choose_stats_all(store.select("trackrecord_stats", {"select": "*"}))
    rows = store.price_rows(since)
    nm_by_pid = {}
    for r in store.price_rows(since, grade_key="nm"):
        nm_by_pid.setdefault(r["product_id"], []).append({**r, "price": float(r["price"]) if r.get("price") is not None else None})
    for pid in nm_by_pid:
        nm_by_pid[pid].sort(key=lambda r: r["date"])
    out, history, nm_used = [], [], 0
    for pid, grp in groupby(rows, key=lambda r: r["product_id"]):
        by_source = {}
        for r in grp:
            by_source.setdefault(r["source"], []).append(
                {**r, **{k: (float(r[k]) if r.get(k) is not None else None) for k in ("price", "avg1", "avg7", "avg30", "low")}})
        nm_rows = nm_by_pid.get(pid)
        basis = "nm" if nm_rows and len(nm_rows) >= config.MIN_HISTORY_POINTS else "trend"
        if basis == "nm":
            nm_used += 1
        series = analysis.series_for(pid, by_source, nm_rows=nm_rows)
        if not series or series[-1]["avg30"] is None:
            continue    # geen verkopen in de laatste 30 dagen: te dunne markt voor een betrouwbare kans
        for horizon, pct in combos:
            f = analysis.forecast(series, horizon, pct / 100)
            if not f or f["price"] < config.MIN_PRICE:
                continue
            p_raw = f["p_up"]
            p_up, p_down = f["p_up"], f["p_down"]
            p_up = analysis.calibrate(p_up, stats_all.get((horizon, pct), {}))
            if horizon <= 60:   # alleen periodes die binnen een redelijke tijd echt kunnen worden nagekeken
                history.append({"product_id": pid, "date": today, "horizon_days": horizon, "threshold_pct": pct,
                                "p_up": round(p_raw, 4), "price": f["price"], "signal": analysis._signal(p_raw, p_down)})
            out.append({
                "product_id": pid, "horizon_days": horizon, "threshold_pct": pct,
                "price": f["price"], "avg7": f["avg7"], "avg30": f["avg30"], "mom30": f["mom30"],
                "p_up": round(p_up, 4), "p_down": round(p_down, 4), "exp_change": round(f["exp_change"], 4),
                "exp_up": round(f["exp_up"], 4), "exp_down": round(f["exp_down"], 4),
                "score": round(p_up - p_down, 4), "sigma": round(f["sigma"], 5),
                "signal": analysis._signal(p_up, p_down), "mode": f["mode"], "confidence": f["confidence"],
                "n": f["n"], "updated": f["updated"], "computed_on": today, "basis": basis,
            })
    if out:
        store.upsert("forecasts", out, "product_id,horizon_days,threshold_pct")
    horizons = sorted({h for h, _ in combos})   # alleen de net berekende periodes opruimen, niet die van een andere cyclus (bijv. de wekelijkse lange periodes)
    if horizons:
        store.delete("forecasts", {"horizon_days": f"in.({','.join(map(str, horizons))})", "computed_on": f"lt.{today}"})
    if history:
        store.upsert("forecast_history", history, "product_id,date,horizon_days,threshold_pct")
    log(f"Kansen berekend: {len(out)} rijen voor {len({r['product_id'] for r in out})} producten"
        f"{' (gekalibreerd voor ' + str(len(stats_all)) + ' periodes)' if stats_all else ''}, "
        f"waarvan {nm_used} kaarten op basis van eigen Near Mint-geschiedenis")
    return out


def prune(store, today, log=print):
    cutoff = (date.fromisoformat(today) - timedelta(days=config.PRUNE_CHEAP_DAYS)).isoformat()
    store.delete("prices", {"price": f"lt.{config.MIN_PRICE}", "date": f"lt.{cutoff}"})
    log("Oude prijzen van goedkope kaarten opgeruimd")


# ---------------------------------------------------------------------------
# Hoofdprogramma
# ---------------------------------------------------------------------------
def spend_pkmn_credits(store, today, log=print, time_budget=None):
    """NM-prijzen, kaartgeschiedenis en sealed-geschiedenis delen hier één PkmnPrices-budget voor de hele dag
    (in die volgorde). Los aanroepbaar (--credits-only) zodat je dit kort voor het einde van de PkmnPrices-dag
    nog een keer kunt draaien om overgebleven credits te benutten, i.p.v. ze te laten verlopen.
    Stopt zichzelf ook op tijd (standaard na 4 uur): bij een groot dagbudget kan PkmnPrices' eigen snelheidslimiet
    (60 verzoeken per minuut) er anders voor zorgen dat de taak de 5 à 6 uur die GitHub Actions toestaat overschrijdt
    en van buitenaf wordt afgebroken. Bij een nette, eigen stop blijft alles wat al gelukt is gewoon staan, en de
    rest volgt gewoon de volgende keer — net als wanneer het creditbudget op is."""
    if not os.environ.get("PKMN_API_KEY"):
        log("PKMN_API_KEY niet gevonden: NM-prijzen en sealed-geschiedenis worden overgeslagen (kans-berekening zelf werkt hier los van).")
        return
    deadline = time.time() + (time_budget if time_budget is not None else config.PK_TIME_BUDGET)
    from pkmnprices import PkmnPrices
    pk_client = PkmnPrices(os.environ["PKMN_API_KEY"], budget=config.PK_BUDGET)
    try:
        import nm
        import card_history
        core = nm.core_ids(store)   # eigen collectie + prijsmeldingen: eerste, kleine prioriteitsronde vóór al het andere
        core_products = {p["product_id"]: p for p in store.products("card") if p["product_id"] in set(core)}
        core_cards = [pid for pid in core if pid in core_products]
        log(f"Eigen collectie eerst: {len(core)} item(s) in collectie/prijsmeldingen, {len(core_cards)} daarvan zijn kaarten met bekende gegevens.")
        if core_cards:
            nm._map_and_refresh(store, pk_client, today, core_cards, core_products, log, deadline=deadline, refresh_price=config.NM_REFRESH_PRICE)
            card_history.run(store, pk_client, today, log=log, deadline=deadline, only=core_cards)
    except Exception as e:
        log(f"! eigen collectie eerst overgeslagen: {e}")
    try:
        import nm
        nm.run(store, pk_client, today, log=log, deadline=deadline)
    except Exception as e:  # de actuele NM-prijs is het belangrijkst, dus die gaat als eerste
        log(f"! NM-prijzen overgeslagen: {e}")
    try:
        import card_history
        card_history.run(store, pk_client, today, log=log, deadline=deadline)   # deelt hetzelfde budget: bouwt Near Mint-geschiedenis op, kaart voor kaart, zonder vast maximum
    except Exception as e:
        log(f"! kaartgeschiedenis overgeslagen: {e}")
    try:
        import sealed_history
        sealed_history.run(store, pk_client, today, log=log, deadline=deadline)   # krijgt wat de twee taken hierboven nog overlaten
    except Exception as e:
        log(f"! sealed-geschiedenis overgeslagen: {e}")
    try:
        import offers
        offers.run(store, pk_client, today, log=log, deadline=deadline)   # laagste aanbiedingen: helemaal achteraan, profiteert van budget dat vrijkomt
    except Exception as e:
        log(f"! laagste aanbiedingen overgeslagen: {e}")


def daily(store, tcg, ppt, sender, today, set_ids, log=print, pk_time_budget=None):
    import alerts
    import features
    import fx as fxmod
    import trackrecord

    rate, src = fxmod.usd_to_eur(tcg.session)
    log(f"USD→EUR: {rate:.4f} ({src})")
    collect_cards(tcg, store, set_ids, today, log=log)
    try:
        scan_sealed(tcg.session, store, today, log=log)
    except Exception as e:  # kaarten gaan dan gewoon door
        log(f"! sealed van Cardmarket overgeslagen: {e}")
    features.update_static(store, log=log)
    try:
        features.update_pageviews(store, today, log=log)
    except Exception as e:  # context-data is niet essentieel
        log(f"pageviews overgeslagen: {e}")
    build_forecasts(store, today, log=log)
    if date.fromisoformat(today).weekday() == 0:
        build_forecasts(store, today, log=log, combos=config.LONG_GRID)
    else:
        log("Lange periodes (3-24 maanden) worden alleen op maandag herberekend; vandaag overgeslagen.")
    spend_pkmn_credits(store, today, log=log, time_budget=pk_time_budget)
    trackrecord.resolve(store, today, log=log)
    if date.fromisoformat(today).weekday() == 0:   # maandag: ook de backtest bijwerken (dekt alle periodes, ook de lange)
        try:
            trackrecord.backtest(store, today, log=log)
        except Exception as e:
            log(f"! backtest overgeslagen: {e}")
    alerts.evaluate(store, sender, today, log=log)
    alerts.send_digest(store, sender, today, log=log)
    prune(store, today, log=log)


def make_sender(log=print):
    pem = os.environ.get("VAPID_PRIVATE_KEY")
    if not pem:
        log("Geen VAPID_PRIVATE_KEY: meldingen worden niet verstuurd")
        return None
    from push import WebPushSender
    return WebPushSender(pem, os.environ.get("VAPID_SUBJECT", "mailto:jij@example.com"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-sets", action="store_true")
    ap.add_argument("--sets", nargs="+")
    ap.add_argument("--recent", type=int)
    ap.add_argument("--forecast-only", action="store_true")
    ap.add_argument("--probe-ppt", action="store_true", help="test de gegevensbronnen (Cardmarket en PokemonPriceTracker)")
    ap.add_argument("--credits-only", action="store_true",
                    help="alleen NM-prijzen en sealed-geschiedenis (PkmnPrices); voor een korte, late taak die overgebleven dagcredits nog benut")
    ap.add_argument("--pk-minutes", type=int, help="tijdslimiet in minuten voor de PkmnPrices-onderdelen (standaard 4 uur); handig om snel te testen zonder er lang op te wachten")
    args = ap.parse_args()

    tcg = TCGdex()
    if args.list_sets:
        for s in tcg.list_sets():
            print(f"{s['set_id']:<12} {s['name']}")
        return

    ppt = None
    if os.environ.get("PPT_API_KEY"):
        from ppt import PPT
        ppt = PPT(os.environ["PPT_API_KEY"])
    if args.probe_ppt:
        import cardmarket
        guide = cardmarket.probe(tcg.session)
        print()
        import shipping
        shipping.probe()
        if os.environ.get("PKMN_API_KEY"):
            import pkmnprices
            print()
            pkmnprices.probe(pkmnprices.PkmnPrices(os.environ["PKMN_API_KEY"]), guide)
        else:
            print("\n(geen PKMN_API_KEY: PkmnPrices-test overgeslagen)")
        if ppt:
            print()
            ppt.probe()
        return

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        ap.error("zet SUPABASE_URL en SUPABASE_SECRET_KEY")
    store = SupabaseStore(url, key)
    today = date.today().isoformat()
    if args.forecast_only:
        build_forecasts(store, today)
        return
    if args.credits_only:
        spend_pkmn_credits(store, today, time_budget=config.PK_CREDITS_ONLY_TIME_BUDGET)
        return
    set_ids = args.sets or (newest_sets(tcg, store, args.recent) if args.recent else None)
    if not set_ids:
        ap.error("kies --sets of --recent")
    daily(store, tcg, ppt, make_sender(), today, set_ids, pk_time_budget=args.pk_minutes * 60 if args.pk_minutes else None)


if __name__ == "__main__":
    main()
