"""Opslag in Supabase via de REST-interface (PostgREST). Geen extra bibliotheek nodig."""
import time

import requests

PAGE = 1000


class SupabaseStore:
    def __init__(self, url, key, session=None):
        self.base = url.rstrip("/") + "/rest/v1"
        self.s = session or requests.Session()
        self.s.headers.update({"apikey": key, "Content-Type": "application/json"})
        # Oude sleutels zijn JWT's ('eyJ...') en horen ook in Authorization; nieuwe 'sb_secret_...'-sleutels niet.
        if key.startswith("eyJ"):
            self.s.headers["Authorization"] = f"Bearer {key}"

    # ---- basis ----
    def _get(self, url, params, timeout):
        """Eén verzoek, met één keer opnieuw proberen (langere wachttijd) als de verbinding traag is of wegvalt."""
        try:
            r = self.s.get(url, params=params, timeout=timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(3)
            r = self.s.get(url, params=params, timeout=timeout * 2)
        r.raise_for_status()
        return r

    def select(self, table, params=None):
        rows, offset = [], 0
        while True:
            q = dict(params or {})
            q.update({"limit": PAGE, "offset": offset})
            page = self._get(f"{self.base}/{table}", q, 90).json()
            rows.extend(page)
            if len(page) < PAGE:
                return rows
            offset += PAGE

    def upsert(self, table, rows, on_conflict, chunk=500):
        for i in range(0, len(rows), chunk):
            r = self.s.post(f"{self.base}/{table}", params={"on_conflict": on_conflict},
                            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                            json=rows[i:i + chunk], timeout=90)
            if not r.ok:
                raise RuntimeError(f"Supabase {table}: {r.status_code} {r.text[:300]}")

    def insert(self, table, rows, chunk=500):
        for i in range(0, len(rows), chunk):
            r = self.s.post(f"{self.base}/{table}", headers={"Prefer": "return=minimal"}, json=rows[i:i + chunk], timeout=90)
            if not r.ok:
                raise RuntimeError(f"Supabase {table}: {r.status_code} {r.text[:300]}")

    def patch(self, table, params, data):
        r = self.s.patch(f"{self.base}/{table}", params=params, headers={"Prefer": "return=minimal"}, json=data, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Supabase {table}: {r.status_code} {r.text[:300]}")

    def delete(self, table, params):
        r = self.s.delete(f"{self.base}/{table}", params=params, timeout=90)
        if not r.ok:
            raise RuntimeError(f"Supabase {table}: {r.status_code} {r.text[:300]}")

    # ---- handige combinaties ----
    def known_sets(self):
        return {r["set_id"]: r for r in self.select("sets", {"select": "set_id,name,release_date", "order": "set_id.asc"})}

    def upsert_sets(self, rows):
        self.upsert("sets", rows, "set_id")

    def upsert_products(self, rows):
        cols = ("product_id", "kind", "name", "set_id", "set_name", "number", "set_total", "rarity", "image",
                "category", "product_type", "dex_id", "regulation_mark", "legal_standard", "ppt_id",
                "printings", "newer_printing", "pk_id")
        self.upsert("products", [{k: r.get(k) for k in cols if k in r} for r in rows], "product_id")

    def upsert_prices(self, rows):
        self.upsert("prices", rows, "product_id,date,source,grade_key")

    def latest_prices(self):
        rows = self.select("latest_prices", {"select": "product_id,date,price", "order": "product_id.asc"})
        return {r["product_id"]: r for r in rows}

    def price_rows(self, since, grade_key="raw"):
        return self.select("prices", {
            "select": "product_id,date,source,price,avg1,avg7,avg30,low",
            "date": f"gte.{since}", "grade_key": f"eq.{grade_key}",
            "order": "product_id.asc,date.asc,source.asc"})

    def products(self, kind=None, extra=None):
        p = {"select": "*", "order": "product_id.asc"}
        if kind:
            p["kind"] = f"eq.{kind}"
        p.update(extra or {})
        return self.select("products", p)
