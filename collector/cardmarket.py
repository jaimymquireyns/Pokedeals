"""Cardmarket: de officiële, openbare prijslijst (dagelijks ververst) voor sealed producten, in euro.

Cardmarket publiceert zelf bestanden op downloads.s3.cardmarket.com (geen sleutel nodig):
  productList/products_nonsingles_<game>.json   sealed en overige niet-losse producten (Pokémon = game 6)
  priceGuide/price_guide_<game>.json            prijzen per product: trend, laagste, gemiddelde 1/7/30 dagen
De exacte vorm kon ik niet vooraf zien, dus de parsers zijn ruim opgezet. `python run.py --probe-ppt` toont de echte vorm.
"""
import re
from collections import Counter

import config

BASE = "https://downloads.s3.cardmarket.com/productCatalog"

# Cardmarket-categorieën die sealed zijn (bevestigd in de livetest): Booster, Display, Box Set, Tins, Theme Decks,
# Blisters, Elite Trainer Boxes, Trainer Kits en PCG Set. 'Pokémon Coins' en 'Pokémon Lot' horen er niet bij.
SEALED_CATEGORY_WORDS = ("booster", "display", "box", "tin", "deck", "blister", "trainer", "set", "case", "bundle", "collection", "pack")
# Alleen als een product geen categorienaam heeft, beoordelen we de productnaam:
NAME_SEALED = ("booster", "box", "display", "blister", "tin", "collection", "bundle", "deck", "trainer", "etb", "case", "pack", "starter", "premium")
PRODUCT_WORDS = re.compile(r"\b(booster box|booster pack|booster|display|elite trainer box|etb|mini tin|tin|blister|theme deck|starter deck|"
                           r"trainer kit|box set|collection|bundle|fun pack|premium)\b.*$", re.I)
NAME_NOT_SEALED = re.compile(r"\b(sleeves?|playmats?|binders?|portfolios?|dice|deck box|deckbox|coins?|plush|figures?|stickers?|albums?|toploaders?|keychains?|lanyards?|bags?|backpacks?|mats?)\b", re.I)


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def records(data):
    """Haalt de lijst met records uit het bestand, ongeacht hoe het is ingepakt."""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for k in ("products", "priceGuides", "priceGuide", "rows", "data"):
            if isinstance(data.get(k), list):
                return [d for d in data[k] if isinstance(d, dict)]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def fetch(session, path):
    r = session.get(f"{BASE}/{path}", timeout=300)
    r.raise_for_status()
    return r.json()


def is_sealed(name, category=None):
    n = (name or "").lower()
    if NAME_NOT_SEALED.search(n):
        return False
    if category:
        return any(w in category.lower() for w in SEALED_CATEGORY_WORDS)
    return any(w in n for w in NAME_SEALED)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def guess_set_name(name):
    """'Phantom Forces Booster Box' -> 'Phantom Forces'; 'Great Encounters: Infinite Space Theme Deck' -> 'Great Encounters'."""
    n = re.sub(r"\(.*?\)", "", name or "").strip()
    if ":" in n:
        return n.split(":")[0].strip() or None
    return PRODUCT_WORDS.sub("", n).strip() or None


def resolve_set_names(products, known_sets):
    """{idExpansion: (set_id, set_name)}. Eerst een bekende set (TCGdex) in de productnaam zoeken; anders de meest voorkomende gok."""
    catalog = sorted(((norm(s["name"]), sid, s["name"]) for sid, s in known_sets.items() if s.get("name") and len(norm(s["name"])) >= 5),
                     key=lambda x: -len(x[0]))
    votes = {}
    for p in products:
        exp = p["expansion"]
        if exp is None:
            continue
        n = norm(p["name"])
        hit = next(((sid, name) for key, sid, name in catalog if key in n), None)
        votes.setdefault(exp, Counter())[("set", hit) if hit else ("guess", guess_set_name(p["name"]))] += 1
    out = {}
    for exp, counter in votes.items():
        (kind_val, count), = counter.most_common(1)
        kind, val = kind_val
        if kind == "set":
            out[exp] = val
        elif val and count >= 2:
            out[exp] = (None, val)
    return out


def load_price_guide(session, game=None):
    """{idProduct: {price, low, avg1, avg7, avg30}}. Prijs = trend, anders het 7- of 30-daags gemiddelde. ('avg' en 'low' zijn bij sealed te grillig.)"""
    game = game or config.CARDMARKET_GAME_ID
    out = {}
    for d in records(fetch(session, f"priceGuide/price_guide_{game}.json")):
        pid = d.get("idProduct")
        if pid is None:
            continue
        price = next((v for v in (_num(d.get("trend")), _num(d.get("avg7")), _num(d.get("avg30"))) if v), None)
        if price:
            out[int(pid)] = {"price": price, "low": _num(d.get("low")), "avg1": _num(d.get("avg1")),
                             "avg7": _num(d.get("avg7")), "avg30": _num(d.get("avg30"))}
    return out


