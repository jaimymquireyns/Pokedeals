# Pokédeals

Een app op je telefoon die kaarten en sealed producten laat zien met de grootste kans op prijsstijging, je collectie bijhoudt en je een melding stuurt als een prijs in jouw bereik komt. Het is een statistische schatting, geen financieel advies.

**Kosten:** alles is gratis, behalve PokemonPriceTracker ($9,99 per maand).
**Tijd:** ongeveer 45 minuten. Het gaat het makkelijkst op een computer; daarna gebruik je alles op je telefoon.

Loop je ergens vast, stuur de foutmelding of een schermafbeelding naar Claude.

---

## Stap 1. GitHub: je eigen kopie van de app

1. Maak een account op github.com (gratis).
2. Klik rechtsboven op **+** → **New repository**. Naam: `pokedeals`. Kies **Public** (nodig voor gratis hosting). Klik **Create repository**.
3. Pak deze zip uit op je computer. Klik in de nieuwe repository op **uploading an existing file** en sleep de **inhoud** van de uitgepakte map erin (dus alle mappen en bestanden, niet de zip zelf). Klik onderaan **Commit changes**.
4. Controleer: open in de repository de map `.github/workflows`. Zie je daar vier bestanden (`daily.yml`, `watch.yml`, `historie.yml`, `test-ppt.yml`)? Mooi. Ontbreken ze omdat je computer mappen met een punt verbergt: kies **Add file → Create new file**, typ als naam `.github/workflows/daily.yml`, plak de inhoud uit de map `extra-workflows` en herhaal dat voor de andere drie.

## Stap 2. Gratis hosting aanzetten (GitHub Pages)

1. In de repository: **Settings → Pages**.
2. Bij **Source** kies je **Deploy from a branch**. Branch: `main`, map: `/docs`. Klik **Save**.
3. Na 1 à 2 minuten staat je app op `https://JOUWNAAM.github.io/pokedeals/` (JOUWNAAM is je GitHub-gebruikersnaam). Bewaar dit adres.

## Stap 3. Supabase: de database

1. Maak een account op supabase.com en klik **New project**. Kies een regio in Europa (bijv. Frankfurt) en bedenk een databasewachtwoord (bewaar het; je hebt het verder niet nodig).
2. Ga links naar **SQL Editor → New query**. Open het bestand `supabase/schema.sql` uit deze map, kopieer alles, plak het en klik **Run**. Er moet "Success" komen. Krijg je een rode foutmelding: stuur die naar Claude.
3. **Inlogcode per e-mail.** De app logt in met een code, dus de e-mail moet die code bevatten:
   - Ga naar **Authentication → Emails** (of *Email Templates*).
   - Open **Confirm signup** en **Magic link**. Vervang bij allebei de tekst door: `<h2>Je code</h2><p>Vul in de app in: <strong>{{ .Token }}</strong></p>`. Sla op.
4. **Sleutels opzoeken.** Ga naar **Project Settings → API** (of *API Keys*) en noteer:
   - de **Project URL** (begint met `https://` en eindigt op `.supabase.co`)
   - de **publishable key** (of *anon key*): mag openbaar, komt in `config.js`
   - de **secret key** (of *service_role key*): blijft geheim, komt alleen als GitHub-secret

## Stap 4. PokemonPriceTracker

1. Maak een account op pokemonpricetracker.com en neem het **API-plan** ($9,99 per maand). Daarmee krijg je 20.000 credits per dag en 6 maanden prijsgeschiedenis.
2. Kopieer je **API key** (te vinden onder je account, bij API).

## Stap 5. Sleutels voor meldingen

1. Open `https://JOUWNAAM.github.io/pokedeals/sleutels.html` in je browser en tik **Maak sleutels**.
2. Je krijgt twee vakken: een **publieke** en een **geheime** sleutel. Laat de pagina open staan tot stap 6 en 7 klaar zijn.

## Stap 6. De app koppelen (config.js)

1. Open in je repository `docs/config.js` en klik op het potloodje (bewerken).
2. Vul in tussen de aanhalingstekens: `SUPABASE_URL` (Project URL), `SUPABASE_KEY` (de **publishable** key) en `VAPID_PUBLIC_KEY` (de publieke sleutel uit stap 5).
3. Klik **Commit changes**. Wacht 1 à 2 minuten tot Pages is bijgewerkt.

## Stap 7. Geheimen voor de dagelijkse taak

