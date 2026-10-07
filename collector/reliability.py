"""Betrouwbaarheid van de laagste Near Mint-prijs: een aanwijzing, geen bewijs, dat een prijs mogelijk niet klopt.

Onze Near Mint-prijs is de LAAGSTE VRAAGPRIJS op Cardmarket, geen verkoopprijs. Eén verkoper kan die omhoog (een absurd hoge
laagste prijs, bijvoorbeeld door alle goedkopere exemplaren op te kopen) of omlaag (een foutje, een lokvogel) duwen. Wat we kunnen controleren,
zonder extra credits:

  afwijking          de laagste prijs is minder dan de helft of meer dan het dubbele van Cardmarkets eigen verkoopgemiddelde (echte verkopen,
                     veel moeilijker te sturen dan een vraagprijs)
  pieken             in de laatste 90 dagen moesten er veel punten uit de reeks worden gehaald (analysis.clean_nm_rows)
  springt            drie of meer keer in 60 dagen een sprong van meer dan 50% tussen twee opeenvolgende punten
  vast               de prijs staat al 7+ dagen op exact hetzelfde bedrag (vaak één verkoper die niets verandert)
  weinig verkopers   hooguit 2 verschillende verkopers onder de 5 goedkoopste aanbiedingen (alleen voor kaarten met opgehaalde aanbiedingen)

Gewicht: afwijking, pieken en springt tellen dubbel, vast en weinig verkopers enkel. Een lage of hoge prijs kan ook gewoon een dunne markt zijn.
"""
from datetime import timedelta

import analysis
from edge import _d, jump_count

WEIGHTS = {"afwijking": 2, "pieken": 2, "springt": 2, "vast": 1, "weinig verkopers": 1}


def assess(nm_rows, anchors, sellers=None):
    """nm_rows: [{'date', 'price'}]; anchors: {datum: Cardmarkets verkoopgemiddelde}; sellers: set verkopers onder de goedkoopste aanbiedingen of None."""
    pts = sorted(((r["date"], float(r["price"])) for r in nm_rows if r.get("price")), key=lambda x: x[0])
    if len(pts) < 5:
        return None
    last_d, last_p = pts[-1]
    flags, info = [], {"price": last_p, "date": last_d}
    ad = max(anchors) if anchors else None
    if ad and abs((_d(ad) - _d(last_d)).days) <= 14 and anchors[ad] > 0:
        info["ratio"] = last_p / anchors[ad]
        if info["ratio"] < 0.5 or info["ratio"] > 2.0:
            flags.append("afwijking")
    window = [r for r in nm_rows if r.get("price") and r["date"] >= (_d(last_d) - timedelta(days=90)).isoformat()]
    if len(window) >= 5:
        _, st = analysis.clean_nm_rows(window, anchors=anchors)
        removed = st["in"] - st["out"]
        info["spike_share"] = removed / max(st["in"], 1)
        if removed >= 3 and info["spike_share"] >= 0.2:
            flags.append("pieken")
    info["jumps"] = jump_count(pts)
    if info["jumps"] >= 3:
        flags.append("springt")
    run_start = last_d
    for d, p in reversed(pts):
        if abs(p - last_p) > 1e-9:
            break
        run_start = d
    info["flat_days"] = (_d(last_d) - _d(run_start)).days
    if info["flat_days"] >= 7:
        flags.append("vast")
    if sellers is not None:
        info["sellers"] = len(sellers)
        if len(sellers) <= 2:
            flags.append("weinig verkopers")
    info["flags"] = flags
    info["severity"] = sum(WEIGHTS[f] for f in flags)
    return info


def _anchors(raw_rows):
    by_source = {}
    for r in raw_rows:
        by_source.setdefault(r["source"], []).append(r)
    return analysis.anchors_from(by_source)


def report(store, inputs, products, today, log=print, top=20):
    """Telt per waarschuwing hoeveel beroemde kaarten dat hebben, noemt de verdachtste, en toont apart je eigen kaarten."""
    from signals import load_inputs
    ids, raw, nm = inputs
    sellers = {}
    try:
        for r in store.select("offers", {"select": "product_id,rank,seller"}):
            s = sellers.setdefault(r["product_id"], set())
            if r.get("seller") and (r.get("rank") or 99) <= 5:
                s.add(r["seller"])
    except Exception:
        sellers = {}
    out = {}
    for pid in ids:
        a = assess(nm.get(pid) or [], _anchors(raw.get(pid, [])), sellers.get(pid))
        if a:
            out[pid] = a
    own_ids = []
    for table in ("collection", "watch_items", "alerts"):
        try:
            own_ids += [r["product_id"] for r in store.select(table, {"select": "product_id"})]
        except Exception:
            pass
    own_ids = sorted(set(own_ids))
    own = {}
    if own_ids:
        try:
            since = (_d(today) - timedelta(days=120)).isoformat()
            o_ids, o_raw, o_nm = load_inputs(store, own_ids, since)
            for pid in o_ids:
                a = assess(o_nm.get(pid) or [], _anchors(o_raw.get(pid, [])), sellers.get(pid))
                if a:
                    own[pid] = a
        except Exception as e:
            log(f"  (eigen kaarten niet gecontroleerd: {type(e).__name__})")
    names = {p["product_id"]: p for p in store.products("card")} if (out or own) else {}

    def name(pid):
        p = names.get(pid) or products.get(pid) or {}
        return f"{p.get('name', pid)} ({p.get('set_name', '?')}{' #' + str(p['number']) if p.get('number') else ''})"

    def show(pid, a):
        ratio = f"{a['ratio']:.1f}x het verkoopgemiddelde" if a.get("ratio") is not None else "geen verkoopgemiddelde bekend"
        return f"    € {a['price']:.2f}  {name(pid)}: {ratio}; {', '.join(a['flags'])}"

    log(f"Prijsbetrouwbaarheid ({len(out)} beroemde kaarten met genoeg eigen Near Mint-geschiedenis; een aanwijzing, geen bewijs van manipulatie):")
    counts = {f: sum(1 for a in out.values() if f in a["flags"]) for f in WEIGHTS}
    log("  " + ", ".join(f"{f}: {n}" for f, n in counts.items()) + f"; {sum(1 for a in out.values() if a['severity'] >= 2)} kaarten met gewicht 2 of hoger")
    worst = sorted((x for x in out.items() if x[1]["severity"] >= 2), key=lambda x: (-x[1]["severity"], -(x[1]["price"])))[:top]
    if worst:
        log(f"  de {len(worst)} verdachtste:")
        for pid, a in worst:
            log(show(pid, a))
    if own:
        flagged = sorted((x for x in own.items() if x[1]["flags"]), key=lambda x: -x[1]["severity"])
        log(f"  je eigen kaarten (collectie, watchlist, prijsmeldingen): {len(own)} gecontroleerd, {len(flagged)} met een waarschuwing")
        for pid, a in flagged[:top]:
            log(show(pid, a))
    return out, own
