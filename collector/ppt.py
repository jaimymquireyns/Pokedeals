"""PokemonPriceTracker (betaald API-plan): sealed, graded en prijshistorie.

Let op: de exacte vorm van de antwoorden kon ik niet live testen. De parsers hieronder zoeken daarom op meerdere
plekken naar velden en negeren wat ze niet snappen. Met `python run.py --probe-ppt` zie je de echte structuur en
of de velden gevonden worden.
"""
import re
import time
from datetime import date, datetime, timezone

import requests

import config


# ---------- kleine hulpjes ----------
def _dig(d, path):
    cur = d
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def _first(d, *paths):
    for p in paths:
        v = _dig(d, p)
        if v is not None and v != "":
            return v
    return None


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _items(data):
    if isinstance(data, dict):
        data = data.get("data", data)
    if isinstance(data, dict):
        return [data]
    return [x for x in (data or []) if isinstance(x, dict)]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def norm_number(n):
    if n is None:
        return None
    return (str(n).split("/")[0].strip().lstrip("0") or "0").lower()


DATE_KEYS = ("date", "day", "timestamp", "t", "d")
PRICE_KEYS = ("market", "marketPrice", "price", "avg", "average", "p", "close")


def _to_date(v):
    if isinstance(v, str):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", v)
        return m.group(1) if m else None
    if isinstance(v, (int, float)) and v > 1e9:
        secs = v / 1000 if v > 1e11 else v
        return datetime.fromtimestamp(secs, tz=timezone.utc).date().isoformat()
    return None


def extract_history(obj):
    """Zoekt de langste reeks (datum, prijs) ergens in het antwoord."""
    best = []

    def point(it):
        dt = next((_to_date(it[k]) for k in DATE_KEYS if k in it and _to_date(it[k])), None)
        pr = next((_num(it[k]) for k in PRICE_KEYS if k in it and _num(it[k])), None)
        return (dt, pr) if dt and pr else None

    def walk(x):
        nonlocal best
        if isinstance(x, list):
            pts = [p for p in (point(it) for it in x if isinstance(it, dict)) if p]
            if len(pts) > len(best):
                best = pts
            for it in x:
                walk(it)
        elif isinstance(x, dict):
            pts = []
            for k, v in x.items():
                dt = _to_date(k)
                if not dt:
                    continue
                if isinstance(v, dict):
                    pr = next((_num(v[kk]) for kk in PRICE_KEYS if kk in v and _num(v[kk])), None)
                else:
                    pr = _num(v)
                if pr:
                    pts.append((dt, pr))
            if len(pts) > len(best):
                best = pts
            for v in x.values():
                walk(v)

    walk(obj)
    return sorted({d: p for d, p in best}.items())


GRADER_RE = re.compile(r"^\s*(psa|bgs|cgc|sgc)[\s_\-]*(\d{1,2})(?:[._](\d))?\s*$", re.I)
GRADE_PRICE_KEYS = ("smartMarketPrice", "avg", "average", "averagePrice", "medianPrice", "marketPrice7Day", "price", "market")


def norm_grade(label):
    m = GRADER_RE.match(str(label))
    if not m:
        return None
    co, whole, frac = m.group(1).upper(), m.group(2), m.group(3)
    return f"{co}-{whole}" + (f".{frac}" if frac else "")


def _grade_price(v):
    if isinstance(v, dict):
        return next((_num(v[k]) for k in GRADE_PRICE_KEYS if k in v and _num(v[k])), None)
    return _num(v)


def extract_graded(ebay):
    out = {}
    if isinstance(ebay, dict):
        for k, v in ebay.items():
            if str(k).lower() in ("psa", "bgs", "cgc", "sgc") and isinstance(v, dict):
                for gk, gv in v.items():
                    g, p = norm_grade(f"{k}{gk}"), _grade_price(gv)
                    if g and p:
                        out[g] = p
                continue
            g, p = norm_grade(k), _grade_price(v)
            if g and p:
                out[g] = p
    elif isinstance(ebay, list):
        for row in ebay:
            if not isinstance(row, dict):
                continue
            label = row.get("grade") or row.get("gradeLabel") or ""
            if row.get("grader") and not GRADER_RE.match(str(label)):
                label = f"{row['grader']}{label}"
            g, p = norm_grade(label), _grade_price(row)
            if g and p:
                out[g] = p
    return out


def parse_item(d, kind="card"):
    """Genormaliseerd antwoord voor één kaart of sealed product."""
    price = _num(_first(d, "prices.market", "prices.marketPrice", "marketPrice", "market", "price"))
    if price is None and isinstance(d.get("variants"), dict):
        for v in d["variants"].values():
            price = _num(_first(v, "marketPrice", "prices.market", "market")) if isinstance(v, dict) else None
            if price:
                break
    tid = _first(d, "tcgPlayerId", "id")
    return {
        "ppt_id": str(tid) if tid is not None else None,
        "name": _first(d, "name", "productName"),
        "set_name": _first(d, "setName", "set.name"),
        "set_id": _first(d, "setId", "set.id"),
        "number": _first(d, "cardNumber", "number"),
        "rarity": _first(d, "rarity"),
        "product_type": _first(d, "productType"),
        "image": _first(d, "imageUrl", "image", "images.small"),
        "price_usd": price,
        "low_usd": _num(_first(d, "prices.low", "lowPrice", "prices.lowPrice")),
        "history": extract_history(d.get("priceHistory") or d.get("history") or {}),
        "graded": extract_graded(d.get("ebay") or d.get("graded")),
    }


