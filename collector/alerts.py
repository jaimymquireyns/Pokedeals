"""Prijsmeldingen, 'aandacht nodig' en de dagelijkse samenvatting."""
from datetime import date, datetime, timedelta, timezone

import config


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _f(x):
    return None if x is None else float(x)


def grade_key(item):
    return "raw" if not item.get("grade_company") else f"{item['grade_company']}-{item['grade']}"


def eur(x):
    return f"€{x:,.2f}"


def net_change(price, exp, fee_pct):
    """Verwachte winst als fractie van wat je betaalt: nu kopen (prijs + geschatte verzending als koper) en na de
    verwachte stijging verkopen (min commissie en verpakking; de verzending bij verkopen betaalt de koper)."""
    cost = price + config.ship_cost(price)
    net = price * (1 + exp) * (1 - fee_pct / 100) - config.PACKAGING
    return net / cost - 1


def latest_map(store, keys, today, days=10):
    """Laatste prijs per (product_id, grade_key)."""
    since = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    out = {}
    for ch in _chunks(sorted({k[0] for k in keys}), 60):
        rows = store.select("prices", {"select": "product_id,grade_key,date,price", "date": f"gte.{since}",
                                       "product_id": f"in.({','.join(ch)})", "order": "product_id.asc,date.asc"})
        for r in rows:
            if r["price"] is not None:
                out[(r["product_id"], r["grade_key"])] = float(r["price"])
    return out


def _subscriptions(store):
    subs = {}
    for s in store.select("push_subscriptions", {"select": "*"}):
        subs.setdefault(s["user_id"], []).append(s)
    return subs


def _push(store, sender, user_subs, payload):
    """Stuurt naar alle toestellen van één gebruiker; ruimt verlopen abonnementen op. True als er iets aankwam."""
    ok = False
    for sub in user_subs:
        res = sender.send(sub, payload)
        if res == "ok":
            ok = True
        elif res == "gone":
            store.delete("push_subscriptions", {"id": f"eq.{sub['id']}"})
    return ok


def evaluate(store, sender, today, log=print):
    alerts = store.select("alerts", {"select": "*", "active": "eq.true"})
    if not alerts:
        return 0
    prices = latest_map(store, [(a["product_id"], a["grade_key"]) for a in alerts], today)
    settings = {s["user_id"]: s for s in store.select("user_settings", {"select": "*"})}
    subs = _subscriptions(store)
    names = {}
    for ch in _chunks(sorted({a["product_id"] for a in alerts}), 80):
        for p in store.select("products", {"select": "product_id,name", "product_id": f"in.({','.join(ch)})"}):
            names[p["product_id"]] = p["name"]

    sent = 0
    for a in alerts:
        price = prices.get((a["product_id"], a["grade_key"]))
        if price is None:
            continue
        lo, hi = _f(a["min_price"]), _f(a["max_price"])
        inside = (lo is None or price >= lo) and (hi is None or price <= hi)
        if inside and a["armed"]:
            wants = settings.get(a["user_id"], {}).get("price_alerts", True)
            label = names.get(a["product_id"], a["product_id"]) + ("" if a["grade_key"] == "raw" else f" ({a['grade_key'].replace('-', ' ')})")
            if lo is not None and hi is not None:
                span = f"between {eur(lo)} and {eur(hi)}"
            elif lo is not None:
                span = f"above {eur(lo)}"
            else:
                span = f"below {eur(hi)}"
            payload = {"title": "Price alert", "body": f"{label} is now {eur(price)}, {span}.",
                       "url": f"./#/detail/{a['product_id']}", "tag": f"alert-{a['id']}"}
            if wants and sender and _push(store, sender, subs.get(a["user_id"], []), payload):
                store.patch("alerts", {"id": f"eq.{a['id']}"},
                            {"armed": False, "last_triggered": datetime.now(timezone.utc).isoformat()})
                sent += 1
        elif not inside and not a["armed"]:
            store.patch("alerts", {"id": f"eq.{a['id']}"}, {"armed": True})   # weer klaar voor een volgende melding
    log(f"Prijsmeldingen: {sent} verstuurd")
    return sent


def attention(items):
    """items: collectieregels met kansen. Geeft [(item, reden)] waarvoor aandacht nodig is."""
    out = []
    for it in items:
        p_up, p_down = _f(it.get("p_up")), _f(it.get("p_down"))
        value, buy = _f(it.get("value_each")), _f(it.get("purchase_price"))
        if p_down is not None and p_down >= config.ATTN_MIN_P_DOWN:
            out.append((it, "daling"))
        elif value and buy and p_up is not None and value / buy - 1 >= config.ATTN_PROFIT and p_up <= config.ATTN_MAX_P_UP:
            out.append((it, "winst nemen"))
    return out


def _advice_rows(store, ids, since, until):
    out = {}
    for ch in _chunks(sorted(ids), 100):
        for r in store.select("advice", {"select": "product_id,date,state,price,normal,flags,context", "product_id": f"in.({','.join(ch)})",
                                         "date": f"gte.{since}", "order": "product_id.asc,date.asc"}):
            if str(r["date"])[:10] <= until:
                out.setdefault(r["product_id"], []).append(r)
    return out


