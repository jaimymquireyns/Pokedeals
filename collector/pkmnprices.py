"""PkmnPrices (pkmnprices.com): Cardmarket-prijzen per conditie, prijshistorie tot een jaar, sealed met plaatjes.

Voorlopig alleen een TEST (probe): hij laat zien wat de dienst teruggeeft, zodat we de koppeling erna goed kunnen bouwen.
Gratis plan: alleen Engelse kaarten in dollars. Euro's (Cardmarket), historie en sealed zitten in Pro ($14,99 per maand).
"""
import requests

BASE = "https://api.pkmnprices.com/v1"


class PkmnPrices:
    def __init__(self, key, session=None):
        self.s = session or requests.Session()
        self.s.headers.update({"X-API-Key": key, "User-Agent": "pokedeals/2.0"})

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


def probe(pk):
    short = lambda x, n=700: str(x)[:n]
    seen = {}

    def call(label, path, params=None):
        try:
            status, body, headers = pk.get(path, params)
        except Exception as e:
            print(f"{label}: FOUT {e}")
            return None, None
        for k, v in headers.items():
            if k.lower().startswith("x-") or "credit" in k.lower() or "ratelimit" in k.lower():
                seen[k] = v
        print(f"{label}: status {status}")
        return status, body

    print("=== PkmnPrices ===")
    print("--- 1. Kaarten zoeken (max. 2) ---")
    status, body = call("cards", "/cards", {"name": "charizard ex", "per_page": 2})
    rows = _rows(body)
    if isinstance(body, dict):
        print("sleutels:", list(body)[:8], "| paginering:", short(body.get("pagination") or body.get("meta"), 200))
    if not rows:
        print("ruw:", short(body))
        return
    print("eerste kaart, velden:", sorted(rows[0].keys()) if isinstance(rows[0], dict) else rows[0])
    print("ruw:", short(rows[0], 900))
    cid = rows[0].get("id") if isinstance(rows[0], dict) else None

    print("\n--- 2. Eén kaart met prijzen ---")
    status, body = call("card", f"/cards/{cid}")
    d = body.get("data", body) if isinstance(body, dict) else {}
    if isinstance(d, dict):
        print("velden:", sorted(d.keys()))
        print("Cardmarket-koppeling:", {k: d.get(k) for k in d if "cardmarket" in k.lower()})
        print("plaatje/set:", {k: d.get(k) for k in d if "image" in k.lower() or k.lower().startswith("set")})
        prices = d.get("prices") or []
        print(f"{len(prices)} prijsregels; eerste 6:")
        for p in prices[:6]:
            print("  ", short(p, 250))

    print("\n--- 3. Euro's (Cardmarket) voor deze kaart ---")
    status, body = call("card eur", f"/cards/{cid}", {"currency": "eur"})
    if status == 200 and isinstance(body, dict):
        d = body.get("data", body)
        print("prijsregels:", [short(p, 200) for p in (d.get("prices") or [])[:6]])
    else:
        print("melding:", short(body, 300))

    print("\n--- 4. Sets ---")
    status, body = call("sets", "/sets", {"per_page": 2})
    print("ruw:", short(_rows(body)[:2] or body, 500))

    print("\n--- 5. Sealed ---")
    status, body = call("sealed", "/sealed", {"per_page": 2})
    srows = _rows(body)
    print("ruw:", short(srows[:2] or body, 800))

    print("\n--- 6. Prijshistorie (Cardmarket, Near Mint, 7 dagen) ---")
    status, body = call("history", f"/cards/{cid}/prices/history", {"currency": "eur", "period": "7d", "condition": "Near Mint", "limit": 5})
    print("ruw:", short(body, 800))

    print("\nheaders over limieten en credits:", seen)
