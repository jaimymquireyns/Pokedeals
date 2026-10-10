"""Samenvatting van de dagelijkse controle (model_checks) naar ../reports/check_report.md."""
import os
from collections import Counter
from store import SupabaseStore
st = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
days = st.select("v_model_checks_daily", {"select": "*", "order": "check_date.desc"})
rows = st.select("model_checks", {"select": "*", "check_date": f"eq.{days[0]['check_date']}"}) if days else []
out = ["# Dagelijkse controle", "", str(days), "", f"rijen: {len(rows)}",
       "richting (voorspeld, echt): " + str(Counter((r['dir_pred'], r['dir_actual']) for r in rows).most_common()),
       "basis: " + str(Counter(r['basis'] for r in rows))]
ch = sorted(float(r["actual"]) / float(r["price_then"]) - 1 for r in rows)
pr = sorted(float(r["predicted"]) / float(r["price_then"]) - 1 for r in rows)
if ch:
    q = lambda xs, p: xs[int(p * (len(xs) - 1))]
    out.append(f"echte verandering: p10 {q(ch,.1):+.1%} mediaan {q(ch,.5):+.1%} p90 {q(ch,.9):+.1%}")
    out.append(f"voorspelde verandering: p10 {q(pr,.1):+.1%} mediaan {q(pr,.5):+.1%} p90 {q(pr,.9):+.1%}")
os.makedirs("../reports", exist_ok=True)
open("../reports/check_report.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
