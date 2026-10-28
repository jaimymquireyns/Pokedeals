"""Verkopers met meerdere koopjes, voor het blok 'Sellers' bovenaan Home.

Kijkt naar ALLE bewaarde aanbiedingen (tabel offers, tot 20 per kaart), niet alleen de allergoedkoopste. Een aanbieding is een
koopje als hij minstens MIN_BELOW_SOLD onder de verkoopprijs ligt. Per verkoper: wat je overhoudt als je alles in één bestelling
koopt (verzending één keer, naar de totale waarde) en elke kaart later verkoopt, min commissie en verpakking.

Verkoopprijs = de laagste van
  (a) Cardmarkets echte verkoopcijfers (prijslijst; gewoon en reverse holo apart, zie guide_price), en
  (b) wat de ANDERE verkopers vragen: de mediaan van de MARKET_N goedkoopste andere Engelse verkopers van dezelfde uitvoering.
      Daaronder moet je zitten om te verkopen; een paar dure aanbiedingen achteraan tellen niet.

Bescherming tegen gestuurde prijzen (19 okt: de lijst zat vol kaarten met een opgeblazen of grillige prijs):
  - minstens MIN_SELLERS verschillende Engelse verkopers in die uitvoering (dunne markt = één verkoper bepaalt de prijs)
  - de verkoopcijfers moeten met elkaar kloppen: avg30, avg7 en trend liggen niet meer dan MAX_SPREAD keer uit elkaar
  - wat verkocht wordt en wat gevraagd wordt moeten kloppen: niet meer dan MAX_SPREAD keer uit elkaar
  - meer dan MAX_BELOW goedkoper: bijna altijd een andere uitvoering of conditie
  - kaarten onder MIN_PRICE tellen niet (de ruis is groter dan de winst)

Alleen Engels, Near Mint (offers bevat alleen NM), geen eigen aanbiedingen (user_settings.cm_name), niet ouder dan MAX_AGE_DAYS.
Schrijft reports/sellers.json (branch reports); de app leest dat bestand.

    python sellers.py --out ../reports/sellers.json
"""
import argparse
import json
import os
from datetime import date, timedelta
from statistics import median

import config

MIN_BELOW_SOLD = 0.10
MAX_AGE_DAYS = 7
MIN_CARDS = 2
MIN_GAIN = 1.0
MAX_SELLERS = 150
MARKET_N = 5        # verkoopprijs volgens de aanbiedingen: mediaan van de 5 goedkoopste andere verkopers
MIN_SELLERS = 6     # minder verschillende Engelse verkopers in die uitvoering: dunne markt, niet te vertrouwen
MAX_SPREAD = 1.6    # verkoopcijfers onderling, en verkocht tegen gevraagd, mogen niet verder uit elkaar liggen
MAX_BELOW = 0.50    # meer dan de helft goedkoper: bijna altijd een andere uitvoering (holo/niet-holo, Skyridge, e-card) of conditie
MIN_PRICE = 3.0


def ladders(offers, own=()):
    """{(kaart, uitvoering): {verkoper: goedkoopste prijs}}, alleen Engels, zonder eigen aanbiedingen."""
    own = {n.strip().lower() for n in own if n}
    by = {}
    for o in offers:
        seller = (o.get("seller") or "").strip().lower()
        if o.get("price") is None or (o.get("language") or "EN") != "EN" or seller in own:
            continue
        d = by.setdefault((o.get("product_id"), o.get("variant")), {})
        key = seller or f"#{len(d)}"
        d[key] = min(d.get(key, float("inf")), float(o["price"]))
    return by


def market_price(ladder, seller):
    """Wat de andere verkopers vragen: mediaan van de MARKET_N goedkoopsten zonder deze verkoper, of None bij een dunne markt."""
    if len(ladder) < MIN_SELLERS:
        return None
    others = sorted(p for s, p in ladder.items() if s != seller)
    return median(others[:MARKET_N]) if others else None


WHY = {}


def _why(k):
    WHY[k] = WHY.get(k, 0) + 1


