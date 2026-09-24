"""Laagste Near Mint-prijs (Cardmarket, euro) per kaart, via PkmnPrices Pro.

De trendprijs van Cardmarket is een gemiddelde; wie koopt of verkoopt kijkt naar het aanbod. Voor de kaarten die we
volgen slaan we daarom dagelijks de Near Mint-prijs van PkmnPrices op (grade_key 'nm'). Eerst koppelen we een kaart
één keer aan PkmnPrices (zoeken op naam, dan op kaartnummer en set), daarna kost het vernieuwen 1 credit per kaart.
"""
import os
import time
from datetime import date

import config
from ppt import norm, norm_number
from pkmnprices import PkmnPrices

VARIANT_ORDER = ("normal", "holofoil", "reverse holofoil")


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def nm_price(detail):
    """(variant, prijs) van de Near Mint-prijs in euro. Bij meerdere uitvoeringen: niet-1st edition, normal > holo > reverse."""
    rows = [p for p in (detail.get("prices") or [])
            if (p.get("source") or "").lower() == "cardmarket" and (p.get("currency") or "").upper() == "EUR"
            and (p.get("condition") or "").lower() == "near mint" and p.get("market_price")]
    if not rows:
        return None

    def rank(p):
        v = (p.get("variant") or "").lower()
        return ("1st" in v, VARIANT_ORDER.index(v) if v in VARIANT_ORDER else len(VARIANT_ORDER))

    best = min(rows, key=rank)
    return best.get("variant"), float(best["market_price"])


def match_card(product, candidates):
    """Kiest de PkmnPrices-kaart bij een van onze kaarten: kaartnummer moet kloppen, dan setnaam en setgrootte."""
    number = norm_number(product.get("number"))
    best, best_score = None, 0
    for c in candidates:
        if norm_number(c.get("number")) != number:
            continue
        score = 0
        cset = norm((c.get("set") or {}).get("name"))
        mine = norm(product.get("set_name"))
        if mine and cset and (mine in cset or cset in mine):
            score += 2
        if product.get("set_total") and norm_number(c.get("total_set_number")) == norm_number(product["set_total"]):
            score += 1
        if score > best_score:
            best, best_score = c, score
    return best


def find_card(pk, product):
    """Zoekt de kaart bij PkmnPrices. Credits worden per teruggegeven rij gerekend, dus een korte, gerichte
    zoekopdracht scheelt veel: een klein aantal resultaten per pagina, en het kaartnummer meegestuurd (voor het
    geval de zoekopdracht daarop kan filteren; negeert de API dat veld, dan kost het verder niets extra)."""
    rows = pk.list_all("/cards", {"name": product["name"], "number": product.get("number")}, per_page=15, max_pages=1)
    hit = match_card(product, rows)
    return str(hit["id"]) if hit else None


def pick_targets(store, limit, fc=None):
    """Volgorde: collectie en prijsmeldingen, dan de beste kansen, dan de duurste kaarten."""
    order, seen = [], set()

    def add(pid):
        if pid and ":" not in pid and pid not in seen:
            seen.add(pid)
            order.append(pid)

    for c in store.select("collection", {"select": "product_id"}):
        add(c["product_id"])
    for a in store.select("alerts", {"select": "product_id", "active": "eq.true"}):
        add(a["product_id"])
    horizon, pct = config.STANDARD
    fc = fc if fc is not None else store.select("forecasts", {"select": "product_id,price,p_up,p_down", "horizon_days": f"eq.{horizon}", "threshold_pct": f"eq.{pct}"})
    for f in sorted(fc, key=lambda f: float(f["p_up"]) - float(f["p_down"]), reverse=True)[:300]:
        add(f["product_id"])
    for f in sorted(fc, key=lambda f: -float(f["price"])):
        if len(order) >= limit:
            break
        add(f["product_id"])
    return order[:limit], fc


def extra_targets(fc, exclude, cap=20_000):
    """Aanvullende kaarten (buiten de vaste lijst), duurste eerst: alleen gebruikt als er na de vaste lijst nog
    budget overblijft, zodat een dag met credits over toch meer kaarten van een Near Mint-prijs voorziet.
    Eén kaart heeft meerdere rijen in 'fc' (één per periode van 7 dagen tot 24 maanden) — zonder dedupen zou
    diezelfde kaart hier meerdere keren in de lijst belanden."""
    order, seen = [], set(exclude)
    for f in sorted(fc, key=lambda f: -float(f["price"])):
        pid = f["product_id"]
        if pid and ":" not in pid and pid not in seen:
            seen.add(pid)
            order.append(pid)
            if len(order) >= cap:
                break
    return order


