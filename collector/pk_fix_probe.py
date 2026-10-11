"""Collectiekaarten zonder aanbiedingen: koppeling zoeken (geen pk_id) of nagaan of er Engelse NM-aanbiedingen zijn. Verslag zonder verkopersnamen."""
import os
from collections import Counter
from pkmnprices import PkmnPrices
from store import SupabaseStore
st = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
pk = PkmnPrices(os.environ["PKMN_API_KEY"], budget=600)
UNMAPPED = ["30th-c-029", "30th-c-027", "swshp-SWSH138", "cel25cc-CC008", "swshp-SWSH144", "cel25cc-CC015"]
MAPPED = ["swshp-SWSH301", "sv04-208", "me02.5-269", "sv10-190", "me01-137", "sv10-191", "sm9-113", "sv04-189", "base1-52", "swsh11tg-TG03", "pl3-20", "dp2-5", "smp-SM247"]
out = []; p = lambda *a: (print(*a), out.append(" ".join(str(x) for x in a)))
prod = {r["product_id"]: r for r in st.select("products", {"select": "*", "product_id": "in.(" + ",".join(f'"{x}"' for x in UNMAPPED + MAPPED) + ")"})}
p("# Koppeling en aanbiedingen\n\n## Zonder koppeling")
for pid in UNMAPPED:
    r = prod[pid]; p(f"\n### {pid}: {r['name']} | {r['set_name']} | nr {r['number']}")
    name = r["name"].replace("☆", "Star").replace("_____'s", "").replace("C", "C").strip()
    for q in ({"name": name}, {"name": r["name"].split()[0]}):
        try:
            rows = pk.list_all("/cards", {**q, **({"set": "Celebrations"} if pid.startswith("cel") else {})}, per_page=15, max_pages=1) if False else pk.list_all("/cards", q, per_page=15, max_pages=1)
        except Exception as e:
            p(f"- {q}: FOUT {str(e)[:120]}"); continue
        for c in rows:
            s = c.get("set") if isinstance(c.get("set"), str) else (c.get("set") or {}).get("name") if isinstance(c.get("set"), dict) else c.get("set_name")
            p(f"- [{q['name']}] id {c.get('id')} | {c.get('name')} | {s or c.get('set_name') or c.get('setName')} | nr {c.get('number') or c.get('card_number')}")
p("\n## Met koppeling: aanbiedingen nu")
for pid in MAPPED:
    r = prod[pid]
    try:
        data = pk.list_all(f"/cards/{r['pk_id']}/listings/cardmarket", {"condition": "Near Mint"}, per_page=20, max_pages=1)
    except Exception as e:
        p(f"- {pid} {r['name']}: FOUT {str(e)[:120]}"); continue
    p(f"- {pid} {r['name']}: {len(data)} NM-aanbiedingen; talen {dict(Counter(d.get('language') for d in data))}; varianten {dict(Counter(d.get('variant') for d in data))}")
p(f"\ncredits {pk.credits}")
os.makedirs("../reports", exist_ok=True)
open("../reports/pk_fix_probe.md", "w").write("\n".join(out) + "\n")