def groups(offers, sold, products, own=(), today=None, fee_pct=None):
    """offers: rijen uit offers; sold: {product_id: {'normal': prijs, 'reverse': prijs}} (of één getal); products: {product_id: {...}}."""
    fee = config.DEFAULT_FEE_PCT if fee_pct is None else fee_pct
    today = today or date.today()
    lad = ladders(offers, own)
    own = {n.strip().lower() for n in own if n}
    best = {}   # (verkoper, kaart) -> goedkoopste aanbieding van die verkoper voor die kaart
    for o in offers:
        seller = (o.get("seller") or "").strip()
        pid, price = o.get("product_id"), o.get("price")
        if not seller or seller.lower() in own or price is None or (o.get("language") or "EN") != "EN":
            _why("eigen, niet Engels of zonder verkoper"); continue
        if o.get("date") and (today - date.fromisoformat(str(o["date"])[:10])).days > MAX_AGE_DAYS:
            _why("te oud"); continue
        price = float(price)
        if price < MIN_PRICE:
            _why("onder minimumprijs"); continue
        sv = sold.get(pid)
        if isinstance(sv, dict):   # holo en gewoon apart
            sv = sv.get("reverse") if (o.get("variant") or "").lower().startswith("reverse") else sv.get("normal")
        mk = market_price(lad.get((pid, o.get("variant")), {}), seller.lower())
        if not sv:
            _why("geen of onbetrouwbare verkoopprijs"); continue
        if not mk:
            _why("dunne markt (< %d verkopers)" % MIN_SELLERS); continue
        if max(sv, mk) > MAX_SPREAD * min(sv, mk):
            _why("verkocht en gevraagd kloppen niet"); continue
        s = min(sv, mk)
        if price > s * (1 - MIN_BELOW_SOLD):
            _why("niet 10% onder de verkoopprijs"); continue
        if price < s * (1 - MAX_BELOW):
            _why("meer dan de helft goedkoper"); continue
        net = s * (1 - fee / 100) - config.PACKAGING - price
        if net <= 0:
            _why("geen winst na kosten"); continue
        _why("koopje")
        k = (seller.lower(), pid)
        if k not in best or price < best[k]["price"]:
            p = products.get(pid, {})
            best[k] = {"seller": seller, "product_id": pid, "price": round(price, 2), "sold": round(s, 2), "net": round(net, 2),
                       "below": round(1 - price / s, 3), "variant": o.get("variant"), "date": str(o.get("date") or "")[:10],
                       "name": p.get("name"), "set_name": p.get("set_name"), "number": p.get("number"), "image": p.get("image"), "kind": p.get("kind")}
    by = {}
    for (sk, _), c in best.items():
        by.setdefault(sk, []).append(c)
    out = []
    for cards in by.values():
        total = sum(c["price"] for c in cards)
        ship = config.ship_cost(total)
        gain = sum(c["net"] for c in cards) - ship
        if len(cards) >= MIN_CARDS and gain >= MIN_GAIN:
            out.append({"seller": cards[0]["seller"], "n": len(cards), "total": round(total, 2), "ship": ship, "gain": round(gain, 2),
                        "cards": sorted(cards, key=lambda c: -c["net"])})
    out.sort(key=lambda g: (-g["n"], -g["gain"]))
    return out[:MAX_SELLERS]


def consistent(vals):
    """Het laagste verkoopcijfer, maar alleen als de cijfers met elkaar kloppen (anders None: grillig of gestuurd)."""
    vals = [v for v in vals if v and v > 0.05]
    if not vals or max(vals) > MAX_SPREAD * min(vals):
        return None
    return min(vals)


GUIDE_CONFLICT = 2.5   # liggen de gewone en de holo-cijfers verder dan zoveel keer uit elkaar, dan vertrouwen we geen van beide apart


def _vals(entry, suffix):
    out = []
    for k in ("avg30", "avg7"):
        try:
            v = float(entry.get(k + suffix)) if entry.get(k + suffix) is not None else None
        except (TypeError, ValueError):
            v = None
        if v and v > 0.05:
            out.append(v)
    return out


