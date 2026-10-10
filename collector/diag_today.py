"""Export voor de import van aankopen/verkopen: kaartcatalogus + eigen collectie/verkopen.
Alles wordt in de workflow versleuteld (publieke sleutel collector/export_pub.pem) voordat het in de repo komt."""
import gzip
import json
import os
import sys

from store import SupabaseStore

store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
out = {
    "sets": store.select("sets", {"select": "set_id,name,release_date,card_total"}),
    "products": store.select("products", {"select": "product_id,kind,name,set_id,set_name,number,set_total,rarity", "order": "product_id.asc"}),
    "collection": store.select("collection", {"select": "*"}),
    "sales": store.select("sales", {"select": "*"}),
    "sale_items": store.select("sale_items", {"select": "*"}),
    "advice": store.select("advice", {"select": "*", "date": "gte." + __import__("datetime").date.fromordinal(__import__("datetime").date.today().toordinal() - 2).isoformat()}),
    "prices": store.select("v_search", {"select": "product_id,price", "price": "not.is.null"}),
}
ids = sorted({c["product_id"] for c in out["collection"]} | {"swsh12.5gg-GG10", "pl3-20", "swshp-SWSH184", "svp-085", "sv04.5-232", "swsh12.5gg-GG44"})
out["offers"] = []
for i in range(0, len(ids), 40):
    out["offers"] += store.select("offers", {"select": "*", "product_id": "in.(" + ",".join(ids[i:i + 40]) + ")"})
print({k: len(v) for k, v in out.items()})
with gzip.open(sys.argv[1], "wt") as f:
    json.dump(out, f, default=str)
# export 2026-10-10T12:24:33
