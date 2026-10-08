"""Cardmarkets eigen naam per kaart ("Charizard (30C BS4)", "Blissey Lv.44 (MT 5)", "_____'s Pikachu (CEL WP 24)").

Wij noemen een kaart zoals TCGdex hem noemt, met TCGdex' nummer. Cardmarket noemt hem anders, vaak met een setcode en een eigen nummer
tussen haakjes. Wie op Cardmarkets schrijfwijze zoekt, vond daardoor niets. Cardmarket publiceert zijn productlijst openbaar
(productList/products_singles_<game>.json, geen sleutel nodig); voor elke kaart die we al aan een Cardmarket-product gekoppeld hebben
(cm_product_id, via de koppelstap) bewaren we daaruit de naam in products.cm_name. Zoeken kijkt daar daarna ook in.

Dit kost geen PkmnPrices-credits. Zonder gekoppelde kaarten (cm_product_id) valt er niets te vullen: koppelen gebeurt in cm_links.py.
"""
import config
import cardmarket


def load_singles(session, game=None):
    """{idProduct: naam} uit Cardmarkets lijst met losse kaarten, plus de eerste record voor het logboek."""
    game = game or config.CARDMARKET_GAME_ID
    recs = cardmarket.records(cardmarket.fetch(session, f"productList/products_singles_{game}.json"))
    out = {}
    for d in recs:
        pid, name = d.get("idProduct"), d.get("name")
        if pid is None or not name:
            continue
        try:
            out[int(pid)] = str(name).strip()
        except (TypeError, ValueError):
            continue
    return out, (recs[0] if recs else None)


def run(store, session, today=None, log=print, loader=None):
    """Vult cm_name voor alle gekoppelde kaarten waar die nog ontbreekt of veranderd is. Geeft het aantal bijgewerkte kaarten terug."""
    cards = [p for p in store.products("card", extra={"cm_product_id": "not.is.null"}) if p.get("cm_product_id") not in (None, "")]
    log(f"Cardmarket-namen: {len(cards)} gekoppelde kaarten.")
    if not cards:
        log("Cardmarket-namen: nog geen kaarten met een Cardmarket-productnummer; die komen er via de koppelstap (Cardmarket-links).")
        return 0
    names, sample = (loader or load_singles)(session)
    if not names:
        log("! Cardmarket-namen: de productlijst met losse kaarten gaf niets bruikbaars terug (geen idProduct/name). "
            f"Eerste record: {str(sample)[:300] if sample else 'leeg bestand'}. Niets bijgewerkt.")
        return 0
    log(f"Cardmarket-namen: {len(names)} producten in Cardmarkets lijst.")
    rows, missing = [], 0
    for p in cards:
        try:
            name = names.get(int(p["cm_product_id"]))
        except (TypeError, ValueError):
            continue
        if not name:
            missing += 1
            continue
        if name != p.get("cm_name"):
            rows.append({"product_id": p["product_id"], "kind": "card", "name": p["name"], "cm_name": name})
    for i in range(0, len(rows), 200):
        try:
            store.upsert_products(rows[i:i + 200])
        except Exception as e:
            log(f"! Cardmarket-namen: opslaan mislukt ({type(e).__name__}: {str(e)[:200]}). Is supabase/schema.sql opnieuw gedraaid (kolom cm_name)?")
            return 0
    coded = sum(1 for r in rows if "(" in r["cm_name"])
    log(f"Cardmarket-namen: {len(rows)} kaarten bijgewerkt ({coded} met een code tussen haakjes); {missing} niet in Cardmarkets lijst gevonden.")
    for r in rows[:3]:
        log(f"  voorbeeld: {r['product_id']} -> {r['cm_name']}")
    return len(rows)
