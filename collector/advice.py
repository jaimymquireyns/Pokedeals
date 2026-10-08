"""Advies per kaart: kopen, verkopen, houden of verdacht. Bewust eenvoudige regels die je zelf kunt narekenen, geen voorspelling.

Waarom zo. De backtests van de app lieten zien dat trendsignalen ('het stijgt, dus het blijft stijgen') niets voorspellen, en dat
prijzen die ver van hun normale niveau staan meestal terugkeren. Het advies kijkt dus maar naar één ding: staat een kaart nu ver
boven of ver onder zijn normale prijs, en wordt dat bevestigd door echte verkopen? Of dat werkt, toetsen we zelf: elk advies
wordt bewaard, en na 30 dagen gekeken of het klopte (evaluate). De uitkomst staat in de app.

Per product één toestand (de app maakt er per persoon Kopen/Verkopen/Houden van, met de eigen aankoopprijs en kosten erbij):
  hoog       de prijs staat al minstens een week ruim boven normaal, en echte verkopen bevestigen dat
  laag       de prijs staat al minstens een week ruim onder normaal, er wordt geregeld verkocht, en ook de verkopen liggen lager
  verdacht   de prijs staat ver van normaal, maar iets wijst op een gestuurde of onbetrouwbare prijs (zie FLAG_TEXT)
  normaal    niets bijzonders
  onbekend   te weinig gegevens

Bescherming tegen marktmanipulatie (zie FLAG_TEXT). Een vraagprijs kan iedereen neerzetten, een verkoop niet; daarom moet
een hoge of lage prijs altijd door Cardmarkets verkoopgemiddelde bevestigd worden, een week aanhouden, en mag er geen van
de waarschuwingen hieronder gelden.

Gegevens:
  - Cardmarket via TCGdex (bron 'tcgdex', of 'cardmarket' bij sealed): per dag de trendprijs (price), het verkoopgemiddelde
    van gisteren (avg1, leeg = geen verkoop), van 7 en 30 dagen (avg7, avg30) en de laagste vraagprijs (low).
  - De Near Mint-geschiedenis van PkmnPrices (grade_key 'nm', tot een jaar terug) voor 'normaal' over 90 dagen, zonder pieken.
"""
from datetime import date, timedelta

import config
from edge import jump_count

STATES = ("hoog", "laag", "verdacht", "normaal", "onbekend")

FLAG_TEXT = {
    "afwijking": "de vraagprijs wijkt sterk af van waarvoor de kaart echt verkocht wordt",
    "springt": "de prijs maakte de laatste 2 maanden meerdere grote sprongen",
    "weinig verkopers": "maar 1 of 2 verkopers bieden hem aan, dus de prijs is makkelijk te sturen",
    "aanbod verdwijnt": "het aanbod is de laatste 2 weken plots gehalveerd: mogelijk opgekocht",
    "te goedkoop": "de goedkoopste aanbieding is verdacht laag (minder dan de helft van de verkoopprijs)",
    "niet bevestigd": "de hoge prijs komt niet terug in de echte verkopen",
}


def _d(s):
    return date.fromisoformat(str(s)[:10])


def _median(xs):
    s = sorted(x for x in xs if x is not None)
    if not s:
        return None
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def normal_price(raw, nm, today):
    """Normale prijs en waar hij vandaan komt. Eerst de Near Mint-reeks over 90 dagen (zonder de laatste week en zonder pieken),
    anders het oudste 30-daagse verkoopgemiddelde van Cardmarket dat we hebben (dat loopt van voor de laatste week)."""
    t = _d(today)
    start, end = (t - timedelta(days=config.ADVICE_NORMAL_DAYS)).isoformat(), (t - timedelta(days=config.ADVICE_CONFIRM_DAYS)).isoformat()
    if nm:
        import analysis
        anchors = {r["date"]: _f(r.get("avg30")) for r in raw if _f(r.get("avg30"))}
        window = [r for r in nm if start <= r["date"] < end and _f(r.get("price"))]
        if len(window) >= config.ADVICE_MIN_NM_POINTS:
            kept, _ = analysis.clean_nm_rows([{"date": r["date"], "price": _f(r["price"])} for r in window], anchors=anchors)
            med = _median([r["price"] for r in kept])
            if med:
                return med, "nm"
    old = [r for r in raw if r["date"] < end and _f(r.get("avg30"))]
    if old:
        return _f(old[0]["avg30"]), "avg30"
    return None, None


