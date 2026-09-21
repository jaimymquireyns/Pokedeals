"""Extra gegevens (context) die we vanaf dag 1 opslaan, zodat ze later getest kunnen worden in het model:
herdrukken, leeftijd van een set (via sets.release_date), rotatie (products.legal_standard) en
populariteit (Wikipedia-bezoekers per Pokémon). Ze zitten nog NIET in de kansberekening."""
import re
import time
from datetime import date, timedelta

SUFFIXES = {"ex", "v", "vmax", "vstar", "gx", "v-union", "mega", "m", "radiant", "shining", "dark", "light",
            "alolan", "galarian", "hisuian", "paldean", "tera", "break", "prime", "star", "lv.x", "δ"}


def species_name(card_name):
    toks = (card_name or "").split()
    for i in range(len(toks) - 1, -1, -1):          # "Team Rocket's Mewtwo ex" -> "Mewtwo ex"
        if toks[i].endswith("'s") or toks[i].endswith("’s"):
            toks = toks[i + 1:]
            break
    toks = [t for t in toks if t.lower() not in SUFFIXES and not re.match(r"^\(.*\)$", t)]
    return " ".join(toks) or None


def update_static(store, today=None, force=False, log=print):
    """Aantal keer gedrukt en of er een nieuwere versie bestaat. Draait op maandag (of met force)."""
    today = today or date.today()
    if not force and today.weekday() != 0:
        return 0
    sets = store.known_sets()
    rel = {sid: (s.get("release_date") or "") for sid, s in sets.items()}
    cards = store.select("products", {"select": "product_id,name,kind,set_id", "kind": "eq.card", "order": "product_id.asc"})
    by_name = {}
    for c in cards:
        by_name.setdefault((c["name"] or "").lower(), []).append(c)
    out = []
    for group in by_name.values():
        set_ids = {c["set_id"] for c in group}
        latest = max((rel.get(s, "") for s in set_ids), default="")
        for c in group:
            mine = rel.get(c["set_id"], "")
            out.append({"product_id": c["product_id"], "kind": "card", "name": c["name"], "printings": len(set_ids),
                        "newer_printing": bool(mine and latest > mine)})
    if out:
        store.upsert_products(out)
    log(f"Herdruk-context bijgewerkt voor {len(out)} kaarten")
    return len(out)


def pageviews_url(title, start, end):
    return ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
            f"{title.replace(' ', '_')}/daily/{start}/{end}")


def update_pageviews(store, today, limit=150, session=None, log=print):
    """Wikipedia-bezoekers (laatste 7 dagen) voor de Pokémon met de duurste kaarten. Alleen soorten met een eigen
    artikel geven bruikbare cijfers; de rest wordt overgeslagen."""
    import requests
    s = session or requests.Session()
    s.headers["User-Agent"] = "pokedeals/2.0 (persoonlijk project)"
    rows = store.select("v_forecasts", {"select": "name,price,dex_id", "horizon_days": "eq.30", "threshold_pct": "eq.10",
                                        "kind": "eq.card", "order": "price.desc"})
    species = {}
    for r in rows:
        if r.get("dex_id") and r["dex_id"] not in species:
            name = species_name(r["name"])
            if name:
                species[r["dex_id"]] = name
        if len(species) >= limit:
            break
    end = date.fromisoformat(today) - timedelta(days=1)
    start = end - timedelta(days=6)
    out = []
    for dex, name in species.items():
        r = s.get(pageviews_url(name, start.strftime("%Y%m%d"), end.strftime("%Y%m%d")), timeout=20)
        if r.status_code != 200:
            continue
        for it in r.json().get("items", []):
            ts = it["timestamp"]
            out.append({"dex_id": dex, "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "views": it["views"]})
        time.sleep(0.05)
    if out:
        store.upsert("pokemon_interest", out, "dex_id,date")
    log(f"Populariteit: {len({o['dex_id'] for o in out})} Pokémon bijgewerkt")
    return len(out)
