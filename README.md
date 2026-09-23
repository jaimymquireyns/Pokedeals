# Pokédeals

Een app op je telefoon die kaarten en sealed producten laat zien met de grootste kans op prijsstijging, je collectie bijhoudt en je een melding stuurt als een prijs in jouw bereik komt. Het is een statistische schatting, geen financieel advies.

**Kosten:** alles is gratis. PokemonPriceTracker ($9,99 per maand) is optioneel.
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
3. **Inloggen zonder e-mail.** De app logt in met een wachtwoord. Zet daarvoor de e-mailbevestiging uit: ga naar **Authentication → Sign In / Providers → Email** en zet **Confirm email** uit. Klik **Save**. De e-mailsjablonen hoef je niet aan te passen.
4. **Sleutels opzoeken.** Ga naar **Project Settings → API** (of *API Keys*) en noteer:
   - de **Project URL** (begint met `https://` en eindigt op `.supabase.co`)
   - de **publishable key** (of *anon key*): mag openbaar, komt in `config.js`
   - de **secret key** (of *service_role key*): blijft geheim, komt alleen als GitHub-secret

## Stap 4. PokemonPriceTracker (optioneel)

De prijzen komen van **Cardmarket**: kaarten via TCGdex en sealed rechtstreeks uit de openbare prijslijst van Cardmarket, allemaal in euro. Deze stap is dus niet nodig om te starten. PokemonPriceTracker voegt twee dingen toe: 6 maanden prijsgeschiedenis van kaarten (van TCGplayer, in dollars, alleen gebruikt om te zien hoe wisselvallig een kaart is) en prijzen van gegradeerde kaarten (eBay).

1. Maak een gratis account op pokemonpricetracker.com/sign-up. Je API key staat op pokemonpricetracker.com/api-keys. Met het gratis plan (100 credits per dag, 3 dagen historie) kun je gegradeerde prijzen al gebruiken.
2. Wil je ook de 6 maanden historie? Neem dan het **API-plan** ($9,99 per maand).

### PkmnPrices (aanbevolen om te testen)

pkmnprices.com geeft Cardmarket-prijzen in euro per conditie, prijshistorie tot een jaar (ook uit Cardmarket), sealed met plaatjes en gegradeerde prijzen. Het gratis plan (500 credits per dag) laat alleen Engelse kaarten in dollars zien; euro's, historie en sealed zitten in Pro ($14,99 per maand).

1. Maak een gratis account op pkmnprices.com/sign-up en kopieer je API key (begint met `pk_`) van het dashboard.
2. Maak in GitHub het secret `PKMN_API_KEY` aan.
3. Open `.github/workflows/test-ppt.yml`, klik op het potlood en zet onder `PPT_API_KEY: ${{ secrets.PPT_API_KEY }}` een nieuwe regel met dezelfde inspringing: `PKMN_API_KEY: ${{ secrets.PKMN_API_KEY }}`. Commit de wijziging. Daarna toont de test ook wat PkmnPrices teruggeeft.

### Laagste Near Mint-prijs (met PkmnPrices Pro)

Open `.github/workflows/daily.yml`, klik op het potlood en zet onder `PPT_API_KEY: ${{ secrets.PPT_API_KEY }}` een regel met dezelfde inspringing: `PKMN_API_KEY: ${{ secrets.PKMN_API_KEY }}`. De dagelijkse update koppelt daarna de belangrijkste kaarten aan PkmnPrices (300 per dag) en slaat hun laagste Near Mint-prijs op. Die zie je in de kaartdetails naast de trendprijs.

### Sealed plaatjes en setnamen (met PkmnPrices Pro)

Draai eenmalig de taak **Sealed verrijken** (bestand `.github/workflows/verrijk.yml`, zie Claude voor de inhoud) om plaatjes en officiële setnamen aan de sealed producten te koppelen. Dat kost ongeveer 12.000 credits en 1 à 2 uur; draait hij vast op het dagbudget, start hem de volgende dag opnieuw. Eerst moet je in Supabase (SQL Editor) deze regel draaien: `alter table products add column if not exists pk_id text;`

### Nieuw: Near Mint-geschiedenis als basis van de kansberekening

De app bouwt nu voor kaarten (naast sealed) ook een eigen Near Mint-prijsgeschiedenis op via PkmnPrices, in dezelfde volgorde als de Near Mint-prijzen (collectie, prijsmeldingen, beste kansen, dan de rest op prijs). Geen vast maximum: elke dag gaat het verder waar het de vorige keer stopte, tot het gedeelde PkmnPrices-budget op is. Zodra een kaart genoeg van die geschiedenis heeft, draait zíjn kansberekening voortaan op die eigen Near Mint-reeks in plaats van op de gemengde Cardmarket-trend; dat zie je op de kaartdetailpagina terug in een regel onder "Waarom deze kans?". Kaarten zonder die geschiedenis blijven gewoon op Cardmarket draaien, zodat het scherm Kansen breed blijft zoeken.

