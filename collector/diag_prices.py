"""Diagnose: wat staat er in de database en wat geeft TCGdex nu, voor een paar kaarten. Schrijft ../reports/diag_prices.md."""
import json, os, sys
import requests
from store import SupabaseStore

ids = sys.argv[1:] or ["ecard3-27"]
s = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
L = ["# Diagnose prijzen", ""]
for pid in ids:
    L += [f"## {pid}", "", "Database (laatste 5 dagen, alle bronnen):", ""]
    for r in s.select("prices", {"select": "date,source,grade_key,price,avg1,avg7,avg30,low", "product_id": f"eq.{pid}", "order": "date.desc", "limit": 12}):
        L.append(f"- {r}")
    L += ["", "Aanbiedingen:", ""]
    for o in s.select("offers", {"select": "rank,price,seller,language,variant,date", "product_id": f"eq.{pid}", "order": "rank.asc"}):
        L.append(f"- {o}")
    try:
        d = requests.get(f"https://api.tcgdex.net/v2/en/cards/{pid}", timeout=30).json()
        L += ["", "TCGdex nu:", "", "```", json.dumps({"name": d.get("name"), "rarity": d.get("rarity"), "variants": d.get("variants"),
                                                       "cardmarket": (d.get("pricing") or {}).get("cardmarket")}, indent=1), "```"]
    except Exception as e:
        L.append(f"TCGdex fout: {e}")
    L.append("")
os.makedirs("../reports", exist_ok=True)
open("../reports/diag_prices.md", "w").write("\n".join(L) + "\n")
print("\n".join(L))
