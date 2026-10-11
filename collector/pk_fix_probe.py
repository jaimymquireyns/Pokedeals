"""Kandidaat-koppelingen voor collectiekaarten zonder pk_id: aanbiedingen nagaan, en de verjaardags-Pikachu zoeken."""
import os
from collections import Counter
from pkmnprices import PkmnPrices
pk = PkmnPrices(os.environ["PKMN_API_KEY"], budget=300)
out = []; p = lambda *a: (print(*a), out.append(" ".join(str(x) for x in a)))
for pid, kid in (("swshp-SWSH138", 26541), ("swshp-SWSH144", 26604), ("cel25cc-CC015", 16901)):
    d = pk.detail(f"/cards/{kid}")
    rows = pk.list_all(f"/cards/{kid}/listings/cardmarket", {"condition": "Near Mint"}, per_page=20, max_pages=1)
    p(f"- {pid} -> {kid}: {d.get('name')} | {(d.get('set') or {}).get('name')} | cm {d.get('cardmarket_url')} | NM-aanbiedingen {len(rows)}, talen {dict(Counter(r.get('language') for r in rows))}")
for q in ({"name": "Birthday Pikachu"}, {"name": "'s Pikachu"}, {"name": "Pikachu", "number": "24"}, {"name": "Lugia", "number": "029"}, {"name": "Arceus VSTAR", "number": "027"}):
    try:
        rows = pk.list_all("/cards", q, per_page=10, max_pages=1)
        p(f"- zoek {q}: " + "; ".join(f"{c.get('id')} {c.get('name')} [{(c.get('set') or {}).get('name') if isinstance(c.get('set'), dict) else c.get('set')}] nr {c.get('number')}" for c in rows))
    except Exception as e:
        p(f"- zoek {q}: FOUT {str(e)[:100]}")
p(f"\ncredits {pk.credits}")
os.makedirs("../reports", exist_ok=True)
open("../reports/pk_fix_probe.md", "w").write("\n".join(out) + "\n")