def assess(raw, nm=None, today=None, sellers=None, listings=None):
    """raw: Cardmarket-rijen van één product, op datum gesorteerd ({date, price, avg1, avg7, avg30, low}); nm: Near Mint-rijen
    ({date, price}); sellers: aantal verschillende verkopers onder de goedkoopste aanbiedingen of None; listings: [(datum, aantal)]
    of None. Geeft {state, price, normal, ratio, sales7, sale_days, flags, basis}."""
    today = today or date.today().isoformat()
    raw = [r for r in raw if r["date"] <= today and _f(r.get("price"))]
    out = {"state": "onbekend", "price": None, "normal": None, "ratio": None, "sales7": None, "sale_days": 0, "flags": [], "basis": None}
    if not raw:
        return out
    t = _d(today)
    recent = [r for r in raw if r["date"] > (t - timedelta(days=config.ADVICE_CONFIRM_DAYS)).isoformat()]
    last = raw[-1]
    out["price"] = _f(last["price"])
    out["sales7"] = _f(last.get("avg7"))
    out["sale_days"] = sum(1 for r in raw if r["date"] > (t - timedelta(days=14)).isoformat() and _f(r.get("avg1")))
    normal, basis = normal_price(raw, nm or [], today)
    out["normal"], out["basis"] = normal, basis
    if not normal or len(recent) < config.ADVICE_MIN_RECENT or (t - _d(last["date"])).days > 3:
        return out
    trends = [_f(r["price"]) for r in recent]
    out["ratio"] = _median(trends) / normal

    # waarschuwingen (marktmanipulatie of een onbetrouwbare prijs)
    flags = []
    s7 = out["sales7"]
    if s7 and not (1 / config.ADVICE_SALES_MISMATCH <= out["price"] / s7 <= config.ADVICE_SALES_MISMATCH):
        flags.append("afwijking")
    pts = [(r["date"], _f(r["price"])) for r in raw]
    if jump_count(pts) >= 3:
        flags.append("springt")
    if sellers is not None and sellers <= 2:
        flags.append("weinig verkopers")
    if listings:
        now_l = listings[-1][1]
        before = [n for d, n in listings if d <= (t - timedelta(days=7)).isoformat()]
        if now_l is not None and before and before[-1] and now_l <= before[-1] * 0.5:
            flags.append("aanbod verdwijnt")
    low, a30 = _f(last.get("low")), _f(last.get("avg30"))
    cheap_listing = bool(low and a30 and low < 0.5 * a30)

    high = all(p >= config.ADVICE_HIGH * normal for p in trends)
    dip = all(p <= config.ADVICE_LOW * normal for p in trends)
    if high:
        if flags:
            out["state"] = "verdacht"
        elif not (s7 and s7 >= config.ADVICE_SALES_CONFIRM_HIGH * normal and out["sale_days"] >= 3):
            flags.append("niet bevestigd")
            out["state"] = "verdacht"
        else:
            out["state"] = "hoog"
    elif dip:
        if cheap_listing:
            flags.append("te goedkoop")
        if flags:
            out["state"] = "verdacht"
        elif out["sale_days"] >= config.ADVICE_MIN_SALE_DAYS and s7 and s7 <= config.ADVICE_SALES_CONFIRM_LOW * normal:
            out["state"] = "laag"
        else:
            out["state"] = "normaal"   # lage vraagprijs, maar de verkopen gaan er niet in mee of er wordt te weinig verkocht
    else:
        out["state"] = "normaal"
    out["flags"] = flags
    return out


def buy_gain(price, normal, fee_pct=None):
    """Wat je overhoudt als je nu koopt (met verzending) en verkoopt zodra de prijs terug op normaal staat (min commissie en
    verpakking), als deel van wat je betaalde."""
    fee = config.DEFAULT_FEE_PCT if fee_pct is None else fee_pct
    cost = price + config.ship_cost(price)
    return (normal * (1 - fee / 100) - config.PACKAGING - cost) / cost


