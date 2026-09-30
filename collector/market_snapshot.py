"""Stap 1 van het meersignalenplan: elke dag een momentopname van aanbod, vraag en liquiditeit voor de kaarten van
de beroemde Pokémon (config.FAMOUS_DEX_IDS), via PokemonPriceTracker:
  - listings      aantal aanbiedingen            (aanbod)
  - sellers       aantal verschillende verkopers (liquiditeit)
  - recent_sales  recente verkopen               (vraag)
PokemonPriceTracker geeft die cijfers alleen voor NU, niet terug in de tijd. Een trend ('listings nemen af')
ontstaat dus pas nadat we een paar weken elke dag een momentopname hebben opgeslagen.

Werkwijze per nacht, binnen een eigen budget (config.SNAPSHOT_PPT_BUDGET, los van PkmnPrices):
  1. Kaarten die al een ppt_id hebben: één opvraging per kaart.
  2. Budget over? Nog niet gekoppelde kaarten koppelen, set voor set (de sets met de meeste beroemde kaarten
     zonder koppeling eerst). Zo'n set-opvraging levert meteen ook de momentopname van die kaarten op.
Het logboek toont hoeveel credits dit kostte, zodat we na de eerste nacht de echte kosten per kaart kennen.
"""
import time
from collections import Counter
from datetime import date, timedelta

import config
from ppt import clean_card_name, norm, norm_number


def famous_cards(store):
    return [p for p in store.products("card") if p.get("dex_id") in config.FAMOUS_DEX_IDS]


def snapshot_row(product_id, item, today):
    return {"product_id": product_id, "date": today, "listings": item.get("listings"), "sellers": item.get("sellers"),
            "recent_sales": item.get("recent_sales"), "price_usd": item.get("price_usd")}


def _has_data(item):
    return any(item.get(k) is not None for k in ("listings", "sellers", "recent_sales"))


def find_ppt_set(tcg_set, ppt_sets):
    """Zelfde logica als backfill.find_ppt_set: PPT noemt sets bijv. 'SV03: Obsidian Flames' of 'XY - Roaring Skies'."""
    n = norm(tcg_set["name"])
    exact = [s for s in ppt_sets if norm(s["name"]) == n]
    if exact:
        return exact[0]
    part = [s for s in ppt_sets if n and (n in norm(s["name"]) or norm(s["name"]) in n)]
    return min(part, key=lambda s: len(norm(s["name"]))) if part else None


def match(items, cards):
    """Koppelt PPT-kaarten aan onze kaarten op nummer + naam. Geeft {product_id: item}."""
    by_number = {}
    for c in cards:
        by_number.setdefault(norm_number(c.get("number")), []).append(c)
    out = {}
    for it in items:
        name = norm(clean_card_name(it.get("name") or ""))
        for c in by_number.get(norm_number(it.get("number")), []):
            cn = norm(c.get("name") or "")
            if it.get("ppt_id") and (cn == name or (name and (cn in name or name in cn))):
                out.setdefault(c["product_id"], it)
    return out


def last_snapshot(store, product_ids, today):
    """Datum van de laatste momentopname per kaart (laatste 14 dagen), om de langst niet bijgewerkte eerst te doen."""
    since = (date.fromisoformat(today) - timedelta(days=14)).isoformat()
    out = {}
    ids = sorted(product_ids)
    for i in range(0, len(ids), 150):
        try:
            for r in store.select("market_snapshots", {"select": "product_id,date", "product_id": f"in.({','.join(ids[i:i + 150])})", "date": f"gte.{since}"}):
                out[r["product_id"]] = max(out.get(r["product_id"], ""), r["date"])
        except Exception:
            return out
    return out


def run(store, ppt, today, log=print, deadline=None):
    if ppt is None:
        log("Marktmomentopname: geen PPT_API_KEY, overgeslagen.")
        return 0
    start_credits = ppt.credits
    budget = config.SNAPSHOT_PPT_BUDGET
    over = lambda: ppt.over_budget() or ppt.credits - start_credits >= budget or (deadline is not None and time.time() >= deadline)
    cards = famous_cards(store)
    last = last_snapshot(store, [c["product_id"] for c in cards], today)
    cards = [c for c in cards if last.get(c["product_id"]) != today]          # vandaag al gedaan: overslaan
    cards.sort(key=lambda c: last.get(c["product_id"], ""))                 # langst niet bijgewerkt eerst
    mapped = [c for c in cards if c.get("ppt_id")]
    unmapped = [c for c in cards if not c.get("ppt_id")]
    log(f"Marktmomentopname: {len(cards)} kaarten van beroemde Pokémon, {len(mapped)} al gekoppeld aan PokemonPriceTracker.")

    rows, done = [], set()
    for c in mapped:
        if over():
            log(f"  budget of tijd voor de momentopname op ({ppt.credits - start_credits} credits); de rest morgen.")
            break
        try:
            it = ppt.card(c["ppt_id"])
        except Exception as e:
            log(f"  {c['name']}: {e}")
            if ppt.blocked:
                break
            continue
        if it and _has_data(it):
            rows.append(snapshot_row(c["product_id"], it, today))
            done.add(c["product_id"])
    per_card = (ppt.credits - start_credits) / len(done) if done else None

    newly = 0
    if unmapped and not over():
        try:
            ppt_sets = ppt.sets()
        except Exception as e:
            ppt_sets = []
            log(f"  sets ophalen bij PokemonPriceTracker mislukt: {e}")
        known = store.known_sets()
        per_set = Counter(c.get("set_id") for c in unmapped if c.get("set_id"))
        for set_id, _ in per_set.most_common():
            if over():
                break
            ts = known.get(set_id)
            ps = find_ppt_set(ts, ppt_sets) if ts else None
            if not ps:
                continue
            try:
                items = ppt.cards_in_set(ps["set_id"])
            except Exception as e:
                log(f"  set {ts['name']}: {e}")
                if ppt.blocked:
                    break
                continue
            wanted = [c for c in unmapped if c.get("set_id") == set_id]
            hits = match(items, wanted)
            if hits:
                store.upsert_products([{"product_id": pid, "kind": "card", "name": next(c["name"] for c in wanted if c["product_id"] == pid),
                                        "ppt_id": it["ppt_id"]} for pid, it in hits.items()])
                newly += len(hits)
                rows += [snapshot_row(pid, it, today) for pid, it in hits.items() if _has_data(it) and pid not in done]
                done.update(hits)

    if rows:
        store.upsert("market_snapshots", rows, "product_id,date")
    used = ppt.credits - start_credits
    log(f"Marktmomentopname: {len(rows)} kaarten vastgelegd, {newly} nieuw gekoppeld, {used} credits"
        + (f" (~{per_card:.1f} per al gekoppelde kaart)" if per_card is not None else "") + ".")
    return len(rows)