Volgorde waarin het gedeelde PkmnPrices-budget per dag wordt besteed: eerst de actuele Near Mint-prijs (nm.py), dan deze geschiedenis-opbouw (card_history.py), dan sealed-geschiedenis. Vraagt ook weer het volledige `supabase/schema.sql` opnieuw (voegt de kolom `basis` toe aan `forecasts`).

### Nieuw: een late taak die overgebleven credits opmaakt

Als je denkt dat het PkmnPrices-dagbudget rond een bepaald tijdstip reset, kun je vlak daarvoor een extra taak draaien die alles nog probeert te benutten: **Actions → Credits opmaken (laat op de dag)**. Hij draait sowieso al elke nacht vanzelf, rond 00:30-01:30 Belgische tijd (23:30 UTC) — ik weet de echte reset-tijd van PkmnPrices niet zeker, dus pas de tijd in `.github/workflows/credits.yml` gerust aan (het cijfer bij `cron:`, in UTC) als jij een ander tijdstip ziet. Kaarten die dezelfde dag al een prijs kregen, worden overgeslagen, zodat deze taak meteen verder gaat waar de ochtendtaak stopte in plaats van dezelfde kaarten over te doen.

### Nieuw: aanbod-onderzoek en overgebleven credits echt gebruiken

- **Aantal aanbiedingen (listings):** ik vond dit niet bij PkmnPrices, maar wel als los veld bij PokemonPriceTracker. De test hieronder controleert of het betrouwbaar is (op een paar kaarten) voordat er iets mee gebouwd wordt.
- **Bug gevonden en opgelost:** NM-prijzen en sealed-geschiedenis kregen ieder een eigen volledig dagbudget bij PkmnPrices, samen dus mogelijk het dubbele van je echte daglimiet. Ze delen nu één budget, in deze volgorde: eerst NM-prijzen (belangrijker voor de kansen), dan sealed-geschiedenis met wat overblijft.
- **Overgebleven credits worden nu gebruikt:** eerder stopte de NM-taak bij een vaste 300 kaarten per dag, ook als er nog volop budget over was. Nu wordt, zodra de vaste lijst van 1.200 kaarten klaar is, automatisch doorgegaan met extra kaarten (duurste eerst) tot het echte dagbudget op is.

### Nieuw: trackrecord per periode, sealed-geschiedenis, en een wiskundefoutje bij lange periodes

- **Trackrecord:** eerder werd alleen "30 dagen, 10%" bijgehouden en bijgesteld. Nu krijgt elke korte periode (7-60 dagen) zijn eigen trackrecord, en de lange periodes (3-24 maanden) worden elke maandag via een backtest op de bestaande prijsgeschiedenis gecontroleerd, zonder daar jaren op te hoeven wachten.
- **Sealed-geschiedenis:** met PkmnPrices Pro haalt de app nu ook oudere Cardmarket-prijzen op voor sealed producten die al gekoppeld zijn (na `enrich.py --sealed`). Zonder dit begon elk sealed product vanaf nul.
- **Rekenfout bij lange periodes hersteld:** bij 12 of 24 maanden kon een gewone trend worden doorgetrokken tot duizenden procenten. Er zit nu een grens op (+300% als plafond), alleen bij lange periodes; 7-60 dagen zijn ongewijzigd.

Ook dit vraagt om het volledige `supabase/schema.sql` opnieuw te draaien (voegt kolommen toe aan `forecast_history` en `trackrecord_stats`, bestaande gegevens blijven staan).

### Nieuw: periodes op de kaartdetailpagina

Naast 30 dagen kun je nu ook 7 en 14 dagen, en 3, 6, 12 en 24 maanden bekijken. Bij lange periodes ligt de bewegingsdrempel hoger (bijvoorbeeld 100% bij 24 maanden = "kans op verdubbeling"), anders zou bijna elke kaart een hoge kans op zowel stijging als daling tonen. De korte periodes (7-60 dagen) worden elke dag bijgewerkt; de lange (3-24 maanden) maar 1x per week, op maandag, om de rekentijd en je Supabase-opslag te sparen. Niets aan de instellingen zelf is veranderd.

### Nieuw: watchlist

