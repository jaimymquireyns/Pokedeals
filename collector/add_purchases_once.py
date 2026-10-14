"""Eenmalig: Pikachu (CRZ GG30) uit de collectie halen, is voor de persoonlijke collectie."""
import os, requests
URL = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY = os.environ["SUPABASE_SECRET_KEY"]
H = {"apikey": KEY, "Content-Type": "application/json", "Prefer": "return=representation"}
if KEY.startswith("eyJ"):
    H["Authorization"] = f"Bearer {KEY}"
r = requests.delete(f"{URL}/collection", headers=H, params={"id": "eq.2eb60ca8-08ee-4ac5-b975-0eab01501435", "product_id": "eq.swsh12.5gg-GG30"}, timeout=60)
print(r.status_code, r.text)
r.raise_for_status()
print("left in order:", requests.get(f"{URL}/collection", headers=H, params={"select": "product_id,purchase_price,purchase_shipping,purchase_costs", "purchase_order": "eq.cm-1306567466"}, timeout=60).json())