def _was(rows, today, state):
    """Stond dit product de afgelopen week al op deze toestand? Dan is het geen nieuws meer."""
    return any(str(r["date"])[:10] < today and r["state"] == state for r in rows)


def personal_advice(a, coll, fee_pct):
    """Voor één kaart uit iemands collectie: ('sell', winst) als hij ruim boven normaal staat en je na kosten genoeg overhoudt,
    ('buy', winst bij herstel) als hij tijdelijk ruim onder normaal staat zonder reden of waarschuwing, anders None.
    Zelfde regels als het advies in de app (Sell now / Buy more)."""
    import advice
    price, normal = _f(a.get("price")), _f(a.get("normal"))
    if not price or not normal or coll.get("grade_company"):
        return None
    if a["state"] == "hoog":
        qty = max(int(coll.get("quantity") or 1), 1)
        cost = _f(coll["purchase_price"]) + ((_f(coll.get("purchase_shipping")) or 0) + (_f(coll.get("purchase_costs")) or 0)) / qty
        net = price * (1 - fee_pct / 100) - config.PACKAGING
        if cost and net / cost - 1 >= config.NOTIFY_SELL_PROFIT:
            return ("sell", net / cost - 1)
    if a["state"] == "laag" and not a.get("context") and not a.get("flags") and price >= config.ADVICE_MIN_BUY:
        g = advice.buy_gain(price, normal, fee_pct)
        if g >= config.ADVICE_BUY_GAIN:
            return ("buy", g)
    return None


def send_digest(store, sender, today, log=print):
    """Ochtendmelding op basis van het advies van vandaag, alleen bij nieuws (wat de week ervoor al zo stond, melden we niet
    opnieuw): kaarten uit je collectie die 'Sell now' of 'Buy more' werden, en het aantal nieuwe sterke deals."""
    if not sender:
        return 0
    import advice
    since = (date.fromisoformat(today) - timedelta(days=7)).isoformat()
    settings = {s["user_id"]: s for s in store.select("user_settings", {"select": "*"})}
    subs = _subscriptions(store)
    laag = {r["product_id"]: r for r in store.select("advice", {"select": "product_id,date,state,price,normal,flags,context",
                                                                "date": f"eq.{today}", "state": "eq.laag"})}
    prev = _advice_rows(store, laag, since, today) if laag else {}
    strong = [pid for pid, r in laag.items()
              if not r.get("context") and not r.get("flags") and (_f(r.get("price")) or 0) >= config.ADVICE_MIN_BUY and _f(r.get("normal"))
              and advice.buy_gain(_f(r["price"]), _f(r["normal"])) >= config.NOTIFY_DEAL_GAIN and not _was(prev.get(pid, []), today, "laag")]
    names, sent = {}, 0
    for uid, user_subs in subs.items():
        st = settings.get(uid, {})
        if not st.get("digest", True):
            continue
        fee = _f(st.get("fee_pct")) or config.DEFAULT_FEE_PCT
        coll = store.select("collection", {"select": "*", "user_id": f"eq.{uid}"})
        hist = _advice_rows(store, {c["product_id"] for c in coll}, since, today) if coll else {}
        found = {"sell": {}, "buy": {}}
        for c in coll:
            rows = hist.get(c["product_id"], [])
            now = next((r for r in rows if str(r["date"])[:10] == today), None)
            res = personal_advice(now, c, fee) if now else None
            if res and not _was(rows, today, now["state"]):
                found[res[0]][c["product_id"]] = max(res[1], found[res[0]].get(c["product_id"], -9))
        if not found["sell"] and not found["buy"] and not strong:
            continue
        need = sorted((set(found["sell"]) | set(found["buy"])) - set(names))
        for ch in _chunks(need, 80):
            for p in store.select("products", {"select": "product_id,name", "product_id": f"in.({','.join(ch)})"}):
                names[p["product_id"]] = p["name"]

        def lst(d):
            items = sorted(d.items(), key=lambda x: -x[1])
            txt = ", ".join(f"{names.get(pid, pid)} ({x * 100:+.0f}%)" for pid, x in items[:2])
            return txt + (f" +{len(items) - 2} more" if len(items) > 2 else "")
        parts = []
        if found["sell"]:
            parts.append(f"Sell now: {lst(found['sell'])}.")
        if found["buy"]:
            parts.append(f"Buy more: {lst(found['buy'])}.")
        if strong:
            parts.append(f"{len(strong)} new strong {'deal' if len(strong) == 1 else 'deals'}.")
        url = "./#/collection" if found["sell"] or found["buy"] else "./#/home"
        if _push(store, sender, user_subs, {"title": "Pokédeals", "body": " ".join(parts), "url": url, "tag": f"advice-{today}"}):
            sent += 1
    log(f"Adviesmelding: {sent} verstuurd ({len(strong)} nieuwe sterke deals)")
    return sent
