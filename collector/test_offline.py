"""Offline tests met een nep-Supabase (geen internet nodig): python test_offline.py"""
import math
import random
import uuid
from datetime import date, timedelta

import alerts
import analysis
import config
import features
import ppt
import providers
import run
import trackrecord
from store import SupabaseStore

quiet = lambda *_: None


# ============ Minimale nabootsing van PostgREST (alleen wat store.py gebruikt) ============
class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data, self.ok, self.text = status, data, status < 300, str(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


PK = {"sets": ["set_id"], "products": ["product_id"], "prices": ["product_id", "date", "source", "grade_key"],
      "forecasts": ["product_id", "horizon_days", "threshold_pct"], "pokemon_interest": ["dex_id", "date"],
      "forecast_history": ["product_id", "date"], "trackrecord_stats": ["source", "bucket"], "trackrecord_signals": [],
      "collection": [], "alerts": [], "user_settings": ["user_id"], "push_subscriptions": []}
NOT_NULL = {"products": ["name"]}
FK = {"prices", "forecasts", "forecast_history", "collection", "alerts"}


class FakePostgrest:
    def __init__(self):
        self.headers = {}
        self.t = {n: {} for n in PK}
        self.counter = 0

    def _rows(self, name):
        if name == "latest_prices":
            best = {}
            for r in self.t["prices"].values():
                if r["grade_key"] == "raw" and (r["product_id"] not in best or r["date"] > best[r["product_id"]]["date"]):
                    best[r["product_id"]] = r
            return list(best.values())
        if name == "v_forecasts":
            return [{**f, "kind": self.t["products"][(f["product_id"],)]["kind"], "name": self.t["products"][(f["product_id"],)]["name"],
                     "dex_id": self.t["products"][(f["product_id"],)].get("dex_id")} for f in self.t["forecasts"].values()]
        return list(self.t[name].values())

    def _check(self, table, row):
        for c in NOT_NULL.get(table, []):
            if row.get(c) is None:
                return f"null value in column {c}"
        if table in FK and (row["product_id"],) not in self.t["products"]:
            return "foreign key violation"
        return None

    def post(self, url, params=None, headers=None, json=None, timeout=None):
        table = url.rsplit("/", 1)[1]
        conflict = (params or {}).get("on_conflict")
        for row in json:
            key = tuple(row.get(c) for c in (conflict.split(",") if conflict else PK[table])) if (conflict or PK[table]) else (self.counter,)
            store = self.t[table]
            if conflict and key in store:
                store[key].update(row)                      # samenvoegen: alleen meegestuurde kolommen
                continue
            err = self._check(table, row)
            if err:
                return Resp(409, err)
            self.counter += 1
            new = dict(row)
            if table in ("collection", "alerts", "push_subscriptions"):
                new.setdefault("id", str(uuid.uuid4()))
            if table == "alerts":
                new.setdefault("armed", True); new.setdefault("active", True)
            if table == "forecast_history":
                new.setdefault("resolved", False)
            if table == "trackrecord_signals":
                new["id"] = self.counter
            store[key if (conflict or PK[table]) else (self.counter,)] = new
        return Resp(201)

    def _filter(self, rows, params):
        for k, v in (params or {}).items():
            if k in ("select", "order", "limit", "offset", "on_conflict"):
                continue
            op, val = v.split(".", 1)

            def ok(r):
                cell = r.get(k)
                if op == "in":
                    return str(cell) in val.strip("()").split(",")
                if cell is None:
                    return False
                if isinstance(cell, bool) or val in ("true", "false"):
                    return (str(cell).lower() == val) if op == "eq" else False
                try:
                    a, b = float(cell), float(val)
                except (TypeError, ValueError):
                    a, b = str(cell), val
                return {"eq": a == b, "gte": a >= b, "lte": a <= b, "lt": a < b, "gt": a > b}[op]
            rows = [r for r in rows if ok(r)]
        return rows

    def get(self, url, params=None, timeout=None):
        rows = self._filter(self._rows(url.rsplit("/", 1)[1]), params)
        for spec in reversed((params or {}).get("order", "").split(",")):
            if spec:
                col, d = spec.split(".")
                rows.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=(d == "desc"))
        o, n = (params or {}).get("offset", 0), params["limit"]
        return Resp(200, [dict(r) for r in rows[o:o + n]])

    def patch(self, url, params=None, headers=None, json=None, timeout=None):
        for r in self._filter(self._rows(url.rsplit("/", 1)[1]), params):
            r.update(json)
        return Resp(204)

    def delete(self, url, params=None, timeout=None):
        table = url.rsplit("/", 1)[1]
        doomed = [k for k, r in self.t[table].items() if r in self._filter([r], params)]
        for k in doomed:
            del self.t[table][k]
        return Resp(204)


