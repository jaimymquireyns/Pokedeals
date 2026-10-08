"""Kaartfoto's op orde houden. Drie dingen, elke nacht een beetje:
  1. Controleren of de foto die we bewaren echt bestaat (1/7 van alle kaarten per nacht, dus elke kaart wekelijks). Een link die
     'bestaat niet' (404/410) geeft, wordt leeggemaakt zodat de kaart opnieuw een foto kan krijgen. Een time-out of serverfout telt
     NIET als kapot: dan weten we het niet, en laten we de link staan.
  2. Kaarten zonder foto aanvullen: eerst TCGdex in het Engels, dan TCGdex in andere talen (een kaart heeft soms alleen daar een scan),
     en daarna (met credits) de afbeelding van PkmnPrices. Elke gevonden link wordt eerst gecontroleerd voordat we hem opslaan.
  3. In het logboek staat bij welke sets foto's ontbreken, zodat je ziet of het een gat in de bron is of een fout bij ons.
"""
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import time

import config

TCGDEX = "https://api.tcgdex.net/v2"
LANGS = ("en", "ja", "fr", "de", "es", "it", "pt")


def probe(session, url, timeout=15):
    """True = bestaat, False = bestaat zeker niet (404/410), None = onbekend (netwerkfout, drukte, andere status)."""
    try:
        r = session.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code in (405, 501):   # server staat HEAD niet toe: één gewone opvraging
            r = session.get(url, timeout=timeout, stream=True)
            r.close()
        if r.status_code in (404, 410):
            return False
        if 200 <= r.status_code < 300:
            return True
    except Exception:
        pass
    return None


def verify_slice(store, today, session, log=print, deadline=None, workers=16, products=None):
    """Controleert 1/7 van de kaarten met een foto. Geeft het aantal kapotte links terug (die zijn dan leeggemaakt)."""
    prods = products if products is not None else store.products("card", extra={"image": "not.is.null"})
    day = date.fromisoformat(today).toordinal() % 7
    mine = [p for p in prods if p.get("image") and zlib.crc32(p["product_id"].encode()) % 7 == day]
    log(f"Foto's controleren: {len(mine)} van {len(prods)} kaarten zijn vandaag aan de beurt (elke kaart wekelijks).")
    broken, unknown, ok = [], 0, 0

    def one(p):
        if deadline and time.time() >= deadline:
            return p, "skip"
        return p, probe(session, p["image"])

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for p, res in ex.map(one, mine):
            if res is False:
                broken.append(p)
            elif res is True:
                ok += 1
            else:
                unknown += 1
    if broken:
        store.upsert_products([{"product_id": p["product_id"], "kind": "card", "name": p["name"], "image": None} for p in broken])
        sets = Counter(p.get("set_name") or p.get("set_id") for p in broken).most_common(5)
        log(f"Foto's controleren: {len(broken)} kapotte links leeggemaakt (o.a. {', '.join(f'{s} ({n})' for s, n in sets)}); {ok} in orde, {unknown} onbekend.")
    else:
        log(f"Foto's controleren: geen kapotte links; {ok} in orde, {unknown} onbekend.")
    return len(broken)


def tcgdex_other_langs(session, card_id, langs=LANGS):
    """Zoekt de foto van een kaart in alle TCGdex-talen. Geeft een link terug of None."""
    for lang in langs:
        try:
            r = session.get(f"{TCGDEX}/{lang}/cards/{card_id}", timeout=20)
            if r.status_code != 200:
                continue
            img = (r.json() or {}).get("image")
            if img:
                return f"{img}/low.webp"
        except Exception:
            continue
    return None


def fill_missing(store, session, log=print, limit=2000, deadline=None, finder=None, products=None):
    """Kaarten zonder foto: TCGdex in alle talen. 'finder(product) -> url' is voor tests."""
    missing = products if products is not None else store.products("card", extra={"image": "is.null"})
    missing = [p for p in missing if not config.is_digital_set(p.get("set_id"))]
    log(f"Foto's aanvullen: {len(missing)} kaarten zonder foto.")
    day = date.today().toordinal()
    missing = sorted(missing, key=lambda p: zlib.crc32(f"{p['product_id']}{day}".encode()))   # elke nacht een andere volgorde, zodat hardnekkige gevallen de rest niet blokkeren
    find = finder or (lambda p: tcgdex_other_langs(session, p["product_id"]))
    found, updates = 0, []
    for p in missing[:limit]:
        if deadline and time.time() >= deadline:
            break
        url = find(p)
        if url and probe(session, url) is not False:
            updates.append({"product_id": p["product_id"], "kind": "card", "name": p["name"], "image": url})
            found += 1
        if len(updates) >= 150:
            store.upsert_products(updates)
            updates.clear()
    if updates:
        store.upsert_products(updates)
    left = Counter(p.get("set_name") or p.get("set_id") for p in missing).most_common(8)
    log(f"Foto's aanvullen: {found} kaarten kregen alsnog een foto; {len(missing) - found} nog zonder"
        + (f" (sets: {', '.join(f'{s} {n}' for s, n in left)})" if left else "") + ".")
    return found


def fill_from_pkmnprices(store, pk, session, log=print, budget=1500, deadline=None, products=None):
    """Wat TCGdex niet heeft: de afbeelding van PkmnPrices (1 credit per kaart), alleen voor al gekoppelde kaarten."""
    cards = products if products is not None else store.products("card", extra={"image": "is.null", "pk_id": "not.is.null"})
    cards = [p for p in cards if p.get("pk_id") and not p.get("image") and not config.is_digital_set(p.get("set_id"))]
    if not cards:
        return 0
    start = pk.credits
    found, updates = 0, []
    for p in cards:
        if pk.over_budget() or pk.credits - start >= budget or (deadline and time.time() >= deadline):
            break
        try:
            d = pk.detail(f"/cards/{p['pk_id']}")
        except Exception as e:
            log(f"  foto {p.get('name')}: {e}")
            if getattr(pk, "blocked", False):
                break
            continue
        url = d.get("image_url") or d.get("image")
        if url and probe(session, url) is not False:
            updates.append({"product_id": p["product_id"], "kind": "card", "name": p["name"], "image": url})
            found += 1
    if updates:
        store.upsert_products(updates)
    log(f"Foto's van PkmnPrices: {found} van {len(cards)} kaarten zonder foto kregen er een ({pk.credits - start} credits).")
    return found


def run(store, today, session, log=print, deadline=None):
    verify_slice(store, today, session, log=log, deadline=deadline)
    return fill_missing(store, session, log=log, deadline=deadline)
