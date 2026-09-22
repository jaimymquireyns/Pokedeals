"""Verzendkosten Cardmarket: test of de tabel op help.cardmarket.com/en/ShippingCosts automatisch is op te halen.

Die pagina toont een tabel pas nadat je zelf een land van herkomst en bestemming kiest; de cijfers komen dan ergens
vandaan (server-rendering met querystring, of een los verzoek op de achtergrond). Ik kon dat vanuit mijn eigen
omgeving niet uittesten (geen internettoegang daar), dus deze test probeert een aantal aannames en toont wat elke
poging teruggeeft. Kost geen API-sleutel, alleen een paar gewone paginabezoeken.
"""
import re

import requests

# Alleen EU-landen, zonder Zwitserland en het VK (op jouw verzoek).
EU_COUNTRIES = ["Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czech Republic", "Denmark", "Estonia",
                "Finland", "France", "Germany", "Greece", "Hungary", "Ireland", "Italy", "Latvia", "Lithuania",
                "Luxembourg", "Malta", "Netherlands", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia",
                "Spain", "Sweden"]
ISO = {"Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY", "Czech Republic": "CZ",
       "Denmark": "DK", "Estonia": "EE", "Finland": "FI", "France": "FR", "Germany": "DE", "Greece": "GR",
       "Hungary": "HU", "Ireland": "IE", "Italy": "IT", "Latvia": "LV", "Lithuania": "LT", "Luxembourg": "LU",
       "Malta": "MT", "Netherlands": "NL", "Poland": "PL", "Portugal": "PT", "Romania": "RO", "Slovakia": "SK",
       "Slovenia": "SI", "Spain": "ES", "Sweden": "SE"}
DESTINATION = "Belgium"
PAGE = "https://help.cardmarket.com/en/ShippingCosts"


def _session():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (pokedeals; persoonlijk project)"
    return s


def _looks_like_table(text):
    """Ruwe check of de tekst een gevulde tabel bevat in plaats van de lege sjabloon."""
    t = text.lower()
    return ("tracked" in t and "price" in t and ("day" in t or "delivery" in t)
            and "sorry, we are not shipping" not in t and len(t) > 200)


def probe():
    s = _session()
    print("=== 1. De kale pagina: op zoek naar een verborgen bron ===")
    try:
        r = s.get(PAGE, timeout=30)
        html = r.text
        print(f"status {r.status_code}, {len(html)} tekens")
        hits = sorted(set(re.findall(r'["\'](/[a-zA-Z0-9/_\-.]*(?:shipping|cost|price)[a-zA-Z0-9/_\-.]*)["\']', html, re.I)))
        print("mogelijke paden in de pagina zelf:", hits or "niets gevonden")
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I)
        own = [u for u in scripts if "cardmarket" in u or u.startswith("/")]
        print("eigen scriptbestanden (waar de logica in kan zitten):", own[:10])
        json_blobs = re.findall(r'<script[^>]+type=["\']application/json["\'][^>]*>(.{0,300})', html, re.I | re.S)
        print("json-blokken op de pagina (eerste 300 tekens):", json_blobs[:2] or "geen")
    except Exception as e:
        print("FOUT:", e)
        return

    print("\n=== 2. Gokken: dezelfde pagina met land als parameter ===")
    guesses = []
    for frm, to in (("Germany", "Belgium"), ("de", "be")):
        for params in ({"from": frm, "to": to}, {"origin": frm, "destination": to},
                        {"fromCountry": frm, "toCountry": to}, {"country_from": frm, "country_to": to}):
            guesses.append(params)
    seen = set()
    for params in guesses:
        key = tuple(sorted(params.items()))
        if key in seen:
            continue
        seen.add(key)
        try:
            r = s.get(PAGE, params=params, timeout=20)
            ok = _looks_like_table(r.text)
            print(f"  {params} -> status {r.status_code}, {len(r.text)} tekens, lijkt gevuld: {ok}")
            if ok:
                print("    fragment:", re.sub(r"\s+", " ", r.text)[:500])
        except Exception as e:
            print(f"  {params} -> FOUT {e}")

    print("\n=== 3. Gokken: een los verzoek op de achtergrond (JSON) ===")
    for path in ("/api/shipping-costs", "/api/ShippingCosts", "/en/api/shipping-costs", "/shipping-costs.json"):
        for base in ("https://help.cardmarket.com", "https://www.cardmarket.com"):
            url = base + path
            try:
                r = s.get(url, params={"from": "Germany", "to": "Belgium"}, timeout=15)
                print(f"  {url} -> status {r.status_code}, content-type {r.headers.get('content-type')}, {len(r.text)} tekens")
                if r.status_code == 200 and "json" in (r.headers.get("content-type") or ""):
                    print("    inhoud:", r.text[:400])
            except Exception as e:
                print(f"  {url} -> FOUT {e}")

    print(f"\nLanden die ik zou gebruiken (EU, zonder CH/UK), {len(EU_COUNTRIES)} stuks, allemaal richting {DESTINATION}:")
    print(", ".join(c for c in EU_COUNTRIES if c != DESTINATION))
