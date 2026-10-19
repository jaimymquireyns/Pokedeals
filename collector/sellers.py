"""Verkopers met meerdere koopjes, voor het blok 'Sellers' bovenaan Home.

Kijkt naar ALLE bewaarde aanbiedingen (tabel offers, tot 20 per kaart), niet alleen de allergoedkoopste: elke aanbieding die minstens
MIN_BELOW_SOLD onder Cardmarkets echte verkoopgemiddelde van 30 dagen ligt (avg30, niet te sturen met een vraagprijs), telt mee
voor die verkoper. Per verkoper: wat je overhoudt als je alles in één bestelling koopt (verzending één keer, naar de totale waarde)
en elke kaart later verkoopt tegen het verkoopgemiddelde, min commissie en verpakking.

Alleen Engels, Near Mint (offers bevat alleen NM), geen eigen aanbiedingen (user_settings.cm_name), niet ouder dan MAX_AGE_DAYS.
Schrijft reports/sellers.json (branch reports); de app leest dat bestand.

    python sellers.py --out ../reports/sellers.json
"""
import argparse
import json
import os
from datetime import date, timedelta

import config

MIN_BELOW_SOLD = 0.10
MAX_AGE_DAYS = 7
MIN_CARDS = 2
MIN_GAIN = 1.0
MAX_SELLERS = 150


def groups(offers, sold, products, own=(), today=None, fee_pct=None):
    """offers: rijen uit offers; sold: {product_id: verkoopgemiddelde}; products: {product_id: {...}}. Geeft verkopers, beste eerst."""
    fee = config.DEFAULT_FEE_PCT if fee_pct is None else fee_pct
    today = today or date.today()
    own = {n.strip().lower() for n in own if n}
    best = {}   # (verkoper, kaart) -> goedkoopste aanbieding van die verkoper voor die kaart
    for o in offers:
        seller = (o.get("seller") or "").strip()
        pid, price = o.get("product_id"), o.get("price")
        if not seller or seller.lower() in own or price is None or (o.get("language") or "EN") != "EN":
            continue
        if o.get("date") and (today - date.fromisoformat(str(o["date"])[:10])).days > MAX_AGE_DAYS:
            continue
        s, price = sold.get(pid), float(price)
        if not s or price > s * (1 - MIN_BELOW_SOLD):
            continue
        net = s * (1 - fee / 100) - config.PACKAGING - price
        if net <= 0:
            continue
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
            v = r.get("avg30") or r.get("avg7")
            if v and r["product_id"] not in sold:
                sold[r["product_id"]] = float(v)
    products = {}
    for i in range(0, len(ids), 150):
        chunk = ids[i:i + 150]
        for p in store.select("products", {"select": "product_id,name,set_name,number,image,kind", "product_id": "in.(" + ",".join(f'"{x}"' for x in chunk) + ")"}):
            products[p["product_id"]] = p
    own = [r.get("cm_name") for r in store.select("user_settings", {"select": "cm_name", "cm_name": "not.is.null"})]
    return offers, sold, products, own


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/sellers.json")
    args = ap.parse_args()
    from store import SupabaseStore
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today()
    offers, sold, products, own = load(store, today)
    gs = groups(offers, sold, products, own, today)
    doc = {"updated": today.isoformat(), "offers": len(offers), "cards": len({o["product_id"] for o in offers}),
           "cards_with_sales": len(sold), "sellers": gs}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    print(f"Verkopers: {len(gs)} met minstens {MIN_CARDS} koopjes, uit {len(offers)} aanbiedingen van {doc['cards']} kaarten "
          f"({len(sold)} met een verkoopgemiddelde).")
    for g in gs[:10]:
        print(f"  {g['seller']}: {g['n']} koopjes, EUR {g['total']:.2f} + {g['ship']:.2f} verzending, winst EUR {g['gain']:.2f}")


if __name__ == "__main__":
    main()