def _map_and_refresh(store, pk, today, targets, products, log, flush_every=150, deadline=None, refresh_price=True):
    """Koppelt nog niet-gekoppelde kaarten uit 'targets' aan PkmnPrices en ververst (als refresh_price=True) hun
    Near Mint-prijs. refresh_price=False slaat het verversen over maar koppelt gewoon door, voor als de actuele
    prijs zelf even kan wachten (bijv. tijdens het opbouwen van geschiedenis) maar nieuwe kaarten wel gekoppeld
    moeten blijven worden, want dat is een voorwaarde voor card_history.py.
    Slaat kaarten over die vandaag al een NM-prijs kregen (bijv. door een eerdere taak dezelfde dag), zodat een
    late 'maak het dagbudget op'-taak niet dezelfde kaarten herhaalt maar verder komt in de lijst.
    Slaat tussentijds op (elke 'flush_every' kaarten), zodat een haperende verbinding verderop niet de opgehaalde
    resultaten van hiervoor ongedaan maakt en er geen PkmnPrices-credits voor niets worden uitgegeven.
    Stopt vanzelf zodra pk.over_budget() aangeeft dat het dagbudget op is; verder geen eigen limiet."""
    wanted = set(targets)
    done_today = set()
    try:
        for ch in _chunks(sorted(wanted), 150):
            rows = store.select("prices", {"select": "product_id", "product_id": f"in.({','.join(ch)})",
                                           "date": f"eq.{today}", "source": "eq.pkmnprices", "grade_key": "eq.nm"})
            done_today.update(r["product_id"] for r in rows)
    except Exception as e:
        log(f"  (kon niet controleren wie vandaag al gedaan is, ga gewoon door: {e})")

    mapped = failed = 0
    new_links = []
    for i, pid in enumerate(targets, 1):
        if pk.over_budget() or (deadline and time.time() >= deadline):
            break
        p = products.get(pid)
        if not p or p.get("pk_id"):
            continue
        try:
            found = find_card(pk, p)
        except Exception as e:
            log(f"  zoeken mislukt voor {p['name']}: {e}")
            failed += 1
            continue
        if found:
            p["pk_id"] = found
            new_links.append({"product_id": pid, "kind": "card", "name": p["name"], "pk_id": found})
            mapped += 1
        else:
            failed += 1
        if len(new_links) >= flush_every or (i == len(targets) and new_links):
            store.upsert_products(new_links)
            new_links = []
    if new_links:
        store.upsert_products(new_links)

    all_rows, examples = [], []
    if not refresh_price:
        return mapped, failed, all_rows, examples
    try:
        price_now = {f["product_id"]: float(f["price"]) for f in store.select(
            "forecasts", {"select": "product_id,price", "horizon_days": f"eq.{config.STANDARD[0]}", "threshold_pct": f"eq.{config.STANDARD[1]}"})}
    except Exception:
        price_now = {}   # alleen nodig voor de voorbeeldregels in het logboek; niet kritiek
    pending = []
    for i, pid in enumerate(targets, 1):
        if pk.over_budget() or (deadline and time.time() >= deadline):
            break
        p = products.get(pid)
        if not p or not p.get("pk_id") or pid in done_today:
            continue
        try:
            d = pk.detail(f"/cards/{p['pk_id']}", {"currency": "eur"})
        except Exception as e:
            log(f"  {p['name']}: {e}")
            continue
        nm = nm_price(d)
        if not nm:
            continue
        row = {"product_id": pid, "date": today, "source": "pkmnprices", "grade_key": "nm",
              "price": nm[1], "native": nm[1], "currency": "EUR"}
        pending.append(row)
        all_rows.append(row)
        if price_now.get(pid):
            examples.append((price_now[pid], f"{p['name']} ({p.get('set_name')} #{p.get('number')}): NM €{nm[1]:.2f} ({nm[0]}) tegenover trend €{price_now[pid]:.2f}"))
        if len(pending) >= flush_every:
            store.upsert_prices(pending)
            pending = []
    if pending:
        store.upsert_prices(pending)
    return mapped, failed, all_rows, examples


def run(store, pk, today, log=print, limit=None, deadline=None):
    """pk: een PkmnPrices-client die de HELE dag deelt (ook met sealed_history.py), zodat het echte dagbudget
    maar één keer wordt opgemaakt, niet per taak apart. Blijft, zolang er budget over is, ook kaarten buiten de
    vaste lijst van dag tot dag verder afwerken in plaats van vroegtijdig te stoppen."""
    limit = limit or config.PK_TARGETS
    targets, fc = pick_targets(store, limit)
    products = {p["product_id"]: p for p in store.products("card")}   # 1x opgehaald, hieronder hergebruikt (voorkomt een tweede trage aanvraag)
    already = sum(1 for pid in targets if products.get(pid, {}).get("pk_id"))
    log(f"NM-prijzen: {len(targets)} kaarten in de vaste lijst, {already} al gekoppeld"
        + ("" if config.NM_REFRESH_PRICE else " (verversen staat tijdelijk uit; koppelen gaat wel door voor de geschiedenis-opbouw)"))

    mapped, failed, rows, examples = _map_and_refresh(store, pk, today, targets, products, log, deadline=deadline, refresh_price=config.NM_REFRESH_PRICE)
    log(f"Vaste lijst: {mapped} nieuw gekoppeld, {failed} niet gevonden, {len(rows)} prijzen opgeslagen ({pk.credits} credits tot nu toe)")

    if config.NM_WIDEN_EXTRA and not pk.over_budget() and not (deadline and time.time() >= deadline):
        extra = extra_targets(fc, exclude=set(targets))
        if extra:
            log(f"Nog budget over: {len(extra)} extra kaarten (buiten de vaste lijst) worden ook meegenomen, duurste eerst")
            extra_products = {pid: products[pid] for pid in extra if pid in products}
            m2, f2, r2, e2 = _map_and_refresh(store, pk, today, [pid for pid in extra if pid in products], extra_products, log, deadline=deadline)
            mapped += m2
            failed += f2
            rows += r2
            examples += e2
            log(f"Extra: {m2} nieuw gekoppeld, {f2} niet gevonden, {len(r2)} prijzen opgeslagen")

    log(f"NM-prijzen totaal opgeslagen: {len(rows)}; {pk.credits} credits gebruikt, budget bereikt: {pk.over_budget()}")
    for _, line in sorted(examples, reverse=True)[:8]:
        log("  voorbeeld (duurste eerst): " + line)
    return len(rows)


def main():
    from store import SupabaseStore
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    run(store, PkmnPrices(os.environ["PKMN_API_KEY"], budget=config.PK_BUDGET), date.today().isoformat())


if __name__ == "__main__":
    main()
