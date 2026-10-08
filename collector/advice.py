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
  - 'Normaal' komt ook uit Cardmarket zelf (zie normal_price); de Near Mint-vraagprijs gaat over iets anders.
  - De goedkoopste Near Mint-aanbiedingen (tabel offers) voor de verkopers en een verdacht goedkope aanbieding.
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
    "onwaarschijnlijk": "de prijs zou meer dan 3 keer zo hoog of laag zijn als normaal: waarschijnlijk klopt de koppeling met Cardmarket niet",
    "trend wijkt af": "Cardmarkets trendprijs ligt ver van wat de kaart nu echt kost (de goedkoopste Near Mint-aanbiedingen); een paar uitschieters trekken hem scheef",
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
    """Normale prijs en waar hij vandaan komt, altijd uit Cardmarket zelf (appels met appels: de trendprijs vergelijken we niet
    met de Near Mint-vraagprijs, die gaat over iets anders en week bij oude kaarten tot tientallen keren af). Eerst de mediaan
    van de trendprijs over 90 dagen zonder de laatste week; zolang we die geschiedenis nog niet hebben het oudste 30-daagse
    verkoopgemiddelde dat we bewaarden (dat gaat over de maand daarvoor). 'nm' wordt niet meer gebruikt."""
    t = _d(today)
    start, end = (t - timedelta(days=config.ADVICE_NORMAL_DAYS)).isoformat(), (t - timedelta(days=config.ADVICE_CONFIRM_DAYS)).isoformat()
    window = [_f(r["price"]) for r in raw if start <= r["date"] < end and _f(r.get("price"))]
    if len(window) >= config.ADVICE_MIN_CM_POINTS:
        return _median(window), "trend"
    old = [r for r in raw if r["date"] < end and _f(r.get("avg30"))]
    if old:
        return _f(old[0]["avg30"]), "avg30"
    return None, None