# ---------------------------------------------------------------- gegevens laden en opslaan
def _chunks(xs, n=150):
    xs = sorted(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def load_raw(store, ids, since):
    """Cardmarket-rijen per product (één rij per dag; TCGdex gaat voor op andere bronnen)."""
    rank = {"tcgdex": 0, "cardmarket": 1}
    out = {}
    for ch in _chunks(ids):
        for r in store.select("prices", {"select": "product_id,date,source,price,avg1,avg7,avg30,low", "product_id": f"in.({','.join(ch)})",
                                         "grade_key": "eq.raw", "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
            day = out.setdefault(r["product_id"], {})
            cur = day.get(r["date"])
            if cur is None or rank.get(r["source"], 9) < rank.get(cur["source"], 9):
                day[r["date"]] = r
    return {pid: [days[d] for d in sorted(days)] for pid, days in out.items()}


def load_nm(store, ids, since):
    out = {}
    for ch in _chunks(ids):
        for r in store.select("prices", {"select": "product_id,date,price", "product_id": f"in.({','.join(ch)})",
                                         "grade_key": "eq.nm", "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
            out.setdefault(r["product_id"], []).append(r)
    return out


def load_sellers(store):
    """Aantal verschillende verkopers onder de 5 goedkoopste aanbiedingen, per product (alleen waar aanbiedingen zijn opgehaald)."""
    by = {}
    for r in store.select("offers", {"select": "product_id,rank,seller", "rank": "lte.5"}):
        if r.get("seller"):
            by.setdefault(r["product_id"], set()).add(r["seller"])
    return {pid: len(s) for pid, s in by.items()}


def load_listings(store, since):
    by = {}
    for r in store.select("market_snapshots", {"select": "product_id,date,listings", "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
        by.setdefault(r["product_id"], []).append((r["date"], r.get("listings")))
    return by


def candidates(store, log=print):
    """Producten om te beoordelen: alles met een prijs vanaf ADVICE_MIN_TRACK, plus alles in iemands collectie of watchlist."""
    ids = {r["product_id"] for r in store.select("latest_prices", {"select": "product_id,price", "price": f"gte.{config.ADVICE_MIN_TRACK}"})}
    personal = set()
    for table in ("collection", "watch_items"):
        try:
            personal |= {r["product_id"] for r in store.select(table, {"select": "product_id"})}
        except Exception as e:  # zonder die tabel gewoon verder
            log(f"  ({table} niet gelezen: {e})")
    return ids | personal, personal


def run(store, today, log=print):
    """Beoordeelt vandaag alle kandidaten en slaat het advies op. Bewaard worden de opvallende toestanden (hoog, laag, verdacht)
    van alles, en alle toestanden van kaarten die iemand heeft of volgt (die hebben altijd een uitleg nodig)."""
    ids, personal = candidates(store, log=log)
    t = date.fromisoformat(today)
    raw = load_raw(store, ids, (t - timedelta(days=config.ADVICE_NORMAL_DAYS + 10)).isoformat())
    nm = load_nm(store, ids, (t - timedelta(days=config.ADVICE_NORMAL_DAYS + 10)).isoformat())
    try:
        sellers = load_sellers(store)
    except Exception:
        sellers = {}
    try:
        listings = load_listings(store, (t - timedelta(days=21)).isoformat())
    except Exception:
        listings = {}
    rows, counts = [], {s: 0 for s in STATES}
    for pid in sorted(ids):
        a = assess(raw.get(pid, []), nm.get(pid), today, sellers=sellers.get(pid), listings=listings.get(pid))
        counts[a["state"]] += 1
        if a["state"] in ("hoog", "laag", "verdacht") or pid in personal:
            rows.append({"product_id": pid, "date": today, "state": a["state"], "price": a["price"], "normal": a["normal"],
                         "sales7": a["sales7"], "sale_days": a["sale_days"], "flags": a["flags"], "basis": a["basis"]})
    for i in range(0, len(rows), 500):
        store.upsert("advice", rows[i:i + 500], "product_id,date")
    store.delete("advice", {"date": f"lt.{(t - timedelta(days=config.ADVICE_KEEP_DAYS)).isoformat()}"})
    log(f"Advies: {len(ids)} producten beoordeeld: " + ", ".join(f"{s} {n}" for s, n in counts.items()) + f"; {len(rows)} opgeslagen.")
    evaluate(store, today, log=log)
    return counts


def outcome(state, price, later, fee_pct=None):
    """Klopte het advies na 30 dagen? laag: wie kocht, houdt na verzending, commissie en verpakking iets over bij de prijs van
    toen. hoog: de prijs is daarna gezakt (verkopen was dus goed). Geeft (klopte, rendement) of None."""
    if not price or not later:
        return None
    if state == "laag":
        fee = config.DEFAULT_FEE_PCT if fee_pct is None else fee_pct
        cost = price + config.ship_cost(price)
        ret = (later * (1 - fee / 100) - config.PACKAGING - cost) / cost
        return ret > 0, ret
    if state == "hoog":
        ret = later / price - 1
        return ret < 0, ret
    return None


def evaluate(store, today, log=print):
    """Vergelijkt het advies van 30+ dagen geleden met de prijs 30 dagen later en schrijft het resultaat naar advice_stats ('live').
    Per product telt één advies per toestand per 7 dagen, zodat een kaart die wekenlang 'laag' staat niet 30 keer meetelt."""
    t = date.fromisoformat(today)
    h = config.ADVICE_HORIZON_DAYS
    old = store.select("advice", {"select": "product_id,date,state,price", "state": "in.(hoog,laag)",
                                  "date": f"lte.{(t - timedelta(days=h)).isoformat()}", "order": "product_id.asc,date.asc"})
    if not old:
        log("Advies-controle: nog geen advies van 30+ dagen oud; de eerste uitkomsten komen vanzelf.")
        store.upsert("advice_stats", [{"source": "live", "state": s, "n": 0, "hits": 0, "avg_ret": None, "updated": today} for s in ("hoog", "laag")], "source,state")
        return {}
    picked, seen = [], {}
    for r in old:
        key = (r["product_id"], r["state"])
        if key in seen and (_d(r["date"]) - _d(seen[key])).days < 7:
            continue
        seen[key] = r["date"]
        picked.append(r)
    since = min(r["date"] for r in picked)
    raw = load_raw(store, {r["product_id"] for r in picked}, since)
    res = {"hoog": [], "laag": []}
    for r in picked:
        target = (_d(r["date"]) + timedelta(days=h)).isoformat()
        later = next((x for x in raw.get(r["product_id"], []) if target <= x["date"] <= (_d(target) + timedelta(days=7)).isoformat()), None)
        o = outcome(r["state"], _f(r["price"]), _f(later["price"]) if later else None)
        if o:
            res[r["state"]].append(o)
    stats = []
    for s, xs in res.items():
        n, hits = len(xs), sum(1 for ok, _ in xs if ok)
        stats.append({"source": "live", "state": s, "n": n, "hits": hits, "avg_ret": round(sum(x for _, x in xs) / n, 4) if n else None, "updated": today})
        log(f"Advies-controle {s}: {hits} van {n} klopte" + (f", gemiddeld {stats[-1]['avg_ret'] * 100:+.1f}%" if n else "") + ".")
    store.upsert("advice_stats", stats, "source,state")
    return res


def dry_run(store, today, log=print, top=15):
    """Alleen beoordelen en tonen, niets opslaan (om de regels op echte data te bekijken)."""
    ids, personal = candidates(store, log=log)
    t = date.fromisoformat(today)
    since = (t - timedelta(days=config.ADVICE_NORMAL_DAYS + 10)).isoformat()
    raw, nm = load_raw(store, ids, since), load_nm(store, ids, since)
    try:
        sellers = load_sellers(store)
    except Exception:
        sellers = {}
    names = {p["product_id"]: f"{p.get('name')} ({p.get('set_name') or ''} {p.get('number') or ''})".strip() for p in store.products()}
    res = {pid: assess(raw.get(pid, []), nm.get(pid), today, sellers=sellers.get(pid)) for pid in ids}
    counts = {s: sum(1 for a in res.values() if a["state"] == s) for s in STATES}
    log(f"Advies (proef, niets opgeslagen): {len(ids)} producten: " + ", ".join(f"{s} {n}" for s, n in counts.items()))
    log(f"  basis 'normaal': nm {sum(1 for a in res.values() if a['basis'] == 'nm')}, avg30 {sum(1 for a in res.values() if a['basis'] == 'avg30')}")
    flags = {}
    for a in res.values():
        for f in a["flags"]:
            flags[f] = flags.get(f, 0) + 1
    log(f"  waarschuwingen: {flags}")
    for s in ("hoog", "laag", "verdacht"):
        xs = sorted(((pid, a) for pid, a in res.items() if a["state"] == s), key=lambda x: -(x[1]["price"] or 0))[:top]
        log(f"  -- {s} (duurste eerst) --")
        for pid, a in xs:
            gain = f", winst bij herstel {buy_gain(a['price'], a['normal']) * 100:+.0f}%" if s == "laag" else ""
            log(f"     {names.get(pid, pid)}: nu {a['price']:.2f}, normaal {a['normal']:.2f} ({a['basis']}), verkopen 7d {a['sales7'] or 0:.2f}, "
                f"verkoopdagen {a['sale_days']}{gain}{', ' + '/'.join(a['flags']) if a['flags'] else ''}")
    own = [(pid, res[pid]) for pid in personal if pid in res]
    log(f"  eigen kaarten/watchlist: " + ", ".join(f"{s} {sum(1 for _, a in own if a['state'] == s)}" for s in STATES))


if __name__ == "__main__":
    import os
    from store import SupabaseStore
    st = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    dry_run(st, date.today().isoformat())