def load_sealed(session, game=None):
    game = game or config.CARDMARKET_GAME_ID
    out = []
    for d in records(fetch(session, f"productList/products_nonsingles_{game}.json")):
        pid, name = d.get("idProduct"), d.get("name")
        cat = d.get("categoryName") or d.get("category")
        if pid is None or not name or not is_sealed(name, cat):
            continue
        out.append({"id": int(pid), "name": name, "expansion": d.get("idExpansion"), "category": cat})
    return out


def sealed_rows(products, guide, today, set_names=None):
    """Zet producten + prijslijst om naar (products, prices) voor de database."""
    prods, prices = [], []
    for p in products:
        g = guide.get(p["id"])
        if not g or g["price"] < config.MIN_TRACK_PRICE:
            continue
        pid = f"cm:{p['id']}"
        set_id, set_name = (set_names or {}).get(p["expansion"], (None, None))
        prods.append({"product_id": pid, "kind": "sealed", "name": p["name"], "set_name": set_name,
                      "set_id": set_id or (f"cm:{p['expansion']}" if p["expansion"] is not None else None), "product_type": p["category"]})
        prices.append({"product_id": pid, "date": today, "source": "cardmarket", "grade_key": "raw", "price": g["price"],
                       "avg1": g["avg1"], "avg7": g["avg7"], "avg30": g["avg30"], "low": g["low"],
                       "native": g["price"], "currency": "EUR"})
    return prods, prices


def probe(session, game=None):
    """Toont wat Cardmarket teruggeeft, zodat de parsers gecontroleerd kunnen worden."""
    game = game or config.CARDMARKET_GAME_ID
    print(f"=== Cardmarket (game {game}) ===")
    try:
        raw = fetch(session, f"productList/products_nonsingles_{game}.json")
        print("bestand:", type(raw).__name__, "sleutels:", list(raw)[:6] if isinstance(raw, dict) else "-")
        recs = records(raw)
        print(f"{len(recs)} niet-losse producten; eerste 2 ruw: {str(recs[:2])[:700]}")
        cats = {}
        for d in recs:
            c = d.get("categoryName") or d.get("idCategory")
            cats[c] = cats.get(c, 0) + 1
        print("categorieën:", sorted(cats.items(), key=lambda x: -x[1])[:15])
        sealed = load_sealed(session, game)
        print(f"{len(sealed)} herkend als sealed. Voorbeelden:", [s["name"] for s in sealed[:8]])
        excluded = [d.get("name") for d in recs if not is_sealed(d.get("name"), d.get("categoryName") or d.get("category"))]
        print(f"{len(excluded)} uitgesloten. Voorbeelden:", excluded[:8])
    except Exception as e:
        print("FOUT bij productlijst:", e)
        return
    try:
        raw = fetch(session, f"priceGuide/price_guide_{game}.json")
        recs = records(raw)
        print(f"\nprijslijst: {len(recs)} records; eerste 2 ruw: {str(recs[:2])[:600]}")
        guide = load_price_guide(session, game)
        rows = [(guide[s["id"]]["price"], s["name"], guide[s["id"]]["avg7"], guide[s["id"]]["avg30"]) for s in sealed if s["id"] in guide]
        print(f"{len(rows)} sealed producten met prijs. Duurste 5 (prijs, naam, gem. 7d, gem. 30d):")
        for r in sorted(rows, reverse=True)[:5]:
            print("  ", r)
        print("Goedkoopste boven €2 (controle):", sorted(r for r in rows if r[0] >= 2)[:3])
        n = len(rows)
        print(f"Liquiditeit: {sum(1 for r in rows if r[3])} van {n} sealed hebben een 30-daags gemiddelde, {sum(1 for r in rows if r[2])} een 7-daags gemiddelde")
        recent = [(guide[s['id']]['avg30'], s['name']) for s in sealed if s['id'] in guide and guide[s['id']]['avg30']]
        print("voorbeeld met verkopen:", sorted(recent, reverse=True)[:3])
        names = resolve_set_names(sealed, {})
        print(f"setnamen (alleen gokken, zonder TCGdex): {len(names)} van {len({s['expansion'] for s in sealed})} uitbreidingen; voorbeeld: {list(names.items())[:4]}")
    except Exception as e:
        print("FOUT bij prijslijst:", e)