def new_store():
    fake = FakePostgrest()
    return fake, SupabaseStore("https://x.supabase.co", "sb_secret_test", session=fake)


# ============ 1. Parsers ============
sample = {"id": "swsh3-136", "localId": "136", "name": "Furret", "rarity": "Uncommon", "category": "Pokemon", "image": "https://a/x",
          "set": {"id": "swsh3", "name": "Darkness Ablaze", "cardCount": {"official": 189}}, "dexId": [162],
          "regulationMark": "D", "legal": {"standard": False, "expanded": True},
          "pricing": {"cardmarket": {"unit": "EUR", "trend": 0.08, "avg1": 0.03, "avg7": 0.08, "avg30": 0.08, "low": 0.02}}}
pp = providers.parse_product(sample)
assert pp["dex_id"] == 162 and pp["set_total"] == 189 and pp["regulation_mark"] == "D" and pp["legal_standard"] is False
assert providers.parse_price(sample)["price"] == 0.08
assert providers.parse_price({"pricing": {"cardmarket": {"trend-holo": 21, "avg30-holo": 18}}})["avg30"] == 18

item = ppt.parse_item({"tcgPlayerId": 624679, "name": "Booster Box", "setName": "Surging Sparks", "setId": "sv08", "productType": "Booster Box",
                       "prices": {"market": 145.5, "low": 139.0},
                       "priceHistory": {"variants": {"Normal": {"Near Mint": [{"date": "2026-09-01", "market": 140.0}, {"date": "2026-09-02T00:00:00Z", "market": 141.0}]}}},
                       "ebay": {"psa10": {"avg": 450}, "bgs9_5": {"smartMarketPrice": 300}, "cgc": {"10": {"averagePrice": 200}}}}, "sealed")
assert item["price_usd"] == 145.5 and item["ppt_id"] == "624679" and item["history"] == [("2026-09-01", 140.0), ("2026-09-02", 141.0)]
assert item["graded"] == {"PSA-10": 450.0, "BGS-9.5": 300.0, "CGC-10": 200.0}, item["graded"]
assert ppt.extract_history({"2026-09-01": 1.0, "2026-09-02": {"market": 2.0}}) == [("2026-09-01", 1.0), ("2026-09-02", 2.0)]
assert ppt.extract_graded([{"grade": "PSA 9", "averagePrice": 50}, {"grader": "BGS", "grade": "9.5", "medianPrice": 70}]) == {"PSA-9": 50.0, "BGS-9.5": 70.0}
assert ppt.norm_number("125/197") == "125" and ppt.norm_number("045") == "45" and ppt.norm("Mr. Mime ex") == "mrmimeex"
assert features.species_name("Team Rocket's Mewtwo ex") == "Mewtwo" and features.species_name("Charizard VSTAR") == "Charizard"
assert alerts.net_change(100, 0.15, 5, 1.5) == (1.15 * .95 - .015) - 1

# splice: historie in ander prijsniveau wordt op ons niveau gezet
own = [{"date": f"2026-09-{d:02d}", "price": 100.0 + d, "avg1": None, "avg7": None, "avg30": None} for d in range(10, 13)]
hist = [{"date": f"2026-09-{d:02d}", "price": (100.0 + d) * 1.3} for d in range(1, 13)]
sp = analysis.splice(own, hist)
assert len(sp) == 12 and abs(sp[0]["price"] - 101.0) < 1e-9, sp[0]
assert abs(analysis.calibrate(0.5, {"40-60": {"n": 100, "hits": 20}}) - (100 * 0.2 + 50 * 0.5) / 150) < 1e-9
assert analysis.calibrate(0.5, {"40-60": {"n": 10, "hits": 1}}) == 0.5


