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
    return "€\u00a0" + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def net_change(price, exp, fee_pct, ship):
    """Verwachte winst na verkoopkosten en verzending, als fractie van de huidige prijs."""
    return ((1 + exp) * (1 - fee_pct / 100) - ship / price) - 1


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
                span = f"tussen {eur(lo)} en {eur(hi)}"
            elif lo is not None:
                span = f"boven {eur(lo)}"
            else:
                span = f"onder {eur(hi)}"
            payload = {"title": "Prijsmelding", "body": f"{label} kost nu {eur(price)}, {span}.",
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


def send_digest(store, sender, today, log=print):
    if not sender:
        return 0
    horizon, pct = config.STANDARD
    fc = {r["product_id"]: r for r in store.select("forecasts", {
        "select": "product_id,price,p_up,p_down,exp_change", "horizon_days": f"eq.{horizon}", "threshold_pct": f"eq.{pct}"})}
    settings = {s["user_id"]: s for s in store.select("user_settings", {"select": "*"})}
    subs = _subscriptions(store)
    sent = 0
    for uid, user_subs in subs.items():
        st = settings.get(uid, {})
        if not st.get("digest", True):
            continue
        fee, ship = _f(st.get("fee_pct", 5)), _f(st.get("ship_eur", 1.5))
        net_only, net_min = st.get("net_only", True), _f(st.get("net_min_pct", 3)) / 100
        opps = 0
        for f in fc.values():
            if _f(f["p_up"]) < config.DIGEST_MIN_P_UP:
                continue
            if net_only and net_change(_f(f["price"]), _f(f["exp_change"]), fee, ship) < net_min:
                continue
            opps += 1
        rows = store.select("collection", {"select": "*", "user_id": f"eq.{uid}"})
        items = []
        if rows:
            prices = latest_map(store, [(r["product_id"], grade_key(r)) for r in rows], today)
            for r in rows:
                f = fc.get(r["product_id"], {})
                items.append({**r, "value_each": prices.get((r["product_id"], grade_key(r))),
                              "p_up": f.get("p_up"), "p_down": f.get("p_down")})
        attn = attention(items)
        if not opps and not attn:
            continue
        parts = []
        if opps:
            parts.append(f"{opps} nieuwe {'kans' if opps == 1 else 'kansen'} met minstens {int(config.DIGEST_MIN_P_UP * 100)}% kans op +{pct}%.")
        if attn:
            parts.append(f"{len(attn)} {'item' if len(attn) == 1 else 'items'} in je collectie {'vraagt' if len(attn) == 1 else 'vragen'} aandacht.")
        if _push(store, sender, user_subs, {"title": "Pokédeals", "body": " ".join(parts), "url": "./", "tag": "digest"}):
            sent += 1
    log(f"Samenvatting: {sent} verstuurd")
    return sent
