"""Hoe ver gaat de Near Mint-geschiedenis van PkmnPrices terug? (controle of 'period' langer dan 90 dagen werkt)"""
import os
import sys
from datetime import date, timedelta

from store import SupabaseStore

store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
L = ["# Diepte Near Mint-geschiedenis", ""]
for days in (60, 90, 100, 120, 150, 180, 365):
    d = (date.today() - timedelta(days=days)).isoformat()
    rows = store.select("prices", {"select": "product_id", "source": "eq.pkmnprices", "grade_key": "eq.nm", "date": f"lt.{d}", "limit": "1"})
    L.append(f"- punten ouder dan {days} dagen ({d}): {'ja' if rows else 'nee'}")
oldest = store.select("prices", {"select": "product_id,date", "source": "eq.pkmnprices", "grade_key": "eq.nm", "order": "date.asc", "limit": "3"})
L.append(f"- oudste punten: {oldest}")
hd = store.select("products", {"select": "nm_hist_days", "nm_hist_days": "gt.90"})
L.append(f"- kaarten met opgehaalde diepte > 90 dagen (nm_hist_days): {len(hd)}; waarden: {sorted({r['nm_hist_days'] for r in hd})}")
text = "\n".join(L) + "\n"
os.makedirs("../reports", exist_ok=True)
open(sys.argv[1] if len(sys.argv) > 1 else "../reports/diag_today.md", "w").write(text)
print(text)