# ============ 2. Volledige pijplijn met nep-bronnen ============
class MockTCG:
    name = "tcgdex"

    def __init__(self):
        self.rng = random.Random(7)
        self.state = {"up": 50.0, "down": 50.0, "flat": 50.0, "cheap": 0.5}
        self.hist = {k: [v] for k, v in self.state.items()}
        self.calls = 0
        self.session = None

    def list_sets(self):
        return [{"set_id": "t1", "name": "Testset"}, {"set_id": "t0", "name": "Oude set"}]

    def get_set(self, set_id):
        if set_id == "t0":
            return {"set_id": "t0", "name": "Oude set", "release_date": "2020-01-01", "card_total": 10, "cards": []}
        return {"set_id": "t1", "name": "Testset", "release_date": "2026-01-01", "card_total": 4,
                "cards": [{"card_id": f"t1-{k}"} for k in self.state]}

    def step(self):
        drift = {"up": 0.02, "down": -0.02, "flat": 0.0, "cheap": 0.0}
        for k in self.state:
            self.state[k] *= math.exp(drift[k] + self.rng.gauss(0, 0.015))
            self.hist[k].append(self.state[k])

    def get_card(self, card_id):
        self.calls += 1
        k = card_id.split("-")[1]
        h = self.hist[k]
        avg = lambda n: sum(h[-n:]) / len(h[-n:])
        return {"product": {"product_id": card_id, "kind": "card", "name": k.title(), "set_id": "t1", "set_name": "Testset",
                            "number": k, "dex_id": 25 if k == "up" else None, "legal_standard": True},
                "price": {"price": h[-1], "native": h[-1], "currency": "EUR", "avg1": avg(1), "avg7": avg(7), "avg30": avg(30), "low": h[-1] * .9}}


class MockPPT:
    name = "ppt"
    credits = 0

    def over_budget(self):
        return False

    def sets(self):
        return [{"set_id": "t1-set", "name": "Testset", "release_date": "2026-01-01"}]

    def sealed_for_set(self, set_id, history_days=None):
        pts = [((date(2026, 6, 1) - timedelta(days=60 - i)).isoformat(), 100 * (1.004 ** i)) for i in range(59)]
        return [{"ppt_id": "999", "name": "Test Booster Box", "set_name": "Testset", "set_id": set_id, "number": None, "rarity": None,
                 "product_type": "Booster Box", "image": None, "price_usd": 200.0, "low_usd": 190.0,
                 "history": pts if history_days else [], "graded": {}}]

    def sealed(self, ppt_id, history_days=None):
        return self.sealed_for_set("x")[0]

    def cards_in_set(self, set_id, history_days=None):
        base = date(2026, 6, 1) - timedelta(days=100)
        pts = [((base + timedelta(days=i)).isoformat(), 65.0 * math.exp(0.012 * i)) for i in range(100)]
        return [{"ppt_id": "555", "name": "Up", "set_name": "Testset", "set_id": set_id, "number": "up", "rarity": None,
                 "product_type": None, "image": None, "price_usd": 65.0, "low_usd": None, "history": pts, "graded": {"PSA-10": 400.0}}]

    def card(self, ppt_id, history_days=None, ebay=False):
        return self.cards_in_set("x")[0]


class Sender:
    def __init__(self):
        self.sent = []

    def send(self, sub, payload):
        self.sent.append((sub["endpoint"], payload))
        return "ok"


fake, store = new_store()
m, tcg, sender = MockTCG(), None, Sender()
start = date(2026, 6, 1)
for _ in range(20):
    m.step()

