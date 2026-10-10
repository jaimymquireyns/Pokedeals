"""Proef: kunnen we Engelse Cardmarket-aanbiedingen ophalen voor sealed (ETB, bundle, booster box)?
Schrijft een kort verslag zonder verkopersnamen naar ../reports/sealed_probe.md."""
import os, re, sys
from collections import Counter
from pkmnprices import PkmnPrices
from store import SupabaseStore

TYPES = {"etb": re.compile(r"elite trainer box|\betb\b", re.I), "bundle": re.compile(r"booster bundle|\bbundle\b", re.I),
         "box": re.compile(r"booster box|\bdisplay\b", re.I)}
out = []
p = out.append
store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
prods = store.products("sealed")
p(f"# Sealed proef\n\nSealed producten in database: {len(prods)}, met pk_id: {sum(1 for x in prods if x.get('pk_id'))}\n")
for t, rx in TYPES.items():
    m = [x for x in prods if rx.search(x.get("name") or "")]
    p(f"- {t}: {len(m)} (met pk_id {sum(1 for x in m if x.get('pk_id'))}); voorbeelden: {[x['name'] for x in m[:6]]}")
pk = PkmnPrices(os.environ["PKMN_API_KEY"], budget=400)
picks = []
for t, rx in TYPES.items():
    m = sorted([x for x in prods if rx.search(x.get("name") or "") and x.get("pk_id")], key=lambda x: x.get("name"))
    picks += [(t, x) for x in m[-2:]]
for t, x in picks:
    p(f"\n## {t}: {x['name']} ({x['product_id']}, pk {x['pk_id']})")
    for path, params in [(f"/sealed/{x['pk_id']}/listings/cardmarket", {}), (f"/sealed/{x['pk_id']}/listings/cardmarket", {"language": "English"})]:
        try:
            body = pk.call(path, {**params, "per_page": 20})
        except Exception as e:
            p(f"- {path} {params}: FOUT {str(e)[:200]}"); continue
        rows = body.get("data") if isinstance(body, dict) else body
        rows = rows if isinstance(rows, list) else []
        p(f"- {path} {params}: {len(rows)} rijen; sleutels: {sorted(rows[0].keys()) if rows else (list(body.keys()) if isinstance(body, dict) else type(body).__name__)}")
        p(f"  talen: {dict(Counter(r.get('language') for r in rows))}; condities: {dict(Counter(r.get('condition') for r in rows))}")
        p(f"  prijzen (taal): {[(r.get('price'), r.get('language')) for r in rows[:20]]}")
        if params: break
p(f"\ncredits: {pk.credits}")
os.makedirs("../reports", exist_ok=True)
open("../reports/sealed_probe.md", "w").write("\n".join(out))
print("\n".join(out))
