"""Stap 2 van het meersignalenplan: elke kaart van de beroemde Pokémon krijgt een aantal losse signalen, elk
+1 (gunstig om te kopen), 0 (neutraal) of -1 (ongunstig). Home gaat later alleen kaarten tonen waar meerdere
signalen tegelijk positief zijn, maar pas nadat de backtest hieronder laat zien dat zo'n combinatie ook echt
vaker uitkomt dan gemiddeld.

Signalen uit de prijsgeschiedenis (ook terug in de tijd te testen):
  onder_gemiddelde   prijs t.o.v. het gemiddelde van de laatste 180 dagen (eronder = positief, ver erboven = negatief;
                     de backtest liet al zien dat net gestegen kaarten vaker terugzakken dan doorstijgen)
  stabiliseert       onder het gemiddelde en de laatste 14 dagen rustig = de daling lijkt voorbij
  piek               meer dan +25% in 14 dagen = negatief (zakt vaak terug)
  valt_nog           meer dan 10% gedaald in 14 dagen = negatief (de daling is nog niet voorbij)
Uit de kaartgegevens:
  reprint            er bestaat een nieuwere druk van dezelfde kaart = negatief
Uit de dagelijkse marktmomentopname (market_snapshot.py, via PkmnPrices, alleen voor kandidaten):
  liquiditeit        te weinig verkopers = negatief (dunne markt, prijs kan door 1 verkoper bepaald worden); meteen
  aanbod             aantal listings neemt af = positief, neemt toe = negatief; pas na SIG_MIN_SNAPSHOT_DAYS dagen
  vraag              (nog) geen bron: PkmnPrices geeft geen recente verkopen, deze blijft leeg

    python signals.py                 # momentopname + signalen van vandaag berekenen en opslaan (de dagelijkse taak)
    python signals.py --backtest      # per signaal nagaan hoe vaak een +10% stijging binnen 30 dagen volgde, met en zonder
                                      # de pieken in de Near Mint-reeks (zie analysis.clean_nm_rows)
    python signals.py --skip-snapshot # alleen signalen, zonder PokemonPriceTracker
"""
import argparse
import math
import os
import time
from datetime import date, timedelta

import analysis
import config
from store import SupabaseStore

PRICE_SIGNALS = ("onder_gemiddelde", "stabiliseert", "piek", "valt_nog")
MARKET_SIGNALS = ("aanbod", "vraag", "liquiditeit")


# ---------------- gegevens laden ----------------
def famous_products(store):
    return {p["product_id"]: p for p in store.products("card") if p.get("dex_id") in config.FAMOUS_DEX_IDS}


