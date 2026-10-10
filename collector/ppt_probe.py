"""Hoe ver gaat de prijsgeschiedenis bij PokemonPriceTracker terug, en wat kost dat? Verslag naar ../reports/ppt_probe.md."""
import os
from ppt import PPT, _items, parse_item
out = []; p = lambda *a: (print(*a), out.append(" ".join(str(x) for x in a)))
pk = PPT(os.environ["PPT_API_KEY"], budget=200)
for tid in ("96392", "490294"):
    for days in (180, 365, 730, 1825):
        before = pk.credits
        try:
            raw = pk._get("/cards", {"tcgPlayerId": tid, "includeHistory": "true", "days": days})
            d = (_items(raw) or [{}])[0]; it = parse_item(d)
            h = it.get("history") or []
            ds = sorted(x.get("date") for x in h if isinstance(x, dict) and x.get("date"))
            p(f"- kaart {tid} ({it.get('name')}), gevraagd {days} d: {len(h)} punten, van {ds[0] if ds else '-'} tot {ds[-1] if ds else '-'}; credits {pk.credits - before}")
        except Exception as e:
            p(f"- kaart {tid}, {days} d: FOUT {str(e)[:200]}")
p(f"\ncredits totaal {pk.credits}; nog over vandaag: {pk.remaining}")
os.makedirs("../reports", exist_ok=True)
open("../reports/ppt_probe.md", "w").write("# PPT historie-proef\n\n" + "\n".join(out) + "\n")
