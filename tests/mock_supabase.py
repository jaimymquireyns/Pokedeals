"""Nep-Supabase voor de browsertest: beantwoordt REST- en auth-verzoeken vanuit Playwright."""
import json
import re
import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote, urlparse

CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*"}
RESERVED = {"select", "order", "limit", "offset", "on_conflict"}
TODAY = date(2026, 9, 21)


def build_db():
    P = lambda pid, kind, name, st, num, tot, img=None: {"product_id": pid, "kind": kind, "name": name, "set_name": st, "number": num,
                                                          "set_total": tot, "rarity": None, "image": img}
    products = [P("sv03-125", "card", "Charizard ex", "Obsidian Flames", "125", 197), P("base1-4", "card", "Charizard", "Base Set", "4", 102),
                P("swsh7-215", "card", "Umbreon VMAX", "Evolving Skies", "215", 203), P("ppt:999", "sealed", "Surging Sparks Booster Box", "Surging Sparks", None, None),
                P("sv08-100", "card", "Pikachu ex", "Surging Sparks", "100", 191)]
    price = {"sv03-125": 45.5, "base1-4": 350.0, "swsh7-215": 610.0, "ppt:999": 145.0, "sv08-100": 40.0}
    fc = {"sv03-125": (.72, .06, .14, "koop"), "base1-4": (.30, .22, .02, "afwachten"), "swsh7-215": (.18, .41, -.06, "verkoop"),
          "ppt:999": (.55, .10, .15, "koop"), "sv08-100": (.64, .05, .18, "koop")}
    forecasts = []
    for pid, (u, d, e, sig) in fc.items():
        forecasts.append({"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": price[pid], "avg7": price[pid] * 1.02, "avg30": price[pid] * .93,
                          "mom30": .075, "p_up": u, "p_down": d, "exp_change": e, "score": u - d, "sigma": .034, "signal": sig, "mode": "historie",
                          "confidence": "hoog", "n": 58, "updated": "2026-09-21", "computed_on": "2026-09-21"})
    prices = []
    for pid, p in price.items():
        for i in range(45):
            prices.append({"product_id": pid, "date": (TODAY - timedelta(days=44 - i)).isoformat(), "source": "tcgdex" if pid != "ppt:999" else "ppt",
                           "grade_key": "raw", "price": round(p * (0.85 + 0.15 * i / 44), 2)})
    prices.append({"product_id": "sv03-125", "date": TODAY.isoformat(), "source": "ppt", "grade_key": "PSA-10", "price": 180.0})
    stats = [{"source": "live", "bucket": b, "n": n, "hits": h, "sum_p": sp} for b, n, h, sp in
             [("all", 200, 48, 60.0), ("koop", 46, 27, 30.0), ("40-60", 60, 21, 30.0), ("60-80", 40, 22, 28.0), ("80-100", 10, 8, 9.0), ("20-40", 50, 9, 15.0)]]
    signals = [{"id": 1, "product_id": "sv03-125", "name": "Charizard ex", "signal_date": "2026-08-01", "p_up": .72, "change": .18, "hit": True, "resolved_on": "2026-08-31"},
               {"id": 2, "product_id": "sv08-100", "name": "Pikachu ex", "signal_date": "2026-08-02", "p_up": .64, "change": -.04, "hit": False, "resolved_on": "2026-09-01"}]
    return {"products": products, "forecasts": forecasts, "prices": prices, "trackrecord_stats": stats, "trackrecord_signals": signals,
            "collection": [], "alerts": [], "user_settings": [], "push_subscriptions": [], "_log": []}


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


class Mock:
    def __init__(self):
        self.db = build_db()
        self.logged_in = False

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
            return [{**p, "price": (self.latest(p["product_id"]) or {}).get("price"), "p_up": fc.get(p["product_id"], {}).get("p_up"), "signal": fc.get(p["product_id"], {}).get("signal")} for p in d["products"]]
        if name == "v_collection":
            out = []
            for c in d["collection"]:
                gk = "raw" if not c.get("grade_company") else f"{c['grade_company']}-{c['grade']}"
                lp = self.latest(c["product_id"], gk)
                old = [p for p in d["prices"] if p["product_id"] == c["product_id"] and p["grade_key"] == gk and p["date"] <= (TODAY - timedelta(days=30)).isoformat()]
                f = fc.get(c["product_id"], {})
                p = prod[c["product_id"]]
                out.append({**{k: c.get(k) for k in ("id", "product_id", "quantity", "condition", "grade_company", "grade", "purchase_price", "purchase_date")},
                            **{k: p[k] for k in ("kind", "name", "set_name", "number", "rarity", "image")},
                            "value_each": lp["price"] if lp else None, "value_date": lp["date"] if lp else None,
                            "value_30d_ago": sorted(old, key=lambda r: r["date"])[-1]["price"] if old else None,
                            **{k: f.get(k) for k in ("p_up", "p_down", "exp_change", "signal", "confidence", "mode", "n", "sigma", "avg7", "avg30", "mom30")}})
            return out
        return d[name]

    def handle(self, route, request):
        url = urlparse(request.url)
        path, qs, method = url.path, parse_qs(url.query, keep_blank_values=True), request.method
        if method == "OPTIONS":
            return route.fulfill(status=204, headers=CORS)
        j = lambda body, status=200: route.fulfill(status=status, headers={**CORS, "content-type": "application/json"}, body=json.dumps(body))
        self.db["_log"].append((method, path, url.query))
        if path == "/auth/v1/otp":
            return j({})
        if path == "/auth/v1/verify":
            body = json.loads(request.post_data)
            if body["token"] != "123456":
                return j({"msg": "bad"}, 403)
            self.logged_in = True
            return j({"access_token": "tok", "refresh_token": "r", "expires_in": 3600, "user": {"id": "u1", "email": body["email"]}})
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
                if name in ("collection", "alerts", "push_subscriptions"):
                    r.setdefault("id", str(uuid.uuid4()))
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