class PPT:
    name = "ppt"

    def __init__(self, key, session=None, budget=None, log=print):
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {key}", "User-Agent": "pokedeals/2.0"})
        self.credits = 0
        self.remaining = None      # credits die vandaag nog over zijn volgens PokemonPriceTracker
        self.blocked = False       # True zodra de API definitief weigert (credits op, geen toegang)
        self.budget = budget or config.PPT_DAILY_BUDGET
        self.log = log

    def over_budget(self):
        """Stopt ruim voordat het dagtegoed op is, zodat ook het gratis plan (100 credits) veilig blijft."""
        return self.blocked or self.credits >= self.budget or (self.remaining is not None and self.remaining <= 5)

    def _get(self, path, params=None):
        for _ in range(3):
            r = self.s.get(config.PPT_BASE + path, params=params, timeout=90)
            rem = r.headers.get("X-RateLimit-Daily-Remaining")
            if rem is not None:
                try:
                    self.remaining = int(float(rem))
                except ValueError:
                    pass
            if r.status_code == 429:
                if "credit" in (r.text or "").lower() or "daily" in (r.text or "").lower() or (self.remaining is not None and self.remaining <= 0):
                    self.blocked = True
                    raise RuntimeError("PokemonPriceTracker: het dagtegoed aan credits is op (gratis plan: 100 per dag)")
                try:
                    wait = int(r.headers.get("Retry-After", 20))
                except ValueError:
                    wait = 20
                time.sleep(min(wait, 90))
                continue
            if r.status_code in (401, 403):
                self.blocked = True
                raise RuntimeError(f"PokemonPriceTracker: geen toegang ({r.status_code}). Controleer de API key en of je plan dit toestaat.")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            used = r.headers.get("X-API-Calls-Consumed") or r.headers.get("X-RateLimit-Cost")
            if used is None:
                try:
                    used = r.json()["metadata"]["apiCallsConsumed"]["total"]
                except Exception:
                    used = 0
            self.credits += int(float(used or 0))
            return r.json()
        self.blocked = True
        raise RuntimeError("PokemonPriceTracker: blijft 429 geven (te veel verzoeken)")

    def sets(self):
        out = []
        for d in _items(self._get("/sets", {"sortBy": "releaseDate", "sortOrder": "desc"})):
            sid = _first(d, "setId", "id", "slug", "code")
            if sid:
                out.append({"set_id": str(sid), "name": _first(d, "name", "setName"),
                            "release_date": _to_date(_first(d, "releaseDate", "release_date"))})
        return out

    def _params(self, base, history_days=None, ebay=False):
        p = dict(base)
        if history_days:
            p.update({"includeHistory": "true", "days": history_days})
        if ebay:
            p["includeEbay"] = "true"
        return p

    def sealed_for_set(self, set_id, history_days=None):
        data = self._get("/sealed-products", self._params({"set": set_id}, history_days))
        return [parse_item(d, "sealed") for d in _items(data)]

    def sealed(self, ppt_id, history_days=None):
        data = self._get("/sealed-products", self._params({"tcgPlayerId": ppt_id}, history_days))
        items = [parse_item(d, "sealed") for d in _items(data)]
        return items[0] if items else None

    def cards_in_set(self, set_id, history_days=None):
        data = self._get("/cards", self._params({"set": set_id, "fetchAllInSet": "true"}, history_days))
        return [parse_item(d) for d in _items(data)]

    def card(self, ppt_id, history_days=None, ebay=False):
        data = self._get("/cards", self._params({"tcgPlayerId": ppt_id}, history_days, ebay))
        items = [parse_item(d) for d in _items(data)]
        return items[0] if items else None

    def probe(self):
        """Kleine test (ca. 6 credits): toont de ruwe antwoorden en wat de parsers eruit halen."""
        def short(d, n=900):
            return str(d)[:n]

        def summary(it):
            return {k: (v if k not in ("history", "graded") else (f"{len(v)} punten" if k == "history" else v)) for k, v in it.items()}

        print("=== 1. Sets (1 credit) ===")
        found = []
        try:
            print("ruw:", short(self._get("/sets", {"sortBy": "releaseDate", "sortOrder": "desc", "limit": 3}), 500))
            found = self.sets()
            print("herkend:", len(found), "sets; nieuwste:", found[:2])
        except Exception as e:
            print("FOUT:", e)

        print("\n=== 2. Sealed producten (max. 2 credits + historie) ===")
        try:
            items = []
            if found:
                raw = self._get("/sealed-products", {"set": found[0]["set_id"], "includeHistory": "true", "days": 3, "limit": 2})
                print("ruw:", short(raw))
                items = [parse_item(d, "sealed") for d in _items(raw)]
            if not items:
                print("(geen resultaat met de set-id; nu zoeken op naam)")
                raw = self._get("/sealed-products", {"search": "booster box", "includeHistory": "true", "days": 3, "limit": 2})
                print("ruw:", short(raw))
                items = [parse_item(d, "sealed") for d in _items(raw)]
            for it in items[:2]:
                print("herkend:", summary(it))
        except Exception as e:
            print("FOUT:", e)

        print("\n=== 3. Kaart met historie en gegradeerde prijzen (max. 3 credits) ===")
        try:
            raw = self._get("/cards", {"search": "charizard ex", "limit": 1, "includeHistory": "true", "includeEbay": "true", "days": 3})
            print("ruw:", short(raw, 1400))
            for it in [parse_item(d) for d in _items(raw)][:1]:
                print("herkend:", summary(it))
        except Exception as e:
            print("FOUT:", e)

        print(f"\ncredits verbruikt: {self.credits}; nog over vandaag: {self.remaining}")