In de repository: **Settings → Secrets and variables → Actions → New repository secret**. Maak deze vijf aan:

| Naam | Waarde |
|---|---|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SECRET_KEY` | de **secret** key (dus niet de publishable!) |
| `PPT_API_KEY` | API key van PokemonPriceTracker |
| `VAPID_PRIVATE_KEY` | de geheime sleutel uit stap 5, inclusief de regels met streepjes |
| `VAPID_SUBJECT` | `mailto:` gevolgd door je e-mailadres, bijv. `mailto:jij@example.com` |

## Stap 8. De eerste gegevens ophalen

Ga in de repository naar het tabblad **Actions**. Start de onderstaande taken één voor één met **Run workflow** en wacht tot elke taak een groen vinkje heeft.

1. **Test PokemonPriceTracker**: open na afloop de run en klik op de stap *Toon wat PokemonPriceTracker teruggeeft*. Stuur de tekst naar Claude. Dit controleert of de gegevens goed worden gelezen; ik kon dat zelf niet testen.
2. **Dagelijkse update** met bij *recent* het getal `3`. Dat is een snelle test (een paar minuten).
3. **Dagelijkse update** nog een keer, nu met `500`. Dat haalt alle sets op en kan een uur duren.
4. **Historie ophalen (eenmalig)** met de standaardwaarden. Dit haalt maanden prijsgeschiedenis op zodat de kansen meteen betrouwbaarder zijn en het trackrecord al een backtest kan tonen. Loopt het dagbudget op (je ziet dat in de log), start hem de volgende dag opnieuw; hij gaat verder waar hij was.

Vanaf nu draait alles vanzelf: elke dag rond 07:00-08:00 de volledige update en de samenvatting, en 3 extra keer per dag een controle van je collectie en prijsmeldingen.

## Stap 9. Op je telefoon zetten

1. Open `https://JOUWNAAM.github.io/pokedeals/` op je telefoon.
2. **iPhone (Safari):** deelknop → *Zet op beginscherm*. **Android (Chrome):** menu → *App installeren*. Open de app daarna vanaf je beginscherm. Op een iPhone werken meldingen alleen zo, vanaf iOS 16.4.
3. Tik op **Collectie**, vul je e-mailadres in en daarna de code uit je mail.
4. Ga naar **Instellingen** en tik **Meldingen op dit toestel aanzetten**.
5. Zet daarna bij Supabase het aanmelden van nieuwe gebruikers uit (**Authentication → Sign In / Providers → Allow new users to sign up: uit**), zodat alleen jij kunt inloggen.

---

## Hoe het werkt

- **Prijzen:** kaarten komen van TCGdex (Cardmarket, euro). Sealed, gegradeerde prijzen en prijsgeschiedenis komen van PokemonPriceTracker (TCGplayer/eBay, dollars, omgerekend naar euro).
- **Kans:** de app berekent hoe waarschijnlijk het is dat de prijs binnen 14, 30 of 60 dagen minstens 10% of 20% stijgt, uit hoe hard en hoe wisselvallig de prijs recent bewoog. Met weinig data is de schatting grof en dat staat erbij.
- **Netto:** na jouw verkoopkosten en verzending (Instellingen). Goedkope kaarten vallen daardoor snel af, omdat verzending zwaar weegt.
- **Trackrecord:** na 30 dagen wordt elke voorspelling nagekeken. Zodra er genoeg uitkomsten zijn, worden de kansen daarop bijgestuurd.
- **Nog niet in de berekening:** herdrukken, leeftijd van een set, rotatie en populariteit. Die worden wel al bewaard, zodat ze later getest kunnen worden.
- **Bijwerken:** prijsbronnen verversen één keer per dag; de extra controles geven vooral zekerheid voor je meldingen.

## Problemen

- **Geen kansen op het beginscherm:** de dagelijkse update heeft nog niet gedraaid (stap 8).
- **Geen code in je mail:** controleer stap 3.3 en je spam. De ingebouwde e-mail van Supabase heeft een lage limiet per uur; wacht even.
- **Taak in Actions is rood:** klik erop, open de rode stap en stuur de laatste regels naar Claude.
- **Supabase pauzeert een gratis project na 7 dagen zonder gebruik.** De dagelijkse taak voorkomt dat.

## Voor ontwikkelaars

`python collector/test_offline.py` test de berekeningen en taken met een nagebootste database. `python tests/e2e.py` test de app in een browser (vereist Playwright).
