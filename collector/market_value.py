"""Waarde van een kaart uit de aanbiedingen, elke dag bewaard (prices: bron 'offers', grade_key 'mv').
Zelfde regel als v_market in de database en marketValue in docs/js/model.js:
  alleen Engels; aanbiedingen van de app-gebruikers zelf (user_settings.cm_name) tellen niet mee; alleen de uitvoering van de
  goedkoopste (Normal en Reverse Holofoil kunnen ver uit elkaar liggen); elke verkoper één keer (zijn goedkoopste); de 10
  goedkoopste; prijzen boven 2x de mediaan daarvan vallen weg (absurde vraagprijzen); dan het gemiddelde.
Zo bouwen we een geschiedenis op van wat een kaart echt opbrengt, voor de pijl over 30 dagen en de grafiek."""
from statistics import median

TOP_N = 10
MAX_AGE_DAYS = 4   # aanbiedingen worden om de paar dagen ververst; oudere tellen niet meer als 'vandaag'


def value(offers, own_names=()):
    own = {n.strip().lower() for n in own_names if n}
    xs = sorted((o for o in offers if (o.get("language") or "EN") == "EN" and (o.get("seller") or "").lower() not in own and o.get("price") is not None),
                key=lambda o: (float(o["price"]), o.get("rank") or 0))
    if not xs:
        return None, 0
    variant, seen, ref = xs[0].get("variant"), set(), []
    for o in xs:
        key = (o.get("seller") or "").lower() or f"#{o.get('rank')}"
        if o.get("variant") != variant or key in seen:
            continue
        seen.add(key)
        ref.append(float(o["price"]))
    top = ref[:TOP_N]
    mid = median(top)
    top = [p for p in top if p <= 2 * mid]
    return round(sum(top) / len(top), 2), len(top)


def run(store, today, log=print):
    from datetime import date, timedelta
    since = (date.fromisoformat(today) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    own = [r.get("cm_name") for r in store.select("user_settings", {"select": "cm_name", "cm_name": "not.is.null"})]
    by = {}
    for o in store.select("offers", {"select": "product_id,rank,price,seller,language,variant,date", "date": f"gte.{since}", "order": "product_id.asc,rank.asc"}):
        by.setdefault(o["product_id"], []).append(o)
    rows = []
    for pid, offs in by.items():
        v, n = value(offs, own)
        if v:
            rows.append({"product_id": pid, "date": today, "source": "offers", "grade_key": "mv", "price": v})
    for i in range(0, len(rows), 500):
        store.upsert("prices", rows[i:i + 500], "product_id,date,source,grade_key")
    log(f"Waarde uit aanbiedingen: {len(rows)} kaarten bewaard (gemiddelde van de {TOP_N} goedkoopste).")
    return len(rows)