def guide_price(entry, variant):
    """Verkoopprijs uit Cardmarkets prijslijst voor één product en één uitvoering, holo en gewoon apart:
    Reverse Holofoil -> de '-holo'-cijfers, Normal/Holofoil -> de gewone. Het laagste van avg30 en avg7 (echte verkopen; de trend
    is een berekend cijfer dat achterloopt). Gewoon en reverse mogen ver uit elkaar liggen (bij moderne kaarten is reverse vaak
    veel meer waard); een verwisseling zoals bij Skyridge vangt de vergelijking met wat de andere verkopers vragen op.
    Spreken de twee sets elkaar sterk tegen (oude sets als Skyridge: 137 gewoon tegen 40 holo, terwijl de pagina 26,57 toont),
    dan geen prijs: we weten niet welke bij welke uitvoering hoort. Ook geen prijs als de cijfers onderling niet kloppen."""
    if not entry:
        return None
    norm, holo = _vals(entry, ""), _vals(entry, "-holo")
    own = holo if (variant or "").lower().startswith("reverse") else norm
    return consistent(own)


def load(store, today):
    since = (today - timedelta(days=MAX_AGE_DAYS)).isoformat()
    offers = store.select("offers", {"select": "product_id,price,seller,language,variant,date", "date": f"gte.{since}", "order": "product_id.asc,rank.asc"})
    ids = sorted({o["product_id"] for o in offers})
    sold, since_p = {}, (today - timedelta(days=10)).isoformat()
    for i in range(0, len(ids), 150):
        chunk = ids[i:i + 150]
        for r in store.select("prices", {"select": "product_id,date,avg7,avg30", "grade_key": "eq.raw", "source": "in.(tcgdex,cardmarket)",
                                         "date": f"gte.{since_p}", "product_id": "in.(" + ",".join(f'"{x}"' for x in chunk) + ")",
                                         "order": "product_id.asc,date.desc"}):
            if r["product_id"] not in sold:
                v = consistent([float(x) for x in (r.get("avg30"), r.get("avg7")) if x is not None])
                if v:
                    sold[r["product_id"]] = {"normal": v, "reverse": None}
    products = {}
    for i in range(0, len(ids), 150):
        chunk = ids[i:i + 150]
        for p in store.select("products", {"select": "product_id,name,set_name,number,image,kind", "product_id": "in.(" + ",".join(f'"{x}"' for x in chunk) + ")"}):
            products[p["product_id"]] = p
    own = [r.get("cm_name") for r in store.select("user_settings", {"select": "cm_name", "cm_name": "not.is.null"})]
    # Cardmarkets eigen prijslijst: het laagste van alle verkoopcijfers (gewoon en holo) begrenst de verkoopprijs
    try:
        import requests
        import cardmarket
        guide = {}
        for d in cardmarket.records(cardmarket.fetch(requests.Session(), f"priceGuide/price_guide_{config.CARDMARKET_GAME_ID}.json")):
            if d.get("idProduct") is not None:
                guide[int(d["idProduct"])] = d
        cm_ids = {}
        for i in range(0, len(ids), 150):
            chunk = ids[i:i + 150]
            for p in store.select("products", {"select": "product_id,cm_product_id", "product_id": "in.(" + ",".join(f'"{x}"' for x in chunk) + ")",
                                               "cm_product_id": "not.is.null"}):
                cm_ids[p["product_id"]] = int(p["cm_product_id"])
        for pid in ids:   # sealed: het Cardmarket-productnummer zit in de id ('cm:12345')
            if pid.startswith("cm:") and pid[3:].isdigit():
                cm_ids[pid] = int(pid[3:])
        for pid, cid in cm_ids.items():
            if guide.get(cid):
                sold[pid] = {"normal": guide_price(guide[cid], "Normal"), "reverse": guide_price(guide[cid], "Reverse Holofoil"), "avg": sold.get(pid)}
        print(f"Prijslijst Cardmarket: {len(cm_ids)} kaarten gekoppeld; gewoon en reverse holo apart.")
    except Exception as e:   # prijslijst niet bereikbaar: dan alleen het gemiddelde en de aanbiedingen
        print(f"Prijslijst Cardmarket niet gelezen: {type(e).__name__}: {e}")
    return offers, sold, products, own


