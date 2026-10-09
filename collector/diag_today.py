"""Staan er toestellen ingeschreven voor meldingen?"""
import os
import sys

from store import SupabaseStore

store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
subs = store.select("push_subscriptions", {"select": "user_id,created_at"})
text = f"# Meldingen\n\n- toestellen ingeschreven: {len(subs)}\n- laatst: {max((s.get('created_at') or '' for s in subs), default='-')}\n"
os.makedirs("../reports", exist_ok=True)
open(sys.argv[1] if len(sys.argv) > 1 else "../reports/diag_today.md", "w").write(text)
print(text)
# Fri Oct  9 18:30:14 CEST 2026
