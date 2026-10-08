"""Nep-Supabase voor de browsertest: beantwoordt REST- en auth-verzoeken vanuit Playwright."""
import json
import re
import uuid
from datetime import datetime, date, timedelta
from urllib.parse import parse_qs, unquote, urlparse

CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*"}
RESERVED = {"select", "order", "limit", "offset", "on_conflict"}
TODAY = date(2026, 9, 21)


def build_db():
    P = lambda pid, kind, name, st, num, tot, img=None, rarity=None, release_date=None: {
        "product_id": pid, "kind": kind, "name": name, "set_name": st, "number": num,
        "set_total": tot, "rarity": rarity, "image": img, "release_date": release_date}
    products = [P("sv03-125", "card", "Charizard ex", "Obsidian Flames", "125", 197, rarity="Double Rare", release_date="2023-08-11"), P("base1-4", "card", "Charizard", "Base Set", "4", 102),
                P("30th-63", "card", "Charizard", "30th Celebration", "63", 128),
                P("cel25cc-WP24", "card", "_____'s Pikachu", "Celebrations Classic Collection", "WP24", 25),   # naam met underscores, nummer zoals op Cardmarket (CEL WP 24)
                P("30th-c-001", "card", "Charizard", "30th Classic Collection", "001", 30),   # zoals in de echte database: Cardmarket noemt hem "Charizard (30C BS4)", wij nummer 001
                P("30th-c-002", "card", "Blastoise", "30th Classic Collection", "002", 30),
                P("30th-lugia", "card", "Lugia", "30th Celebration", "77", 201),
                P("30th-lugia-sp", "card", "Lugia", "30th Classic Collection", "009", 30),   # de "speciale" Lugia: zelfde naam, andere set, Cardmarket-code NG9
                P("swsh7-215", "card", "Umbreon VMAX", "Evolving Skies", "215", 203), P("cm:999", "sealed", "Surging Sparks Booster Box", "Surging Sparks", None, None),
                P("sv08-100", "card", "Pikachu ex", "Surging Sparks", "100", 191),
                P("dp2-5", "card", "Blissey", "Mysterious Treasures", "5", 124),    # op Cardmarket: "Blissey Lv.44 (MT 5)"
                P("swsh6-5", "card", "Blissey V", "Chilling Reign", "5", 233),
                P("ex1-5", "card", "Blissey", "Ruby & Sapphire", "5", 109),
                P("sv03-007", "card", "Zzyzx Test", "Obsidian Flames", "007", 197),
                P("A1-001", "card", "Bulbasaur", "Genetic Apex", "001", 226)]   # Pokémon TCG Pocket: digitaal, hoort niet in de app    # gevulde nummering, zoals bij Scarlet & Violet
    for p in products:   # set_id afleiden uit het product-id, zoals bij TCGdex (sv03-125 -> sv03)
        p["set_id"] = p["product_id"].split("-")[0] if "-" in p["product_id"] else None
    price = {"sv03-125": 45.5, "base1-4": 350.0, "swsh7-215": 610.0, "cm:999": 145.0, "sv08-100": 40.0, "dp2-5": 4.0, "swsh6-5": 2.0, "ex1-5": 9.0, "sv03-007": 3.0}
    fc = {"sv03-125": (.72, .06, .36, "koop"), "base1-4": (.30, .22, .02, "afwachten"), "swsh7-215": (.18, .41, -.06, "verkoop"),
          "cm:999": (.55, .10, .25, "koop"), "sv08-100": (.64, .05, .40, "koop"),
          "dp2-5": (.30, .20, .02, "afwachten"), "swsh6-5": (.30, .20, .02, "afwachten"), "ex1-5": (.30, .20, .02, "afwachten"), "sv03-007": (.30, .20, .02, "afwachten")}   # exp_change ruim genoeg om ook na de oplopende verzendtabel nog netto winst te geven
    forecasts = []
    for pid, (u, d, e, sig) in fc.items():
        forecasts.append({"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": price[pid], "avg7": price[pid] * 1.02, "avg30": price[pid] * .93,
                          "mom30": .075, "p_up": u, "p_down": d, "exp_change": e, "score": u - d, "sigma": .034, "signal": sig, "mode": "historie",
                          "confidence": "hoog", "n": 58, "updated": "2026-09-21", "computed_on": "2026-09-21"})
    prices = []
    for pid, p in price.items():
        for i in range(45):
            prices.append({"product_id": pid, "date": (TODAY - timedelta(days=44 - i)).isoformat(), "source": "tcgdex" if pid != "cm:999" else "cardmarket",
                           "grade_key": "raw", "price": round(p * (0.85 + 0.15 * i / 44), 2)})
    prices.append({"product_id": "sv03-125", "date": TODAY.isoformat(), "source": "ppt", "grade_key": "PSA-10", "price": 180.0})
    prices.append({"product_id": "sv03-125", "date": TODAY.isoformat(), "source": "pkmnprices", "grade_key": "nm", "price": 38.0})
    stats = [{"source": "live", "horizon_days": 30, "threshold_pct": 10, "bucket": b, "n": n, "hits": h, "sum_p": sp} for b, n, h, sp in
             [("all", 200, 48, 60.0), ("koop", 46, 27, 30.0), ("40-60", 60, 21, 30.0), ("60-80", 40, 22, 28.0), ("80-100", 10, 8, 9.0), ("20-40", 50, 9, 15.0)]]
    signals = [{"id": 1, "product_id": "sv03-125", "name": "Charizard ex", "signal_date": "2026-08-01", "horizon_days": 30, "threshold_pct": 10, "p_up": .72, "change": .18, "hit": True, "resolved_on": "2026-08-31"},
               {"id": 2, "product_id": "sv08-100", "name": "Pikachu ex", "signal_date": "2026-08-02", "horizon_days": 30, "threshold_pct": 10, "p_up": .64, "change": -.04, "hit": False, "resolved_on": "2026-09-01"}]
    def O(pid, rank, price, seller, variant="Normal", qty=1):
        return {"product_id": pid, "rank": rank, "price": price, "seller": seller, "quantity": qty, "language": "EN", "variant": variant, "date": "2026-09-21"}
    offers = [
        O("sv03-125", 1, 38.0, "rudifer"), O("sv03-125", 2, 39.5, "nofox", qty=2),
        # base1-4: duidelijke uitschieter t.o.v. de tweede goedkoopste van dezelfde uitvoering: moet als 'goedkope aanbieding' worden herkend
        O("base1-4", 1, 200.0, "koopje99"), O("base1-4", 2, 350.0, "a"), O("base1-4", 3, 355.0, "b"), O("base1-4", 4, 360.0, "c"),
        # swsh7-215: maar ~5% goedkoper (haalt de 20%-grens niet), maar wel EUR30 goedkoper (haalt de vaste EUR25-grens wel)
        O("swsh7-215", 1, 610.0, "duurkoper"), O("swsh7-215", 2, 640.0, "d"), O("swsh7-215", 3, 650.0, "e"),
        # sv08-100: de goedkoopste is een Reverse Holofoil, maar die is de enige van zijn soort; de Normals liggen dicht bij elkaar. GEEN koopje.
        O("sv08-100", 1, 12.0, "revfan", "Reverse Holofoil"), O("sv08-100", 2, 40.0, "n1"), O("sv08-100", 3, 41.0, "n2"),
        # sv03-007: een Reverse Holofoil die flink goedkoper is dan de volgende Reverse Holofoil: wel een koopje, met label
        O("sv03-007", 1, 5.0, "slimmerik", "Reverse Holofoil"), O("sv03-007", 2, 40.0, "r2", "Reverse Holofoil"), O("sv03-007", 3, 3.0, "gewoon", "Normal"),
        # dragonite-achtig: een belachelijke vraagprijs mag het beeld niet vertekenen
        # swsh6-5: 23% goedkoper (haalt de 20%-grens), maar na verzending (3), commissie en verpakking blijft er geen winst over: GEEN koopje
        O("swsh6-5", 1, 10.0, "krap"), O("swsh6-5", 2, 13.0, "k2"),
        # ex1-5: 12 aanbiedingen van dezelfde uitvoering: de lijst toont er 8 en klapt uit; hoofdprijs = mediaan van de 10 goedkoopste (5..14 -> 9,50)
        *[O("ex1-5", i, 4.0 + i, f"v{i}") for i in range(1, 13)],
        # cm:999 (sealed): 100 tegen 150 -> koopje voor het filter op soort (winst 150 x 0,94 - 0,50 - (100 + 10) = 30,50)
        O("cm:999", 1, 100.0, "sealseller"), O("cm:999", 2, 150.0, "s2"),
        O("dp2-5", 1, 29.09, "x1"), O("dp2-5", 2, 30.3, "x2"), O("dp2-5", 3, 50.0, "x3"), O("dp2-5", 4, 300.0, "x4", "Reverse Holofoil"), O("dp2-5", 5, 9001.0, "x5"),
    ]
    sets = [
        {"set_id": "sv03", "name": "Obsidian Flames"}, {"set_id": "base1", "name": "Base Set"},
        {"set_id": "swsh7", "name": "Evolving Skies"}, {"set_id": "cm-sealed", "name": "Sealed"},
        {"set_id": "sv08", "name": "Surging Sparks"}, {"set_id": "30th", "name": "30th Celebration"}, {"set_id": "30th-c", "name": "30th Classic Collection"},
        {"set_id": "dp2", "name": "Mysterious Treasures"}, {"set_id": "swsh6", "name": "Chilling Reign"}, {"set_id": "ex1", "name": "Ruby & Sapphire"},
    ]
    return {"products": products, "forecasts": forecasts, "prices": prices, "trackrecord_stats": stats, "trackrecord_signals": signals,
            "collection": [], "alerts": [], "user_settings": [], "push_subscriptions": [], "offers": offers, "sets": sets, "sales": [], "sale_items": [],
            "watch_items": [], "watch_folders": [], "watch_folder_items": [], "_log": []}


