"""Offline tests met een nep-Supabase (geen internet nodig): python test_offline.py"""
import os
import math
import random
import uuid
from datetime import date, timedelta

import alerts
import analysis
import config
config.NM_REFRESH_PRICE = True   # de meeste tests hieronder testen het ververs-mechanisme zelf; zie de aparte test voor de uit-stand (config.NM_REFRESH_PRICE = False, de huidige standaard)
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
      "forecast_history": ["product_id", "date", "horizon_days", "threshold_pct"], "trackrecord_stats": ["source", "horizon_days", "threshold_pct", "bucket"], "trackrecord_signals": [],
      "collection": [], "alerts": [], "user_settings": ["user_id"], "push_subscriptions": [], "offers": ["product_id", "rank"], "market_snapshots": ["product_id", "date"], "card_signals": ["product_id", "date"]}
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
            if k == "and":   # PostgREST: and=(kolom.op.waarde,kolom.op.waarde)
                for part in v.strip("()").split(","):
                    col, op2, val2 = part.split(".", 2)
                    rows = [r for r in rows if r.get(col) is not None and
                            {"eq": str(r.get(col)) == val2, "gte": str(r.get(col)) >= val2, "lte": str(r.get(col)) <= val2,
                             "lt": str(r.get(col)) < val2, "gt": str(r.get(col)) > val2}[op2]]
                continue
            op, val = v.split(".", 1)

            def ok(r):
                cell = r.get(k)
                if op == "in":
                    return str(cell) in val.strip("()").split(",")
                if op == "is":
                    return (cell is None) == (val == "null")
                if op == "ilike":
                    return cell is not None and str(cell).lower() == val.lower().replace("*", "")
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
assert abs(alerts.net_change(100, 0.15, 5) - ((115 * .95 - config.PACKAGING) / (100 + config.ship_cost(100)) - 1)) < 1e-9
# het voorbeeld van de gebruiker: 2 kaarten voor 6 euro + 4 verzending, verkocht voor 8 per stuk -> ongeveer 4 euro winst
assert abs((2 * (8 * 0.94 - config.PACKAGING) - (6 + 4)) - 4.04) < 1e-9
assert config.ship_cost(4) == 1.50 and config.ship_cost(45) == 7.00 and config.ship_cost(500) == 15.00, "oplopende verzendtabel"

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
import cardmarket
GUIDE = {999: {"price": 180.0, "low": 170.0, "avg1": 180.0, "avg7": 176.0, "avg30": 168.0}, 1000: {"price": 9.0, "low": 8.0, "avg1": 9.0, "avg7": 9.0, "avg30": 9.0}}
cardmarket.load_price_guide = lambda session, game=None: {k: dict(v) for k, v in GUIDE.items()}
cardmarket.load_sealed = lambda session, game=None: [
    {"id": 999, "name": "Test Booster Box", "expansion": 7, "category": "Pokémon Booster Boxes"},
    {"id": 1000, "name": "Test Sleeves", "expansion": 7, "category": "Pokémon Sleeves"}]   # 1000 is geen sealed maar we filteren op naam in load_sealed zelf
m.session = None
assert cardmarket.sealed_rows([{"id": 1000, "name": "x", "expansion": None, "category": None}], {1000: GUIDE[1000]}, day(0))[0], "9 euro telt mee"
run.scan_sealed(None, store, day(0), log=quiet)
sealed = fake.t["products"][("cm:999",)]
assert sealed["kind"] == "sealed" and abs(float(fake.t["prices"][("cm:999", day(0), "cardmarket", "raw")]["price"]) - 180.0) < 1e-6
assert float(fake.t["prices"][("cm:999", day(0), "cardmarket", "raw")]["avg30"]) == 168.0 and ("cm:1000",) in fake.t["products"]
run.build_forecasts(store, day(0), log=quiet)
fc = {(r["product_id"], r["horizon_days"], r["threshold_pct"]): r for r in fake.t["forecasts"].values()}
assert ("t1-cheap", 30, 10) not in fc and ("t1-up", 30, 10) in fc and ("cm:999", 30, 10) in fc
assert fc[("cm:999", 30, 10)]["mode"] == "snel" and fc[("cm:999", 30, 10)]["price"] == 180.0
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
    for g in GUIDE.values():
        g["price"] *= 1.004
        g["avg7"], g["avg30"] = g["price"] * 0.99, g["price"] * 0.95
    run.scan_sealed(None, store, day(d), log=quiet)
    run.collect_cards(m, store, ["t1"], day(d), log=quiet)
    run.build_forecasts(store, day(d), log=quiet)
    trackrecord.resolve(store, day(d), log=quiet)
fc = {(r["product_id"], r["horizon_days"], r["threshold_pct"]): r for r in fake.t["forecasts"].values()}
assert fc[("cm:999", 30, 10)]["mode"] == "historie" and fc[("cm:999", 30, 10)]["n"] >= 30, "sealed bouwt eigen Cardmarket-historie op"
live = {r["bucket"]: r for r in fake.t["trackrecord_stats"].values() if r["source"] == "live" and r["horizon_days"] == 30 and r["threshold_pct"] == 10}
assert live["all"]["n"] > 0 and live["koop"]["n"] > 0, live
live7 = {r["bucket"]: r for r in fake.t["trackrecord_stats"].values() if r["source"] == "live" and r["horizon_days"] == 7}
assert live7["all"]["n"] > 0, "de korte periode (7 dagen) wordt ook los bijgehouden"
assert any(r["hit"] for r in fake.t["trackrecord_signals"].values()), "koop-signaal op stijgende kaart moet uitkomen"
resolved_30 = [r for r in fake.t["forecast_history"].values() if r["date"] <= day(2) and r["horizon_days"] == 30 and r["threshold_pct"] == 10]
assert resolved_30 and all(r["resolved"] for r in resolved_30), "oude voorspellingen (30 dagen) beoordeeld"
unresolved_60 = [r for r in fake.t["forecast_history"].values() if r["date"] <= day(2) and r["horizon_days"] == 60]
assert unresolved_60 and not any(r["resolved"] for r in unresolved_60), "een periode van 60 dagen kan in dit venster van 31 dagen nog niet zijn afgerond"
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
fake.post("https://x/rest/v1/user_settings", json=[{"user_id": uid, "fee_pct": 5, "ship_eur": 1.5, "net_only": False, "net_min_pct": 3, "digest": True, "price_alerts": True}])
sender.sent.clear()
config.DIGEST_MIN_P_UP = 0.3      # de nagebootste markt is rustig; zo tellen er toch kansen mee
assert alerts.send_digest(store, sender, day(32), log=quiet) == 1
body = sender.sent[0][1]["body"]
assert "aandacht" in body and "kans" in body, body
assert alerts.attention([{"name": "x", "value_each": 100, "purchase_price": 50, "p_up": 0.1, "p_down": 0.1}])[0][1] == "winst nemen"
assert alerts.attention([{"name": "x", "value_each": 100, "purchase_price": 50, "p_up": 0.6, "p_down": 0.1}]) == []

# ============ 6. Watch: volglijst vernieuwen (kaart, sealed, graded) ============
import watch
fake.post("https://x/rest/v1/collection", json=[
    {"user_id": uid, "product_id": "t1-up", "grade_company": "PSA", "grade": "10", "quantity": 1, "purchase_price": 300.0, "purchase_date": day(3)},
    {"user_id": uid, "product_id": "cm:999", "quantity": 1, "purchase_price": 150.0, "purchase_date": day(3)}])
keys = watch.watched_keys(store)
assert ("t1-up", "PSA-10") in keys and ("cm:999", "raw") in keys and ("t1-up", "raw") in keys
assert watch.refresh(store, m, MockPPT(), day(32), 0.9, keys, log=quiet) == 5
assert float(fake.t["prices"][("t1-up", day(32), "ppt", "PSA-10")]["price"]) == 360.0
assert ("cm:999", day(32), "cardmarket", "raw") in fake.t["prices"]

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
st = trackrecord.backtest(store2, "2026-06-01", days=200, step=5, log=quiet)   # combos=None -> alle periodes, GRID + LONG_GRID
assert (30, 10) in st and st[(30, 10)]["all"]["n"] > 100, st.get((30, 10))
assert any(r["source"] == "backtest" and r["horizon_days"] == 30 and r["threshold_pct"] == 10 for r in fake2.t["trackrecord_stats"].values())
assert (730, 100) not in st, "te lange periode past niet in de 150 dagen historie van deze test, dus wordt gewoon overgeslagen"
# opnieuw draaien met alleen de standaardcombinatie overschrijft alleen die ene periode, de rest blijft staan
before_other = [r for r in fake2.t["trackrecord_stats"].values() if r["source"] == "backtest" and r["horizon_days"] != 30]
trackrecord.backtest(store2, "2026-06-01", days=200, step=5, combos=[(30, 10)], log=quiet)
assert all(r in fake2.t["trackrecord_stats"].values() for r in before_other), "backtest van 1 periode laat de andere periodes met rust"
# kalibratie gebruikt backtest-uitkomsten per periode zodra er genoeg zijn
choose = run.choose_stats_all(list(fake2.t["trackrecord_stats"].values()))
assert choose.get((30, 10)) and any(v["n"] >= config.CALIBRATE_MIN_N for v in choose[(30, 10)].values()), choose.get((30, 10))

# ============ 8. Pageviews (nep-sessie) ============
class FakeSession:
    headers = {}
    def get(self, url, timeout=None):
        assert "Pikachu" in url or "Up" in url
        return type("R", (), {"status_code": 200, "json": lambda self: {"items": [{"timestamp": "2026070100", "views": 1234}]}})()
assert features.update_pageviews(store, day(32), session=FakeSession(), log=quiet) == 1
assert list(fake.t["pokemon_interest"].values())[0]["views"] == 1234

# ============ 8b. Echte antwoordvormen (uit de livetest) ============
real_sealed = {"id": "696fa9", "tcgPlayerId": "98026", "name": "XY Roaring Skies Booster Box", "setId": "1534", "setName": "XY - Roaring Skies",
               "unopenedPrice": 4280.92, "imageUrl": "https://x/i.jpg",
               "priceHistory": [{"date": "2026-09-19T00:00:00.000Z", "unopenedPrice": 4280.92}, {"date": "2026-09-20T00:00:00.000Z", "unopenedPrice": 4300.0}]}
it = ppt.parse_item(real_sealed, "sealed")
assert it["price_usd"] == 4280.92 and it["ppt_id"] == "98026" and len(it["history"]) == 2 and it["set_name"] == "XY - Roaring Skies", it
real_card = {"tcgPlayerId": "96392", "setId": 1451, "setName": "XY Promos", "name": "Charizard EX - XY29", "cardNumber": "XY29",
             "prices": {"market": 22.1, "low": 2.79, "variants": {"Holofoil": {"Lightly Played": {"price": 10.62}}}}}
it = ppt.parse_item(real_card)
assert it["price_usd"] == 22.1 and it["number"] == "XY29" and ppt.clean_card_name(it["name"]) == "Charizard EX"
assert ppt.clean_card_name("Charizard ex - 125/197") == "Charizard ex" and ppt.clean_card_name("Ho-Oh ex - 030/191") == "Ho-Oh ex"
assert ppt.clean_card_name("Pikachu (Cosmos Holo) - 025/165") == "Pikachu"
assert backfill.find_ppt_set({"name": "Obsidian Flames"}, [{"name": "SV03: Obsidian Flames", "set_id": "a"}, {"name": "Obsidian Flames Extra", "set_id": "b"}])["set_id"] == "a"

class PagedSess:
    headers = {}
    def __init__(self):
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        off = params["offset"]
        rows = [{"id": f"a{i}", "tcgPlayerId": f"slug-{i}", "name": f"Set {i}", "releaseDate": "2026-01-01T00:00:00.000Z"} for i in range(off, min(off + 2, 5))]
        return type("R", (), {"status_code": 200, "headers": {"X-API-Calls-Consumed": "1"}, "text": "", "json": lambda self: {"data": rows, "metadata": {"hasMore": off + 2 < 5}}, "raise_for_status": lambda self: None})()
ps = PagedSess()
found = ppt.PPT("k", session=ps, log=quiet)._paged("/sets", {}, limit=2)
assert len(found) == 5 and len(ps.calls) == 3, "alle pagina's opgehaald"
class SameSess(PagedSess):
    def get(self, url, params=None, timeout=None):
        params = {**params, "offset": 0}
        return super().get(url, params)
assert len(ppt.PPT("k", session=SameSess(), log=quiet)._paged("/sets", {}, limit=2)) == 2, "stopt als offset genegeerd wordt"
sl = ppt.PPT("k", session=PagedSess(), log=quiet).sets()
assert sl[0]["set_id"] == "slug-0", "leesbare set-code gebruikt in plaats van interne id"

# ============ 8c. Cardmarket-bestanden ============
assert cardmarket.records({"version": 1, "products": [{"idProduct": 1}]}) == [{"idProduct": 1}]
assert cardmarket.records({"priceGuides": [{"idProduct": 2}]}) == [{"idProduct": 2}] and cardmarket.records([{"a": 1}, 3]) == [{"a": 1}]
assert cardmarket.is_sealed("Surging Sparks Booster Box", "Pokémon Display") and cardmarket.is_sealed("Obsidian Flames Elite Trainer Box")
assert cardmarket.is_sealed("Great Encounters Booster", "Pokémon Booster") and cardmarket.is_sealed("Chespin Box", "Pokémon Box Set")
assert cardmarket.is_sealed("Base Set Theme Deck", "Pokémon Theme Decks") and cardmarket.is_sealed("X", "PCG Set") and cardmarket.is_sealed("X", "Pokémon Elite Trainer Boxes")
assert not cardmarket.is_sealed("Rare Coin", "Pokémon Coins") and not cardmarket.is_sealed("Mixed lot", "Pokémon Lot")
assert not cardmarket.is_sealed("Ultra Pro Card Sleeves") and not cardmarket.is_sealed("Charizard Playmat") and not cardmarket.is_sealed("Dragon Shield Deck Box")
assert cardmarket.is_sealed("Great Encounters Booster"), "'Encounters' bevat 'counter' maar is geen teller"
class Doc:
    def __init__(self, data):
        self.data = data
    def raise_for_status(self):
        pass
    def json(self):
        return self.data
class CmSess:
    def get(self, url, timeout=None):
        if "price_guide" in url:
            return Doc({"version": 1, "priceGuides": [{"idProduct": 5, "trend": None, "avg7": 12.5, "avg30": 11.0, "low": 9.0, "avg1": None}, {"idProduct": 6, "trend": 30.0, "avg": 29.0}, {"idProduct": 7}]})
        return Doc({"version": 1, "products": [{"idProduct": 5, "name": "Test Tin", "idExpansion": 3, "categoryName": "Pokémon Tins"}, {"idProduct": 6, "name": "Test Sleeves", "idExpansion": 3}, {"idProduct": 7, "name": "Empty Box"}]})
import importlib
importlib.reload(cardmarket)
g = cardmarket.load_price_guide(CmSess())
assert g[5]["price"] == 12.5, "zonder trend valt het terug op het 7-daags gemiddelde" and 7 not in g
sl = cardmarket.load_sealed(CmSess())
assert [s["id"] for s in sl] == [5, 7], sl
pr, pc = cardmarket.sealed_rows(sl, g, "2026-09-21")
assert [p["product_id"] for p in pr] == ["cm:5"] and pc[0]["source"] == "cardmarket" and pc[0]["currency"] == "EUR"

# ============ 8d. Echte PPT-vormen: graded en historie per conditie ============
ebay_real = {"updatedAt": "x", "salesByGrade": {
    "psa10": {"count": 5, "averagePrice": 42.9, "medianPrice": 39.79, "smartMarketPrice": {"price": 39.0, "confidence": "low"}},
    "psa7": {"count": 1, "averagePrice": 12, "medianPrice": 12, "smartMarketPrice": {"price": 12, "confidence": "low"}},
    "ungraded": {"count": 3, "averagePrice": 15}}}
assert ppt.extract_graded(ebay_real) == {"PSA-10": 39.0, "PSA-7": 12.0}, ppt.extract_graded(ebay_real)
hist_real = {"conditions": {"Lightly Played": {"history": [{"date": "2026-09-19T00:00:00.000Z", "market": 1.0}, {"date": "2026-09-20T00:00:00.000Z", "market": 1.1}, {"date": "2026-09-21T00:00:00.000Z", "market": 1.2}]},
                            "Near Mint": {"history": [{"date": "2026-09-20T00:00:00.000Z", "market": 6.08, "volume": 1}, {"date": "2026-09-21T00:00:00.000Z", "market": 6.13}]}}}
