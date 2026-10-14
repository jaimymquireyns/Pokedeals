"""Controle: waar staan de aankopen van Rusk1turbo en Barbunelce?"""
import os, json, requests
URL = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY = os.environ["SUPABASE_SECRET_KEY"]
H = {"apikey": KEY}
if KEY.startswith("eyJ"):
    H["Authorization"] = f"Bearer {KEY}"
g = lambda t, p: requests.get(f"{URL}/{t}", headers=H, params=p, timeout=60).json()
print("collection:", json.dumps(g("collection", {"select": "*", "or": "(purchase_seller.ilike.*rusk*,purchase_seller.ilike.*barbun*,product_id.in.(30th-c-001,xy12-51,swsh11-137,swsh12.5gg-GG30))"}), indent=1))
print("sales recent:", json.dumps(g("sales", {"select": "*", "order": "created_at.desc", "limit": "5"}), indent=1))
print("sale_items match:", json.dumps(g("sale_items", {"select": "*", "or": "(purchase_seller.ilike.*rusk*,purchase_seller.ilike.*barbun*,product_id.in.(30th-c-001,xy12-51,swsh11-137,swsh12.5gg-GG30))"}), indent=1))
print("sale_items recent:", json.dumps(g("sale_items", {"select": "*", "order": "id.desc", "limit": "3"}), indent=1))