def _cmp(cell, op, val):
    if op == "in":
        return str(cell) in val.strip("()").split(",")
    if cell is None:
        return False
    if op in ("ilike", "like"):
        return re.fullmatch(re.escape(val).replace(r"\*", ".*"), str(cell), re.I) is not None
    try:
        a, b = float(cell), float(val)
    except (TypeError, ValueError):
        a, b = str(cell).lower(), val.lower()
    return {"eq": a == b, "gte": a >= b, "lte": a <= b, "lt": a < b, "gt": a > b, "neq": a != b}[op]


def apply(rows, qs):
    out = rows
    for k, vs in qs.items():
        if k in RESERVED:
            continue
        v = vs[0]
        if k == "or":
            conds = re.split(r",(?![^()]*\))", v[1:-1])
            parsed = [c.split(".", 2) for c in conds]
            out = [r for r in out if any(_cmp(r.get(col), op, val) for col, op, val in parsed)]
        else:
            op, val = v.split(".", 1)
            out = [r for r in out if _cmp(r.get(k), op, val)]
    for spec in reversed(qs.get("order", [""])[0].split(",")):
        if spec:
            parts = spec.split(".")
            col, desc = parts[0], "desc" in parts
            out = sorted(out, key=lambda r: (r.get(col) is None, r.get(col) if r.get(col) is not None else 0), reverse=desc)
            if desc and "nullslast" in parts:
                out = [r for r in out if r.get(col) is not None] + [r for r in out if r.get(col) is None]
    if "limit" in qs:
        out = out[int(qs.get("offset", ["0"])[0]):][:int(qs["limit"][0])]
    return out


