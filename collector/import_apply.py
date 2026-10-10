"""Eenmalige import van aankopen/verkopen (plan.json, lokaal opgesteld en door de gebruiker goedgekeurd).
1) backup van collection/sales/sale_items van de gebruiker  2) controle dat er sinds het plan niets veranderde  3) schrijven."""
import json, os, sys
from store import SupabaseStore

plan = json.load(open(sys.argv[1]))
backup_path, log_path = sys.argv[2], sys.argv[3]
UID = "43f56a30-d159-4c16-b093-f7d95f7d0039"
st = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
log = []
def say(*a):
    print(*a); log.append(" ".join(str(x) for x in a))
q = {"user_id": f"eq.{UID}", "select": "*"}
backup = {"collection": st.select("collection", q), "sales": st.select("sales", q), "sale_items": st.select("sale_items", q)}
json.dump(backup, open(backup_path, "w"), default=str)
say("backup:", {k: len(v) for k, v in backup.items()})
ids = {c["id"] for c in backup["collection"]}
need = set(plan["delete_collection"]) | set(plan["delete_collection_extra"]) | {u["id"] for u in plan["update_collection"]}
if len(backup["collection"]) != 78 or len(backup["sales"]) != 3 or not need <= ids:
    say("STOP: database veranderd sinds het plan", len(backup["collection"]), len(backup["sales"]), len(need - ids))
    json.dump(log, open(log_path, "w")); sys.exit(1)
try:
    for sid in plan["delete_sales"]:
        st.delete("sale_items", {"sale_id": f"eq.{sid}"}); st.delete("sales", {"id": f"eq.{sid}"})
    say("oude verkopen weg:", len(plan["delete_sales"]))
    dels = plan["delete_collection"] + plan["delete_collection_extra"]
    for i in range(0, len(dels), 50):
        st.delete("collection", {"id": f"in.({','.join(dels[i:i + 50])})"})
    say("collectie-rijen weg:", len(dels))
    for u in plan["update_collection"]:
        data = {"purchase_price": u["purchase_price"]}
        if u.get("purchase_seller"): data["purchase_seller"] = u["purchase_seller"]
        st.patch("collection", {"id": f"eq.{u['id']}"}, data)
    say("collectie-rijen aangepast:", len(plan["update_collection"]))
    cols = ("product_id", "quantity", "condition", "purchase_price", "purchase_shipping", "purchase_costs", "purchase_date", "purchase_seller", "purchase_order")
    rows = [dict({k: r[k] for k in cols}, user_id=UID) for r in plan["insert_collection"]]
    st.insert("collection", rows)
    say("collectie-rijen erbij:", len(rows))
    sales, items = [], []
    for s in plan["insert_sales"]:
        sales.append({"id": s["id"], "user_id": UID, "sale_date": s["sale_date"], "buyer": s["buyer"], "total_price": s["total_price"],
                      "shipping_received": s["shipping_received"], "shipping_paid": s["shipping_paid"], "commission": s["commission"],
                      "other_costs": s["other_costs"], "note": "Cardmarket" + (" (onderweg bij import)" if s["transit"] else "")})
        for l in s["lines"]:
            items.append({"sale_id": s["id"], "user_id": UID, "product_id": l["product_id"], "quantity": l["quantity"], "condition": "NM",
                          "price_share": l["price_share"], "cost_total": l["cost_total"], "purchase_date": l["purchase_date"],
                          "purchase_seller": l.get("purchase_seller"), "purchase_order": l.get("purchase_order")})
    st.insert("sales", sales); say("verkopen erbij:", len(sales))
    st.insert("sale_items", items); say("verkoopregels erbij:", len(items))
    after = {"collection": len(st.select("collection", q)), "sales": len(st.select("sales", q)), "sale_items": len(st.select("sale_items", q))}
    say("na import:", after)
except Exception as e:
    say("FOUT:", repr(e)); json.dump(log, open(log_path, "w")); raise
json.dump(log, open(log_path, "w"))