Je kunt kaarten en sealed producten volgen (los van je collectie) via de nieuwe knop "Volgen" op een kaartdetailpagina, en ze terugzien onder het tabblad Watchlist, met eigen mappen. Werkt zodra je de nieuwe `supabase/schema.sql` opnieuw hebt gedraaid (voegt alleen ontbrekende tabellen toe, bestaande data blijft staan) en de nieuwste `docs`-bestanden zijn geüpload.

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
| `PPT_API_KEY` | (optioneel) API key van PokemonPriceTracker |
| `VAPID_PRIVATE_KEY` | de geheime sleutel uit stap 5, inclusief de regels met streepjes |
| `VAPID_SUBJECT` | `mailto:` gevolgd door je e-mailadres, bijv. `mailto:jij@example.com` |

## Stap 8. De eerste gegevens ophalen

Ga in de repository naar het tabblad **Actions**. Start de onderstaande taken één voor één met **Run workflow** en wacht tot elke taak een groen vinkje heeft.

1. **Test PokemonPriceTracker**: dit test ook Cardmarket. Open na afloop de run en klik op de stap *Toon wat PokemonPriceTracker teruggeeft*. Stuur de tekst naar Claude. Dit controleert of de gegevens goed worden gelezen; ik kon dat zelf niet testen.
2. **Dagelijkse update** met bij *recent* het getal `3`. Dat is een snelle test (een paar minuten).
3. **Dagelijkse update** nog een keer, nu met `500`. Dat haalt alle sets op en kan een uur duren.
4. *(Alleen met het betaalde plan)* **Historie ophalen (eenmalig)** met bij *cards_sets* eerst `1` als test, en daarna `12`. Dit haalt maanden prijsgeschiedenis op zodat de kansen meteen betrouwbaarder zijn en het trackrecord al een backtest kan tonen. Loopt het dagbudget op (je ziet dat in de log), start hem de volgende dag opnieuw; hij gaat verder waar hij was.

Vanaf nu draait alles vanzelf: elke dag rond 07:00-08:00 de volledige update en de samenvatting, en 3 extra keer per dag een controle van je collectie en prijsmeldingen.

## Stap 9. Op je telefoon zetten

1. Open `https://JOUWNAAM.github.io/pokedeals/` op je telefoon.
2. **iPhone (Safari):** deelknop → *Zet op beginscherm*. **Android (Chrome):** menu → *App installeren*. Open de app daarna vanaf je beginscherm. Op een iPhone werken meldingen alleen zo, vanaf iOS 16.4.
3. Tik op **Collectie**, kies **Nog geen account? Maak er een** en vul je e-mailadres en een wachtwoord (minstens 8 tekens) in. Daarna log je voortaan in met dezelfde gegevens.
4. Ga naar **Instellingen** en tik **Meldingen op dit toestel aanzetten**.
5. Zet daarna bij Supabase het aanmelden van nieuwe gebruikers uit (**Authentication → Sign In / Providers → Allow new users to sign up: uit**), zodat alleen jij kunt inloggen.

---

## Hoe het werkt

- **Prijzen:** alles wat je op Cardmarket koopt en verkoopt komt van Cardmarket zelf, in euro: kaarten via TCGdex en sealed uit de openbare prijslijst. Alleen gegradeerde kaarten (eBay) en de optionele oude historie (TCGplayer) komen uit een andere bron. Cardmarket geeft één prijs per product voor alle talen en conditie, geen prijs per taal.
- **Kans:** de app berekent hoe waarschijnlijk het is dat de prijs binnen 14, 30 of 60 dagen minstens 10% of 20% stijgt, uit hoe hard en hoe wisselvallig de prijs recent bewoog. Met weinig data is de schatting grof en dat staat erbij.
- **Netto:** na jouw verkoopkosten en verzending (Instellingen). Goedkope kaarten vallen daardoor snel af, omdat verzending zwaar weegt.
- **Trackrecord:** na 30 dagen wordt elke voorspelling nagekeken. Zodra er genoeg uitkomsten zijn, worden de kansen daarop bijgestuurd.
- **Nog niet in de berekening:** herdrukken, leeftijd van een set, rotatie en populariteit. Die worden wel al bewaard, zodat ze later getest kunnen worden.
- **Bijwerken:** prijsbronnen verversen één keer per dag; de extra controles geven vooral zekerheid voor je meldingen.

## Problemen

- **Geen kansen op het beginscherm:** de dagelijkse update heeft nog niet gedraaid (stap 8).
- **Account maken lukt niet of vraagt om bevestiging:** controleer of **Confirm email** uit staat (stap 3.3).
- **Taak in Actions is rood:** klik erop, open de rode stap en stuur de laatste regels naar Claude.
- **Supabase pauzeert een gratis project na 7 dagen zonder gebruik.** De dagelijkse taak voorkomt dat.

## Voor ontwikkelaars

`python collector/test_offline.py` test de berekeningen en taken met een nagebootste database. `python tests/e2e.py` test de app in een browser (vereist Playwright).