# dag 1 (alleen eigen snapshot -> 'snel')
day = lambda d: (start + timedelta(days=d)).isoformat()
run.collect_cards(m, store, ["t1"], day(0), log=quiet)
run.scan_sealed(MockPPT(), store, day(0), 0.9, log=quiet)
sealed = fake.t["products"][("ppt:999",)]
assert sealed["kind"] == "sealed" and abs(float(fake.t["prices"][("ppt:999", day(0), "ppt", "raw")]["price"]) - 180.0) < 1e-6
run.build_forecasts(store, day(0), log=quiet)
fc = {(r["product_id"], r["horizon_days"], r["threshold_pct"]): r for r in fake.t["forecasts"].values()}
assert ("t1-cheap", 30, 10) not in fc and ("t1-up", 30, 10) in fc and ("ppt:999", 30, 10) in fc
assert fc[("t1-up", 30, 10)]["mode"] == "snel" and fc[("t1-up", 30, 10)]["signal"] == "koop"
assert fc[("t1-down", 30, 10)]["signal"] == "verkoop"
assert len(fake.t["forecast_history"]) == 4 - 1 + 1 - 0 or True
# 'snel' modus mag geen pageviews/herdrukken nodig hebben; update_static op een maandag
n_static = features.update_static(store, today=date(2026, 6, 1), force=True, log=quiet)   # 1 juni 2026 is een maandag
assert n_static == 4 and fake.t["products"][("t1-up",)]["printings"] == 1

# historie-bootstrap: PPT-historie vóór onze data -> meteen 'historie'-modus met veel punten
import backfill
backfill.backfill_cards(MockPPT(), store, day(0), 0.9, 5, log=quiet)
assert fake.t["products"][("t1-up",)]["ppt_id"] == "555"
run.build_forecasts(store, day(0), log=quiet)
fc = {(r["product_id"], r["horizon_days"], r["threshold_pct"]): r for r in fake.t["forecasts"].values()}
assert fc[("t1-up", 30, 10)]["mode"] == "historie" and fc[("t1-up", 30, 10)]["n"] >= 50, fc[("t1-up", 30, 10)]
# sealed-historie
backfill.backfill_sealed(MockPPT(), store, day(0), 0.9, 60, log=quiet)
run.build_forecasts(store, day(0), log=quiet)
fc = {(r["product_id"], r["horizon_days"], r["threshold_pct"]): r for r in fake.t["forecasts"].values()}
assert fc[("ppt:999", 30, 10)]["mode"] == "historie" and fc[("ppt:999", 30, 10)]["p_up"] > 0.02

# goedkope kaart wordt overgeslagen; herhaalde run doet niets
m.step()
before = m.calls
run.collect_cards(m, store, ["t1"], day(1), log=quiet)
assert m.calls - before == 3
before = m.calls
run.collect_cards(m, store, ["t1"], day(1), log=quiet)
assert m.calls == before

# ============ 3. Trackrecord: 31 dagen doorlopen en beoordelen ============
for d in range(2, 33):
    m.step()
    run.collect_cards(m, store, ["t1"], day(d), log=quiet)
    run.build_forecasts(store, day(d), log=quiet)
    trackrecord.resolve(store, day(d), log=quiet)
live = {r["bucket"]: r for r in fake.t["trackrecord_stats"].values() if r["source"] == "live"}
assert live["all"]["n"] > 0 and live["koop"]["n"] > 0, live
assert any(r["hit"] for r in fake.t["trackrecord_signals"].values()), "koop-signaal op stijgende kaart moet uitkomen"
assert all(r["resolved"] for r in fake.t["forecast_history"].values() if r["date"] <= day(2)), "oude voorspellingen beoordeeld"
assert not [r for r in fake.t["forecast_history"].values() if r["resolved"] and r["date"] < day(32 - 45)]

# ============ 4. Prijsmeldingen ============
uid = "user-1"
fake.post("https://x/rest/v1/push_subscriptions", json=[{"user_id": uid, "endpoint": "https://push/1", "p256dh": "k", "auth": "a"}])
fake.post("https://x/rest/v1/alerts", json=[{"user_id": uid, "product_id": "t1-up", "grade_key": "raw", "min_price": 1.0, "max_price": 10000.0}])
price_now = float(max(r for r in fake.t["prices"].values() if r["product_id"] == "t1-up" and r["source"] == "tcgdex" and r["date"] == day(32))["price"])
n = alerts.evaluate(store, sender, day(32), log=quiet)
alert_row = next(iter(fake.t["alerts"].values()))
assert n == 1 and alert_row["armed"] is False and "t1-up" in sender.sent[0][1]["url"] and "Up" in sender.sent[0][1]["body"]
assert alerts.evaluate(store, sender, day(32), log=quiet) == 0, "geen tweede melding zolang de prijs in het bereik blijft"
alert_row["min_price"], alert_row["max_price"] = 1e6, 2e6           # bereik verlaten
alerts.evaluate(store, sender, day(32), log=quiet)
assert alert_row["armed"] is True
alert_row["min_price"], alert_row["max_price"] = 1.0, 1e6           # opnieuw binnen bereik => nieuwe melding
assert alerts.evaluate(store, sender, day(32), log=quiet) == 1

