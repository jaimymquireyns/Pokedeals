"""Versleutelde export van de eigen verkopen (laatste eerst) met kaartnamen, voor de sessie die de privésleutel heeft."""
import json, os
from store import SupabaseStore
UID = "43f56a30-d159-4c16-b093-f7d95f7d0039"
st = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
q = {"user_id": f"eq.{UID}", "select": "*"}
sales = st.select("sales", dict(q, order="created_at.desc"))
items = st.select("sale_items", q)
coll = st.select("collection", dict(q, order="created_at.desc"))
settings = st.select("user_settings", q)
pids = sorted({i["product_id"] for i in items if i.get("product_id")} | {c["product_id"] for c in coll})
names = {}
for i in range(0, len(pids), 100):
    for p in st.select("products", {"select": "product_id,name,set_name,number", "product_id": "in.(" + ",".join(f'"{x}"' for x in pids[i:i+100]) + ")"}):
        names[p["product_id"]] = p
extra = {}
for pre in ("30th-", "mep-", "swshp-SWSH2", "swshp-SWSH1"):
    for p in st.select("products", {"select": "product_id,name,set_name,number", "product_id": f"like.{pre}*"}):
        extra[p["product_id"]] = p
names.update(extra)
json.dump({"sales": sales, "items": items, "products": names, "collection": coll, "settings": settings}, open("/tmp/sales.json", "w"), default=str)
print("verkopen:", len(sales), "regels:", len(items), "collectie:", len(coll))
