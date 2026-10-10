"""Openbare marktgegevens (geen persoonlijke data) voor modelonderzoek: Near Mint-, Cardmarket-trend- en marktwaarde-reeksen
van kaarten vanaf 3 euro, naar ../reports/prices_export.json.gz."""
import gzip, json, os
from store import SupabaseStore
st = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
ids = [r["product_id"] for r in st.select("v_search", {"select": "product_id", "kind": "eq.card", "price": "gte.3"})]
out = {}
for i in range(0, len(ids), 80):
    q = {"select": "product_id,date,source,grade_key,price,avg1,avg7,avg30,low", "grade_key": "in.(raw,nm,mv)",
         "product_id": "in.(" + ",".join(f'"{x}"' for x in ids[i:i + 80]) + ")", "order": "product_id.asc,date.asc"}
    for r in st.select("prices", q):
        out.setdefault(r["product_id"], []).append([r["date"], r["source"], r["grade_key"], r["price"], r["avg1"], r["avg7"], r["avg30"], r["low"]])
os.makedirs("../reports", exist_ok=True)
with gzip.open("../reports/prices_export.json.gz", "wt") as f:
    json.dump(out, f)
print(len(ids), "kaarten,", sum(len(v) for v in out.values()), "rijen")
