"""Eenmalig: twee Cardmarket-aankopen (14-10-2026) toevoegen aan collection. Veilig om opnieuw te draaien (slaat bestaande bestellingen over)."""
import os, sys, requests

URL = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY = os.environ["SUPABASE_SECRET_KEY"]
H = {"apikey": KEY, "Content-Type": "application/json"}
if KEY.startswith("eyJ"):
    H["Authorization"] = f"Bearer {KEY}"

ORDERS = [
    {"order": "cm-rusk1turbo-2026-10-03", "seller": "Rusk1turbo", "date": "2026-10-03", "ship": 19.20, "costs": 0.95,
     "lines": [{"cm": "Charizard (30C BS4%", "name": "Charizard", "number": "4", "price": 190.00}]},
    {"order": "cm-1306567466", "seller": "Barbunelce", "date": "2026-10-08", "ship": 9.65, "costs": 0.21,
     "lines": [{"cm": "Mewtwo (EVO 51)%", "name": "Mewtwo", "number": "51", "set": "Evolutions", "price": 1.25},
               {"cm": "Pidgeot V (LOR 137)%", "name": "Pidgeot V", "number": "137", "set": "Lost Origin", "price": 0.50},
               {"cm": "Pikachu (CRZ GG30)%", "name": "Pikachu", "number": "GG30", "set": "Crown Zenith", "price": 40.00}]},
]


def get(path, params):
    r = requests.get(f"{URL}/{path}", headers=H, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def allocate(total, weights):
    s = sum(weights)
    out = [round(w / s * total, 2) for w in weights]
    out[-1] = round(total - sum(out[:-1]), 2)
    return out


def find(line):
    sel = "product_id,name,set_name,number,cm_name,kind"
    rows = get("products", {"select": sel, "cm_name": f"ilike.{line['cm']}", "kind": "eq.card"})
    if len(rows) != 1:
        alt = get("products", {"select": sel, "name": f"ilike.{line['name']}", "number": f"ilike.{line['number']}", "kind": "eq.card"})
        if line.get("set"):
            alt = [p for p in alt if line["set"].lower() in (p.get("set_name") or "").lower()]
        print(f"  cm_name gave {len(rows)}, fallback gave {len(alt)}: {alt}")
        rows = alt if len(alt) == 1 else rows
    print(f"  {line['cm']} -> {rows}")
    return rows


users = {r["user_id"] for r in get("collection", {"select": "user_id", "limit": "1000"})}
print("users:", users)
if len(users) != 1:
    sys.exit("Expected exactly one user in collection")
uid = users.pop()

plan = []
for o in ORDERS:
    if get("collection", {"select": "id", "purchase_order": f"eq.{o['order']}"}):
        print(f"{o['order']} already exists, skipping"); continue
    prods = [find(l) for l in o["lines"]]
    if any(len(p) != 1 for p in prods):
        print(f"Ambiguous or missing product in {o['order']}; order skipped"); continue
    w = [l["price"] for l in o["lines"]]
    sh, co = allocate(o["ship"], w), allocate(o["costs"], w)
    for i, l in enumerate(o["lines"]):
        plan.append({"user_id": uid, "product_id": prods[i][0]["product_id"], "quantity": 1, "condition": "NM",
                     "grade_company": None, "grade": None, "purchase_price": l["price"], "purchase_date": o["date"],
                     "purchase_shipping": sh[i], "purchase_costs": co[i], "purchase_seller": o["seller"], "purchase_order": o["order"]})

for p in plan:
    print("INSERT", p)
if plan:
    r = requests.post(f"{URL}/collection", headers={**H, "Prefer": "return=representation"}, json=plan, timeout=60)
    print(r.status_code, r.text)
    r.raise_for_status()
print("done")
print("30C in db:", get("products", {"select": "product_id,name,set_name,number,cm_name", "or": "(cm_name.ilike.*30C*,set_name.ilike.*30th*,set_name.ilike.*Classic Coll*)", "limit": "20"}))
try:
    sets = requests.get("https://api.tcgdex.net/v2/en/sets", timeout=30).json()
    print("tcgdex:", [(x["id"], x["name"]) for x in sets if "30" in x["name"] or "elebrat" in x["name"] or x["id"].startswith("me")])
except Exception as e:
    print("tcgdex err", e)
