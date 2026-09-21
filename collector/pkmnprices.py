"""PkmnPrices (pkmnprices.com): Cardmarket-prijzen per conditie, prijshistorie tot een jaar, sealed met plaatjes.

Voorlopig alleen een TEST (probe): hij laat zien wat de dienst teruggeeft, zodat we de koppeling erna goed kunnen bouwen.
Gratis plan: alleen Engelse kaarten in dollars. Euro's (Cardmarket), historie en sealed zitten in Pro ($14,99 per maand).
"""
import time

import requests

BASE = "https://api.pkmnprices.com/v1"
MIN_INTERVAL = 1.05        # het plan staat 60 verzoeken per minuut toe


class PkmnPrices:
    def __init__(self, key, session=None, budget=15000):
        self.s = session or requests.Session()
        self.s.headers.update({"X-API-Key": key, "User-Agent": "pokedeals/2.0"})
        self.credits = 0           # credits die deze run heeft verbruikt (er wordt per teruggegeven rij gerekend)
        self.budget = budget
        self._last = 0.0

    def over_budget(self):
        return self.credits >= self.budget

    def call(self, path, params=None):
        """Eén verzoek met wachttijd (60 per minuut), telt credits en probeert het opnieuw bij 429. Geeft de 'data' terug."""
        for _ in range(4):
            wait = MIN_INTERVAL - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            status, body, headers = self.get(path, params)
            self._last = time.time()
            try:
                self.credits += int(float(headers.get("x-credits-charged") or 0))
            except (TypeError, ValueError):
                pass
            if status == 429:
                time.sleep(15)
                continue
            if status >= 400:
                raise RuntimeError(f"PkmnPrices {path}: {status} {str(body)[:160]}")
            return body
        raise RuntimeError(f"PkmnPrices {path}: blijft 429 geven")

    def list_all(self, path, params=None, per_page=100, max_pages=200):
        """Alle pagina's van een lijst (kosten: één credit per teruggegeven rij)."""
        out, page = [], 1
        while page <= max_pages and not self.over_budget():
            body = self.call(path, {**(params or {}), "per_page": per_page, "page": page})
            out += _rows(body)
            total_pages = ((body or {}).get("pagination") or {}).get("total_pages") if isinstance(body, dict) else None
            if not total_pages or page >= total_pages:
                break
            page += 1
        return out

    def detail(self, path, params=None):
        body = self.call(path, params)
        d = body.get("data", body) if isinstance(body, dict) else {}
        return d if isinstance(d, dict) else {}

    def get(self, path, params=None):
        r = self.s.get(BASE + path, params=params, timeout=60)
        try:
            body = r.json()
        except ValueError:
            body = (r.text or "")[:300]
        return r.status_code, body, r.headers


def _rows(body):
    if isinstance(body, dict):
        for k in ("data", "results", "items", "cards", "sealed"):
            if isinstance(body.get(k), list):
                return body[k]
    return body if isinstance(body, list) else []


GUIDE_KEYS = ("trend", "avg", "low", "avg1", "avg7", "avg30", "trend-holo", "low-holo", "avg30-holo")


def _guide_line(guide, cm_id):
    row = (guide or {}).get(cm_id)
    return {k: row.get(k) for k in GUIDE_KEYS if row.get(k) is not None} if row else None


def probe(pk, guide=None):
    """Test met of zonder Pro. Vergelijkt PkmnPrices-euro's automatisch met de officiële Cardmarket-prijslijst."""
    short = lambda x, n=700: str(x)[:n]
    seen = {}

    def call(label, path, params=None):
        try:
            status, body, headers = pk.get(path, params)
        except Exception as e:
            print(f"{label}: FOUT {e}")
            return None, None
        for k, v in headers.items():
            if k.lower() in ("x-credits-limit", "x-credits-remaining", "x-rate-limit", "x-rate-remaining"):
                seen[k.lower()] = v
        print(f"{label}: status {status}, credits {headers.get('x-credits-charged', '?')}")
        return status, body

    def detail(cid, **params):
        status, body = call(f"card {cid}", f"/cards/{cid}", params or None)
        d = body.get("data", body) if isinstance(body, dict) else {}
        return status, (d if isinstance(d, dict) else {}), body

    print("=== PkmnPrices ===")
    print("--- 1. Kaarten zoeken (max. 2) ---")
    status, body = call("cards", "/cards", {"name": "charizard ex", "per_page": 2})
    rows = _rows(body)
    if not rows:
        print("ruw:", short(body))
        return
    cid = rows[0].get("id")
    print("eerste kaart:", short(rows[0], 500))

    print("\n--- 2. Eén kaart: koppeling met Cardmarket en prijzen ---")
    status, d, _ = detail(cid)
    cm_id = d.get("cardmarket_product_id")
    print("Cardmarket-nummer:", cm_id, "|", d.get("cardmarket_url"))
    for p in (d.get("prices") or [])[:6]:
        print("  ", short(p, 200))
    print("Officiële Cardmarket-prijslijst voor dit nummer:", _guide_line(guide, cm_id))

    print("\n--- 3. Euro's (Cardmarket) voor dezelfde kaart ---")
    status, d2, body = detail(cid, currency="eur")
    if status == 200:
        for p in (d2.get("prices") or [])[:14]:
            print("  ", short(p, 220))
        print("Ter vergelijking, officiële prijslijst:", _guide_line(guide, cm_id))
    else:
        print("melding:", short(body, 250))

    print("\n--- 4. Hoeveel kaarten hebben een Cardmarket-nummer? (10 kaarten) ---")
    status, body = call("lijst", "/cards", {"name": "pikachu", "per_page": 10})
    ids = [r.get("id") for r in _rows(body)][:10]
    mapped = 0
    for i in ids:
        _, dd, _ = detail(i)
        mapped += 1 if dd.get("cardmarket_product_id") else 0
    print(f"{mapped} van {len(ids)} kaarten hebben een Cardmarket-nummer")

    print("\n--- 5. Sets ---")
    status, body = call("sets", "/sets", {"per_page": 2})
    print("ruw:", short(_rows(body)[:2] or body, 400))

    print("\n--- 6. Sealed ---")
    status, body = call("sealed", "/sealed", {"per_page": 3})
    srows = _rows(body)
    print("ruw:", short(srows[:2] or body, 700))
    if srows:
        sid = srows[0].get("id")
        status, body = call(f"sealed {sid}", f"/sealed/{sid}")
        sd = body.get("data", body) if isinstance(body, dict) else {}
        if isinstance(sd, dict):
            print("velden:", sorted(sd.keys()))
            sm = sd.get("cardmarket_product_id")
            print("Cardmarket-nummer:", sm, "| officiële prijslijst:", _guide_line(guide, sm))
            for p in (sd.get("prices") or [])[:6]:
                print("  ", short(p, 200))
        status, body = call("sealed historie", f"/sealed/{sid}/prices/history", {"currency": "eur", "period": "30d", "limit": 5})
        print("ruw:", short(body, 600))

    print("\n--- 7. Prijshistorie kaart (Cardmarket, Near Mint, 30 dagen) ---")
    status, body = call("history", f"/cards/{cid}/prices/history", {"currency": "eur", "period": "30d", "condition": "Near Mint", "limit": 40})
    hrows = _rows(body)
    print(f"{len(hrows)} rijen; paginering: {short(body.get('pagination') if isinstance(body, dict) else None, 200)}")
    print("eerste 3:", short(hrows[:3] or body, 600))

    print("\nlimieten:", seen)