def seller_report(name, offers, sold, products, own, today, fee_pct=None):
    """Alle bewaarde aanbiedingen van één verkoper, met de voorzichtige verkoopprijs en of het een koopje is (zelfde regels als groups)."""
    fee = config.DEFAULT_FEE_PCT if fee_pct is None else fee_pct
    lad = ladders(offers, own)
    rows = []
    for o in offers:
        if (o.get("seller") or "").strip().lower() != name.lower():
            continue
        pid, price, var = o["product_id"], float(o["price"]), o.get("variant")
        sv = sold.get(pid)
        if isinstance(sv, dict):
            sv = sv.get("reverse") if (var or "").lower().startswith("reverse") else sv.get("normal")
        mk = market_price(lad.get((pid, var), {}), name.lower())
        n_sellers = len(lad.get((pid, var), {}))
        why, s, net = "", None, None
        if (o.get("language") or "EN") != "EN":
            why = f"taal {o.get('language')}"
        elif not sv:
            why = "geen betrouwbare verkoopprijs"
        elif not mk:
            why = f"dunne markt ({n_sellers} verkopers)"
        elif max(sv, mk) > MAX_SPREAD * min(sv, mk):
            why = f"verkocht {sv:.2f} en gevraagd {mk:.2f} kloppen niet"
        else:
            s = min(sv, mk)
            net = s * (1 - fee / 100) - config.PACKAGING - price
            below = 1 - price / s
            why = "KOOPJE" if MIN_BELOW_SOLD <= below <= MAX_BELOW and net > 0 else f"{below:+.0%} t.o.v. verkoopprijs"
        p = products.get(pid, {})
        rows.append({"name": p.get("name"), "set": p.get("set_name"), "number": p.get("number"), "variant": var, "price": price,
                     "resale": round(s, 2) if s else None, "net": round(net, 2) if net is not None else None, "why": why, "date": o.get("date")})
    rows.sort(key=lambda r: (r["why"] != "KOOPJE", -(r["net"] or -99)))
    deals = [r for r in rows if r["why"] == "KOOPJE"]
    total = sum(r["price"] for r in deals)
    L = [f"# Verkoper {name} ({today})", "", f"{len(rows)} aanbiedingen bij de kaarten die we volgen, waarvan {len(deals)} koopje(s)."]
    if deals:
        ship = config.ship_cost(total)
        L.append(f"Alle koopjes samen: EUR {total:.2f} + EUR {ship:.2f} verzending, winst na kosten ongeveer EUR {sum(r['net'] for r in deals) - ship:.2f}.")
    L += ["", "| kaart | uitvoering | vraagprijs | verkoopprijs | winst per stuk | oordeel |", "|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['name']} ({r['set']} {r['number']}) | {r['variant'] or ''} | {r['price']:.2f} | {r['resale'] if r['resale'] else '–'} | "
                 f"{r['net'] if r['net'] is not None else '–'} | {r['why']} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/sellers.json")
    ap.add_argument("--seller", help="alleen een verslag voor deze verkoper (reports/seller_check.md)")
    args = ap.parse_args()
    if args.seller:
        from store import SupabaseStore
        store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
        today = date.today()
        offers, sold, products, own = load(store, today)
        text = seller_report(args.seller, offers, sold, products, own, today)
        os.makedirs("../reports", exist_ok=True)
        open("../reports/seller_check.md", "w").write(text)
        print(text)
        return
    from store import SupabaseStore
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today()
    offers, sold, products, own = load(store, today)
    gs = groups(offers, sold, products, own, today)
    doc = {"updated": today.isoformat(), "offers": len(offers), "cards": len({o["product_id"] for o in offers}),
           "cards_with_sales": len(sold), "why": WHY, "sold_kinds": {
               "guide_normal": sum(1 for v in sold.values() if isinstance(v, dict) and v.get("normal")),
               "guide_none": sum(1 for v in sold.values() if isinstance(v, dict) and not v.get("normal") and not v.get("reverse"))}, "sellers": gs}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    print("Waarom:", WHY)
    print(f"Verkopers: {len(gs)} met minstens {MIN_CARDS} koopjes, uit {len(offers)} aanbiedingen van {doc['cards']} kaarten "
          f"({len(sold)} met een verkoopgemiddelde).")
    for g in gs[:10]:
        print(f"  {g['seller']}: {g['n']} koopjes, EUR {g['total']:.2f} + {g['ship']:.2f} verzending, winst EUR {g['gain']:.2f}")


if __name__ == "__main__":
    main()
