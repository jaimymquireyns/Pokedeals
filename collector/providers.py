"""TCGdex: gratis kaartendatabase met Cardmarket-prijzen (EUR).

Interface:
    list_sets()        -> [{"set_id", "name"}]
    get_set(set_id)    -> {"set_id", "name", "release_date", "card_total", "cards": [{"card_id", ...}]}
    get_card(card_id)  -> {"product": {...}, "price": {...} of None}
"""
import requests
import urllib3.util.connection as _u3conn
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

_orig_create_connection = _u3conn.create_connection


def _pinned_create_connection(address, *args, **kwargs):
    """Verbindingen naar TCGdex gaan naar de server die bij is (zie config.TCGDEX_PIN_IP). Alleen het IP-adres verandert:
    de naam blijft api.tcgdex.net, dus het certificaat wordt gewoon gecontroleerd. Lukt die server niet, dan het gewone adres."""
    host, port = address
    if host == config.TCGDEX_HOST and config.TCGDEX_PIN_IP:
        try:
            return _orig_create_connection((config.TCGDEX_PIN_IP, port), *args, **kwargs)
        except OSError:
            pass
    return _orig_create_connection(address, *args, **kwargs)


def pin_tcgdex():
    """Eén keer aanzetten geldt voor het hele programma (ook images.py, dat TCGdex in andere talen opvraagt)."""
    _u3conn.create_connection = _pinned_create_connection   # urllib3 (en dus requests) roept deze functie via deze module aan


pin_tcgdex()


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
    # Cardmarket-productnummer zoals TCGdex het meegeeft: daarmee vindt cm_names.py Cardmarkets eigen naam ("Charizard (30C BS4)"),
    # zodat ook die schrijfwijze in Zoeken werkt. Alleen meesturen als het er is: een leeg veld mag een eerdere koppeling niet wissen.
    cm_id = ((d.get("pricing") or {}).get("cardmarket") or {}).get("idProduct")
    extra = {"cm_product_id": int(cm_id)} if isinstance(cm_id, int) and not isinstance(cm_id, bool) and cm_id > 0 else {}
    return {**extra,
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
