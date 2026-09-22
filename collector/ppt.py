"""PokemonPriceTracker (betaald API-plan): prijshistorie en gegradeerde prijzen van kaarten (TCGplayer/eBay, dollars).

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


def _int(x):
    try:
        v = int(float(x))
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


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


def clean_card_name(name):
    """'Charizard ex - 125/197' -> 'Charizard ex'; '(Reverse Holo)' e.d. verdwijnt ook."""
    n = re.sub(r"\s*-\s*[A-Za-z]{0,5}\d+(?:/\d+)?\s*$", "", name or "")
    return re.sub(r"\s*\([^)]*\)\s*", " ", n).strip()


DATE_KEYS = ("date", "day", "timestamp", "t", "d")
PRICE_KEYS = ("market", "marketPrice", "unopenedPrice", "price", "avg", "average", "p", "close")


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
GRADE_PRICE_KEYS = ("smartMarketPrice", "marketPrice7Day", "medianPrice", "averagePrice", "average", "avg", "price", "market")


def norm_grade(label):
    m = GRADER_RE.match(str(label))
    if not m:
        return None
    co, whole, frac = m.group(1).upper(), m.group(2), m.group(3)
    return f"{co}-{whole}" + (f".{frac}" if frac else "")


def _grade_price(v):
    if isinstance(v, dict):
        sm = v.get("smartMarketPrice")
        if isinstance(sm, dict) and _num(sm.get("price")):
            return _num(sm["price"])
        for k in GRADE_PRICE_KEYS:
            x = v.get(k)
            x = x.get("price") if isinstance(x, dict) else x      # smartMarketPrice is een blokje met 'price' erin
            if _num(x):
                return _num(x)
        return None
    return _num(v)


def extract_graded(ebay):
    out = {}
    if isinstance(ebay, dict) and isinstance(ebay.get("salesByGrade"), dict):   # zo levert PokemonPriceTracker het echt
        ebay = ebay["salesByGrade"]
    if isinstance(ebay, dict) and isinstance(ebay.get("salesByGrade"), dict):
        ebay = ebay["salesByGrade"]
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


def _preferred_history(h):
    """priceHistory.conditions.<conditie>.history: kies Near Mint (de conditie waar Cardmarket-kopers naar kijken)."""
    conds = h.get("conditions") if isinstance(h, dict) else None
    if isinstance(conds, dict) and conds:
        return conds.get("Near Mint") or next(iter(conds.values()))
    return h


def _card_history(ph):
    """Kaarten leveren historie per conditie: {'conditions': {'Near Mint': {'history': [...]}}}. We nemen Near Mint."""
    conds = ph.get("conditions") if isinstance(ph, dict) else None
    if isinstance(conds, dict) and conds:
        return extract_history(conds.get("Near Mint") or next(iter(conds.values())))
    return extract_history(ph)


def parse_item(d, kind="card"):
    """Genormaliseerd antwoord voor één kaart of sealed product."""
    price = _num(_first(d, "prices.market", "prices.marketPrice", "unopenedPrice", "marketPrice", "market", "price"))
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
        "history": extract_history(_preferred_history(d.get("priceHistory") or d.get("history") or {})),
        "graded": extract_graded(d.get("ebay") or d.get("graded")),
        "listings": _int(_first(d, "prices.listings", "listings", "totalListings")),
        "sellers": _int(_first(d, "prices.sellers", "sellers", "totalSellers")),
        "recent_sales": _int(_first(d, "prices.recentSales", "recentSales")),
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

    def _paged(self, path, params, limit=100, max_pages=30):
        """Haalt alle pagina's op. Stopt als er niets nieuws bijkomt (voor het geval 'offset' genegeerd wordt)."""
        out, seen, offset = [], set(), 0
        for _ in range(max_pages):
            data = self._get(path, {**params, "limit": limit, "offset": offset})
            items = _items(data)
            fresh = [d for d in items if str(d.get("id") or d.get("tcgPlayerId") or id(d)) not in seen]
            for d in fresh:
                seen.add(str(d.get("id") or d.get("tcgPlayerId") or id(d)))
            out += fresh
            more = ((data or {}).get("metadata") or {}).get("hasMore") if isinstance(data, dict) else None
            if more is None:
                more = len(items) >= limit
            if not fresh or not more or self.over_budget():
                break
            offset += len(items)
        return out

    def sets(self):
        out = []
        for d in self._paged("/sets", {"sortBy": "releaseDate", "sortOrder": "desc"}):
            # let op: 'id' is een interne code; voor de sealed-zoekopdracht heb je de leesbare code ('tcgPlayerId') nodig
            sid = _first(d, "tcgPlayerId", "slug", "setId", "code", "id")
            if sid:
                out.append({"set_id": str(sid), "name": _first(d, "name", "setName"),
                            "release_date": _to_date(_first(d, "releaseDate", "release_date")),
                            "card_count": d.get("cardCount")})
        return out

    def _params(self, base, history_days=None, ebay=False):
        p = dict(base)
        if history_days:
            p.update({"includeHistory": "true", "days": history_days})
        if ebay:
            p["includeEbay"] = "true"
        return p

    def cards_in_set(self, set_id, history_days=None):
        data = self._get("/cards", self._params({"set": set_id, "fetchAllInSet": "true"}, history_days))
        return [parse_item(d) for d in _items(data)]

    def card(self, ppt_id, history_days=None, ebay=False):
        data = self._get("/cards", self._params({"tcgPlayerId": ppt_id}, history_days, ebay))
        items = [parse_item(d) for d in _items(data)]
        return items[0] if items else None

    def probe(self):
        """Kleine test (ca. 6 credits): sets, een set-opvraag en een kaart met historie en gegradeerde prijzen."""
        short = lambda d, n=900: str(d)[:n]
        today = date.today().isoformat()
        summary = lambda it: {k: (f"{len(v)} punten" if k == "history" else v) for k, v in it.items() if k != "image"}
        print("=== PokemonPriceTracker 1. Sets (1 credit) ===")
        found = []
        try:
            found = self.sets()
            print(f"{len(found)} sets; nieuwste: {found[:2]}")
        except Exception as e:
            print("FOUT:", e)

        print("\n=== 2. Kaarten van één set opvragen (limit=2, met historie) ===")
        try:
            released = [x for x in found if x["release_date"] and x["release_date"] <= today and (x.get("card_count") or 0) > 0]
            if released:
                raw = self._get("/cards", {"set": released[0]["set_id"], "limit": 2, "includeHistory": "true", "days": 3})
                print("set:", released[0])
                print("metadata:", short((raw or {}).get("metadata"), 700))
                for it in [parse_item(d) for d in _items(raw)][:2]:
                    print("herkend:", summary(it))
        except Exception as e:
            print("FOUT:", e)

        print("\n=== 3. Kaart met historie en gegradeerde prijzen (max. 3 credits) ===")
        try:
            raw = self._get("/cards", {"tcgPlayerId": "96392", "includeHistory": "true", "includeEbay": "true", "days": 3})
            d = (_items(raw) or [{}])[0]
            print("ebay ruw:", short(d.get("ebay"), 700))
            print("herkend:", summary(parse_item(d)))
        except Exception as e:
            print("FOUT:", e)

        print("\n=== 4. Aanbod (listings/sellers) op een paar kaarten ===")
        try:
            test_ids = ["96392", "490294", "624679"]
            found_any = False
            for tid in test_ids:
                raw = self._get("/cards", {"tcgPlayerId": tid})
                d = (_items(raw) or [{}])[0]
                it = parse_item(d)
                print(f"  {tid}: listings={it['listings']}, sellers={it['sellers']}, recent_sales={it['recent_sales']}, prijs=${it['price_usd']}")
                print("    ruwe 'prices'-sleutels:", sorted((d.get('prices') or {}).keys()))
                if it["listings"] is not None or it["sellers"] is not None:
                    found_any = True
            print("wel/geen aanbod-getallen gevonden:", "JA" if found_any else "NEE, geen van deze velden zat erbij")
            print("(let op: dit is één totaal voor de kaart, niet per conditie/graad, voor zover hier te zien)")
        except Exception as e:
            print("FOUT:", e)

        print(f"\ncredits verbruikt: {self.credits}; nog over vandaag: {self.remaining}")