def load_inputs(store, product_ids, since):
    """De ruwe prijsrijen per kaart (Cardmarket-reeks en Near Mint-reeks), in stukjes van 150 kaarten opgehaald, zodat
    het nooit de hele prijzentabel doorbladert."""
    raw, nm = {}, {}
    ids = sorted(product_ids)
    for i in range(0, len(ids), 150):
        ch = ",".join(ids[i:i + 150])
        for gk, target in (("raw", raw), ("nm", nm)):
            for r in store.select("prices", {"select": "product_id,date,source,price,avg7,avg30", "product_id": f"in.({ch})",
                                             "grade_key": f"eq.{gk}", "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
                if r.get("price") is not None:
                    target.setdefault(r["product_id"], []).append(
                        {**r, "price": float(r["price"]), "anchor": r.get("avg30") or r.get("avg7"), "avg1": None, "avg7": None, "avg30": None})
    return ids, raw, nm


def build_series(inputs, clean=False, stats=None):
    """Prijsreeks per kaart, op dezelfde manier opgebouwd als de kansberekening (Near Mint als die er is, anders de
    trend). clean=True haalt pieken uit de Near Mint-reeks (zie analysis.clean_nm_rows)."""
    ids, raw, nm = inputs
    out = {}
    for pid in ids:
        by_source = {}
        for r in raw.get(pid, []):
            by_source.setdefault(r["source"], []).append(r)
        s = analysis.series_for(pid, by_source, nm_rows=nm.get(pid), clean=clean, clean_stats=stats)
        if s:
            out[pid] = [(x["date"], float(x["price"])) for x in s if x.get("price")]
    return out


def load_series(store, product_ids, since, clean=False, stats=None):
    return build_series(load_inputs(store, product_ids, since), clean=clean, stats=stats)


def load_snapshots(store, product_ids, since):
    out = {}
    ids = sorted(product_ids)
    for i in range(0, len(ids), 150):
        for r in store.select("market_snapshots", {"select": "*", "product_id": f"in.({','.join(ids[i:i + 150])})",
                                                    "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
            out.setdefault(r["product_id"], []).append(r)
    return out


# ---------------- signalen ----------------
def _price_on_or_before(points, day):
    best = None
    for d, p in points:
        if d <= day:
            best = p
        else:
            break
    return best


def price_signals(points):
    """points: [(datum, prijs)] tot en met 'vandaag', oplopend. Geeft None als er te weinig geschiedenis is."""
    if len(points) < 20:
        return None
    today = date.fromisoformat(points[-1][0])
    first = date.fromisoformat(points[0][0])
    if (today - first).days < 60:
        return None
    since = (today - timedelta(days=180)).isoformat()
    hist = [p for d, p in points if d >= since]
    p = points[-1][1]
    avg = sum(hist) / len(hist)
    vs_avg = p / avg - 1 if avg else 0.0
    p14 = _price_on_or_before(points, (today - timedelta(days=14)).isoformat())
    m14 = p / p14 - 1 if p14 else 0.0
    last14 = [x for d, x in points if d > (today - timedelta(days=14)).isoformat()]
    mean14 = sum(last14) / len(last14) if last14 else p
    cv14 = (math.sqrt(sum((x - mean14) ** 2 for x in last14) / len(last14)) / mean14) if len(last14) >= 3 and mean14 else None

    s = {}
    s["onder_gemiddelde"] = 1 if vs_avg <= -config.SIG_BELOW_AVG else (-1 if vs_avg >= config.SIG_BELOW_AVG else 0)
    s["stabiliseert"] = 1 if (vs_avg <= -0.10 and cv14 is not None and cv14 <= config.SIG_STABLE_CV and m14 >= -0.03) else 0
    # momentum alleen nog als waarschuwing: de backtest van 30 sep liet zien dat 'licht herstel' geen voorspellende
    # waarde had (slechter dan gemiddeld), dus telt het niet meer als positief signaal
    s["piek"] = -1 if m14 > config.SIG_MOM_SPIKE else 0
    s["valt_nog"] = -1 if m14 < config.SIG_MOM_FALLING else 0
    return {"signals": s, "vs_avg": round(vs_avg, 4), "momentum_14d": round(m14, 4), "cv_14d": round(cv14, 4) if cv14 is not None else None, "price": p}


def market_signals(snaps):
    """snaps: momentopnames van één kaart, oplopend op datum. Signalen pas na SIG_MIN_SNAPSHOT_DAYS dagen."""
    out = {}
    if snaps:
        sellers = snaps[-1].get("sellers")
        if sellers is not None:
            out["liquiditeit"] = -1 if sellers < config.SIG_MIN_SELLERS else (1 if sellers >= 10 else 0)
    if len(snaps) < config.SIG_MIN_SNAPSHOT_DAYS:
        return out

    def trend(key):
        vals = [s.get(key) for s in snaps[-14:] if s.get(key) is not None]
        if len(vals) < 10:
            return None
        a, b = vals[: len(vals) // 2], vals[len(vals) // 2:]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        return (mb / ma - 1) if ma else None

    lt, st = trend("listings"), trend("recent_sales")
    if lt is not None:
        out["aanbod"] = 1 if lt <= -0.10 else (-1 if lt >= 0.10 else 0)
    if st is not None:
        out["vraag"] = 1 if st >= 0.10 else (-1 if st <= -0.10 else 0)
    return out


def combine(price_part, product, snaps):
    sig = dict(price_part["signals"]) if price_part else {}
    sig["reprint"] = -1 if product.get("newer_printing") else 0
    sig.update(market_signals(snaps or []))
    return {"signals": sig, "n_positive": sum(1 for v in sig.values() if v > 0), "n_negative": sum(1 for v in sig.values() if v < 0),
            "score": sum(sig.values())}


# ---------------- dagelijks berekenen en opslaan ----------------
def compute_today(store, today, log=print):
    products = famous_products(store)
    if not products:
        log("Signalen: nog geen kaarten van beroemde Pokémon gevonden.")
        return 0
    series = load_series(store, products, (date.fromisoformat(today) - timedelta(days=200)).isoformat())
    snaps = load_snapshots(store, products, (date.fromisoformat(today) - timedelta(days=30)).isoformat())
    rows = []
    for pid, pts in series.items():
        pp = price_signals(pts)
        if not pp:
            continue
        c = combine(pp, products[pid], snaps.get(pid))
        sig = c["signals"]
        rows.append({"product_id": pid, "date": today, "price": pp["price"], "vs_avg": pp["vs_avg"], "momentum_14d": pp["momentum_14d"],
                     "cv_14d": pp["cv_14d"], "s_onder_gemiddelde": sig.get("onder_gemiddelde"), "s_stabiliseert": sig.get("stabiliseert"),
                     "s_momentum": min(sig.get("piek", 0), sig.get("valt_nog", 0)),   # -1 = piek of valt nog
                     "s_reprint": sig.get("reprint"), **{f"s_{k}": sig.get(k) for k in MARKET_SIGNALS},
                     "n_positive": c["n_positive"], "n_negative": c["n_negative"], "score": c["score"]})
    if rows:
        store.upsert("card_signals", rows, "product_id,date")
    n_cand = sum(1 for r in rows if r["s_onder_gemiddelde"] == 1 and r["n_negative"] == 0)
    n_best = sum(1 for r in rows if r["s_onder_gemiddelde"] == 1 and r["s_stabiliseert"] == 1 and r["n_negative"] == 0)
    n_market = sum(1 for r in rows if r["s_aanbod"] is not None)
    log(f"Signalen: {len(rows)} kaarten beoordeeld ({len(series) - len(rows)} met te weinig geschiedenis); "
        f"{n_cand} kaarten onder hun gemiddelde zonder negatief signaal, waarvan {n_best} ook gestabiliseerd; "
        f"aanbod/vraag al meegeteld bij {n_market} kaarten.")
    return len(rows)


# ---------------- backtest per signaal ----------------
OUTCOMES = ("raakt +10%", "na 30d +10%", "raakt +20%", "winst na kosten")


def _outcomes(p0, later, fee):
    """later: [(datum, prijs)] binnen de periode. Vier manieren om 'het kwam uit' te meten, van soepel naar streng."""
    top = max(p for _, p in later)
    end = later[-1][1]
    net = end * (1 - fee) - config.PACKAGING - (p0 + config.ship_cost(p0))   # kopen incl. verzending, verkopen op dag 30 na commissie en verpakking
    return (top >= p0 * 1.10, end >= p0 * 1.10, top >= p0 * 1.20, net > 0)


def groups_for(sig):
    """Onder welke groepen een meetmoment valt: elk los signaal, plus de combinaties die we willen vergelijken."""
    g = ["alle momenten"]
    for name, v in sig.items():
        if v:
            g.append(f"{name} {'+' if v > 0 else '-'}")
    neg = any(v < 0 for v in sig.values())
    onder, stab = sig.get("onder_gemiddelde") == 1, sig.get("stabiliseert") == 1
    if onder and not neg:
        g.append("onder gem., geen negatief")
    if onder and stab:
        g.append("onder gem. + stabiliseert")
    if onder and stab and not neg:
        g.append("onder gem. + stab., geen neg.")
    return g


def backtest(store, today, horizon=30, step=5, log=print, series=None):
    """Loopt terug in de tijd: op een moment de prijssignalen berekenen met alleen de data tot dan, en kijken wat de
    prijs daarna binnen 'horizon' dagen deed. Per kaart maar één meetmoment per periode (niet-overlappend), zodat één
    wispelturige kaart niet tientallen keren meetelt. Alleen de prijssignalen: aanbod, vraag en liquiditeit hebben
    (nog) geen geschiedenis, en reprint verandert niet in de tijd."""
    if series is None:
        products = famous_products(store)
        series = load_series(store, products, (date.fromisoformat(today) - timedelta(days=400)).isoformat())
    fee = config.DEFAULT_FEE_PCT / 100
    tally = {}
    for pid, pts in series.items():
        next_ok = ""
        for i in range(20, len(pts), step):
            if pts[i][0] < next_ok:
                continue
            target = (date.fromisoformat(pts[i][0]) + timedelta(days=horizon)).isoformat()
            if pts[-1][0] < target:
                break
            later = [(d, p) for d, p in pts[i + 1:] if d <= target]
            pp = price_signals(pts[: i + 1])
            if not later or not pp:
                continue
            res = _outcomes(pp["price"], later, fee)
            for g in groups_for(pp["signals"]):
                t = tally.setdefault(g, [0, 0, 0, 0, 0])
                t[0] += 1
                for k, hit in enumerate(res, 1):
                    t[k] += 1 if hit else 0
            next_ok = target   # volgende meetmoment van deze kaart pas na afloop van deze periode
    if not tally:
        log("Signalen-backtest: nog te weinig geschiedenis.")
        return tally
    base = tally["alle momenten"]
    log(f"Signalen-backtest (kaarten van beroemde Pokémon, periode {horizon} dagen, per kaart niet-overlappend):")
    log(f"  {'groep':<31}{'n':>5}  " + "  ".join(f"{o:>16}" for o in OUTCOMES))
    order = ["alle momenten"] + sorted(k for k in tally if k != "alle momenten" and not k[0].isupper() and "gem." not in k) + \
            sorted(k for k in tally if "gem." in k)
    for key in order:
        t = tally[key]
        cells = []
        for k in range(1, 5):
            rate = t[k] / t[0]
            diff = "" if key == "alle momenten" else f" ({(rate - base[k] / base[0]) * 100:+.0f})"
            cells.append(f"{rate * 100:5.1f}%{diff:>7}")
        log(f"  {key:<31}{t[0]:>5}  " + "  ".join(f"{c:>16}" for c in cells))
    log("  (tussen haakjes: verschil in procentpunten t.o.v. alle momenten; 'winst na kosten' = gekocht incl. verzending, verkocht op dag 30 na 6% commissie en verpakking)")
    return tally


def compare_cleaning(store, today, log=print, horizon=30):
    """Draait de backtest twee keer op dezelfde data: zoals het was, en met de pieken uit de Near Mint-reeks gehaald.
    Blijft 'onder het gemiddelde' ook zonder die pieken sterk voorspellen, dan is het geen bijeffect van de pieken."""
    products = famous_products(store)
    inputs = load_inputs(store, products, (date.fromisoformat(today) - timedelta(days=400)).isoformat())
    log("=== A. Zoals het was (Near Mint-reeks ongewijzigd) ===")
    a = backtest(store, today, horizon=horizon, log=log, series=build_series(inputs, clean=False))
    stats = {}
    clean_series = build_series(inputs, clean=True, stats=stats)
    n = max(stats.get("in", 0), 1)
    log("")
    log(f"=== B. Met pieken eruit gehaald ===")
    log(f"  Near Mint-punten: {stats.get('in', 0)} -> {stats.get('out', 0)}; verwijderd {stats.get('in', 0) - stats.get('out', 0)} "
        f"({(stats.get('in', 0) - stats.get('out', 0)) / n * 100:.1f}%): {stats.get('anchor', 0)} via Cardmarkets verkoopgemiddelde, "
        f"{stats.get('causal', 0)} via de schatting uit de eigen reeks; {stats.get('cards_changed', 0)} van {stats.get('cards', 0)} kaarten aangepast")
    b = backtest(store, today, horizon=horizon, log=log, series=clean_series)
    return a, b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--skip-snapshot", action="store_true")
    args = ap.parse_args()
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today().isoformat()
    compute_today(store, today)   # eerst de signalen: de momentopname kiest zijn kandidaten daaruit
    if not args.skip_snapshot:
        import market_snapshot
        pk = None
        if os.environ.get("PKMN_API_KEY"):
            from pkmnprices import PkmnPrices
            pk = PkmnPrices(os.environ["PKMN_API_KEY"], budget=config.SNAPSHOT_PK_BUDGET)
        try:
            if market_snapshot.run(store, pk, today, deadline=time.time() + config.SNAPSHOT_MAX_MINUTES * 60):
                compute_today(store, today)   # opnieuw, zodat liquiditeit van vandaag meteen meetelt
        except Exception as e:   # de signalen zelf staan er dan al, alleen zonder de momentopname van vandaag
            print(f"! marktmomentopname mislukt: {type(e).__name__}: {e}")
    if args.backtest:
        compare_cleaning(store, today)


if __name__ == "__main__":
    main()