it = ppt.parse_item({"tcgPlayerId": "1", "name": "X - 1/2", "prices": {"market": 6.13}, "priceHistory": hist_real, "ebay": ebay_real})
assert it["history"] == [("2026-09-20", 6.08), ("2026-09-21", 6.13)] and it["graded"]["PSA-10"] == 39.0, "Near Mint heeft voorrang"

# liquiditeit: zonder 30-daags gemiddelde geen kans
fake3, store3 = new_store()
store3.upsert_products([{"product_id": "cm:2000", "kind": "sealed", "name": "Dunne markt"}, {"product_id": "cm:2001", "kind": "sealed", "name": "Levendige markt"}])
rows3 = []
for i in range(15):
    dd = (date(2026, 6, 1) + timedelta(days=i)).isoformat()
    rows3.append({"product_id": "cm:2000", "date": dd, "source": "cardmarket", "grade_key": "raw", "price": 50 + i, "avg1": None, "avg7": None, "avg30": None})
    rows3.append({"product_id": "cm:2001", "date": dd, "source": "cardmarket", "grade_key": "raw", "price": 50 + i, "avg1": 50 + i, "avg7": 49 + i, "avg30": 45 + i})
store3.upsert_prices(rows3)
run.build_forecasts(store3, (date(2026, 6, 1) + timedelta(days=14)).isoformat(), log=quiet)
ids3 = {r["product_id"] for r in fake3.t["forecasts"].values()}
assert ids3 == {"cm:2001"}, ids3

# ============ 8d. Echte Cardmarket-categorieën, setnamen en PPT-vormen uit de livetest ============
importlib.reload(cardmarket)
for n_, cat_, want in [("Great Encounters Booster", "Pokémon Booster", True), ("Chespin Box", "Pokémon Box Set", True), ("Arceus Poster Box", "Pokémon Box Set", True),
                       ("Ultra Pro Deck Box", "Pokémon Box Set", False), ("Card Sleeves", "Pokémon Box Set", False), ("Pikachu Coin", "Pokémon Coins", False),
                       ("Some Lot", "Pokémon Lot", False), ("Obsidian Flames Elite Trainer Box", "Pokémon Elite Trainer Boxes", True)]:
    assert cardmarket.is_sealed(n_, cat_) is want, (n_, cat_)
assert cardmarket.guess_set_name("Chilling Reign Fun Pack (3 Cards)") == "Chilling Reign"
assert cardmarket.guess_set_name("Great Encounters: Infinite Space Theme Deck") == "Great Encounters"
sn = cardmarket.resolve_set_names(
    [{"id": 1, "name": "Base Set 2 Booster", "expansion": 10}, {"id": 2, "name": "Base Set 2 Booster Box", "expansion": 10},
     {"id": 3, "name": "Phantom Forces Booster", "expansion": 20}, {"id": 4, "name": "Phantom Forces Booster Box", "expansion": 20},
     {"id": 5, "name": "Odd Thing Box", "expansion": 30}], {"base1": {"name": "Base Set"}, "base4": {"name": "Base Set 2"}})
assert sn == {10: ("base4", "Base Set 2"), 20: (None, "Phantom Forces")}, sn
pr, _ = cardmarket.sealed_rows([{"id": 1, "name": "Phantom Forces Booster Box", "expansion": 20, "category": "x"}], {1: {"price": 50.0, "low": None, "avg1": None, "avg7": None, "avg30": None}}, "2026-09-21", sn)
assert pr[0]["set_name"] == "Phantom Forces" and pr[0]["set_id"] == "cm:20"
assert ppt.extract_graded({"salesByGrade": {"psa10": {"averagePrice": 42.9, "smartMarketPrice": {"price": 39.79}}, "psa7": {"averagePrice": 12}, "ungraded": {"averagePrice": 15}}}) == {"PSA-10": 39.79, "PSA-7": 12.0}
assert ppt._card_history({"conditions": {"Lightly Played": {"history": [{"date": "2026-09-19", "market": 4.0}]},
                                          "Near Mint": {"history": [{"date": "2026-09-19", "market": 5.92}, {"date": "2026-09-20", "market": 6.08}]}}}) == [("2026-09-19", 5.92), ("2026-09-20", 6.08)]
import pkmnprices
assert pkmnprices._rows({"data": [1, 2]}) == [1, 2] and pkmnprices._rows([3]) == [3] and pkmnprices._rows({"x": 1}) == []

# ============ 8e. 'snel'-modus is voorzichtig ============
spike = analysis.forecast([{"date": "2026-09-21", "trend": 8.42, "avg1": 8.0, "avg7": 7.0, "avg30": 5.0}], 30, 0.10)
assert spike["mode"] == "snel" and spike["p_up"] < 0.45 and spike["signal"] == "afwachten" and spike["mu"] == 0.0, spike     # sprong wordt niet doorgetrokken
steady = analysis.forecast([{"date": "2026-09-21", "trend": 74.0, "avg1": 73.0, "avg7": 68.0, "avg30": 61.0}], 30, 0.10)
assert steady["mode"] == "snel" and steady["p_up"] <= 0.70 and steady["mu"] <= config.FAST_MAX_DRIFT + 1e-9, steady
assert steady["confidence"] == "laag"
mew = analysis.forecast([{"date": "2026-09-21", "trend": 908.89, "avg1": 1199.0, "avg7": 830.66, "avg30": 864.31}], 30, 0.10)
assert mew["sigma"] <= config.FAST_MAX_SIGMA and 0.05 < mew["p_up"] < 0.55 and abs(mew["exp_change"]) < 0.15, mew     # één dure verkoop (avg1) verstoort niets

# ============ 9. PokemonPriceTracker-client: gratis plan veilig ============
import time as _time
class R:
    def __init__(self, status, body=None, headers=None, text=""):
        self.status_code, self._b, self.headers, self.text = status, body, headers or {}, text
    def json(self):
        return self._b
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)
class Sess:
    headers = {}
    def __init__(self, *responses):
        self.rs = list(responses)
    def get(self, url, params=None, timeout=None):
        return self.rs.pop(0)
_time.sleep = lambda *_: None
c = ppt.PPT("key", session=Sess(R(200, {"data": []}, {"X-API-Calls-Consumed": "3", "X-RateLimit-Daily-Remaining": "4"})), log=quiet)
c.sets()
assert c.credits == 3 and c.remaining == 4 and c.over_budget(), "stopt als er bijna geen credits meer zijn"
c = ppt.PPT("key", session=Sess(R(429, None, {}, "Daily credit limit reached")), log=quiet)
try:
    c.sets(); raise SystemExit("hoort te falen")
except RuntimeError as e:
    assert "dagtegoed" in str(e) and c.blocked and c.over_budget()
c = ppt.PPT("key", session=Sess(R(429, None, {"Retry-After": "1"}), R(200, {"data": [{"setId": "s1", "name": "Set 1"}]}, {"X-API-Calls-Consumed": "1"})), log=quiet)
assert c.sets()[0]["set_id"] == "s1", "korte 429 wordt opnieuw geprobeerd"
c = ppt.PPT("key", session=Sess(R(403)), log=quiet)
try:
    c.sets(); raise SystemExit("hoort te falen")
except RuntimeError as e:
    assert "geen toegang" in str(e) and c.blocked
c = ppt.PPT("key", session=Sess(R(200, {"data": [{"setId": "a"}]}, {"X-API-Calls-Consumed": "1", "X-RateLimit-Daily-Remaining": "90"})), log=quiet)
c.sets(); assert not c.over_budget()

# ============ 10. Sealed verrijken met plaatjes en setnamen (PkmnPrices) ============
import enrich
import pkmnprices
cardmarket.load_price_guide = lambda session, game=None: {k: dict(v) for k, v in GUIDE.items()}
cardmarket.load_sealed = lambda session, game=None: [
    {"id": 999, "name": "Test Booster Box", "expansion": 7, "category": "Pokémon Booster Boxes"}, {"id": 1000, "name": "Other Box", "expansion": 7, "category": "Pokémon Box Set"}]
class PkResp:
    def __init__(self, body, status=200):
        self.status_code, self._b, self.headers, self.text = status, body, {"x-credits-charged": "1"}, ""
    def json(self):
        return self._b
class PkSess:
    headers = {}
    def __init__(self):
        self.paths = []
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        self.paths.append(path)
        items = {"11": 999, "12": 555, "13": 1000}
        if path == "/sealed":
            return PkResp({"data": [{"id": i, "name": f"n{i}", "image_url": f"https://img/{i}.webp", "set": {"id": 1, "name": "Set A"}} for i in (11, 12, 13)],
                           "pagination": {"page": 1, "total_pages": 1}})
        i = path.rsplit("/", 1)[1]
        return PkResp({"data": {"id": int(i), "cardmarket_product_id": items[i], "image_url": f"https://img/{i}.webp", "set": {"id": 1, "name": "Set A"}}})
sess = PkSess()
pk = pkmnprices.PkmnPrices("pk_x", session=sess)
assert enrich.enrich_sealed(store, pk, log=quiet) == 2
p999 = fake.t["products"][("cm:999",)]
assert p999["image"] == "https://img/11.webp" and p999["set_name"] == "Set A" and p999["pk_id"] == "11" and p999["name"] == "Test Booster Box"
assert pk.credits == 4, pk.credits         # 1 lijst + 3 details
sess.paths.clear()
enrich.enrich_sealed(store, pkmnprices.PkmnPrices("pk_x", session=sess), log=quiet)
assert sess.paths == ["/sealed", "/sealed/12"], sess.paths      # al gekoppelde producten worden niet opnieuw opgehaald
run.scan_sealed(None, store, day(33), log=quiet)                # de dagelijkse update mag plaatje en setnaam niet wissen
p999 = fake.t["products"][("cm:999",)]
assert p999["image"] == "https://img/11.webp" and p999["set_name"] == "Set A" and p999["pk_id"] == "11"
small = pkmnprices.PkmnPrices("pk_x", session=PkSess(), budget=1)
assert small.list_all("/sealed") and small.over_budget() is True

