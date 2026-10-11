"""Waarom geven sommige gekoppelde collectiekaarten 0 aanbiedingen? Kaartdetail + aanbiedingen zonder filter. Geen verkopersnamen."""
import os, json
from collections import Counter
from pkmnprices import PkmnPrices
pk = PkmnPrices(os.environ["PKMN_API_KEY"], budget=300)
out = []; p = lambda *a: (print(*a), out.append(" ".join(str(x) for x in a)))
for pid, kid in (("base1-52", 12845), ("pl3-20", 18803)):
    p(f"\n## {pid} (pk {kid})")
    try:
        d = pk.detail(f"/cards/{kid}")
        keep = {k: v for k, v in (d or {}).items() if k not in ("image", "images", "prices", "price_history")}
        p("detail:", json.dumps(keep, default=str)[:900])
        p("prices-sleutels:", list(((d or {}).get("prices") or {}).keys())[:20] if isinstance((d or {}).get("prices"), dict) else type((d or {}).get("prices")).__name__)
    except Exception as e:
        p("detail FOUT", str(e)[:200])
    for params, pp_, mp in (({}, 100, 3), ({"condition": "Near Mint"}, 50, 1), ({"condition": "near_mint"}, 20, 1), ({"condition": "NM"}, 20, 1)):
        try:
            rows = pk.list_all(f"/cards/{kid}/listings/cardmarket", params, per_page=pp_, max_pages=mp)
            prices = sorted(float(r["price"]) for r in rows if r.get("price"))
            p(f"  prijzen van {prices[0] if prices else '-'} tot {prices[-1] if prices else '-'}; NM-prijzen {sorted(float(r['price']) for r in rows if (r.get('condition') or '').lower()=='near mint')[:5]}")
            p(f"listings {params}: {len(rows)}; condities {dict(Counter(r.get('condition') for r in rows))}; talen {dict(Counter(r.get('language') for r in rows))}")
        except Exception as e:
            p(f"listings {params}: FOUT {str(e)[:200]}")
p(f"\ncredits {pk.credits}")
os.makedirs("../reports", exist_ok=True)
open("../reports/pk_fix_probe.md", "w").write("\n".join(out) + "\n")