def assess(raw, nm=None, today=None, sellers=None, listings=None, lowest_offer=None, ask=None):
    """raw: Cardmarket-rijen van één product, op datum gesorteerd ({date, price, avg1, avg7, avg30, low}); nm: Near Mint-rijen
    ({date, price}); sellers: aantal verschillende verkopers onder de goedkoopste aanbiedingen of None; listings: [(datum, aantal)]
    of None; lowest_offer: goedkoopste Near Mint-aanbieding of None; ask: mediaan van de 5 goedkoopste Near Mint-aanbiedingen (recent) of None. Geeft {state, price, normal, ratio, sales7, sale_days, flags, basis}."""
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
    if not (1 / config.ADVICE_MAX_RATIO <= out["ratio"] <= config.ADVICE_MAX_RATIO):
        flags.append("onwaarschijnlijk")
    # Cardmarkets trendprijs tegen wat de kaart nu echt kost (de goedkoopste Near Mint-aanbiedingen). Een paar dure verkopen kunnen de
    # trend ver omhoog trekken terwijl je hem voor een fractie kunt kopen (Charizard G Lv.65: trend 165, te koop vanaf 36).
    if ask and out["price"] and not (1 / config.ADVICE_ASK_MISMATCH <= out["price"] / ask <= config.ADVICE_ASK_MISMATCH):
        flags.append("trend wijkt af")
    if "onwaarschijnlijk" in flags or "trend wijkt af" in flags:   # hoe het ook staat: met deze prijzen klopt er iets niet
        out["state"], out["flags"] = "verdacht", flags
        return out
    # (Cardmarkets 'low' gaat over alle talen en condities en ligt dus vaak laag; alleen de goedkoopste Near Mint-aanbieding telt)
    cheap_listing = bool(lowest_offer and s7 and lowest_offer < 0.5 * s7)

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
    """Near Mint-geschiedenis van PkmnPrices (grade_key 'nm'): vraagprijzen, geen verkopen, maar wel tot maanden terug."""
    out = {}
    for ch in _chunks(ids):
        for r in store.select("prices", {"select": "product_id,date,price", "product_id": f"in.({','.join(ch)})",
                                         "grade_key": "eq.nm", "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
            out.setdefault(r["product_id"], []).append(r)
    return out


def load_offers(store, today=None):
    """Per product: (aantal verschillende verkopers onder de 5 goedkoopste aanbiedingen, goedkoopste prijs, mediaan van die 5).
    Alleen waar aanbiedingen zijn opgehaald; de mediaan alleen als ze hooguit ADVICE_ASK_MAX_AGE dagen oud zijn."""
    by, low, prices, fresh = {}, {}, {}, {}
    since = (_d(today or date.today().isoformat()) - timedelta(days=config.ADVICE_ASK_MAX_AGE)).isoformat()
    for r in store.select("offers", {"select": "product_id,rank,seller,price,date", "rank": "lte.5"}):
        pid = r["product_id"]
        if r.get("seller"):
            by.setdefault(pid, set()).add(r["seller"])
        p = _f(r.get("price"))
        if p:
            if pid not in low or p < low[pid]:
                low[pid] = p
            prices.setdefault(pid, []).append(p)
            fresh[pid] = fresh.get(pid, True) and str(r.get("date") or "") >= since
    asks = {pid: _median(ps) for pid, ps in prices.items() if fresh.get(pid) and len(ps) >= 3}
    return {pid: len(s) for pid, s in by.items()}, low, asks


def load_listings(store, since):
    by = {}
    for r in store.select("market_snapshots", {"select": "product_id,date,listings", "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
        by.setdefault(r["product_id"], []).append((r["date"], r.get("listings")))
    return by


def candidates(store, log=print, today=None):
    """Producten om te beoordelen: alles met een prijs vanaf ADVICE_MIN_TRACK, plus alles in iemands collectie of watchlist."""
    # (niet via de weergave latest_prices: die is over de hele prijzentabel te traag en liep tegen de tijdslimiet van de database aan)
    since = (date.fromisoformat(today or date.today().isoformat()) - timedelta(days=3)).isoformat()
    ids = {r["product_id"] for r in store.select("prices", {"select": "product_id", "grade_key": "eq.raw", "date": f"gte.{since}",
                                                             "price": f"gte.{config.ADVICE_MIN_TRACK}", "order": "product_id.asc,date.asc"})}
    personal = set()
    for table in ("collection", "watch_items"):
        try:
            personal |= {r["product_id"] for r in store.select(table, {"select": "product_id"})}
        except Exception as e:  # zonder die tabel gewoon verder
            log(f"  ({table} niet gelezen: {e})")
    return ids | personal, personal


# ---------------------------------------------------------------- heeft een daling (of stijging) een reden?
CONTEXT_TEXT = {
    "herdruk": "er kwam onlangs een nieuwe versie van deze kaart uit",
    "nieuwe set": "de set is nog nieuw: prijzen zakken de eerste maanden vaak verder",
    "set daalt": "de hele set daalt",
    "pokemon daalt": "alle kaarten van deze Pokémon dalen",
    "markt daalt": "de hele markt daalt",
    "na een piek": "de langere geschiedenis (Near Mint, PkmnPrices) laat zien dat de prijs eerder een piek had en nu terugzakt",
    "set stijgt": "de hele set stijgt (hype)",
    "pokemon stijgt": "alle kaarten van deze Pokémon stijgen (hype)",
}


def _norm_name(n):
    return " ".join(str(n or "").lower().split())


def after_peak(nm_rows, today):
    """Vergelijkt de Near Mint-reeks van PkmnPrices met zichzelf (appels met appels): de mediaan van de laatste 45 dagen tegen
    die van de 3 maanden daarvoor, zonder pieken. Geeft de verhouding, of None bij te weinig punten. Ligt die verhouding hoog,
    dan was de prijs waar we nu 'normaal' mee vergelijken zelf al een piek, en is een daling eerder een terugkeer dan een koopje."""
    import analysis
    t = _d(today)
    mid, start = (t - timedelta(days=45)).isoformat(), (t - timedelta(days=135)).isoformat()
    pts = [{"date": r["date"], "price": _f(r.get("price"))} for r in nm_rows or [] if start <= r["date"] and _f(r.get("price"))]
    if len(pts) < 20:
        return None
    kept, _ = analysis.clean_nm_rows(pts)
    recent = [r["price"] for r in kept if r["date"] >= mid]
    longer = [r["price"] for r in kept if r["date"] < mid]
    if len(recent) < 6 or len(longer) < 10:
        return None
    return _median(recent) / _median(longer)


def context_flags(results, products, sets, today, nm=None):
    """Achtergrondcontrole: heeft een grote beweging een aanwijsbare reden? Kijkt naar herdrukken (zelfde naam in een set van
    de laatste ADVICE_REPRINT_DAYS dagen), een nog jonge set, en of de hele set, alle kaarten van die Pokémon of de hele markt
    meebewegen. results: {product_id: assess-uitkomst}; products: {product_id: product}; sets: {set_id: set}.
    Geeft {product_id: [(vlag, toelichting)]} voor producten die laag of hoog staan."""
    t = _d(today)
    rel = {sid: (st.get("release_date") or "") for sid, st in sets.items()}
    setname = {sid: st.get("name") or sid for sid, st in sets.items()}
    ratios = {pid: a["ratio"] for pid, a in results.items() if a.get("ratio")}
    def med_by(key):
        groups = {}
        for pid, r in ratios.items():
            k = key(products.get(pid) or {})
            if k:
                groups.setdefault(k, []).append(r)
        return {k: (_median(v), len(v)) for k, v in groups.items()}
    by_set = med_by(lambda p: p.get("set_id"))
    by_dex = med_by(lambda p: p.get("dex_id"))
    market = _median(list(ratios.values()))
    newest = {}   # naam -> (releasedatum, set) van de nieuwste druk
    for pid, p in products.items():
        if p.get("kind") != "card":
            continue
        d = rel.get(p.get("set_id"), "")
        k = _norm_name(p.get("name"))
        if d and k and (k not in newest or d > newest[k][0]):
            newest[k] = (d, p.get("set_id"))
    recent = (t - timedelta(days=config.ADVICE_REPRINT_DAYS)).isoformat()
    young = (t - timedelta(days=config.ADVICE_YOUNG_SET_DAYS)).isoformat()
    out = {}
    for pid, a in results.items():
        if a["state"] not in ("laag", "hoog"):
            continue
        p = products.get(pid) or {}
        flags = []
        mine = rel.get(p.get("set_id"), "")
        nd = newest.get(_norm_name(p.get("name")))
        if a["state"] == "laag":
            if nd and mine and nd[0] > mine and nd[0] >= recent:
                flags.append(("herdruk", f"in {setname.get(nd[1], nd[1])} ({nd[0]})"))
            if mine and mine >= young:
                flags.append(("nieuwe set", f"uitgekomen op {mine}"))
            sm = by_set.get(p.get("set_id"))
            if sm and sm[1] >= config.ADVICE_GROUP_MIN and sm[0] <= config.ADVICE_GROUP_DROP:
                flags.append(("set daalt", f"{setname.get(p.get('set_id'), '')}: gemiddeld {(sm[0] - 1) * 100:+.0f}% t.o.v. normaal"))
            dm = by_dex.get(p.get("dex_id"))
            if dm and dm[1] >= config.ADVICE_GROUP_MIN and dm[0] <= config.ADVICE_GROUP_DROP:
                flags.append(("pokemon daalt", f"gemiddeld {(dm[0] - 1) * 100:+.0f}% over {dm[1]} kaarten"))
            if market and market <= config.ADVICE_MARKET_DROP:
                flags.append(("markt daalt", f"gemiddeld {(market - 1) * 100:+.0f}%"))
            peak = after_peak((nm or {}).get(pid), today)
            if peak and peak >= config.ADVICE_PEAK:
                flags.append(("na een piek", f"de laatste 6 weken {(peak - 1) * 100:+.0f}% boven de 3 maanden daarvoor"))
        else:
            sm = by_set.get(p.get("set_id"))
            if sm and sm[1] >= config.ADVICE_GROUP_MIN and sm[0] >= config.ADVICE_GROUP_RISE:
                flags.append(("set stijgt", f"{setname.get(p.get('set_id'), '')}: gemiddeld {(sm[0] - 1) * 100:+.0f}%"))
            dm = by_dex.get(p.get("dex_id"))
            if dm and dm[1] >= config.ADVICE_GROUP_MIN and dm[0] >= config.ADVICE_GROUP_RISE:
                flags.append(("pokemon stijgt", f"gemiddeld {(dm[0] - 1) * 100:+.0f}% over {dm[1]} kaarten"))
        if flags:
            out[pid] = flags
    return out


def is_control(pid, today, share=None):
    """Een vaste, willekeurige steekproef van gewone kaarten (controlegroep): zo kunnen we straks zien of het advies beter is dan toeval."""
    import zlib
    share = config.ADVICE_CONTROL_SHARE if share is None else share
    return zlib.crc32(f"{pid}|{today}".encode()) % 1000 < share * 1000


def run(store, today, log=print):
    """Beoordeelt vandaag alle kandidaten en slaat het advies op. Bewaard worden de opvallende toestanden (hoog, laag, verdacht)
    van alles, en alle toestanden van kaarten die iemand heeft of volgt (die hebben altijd een uitleg nodig)."""
    ids, personal = candidates(store, log=log, today=today)
    t = date.fromisoformat(today)
    raw = load_raw(store, ids, (t - timedelta(days=config.ADVICE_NORMAL_DAYS + 10)).isoformat())
    try:
        sellers, lows, asks = load_offers(store, today)
    except Exception:
        sellers, lows, asks = {}, {}, {}
    try:
        listings = load_listings(store, (t - timedelta(days=21)).isoformat())
    except Exception:
        listings = {}
    rows, counts = [], {s: 0 for s in STATES}
    results = {pid: assess(raw.get(pid, []), None, today, sellers=sellers.get(pid), listings=listings.get(pid), lowest_offer=lows.get(pid), ask=asks.get(pid))
               for pid in sorted(ids)}
    try:
        products = {p["product_id"]: p for p in store.select("products", {"select": "product_id,kind,name,set_id,dex_id", "order": "product_id.asc"})}
        laag_ids = [pid for pid, a in results.items() if a["state"] == "laag"]
        nm = load_nm(store, laag_ids, (t - timedelta(days=140)).isoformat())
        ctx = context_flags(results, products, store.known_sets(), today, nm=nm)
    except Exception as e:  # zonder context gaat het advies gewoon door
        log(f"  (achtergrondcontrole overgeslagen: {e})")
        ctx = {}
    n_ctrl = 0
    for pid, a in results.items():
        counts[a["state"]] += 1
        control = a["state"] == "normaal" and pid not in personal and a.get("price") and is_control(pid, today)
        n_ctrl += bool(control)
        if a["state"] in ("hoog", "laag", "verdacht") or pid in personal or control:
            rows.append({"product_id": pid, "date": today, "state": a["state"], "price": a["price"], "normal": a["normal"],
                         "sales7": a["sales7"], "sale_days": a["sale_days"], "flags": a["flags"], "basis": a["basis"],
                         "context": [f"{k}: {v}" for k, v in ctx.get(pid, [])], "control": bool(control)})
    with_reason = sum(1 for pid, f in ctx.items() if results[pid]["state"] == "laag")
    log(f"Achtergrondcontrole: {with_reason} van {counts['laag']} dalers hebben een aanwijsbare reden "
        f"({', '.join(f'{k} {n}' for k, n in sorted(_count_flags(ctx).items()))}); controlegroep {n_ctrl} gewone kaarten.")
    try:
        for i in range(0, len(rows), 500):
            store.upsert("advice", rows[i:i + 500], "product_id,date")
    except RuntimeError as e:   # supabase/schema.sql nog niet opnieuw gedraaid: kolommen context/control ontbreken nog
        if "context" not in str(e) and "control" not in str(e):
            raise
        log("! Advies: kolommen 'context'/'control' ontbreken; draai supabase/schema.sql opnieuw. Nu opgeslagen zonder die twee.")
        rows = [{k: v for k, v in r.items() if k not in ("context", "control")} for r in rows if not r["control"]]
        for i in range(0, len(rows), 500):
            store.upsert("advice", rows[i:i + 500], "product_id,date")
    store.delete("advice", {"date": f"lt.{(t - timedelta(days=config.ADVICE_KEEP_DAYS)).isoformat()}"})
    log(f"Advies: {len(ids)} producten beoordeeld: " + ", ".join(f"{s} {n}" for s, n in counts.items()) + f"; {len(rows)} opgeslagen.")
    evaluate(store, today, log=log)
    return counts


def _count_flags(ctx):
    out = {}
    for flags in ctx.values():
        for k, _ in flags:
            out[k] = out.get(k, 0) + 1
    return out


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


STAT_KEYS = ("laag", "hoog", "laag_reden", "laag_diep", "laag_mild", "controle", "controle_daalt")


def evaluate(store, today, log=print):
    """Vergelijkt het advies van 30+ dagen geleden met de prijs 30 dagen later en schrijft het resultaat naar advice_stats ('live').
    Per product telt één advies per soort per 7 dagen, zodat een kaart die wekenlang 'laag' staat niet 30 keer meetelt.
      laag            koopadvies (vanaf ADVICE_MIN_BUY, genoeg winst bij herstel, géén reden voor de daling): wie kocht, maakte winst
      laag_reden      dalers mét een aanwijsbare reden (herdruk, hele set...): zo zien we of die achtergrondcontrole terecht afraadt
      laag_diep/_mild het koopadvies uitgesplitst naar hoe diep de daling was (onder of boven 35% onder normaal)
      hoog            verkoopadvies: de prijs zakte daarna
      controle        willekeurige gewone kaarten, gekocht zoals bij 'laag': het toeval waar het koopadvies boven moet uitkomen
      controle_daalt  willekeurige gewone kaarten die daarna zakten: het toeval voor het verkoopadvies"""
    t = date.fromisoformat(today)
    h = config.ADVICE_HORIZON_DAYS
    cutoff = (t - timedelta(days=h)).isoformat()
    try:
        old = store.select("advice", {"select": "product_id,date,state,price,normal,context,control", "state": "in.(hoog,laag,normaal)",
                                      "date": f"lte.{cutoff}", "order": "product_id.asc,date.asc"})
    except Exception:   # oudere database zonder de kolommen context/control
        old = store.select("advice", {"select": "product_id,date,state,price,normal", "state": "in.(hoog,laag)",
                                      "date": f"lte.{cutoff}", "order": "product_id.asc,date.asc"})
    groups = []
    for r in old:
        price, normal = _f(r.get("price")), _f(r.get("normal"))
        if r["state"] == "laag" and price:
            if r.get("context"):
                groups.append(("laag_reden", "laag", r))
            elif price >= config.ADVICE_MIN_BUY and normal and buy_gain(price, normal) >= config.ADVICE_BUY_GAIN:
                groups.append(("laag", "laag", r))
                groups.append(("laag_diep" if price / normal <= 0.65 else "laag_mild", "laag", r))
        elif r["state"] == "hoog":
            groups.append(("hoog", "hoog", r))
        elif r["state"] == "normaal" and r.get("control") and price:
            if price >= config.ADVICE_MIN_BUY:
                groups.append(("controle", "laag", r))
            groups.append(("controle_daalt", "hoog", r))
    picked, seen = [], {}
    for key, rule, r in groups:
        k = (r["product_id"], key)
        if k in seen and (_d(r["date"]) - _d(seen[k])).days < 7:
            continue
        seen[k] = r["date"]
        picked.append((key, rule, r))
    res = {k: [] for k in STAT_KEYS}
    if picked:
        raw = load_raw(store, {r["product_id"] for _, _, r in picked}, min(r["date"] for _, _, r in picked))
        for key, rule, r in picked:
            target = (_d(r["date"]) + timedelta(days=h)).isoformat()
            later = next((x for x in raw.get(r["product_id"], []) if target <= x["date"] <= (_d(target) + timedelta(days=7)).isoformat()), None)
            o = outcome(rule, _f(r["price"]), _f(later["price"]) if later else None)
            if o:
                res[key].append(o)
    stats = []
    for key in STAT_KEYS:
        xs = res[key]
        n, hits = len(xs), sum(1 for ok, _ in xs if ok)
        stats.append({"source": "live", "state": key, "n": n, "hits": hits, "avg_ret": round(sum(x for _, x in xs) / n, 4) if n else None, "updated": today})
    store.upsert("advice_stats", stats, "source,state")
    if not picked:
        log("Advies-controle: nog geen advies van 30+ dagen oud; de eerste uitkomsten komen vanzelf.")
    else:
        log("Advies-controle: " + "; ".join(f"{x['state']} {x['hits']}/{x['n']}" + (f" ({x['avg_ret'] * 100:+.1f}%)" if x["n"] else "") for x in stats))
    return res


def dry_run(store, today, log=print, top=15):
    """Alleen beoordelen en tonen, niets opslaan (om de regels op echte data te bekijken)."""
    ids, personal = candidates(store, log=log, today=today)
    t = date.fromisoformat(today)
    since = (t - timedelta(days=config.ADVICE_NORMAL_DAYS + 10)).isoformat()
    raw = load_raw(store, ids, since)
    try:
        sellers, lows, asks = load_offers(store, today)
    except Exception:
        sellers, lows, asks = {}, {}, {}
    names = {p["product_id"]: f"{p.get('name')} ({p.get('set_name') or ''} {p.get('number') or ''})".strip() for p in store.products()}
    res = {pid: assess(raw.get(pid, []), None, today, sellers=sellers.get(pid), lowest_offer=lows.get(pid), ask=asks.get(pid)) for pid in ids}
    try:
        prods = {p["product_id"]: p for p in store.select("products", {"select": "product_id,kind,name,set_id,dex_id", "order": "product_id.asc"})}
        nm = load_nm(store, [pid for pid, a in res.items() if a["state"] == "laag"], (t - timedelta(days=140)).isoformat())
        ctx = context_flags(res, prods, store.known_sets(), today, nm=nm)
        laag = [pid for pid, a in res.items() if a["state"] == "laag"]
        log(f"  achtergrondcontrole: {sum(1 for pid in laag if pid in ctx)} van {len(laag)} dalers hebben een reden: {_count_flags(ctx)}")
        for pid in sorted(laag, key=lambda x: -(res[x]["price"] or 0))[:10]:
            if pid in ctx:
                log(f"     {pid}: " + "; ".join(f"{k} ({v})" for k, v in ctx[pid]))
    except Exception as e:
        log(f"  (achtergrondcontrole mislukt: {e})")
    counts = {s: sum(1 for a in res.values() if a["state"] == s) for s in STATES}
    log(f"Advies (proef, niets opgeslagen): {len(ids)} producten: " + ", ".join(f"{s} {n}" for s, n in counts.items()))
    log(f"  basis 'normaal': trend {sum(1 for a in res.values() if a['basis'] == 'trend')}, avg30 {sum(1 for a in res.values() if a['basis'] == 'avg30')}")
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
    # python advice.py          advies berekenen en opslaan (zoals in de dagelijkse update)
    # python advice.py --proef  alleen berekenen en tonen, niets opslaan
    import os
    import sys
    from store import SupabaseStore
    st = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    if "--proef" in sys.argv:
        dry_run(st, date.today().isoformat())
    else:
        run(st, date.today().isoformat())