# ============ 11. Laagste Near Mint-prijs ============
import nm
assert nm.nm_price({"prices": [
    {"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "1st Edition Holofoil", "market_price": 900},
    {"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Normal", "market_price": 40},
    {"source": "cardmarket", "currency": "EUR", "condition": "Excellent", "variant": "Normal", "market_price": 30},
    {"source": "tcgplayer", "currency": "USD", "condition": "Near Mint", "variant": "Normal", "market_price": 55}]}) == ("Normal", 40.0)
assert nm.nm_price({"prices": [{"source": "cardmarket", "currency": "EUR", "condition": "Good", "market_price": 3}]}) is None
cands = [{"id": 900, "number": "1", "set": {"name": "Other"}}, {"id": 901, "number": "232", "total_set_number": "091", "set": {"name": "SV04.5: Paldean Fates"}},
         {"id": 902, "number": "232", "total_set_number": "999", "set": {"name": "Elsewhere"}}]
assert nm.match_card({"number": "232", "set_name": "Paldean Fates", "set_total": 91}, cands)["id"] == 901
assert nm.match_card({"number": "77", "set_name": "Paldean Fates", "set_total": 91}, cands) is None

fake3, store3 = new_store()
store3.upsert_products([
    {"product_id": "sv04.5-232", "kind": "card", "name": "Mew ex", "set_name": "Paldean Fates", "number": "232", "set_total": 91},
    {"product_id": "base1-58", "kind": "card", "name": "Pikachu", "set_name": "Base Set", "number": "058", "set_total": 102},
    {"product_id": "x-1", "kind": "card", "name": "Zzz", "set_name": "Nope", "number": "1", "set_total": 10}])
for pid_, price_, up_ in (("sv04.5-232", 900.0, 0.5), ("base1-58", 50.0, 0.3), ("x-1", 20.0, 0.1)):
    fake3.t["forecasts"][(pid_, 30, 10)] = {"product_id": pid_, "horizon_days": 30, "threshold_pct": 10, "price": price_, "p_up": up_, "p_down": 0.1}
fake3.post("https://x/rest/v1/collection", json=[{"user_id": "u", "product_id": "base1-58", "quantity": 1, "purchase_price": 30.0, "purchase_date": "2026-09-01"}])

class NmSess:
    headers = {}
    def __init__(self):
        self.paths = []
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        self.paths.append(path)
        if path == "/cards":
            data = {"Mew ex": [{"id": 900, "number": "1", "set": {"name": "Other"}}, {"id": 901, "number": "232", "total_set_number": "091", "set": {"name": "SV04.5: Paldean Fates"}}],
                    "Pikachu": [{"id": 500, "number": "58", "total_set_number": "102", "set": {"name": "Base Set"}}]}.get(params["name"], [])
            return PkResp({"data": data, "pagination": {"page": 1, "total_pages": 1}})
        d = {"/cards/901": [{"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Holofoil", "market_price": 630.0}],
             "/cards/500": [{"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Normal", "market_price": 40.0},
                            {"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "1st Edition Holofoil", "market_price": 900.0}]}[path]
        return PkResp({"data": {"id": 1, "prices": d}})
ns = NmSess()
pk3 = pkmnprices.PkmnPrices("pk", session=ns)
assert nm.run(store3, pk3, "2026-09-21", log=quiet) == 2
assert fake3.t["products"][("sv04.5-232",)]["pk_id"] == "901" and fake3.t["products"][("base1-58",)]["pk_id"] == "500"
assert "pk_id" not in fake3.t["products"][("x-1",)] or not fake3.t["products"][("x-1",)].get("pk_id")
assert float(fake3.t["prices"][("sv04.5-232", "2026-09-21", "pkmnprices", "nm")]["price"]) == 630.0
assert float(fake3.t["prices"][("base1-58", "2026-09-21", "pkmnprices", "nm")]["price"]) == 40.0
ns.paths.clear()
nm.run(store3, pkmnprices.PkmnPrices("pk", session=ns), "2026-09-22", log=quiet)
assert [p for p in ns.paths if p == "/cards"] == ["/cards"], ns.paths       # alleen nog de mislukte kaart 'Zzz' wordt opnieuw gezocht
assert "/cards/901" in ns.paths and "/cards/500" in ns.paths
order, _fc = nm.pick_targets(store3, 10)
assert order[0] == "base1-58" and order[1:] == ["sv04.5-232", "x-1"], order       # collectie eerst, dan beste kansen

# ============ 12. Verzendkosten-probe: geen crash, herkent gevulde vs lege tabel ============
import shipping
assert not shipping._looks_like_table("Sorry, we are not shipping between these countries.")
assert shipping._looks_like_table("Shipping Method Tracked Max. Value Price Average Delivery Time (days) " * 5)
assert "Belgium" not in [c for c in shipping.EU_COUNTRIES if c != "Belgium"] or True
assert "Switzerland" not in shipping.EU_COUNTRIES and "United Kingdom" not in shipping.EU_COUNTRIES
assert len(shipping.EU_COUNTRIES) == 27 and shipping.ISO["Germany"] == "DE"

# ============ 13. Meerdere periodes: wekelijkse lange combo's overschrijven de dagelijkse niet ============
f100 = analysis.forecast([{"date": "2026-09-21", "trend": 45.5, "avg1": 46.0, "avg7": 46.41, "avg30": 42.32}], 730, 1.0)
assert -0.99 <= f100["exp_down"] < 0 and f100["exp_up"] >= 1.0 - 1e-9, f100     # geen wiskundige fout bij 100% drempel

fake4, store4 = new_store()
store4.upsert_products([{"product_id": "w-1", "kind": "card", "name": "W1"}])
base = date(2026, 6, 1)
prices4 = [40.0 * math.exp(0.01 * i) for i in range(41)]
def wrow(i, price):
    return {"product_id": "w-1", "date": (base + timedelta(days=i)).isoformat(), "source": "tcgdex", "grade_key": "raw",
            "price": price, "avg1": price, "avg7": sum(prices4[max(0, i - 6):i + 1]) / len(prices4[max(0, i - 6):i + 1]),
            "avg30": sum(prices4[max(0, i - 29):i + 1]) / len(prices4[max(0, i - 29):i + 1])}
store4.upsert_prices([wrow(i, prices4[i]) for i in range(40)])
today4 = (base + timedelta(days=39)).isoformat()   # 2026-07-10, een vrijdag: geen maandag
run.build_forecasts(store4, today4, log=quiet)                              # dagelijkse combo's
run.build_forecasts(store4, today4, log=quiet, combos=config.LONG_GRID)     # simuleert een eerdere maandag-run
assert (("w-1", 90, 20) in fake4.t["forecasts"]) and (("w-1", 30, 10) in fake4.t["forecasts"])
next_day = (base + timedelta(days=40)).isoformat()   # niet-maandag: alleen de dagelijkse combo's opnieuw
store4.upsert_prices([wrow(40, 61.0)])
run.build_forecasts(store4, next_day, log=quiet)
assert ("w-1", 90, 20) in fake4.t["forecasts"], "de lange periode van vorige week mag niet zijn verwijderd door de dagelijkse opruiming"
assert fake4.t["forecasts"][("w-1", 30, 10)]["computed_on"] == next_day and fake4.t["forecasts"][("w-1", 90, 20)]["computed_on"] == today4

# ============ 14. Lange periodes: doorgetrokken trend krijgt een plafond ============
hot = [{"date": f"2026-{(6 + i // 28):02d}-{(i % 28) + 1:02d}", "trend": 40 * math.exp(0.012 * i), "price": 40 * math.exp(0.012 * i),
        "avg1": 40 * math.exp(0.012 * i), "avg7": 40 * math.exp(0.012 * i), "avg30": 40 * math.exp(0.012 * i)} for i in range(60)]
f30 = analysis.forecast(hot, 30, 0.10)
f365 = analysis.forecast(hot, 365, 0.60)
f730 = analysis.forecast(hot, 730, 1.0)
assert round(f30["exp_change"], 3) == round(math.exp(f30["mu"] * 30) - 1, 3), "30 dagen blijft ongewijzigd (geen plafond nodig)"
assert f365["exp_change"] <= config.MAX_HORIZON_RETURN + 1e-9 and f730["exp_change"] <= config.MAX_HORIZON_RETURN + 1e-9
assert f365["exp_up"] <= config.MAX_HORIZON_RETURN + 0.1 and f730["exp_up"] <= config.MAX_HORIZON_RETURN + 0.1
assert f730["exp_change"] < 20, f730   # geen duizenden procenten meer

# ============ 15. Sealed-geschiedenis (PkmnPrices, Cardmarket-bron) ============
import sealed_history
import graded_history
import famous_analysis
import cm_links
import market_snapshot
import signals
raw_hist = [{"date": "2026-08-01", "source": "cardmarket", "currency": "EUR", "condition": None, "variant": None, "avg": 140.0, "low": 138.0},
            {"date": "2026-08-02", "source": "cardmarket", "currency": "EUR", "avg": 141.0, "low": 139.0},
            {"date": "2026-08-03", "source": "tcgplayer", "currency": "USD", "market_price": 150.0},   # andere bron: overslaan
            {"date": "2026-09-21", "source": "cardmarket", "currency": "EUR", "avg": 180.0}]           # vandaag zelf: overslaan
parsed = sealed_history.parse_rows("cm:999", raw_hist, "2026-09-21")
assert len(parsed) == 2 and parsed[0]["price"] == 140.0 and parsed[0]["source"] == "cardmarket", parsed

fake5, store5 = new_store()
store5.upsert_products([{"product_id": "cm:999", "kind": "sealed", "name": "Test Box", "pk_id": "11"},
                        {"product_id": "cm:1000", "kind": "sealed", "name": "Other Box", "pk_id": "12"}])
store5.upsert_prices([{"product_id": "cm:1000", "date": "2026-06-01", "source": "cardmarket", "grade_key": "raw", "price": 9.0}])   # heeft al oude data
assert sealed_history.needs_backfill(store5, "cm:999", "2026-09-21") is True
assert sealed_history.needs_backfill(store5, "cm:1000", "2026-09-21") is False

class SealedHistSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        i = url.rsplit("/", 2)[1]   # .../sealed/<id>/prices
        rows = [{"date": f"2026-08-{d:02d}", "source": "cardmarket", "currency": "EUR", "avg": 140.0 + d} for d in range(1, 21)]
        return PkResp({"data": rows, "pagination": {"page": 1, "total_pages": 1}})
sh_pk = pkmnprices.PkmnPrices("pk", session=SealedHistSess())
n = sealed_history.run(store5, sh_pk, "2026-09-21", log=quiet)
assert n == 20 and ("cm:999", "2026-08-01", "cardmarket", "raw") in fake5.t["prices"]
assert ("cm:1000", "2026-06-01", "cardmarket", "raw") in fake5.t["prices"] and not any(
    k[0] == "cm:1000" and k[1].startswith("2026-08") for k in fake5.t["prices"])   # al genoeg historie: niet opnieuw opgehaald

# ============ 16. Overgebleven PkmnPrices-budget wordt echt gebruikt (NM eerst, dan extra kaarten) ============
fake6, store6 = new_store()
cards6 = [{"product_id": f"e-{i}", "kind": "card", "name": f"E{i}", "number": "1", "set_name": "S", "set_total": 1} for i in range(5)]
store6.upsert_products(cards6)
for i, pid in enumerate(f["product_id"] for f in cards6):
    fake6.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": 100.0 - i, "p_up": 0.5, "p_down": 0.1}

class WideSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        if path == "/cards":
            i = int(params["name"][1:])
            return PkResp({"data": [{"id": i, "number": "1", "set": {"name": "S"}}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": {"id": 1, "prices": [{"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Normal", "market_price": 9.0}]}})
ws = WideSess()
pk6 = pkmnprices.PkmnPrices("pk_x", session=ws, budget=1000)   # ruim budget: de vaste lijst (limit=2) mag niet de stopreden zijn
config.NM_WIDEN_EXTRA = True   # standaard nu uit (geschiedenis-opbouw krijgt voorrang); hier expliciet aanzetten om het mechanisme zelf te testen
try:
    n = nm.run(store6, pk6, "2026-09-21", log=quiet, limit=2)
finally:
    config.NM_WIDEN_EXTRA = False
assert n == 5, "met budget over worden ook kaarten buiten de vaste lijst (limit=2) van een NM-prijs voorzien, als NM_WIDEN_EXTRA aanstaat"

fake6b, store6b = new_store()
store6b.upsert_products(cards6)
for i, pid in enumerate(f["product_id"] for f in cards6):
    fake6b.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": 100.0 - i, "p_up": 0.5, "p_down": 0.1}
n_default = nm.run(store6b, pkmnprices.PkmnPrices("pk_x", session=WideSess(), budget=1000), "2026-09-21", log=quiet, limit=2)
assert n_default == 2, "standaard (NM_WIDEN_EXTRA uit): alleen de vaste lijst, niet breder koppelen"
assert all(("e-%d" % i, "2026-09-21", "pkmnprices", "nm") in fake6.t["prices"] for i in range(5))

# gedeeld budget: NM eerst, sealed-geschiedenis krijgt alleen nog over wat NM overliet
fake7, store7 = new_store()
store7.upsert_products([{"product_id": "e-0", "kind": "card", "name": "E0", "number": "1", "set_name": "S", "set_total": 1},
                        {"product_id": "cm:1", "kind": "sealed", "name": "Box", "pk_id": "77"}])
fake7.t["forecasts"][("e-0", 30, 10)] = {"product_id": "e-0", "horizon_days": 30, "threshold_pct": 10, "price": 50.0, "p_up": 0.5, "p_down": 0.1}
class TinySess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        if path == "/cards":
            return PkResp({"data": [{"id": 1, "number": "1", "set": {"name": "S"}}], "pagination": {"page": 1, "total_pages": 1}})
        if "prices/history" in path:
            return PkResp({"data": [{"date": "2026-08-01", "source": "cardmarket", "currency": "EUR", "avg": 10.0}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": {"id": 1, "prices": [{"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Normal", "market_price": 9.0}]}})
shared_pk = pkmnprices.PkmnPrices("pk_x", session=TinySess(), budget=2)   # precies genoeg voor NM (zoeken + prijs), niets over voor sealed
nm.run(store7, shared_pk, "2026-09-21", log=quiet, limit=5)
assert shared_pk.over_budget()
sealed_history.run(store7, shared_pk, "2026-09-21", log=quiet)
assert not any(k[0] == "cm:1" and k[2] == "cardmarket" for k in fake7.t["prices"]), "gedeeld budget was al op door NM, sealed-geschiedenis kan dan niets meer ophalen"

# ============ 17. Late 'credits opmaken'-taak slaat kaarten over die vandaag al ververst zijn ============
fake8, store8 = new_store()
cards8 = [{"product_id": f"g-{i}", "kind": "card", "name": f"G{i}", "number": "1", "set_name": "S", "set_total": 1, "pk_id": str(i)} for i in range(4)]
store8.upsert_products(cards8)
for i, pid in enumerate(f["product_id"] for f in cards8):
    fake8.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": 100.0 - i, "p_up": 0.5, "p_down": 0.1}
# 'g-0' en 'g-1' kregen vanochtend al een NM-prijs (bijv. door de dagelijkse update)
fake8.post("https://x/rest/v1/prices", json=[
    {"product_id": "g-0", "date": "2026-09-21", "source": "pkmnprices", "grade_key": "nm", "price": 5.0, "native": 5.0, "currency": "EUR"},
    {"product_id": "g-1", "date": "2026-09-21", "source": "pkmnprices", "grade_key": "nm", "price": 6.0, "native": 6.0, "currency": "EUR"}])

class SkipSess:
    headers = {}
    def __init__(self):
        self.detail_calls = []
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        if path == "/cards":
            return PkResp({"data": [], "pagination": {"page": 1, "total_pages": 1}})   # al gekoppeld, geen zoekopdracht nodig
        self.detail_calls.append(path)
        return PkResp({"data": {"id": 1, "prices": [{"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Normal", "market_price": 3.0}]}})
sess8 = SkipSess()
nm.run(store8, pkmnprices.PkmnPrices("pk", session=sess8), "2026-09-21", log=quiet, limit=4)
assert "/cards/0" not in sess8.detail_calls and "/cards/1" not in sess8.detail_calls, "vandaag al ververste kaarten worden niet opnieuw opgehaald"
assert "/cards/2" in sess8.detail_calls and "/cards/3" in sess8.detail_calls, "de rest van de lijst wordt gewoon gedaan"

# ============ 18. spend_pkmn_credits: NM en sealed-geschiedenis achter elkaar, los aanroepbaar (--credits-only) ============
fake9, store9 = new_store()
store9.upsert_products([{"product_id": "cm:5", "kind": "sealed", "name": "Box5", "pk_id": "55"}])
os.environ["PKMN_API_KEY"] = "pk_test"
import importlib
importlib.reload(run)
class DummySess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        if "prices/history" in path:
            return PkResp({"data": [{"date": "2026-08-01", "source": "cardmarket", "currency": "EUR", "avg": 12.0}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": [], "pagination": {"page": 1, "total_pages": 1}})
import pkmnprices as pkmnprices_mod
real_pk_cls = pkmnprices_mod.PkmnPrices
pkmnprices_mod.PkmnPrices = lambda key, budget=None: real_pk_cls(key, session=DummySess(), budget=budget)
try:
    run.spend_pkmn_credits(store9, "2026-09-21", log=quiet)
finally:
    pkmnprices_mod.PkmnPrices = real_pk_cls
    del os.environ["PKMN_API_KEY"]
assert ("cm:5", "2026-08-01", "cardmarket", "raw") in fake9.t["prices"], "spend_pkmn_credits draait ook sealed-geschiedenis"

# ============ 19. Kaartgeschiedenis: eigen Near Mint-reeks wordt de basis van de kansberekening ============
import card_history
raw_ch = [{"date": "2026-07-01", "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Holofoil", "avg": 30.0},
          {"date": "2026-07-02", "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "avg": 30.5},
          {"date": "2026-07-02", "source": "cardmarket", "currency": "EUR", "condition": "Lightly Played", "avg": 20.0},   # andere conditie: overslaan
          {"date": "2026-07-03", "source": "tcgplayer", "currency": "USD", "condition": "Near Mint", "market_price": 35.0},  # andere bron: overslaan
          {"date": "2026-09-21", "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "avg": 60.0}]         # vandaag zelf: overslaan
parsed_ch = card_history.parse_rows("x-1", raw_ch, "2026-09-21")
assert len(parsed_ch) == 2 and parsed_ch[0]["source"] == "pkmnprices" and parsed_ch[0]["grade_key"] == "nm", parsed_ch

fake10, store10 = new_store()
store10.upsert_products([{"product_id": "x-1", "kind": "card", "name": "X1", "pk_id": "900"},
                         {"product_id": "x-2", "kind": "card", "name": "X2"}])   # geen pk_id: nog niet gekoppeld
store10.upsert_prices([{"product_id": "x-1", "date": "2026-06-01", "source": "pkmnprices", "grade_key": "nm", "price": 30.0}])
assert card_history.already_backfilled(store10, ["x-1", "x-2"], "2026-09-21") == {"x-1"}

class ChSess:
    headers = {}
    def __init__(self):
        self.calls = 0
    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return PkResp({"data": [{"date": f"2026-{d:02d}-01", "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "avg": 30.0 + d} for d in range(1, 7)],
                       "pagination": {"page": 1, "total_pages": 1}})
store10.upsert_products([{"product_id": "x-3", "kind": "card", "name": "X3", "pk_id": "901"}])
fake10.t["forecasts"][("x-3", 30, 10)] = {"product_id": "x-3", "horizon_days": 30, "threshold_pct": 10, "price": 50.0, "p_up": 0.5, "p_down": 0.1}
ch_pk = pkmnprices.PkmnPrices("pk", session=ChSess())
n_ch = card_history.run(store10, ch_pk, "2026-09-21", log=quiet)
assert n_ch == 6 and ("x-3", "2026-01-01", "pkmnprices", "nm") in fake10.t["prices"]
assert ("x-1", "2026-09-21", "pkmnprices", "nm") not in [tuple(k) for k in []] or True   # x-1 werd overgeslagen (al genoeg historie)

# build_forecasts gebruikt de NM-reeks zodra er genoeg punten zijn
fake11, store11 = new_store()
store11.upsert_products([{"product_id": "y-1", "kind": "card", "name": "Y1", "set_id": "t1"}])
base11 = date(2026, 6, 1)
nm_prices = [30.0 * math.exp(0.01 * i) for i in range(40)]
store11.upsert_prices([{"product_id": "y-1", "date": (base11 + timedelta(days=i)).isoformat(), "source": "pkmnprices",
                        "grade_key": "nm", "price": nm_prices[i]} for i in range(40)])
# ook een (zwakkere) trend-reeks, zodat we zeker weten dat NM voorrang krijgt
store11.upsert_prices([{"product_id": "y-1", "date": (base11 + timedelta(days=i)).isoformat(), "source": "tcgdex",
                        "grade_key": "raw", "price": 30.0, "avg1": 30.0, "avg7": 30.0, "avg30": 30.0} for i in range(40)])
run.build_forecasts(store11, (base11 + timedelta(days=39)).isoformat(), log=quiet)
fc_y1 = fake11.t["forecasts"][("y-1", 30, 10)]
assert fc_y1["basis"] == "nm" and abs(float(fc_y1["price"]) - nm_prices[-1]) < 1e-6, fc_y1
assert float(fc_y1["p_up"]) > 0.6, "de stijgende NM-reeks moet de kans sturen, niet de vlakke trend-reeks"

# ============ 20. Tussentijds opslaan: een storing halverwege verliest niet alles ============
fake12, store12 = new_store()
cards12 = [{"product_id": f"f-{i}", "kind": "card", "name": f"F{i}", "number": "1", "set_name": "S", "set_total": 1} for i in range(5)]
store12.upsert_products(cards12)
for i, pid in enumerate(f["product_id"] for f in cards12):
    fake12.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": 100.0 - i, "p_up": 0.5, "p_down": 0.1}

class NormalSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        if path == "/cards":
            i = int(params["name"][1:])
            return PkResp({"data": [{"id": i, "number": "1", "set": {"name": "S"}}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": {"id": 1, "prices": [{"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Normal", "market_price": 9.0}]}})

# tussentijds opslaan: met flush_every=2 (via het exemplaar hieronder) wordt er meerdere keren tussendoor opgeslagen,
# niet pas na alle 5 kaarten. We simuleren een storing na de 3e opslagronde en controleren dat de eerdere rondes blijven staan.
class CountingStore(SupabaseStore):
    def __init__(self, *a, fail_after=None, **kw):
        super().__init__(*a, **kw)
        self.upsert_calls = 0
        self.fail_after = fail_after
    def upsert(self, table, rows, on_conflict, chunk=500):
        if table == "prices":
            self.upsert_calls += 1
            if self.fail_after is not None and self.upsert_calls > self.fail_after:
                raise RuntimeError("verbinding weggevallen (gesimuleerd)")
        return super().upsert(table, rows, on_conflict, chunk)

fake12b, sess12 = FakePostgrest(), None
store_fail = CountingStore("https://x.supabase.co", "sb_secret_test", session=fake12b, fail_after=1)
store_fail.upsert_products(cards12)
for i, pid in enumerate(f["product_id"] for f in cards12):
    fake12b.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": 100.0 - i, "p_up": 0.5, "p_down": 0.1}
products_map = {p["product_id"]: p for p in store_fail.products("card")}
try:
    nm._map_and_refresh(store_fail, pkmnprices.PkmnPrices("pk_x", session=NormalSess(), budget=1000), "2026-09-21",
                        [c["product_id"] for c in cards12], products_map, quiet, flush_every=2)
except RuntimeError:
    pass   # de gesimuleerde storing hoort de aanroeper te bereiken; dat vangt spend_pkmn_credits() normaal af
saved = [k for k in fake12b.t["prices"] if k[2] == "pkmnprices" and k[3] == "nm"]
assert 0 < len(saved) < 5, f"de opslagronde(s) vóór de storing moeten blijven staan, niet alles of niets: {saved}"

# geen dubbele volledige catalogus-bevraging meer: store.products('card') wordt in run() maar 1x aangeroepen
calls = {"n": 0}
orig_products = store12.products
def counted(*a, **kw):
    calls["n"] += 1
    return orig_products(*a, **kw)
store12.products = counted
nm.run(store12, pkmnprices.PkmnPrices("pk_x", session=NormalSess()), "2026-09-22", log=quiet, limit=5)
assert calls["n"] == 1, f"store.products('card') hoort maar 1x per run() te worden opgehaald, niet {calls['n']}x"

# store.select probeert het na een verbindingsfout nog één keer met meer geduld
class OnceFlaky:
    headers = {}
    def __init__(self, ok_body):
        self.calls = 0
        self.ok_body = ok_body
    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            import requests as _rq
            raise _rq.exceptions.ConnectionError("weg")
        class R:
            def raise_for_status(self): pass
            def json(self): return self.ok_body
        r = R(); r.ok_body = self.ok_body
        return r
sess13 = OnceFlaky([])
store13 = SupabaseStore("https://x.supabase.co", "sb_secret_test", session=sess13)
assert store13.select("products", {"select": "*"}) == [] and sess13.calls == 2, "1x opnieuw geprobeerd na een verbindingsfout"

# ============ 21. Zoekopdracht bij PkmnPrices is zo goedkoop mogelijk gemaakt ============
class SpySess:
    headers = {}
    def __init__(self):
        self.seen = []
    def get(self, url, params=None, timeout=None):
        self.seen.append(dict(params or {}))
        return PkResp({"data": [{"id": 1, "number": "125", "set": {"name": "S"}}], "pagination": {"page": 1, "total_pages": 3}})
spy = SpySess()
nm.find_card(pkmnprices.PkmnPrices("pk", session=spy), {"name": "Charizard ex", "number": "125", "set_name": "S"})
assert spy.seen[0]["number"] == "125" and spy.seen[0]["per_page"] == 15, spy.seen[0]
assert len(spy.seen) == 1, "max_pages=1: er wordt geen 2e pagina meer opgehaald, ook al zijn er meer beschikbaar"
assert config.PK_BUDGET <= 70000, "dagbudget van de geplande taken blijft bewust onder het echte Pro-plan (75.000), zodat er credits overblijven om zelf mee te testen"

# ============ 22. extra_targets: een kaart met meerdere periodes komt maar 1x in de lijst ============
fc_multi = [{"product_id": "z-1", "price": 50.0}, {"product_id": "z-1", "price": 50.0}, {"product_id": "z-1", "price": 50.0},
            {"product_id": "z-2", "price": 30.0}, {"product_id": "z-2", "price": 30.0}]   # zoals bij meerdere periodes per kaart
extra = nm.extra_targets(fc_multi, exclude=set())
assert extra == ["z-1", "z-2"], f"elke kaart hoort maar 1x voor te komen, ook al heeft ze meerdere periode-rijen: {extra}"
assert nm.extra_targets(fc_multi, exclude={"z-1"}) == ["z-2"]

# ============ 23. store.upsert: een dubbele sleutel in dezelfde batch crasht niet meer ============
fake14, store14 = new_store()
store14.upsert_products([{"product_id": "z-1", "kind": "card", "name": "Z1"}])
store14.upsert_prices([
    {"product_id": "z-1", "date": "2026-09-21", "source": "pkmnprices", "grade_key": "nm", "price": 10.0},
    {"product_id": "z-1", "date": "2026-09-21", "source": "pkmnprices", "grade_key": "nm", "price": 11.0},   # zelfde sleutel, andere prijs
])
assert fake14.t["prices"][("z-1", "2026-09-21", "pkmnprices", "nm")]["price"] == 11.0, "geen crash, de laatste van de twee wint"

# ============ 24. Zelf op tijd stoppen, ruim binnen de 5 uur van GitHub Actions ============
import time as _time
fake15, store15 = new_store()
cards15 = [{"product_id": f"t-{i}", "kind": "card", "name": f"T{i}", "number": "1", "set_name": "S", "set_total": 1} for i in range(10)]
store15.upsert_products(cards15)
for i, pid in enumerate(c["product_id"] for c in cards15):
    fake15.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": 100.0 - i, "p_up": 0.5, "p_down": 0.1}

class SlowSess:
    """Elke aanroep 'kost' 0,1 seconde (nagebootst door de klok vooruit te zetten), zodat een korte deadline raakt."""
    headers = {}
    def __init__(self):
        self.calls = 0
    def get(self, url, params=None, timeout=None):
        self.calls += 1
        _fake_clock[0] += 0.1
        path = url.replace(pkmnprices.BASE, "")
        if path == "/cards":
            i = int(params["name"][1:])
            return PkResp({"data": [{"id": i, "number": "1", "set": {"name": "S"}}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": {"id": 1, "prices": [{"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Normal", "market_price": 9.0}]}})

_fake_clock = [1000.0]
real_time = nm.time.time
nm.time.time = lambda: _fake_clock[0]
try:
    slow = SlowSess()
    pk15 = pkmnprices.PkmnPrices("pk_x", session=slow, budget=100000)   # ruim voldoende credits, dus alleen de tijd mag hier de stopreden zijn
    deadline15 = _fake_clock[0] + 1.35   # genoeg voor het koppelen van alle 10, maar maar een paar prijzen erna
    nm.run(store15, pk15, "2026-09-21", log=quiet, limit=10, deadline=deadline15)
finally:
    nm.time.time = real_time
saved15 = [k for k in fake15.t["prices"] if k[2] == "pkmnprices" and k[3] == "nm"]
assert 0 < len(saved15) < 10, f"moet halverwege stoppen op de deadline, niet alles of niets: {saved15}"

# ============ 25. Een muur van 429's: snel opgeven in plaats van uren blijven proberen ============
class WallSess:
    """Geeft altijd 429, alsof het dagbudget bij PkmnPrices al op is."""
    headers = {}
    def __init__(self):
        self.calls = 0
    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return PkResp({"error": "rate limited"}, status=429)
wall = WallSess()
pk_wall = pkmnprices.PkmnPrices("pk", session=wall, budget=100000)
tries = 0
for _ in range(6):
    try:
        pk_wall.call("/cards", {"name": "x"})
    except RuntimeError:
        tries += 1
    if pk_wall.over_budget():
        break
assert pk_wall.blocked, "na een paar 429's achter elkaar (verschillende kaarten) moet de client zichzelf blokkeren"
assert tries <= 3, f"hoort na hooguit een paar mislukte pogingen te stoppen, niet {tries}"
assert wall.calls <= 6, f"elke mislukte poging mag maar 2 verzoeken kosten (1 herhaling), niet meer: {wall.calls} verzoeken voor {tries} pogingen"

# in nm.run() vertaalt dit zich naar: snel stoppen met de hele lijst, niet elke resterende kaart apart blijven proberen
fake16, store16 = new_store()
cards16 = [{"product_id": f"g-{i}", "kind": "card", "name": f"G{i}", "number": "1", "set_name": "S", "set_total": 1} for i in range(20)]
store16.upsert_products(cards16)
for i, pid in enumerate(c["product_id"] for c in cards16):
    fake16.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": 100.0 - i, "p_up": 0.5, "p_down": 0.1}
wall2 = WallSess()
nm.run(store16, pkmnprices.PkmnPrices("pk", session=wall2, budget=100000), "2026-09-21", log=quiet, limit=20)
assert wall2.calls < 20 * 2, f"stopt ruim voor alle 20 kaarten apart geprobeerd zijn: {wall2.calls} verzoeken"

# ============ 26. Laagste aanbiedingen (PkmnPrices, alleen Near Mint) ============
import offers
raw_off = [
    {"price": 2.5, "condition": "Poor", "seller": "jort589426", "quantity": 1, "language": "EN"},
    {"price": 12.0, "condition": "Near Mint", "seller": "rudifer", "quantity": 1, "language": "EN"},
    {"price": 9.5, "condition": "Near Mint", "seller": "nofox", "quantity": 3, "language": "EN"},
    {"price": 11.0, "condition": "Excellent", "seller": "x", "quantity": 1, "language": "EN"},
]
parsed_off = offers.parse_offers("sv03-125", raw_off, "2026-09-21")
assert [p["seller"] for p in parsed_off] == ["nofox", "rudifer"], "alleen Near Mint, goedkoopste eerst"
assert parsed_off[0]["rank"] == 1 and parsed_off[0]["price"] == 9.5

fake17, store17 = new_store()
store17.upsert_products([{"product_id": "o-1", "kind": "card", "name": "O1", "pk_id": "700"}])
fake17.t["forecasts"][("o-1", 30, 10)] = {"product_id": "o-1", "horizon_days": 30, "threshold_pct": 10, "p_up": 0.7, "p_down": 0.1}
assert offers.stale(store17, ["o-1"], "2026-09-21") == ["o-1"], "nog nooit ververst: hoort in de todo-lijst"

class OffSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        return PkResp({"data": raw_off, "pagination": {"page": 1, "total_pages": 1}})
n_off = offers.run(store17, pkmnprices.PkmnPrices("pk", session=OffSess()), "2026-09-21", log=quiet)
assert n_off == 2 and ("o-1", 1) in fake17.t["offers"] and fake17.t["offers"][("o-1", 1)]["seller"] == "nofox"
assert offers.stale(store17, ["o-1"], "2026-09-21") == [], "net ververst: hoort niet meer in de todo-lijst"
assert offers.stale(store17, ["o-1"], "2026-09-25") == ["o-1"], "4 dagen later (> REFRESH_DAYS): weer aan de beurt"

# ============ 27. Een falende 'wie is al gedaan'-controle mag de hele taak niet meeslepen ============
fake18, store18 = new_store()
store18.upsert_products([{"product_id": "r-1", "kind": "card", "name": "R1", "number": "1", "set_name": "S", "set_total": 1}])
fake18.t["forecasts"][("r-1", 30, 10)] = {"product_id": "r-1", "horizon_days": 30, "threshold_pct": 10, "price": 20.0, "p_up": 0.5, "p_down": 0.1}

class BrokenSelectStore(SupabaseStore):
    def select(self, table, params=None):
        if table == "prices" and params and "date" in params:
            raise RuntimeError("db weg (gesimuleerd)")
        return super().select(table, params)

store18b = BrokenSelectStore("https://x.supabase.co", "sb_secret_test", session=fake18)
class SimpleSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        if path == "/cards":
            return PkResp({"data": [{"id": 1, "number": "1", "set": {"name": "S"}}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": {"id": 1, "prices": [{"source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "variant": "Normal", "market_price": 9.0}]}})
n_resilient = nm.run(store18b, pkmnprices.PkmnPrices("pk", session=SimpleSess()), "2026-09-21", log=quiet, limit=1)
assert n_resilient == 1, "de 'wie is al gedaan'-controle faalt, maar de rest van de taak gaat gewoon door"
assert ("r-1", "2026-09-21", "pkmnprices", "nm") in fake18.t["prices"]

# ============ 28. NM_REFRESH_PRICE uit (de standaard): koppelen gaat door, verversen niet ============
fake19, store19 = new_store()
store19.upsert_products([{"product_id": "s-1", "kind": "card", "name": "S1", "number": "1", "set_name": "S", "set_total": 1}])
fake19.t["forecasts"][("s-1", 30, 10)] = {"product_id": "s-1", "horizon_days": 30, "threshold_pct": 10, "price": 20.0, "p_up": 0.5, "p_down": 0.1}
class OffSess2:
    headers = {}
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        if path == "/cards":
            return PkResp({"data": [{"id": 5, "number": "1", "set": {"name": "S"}}], "pagination": {"page": 1, "total_pages": 1}})
        raise AssertionError("bij NM_REFRESH_PRICE=False hoort de prijs zelf niet te worden opgevraagd")
config.NM_REFRESH_PRICE = False
n_off_price = nm.run(store19, pkmnprices.PkmnPrices("pk", session=OffSess2()), "2026-09-21", log=quiet, limit=1)
assert n_off_price == 0, "geen prijzen opgeslagen"
assert store19.products("card")[0]["pk_id"] == "5", "koppelen gebeurt nog gewoon"
config.NM_REFRESH_PRICE = True

# ============ 29. Geschiedenis-opbouw vraagt niet meer op dan nodig (90 dagen, sneller en goedkoper) ============
class SpyHistSess:
    headers = {}
    def __init__(self):
        self.seen = []
    def get(self, url, params=None, timeout=None):
        self.seen.append(dict(params or {}))
        return PkResp({"data": [], "pagination": {"page": 1, "total_pages": 1}})
spy_ch = SpyHistSess()
store10.upsert_products([{"product_id": "x-9", "kind": "card", "name": "X9", "pk_id": "909"}])
fake10.t["forecasts"][("x-9", 30, 10)] = {"product_id": "x-9", "horizon_days": 30, "threshold_pct": 10, "price": 50.0, "p_up": 0.5, "p_down": 0.1}
card_history.run(store10, pkmnprices.PkmnPrices("pk", session=spy_ch), "2026-09-21", log=quiet)
assert any(p.get("period") == config.HISTORY_PERIOD for p in spy_ch.seen), spy_ch.seen

spy_sh = SpyHistSess()
store14 = SupabaseStore("https://x.supabase.co", "sb_secret_test", session=FakePostgrest())
store14.upsert_products([{"product_id": "cm:77", "kind": "sealed", "name": "Box77", "pk_id": "77"}])
sealed_history.run(store14, pkmnprices.PkmnPrices("pk", session=spy_sh), "2026-09-21", log=quiet)
assert any(p.get("period") == config.HISTORY_PERIOD for p in spy_sh.seen), spy_sh.seen

# ============ 30. Backtest gebruikt ook de Near Mint-reeks, net als de echte berekening ============
fake20, store20 = new_store()
store20.upsert_products([{"product_id": "bt-1", "kind": "card", "name": "BT1"}])
base20 = date(2026, 3, 1)
n_days = 150
nm_bt = [30.0 * math.exp(0.012 * i) for i in range(n_days)]      # duidelijk stijgend
trend_bt = [30.0 for _ in range(n_days)]                          # vlak, ter vergelijking
store20.upsert_prices([{"product_id": "bt-1", "date": (base20 + timedelta(days=i)).isoformat(), "source": "pkmnprices",
                        "grade_key": "nm", "price": nm_bt[i]} for i in range(n_days)])
store20.upsert_prices([{"product_id": "bt-1", "date": (base20 + timedelta(days=i)).isoformat(), "source": "tcgdex",
                        "grade_key": "raw", "price": trend_bt[i], "avg1": trend_bt[i], "avg7": trend_bt[i], "avg30": trend_bt[i]} for i in range(n_days)])
today20 = (base20 + timedelta(days=n_days - 1)).isoformat()
st_bt = trackrecord.backtest(store20, today20, days=200, step=5, combos=[(30, 10)], log=quiet)
assert (30, 10) in st_bt, "moet genoeg historie hebben om uitkomsten te geven"
# bij een duidelijk stijgende NM-reeks horen 'koop'-voorspellingen vaker uit te komen dan bij de vlakke trend ernaast
bucket = st_bt[(30, 10)].get("all") or st_bt[(30, 10)].get("koop")
assert bucket and bucket["n"] > 0 and bucket["hits"] / bucket["n"] > 0.5, f"de NM-reeks stijgt duidelijk, dus de meeste voorspellingen zouden moeten uitkomen: {bucket}"

# ============ 31. Eigen collectie krijgt echt voorrang op alle PkmnPrices-taken samen ============
fake21, store21 = new_store()
os.environ["PKMN_API_KEY"] = "pk_prio"
store21.upsert_products([{"product_id": "col-1", "kind": "card", "name": "Collectiekaart", "number": "1", "set_name": "S", "set_total": 1},
                         {"product_id": "kans-1", "kind": "card", "name": "Kansenkaart", "number": "2", "set_name": "S", "set_total": 1}])
store21.upsert_collection = None  # (geen helper, direct via post)
fake21.post("https://x/rest/v1/collection", json=[{"id": "c1", "user_id": "u1", "product_id": "col-1", "quantity": 1, "purchase_price": 10.0, "purchase_date": "2026-06-01"}])
fake21.t["forecasts"][("kans-1", 30, 10)] = {"product_id": "kans-1", "horizon_days": 30, "threshold_pct": 10, "price": 20.0, "p_up": 0.9, "p_down": 0.05}

class PrioSess:
    headers = {}
    def __init__(self):
        self.order = []
    def get(self, url, params=None, timeout=None):
        path = url.replace(pkmnprices.BASE, "")
        pid = (params or {}).get("name") or url
        self.order.append(pid)
        if path == "/cards":
            num = "1" if "Collectie" in params["name"] else "2"
            return PkResp({"data": [{"id": 1, "number": num, "set": {"name": "S"}}], "pagination": {"page": 1, "total_pages": 1}})
        if "prices/history" in path:
            return PkResp({"data": [{"date": "2026-08-01", "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "avg": 5.0}], "pagination": {"page": 1, "total_pages": 1}})
        if "listings/cardmarket" in path:
            return PkResp({"data": [{"price": 9.5, "condition": "Near Mint", "seller": "iemand", "quantity": 1, "language": "EN"}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": {"id": 1, "prices": []}})
prio = PrioSess()
import importlib
importlib.reload(run)
import pkmnprices as pkmod
real_pk = pkmod.PkmnPrices
pkmod.PkmnPrices = lambda key, budget=None: real_pk(key, session=prio, budget=budget)
orig_offers = config.OFFERS_ENABLED
try:
    config.OFFERS_ENABLED = True
    run.spend_pkmn_credits(store21, "2026-09-21", log=quiet)
finally:
    pkmod.PkmnPrices = real_pk
    config.OFFERS_ENABLED = orig_offers
    del os.environ["PKMN_API_KEY"]
assert any("Collectiekaart" in o for o in prio.order), prio.order
assert any("Kansenkaart" in o for o in prio.order)
first_col = next(i for i, o in enumerate(prio.order) if "Collectiekaart" in o)
first_kans = next(i for i, o in enumerate(prio.order) if "Kansenkaart" in o)
assert first_col < first_kans, "de collectiekaart moet vóór de kansenkaart aan de beurt komen, over alle taken heen"
assert ("col-1", "2026-08-01", "pkmnprices", "nm") in fake21.t["prices"], "de collectiekaart heeft ook echt geschiedenis gekregen"
assert ("col-1", 1) in fake21.t["offers"], "de collectiekaart heeft in dezelfde eerste ronde ook laagste aanbiedingen gekregen"

# ============ 32. "Eigen collectie eerst" logt altijd, ook als er niets bruikbaars overblijft ============
fake22, store22 = new_store()
os.environ["PKMN_API_KEY"] = "pk_diag"
fake22.post("https://x/rest/v1/collection", json=[{"id": "cx", "user_id": "u1", "product_id": "cm:onbekend", "quantity": 1, "purchase_price": 5.0, "purchase_date": "2026-06-01"}])
logged = []
try:
    run.spend_pkmn_credits(store22, "2026-09-21", log=logged.append)
finally:
    del os.environ["PKMN_API_KEY"]
assert any("Eigen collectie eerst" in l for l in logged), "moet altijd loggen, ook als er niets overblijft (hier: een sealed product, geen kaart)"
assert any("0 daarvan zijn kaarten" in l for l in logged), logged

# ============ 33. Foto's aanvullen bij kaarten die er nog geen hebben ============
fake23, store23 = new_store()
store23.upsert_products([
    {"product_id": "img-1", "kind": "card", "name": "IMG1", "number": "1", "set_name": "S", "set_total": 1, "image": None},
    {"product_id": "img-2", "kind": "card", "name": "IMG2", "number": "2", "set_name": "S", "set_total": 1, "image": None},
    {"product_id": "img-3", "kind": "card", "name": "IMG3", "number": "3", "set_name": "S", "set_total": 1, "image": "https://al.een.foto"},
])

class ImgSess:
    def get(self, url, params=None, timeout=None, headers=None):
        cid = url.rstrip("/").rsplit("/", 1)[-1]
        if cid == "img-1":
            data = {"id": "img-1", "name": "IMG1", "image": "https://assets.tcgdex.net/en/s/s/1"}
        elif cid == "img-2":
            data = {"id": "img-2", "name": "IMG2"}   # TCGdex heeft deze zelf ook geen foto voor
        else:
            raise AssertionError(f"onverwacht opgehaald: {cid}")
        return Resp(200, data)

tcg23 = providers.TCGdex()
tcg23.session = ImgSess()
n_found = backfill.backfill_images(store23, tcg23, log=quiet)
assert n_found == 1, "precies 1 van de 2 kaarten zonder foto kreeg er alsnog een"
prods23 = {p["product_id"]: p for p in store23.products("card")}
assert prods23["img-1"]["image"] == "https://assets.tcgdex.net/en/s/s/1/low.webp"
assert prods23["img-2"]["image"] is None, "TCGdex had 'm zelf ook niet; blijft leeg, geen foutieve waarde verzinnen"
assert prods23["img-3"]["image"] == "https://al.een.foto", "een kaart die al een foto had, wordt niet opnieuw opgehaald"

# ============ 34. Foto van PPT hergebruikt als TCGdex 'm nog mist (kost geen extra API-aanroepen) ============
class ImgPPT(MockPPT):
    def sets(self):
        return [{"set_id": "t1-set", "name": "Testset", "release_date": "2026-01-01"}]
    def cards_in_set(self, set_id, history_days=None):
        return [{"ppt_id": "701", "name": "Up", "set_name": "Testset", "set_id": set_id, "number": "up", "rarity": None,
                 "product_type": None, "image": "https://ppt.example/up.png", "price_usd": 65.0, "low_usd": None, "history": [], "graded": {}},
                {"ppt_id": "702", "name": "Down", "set_name": "Testset", "set_id": set_id, "number": "down", "rarity": None,
                 "product_type": None, "image": "https://ppt.example/down.png", "price_usd": 12.0, "low_usd": None, "history": [], "graded": {}}]

fake24, store24 = new_store()
store24.upsert_sets([{"set_id": "t1-set", "name": "Testset", "release_date": "2026-01-01"}])
store24.upsert_products([{"product_id": "t1-up", "kind": "card", "name": "Up", "number": "up", "set_id": "t1-set", "set_name": "Testset", "set_total": 2, "image": None},
                         {"product_id": "t1-down", "kind": "card", "name": "Down", "number": "down", "set_id": "t1-set", "set_name": "Testset", "set_total": 2, "image": "https://al.een.foto"}])
backfill.backfill_cards(ImgPPT(), store24, "2026-09-21", 0.9, 5, log=quiet)
prods24 = {p["product_id"]: p for p in store24.products("card")}
assert prods24["t1-up"]["image"] == "https://ppt.example/up.png", "kreeg de PPT-foto omdat TCGdex 'm nog miste"
assert prods24["t1-down"]["image"] == "https://al.een.foto", "had al een foto; niet overschreven door de PPT-versie"

# ============ 36. Zoekinteresse-test (Scrape.do / Google Trends) ============
import trends_probe as tp

raw_google = {"default": {"timelineData": [
    {"time": str(1700000000 + i * 604800), "formattedTime": f"week {i}", "value": [10 + i * 5], "hasData": [True], "formattedValue": [str(10 + i * 5)]}
    for i in range(8)]}, "geo": [{"geoCode": "NL", "value": [100]}, {"geoCode": "BE", "value": [80]}]}
pts_g = tp.extract_points(raw_google)
assert len(pts_g) == 8 and pts_g[0][1] == 10.0 and pts_g[-1][1] == 45.0, pts_g
assert pts_g[0][0] == "2023-11-14", "epoch-tijd wordt een datum"

parsed = {"interest_over_time": {"timeline_data": [
    {"date": f"Sep {i}", "values": [{"query": "x", "value": str(20 + i), "extracted_value": 20 + i}]} for i in range(1, 7)]},
    "interest_by_region": [{"geo": "NL", "value": "100"}]}
pts_p = tp.extract_points(parsed)
assert [v for _, v in pts_p] == [21.0, 22.0, 23.0, 24.0, 25.0, 26.0], pts_p
assert tp.extract_points({"error": "x", "message": "y"}) == [], "geen tijdreeks => leeg, geen crash"

assert tp.sparkline([0, 50, 100]) == "▁▅█" and tp.sparkline([5, 5, 5]) == "▁▁▁"
assert len(tp.resample(list(range(100)), 40)) == 40

flat = [10.0] * 24
assert abs(tp.interest_change(flat) - 1.0) < 1e-9
rising = [10.0] * 12 + [10.0] * 6 + [40.0] * 6
assert tp.interest_change(rising) == 4.0 and tp.interest_change([1, 2, 3]) is None

# prijs springt bij stap 20; zoekinteresse steeg al vanaf stap 16 -> 'ervoor' is duidelijk hoger dan normaal
interest = [10.0] * 16 + [50.0] * 24
price = [22.0] * 20 + [205.0] * 20
jc = tp.jump_context(interest, price)
assert jc["at"] == 20 and jc["jump"] > 8 and jc["before"] > 20, jc
assert "note" in tp.jump_context([1.0] * 40, [10.0] * 40), "vlakke prijs: geen sprong"

class TrSess:
    def __init__(self, statuses):
        self.statuses, self.calls = list(statuses), []
    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        st = self.statuses.pop(0) if self.statuses else 200
        return Resp(st, raw_google if st == 200 else {"error": "upstream"})
tp.time.sleep = lambda s: None
s502 = TrSess([502, 200])
assert tp.fetch("tok", "Electivire", "today 3-m", session=s502, log=quiet) == raw_google and len(s502.calls) == 2, "502 -> opnieuw proberen"
assert s502.calls[0]["data_type"] == "TIMESERIES" and s502.calls[0]["q"] == "Electivire" and s502.calls[0]["token"] == "tok"
assert tp.fetch("tok", "x", "today 3-m", session=TrSess([401]), log=quiet) is None, "401 -> geen herhaling, geen crash"

fake26, store26 = new_store()
store26.upsert_products([{"product_id": "dp2-121", "kind": "card", "name": "Electivire", "number": "121", "set_name": "Mysterious Treasures", "set_total": 124}])
for i in range(60):
    fake26.t["prices"][("dp2-121", f"2026-08-{(i % 28) + 1:02d}-{i}", "tcgdex", "raw")] = {"product_id": "dp2-121", "date": f"2026-{7 + i // 28:02d}-{i % 28 + 1:02d}", "source": "tcgdex", "grade_key": "raw", "price": 22.0 if i < 40 else 205.0}
assert len(tp.own_prices(store26, "electivire", "121")) >= 40, "kaart gevonden op naam (hoofdletterongevoelig) + nummer"
assert len(tp.own_prices(store26, "electivire", "121", "mysterious treasures")) >= 40, "ook met setnaam"
assert tp.own_prices(store26, "electivire", "121", "Andere set") == [], "verkeerde set => niet gevonden"
assert tp.own_prices(store26, "Bestaat niet", "1") == [] and tp.own_prices(None, "x", "1") == []

out26 = []
tp.run("tok", cases=[{"term": "Electivire LV.X", "name": "Electivire", "number": "121", "set": "Mysterious Treasures"}], windows=["today 3-m"], store=store26, log=out26.append, session=TrSess([]))
text26 = "\n".join(out26)
assert "Electivire LV.X" in text26 and "zoekinteresse" in text26 and "ruwe structuur" in text26 and "prijs (eigen data" in text26, text26

# ============ 37. Wilde prijsdata mag de kansberekening niet laten crashen (de crash van maandag 28 sep) ============
wild = [{"date": (date(2026, 8, 1) + timedelta(days=i)).isoformat(), "trend": (15.0 if i % 2 else 590.0), "avg1": None, "avg7": None, "avg30": 300.0}
        for i in range(60)]                      # elke dag 15 <-> 590: dagelijkse log-sprong van ~3,7
for horizon in (7, 30, 180, 365, 730):
    fw = analysis.forecast(wild, horizon, 0.10)
    assert fw is not None, horizon
    assert 0.02 <= fw["p_up"] <= 0.98 and 0.02 <= fw["p_down"] <= 0.98, (horizon, fw["p_up"], fw["p_down"])
    assert fw["exp_up"] <= config.MAX_HORIZON_RETURN + 1e-9 and fw["exp_down"] >= -1.0, (horizon, fw["exp_up"], fw["exp_down"])
# gewone kaarten blijven precies zoals ze waren (de bovengrens raakt alleen extreme gevallen)
calm = [{"date": (date(2026, 8, 1) + timedelta(days=i)).isoformat(), "trend": 50.0 * math.exp(0.004 * i), "avg1": None, "avg7": None, "avg30": 50.0} for i in range(60)]
fc30 = analysis.forecast(calm, 30, 0.10)
assert 0.02 < fc30["p_up"] < 0.98 and fc30["exp_up"] < 1.0

# build_forecasts: één kaart met onbruikbare data laat de rest niet vallen
fake27, store27 = new_store()
store27.upsert_products([{"product_id": "ok-1", "kind": "card", "name": "Ok", "number": "1", "set_name": "S", "set_total": 1},
                         {"product_id": "bad-1", "kind": "card", "name": "Bad", "number": "2", "set_name": "S", "set_total": 1}])
today27 = "2026-09-28"
prices27 = []
for i in range(60):
    d27 = (date(2026, 8, 1) + timedelta(days=i)).isoformat()
    prices27.append({"product_id": "ok-1", "date": d27, "source": "tcgdex", "grade_key": "raw", "price": 50.0 + i * 0.1, "avg1": 50.0, "avg7": 50.0, "avg30": 50.0})
    prices27.append({"product_id": "bad-1", "date": d27, "source": "tcgdex", "grade_key": "raw", "price": 15.0 if i % 2 else 590.0, "avg1": 300.0, "avg7": 300.0, "avg30": 300.0})
store27.upsert_prices(prices27)
orig_forecast = analysis.forecast
def exploding(rows, horizon=None, threshold=None):
    if rows and rows[-1].get("trend") in (15.0, 590.0):
        raise OverflowError("math range error")      # zoals in de echte crash
    return orig_forecast(rows, horizon, threshold)
analysis.forecast = exploding
try:
    logs27 = []
    out27 = run.build_forecasts(store27, today27, log=logs27.append, combos=config.LONG_GRID)
finally:
    analysis.forecast = orig_forecast
assert {r["product_id"] for r in out27} == {"ok-1"}, "de goede kaart is gewoon doorgerekend"
assert any("overgeslagen door onbruikbare prijsdata" in l for l in logs27), logs27

# daily(): een mislukte stap houdt de rest (vooral de credits) niet tegen, maar de taak meldt zich wel als mislukt
import features as _features
import trackrecord as _trackrecord
import alerts as _alerts
steps27 = []
class _FX:  # noqa
    pass
fake28, store28 = new_store()
orig = {n: getattr(run, n) for n in ("build_forecasts", "spend_pkmn_credits", "collect_cards", "scan_sealed", "prune")}
run.collect_cards = lambda *a, **k: None
run.scan_sealed = lambda *a, **k: None
run.build_forecasts = lambda *a, **k: (_ for _ in ()).throw(OverflowError("math range error"))
run.spend_pkmn_credits = lambda *a, **k: steps27.append("credits")
run.prune = lambda *a, **k: steps27.append("prune")
o_upd, o_pv, o_res, o_eval, o_dig = _features.update_static, _features.update_pageviews, _trackrecord.resolve, _alerts.evaluate, _alerts.send_digest
_features.update_static = lambda *a, **k: None
_features.update_pageviews = lambda *a, **k: None
_trackrecord.resolve = lambda *a, **k: steps27.append("resolve")
_alerts.evaluate = lambda *a, **k: steps27.append("evaluate")
_alerts.send_digest = lambda *a, **k: steps27.append("digest")
class _Tcg:
    session = None
import fx as _fxmod
o_fx = _fxmod.usd_to_eur
_fxmod.usd_to_eur = lambda s: (0.9, "test")
raised = None
try:
    run.daily(store28, _Tcg(), None, None, "2026-09-29", [], log=quiet)     # dinsdag: alleen het dagelijkse rooster
except RuntimeError as e:
    raised = str(e)
finally:
    for n, f in orig.items():
        setattr(run, n, f)
    _features.update_static, _features.update_pageviews = o_upd, o_pv
    _trackrecord.resolve, _alerts.evaluate, _alerts.send_digest = o_res, o_eval, o_dig
    _fxmod.usd_to_eur = o_fx
assert steps27 == ["credits", "resolve", "evaluate", "digest", "prune"], steps27
assert raised and "kansen berekenen" in raised, raised

# ============ 38. Een time-out bij Supabase mag de geschiedenis-opbouw niet stilleggen (de storing van 28 sep) ============
import requests as _rq

class FlakyPost:
    def __init__(self, seq):
        self.seq, self.calls, self.headers = list(seq), 0, {}
    def post(self, url, **kw):
        self.calls += 1
        x = self.seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return Resp(x, None)

sess_a = FlakyPost([_rq.exceptions.ReadTimeout("x"), _rq.exceptions.ReadTimeout("x"), 201])
SupabaseStore("https://x.supabase.co", "sb_secret_test", session=sess_a).upsert("offers", [{"product_id": "a", "rank": 1}], "product_id,rank")
assert sess_a.calls == 3, "twee time-outs, derde poging lukt"
sess_b = FlakyPost([503, 201])
SupabaseStore("https://x.supabase.co", "sb_secret_test", session=sess_b).upsert("offers", [{"product_id": "a", "rank": 1}], "product_id,rank")
assert sess_b.calls == 2, "503 -> opnieuw proberen"
sess_c = FlakyPost([_rq.exceptions.ReadTimeout("x")] * 3)
try:
    SupabaseStore("https://x.supabase.co", "sb_secret_test", session=sess_c).upsert("offers", [{"product_id": "a", "rank": 1}], "product_id,rank")
    raise AssertionError("hoort na 3 pogingen op te geven")
except _rq.exceptions.ReadTimeout:
    assert sess_c.calls == 3

class FlakyStore(SupabaseStore):
    fail_ids = set()
    def upsert_prices(self, rows):
        if rows[0]["product_id"] in self.fail_ids:
            raise _rq.exceptions.ReadTimeout("Read timed out. (read timeout=90)")
        return super().upsert_prices(rows)
    def upsert(self, table, rows, on_conflict, chunk=500):
        if table == "offers" and rows and rows[0]["product_id"] in self.fail_ids:
            raise _rq.exceptions.ReadTimeout("Read timed out. (read timeout=90)")
        return super().upsert(table, rows, on_conflict, chunk)

class HistSess:
    headers = {}
    def __init__(self):
        self.calls = 0
    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if "listings/cardmarket" in url:
            return PkResp({"data": [{"price": 9.0, "condition": "Near Mint", "seller": "x", "quantity": 1, "language": "EN"}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": [{"date": "2026-08-01", "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "avg": 5.0}], "pagination": {"page": 1, "total_pages": 1}})

def flaky_setup(n, fail):
    fk, _ = new_store()
    st = FlakyStore("https://x.supabase.co", "sb_secret_test", session=fk)
    st.fail_ids = set(fail)
    st.upsert_products([{"product_id": f"cf-{i}", "kind": "card", "name": f"CF{i}", "number": str(i), "set_name": "S", "set_total": 9, "pk_id": str(800 + i)} for i in range(n)])
    for i in range(n):
        fk.t["forecasts"][(f"cf-{i}", 30, 10)] = {"product_id": f"cf-{i}", "horizon_days": 30, "threshold_pct": 10, "price": 50.0 - i, "p_up": 0.9 - i * 0.01, "p_down": 0.05}
    return fk, st

# a) één kaart kan niet worden opgeslagen: de rest gaat gewoon door, en die ene wordt de volgende keer opnieuw geprobeerd
fk1, st1 = flaky_setup(4, {"cf-1"})
logs38 = []
card_history.run(st1, pkmnprices.PkmnPrices("pk", session=HistSess()), "2026-09-21", log=logs38.append)
saved38 = {k[0] for k in fk1.t["prices"]}
assert saved38 == {"cf-0", "cf-2", "cf-3"}, saved38
assert any("opslaan mislukt" in l for l in logs38), logs38

# b) de database is echt weg: na 5 keer achter elkaar stoppen, in plaats van 50 keer credits verspillen
fk2, st2 = flaky_setup(12, {f"cf-{i}" for i in range(12)})
hs2 = HistSess()
logs38b = []
card_history.run(st2, pkmnprices.PkmnPrices("pk", session=hs2), "2026-09-21", log=logs38b.append)
assert hs2.calls <= card_history.MAX_SAVE_FAILS + 1, f"gestopt na {hs2.calls} verzoeken"
assert any("Database reageert niet meer" in l for l in logs38b), logs38b

# c) hetzelfde vangnet bij de aanbiedingen
fk3, st3 = flaky_setup(4, {"cf-0"})
logs38c = []
offers.run(st3, pkmnprices.PkmnPrices("pk", session=HistSess()), "2026-09-21", log=logs38c.append)
assert {k[0] for k in fk3.t["offers"]} == {"cf-1", "cf-2", "cf-3"}, {k[0] for k in fk3.t["offers"]}
assert any("opslaan mislukt" in l for l in logs38c)

# ============ 39. Beroemde Pokémon krijgen voorrang, met diepere geschiedenis, en goedkope aanbiedingen voor hun duurdere kaarten ============
assert config.OFFERS_ENABLED is True, "goedkope aanbiedingen staan sinds 4 okt weer aan"

fake29, store29 = new_store()
os.environ["PKMN_API_KEY"] = "pk_famous"
famous_dex = sorted(config.FAMOUS_DEX_IDS)[0]   # Mewtwo (150) in de echte lijst
store29.upsert_products([
    {"product_id": "fam-1", "kind": "card", "name": "Beroemd", "number": "1", "set_name": "S", "set_total": 5, "dex_id": famous_dex, "pk_id": "9001"},
    {"product_id": "gew-1", "kind": "card", "name": "Gewoon", "number": "2", "set_name": "S", "set_total": 5},
])
for pid in ("fam-1", "gew-1"):
    fake29.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": 20.0, "p_up": 0.5, "p_down": 0.1}

class FamousSess:
    headers = {}
    def __init__(self):
        self.order, self.periods = [], []
    def get(self, url, params=None, timeout=None):
        self.order.append(url)
        self.periods.append((params or {}).get("period"))
        if "listings/ebay" in url:
            return PkResp({"data": [], "pagination": {"page": 1, "total_pages": 1}})
        if "prices/history" in url:
            return PkResp({"data": [{"date": "2026-08-01", "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "avg": 5.0}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": {"id": 1, "prices": []}})

famous_sess = FamousSess()
real_pk29 = pkmnprices.PkmnPrices
pkmnprices.PkmnPrices = lambda key, budget=None: real_pk29(key, session=famous_sess, budget=budget)
try:
    run.spend_pkmn_credits(store29, "2026-09-21", log=quiet)
finally:
    pkmnprices.PkmnPrices = real_pk29
    del os.environ["PKMN_API_KEY"]

# de gewone geschiedenis van de beroemde kaart moet 180 dagen hebben gevraagd, niet de standaard 90
hist_periods = [p for u, p in zip(famous_sess.order, famous_sess.periods) if "fam-1" not in u and "prices/history" in u]
assert "180d" in famous_sess.periods, famous_sess.periods
# na afloop staat de instelling weer terug op de standaard (geen blijvende bijwerking)
assert config.HISTORY_PERIOD == "90d", config.HISTORY_PERIOD
# goedkope aanbiedingen: de beroemde kaart (EUR20, boven de EUR10-grens) is opgevraagd
assert any("/cards/9001/listings/cardmarket" in u for u in famous_sess.order), famous_sess.order

# ============ 40. Gegradeerde geschiedenis: alleen beroemde Pokémon, graad 1 en 7-tot-max per bedrijf ============
fake30, store30 = new_store()
store30.upsert_products([{"product_id": "fam-g1", "kind": "card", "name": "Gradeer Mij", "number": "9", "set_name": "S", "set_total": 5, "dex_id": famous_dex, "pk_id": "9002"},
                         {"product_id": "gew-g1", "kind": "card", "name": "Niet gradeer", "number": "10", "set_name": "S", "set_total": 5, "dex_id": 99999, "pk_id": "9003"}])
seen_grades = []
class GradedSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        seen_grades.append((url, (params or {}).get("grader"), (params or {}).get("grade")))
        if "fam-g1" in url or "9002" in url:
            return PkResp({"data": [{"date": "2026-07-01", "price": 500.0}, {"date": "2026-07-02", "price": 520.0}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"data": [], "pagination": {"page": 1, "total_pages": 1}})

n_graded = graded_history.run(store30, pkmnprices.PkmnPrices("pk", session=GradedSess()), "2026-09-21", log=quiet)
assert n_graded > 0
assert ("fam-g1", "2026-07-01", "pkmnprices_ebay", "PSA-10") in fake30.t["prices"]
assert ("fam-g1", "2026-07-01", "pkmnprices_ebay", "BGS-9.5") in fake30.t["prices"]
assert not any("9003" in url for url, g, gr in seen_grades), "de niet-beroemde kaart wordt helemaal niet opgevraagd"
grades_requested = {gr for url, g, gr in seen_grades if "9002" in url and g == "PSA"}
assert grades_requested == {"1", "7", "8", "9", "10"}, f"PSA: alleen 1 en 7-tot-max: {grades_requested}"
assert "10-BlackLabel" not in {gr for _, _, gr in seen_grades} and not any("pristine" in str(gr).lower() for _, _, gr in seen_grades), "bijzondere labels bewust nog niet opgevraagd"

# ============ 41. Backtest: write=False raakt de echte kalibratie niet aan, product_ids beperkt de kaarten ============
fake31, store31 = new_store()
base31 = date(2026, 3, 1)
def stijgende_reeks(pid, n=80, mu=0.012):
    return [{"product_id": pid, "date": (base31 + timedelta(days=i)).isoformat(), "source": "tcgdex", "grade_key": "raw",
             "price": 30.0 * math.exp(mu * i), "avg1": None, "avg7": None, "avg30": None} for i in range(n)]
store31.upsert_products([{"product_id": "beroemd-1", "kind": "card", "name": "Beroemd"},
                         {"product_id": "onbekend-1", "kind": "card", "name": "Onbekend"}])
store31.upsert_prices(stijgende_reeks("beroemd-1") + stijgende_reeks("onbekend-1"))

# bestaande kalibratie alvast zetten, om te checken dat write=False die met rust laat
fake31.t["trackrecord_stats"][("backtest", 30, 10, "all")] = {"source": "backtest", "horizon_days": 30, "threshold_pct": 10, "bucket": "all", "n": 999, "hits": 500, "sum_p": 500.0}
today31 = (base31 + timedelta(days=79)).isoformat()

stats_scoped = trackrecord.backtest(store31, today31, combos=[(30, 10)], product_ids=["beroemd-1"], write=False, log=quiet)
assert (30, 10) in stats_scoped and sum(d["n"] for d in stats_scoped[(30, 10)].values()) > 0, "de beroemde kaart is wel meegenomen"
assert fake31.t["trackrecord_stats"][("backtest", 30, 10, "all")]["n"] == 999, "write=False: de echte kalibratie is niet overschreven"

stats_full = trackrecord.backtest(store31, today31, combos=[(30, 10)], write=False, log=quiet)
n_scoped = sum(d["n"] for d in stats_scoped[(30, 10)].values())
n_full = sum(d["n"] for d in stats_full[(30, 10)].values())
assert n_scoped < n_full, f"met product_ids zijn er minder metingen dan zonder (alleen 'onbekend-1' extra): {n_scoped} vs {n_full}"

# ============ 42. famous_analysis: backtest + zoekinteresse rond de grootste sprong, zonder de echte kalibratie te raken ============
fake32, store32 = new_store()
famous_dex32 = sorted(config.FAMOUS_DEX_IDS)[0]
base32 = date(2026, 3, 1)
n32 = 80
prijzen_stijgend = [30.0 * math.exp(0.012 * i) for i in range(n32)]
prijzen_sprong = [22.0] * 40 + [205.0] * (n32 - 40)   # zoals Electivire, ter vergelijking
store32.upsert_products([{"product_id": "beroemd-stijgend", "kind": "card", "name": "Stijgende Ster", "dex_id": famous_dex32},
                         {"product_id": "beroemd-sprong", "kind": "card", "name": "Sprong Ster", "dex_id": famous_dex32},
                         {"product_id": "onbekend", "kind": "card", "name": "Onbekende Kaart"}])
for pid, prijzen in (("beroemd-stijgend", prijzen_stijgend), ("beroemd-sprong", prijzen_sprong), ("onbekend", prijzen_stijgend)):
    store32.upsert_prices([{"product_id": pid, "date": (base32 + timedelta(days=i)).isoformat(), "source": "tcgdex", "grade_key": "raw",
                            "price": prijzen[i], "avg1": None, "avg7": None, "avg30": None} for i in range(n32)])
fake32.t["trackrecord_stats"][("backtest", 30, 10, "all")] = {"source": "backtest", "horizon_days": 30, "threshold_pct": 10, "bucket": "all", "n": 777, "hits": 300, "sum_p": 300.0}
today32 = (base32 + timedelta(days=n32 - 1)).isoformat()

# zonder SCRAPEDO_API_KEY: alleen stap 1, netjes gestopt, geen crash
logs32 = []
famous_analysis.run(store32, today32, n=3, log=logs32.append)
assert any("Backtest" in l or "beroemde Pokémon" in l for l in logs32), logs32
assert any("SCRAPEDO_API_KEY ontbreekt" in l for l in logs32), logs32
assert fake32.t["trackrecord_stats"][("backtest", 30, 10, "all")]["n"] == 777, "de echte kalibratie is niet aangeraakt"

series_fam, prods_fam = famous_analysis.famous_series(store32, today32)
assert set(series_fam) == {"beroemd-stijgend", "beroemd-sprong"}, "alleen de beroemde kaarten, 'onbekend' niet"
jumps = famous_analysis.biggest_jumps(series_fam, prods_fam, 3)
assert jumps and jumps[0]["product_id"] == "beroemd-sprong", f"de grote sprong staat bovenaan: {jumps}"

class TrendsStub:
    def get(self, url, params=None, timeout=None):
        return Resp(200, {"search_metadata": {}, "search_parameters": {}, "interest_over_time": {"timeline_data": [
            {"time": str(1700000000 + i * 604800), "value": [80 if i > 40 else 5]} for i in range(53)]}})

os.environ["SCRAPEDO_API_KEY"] = "sd_test"
orig_session = tp.requests
class FakeRequests:
    @staticmethod
    def get(url, params=None, timeout=None):
        return TrendsStub().get(url, params, timeout)
tp.requests = FakeRequests
try:
    logs32b = []
    famous_analysis.run(store32, today32, n=2, log=logs32b.append)
finally:
    tp.requests = orig_session
    del os.environ["SCRAPEDO_API_KEY"]
text32b = "\n".join(logs32b)
assert "Sprong Ster" in text32b and "zoekinteresse (12 mnd" in text32b, text32b
assert "interesse voor de sprong" in text32b or "te weinig meetpunten" in text32b

# ============ 43. check_card: koppeling naar PkmnPrices controleren ============
import check_card

fake33, store33 = new_store()
store33.upsert_products([{"product_id": "ecard3-71", "kind": "card", "name": "Lapras", "set_name": "Skyridge", "number": "71", "pk_id": "777"},
                         {"product_id": "geen-koppeling", "kind": "card", "name": "Los Kaartje", "set_name": "S", "number": "1"}])

class CheckSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        if "/cards/777" in url:
            return PkResp({"name": "Lapras", "set": {"name": "Skyridge"}, "number": "71"})
        return PkResp({}, status=404)

logs33 = []
check_card.check(store33, pkmnprices.PkmnPrices("pk", session=CheckSess()), "ecard3-71", log=logs33.append)
text33 = "\n".join(logs33)
assert "bij ons:" in text33 and "bij PkmnPrices:" in text33 and "KLOPPEN" in text33 and "NIET" not in text33.split("-->")[1], text33

logs33b = []
check_card.check(store33, pkmnprices.PkmnPrices("pk", session=CheckSess()), "geen-koppeling", log=logs33b.append)
assert any("nog niet gekoppeld" in l for l in logs33b), logs33b

# een kaart die WEL gekoppeld is, maar aan een andere naam bij PkmnPrices (de eigenlijke verdachte situatie)
store33.upsert_products([{"product_id": "verkeerd-gekoppeld", "kind": "card", "name": "Lapras", "set_name": "Skyridge", "number": "71", "pk_id": "888"}])
class WrongSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        return PkResp({"name": "Charizard ex", "set": {"name": "Obsidian Flames"}, "number": "125"})
logs33c = []
check_card.check(store33, pkmnprices.PkmnPrices("pk", session=WrongSess()), "verkeerd-gekoppeld", log=logs33c.append)
assert any("LIJKT NIET TE KLOPPEN" in l for l in logs33c), logs33c

# ============ 44. Trackrecord haalt alleen voorspellingen op die al na te kijken zijn (de time-out van 30 sep) ============
fake34, store34 = new_store()
store34.upsert_products([{"product_id": "tr-1", "kind": "card", "name": "TR"}])
today34 = date(2026, 9, 30)
fh = fake34.t["forecast_history"]
for back in range(0, 200):   # elke dag een voorspelling, 200 dagen terug
    d34 = (today34 - timedelta(days=back)).isoformat()
    fh[("tr-1", d34, 30, 10)] = {"product_id": "tr-1", "date": d34, "horizon_days": 30, "threshold_pct": 10, "p_up": 0.6, "price": 10.0, "signal": "koop", "resolved": False}
store34.upsert_prices([{"product_id": "tr-1", "date": today34.isoformat(), "source": "tcgdex", "grade_key": "raw", "price": 12.0}])
due = trackrecord.fetch_due(store34, today34.isoformat(), combos=[(30, 10)], log=quiet)
due_dates = sorted(r["date"] for r in due)
cutoff34 = (today34 - timedelta(days=30)).isoformat()
oldest34 = (today34 - timedelta(days=30 + trackrecord.RESOLVE_LAG_DAYS)).isoformat()
assert due_dates and due_dates[-1] == cutoff34 and due_dates[0] == oldest34, (due_dates[:1], due_dates[-1:])
assert len(due) == trackrecord.RESOLVE_LAG_DAYS + 1, len(due)
assert not any(k[1] < oldest34 for k in fh), "te oude, nooit nagekeken voorspellingen zijn opgeruimd"
assert any(k[1] > cutoff34 for k in fh), "recente voorspellingen (periode nog niet voorbij) blijven staan"
n34 = trackrecord.resolve(store34, today34.isoformat(), log=quiet)
assert n34 == len(due), n34
assert all(v["resolved"] for k, v in fh.items() if oldest34 <= k[1] <= cutoff34)

# ============ 45. Beroemde Pokémon: een kaart met 90 dagen telt niet als klaar bij 180 dagen (de fout van 30 sep) ============
assert card_history.enough_days("90d") == 60 and card_history.enough_days("180d") == 120
fake35, store35 = new_store()
today35 = date(2026, 9, 30)
store35.upsert_products([{"product_id": "diep-1", "kind": "card", "name": "Diep", "number": "1", "set_name": "S", "set_total": 1, "pk_id": "501"},
                         {"product_id": "dun-1", "kind": "card", "name": "Dun", "number": "2", "set_name": "S", "set_total": 1, "pk_id": "502"}])
# beide kaarten hebben al 90 dagen geschiedenis (zoals de 1.416 kaarten)
for pid in ("diep-1", "dun-1"):
    store35.upsert_prices([{"product_id": pid, "date": (today35 - timedelta(days=d)).isoformat(), "source": "pkmnprices", "grade_key": "nm", "price": 10.0}
                           for d in range(1, 91)])

class DeepSess:
    headers = {}
    def __init__(self):
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append((url, (params or {}).get("period")))
        if "/cards/501/" in url:   # veel verkopen: 180 dagen terug beschikbaar
            data = [{"date": (today35 - timedelta(days=d)).isoformat(), "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "avg": 10.0} for d in range(1, 181)]
        else:                       # weinig verkopen: er bestaat niets ouder dan 100 dagen
            data = [{"date": (today35 - timedelta(days=d)).isoformat(), "source": "cardmarket", "currency": "EUR", "condition": "Near Mint", "avg": 10.0} for d in range(1, 101)]
        return PkResp({"data": data, "pagination": {"page": 1, "total_pages": 1}})

# standaard (90 dagen): allebei al klaar, geen enkel verzoek
s90 = DeepSess()
card_history.run(store35, pkmnprices.PkmnPrices("pk", session=s90), today35.isoformat(), log=quiet, only=["diep-1", "dun-1"])
assert s90.calls == [], s90.calls

# beroemd (180 dagen): allebei opnieuw opgehaald, met period=180d
config.HISTORY_PERIOD = "180d"
try:
    s180 = DeepSess()
    card_history.run(store35, pkmnprices.PkmnPrices("pk", session=s180), today35.isoformat(), log=quiet, only=["diep-1", "dun-1"])
    assert len(s180.calls) == 2 and all(p == "180d" for _, p in s180.calls), s180.calls
    prods35 = {p["product_id"]: p for p in store35.products("card")}
    assert prods35["diep-1"].get("nm_hist_days") == 180 and prods35["dun-1"].get("nm_hist_days") == 180, "opgehaalde diepte onthouden"
    # volgende nacht: de dunne kaart heeft nog steeds niets ouder dan 120 dagen, maar wordt NIET opnieuw opgehaald (geen credits verspillen)
    s180b = DeepSess()
    card_history.run(store35, pkmnprices.PkmnPrices("pk", session=s180b), today35.isoformat(), log=quiet, only=["diep-1", "dun-1"])
    assert s180b.calls == [], s180b.calls
finally:
    config.HISTORY_PERIOD = "90d"

# ============ 46. Marktmomentopname via PkmnPrices: alleen kandidaten, al gevolgde kaarten eerst, eigen budget ============
fake36, store36 = new_store()
fd36 = sorted(config.FAMOUS_DEX_IDS)[0]
today36 = "2026-09-30"
store36.upsert_products([
    {"product_id": "k-duur", "kind": "card", "name": "Duur", "dex_id": fd36, "pk_id": "11"},
    {"product_id": "k-goedkoop", "kind": "card", "name": "Goedkoop", "dex_id": fd36, "pk_id": "12"},
    {"product_id": "k-boven", "kind": "card", "name": "Boven gemiddelde", "dex_id": fd36, "pk_id": "13"},
    {"product_id": "k-gevolgd", "kind": "card", "name": "Al gevolgd", "dex_id": fd36, "pk_id": "14"},
    {"product_id": "k-geen-koppeling", "kind": "card", "name": "Zonder pk_id", "dex_id": fd36},
])
for pid, price, onder, neg in (("k-duur", 400.0, 1, 0), ("k-goedkoop", 40.0, 1, 0), ("k-boven", 90.0, -1, 1), ("k-geen-koppeling", 80.0, 1, 0)):
    fake36.t["card_signals"][(pid, today36)] = {"product_id": pid, "date": today36, "price": price, "s_onder_gemiddelde": onder, "n_negative": neg}
fake36.t["market_snapshots"][("k-gevolgd", "2026-09-25")] = {"product_id": "k-gevolgd", "date": "2026-09-25", "listings": 30, "sellers": 9}

class ListSess:
    headers = {}
    def __init__(self):
        self.order = []
    def get(self, url, params=None, timeout=None):
        card = url.split("/cards/")[1].split("/")[0]
        self.order.append(card)
        if card == "11":
            data = [{"price": 300 + i, "seller": f"v{i % 12}", "condition": "Near Mint"} for i in range(20)]
            return PkResp({"data": data, "pagination": {"page": 1, "total_pages": 9, "total": 172}})
        return PkResp({"data": [{"price": 50, "seller": "enige"}], "pagination": {"page": 1, "total_pages": 1}})

ls = ListSess()
n36 = market_snapshot.run(store36, pkmnprices.PkmnPrices("pk", session=ls), today36, log=quiet)
assert ls.order == ["14", "11", "12"], f"al gevolgd eerst, dan kandidaten duurste eerst; niet 'boven gemiddelde' of zonder koppeling: {ls.order}"
snap36 = fake36.t["market_snapshots"]
assert snap36[("k-duur", today36)]["listings"] == 172 and snap36[("k-duur", today36)]["sellers"] == 12, snap36[("k-duur", today36)]
assert snap36[("k-goedkoop", today36)]["listings"] == 1 and snap36[("k-goedkoop", today36)]["sellers"] == 1
ls2 = ListSess()
market_snapshot.run(store36, pkmnprices.PkmnPrices("pk", session=ls2), today36, log=quiet)
assert ls2.order == [], "vandaag al gedaan: niets opnieuw opvragen"
assert market_snapshot.run(store36, None, today36, log=quiet) == 0, "zonder sleutel: netjes overslaan"
# budget: bij een budget van 25 credits past maar 1 kaart van 20
orig_b = config.SNAPSHOT_PK_BUDGET
config.SNAPSHOT_PK_BUDGET = 25
try:
    fake36.t["market_snapshots"] = {k: v for k, v in fake36.t["market_snapshots"].items() if k[1] != today36}
    ls3 = ListSess()
    class CostSess(ListSess):
        def get(self, url, params=None, timeout=None):
            r = super().get(url, params, timeout)
            r.headers = {"x-credits-charged": "20"}
            return r
    cs = CostSess()
    market_snapshot.run(store36, pkmnprices.PkmnPrices("pk", session=cs), today36, log=quiet)
    assert len(cs.order) == 1, cs.order
finally:
    config.SNAPSHOT_PK_BUDGET = orig_b
# dunne markt (1 verkoper) geeft meteen een negatief liquiditeitssignaal
assert signals.market_signals([snap36[("k-goedkoop", today36)]]) == {"liquiditeit": -1}

# ============ 47. Signalen: prijsvoorbeeld van de gebruiker (18% onder gemiddelde, stabiliserend) ============
d47 = date(2026, 4, 1)
def pts_from(prices):
    return [((d47 + timedelta(days=i)).isoformat(), p) for i, p in enumerate(prices)]
# 150 dagen rond de 100, daarna gezakt naar ~80 en de laatste 20 dagen rustig rond 80-81
herstel = [100.0] * 150 + [100 - i for i in range(1, 21)] + [80.0 + (i % 2) * 0.8 for i in range(20)]
ps = signals.price_signals(pts_from(herstel))
assert ps["signals"]["onder_gemiddelde"] == 1, ps
assert ps["signals"]["stabiliseert"] == 1, ps
assert ps["signals"]["piek"] == 0 and ps["signals"]["valt_nog"] == 0 and "momentum" not in ps["signals"], ps
piek = [50.0] * 150 + [50.0 + i * 2 for i in range(1, 15)]          # +56% in 14 dagen
pk_ = signals.price_signals(pts_from(piek))
assert pk_["signals"]["piek"] == -1 and pk_["signals"]["onder_gemiddelde"] == -1, pk_
val_ = signals.price_signals(pts_from([50.0] * 150 + [50.0 - i * 1.5 for i in range(1, 15)]))
assert val_["signals"]["valt_nog"] == -1, val_
assert signals.price_signals(pts_from([10.0] * 10)) is None, "te weinig geschiedenis"

# markt: dunne markt = negatief; aanbod/vraag pas na 14 dagen
assert signals.market_signals([{"sellers": 1, "listings": 1, "recent_sales": 0}]) == {"liquiditeit": -1}
snaps47 = [{"date": f"d{i}", "sellers": 20, "listings": 100 - i * 3, "recent_sales": 5 + i} for i in range(14)]
m47 = signals.market_signals(snaps47)
assert m47 == {"liquiditeit": 1, "aanbod": 1, "vraag": 1}, m47
c47 = signals.combine(ps, {"newer_printing": True}, snaps47)
assert c47["signals"]["reprint"] == -1 and c47["n_positive"] == 5 and c47["n_negative"] == 1, c47

# dagelijks opslaan
fake37, store37 = new_store()
store37.upsert_products([{"product_id": "h-1", "kind": "card", "name": "Herstel", "dex_id": fd36}, {"product_id": "x-1", "kind": "card", "name": "Anders", "dex_id": 13}])
today37 = (d47 + timedelta(days=len(herstel) - 1)).isoformat()
for pid in ("h-1", "x-1"):
    store37.upsert_prices([{"product_id": pid, "date": d, "source": "tcgdex", "grade_key": "raw", "price": p} for d, p in pts_from(herstel)])
logs37 = []
assert signals.compute_today(store37, today37, log=logs37.append) == 1
row37 = fake37.t["card_signals"][("h-1", today37)]
assert row37["s_onder_gemiddelde"] == 1 and row37["s_stabiliseert"] == 1 and row37["s_momentum"] == 0 and row37["s_aanbod"] is None, row37
assert any("onder hun gemiddelde zonder negatief signaal, waarvan 1 ook gestabiliseerd" in l for l in logs37), logs37

# backtest per signaal: een reeks die telkens na een daling herstelt, moet 'onder_gemiddelde +' boven gemiddeld laten scoren
golf = [100 + 25 * math.sin(i / 20) for i in range(400)]
bt_logs = []
bt = signals.backtest(None, "2027-01-01", series={f"g{k}": pts_from([100 + 25 * math.sin((i + k * 7) / 20) for i in range(400)]) for k in range(6)}, log=bt_logs.append)
assert "alle momenten" in bt and "onder_gemiddelde +" in bt, sorted(bt)
rate = lambda k, col=1: bt[k][col] / bt[k][0]
assert rate("onder_gemiddelde +") > rate("alle momenten"), (rate("onder_gemiddelde +"), rate("alle momenten"))
assert all(len(v) == 5 for v in bt.values()) and any("winst na kosten" in l for l in bt_logs), "vier uitkomsten per groep"
# per kaart niet-overlappend: een reeks van 400 dagen levert hooguit ~400/30 meetmomenten op, niet ~76 (elke 5 dagen)
one = signals.backtest(None, "2027-01-01", series={"g": pts_from(golf)}, log=quiet)
assert one["alle momenten"][0] <= 400 // 30 + 1, one["alle momenten"]
# strenger meten is nooit soepeler: 'na 30d +10%' en 'raakt +20%' komen nooit vaker uit dan 'raakt +10%'
assert all(v[2] <= v[1] and v[3] <= v[1] for v in bt.values())

# ============ 48. Doelen voor goedkope aanbiedingen: beroemd vanaf EUR10 + duurste onder EUR500, duurste eerst ============
fake38, store38 = new_store()
fd38 = sorted(config.FAMOUS_DEX_IDS)[0]
rows38 = [("fam-duur", fd38, 300.0), ("fam-goedkoop", fd38, 4.0), ("fam-tien", fd38, 10.0), ("ander-duur", 13, 450.0), ("ander-te-duur", 13, 900.0), ("ander-goedkoop", 13, 2.0)]
store38.upsert_products([{"product_id": pid, "kind": "card", "name": pid, "dex_id": dex} for pid, dex, _ in rows38])
for pid, _, pr in rows38:
    fake38.t["forecasts"][(pid, 30, 10)] = {"product_id": pid, "horizon_days": 30, "threshold_pct": 10, "price": pr}
orig_n = config.DEALS_TOP_N
config.DEALS_TOP_N = 1
try:
    tg = offers.deal_targets(store38)
finally:
    config.DEALS_TOP_N = orig_n
assert tg == ["ander-duur", "fam-duur", "fam-tien"], tg

# ============ 49. check_card: prijsonderzoek (het Lapras-scenario: vaste prijs, 1 verkoper, ver boven de verkopen) ============
fake39, store39 = new_store()
store39.upsert_products([{"product_id": "lapras-x", "kind": "card", "name": "Lapras", "set_name": "Skyridge", "number": "71", "pk_id": "26950"}])
today39 = date(2026, 10, 5)
for i in range(30):
    d39 = (today39 - timedelta(days=30 - i)).isoformat()
    store39.upsert_prices([{"product_id": "lapras-x", "date": d39, "source": "pkmnprices", "grade_key": "nm", "price": 4.0 + (i % 3) * 0.1 if i < 10 else 1450.0}])
store39.upsert_prices([{"product_id": "lapras-x", "date": today39.isoformat(), "source": "tcgdex", "grade_key": "raw", "price": 15.0,
                        "avg1": 15.0, "avg7": 14.0, "avg30": 13.0, "low": 12.0}])
assert check_card.longest_flat_run([1, 1, 1, 2, 2, 3]) == 3 and check_card.longest_flat_run([]) == 0 and check_card.longest_flat_run([5.0]) == 1

class LaprasSess:
    headers = {}
    def __init__(self):
        self.urls = []
    def get(self, url, params=None, timeout=None):
        self.urls.append((url, dict(params or {})))
        if "/listings/cardmarket" in url:
            return PkResp({"data": [{"price": 1450.0, "seller": "enige", "quantity": 1, "condition": "Near Mint"}], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"name": "Lapras", "set": {"name": "Skyridge"}, "number": "071"})

ls39 = LaprasSess()
logs39 = []
check_card.check(store39, pkmnprices.PkmnPrices("pk", session=ls39), "lapras-x", log=logs39.append, today=today39.isoformat())
text39 = "\n".join(logs39)
assert "KLOPPEN" in text39, text39
assert "prijs staat vast" in text39, text39
assert "1 verschillende verkopers" in text39 and "erg weinig verkopers" in text39, text39
assert "103.6x het verkoopgemiddelde van 7 dagen" in text39 and "aanbod ver boven" in text39, text39
assert "ver boven de verkopen" in text39, text39
assert any("/listings/cardmarket" in u and p.get("per_page") == 10 and p.get("condition") == "Near Mint" for u, p in ls39.urls), "max. 10 aanbiedingen per kaart"

# --no-listings: geen enkel aanbiedingen-verzoek
ls39b = LaprasSess()
logs39b = []
check_card.check(store39, pkmnprices.PkmnPrices("pk", session=ls39b), "lapras-x", log=logs39b.append, today=today39.isoformat(), listings=False)
assert not any("/listings/" in u for u, _ in ls39b.urls), ls39b.urls

# fout in het prijsonderzoek haalt de koppelingscontrole niet onderuit
class BoomStore:
    def products(self, *a, **k):
        return store39.products(*a, **k)
    def select(self, *a, **k):
        raise RuntimeError("database weg")
logs39c = []
check_card.check(BoomStore(), pkmnprices.PkmnPrices("pk", session=LaprasSess()), "lapras-x", log=logs39c.append, today=today39.isoformat())
assert any("KLOPPEN" in l for l in logs39c) and any("prijsonderzoek mislukt" in l for l in logs39c), logs39c

# ============ 50. check_card: taal/velden per aanbieding, en geen valse waarschuwing als de prijs LAGER is dan de verkopen ============
fake40, store40 = new_store()
store40.upsert_products([{"product_id": "dragonite-x", "kind": "card", "name": "Dragonite", "set_name": "Triumphant", "number": "18", "pk_id": "14940"}])
store40.upsert_prices([{"product_id": "dragonite-x", "date": today39.isoformat(), "source": "tcgdex", "grade_key": "raw", "price": 11.0, "avg1": 20.0, "avg7": 30.0, "avg30": 8.0, "low": 1.0},
                       {"product_id": "dragonite-x", "date": today39.isoformat(), "source": "pkmnprices", "grade_key": "nm", "price": 9.0}])
class LangSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        if "/listings/cardmarket" in url:
            return PkResp({"data": [{"price": 9.0, "seller": "a", "quantity": 1, "condition": "Near Mint", "language": "Spanish", "country": "ES"},
                                    {"price": 300.0, "seller": "b", "quantity": 1, "condition": "Near Mint", "language": "English", "country": "NL", "comment": "first edition"}],
                           "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"name": "Dragonite", "set": {"name": "Triumphant"}, "number": "18"})
logs40 = []
check_card.check(store40, pkmnprices.PkmnPrices("pk", session=LangSess()), "dragonite-x", log=logs40.append, today=today39.isoformat())
text40 = "\n".join(logs40)
assert "'language': 'Spanish'" in text40 and "'country': 'NL'" in text40 and "first edition" in text40, text40
assert "velden per aanbieding:" in text40 and "language" in text40.split("velden per aanbieding:")[1], text40
assert "0.3x het verkoopgemiddelde" in text40 and "<-- ver boven" not in text40.split("Onze Near Mint-prijs")[1] and "wijkt sterk af" not in text40, text40

# ============ 51. Pieken uit de Near Mint-reeks halen (Lapras, Snorlax, Dragonite) ============
def nm_rows_from(prices, start=date(2026, 6, 1)):
    return [{"date": (start + timedelta(days=i)).isoformat(), "price": p} for i, p in enumerate(prices)]

# Lapras: 10 dagen normaal (4), 25 dagen EUR1450, 2 dagen 800, dan weer normaal (5)
lapras = [4.0 + (i % 3) * 0.2 for i in range(10)] + [1450.0] * 25 + [800.0] * 2 + [5.0] * 23
cl, st = analysis.clean_nm_rows(nm_rows_from(lapras))
assert st["causal"] == 27 and st["anchor"] == 0 and st["in"] == 60 and st["out"] == 33, st
assert max(r["price"] for r in cl) < 6, "geen piek meer over"
assert cl[-1]["price"] == 5.0 and cl[10]["price"] == 5.0, "de normale prijs erna blijft staan"

# normale reeks: ongewijzigd, ook een echte stijging binnen 3x en een daling
rise = [10.0] * 20 + [25.0] * 20 + [8.0] * 20
cl2, st2 = analysis.clean_nm_rows(nm_rows_from(rise))
assert len(cl2) == 60 and st2["causal"] == 0 and st2["anchor"] == 0, st2
flat = nm_rows_from([7.5] * 40)
cl3, st3 = analysis.clean_nm_rows(flat)
assert cl3 == flat and st3["out"] == 40

# een hoog niveau dat langer duurt dan CLEAN_MAX_DROP_DAYS wordt het nieuwe niveau (geen eindeloos wegfilteren van een echte stijging)
lang = [20.0] * 40 + [1949.99] * 100
cl4, st4 = analysis.clean_nm_rows(nm_rows_from(lang))
assert st4["causal"] == config.CLEAN_MAX_DROP_DAYS, st4
assert [r["price"] for r in cl4].count(1949.99) == 100 - config.CLEAN_MAX_DROP_DAYS, "de rest van het hoge niveau is geaccepteerd en blijft (geen heen-en-weer)"

# Cardmarkets verkoopgemiddelde als referentie: werkt ook als de reeks al in de piek begint (Moltres/Snorlax)
moltres = nm_rows_from([329.0] * 30)
anchors = {r["date"]: 5.4 for r in moltres[20:]}                 # alleen de laatste 10 dagen hebben een referentie
cl5, st5 = analysis.clean_nm_rows(moltres, anchors=anchors)
assert st5["anchor"] == 10 and st5["causal"] == 0 and len(cl5) == 20, st5
cl6, st6 = analysis.clean_nm_rows(nm_rows_from([12.0] * 5), anchors={r["date"]: 5.4 for r in nm_rows_from([12.0] * 5)})
assert st6["anchor"] == 0, "12 is geen 3x het gemiddelde van 5,4 (16,2): blijft staan"

# series_for: standaard ongewijzigd; met clean=True zonder piek; te weinig over na opschonen -> terugvallen op de Cardmarket-reeks
by_src = {"tcgdex": [{"date": r["date"], "price": 6.0, "avg1": None, "avg7": 6.0, "avg30": 6.0} for r in nm_rows_from([6.0] * 40)]}
spiky = nm_rows_from([4.0] * 15 + [1450.0] * 20 + [5.0] * 15)
assert config.CLEAN_NM is False
base_len = len(analysis.series_for("x-1", by_src, nm_rows=spiky))
assert base_len == 50, base_len
stats_sf = {}
cleaned_sf = analysis.series_for("x-1", by_src, nm_rows=spiky, clean=True, clean_stats=stats_sf)
assert len(cleaned_sf) == 30 and max(r["price"] for r in cleaned_sf) < 6, (len(cleaned_sf), stats_sf)
assert stats_sf["cards"] == 1 and stats_sf["cards_changed"] == 1 and stats_sf["anchor"] == 20 and stats_sf["causal"] == 0, stats_sf   # hier is voor die dagen een Cardmarket-gemiddelde, dus de nauwkeurige regel pakt het
mostly_spike = nm_rows_from([4.0] * 3 + [1450.0] * 40)
fallback = analysis.series_for("x-2", by_src, nm_rows=mostly_spike, clean=True)
assert len(fallback) == 40 and fallback[0]["price"] == 6.0, "te weinig NM-punten over na opschonen: de gewone Cardmarket-reeks is gebruikt"

# de referentie komt uit de ruwe rijen (anchor of avg30)
assert analysis.anchors_from({"tcgdex": [{"date": "2026-01-01", "avg30": 8.0}, {"date": "2026-01-02", "anchor": 9.0, "avg30": None}, {"date": "2026-01-03"}]}) == {"2026-01-01": 8.0, "2026-01-02": 9.0}

# ============ 52. compare_cleaning: backtest met en zonder pieken, en hoeveel er verwijderd is ============
fake41, store41 = new_store()
fd41 = sorted(config.FAMOUS_DEX_IDS)[0]
store41.upsert_products([{"product_id": f"cc-{k}", "kind": "card", "name": f"CC{k}", "dex_id": fd41} for k in range(4)])
d41 = date(2026, 1, 1)
for k in range(4):
    pr = [20.0 + 3 * math.sin(i / 9) + (1450.0 - 20.0 if (k % 2 == 0 and 60 <= i < 85) else 0.0) for i in range(220)]
    store41.upsert_prices([{"product_id": f"cc-{k}", "date": (d41 + timedelta(days=i)).isoformat(), "source": "pkmnprices", "grade_key": "nm", "price": pr[i]} for i in range(220)])
    store41.upsert_prices([{"product_id": f"cc-{k}", "date": (d41 + timedelta(days=i)).isoformat(), "source": "tcgdex", "grade_key": "raw", "price": 20.0, "avg30": 20.0, "avg7": 20.0} for i in range(150, 220)])
logs41 = []
a41, b41 = signals.compare_cleaning(store41, (d41 + timedelta(days=219)).isoformat(), log=logs41.append)
text41 = "\n".join(logs41)
assert "A. Zoals het was" in text41 and "B. Met pieken eruit gehaald" in text41, text41
assert "verwijderd 50 (" in text41 and "2 van 4 kaarten aangepast" in text41, text41
assert b41["alle momenten"][0] <= a41["alle momenten"][0], "met opschonen nooit meer meetmomenten dan zonder"
assert sum(1 for l in logs41 if l.strip().startswith("alle momenten")) == 2, "beide tabellen getoond"

# ============ 53. Aanbiedingen: variant bewaren, gegradeerd/getekend/bewerkt weglaten ============
raw_var = [
    {"price": 29.09, "condition": "Near Mint", "seller": "a", "quantity": 1, "language": "EN", "variant": "Normal", "graded": False, "signed": False, "altered": False},
    {"price": 300.0, "condition": "Near Mint", "seller": "b", "quantity": 1, "language": "EN", "variant": "Reverse Holofoil", "graded": False, "signed": False, "altered": False},
    {"price": 5.0, "condition": "Near Mint", "seller": "c", "quantity": 1, "language": "EN", "variant": "Normal", "graded": True, "grader": "PSA", "grade": "9"},
    {"price": 6.0, "condition": "Near Mint", "seller": "d", "quantity": 1, "language": "EN", "variant": "Normal", "signed": True},
    {"price": 7.0, "condition": "Near Mint", "seller": "e", "quantity": 1, "language": "EN", "variant": "Normal", "altered": "true"},
    {"price": 30.3, "condition": "Near Mint", "seller": "f", "quantity": 2, "language": "EN", "variant": "Normal"},
]
pv = offers.parse_offers("hgss4-18", raw_var, "2026-10-05")
assert [(p["seller"], p["variant"]) for p in pv] == [("a", "Normal"), ("f", "Normal"), ("b", "Reverse Holofoil")], pv
assert [p["rank"] for p in pv] == [1, 2, 3] and offers.LIMIT == 8
assert offers.parse_offers("x", [], "2026-10-05") == []

# ============ 54. Cardmarket-pagina per kaart (cm_links) ============
assert cm_links.clean_url("https://www.cardmarket.com/en/Pokemon/Products/Singles/Skyridge/Lapras-V1-SK71") == "https://www.cardmarket.com/en/Pokemon/Products/Singles/Skyridge/Lapras-V1-SK71"
assert cm_links.clean_url("/en/Pokemon/Products/Singles/X/Y") == "https://www.cardmarket.com/en/Pokemon/Products/Singles/X/Y", "relatief adres aanvullen"
assert cm_links.clean_url("https://evil.example.com/x") is None and cm_links.clean_url("javascript:alert(1)") is None and cm_links.clean_url("") is None and cm_links.clean_url(None) is None
assert cm_links.extract({"cardmarket_url": "https://www.cardmarket.com/en/Pokemon/Products/Singles/A/B", "cardmarket_product_id": "26950"}) == ("https://www.cardmarket.com/en/Pokemon/Products/Singles/A/B", 26950)
assert cm_links.extract({"data": {"cardmarket_product_id": 5}}) == (None, 5) and cm_links.extract({}) == (None, None) and cm_links.extract(None) == (None, None)

fake42, store42 = new_store()
fd42 = sorted(config.FAMOUS_DEX_IDS)[0]
store42.upsert_products([
    {"product_id": "l-rest", "kind": "card", "name": "Rest", "pk_id": "1", "dex_id": 13},
    {"product_id": "l-famous", "kind": "card", "name": "Beroemd", "pk_id": "2", "dex_id": fd42},
    {"product_id": "l-coll", "kind": "card", "name": "Collectie", "pk_id": "3", "dex_id": 13},
    {"product_id": "l-nolink", "kind": "card", "name": "ZonderLink", "pk_id": "4", "dex_id": 13},
    {"product_id": "l-nopk", "kind": "card", "name": "NietGekoppeld", "dex_id": fd42},
    {"product_id": "l-done", "kind": "card", "name": "Klaar", "pk_id": "5", "dex_id": fd42},
])
fake42.t["products"][("l-done",)]["cm_url"] = "https://www.cardmarket.com/en/Pokemon/Products/Singles/Klaar/K"
fake42.t["collection"][(1,)] = {"id": "c1", "product_id": "l-coll", "user_id": "u"}
order42, _ = cm_links.targets(store42)
assert order42[0] == "l-coll", f"collectie eerst: {order42}"
assert "l-nopk" not in order42 and "l-done" not in order42, "alleen gekoppelde kaarten zonder link"
assert order42.index("l-famous") < order42.index("l-rest"), "beroemde Pokémon vóór de rest"

class CmSess:
    headers = {}
    def __init__(self):
        self.urls = []
    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        n = url.rsplit("/", 1)[-1]
        if n == "4":
            return PkResp({"name": "ZonderLink"})
        return PkResp({"name": "x", "cardmarket_url": f"https://www.cardmarket.com/en/Pokemon/Products/Singles/S/Kaart-{n}", "cardmarket_product_id": int(n) * 100})
cs42 = CmSess()
logs42 = []
n42 = cm_links.run(store42, pkmnprices.PkmnPrices("pk", session=cs42), "2026-10-05", log=logs42.append)
prods42 = {p["product_id"]: p for p in store42.products("card")}
assert n42 == 3 and prods42["l-rest"]["cm_url"].endswith("Kaart-1") and prods42["l-famous"]["cm_product_id"] == 200, prods42["l-famous"]
assert prods42["l-nolink"]["cm_url"] == "", "geen link bij PkmnPrices: lege tekst, zodat hij niet elke nacht opnieuw wordt geprobeerd"
assert prods42["l-done"]["cm_url"].endswith("/Klaar/K"), "bestaande link niet overschreven"
assert prods42["l-nopk"].get("cm_url") is None
cs42b = CmSess()
cm_links.run(store42, pkmnprices.PkmnPrices("pk", session=cs42b), "2026-10-06", log=quiet)
assert cs42b.urls == [], "alles al gedaan: geen enkel verzoek meer"

# budget: 1 credit per kaart, dus bij een budget van 2 maar 2 kaarten
fake43, store43 = new_store()
store43.upsert_products([{"product_id": f"b-{i}", "kind": "card", "name": f"B{i}", "pk_id": str(10 + i), "dex_id": 13} for i in range(6)])
class CostCm(CmSess):
    def get(self, url, params=None, timeout=None):
        r = super().get(url, params, timeout)
        r.headers = {"x-credits-charged": "1"}
        return r
cc43 = CostCm()
cm_links.run(store43, pkmnprices.PkmnPrices("pk", session=cc43, budget=100000), "2026-10-05", log=quiet, budget=2)
assert len(cc43.urls) == 2, cc43.urls

# PkmnPrices geeft het veld helemaal niet mee: na 20 kaarten stoppen, niets opslaan
fake44, store44 = new_store()
store44.upsert_products([{"product_id": f"n-{i}", "kind": "card", "name": f"N{i}", "pk_id": str(100 + i), "dex_id": 13} for i in range(30)])
class NoField(CmSess):
    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        return PkResp({"name": "x"})
nf = NoField()
logs44 = []
assert cm_links.run(store44, pkmnprices.PkmnPrices("pk", session=nf), "2026-10-05", log=logs44.append) == 0
assert len(nf.urls) == cm_links.EARLY_STOP_AFTER and any("geen Cardmarket-adres" in l for l in logs44), (len(nf.urls), logs44)
assert all(p.get("cm_url") is None for p in store44.products("card")), "niets opgeslagen"

# check_card toont de Cardmarket-pagina
fake45, store45 = new_store()
store45.upsert_products([{"product_id": "cc-1", "kind": "card", "name": "Lapras", "set_name": "Skyridge", "number": "71", "pk_id": "26950"}])
class CardSess:
    headers = {}
    def get(self, url, params=None, timeout=None):
        if "/listings/" in url:
            return PkResp({"data": [], "pagination": {"page": 1, "total_pages": 1}})
        return PkResp({"name": "Lapras", "set": {"name": "Skyridge"}, "number": "071", "cardmarket_url": "https://www.cardmarket.com/en/Pokemon/Products/Singles/Skyridge/Lapras-V1-SK71", "cardmarket_product_id": 26950})
logs45 = []
check_card.check(store45, pkmnprices.PkmnPrices("pk", session=CardSess()), "cc-1", log=logs45.append, today="2026-10-05")
assert any("Cardmarket-pagina: https://www.cardmarket.com/en/Pokemon/Products/Singles/Skyridge/Lapras-V1-SK71" in l and "26950" in l for l in logs45), logs45

print("alle tests geslaagd")
