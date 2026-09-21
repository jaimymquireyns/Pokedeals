"""TCGdex: gratis kaartendatabase met Cardmarket-prijzen (EUR).

Interface:
    list_sets()        -> [{"set_id", "name"}]
    get_set(set_id)    -> {"set_id", "name", "release_date", "card_total", "cards": [{"card_id", ...}]}
    get_card(card_id)  -> {"product": {...}, "price": {...} of None}
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 else None


def parse_price(data):
    """Cardmarket (EUR) uit een TCGdex-kaartobject; kaarten die alleen als holo bestaan gebruiken de '-holo'-velden."""
    cm = (data.get("pricing") or {}).get("cardmarket") or {}
    suffix = "" if _num(cm.get("trend")) else "-holo"
    trend = _num(cm.get("trend" + suffix))
    if trend is None:
        return None
    return {
        "price": trend, "native": trend, "currency": cm.get("unit", "EUR"),
        "avg1": _num(cm.get("avg1" + suffix)), "avg7": _num(cm.get("avg7" + suffix)),
        "avg30": _num(cm.get("avg30" + suffix)), "low": _num(cm.get("low" + suffix)),
    }


def parse_product(d):
    st = d.get("set") or {}
    img = d.get("image")
    dex = d.get("dexId")
    legal = d.get("legal")
    return {
        "product_id": d["id"], "kind": "card", "name": d.get("name"),
        "set_id": st.get("id"), "set_name": st.get("name"),
        "number": str(d.get("localId")) if d.get("localId") is not None else None,
        "set_total": (st.get("cardCount") or {}).get("official"),
        "rarity": d.get("rarity"), "image": f"{img}/low.webp" if img else None,
        "category": d.get("category"),
        "dex_id": dex[0] if isinstance(dex, list) and dex else None,
        "regulation_mark": d.get("regulationMark"),
        "legal_standard": legal.get("standard") if isinstance(legal, dict) else None,
    }


class TCGdex:
    name = "tcgdex"
    BASE = "https://api.tcgdex.net/v2/en"

    def __init__(self):
        s = requests.Session()
        retry = Retry(total=4, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
        s.headers["User-Agent"] = "pokedeals/2.0"
        self.session = s

    def _get(self, path):
        r = self.session.get(self.BASE + path, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def list_sets(self):
        return [{"set_id": s["id"], "name": s.get("name")} for s in (self._get("/sets") or [])]

    def get_set(self, set_id):
        d = self._get(f"/sets/{set_id}")
        if not d:
            return None
        return {"set_id": d["id"], "name": d.get("name"), "release_date": d.get("releaseDate"),
                "card_total": (d.get("cardCount") or {}).get("official"),
                "cards": [{"card_id": c["id"]} for c in d.get("cards", [])]}

    def get_card(self, card_id):
        d = self._get(f"/cards/{card_id}")
        if not d:
            return None
        return {"product": parse_product(d), "price": parse_price(d)}