# Pokémon TCG Pocket-sets (digitaal): v_search in de database sluit ze uit
DIGITAL_SET = __import__("re").compile(r"^([AB][0-9]+[a-z]?|P-[A-Z])$")

# kaarten waarvan we de exacte Cardmarket-pagina kennen (de rest valt terug op zoeken)
CM_URLS = {"sv03-125": "https://www.cardmarket.com/en/Pokemon/Products/Singles/Obsidian-Flames/Charizard-ex-OBF125",
           "30th-c-001": "https://www.cardmarket.com/en/Pokemon/Products/Singles/30th-Celebration/Charizard-30C-BS4"}


CM_NAMES = {"30th-c-001": "Charizard (30C BS4)", "30th-c-002": "Blastoise (30C BS2)", "30th-lugia-sp": "Lugia (30C NG9)", "cel25cc-WP24": "_____'s Pikachu (CEL WP 24)", "dp2-5": "Blissey Lv.44 (MT 5)"}


class Mock:
    def __init__(self):
        self.db = build_db()
        self.logged_in = False
        self.accounts = {}

    def latest(self, pid, gk="raw"):
        rows = sorted([p for p in self.db["prices"] if p["product_id"] == pid and p["grade_key"] == gk], key=lambda r: r["date"])
        return rows[-1] if rows else None

    def view(self, name):
        d = self.db
        prod = {p["product_id"]: p for p in d["products"]}
        fc = {f["product_id"]: f for f in d["forecasts"]}
        if name == "v_forecasts":
            return [{**f, **{k: prod[f["product_id"]][k] for k in ("kind", "name", "set_name", "number", "rarity", "image")}} for f in d["forecasts"]]
        if name == "v_search":
            return [{**p, "cm_url": CM_URLS.get(p["product_id"]), "cm_name": CM_NAMES.get(p["product_id"]), "price": (self.latest(p["product_id"]) or {}).get("price"), "p_up": fc.get(p["product_id"], {}).get("p_up"), "signal": fc.get(p["product_id"], {}).get("signal")}
                    for p in d["products"] if not DIGITAL_SET.match(p.get("set_id") or "")]
        if name == "v_watchlist":
            out = []
            for w in d["watch_items"]:
                pr = prod[w["product_id"]]
                out.append({**{k: w.get(k) for k in ("id", "product_id", "created_at")},
                            **{k: pr[k] for k in ("kind", "name", "set_name", "number", "rarity", "image")}, "cm_url": CM_URLS.get(pr["product_id"]),
                            "value_each": (self.latest(w["product_id"]) or {}).get("price"),
                            **{k: fc.get(w["product_id"], {}).get(k) for k in ("p_up", "p_down", "exp_change", "exp_up", "exp_down", "signal", "confidence", "mode", "n")}})
            return out
        if name == "v_collection":
            out = []
            for c in d["collection"]:
                gk = "raw" if not c.get("grade_company") else f"{c['grade_company']}-{c['grade']}"
                lp = self.latest(c["product_id"], gk)
                old = [p for p in d["prices"] if p["product_id"] == c["product_id"] and p["grade_key"] == gk and p["date"] <= (TODAY - timedelta(days=30)).isoformat()]
                f = fc.get(c["product_id"], {})
                p = prod[c["product_id"]]
                out.append({**{k: c.get(k) for k in ("id", "product_id", "quantity", "condition", "grade_company", "grade", "purchase_price", "purchase_date",
                                                  "purchase_shipping", "purchase_costs", "purchase_seller", "purchase_order", "created_at")},
                            **{k: p[k] for k in ("kind", "name", "set_name", "number", "rarity", "image")},
                            "value_each": lp["price"] if lp else None, "value_date": lp["date"] if lp else None,
                            "value_30d_ago": sorted(old, key=lambda r: r["date"])[-1]["price"] if old else None,
                            **{k: f.get(k) for k in ("p_up", "p_down", "exp_change", "signal", "confidence", "mode", "n", "sigma", "avg7", "avg30", "mom30")}})
            return out
        if name == "v_deals":
            by = {}
            for o in d["offers"]:
                by.setdefault((o["product_id"], o.get("variant") or ""), []).append(o)
            out = []
            for (pid, variant), rows in by.items():
                rows = sorted(rows, key=lambda r: (r["price"], r["rank"]))
                if len(rows) < 2:
                    continue
                cheapest, second = rows[0]["price"], rows[1]["price"]
                if cheapest <= second * 0.8 or second - cheapest >= 25:
                    p = prod[pid]
                    out.append({"product_id": pid, "variant": rows[0].get("variant"), "cheapest": cheapest, "market": second, "seller": rows[0]["seller"],
                                "date": rows[0]["date"], "discount": 1 - cheapest / second, **{k: p[k] for k in ("name", "image", "set_name", "number", "kind")}})
            return out
        return d[name]

    def handle(self, route, request):
        url = urlparse(request.url)
        path, qs, method = url.path, parse_qs(url.query, keep_blank_values=True), request.method
        if method == "OPTIONS":
            return route.fulfill(status=204, headers=CORS)
        j = lambda body, status=200: route.fulfill(status=status, headers={**CORS, "content-type": "application/json"}, body=json.dumps(body))
        self.db["_log"].append((method, path, url.query))
        session = lambda email: {"access_token": "tok", "refresh_token": "r", "expires_in": 3600, "user": {"id": "u1", "email": email}}
        if path == "/auth/v1/signup":
            body = json.loads(request.post_data)
            if body["email"] in self.accounts:
                return j({"msg": "User already registered"}, 422)
            self.accounts[body["email"]] = body["password"]
            self.logged_in = True
            return j(session(body["email"]))
        if path == "/auth/v1/token":
            body = json.loads(request.post_data)
            if self.accounts.get(body.get("email")) != body.get("password"):
                return j({"msg": "Invalid login credentials"}, 400)
            self.logged_in = True
            return j(session(body["email"]))
        if path == "/auth/v1/logout":
            return j({}, 204)
        m = re.match(r"^/rest/v1/(\w+)$", path)
        if path.startswith("/rest/v1/rpc/portfolio_series"):
            days = json.loads(request.post_data)["p_days"]
            rows = []
            for i in range(days + 1):
                d = TODAY - timedelta(days=days - i)
                inv = sum(c["purchase_price"] * c["quantity"] for c in self.db["collection"] if c["purchase_date"] <= d.isoformat())
                val = sum((self.latest(c["product_id"]) or {"price": c["purchase_price"]})["price"] * c["quantity"] * (0.9 + 0.1 * i / days) for c in self.db["collection"] if c["purchase_date"] <= d.isoformat())
                rows.append({"day": d.isoformat(), "invested": inv, "value": val})
            return j(rows)
        if not m:
            return j({"error": "no route"}, 404)
        name = m.group(1)
        if method == "GET":
            base = self.view(name) if name.startswith("v_") else self.db[name]
            rows = apply(base, qs)
            return j(rows)
        body = json.loads(request.post_data) if request.post_data else None
        if method == "POST":
            out = []
            conflict = qs.get("on_conflict", [None])[0]
            for r in body:
                r = dict(r)
                if name in ("collection", "alerts", "push_subscriptions", "watch_items", "watch_folders", "sales", "sale_items"):
                    r.setdefault("id", str(uuid.uuid4()))
                    r.setdefault("created_at", (datetime(2026, 10, 7, 12, 0, 0) + timedelta(seconds=len(self.db["_log"]))).isoformat() + "+00:00")
                if conflict:
                    cols = conflict.split(",")
                    hit = next((x for x in self.db[name] if all(x.get(c) == r.get(c) for c in cols)), None)
                    if hit:
                        hit.update(r); out.append(hit); continue
                self.db[name].append(r); out.append(r)
            return j(out, 201)
        if method == "PATCH":
            rows = apply(self.db[name], qs)
            for r in rows:
                r.update(body)
            return j(rows)
        if method == "DELETE":
            doomed = apply(self.db[name], qs)
            self.db[name] = [r for r in self.db[name] if r not in doomed]
            return route.fulfill(status=204, headers=CORS)
        return j({}, 405)
