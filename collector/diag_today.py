"""Controle van de dagelijkse update: wat stond er vandaag in de database (advies, meldingen, app_status). Schrijft een verslag."""
import os
import sys
from datetime import date, timedelta

import advice
import alerts
import config
from store import SupabaseStore


class DrySender:
    """Verstuurt niets, onthoudt alleen wat er verstuurd zou worden."""
    def __init__(self):
        self.sent = []

    def send(self, sub, payload):
        self.sent.append(payload)
        return "ok"


def main(out):
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    today = date.today().isoformat()
    yday = (date.today() - timedelta(days=1)).isoformat()
    L = [f"# Controle dagelijkse update ({today})", ""]
    try:
        st = store.select("app_status", {"select": "*"})
        L.append(f"- app_status: {st if st else 'tabel bestaat, maar nog leeg'}")
    except Exception as e:
        L.append(f"- app_status: NIET LEESBAAR ({str(e)[:150]}) -> SQL nog niet gedraaid?")
    for d in (yday, today):
        rows = store.select("advice", {"select": "state,basis,flags,context,price,normal,control", "date": f"eq.{d}"})
        by = {}
        for r in rows:
            k = (r["state"], r.get("basis"))
            by[k] = by.get(k, 0) + 1
        flags = {}
        for r in rows:
            for f in r.get("flags") or []:
                flags[f] = flags.get(f, 0) + 1
        nm = [r for r in rows if r.get("basis") == "nm"]
        strong = [r for r in rows if r["state"] == "laag" and not r.get("context") and not r.get("flags") and r.get("price") and float(r["price"]) >= config.ADVICE_MIN_BUY
                  and r.get("normal") and advice.buy_gain(float(r["price"]), float(r["normal"])) >= config.NOTIFY_DEAL_GAIN]
        buy = [r for r in rows if r["state"] == "laag" and not r.get("context") and not r.get("flags") and r.get("price") and float(r["price"]) >= config.ADVICE_MIN_BUY
               and r.get("normal") and advice.buy_gain(float(r["price"]), float(r["normal"])) >= config.ADVICE_BUY_GAIN]
        L += ["", f"## Advies {d}: {len(rows)} rijen", "",
              "- per toestand/basis: " + ", ".join(f"{s}/{b}: {n}" for (s, b), n in sorted(by.items(), key=lambda x: str(x))),
              f"- waarschuwingen: {flags}",
              f"- op Near Mint beoordeeld: {len(nm)} (" + ", ".join(f"{s}: {sum(1 for r in nm if r['state'] == s)}" for s in ('laag', 'hoog', 'normaal', 'verdacht')) + ")",
              f"- deals (Good buy): {len(buy)}; sterke deals (>= {config.NOTIFY_DEAL_GAIN:.0%}): {len(strong)}",
              f"- controlegroep: {sum(1 for r in rows if r.get('control'))}"]
    subs = store.select("push_subscriptions", {"select": "user_id"})
    L += ["", f"## Meldingen", "", f"- toestellen met meldingen aan: {len(subs)}"]
    snd = DrySender()
    try:
        n = alerts.send_digest(store, snd, today, log=lambda *a: None)
        L.append(f"- adviesmelding (proef, niets verstuurd): naar {n} gebruiker(s)")
        for p in snd.sent:
            L.append(f"  - \"{p['body']}\"")
    except Exception as e:
        L.append(f"- adviesmelding proef mislukt: {e}")
    stats = store.select("advice_stats", {"select": "*"})
    L += ["", "## Advies-controle (na 30 dagen)", "", "- " + "; ".join(f"{s['state']} {s['hits']}/{s['n']}" for s in stats if s.get("source") == "live")]
    text = "\n".join(L) + "\n"
    with open(out, "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../reports/diag_today.md")