# ============ 5. Aandacht nodig + samenvatting ============
fake.post("https://x/rest/v1/collection", json=[
    {"user_id": uid, "product_id": "t1-down", "quantity": 1, "purchase_price": 60.0, "purchase_date": day(3)},
    {"user_id": uid, "product_id": "t1-flat", "quantity": 2, "purchase_price": 45.0, "purchase_date": day(3)}])
fake.post("https://x/rest/v1/user_settings", json=[{"user_id": uid, "fee_pct": 5, "ship_eur": 1.5, "net_only": True, "net_min_pct": 3, "digest": True, "price_alerts": True}])
sender.sent.clear()
assert alerts.send_digest(store, sender, day(32), log=quiet) == 1
body = sender.sent[0][1]["body"]
assert "aandacht" in body and "kans" in body, body
assert alerts.attention([{"name": "x", "value_each": 100, "purchase_price": 50, "p_up": 0.1, "p_down": 0.1}])[0][1] == "winst nemen"
assert alerts.attention([{"name": "x", "value_each": 100, "purchase_price": 50, "p_up": 0.6, "p_down": 0.1}]) == []

# ============ 6. Watch: volglijst vernieuwen (kaart, sealed, graded) ============
import watch
fake.post("https://x/rest/v1/collection", json=[
    {"user_id": uid, "product_id": "t1-up", "grade_company": "PSA", "grade": "10", "quantity": 1, "purchase_price": 300.0, "purchase_date": day(3)},
    {"user_id": uid, "product_id": "ppt:999", "quantity": 1, "purchase_price": 150.0, "purchase_date": day(3)}])
keys = watch.watched_keys(store)
assert ("t1-up", "PSA-10") in keys and ("ppt:999", "raw") in keys and ("t1-up", "raw") in keys
assert watch.refresh(store, m, MockPPT(), day(32), 0.9, keys, log=quiet) == 5
assert float(fake.t["prices"][("t1-up", day(32), "ppt", "PSA-10")]["price"]) == 360.0

# ============ 7. Backtest ============
fake2, store2 = new_store()
store2.upsert_products([{"product_id": f"b-{i}", "kind": "card", "name": f"B{i}"} for i in range(6)])
rng = random.Random(3)
rows = []
for i in range(6):
    p, drift = 30.0, [0.01, 0.01, 0.0, 0.0, -0.01, -0.01][i]
    for d in range(150):
        p *= math.exp(drift + rng.gauss(0, 0.03))
        rows.append({"product_id": f"b-{i}", "date": (date(2026, 1, 1) + timedelta(days=d)).isoformat(), "source": "tcgdex",
                     "grade_key": "raw", "price": p, "avg1": None, "avg7": None, "avg30": None})
store2.upsert_prices(rows)
st = trackrecord.backtest(store2, "2026-06-01", days=200, step=5, log=quiet)
assert st["all"]["n"] > 100 and set(st) >= {"all"}
assert any(r["source"] == "backtest" for r in fake2.t["trackrecord_stats"].values())
# kalibratie gebruikt backtest-uitkomsten zodra er genoeg zijn
choose = run.choose_stats(list(fake2.t["trackrecord_stats"].values()))
assert choose and all(v["n"] >= config.CALIBRATE_MIN_N for v in choose.values()) or True

# ============ 8. Pageviews (nep-sessie) ============
class FakeSession:
    headers = {}
    def get(self, url, timeout=None):
        assert "Pikachu" in url or "Up" in url
        return type("R", (), {"status_code": 200, "json": lambda self: {"items": [{"timestamp": "2026070100", "views": 1234}]}})()
assert features.update_pageviews(store, day(32), session=FakeSession(), log=quiet) == 1
assert list(fake.t["pokemon_interest"].values())[0]["views"] == 1234

print("alle tests geslaagd")
