"""De exacte Cardmarket-pagina van elke kaart, via PkmnPrices ('/cards/{id}' geeft 'cardmarket_url' en
'cardmarket_product_id' mee). Voorheen zocht de knop 'naar Cardmarket' alleen op naam en nummer, en kwam je dan bij
een pagina met elke kaart van die Pokémon uit.

Kost 1 credit per kaart. Eigen klein dagbudget (config.CM_LINKS_BUDGET); de kaarten die je het meest gebruikt gaan
voor: collectie, watchlist, prijsmeldingen, kaarten met aanbiedingen, de beroemde Pokémon, daarna de rest.
Een kaart zonder link krijgt een lege tekst, zodat hij niet elke nacht opnieuw wordt geprobeerd.
"""
import time

import config

ALLOWED = "https://www.cardmarket.com/"
EARLY_STOP_AFTER = 20   # geeft PkmnPrices bij de eerste zoveel kaarten helemaal niets mee, dan stoppen we: dan bestaat het veld niet


def clean_url(u):
    """Alleen echte Cardmarket-adressen (nooit een willekeurig adres uit een externe bron doorgeven aan de app)."""
    if not isinstance(u, str) or not u.strip():
        return None
    u = u.strip()
    if u.startswith("/"):
        u = "https://www.cardmarket.com" + u
    return u if u.startswith(ALLOWED) else None


def extract(detail):
    """(url, product_id) uit het kaartdetail van PkmnPrices; None waar iets ontbreekt."""
    d = detail if isinstance(detail, dict) else {}
    if isinstance(d.get("data"), dict):
        d = d["data"]
    pid = d.get("cardmarket_product_id")
    try:
        pid = int(pid) if pid not in (None, "") else None
    except (TypeError, ValueError):
        pid = None
    return clean_url(d.get("cardmarket_url")), pid


def targets(store):
    """Gekoppelde kaarten zonder Cardmarket-link, op volgorde van belang."""
    cards = {p["product_id"]: p for p in store.products("card") if p.get("pk_id")}
    todo = {pid for pid, p in cards.items() if p.get("cm_url") is None}
    order, seen = [], set()

    def add(pid):
        if pid in todo and pid not in seen:
            seen.add(pid)
            order.append(pid)

    for table in ("collection", "watch_items", "alerts"):
        try:
            for r in store.select(table, {"select": "product_id"}):
                add(r["product_id"])
        except Exception:
            pass
    try:
        for r in store.select("offers", {"select": "product_id", "rank": "eq.1"}):
            add(r["product_id"])
    except Exception:
        pass
    for pid in sorted(todo, key=lambda x: cards[x].get("dex_id") not in config.FAMOUS_DEX_IDS):   # beroemde Pokémon eerst
        add(pid)
    return order, cards


def run(store, pk, today, log=print, deadline=None, budget=None):
    budget = config.CM_LINKS_BUDGET if budget is None else budget
    order, cards = targets(store)
    log(f"Cardmarket-links: {len(order)} gekoppelde kaarten nog zonder link; budget max {budget} credits.")
    if not order:
        return 0
    original_budget = pk.budget
    pk.budget = min(original_budget, pk.credits + budget)
    rows, found, none, tried, save_fails = [], 0, 0, 0, 0
    try:
        for pid in order:
            if pk.over_budget() or (deadline and time.time() >= deadline):
                break
            p = cards[pid]
            try:
                url, cm_id = extract(pk.call(f"/cards/{p['pk_id']}"))
            except Exception as e:
                log(f"  {p['name']}: {e}")
                if pk.blocked:
                    break
                continue
            tried += 1
            if url or cm_id:
                found += 1
            else:
                none += 1
            if tried == EARLY_STOP_AFTER and not found:
                log(f"Cardmarket-links: PkmnPrices geeft bij de eerste {tried} kaarten geen Cardmarket-adres mee; gestopt, niets opgeslagen. "
                    "Draai check_card voor een kaart om te zien welke velden er wel zijn.")
                return 0
            rows.append({"product_id": pid, "kind": "card", "name": p["name"], "cm_url": url or "", "cm_product_id": cm_id})
            if len(rows) >= 100:
                try:
                    store.upsert_products(rows)
                    rows = []
                except Exception as e:
                    save_fails += 1
                    log(f"  opslaan mislukt ({type(e).__name__}); is supabase/schema.sql opnieuw gedraaid (kolommen cm_url en cm_product_id)?")
                    rows = []
                    if save_fails >= 3:
                        break
        if rows:
            try:
                store.upsert_products(rows)
            except Exception as e:
                log(f"  opslaan mislukt ({type(e).__name__}); is supabase/schema.sql opnieuw gedraaid (kolommen cm_url en cm_product_id)?")
    finally:
        pk.budget = original_budget
    log(f"Cardmarket-links: {found} gevonden, {none} zonder link, {len(order) - tried} nog te gaan.")
    return found
