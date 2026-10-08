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

### Bugfix: uren blijven proberen als PkmnPrices het dagbudget al bereikt heeft

Bij een 429 (te snel, of dagbudget op) probeerde de taak het per kaart tot 4 keer opnieuw met 15 seconden pauze, en ging daarna gewoon door naar de volgende kaart om hetzelfde te herhalen. Was het dagbudget bij PkmnPrices echt op (bijvoorbeeld na een eerdere, afgebroken run), dan kostte dat uren aan zinloos wachten. De taak herkent dit nu na een paar mislukte pogingen achter elkaar en stopt dan meteen voor de rest van de dag, in plaats van door te blijven proberen tot de tijds- of creditlimiet toch wordt bereikt.

### Nieuw: sneller kunnen testen zonder 4 uur te wachten

Bij **Dagelijkse update → Run workflow** staat nu ook een veld "Tijdslimiet in minuten voor PkmnPrices". Leeg laten gebruikt de gewone 4 uur; vul je bijvoorbeeld `10` in, dan stopt dat onderdeel na 10 minuten, handig om snel te controleren of iets werkt.

### Bugfix: de taak liep nu tegen de 5-uurslimiet van GitHub aan

Met het hogere dagbudget en de goedkopere zoekopdracht probeert de taak nu veel meer kaarten in één keer, en PkmnPrices staat maar 60 verzoeken per minuut toe. Daardoor kon een dagelijkse update de 5 uur die GitHub Actions toestaat overschrijden en van buitenaf worden afgebroken (`The job has exceeded the maximum execution time`). De taak stopt zichzelf nu op tijd: na 4 uur bij de dagelijkse update, na 50 minuten bij de late "Credits opmaken"-taak (die zelf maar 1 uur van GitHub krijgt). Wat er tot dat moment gelukt is blijft gewoon staan; de rest volgt de volgende keer, net als bij een opgebruikt creditbudget.

### Bugfix: "Eigen collectie eerst" logde soms helemaal niets

Bleef er na het filteren op "is dit een kaart met bekende gegevens" niets over (bijvoorbeeld doordat de collectie op dat moment leeg was, of alleen sealed producten bevatte), dan gebeurde er stilletjes niets: geen regel in het logboek, geen foutmelding. Dat maakte het onmogelijk om te zien of deze stap wel of niet iets deed. Er staat nu altijd een regel, ook als er niets bruikbaars overblijft.

### Aangepast: eigen collectie krijgt nu echt als eerste PkmnPrices-budget

Er komt nu een aparte, eerste ronde vóór alle andere PkmnPrices-taken: je eigen collectie en prijsmeldingen worden gekoppeld én van geschiedenis voorzien vóór er iets naar de bredere lijst (beste kansen, sealed, aanbiedingen) gaat. Eerder stond je collectie wel vooraan binnen de losse taken, maar liep bijvoorbeeld het koppelen van de hele "vaste lijst" (tot 1.200 kaarten) toch eerst helemaal af voordat er ook maar aan geschiedenis werd begonnen.

### Eerste echte resultaten van het eigen model en wat ik ermee deed (8 okt, derde ronde)

**Wat het logboek van de Signalen-taak liet zien.**
- **'Onder het gemiddelde' werkt vooral bij springerige reeksen.** Reeksen met 2+ sprongen van > 50% in 60 dagen: winst na kosten 45,8% (A) / 25,9% (B). Rustige reeksen: 7,6% (A) / 8,1% (B), niet beter dan de basis (14,9% / 9,6%). Een simulatie zonder enige echte terugkeer, alleen met pieken in de laagste vraagprijs, geeft hetzelfde patroon (16% tegen 10% basis, alleen bij springerige reeksen). Dat bewijst niet dat het in de echte data zo zit, maar het past erbij: de voorsprong is waarschijnlijk deels een bijeffect van pieken in de vraagprijs, en niet iets wat je kunt verhandelen.
- **De marktsplitsing zegt nog niets**: van 373 metingen vallen er 322 in 'markt vlak'.
- **Het model voorspelt vandaag voor 672 van 2.063 kaarten minstens 30% kans op winst**, terwijl de basis 15% (A) of 10% (B) is. Te optimistisch, en getraind op de reeks mét pieken. Niet vertrouwen; de uitkomst van de toetsen hieronder beslist.
- **Prijsbetrouwbaarheid**: 1.238 van 2.586 kaarten kregen gewicht 2 of hoger. Een waarschuwing die voor bijna de helft geldt is niet selectief. De nieuwe regel 'controle op de controle' toont de mediaan van laagste prijs / verkoopgemiddelde; ligt die ver van 1x, dan meten die twee niet hetzelfde. Ik heb niet gecontroleerd welke verkopen (conditie, taal) in Cardmarkets gemiddelde zitten.

**Twee fouten van mij, gevonden en hersteld.**
- **De eerlijke toets draaide niet** ('te weinig metingen', terwijl er 1.610 waren). De oude splitsing nam de datum bij 60% van de metingen en eiste einddatum < splitsdatum. Zit meer dan 60% van de metingen in de eerste meetronde (veel kaarten hebben maar een paar maanden geschiedenis), dan blijft er niets over om op te trainen. Nagebootst: 62% in de eerste ronde geeft 0 trainingsmetingen. Of dit precies de oorzaak in de echte data was, kan ik niet zien; de nieuwe toets meldt voortaan zelf hoeveel metingen en dagen er zijn, en waarom een toets niet kon draaien. Nieuw: `edge._split` kiest de splitsdatum op aantallen (nooit op uitkomsten), met einddatum <= splitsdatum (een uitkomst die op die dag bekend is mag meetrainen; er lekt niets vooruit).
- **De voorspellingen werden niet opgeslagen.** Waarschijnlijke oorzaak (niet zeker): 10 van de 2.073 kaarten kregen geen voorspelling, waardoor de bulk-opslag rijen met verschillende kolommen bevatte, wat PostgREST kan weigeren. Nu hebben alle rijen dezelfde kolommen, en staat de echte foutmelding in het logboek. Een test met een opslag die wisselende kolommen weigert bewaakt dit.

**Nieuw in de Signalen-taak met backtest.**
- **Basis C**: dezelfde uitsplitsing en toets op Cardmarkets eigen prijslijst (trend) in plaats van onze laagste vraagprijs, die één verkoper niet kan sturen. Als 'onder het gemiddelde' daar niet vooral bij springerige reeksen werkt, is het effect echt.
- Het aantal metingen, kaarten en meetdagen per basis; bij de toets de voorsprong in rustige reeksen apart; bij de nachtelijke voorspelling een controle van gemiddelde voorspelling tegen training.
- Toetsgevoeligheid na de nieuwe splitsing: 0 van 30 zuivere random walks als voorspelbaar aangemerkt; zwakke terugkeer gevonden in 15 van 15 reeksen.

### Eigen voorspelmodel, prijsbetrouwbaarheid en kleinere wensen (8 okt, tweede ronde)

**Waarom.** De backtest per signaal liet zien dat prijzen terugkeren naar hun gemiddelde en dat trendsignalen (piek, valt nog, stabiliseert) niets voorspellen. Het oude model (`analysis.forecast`) rekent de trend juist door; dat verklaart waarschijnlijk waarom zijn kansen omgekeerd uitpakten. De kansen blijven verborgen in de app (`SHOW_PREDICTIONS = false`); dit is een proef die zich eerst moet bewijzen.

**`collector/edge.py` (eigen model, versie edge-1).** Verwachte koersverandering over 30 dagen uit zes kenmerken (hoe ver onder het 6-maandsgemiddelde, trend van 14 dagen, prijsniveau, beweging van de hele markt, onrust, aantal sprongen) met kleinste kwadraten, en de overgebleven afwijkingen als verdeling voor twee kansen: `p_win` (nu kopen, over 30 dagen verkopen, winst na verzending, commissie en verpakking) en `p_up10` (minstens +10%).
- **Eerlijk toetsen** (`walk_forward`): trainen op het begin, meten op het eind met een gat van 30 dagen ertussen, zodat de uitkomst van een trainingsmoment niet in de testperiode valt. Een test controleert dat de kenmerken van een meetmoment niet veranderen als de prijzen daarna anders worden.
- **Valkuil die de testen aan het licht brachten:** de kans op winst hangt al van het prijsniveau af (een dure kaart hoeft minder te stijgen om de kosten te dekken). Een model dat alleen dure kaarten hoger inschat leek eerst beter dan 'het basispercentage' zonder iets over prijzen te weten: 2 van 6 zuivere random walks werden ten onrechte voorspelbaar genoemd. Daarom wordt alles nu vergeleken met een **kostenbewust basismodel** (`p_win0`: dezelfde kosten en hetzelfde prijsniveau, maar zonder enig kenmerk). Gemeten op 30 random walks: 1 ten onrechte als voorspelbaar aangemerkt; op zwakke terugkeer naar het gemiddelde vond de toets het effect in 9 van 10 reeksen.
- **Elke dag vastleggen** (`signals.compute_today`, dagelijks 12:00 UTC): `p_win`, `p_win0`, `p_up10`, `exp_ret` en `model` in `card_signals`. Na 30 dagen vergelijkt `edge.evaluate_stored` die voorspellingen met wat er echt gebeurde: de enige toets die echt vooruit kijkt. Ontbreken de kolommen (supabase/schema.sql nog niet opnieuw gedraaid), dan worden de gewone signalen toch opgeslagen, met een melding.
- **Uitsplitsing** (`edge.report_splits`, in de Signalen-taak met backtest): waar 'onder het gemiddelde' werkt, per prijsklasse (onder € 25, € 25-100, vanaf € 100), hoe diep onder het gemiddelde (15/25/35%), bij welke marktbeweging en bij springerige reeksen.

**`collector/reliability.py` (prijsbetrouwbaarheid).** Onze Near Mint-prijs is de laagste vraagprijs, geen verkoopprijs; een verkoper kan hem omhoog of omlaag duwen. Controle zonder extra credits: de laagste prijs minder dan de helft of meer dan het dubbele van Cardmarkets eigen verkoopgemiddelde (`afwijking`), veel pieken die uit de reeks moesten (`pieken`), drie of meer sprongen van > 50% in 60 dagen (`springt`), 7+ dagen exact dezelfde prijs (`vast`) en hooguit 2 verkopers onder de goedkoopste aanbiedingen (`weinig verkopers`). Een aanwijzing, geen bewijs. In de Signalen-taak met backtest staat het overzicht, met je eigen kaarten apart.

**Kleinere wensen.**
- **Verkocht**: filters op periode (alles, deze maand, 3 maanden, dit jaar), uitkomst (alles, winst, verlies) en volgorde (nieuwste, oudste, grootste winst, grootste verlies); totalen, grafiek, lijst en CSV gaan mee. De periode van de grafiek heet nu 'Max'.
- **Near Mint vanaf** op het kaartdetail is een link naar Cardmarket, met `minCondition=2` (Near Mint of beter) als de exacte pagina bekend is. Of Cardmarket dat filter overneemt kon ik niet testen; negeert het de parameter, dan opent gewoon de kaartpagina.
- **Beroemde Pokemon die PkmnPrices niet vond** worden na 7 dagen opnieuw gezocht (`PK_MISS_RETRY_DAYS_FAMOUS`), de rest na 30.
- **Cardmarket-link ontbreekt**: kaarten die je gebruikt (collectie, watchlist, prijsmeldingen, aanbiedingen) en kaarten van beroemde Pokemon krijgen elke 7 dagen een nieuwe kans (`CM_RETRY_DAYS`, kolom `products.cm_checked_on`); de rest niet, om geen credits te verspillen. Ontbreekt de kolom nog, dan worden de links toch opgeslagen en blijft de kaart elke nacht in de rij.
- **Sealed koppelen** (`.github/workflows/sealed_koppelen.yml`, handmatig): de bestaande eenmalige koppeltaak `enrich.py --sealed` had nog geen knop. Kost ongeveer 12.000 PkmnPrices-credits, is hervatbaar, en deelt de wachtrij `pokedeals-data` met de andere taken. Daarna vult de dagelijkse update de sealed-geschiedenis zelf aan.

**Wat nog niet getest kon worden:** alles hierboven is getest op nagebootste reeksen (met bekende structuur en zonder), niet op echte prijzen. Of het model op echte data iets weet, blijkt pas uit de Signalen-taak met backtest en uit de voorspellingen die we de komende weken vastleggen.

### Zoekbalken, A–Z bij verkopen, filters op Home en een grafiek bij Verkocht (8 okt)

- **Verkopen aanvinken**: de kaarten waaruit je kiest staan op A–Z (naam, dan set en nummer).
- **Zoekbalk bij Collectie** (In bezit): filtert terwijl je typt op naam, set, nummer, staat of graad; een setafkorting als `obf` of `30c` telt ook. Toont 'x van y gevonden'. De totalen bovenaan blijven die van je hele collectie.
- **Zoekbalk bij Verkocht**: zoekt op koper, kaartnaam, set, nummer en datum. De totalen ('Winst (gefilterd)'), de grafiek, de lijst en de CSV gaan mee met het filter.
- **Grafiek bij Verkocht** (`salesPoints` in `docs/js/views/sales.js`): twee lijnen, kost (wat de verkochte kaarten je kostten) en winst (je echte winst na commissie en verzending). Opbouwend of per maand, periode 3M / 1J / Alles; tikken of slepen toont op die datum beide waarden (de schuifbalk in `chart.js` kan nu meerdere lijnen, de collectiegrafiek is ongewijzigd).
- **Home**: filter op maximumprijs van de kaart (€ 25 / 50 / 100 / 250 / alles), minimale winst (€ 5 / 10 / 25 / 50+), soort (alles / kaarten / sealed), en sorteren op winst in % (standaard), winst in euro's, grootste korting of laagste prijs. De keuze wordt onthouden op de telefoon (`pd:home`). Bij geen resultaat staat er uitleg en een knop 'Filters wissen'. De lange uitleg is standaard ingeklapt.

### Zoeken: de set eerst, zoals Cardmarket het noemt (8 okt)

Cardmarket noemt een kaart bijvoorbeeld `_____'s Pikachu (CEL WP 24)`: de set eerst, daarna de oorspronkelijke set en het nummer. Een zoekopdracht als `cel wp 24` of `obf 125` (set + nummer, zonder naam) vond niets, omdat het eerste woord altijd als kaartnaam werd gelezen. Nu wordt, als de gewone lezing niets oplevert, ook 'set (voorvoegsel) nummer' geprobeerd: `cel` = Celebrations, `wp24` = nummer. Alleen als terugval, want een afkorting kan ook een kaartnaam zijn (`mew` is zowel de 151-set als de Pokémon). Namen met underscores (`_____'s Pikachu`) zijn gewoon vindbaar op `pikachu` of `'s pikachu`.

### Collectie: sorteren op Z–A en op laatst toegevoegd (8 okt)

Twee nieuwe sorteervolgordes bij Collectie: **Z–A** en **Nieuwste (laatst toegevoegd)**. 'Laatst toegevoegd' is het moment waarop een aankoop aan de collectie is toegevoegd (`collection.created_at`, nu ook in de view `v_collection`), niet de aankoopdatum: je voegt soms een oude aankoop pas later toe. Een kaart met meerdere aankopen telt mee met zijn laatst toegevoegde aankoop. Is de view nog niet bijgewerkt, dan valt de app terug op de aankoopdatum.

### Zoeken: 'charizard 30c BS4' (7 okt)

De zoekfunctie las `charizard 30c BS4` verkeerd: `30c` wees naar '30th Celebration' in plaats van de 30th Classic Collection, en `BS4` werd gesplitst in 'BS' (afkorting voor Base Set) en '4', waardoor 'charizard bs' als naam overbleef. Nu:
- Eerst wordt gekeken of er al een setafkorting of setnaam is getypt (niet aan een nummer geplakt); is die er, dan is een woord als `BS4` het kaartnummer. Is die er niet, dan wordt `MT5` zoals voorheen gesplitst in setafkorting en nummer.
- `30c` is 30th Celebration (de Classic Collection heet `30th-c`). Een setafkorting met een letter erin (`30c`) gaat voor op een kaartnummer.
- Een nummer met letters ervoor (`bs4`, `sv46`) wordt ook zonder letters geprobeerd (`4`); ook `bs 4` met een spatie.
- Een set die precies zo heet (`30th-c`) gaat voor op een set die er alleen mee begint.
- De zoekpogingen met de set erbij gaan voor op die zonder set.

### Gegradeerde geschiedenis hersteld, op basis van het echte antwoord (7 okt)

`check_card --graded` liet het echte eBay-antwoord zien. De uitlezing was fout omdat: de datum heet `sold_at` (niet `date`), de prijzen in dollars zijn (nu omgerekend naar euro, de dollarprijs gaat mee in `native`), en elke verkoop een `variant` heeft: een Normal PSA 10 Lapras ging voor $500, de Reverse Holofoil voor $3.300, en dat mocht nooit door elkaar.
- `graded_history.parse_sales`: kiest per opvraging een uitvoering (normal > holofoil > reverse holofoil, net als bij de Near Mint-prijs), bewaart per dag het gemiddelde in euro, laat verkopen met een andere munt dan USD/EUR, een andere graad of niet 'exact' toegewezen weg (en telt ze), en geeft een `grade_qualifier` (Pristine, Black Label) een eigen sleutel (`CGC-10-Pristine`) zodat de gewone 10 niet vervuild wordt.
- Pagineert met de cursor (`has_more`/`next_cursor`) tot de oudste verkoop de grens haalt (90 dagen), maximaal 3 pagina's; werkt de cursor niet, dan wordt dat herkend en blijft het bij de eerste pagina. Is er na de eerste ronde budget over, dan gaan de drukke combinaties verder terug tot 180 dagen.
- Nieuwe tabel `graded_checks`: wanneer we elke kaart/graad voor het laatst opvroegen en wat eruit kwam; met verkopen pas na 14 dagen opnieuw, zonder verkopen na 45 dagen. Zonder deze tabel slaat de stap zich over. Best verhandelde graden (10, 9) eerst.
- Veiligheid: dagplafond `GRADED_BUDGET` (4.000, bewust klein begonnen), noodrem (20 opvragingen achter elkaar met verkopen zonder herkenbare datum of prijs = stoppen; verkopen die we bewust overslaan tellen niet mee), en `GRADED_ENABLED` om het uit te zetten. Getest met de letterlijke antwoorden uit het logboek.
- `check_card --graded` toont nu ook de uitvoeringen, wat de uitlezing ervan maakt, en test of de cursor voor pagina 2 werkt.

### Pocket-kaarten eruit, promo's en afwijkende kaarten koppelen (7 okt)

- **Pokemon TCG Pocket** (mobiele game, sets A1, A1a, ..., B2a, P-A): digitale kaarten, geen Cardmarket-markt, niet bij PkmnPrices. Herkend via `config.is_digital_set`. Ze worden niet meer opgehaald (`collect_cards`, `newest_sets`), niet meer aan PkmnPrices gekoppeld en niet meer meegeteld bij de beroemde Pokemon. In de app: de view `v_search` sluit ze uit (omkeerbaar, geen gegevens verwijderd).
- **Promo's** (`nm._match_promo`): PkmnPrices schrijft 'Pikachu - SM04' in 'SM Promos' of 'SWSH: Sword & Shield Promo Cards', zonder setgrootte; de oude regel (setnaam of setgrootte moet lijken) wees ze daarom af. Nu: nummer gelijk, kale naam gelijk, kandidaat in een promo-set en zonder variant tussen haakjes ('(Target Non-Holo)'), en precies een kandidaat. Twijfel = niet koppelen.
- **Extra zoekpogingen** (`nm.find_card_ex`), alleen als de vorige niets opleverde: de naam zonder tekens die PkmnPrices niet kent ('Mewtwo δ' -> 'Mewtwo', 'Leafeon-GX' -> 'Leafeon GX'), en het nummer zonder letters ervoor ('CC001' -> '001', alleen voor niet-promo's en alleen met een set die klopt). Het logboek meldt hoeveel kaarten via welke regel zijn gekoppeld.
- `check_card` toont bij een niet-gekoppelde kaart welke regel (set of promo) een kandidaat kiest.

### Onderzoek: waarom 937 beroemde kaarten niet aan PkmnPrices te koppelen zijn (6 okt)

Uitsplitsing per set van de niet-gekoppelde kaarten van de 65 beroemde Pokemon: 349 (37%) zijn Pokemon TCG Pocket-kaarten (de mobiele game: A1, A1a, A2..., B1..., P-A; geen echte kaarten, geen Cardmarket-markt), 446 (48%) zijn Black Star Promos (SWSH, SM, XY, SVP, BW, DP, Nintendo, MEP), 57 zitten in Delta Species, Holon Phantoms, Hidden Fates Shiny Vault en Celebrations Classic Collection, de rest is verspreid. `nm.match_card` eist dat de setnaam of de setgrootte lijkt op die bij PkmnPrices; promo's hebben geen setgrootte en andere setnamen, dus ze worden afgewezen ook als naam en nummer kloppen.

`check_card <product_id>` toont voor een niet-gekoppelde kaart nu de kandidaten die PkmnPrices teruggeeft (id, naam, nummer, set, setgrootte) en per kandidaat of nummer, setnaam en setgrootte kloppen, plus welke kandidaat onze koppelregel kiest. Alleen een controle, verandert niets aan de nachtelijke taak.

### Logboek 6 okt: credits gelekt, koopjes met verzending, hoofdprijs (6 okt)

- **Gegradeerde geschiedenis staat UIT** (`GRADED_ENABLED = False`): de stap deed 9.730 opvragingen (~40.600 credits) en herkende nergens een prijspunt, omdat de veldnamen van de eBay-antwoorden geraden waren. Nu: noodrem (20 opvragingen achter elkaar met verkopen maar zonder herkende prijs = stoppen), eigen dagplafond (`GRADED_BUDGET`), en `check_card <id> --graded` toont het ruwe antwoord en wat de uitlezing ervan maakt. Pas aanzetten nadat de uitlezing aan een echt antwoord is aangepast.
- **Mislukte koppelingen worden onthouden** (`products.pk_miss_on`, `PK_MISS_RETRY_DAYS = 30`): ~937 beroemde kaarten die PkmnPrices niet kon vinden kostten elke nacht ~960 credits; nu pas na 30 dagen opnieuw.
- **Goedkope aanbiedingen houden rekening met verzending**: je koopt de goedkoopste (plus verzending als koper: ~EUR3 tot EUR25, daarna pakket), verkoopt voor de tweede goedkoopste (min commissie en verpakking). Is de winst minder dan EUR1, dan staat de kaart niet op Home; de verwachte winst staat bij elke kaart. Zelfde verzendtabel in app en collector.
- **Hoofdprijs op het kaartdetail** = mediaan van de 10 goedkoopste aanbiedingen van dezelfde uitvoering (`MAIN_PRICE_N`), met de goedkoopste prijs erbij en een waarschuwing bij minder dan 3 aanbiedingen. `offers.py` bewaart nu 20 aanbiedingen per kaart (kost niets extra: de opvraging haalt er al 20 op); de lijst op het kaartdetail toont er 8 en klapt uit.

### Aanbiedingen per uitvoering, exacte Cardmarket-link en een betere hoofdprijs (5 okt)

`check_card` liet zien dat elke Cardmarket-aanbieding een `variant` heeft (Normal, Reverse Holofoil, ...), plus de velden `graded`, `signed` en `altered`. Dragonite en Moltres stonden op EUR300 en EUR329 omdat PkmnPrices daar de Reverse Holofoil-versie volgt, terwijl de gewone kaart EUR29 en EUR20 kost. Daarom:
- **Aanbiedingen** (`offers.py`): bewaren de `variant`, laten gegradeerde, getekende en bewerkte kaarten weg, en bewaren er 8 in plaats van 5 (de opvraging kost per teruggegeven rij, niet per opgeslagen rij).
- **Goedkope aanbiedingen op Home** (view `v_deals`): de goedkoopste aanbieding tegen de **tweede goedkoopste van dezelfde uitvoering**, niet meer tegen het gemiddelde van de rest (dat werd door een grap-aanbieding van EUR9.001 omhoog getrokken en mengde uitvoeringen). Een uitvoering die niet de gewone is krijgt een label.
- **Hoofdprijs op het kaartdetail**: de mediaan van de (maximaal) 3 goedkoopste aanbiedingen van de uitvoering van de goedkoopste aanbieding, in plaats van het gemiddelde van alle 5 (bij Dragonite kwam dat op ongeveer EUR1.900).
- **Knop 'naar Cardmarket'**: ging naar een zoekopdracht op naam en nummer, en dus naar alle kaarten van die Pokemon. `collector/cm_links.py` haalt nu per kaart de exacte pagina op (PkmnPrices `/cards/{id}`: `cardmarket_url`, `cardmarket_product_id`; 1 credit per kaart, eigen budget `CM_LINKS_BUDGET`, collectie en watchlist eerst) en bewaart die in `products.cm_url`. De app gebruikt die ('Open op Cardmarket'), en valt voor kaarten zonder link terug op zoeken ('Zoek op Cardmarket'). Geeft PkmnPrices het veld niet mee, dan stopt cm_links na 20 kaarten en slaat niets op. Alleen adressen die met `https://www.cardmarket.com/` beginnen worden gebruikt. `check_card` toont nu ook de Cardmarket-pagina van een kaart.

### Bevinding (5 okt): de Near Mint-prijs is de laagste vraagprijs, en pieken eruit halen als optie

`check_card` op Lapras, Snorlax, Dragonite, Pikachu en Moltres liet zien dat de Near Mint-prijs van PkmnPrices bij de meeste kaarten precies de goedkoopste Near Mint-aanbieding is, geen verkoopgemiddelde. Zo'n prijs springt naar een absurd bedrag als de goedkope exemplaren verdwijnen en blijft weken staan (Lapras EUR1.450, Snorlax EUR1.949,99); ook Cardmarkets eigen trendprijs is te beinvloeden (een enkele verkoop van EUR350 bij Snorlax). Bij Dragonite en Moltres is de prijs bovendien een aanbieding die niet de goedkoopste is; waarom, onderzoekt `check_card` nu door ook taal en andere velden per aanbieding te tonen.

- `analysis.clean_nm_rows`: haalt pieken uit een Near Mint-reeks, met twee regels die niet naar de toekomst kijken. (1) Meer dan 3x boven Cardmarkets eigen 30-daagse verkoopgemiddelde van die dag: piek (nauwkeurig, maar alleen voor dagen dat onze dagelijkse verzameling draaide). (2) Anders: meer dan 3x boven de mediaan van de behouden punten van de laatste 90 dagen: piek, tot maximaal 60 dagen aaneen, daarna wordt het hoge niveau als nieuw niveau geaccepteerd (een schatting; een reeks die al in een piek begint wordt niet hersteld). Instellingen: `CLEAN_*` in `config.py`.
- Staat standaard UIT voor de dagelijkse kansberekening (`CLEAN_NM = False`). `python signals.py --backtest` draait de backtest nu twee keer, zonder en met opschonen, en meldt hoeveel punten er verwijderd zijn, zodat te zien is of 'ver onder het gemiddelde' ook zonder pieken blijft voorspellen.
- `check_card`: de waarschuwing 'veel lager dan de verkopen' is vervallen (een goedkoopste aanbieding hoort lager te zijn dan het gemiddelde).

### check_card onderzoekt nu ook waar de prijs vandaan komt

Aanleiding: de koppeling van Lapras, Snorlax, Dragonite, Pikachu en Moltres klopte allemaal (zelfde naam, set en nummer), dus de vreemde prijssprongen zitten in de data zelf. `collector/check_card.py` toont nu ook per kaart: de eigen Near Mint-reeks van 60 dagen (hoeveel verschillende waarden, hoe lang de prijs exact gelijk bleef), Cardmarkets eigen verkoopgemiddelden en laagste prijs, en de goedkoopste Near Mint-aanbiedingen met het aantal verschillende verkopers (maximaal 10 credits per kaart; `--no-listings` slaat dat over). Alleen waarnemingen, geen oordeel.

### Zoeken begrijpt nu de Cardmarket-schrijfwijze

Zoeken (en het aankoopformulier) begrijpt namen zoals op Cardmarket: `Blissey Lv.44 (MT 5)`, `Blissey Lv. 44 MT5`, `Charizard 4/102`. Het level wordt weggelaten (in onze database heet de kaart gewoon `Blissey`), setcode en nummer aan elkaar (`MT5`, `OBF125`) worden gesplitst, en `4/102` wordt `4`. Het eerste woord is altijd de naam, nooit een setcode. Nummers worden ook met en zonder voorloopnullen geprobeerd (`7` vindt `007`). Vindt de precieze zoekopdracht niets, dan wordt stap voor stap breder gezocht (zonder set, zonder nummer, alleen de eerste naam), zodat je liever te veel dan niets te zien krijgt.

### Bugfix: kaarten niet gevonden bij zoeken; aankoopvelden aangepast

- **Zoeken** (zowel het scherm Zoeken als het aankoopformulier) gebruikt nu een gedeelde functie (`docs/js/cardsearch.js`) die in de database tegelijk op naam, set en kaartnummer filtert. Voorheen werden eerst de 200 duurste kaarten op naam opgehaald en pas daarna op nummer gefilterd, waardoor goedkopere kaarten van Pokemon met honderden kaarten (bijv. Pikachu) niet gevonden werden. Het aankoopformulier zocht bovendien alleen op naam (geen setafkortingen of nummers) en toonde maar 15 resultaten.
- In het aankoopformulier worden oude zoekresultaten meteen gewist zodra je typt, zodat je nooit per ongeluk een kaart van de vorige zoekopdracht aantikt.
- **Aankoopvelden**: Naam verkoper, Datum aankoop, Verzendkosten en Trustee fee (opgeslagen als `purchase_costs`); de prijs vul je per kaart in.

### Nieuwe richting (4 okt): collectie en kopen/verkopen centraal, kansberekening verborgen

- **Kansberekening verborgen** (`SHOW_PREDICTIONS = false` in `docs/js/model.js`): niet op Home, kaartdetail, Watchlist of Instellingen, tot ze betrouwbaar genoeg is. Op de achtergrond draait alles door; op `true` zetten brengt alles terug.
- **Home toont alleen goedkope aanbiedingen**, uitgerekend door de database (view `v_deals`), zodat niet alle aanbiedingen opgehaald hoeven te worden (Supabase geeft max. 1.000 regels per keer).
- **Goedkope aanbiedingen weer aan** (`OFFERS_ENABLED`): de 500 duurste kaarten onder EUR500 plus de kaarten van de 65 beroemde Pokemon vanaf EUR10 (`offers.deal_targets`), eigen budget, elke kaart om de 3 dagen.
- **Aandacht nodig** in Collectie: kaarten die de laatste 30 dagen minstens X% stegen of daalden (instelbaar, standaard 15%, `user_settings.attn_pct`).
- **Kopen als bestelling** (`docs/js/orders.js`): meerdere kaarten van een verkoper; verzending en overige kosten verdeeld naar prijs (`collection.purchase_costs`, `purchase_seller`, `purchase_order`).
- **Verkopen als bestelling**: kaarten aanvinken (ook een deel van je stuks), koper, totaalprijs, verzending ontvangen/betaald, commissie (vooraf 6%, aanpasbaar), overige kosten; prijs verdeeld naar huidige waarde, per kaart aan te passen. Tabellen `sales` en `sale_items`.
- **In bezit / Verkocht** in Collectie (`docs/js/views/sales.js`): winst totaal en deze maand, elke verkoop met details, terugdraaien, en CSV-export met een regel per kaart (commissie, verzending en kosten verdeeld zoals de prijs).

### Correctie: verzending bij kopen telt mee, verzending bij verkopen niet

Op Cardmarket betaalt de koper de verzending. Het model trok die ten onrechte af van wat je als verkoper krijgt, waardoor goedkopere kaarten veel te pessimistisch uitkwamen (een kaart van EUR 50 leek +28% nodig te hebben). Nu:
- Bij een aankoop vul je de verzending in die je betaalde, plus hoeveel kaarten er in die bestelling zaten; jouw deel per rij wordt opgeslagen (`collection.purchase_shipping`).
- De kostprijs per kaart (aankoopprijs + jouw deel van de verzending) wordt overal gebruikt: winst, collectiewaarde, winstgrens, aandacht nodig, portefeuillegrafiek.
- Winstgrens = (kaartprijs + verzending bij aankoop + EUR 0,50 verpakking) / (1 - commissie). Voor kaarten die je nog niet hebt wordt de verzending bij aankoop geschat met de bestaande tabel (EUR 1,50 tot EUR 15).
- Dezelfde regel in de meldingen (`alerts.net_change`), het 'netto'-percentage op Home en de backtest-kolom 'winst na kosten'.

### Aangepast: marktmomentopname via PkmnPrices, alleen voor kandidaten

PokemonPriceTracker staat op het gratis plan, dus de momentopname loopt nu via PkmnPrices ('/cards/{id}/listings/cardmarket'). Per kaart een pagina van maximaal 20 aanbiedingen (PkmnPrices rekent per rij, dus maximaal 20 credits), met het totaal aantal aanbiedingen uit de paginagegevens en het aantal verschillende verkopers binnen die pagina. Alleen voor kandidaten (onder hun gemiddelde, geen negatief signaal, duurste eerst) en kaarten die de laatste 14 dagen al gevolgd werden, binnen een eigen budget van 6.000 credits (`config.SNAPSHOT_PK_BUDGET`). Liquiditeit telt meteen mee; de aanbod-trend na 14 dagen; vraag (recente verkopen) heeft nog geen bron. De workflow "Signalen" gebruikt daarom nu `PKMN_API_KEY`.

### Aangepast: signalen en backtest na de eerste echte uitkomst (30 sep)

De eerste backtest liet zien dat 'ver onder het 180-dagengemiddelde' sterk voorspelt (71,5% tegen 46% gemiddeld) en 'ver erboven' sterk tegen (23,7%), maar dat 'licht herstel' (momentum) slechter scoorde dan gemiddeld en de combinaties omlaag trok. Aangepast:
- Momentum telt niet meer als positief signaal. Het is opgesplitst in twee waarschuwingen: `piek` (meer dan +25% in 14 dagen) en `valt_nog` (meer dan 10% gedaald in 14 dagen). In `card_signals` staan beide samen in `s_momentum` (-1 als een van de twee geldt).
- De backtest meet nu vier uitkomsten, van soepel naar streng: op enig moment +10%, na 30 dagen nog +10%, op enig moment +20%, en winst na 6% commissie en verzending als je op dag 30 verkoopt.
- Nieuwe combinaties: onder gemiddelde zonder negatief signaal, onder gemiddelde + stabiliseert (met en zonder negatief).
- Per kaart telt nog maar een meetmoment per periode mee (niet-overlappend), zodat een wispelturige kaart de uitkomst niet domineert.

PokemonPriceTracker draait op het gratis plan (100 credits per dag), dus de marktmomentopname via die dienst levert voorlopig niets op.

### Nieuw: meersignalenplan stap 1 en 2, plus twee reparaties

**Reparatie: trackrecord liet de dagelijkse taak elke dag mislukken.** Het doorbladerde de hele tabel met onbeoordeelde voorspellingen en kreeg bij regel ~35.000 een time-out van Supabase. Nu haalt het alleen voorspellingen op waarvan de periode voorbij is, per periode en in vensters van 7 dagen (`trackrecord.fetch_due`). Voorspellingen die na 35 extra dagen nog niet beoordeeld zijn, worden opgeruimd. Nieuwe index `forecast_history_due` in het schema.

**Reparatie: beroemde Pokemon kregen niet echt 180 dagen.** Een kaart telde als klaar bij 60 dagen oude historie, ook als hij 180 dagen hoorde te krijgen. De grens schaalt nu mee met de gevraagde periode (2/3: 60 bij 90 dagen, 120 bij 180), en per kaart wordt onthouden tot hoe ver hij al is opgehaald (`products.nm_hist_days`), zodat kaarten zonder oudere verkopen niet elke nacht opnieuw credits kosten.

**Stap 1: dagelijkse marktmomentopname** (`collector/market_snapshot.py`). Elke dag voor de kaarten van de 65 beroemde Pokemon: aantal listings (aanbod), verkopers (liquiditeit) en recente verkopen (vraag), via PokemonPriceTracker, in de nieuwe tabel `market_snapshots`. Eigen budget van 12.000 PPT-credits per dag en maximaal 40 minuten. Een trend ontstaat pas na een paar weken.

**Stap 2: signalen per kaart** (`collector/signals.py`, tabel `card_signals`): onder_gemiddelde, momentum, stabiliseert, reprint, en zodra er 14 dagen momentopnames zijn ook aanbod, vraag en liquiditeit. Elk +1, 0 of -1. `python signals.py --backtest` laat per signaal zien hoe vaak er daarna binnen 30 dagen een stijging van 10% kwam, vergeleken met gemiddeld. Home verandert nog niet: dat gebeurt pas als de backtest bevestigt dat de combinatie beter werkt.

Beide stappen draaien in een aparte workflow ("Signalen", elke dag om 12:00 UTC), zodat ze de nachtelijke taak nooit over zijn tijdslimiet duwen.

### Nieuw: koppeling met PkmnPrices controleren (collector/check_card.py)

Ontstaan uit een vreemde prijssprong bij Lapras (ecard3-71): de prijs stond wekenlang exact hetzelfde vast en sprong toen in een keer. Dit scriptje zoekt op wat er precies bij PkmnPrices achter de koppeling (pk_id) van een kaart zit, en vergelijkt de naam met wat wij zelf hebben, zodat een verkeerde koppeling meteen zichtbaar wordt:

    python check_card.py ecard3-71
    python check_card.py ecard3-71 lc-64 hgss4-18

### Nieuw: backtest + zoekinteresse naast elkaar, alleen voor de 65 beroemde Pokemon

`collector/famous_analysis.py` (workflow "Beroemde Pokemon analyseren"): draait de backtest maar dan alleen op kaarten van de 65 beroemde Pokemon (`write=False`, dus de echte kalibratie van de hele catalogus wordt niet overschreven met deze kleinere steekproef), en legt daarna voor de grootste prijssprongen die daarbij gevonden worden de Google-zoekinteresse (via Scrape.do) ernaast: was er al meer interesse vlak voor zo'n sprong, of niet? Kost ongeveer 10 credits per sprong (standaard 5 sprongen, dus ~50 credits); zonder `SCRAPEDO_API_KEY` doet het alleen de backtest.

Kleine, veilige uitbreiding aan `trackrecord.backtest()` zelf: kreeg twee nieuwe, optionele parameters (`product_ids` om te beperken tot een deelverzameling, `write=False` om alleen te berekenen zonder de database aan te passen). Bestaand gebruik (de gewone, wekelijkse backtest op de hele catalogus) werkt precies als voorheen.

### Grote wijziging: focus op 65 beroemde Pokemon, "Goedkope aanbiedingen" staat stil

Op verzoek: "Goedkope aanbiedingen" gebruikt voorlopig geen credits meer (`config.OFFERS_ENABLED = False`). Het blokje blijft gewoon in de app staan, met steeds oudere gegevens, tot dit onderdeel later weer wordt opgepakt. Het vrijgekomen budget gaat naar een nieuwe prioriteit: 65 Pokemon (samen met de gebruiker vastgesteld op basis van aantal kaarten x gemiddelde prijs in onze eigen data, zie config.FAMOUS_DEX_IDS) krijgen voortaan voorrang op geschiedenis, net als de eigen collectie:

- Gewone (ongegradeerde) geschiedenis mag voor deze 65 dieper terug dan de standaard 90 dagen: tot 180 dagen (config.FAMOUS_HISTORY_DAYS).
- Nieuw: gegradeerde geschiedenis (collector/graded_history.py) voor diezelfde 65, via PSA/BGS/CGC. Alleen graad 1 en 7-tot-en-met-de-hoogste per bedrijf (dus niet 2 t/m 6); eerst 90 dagen, en verder tot 180 dagen als er nog budget over is. BGS Black Label en CGC Pristine 10 zijn bewust nog niet meegenomen: dat zijn geen gewone cijfergraden maar aparte labels, en de juiste manier om die bij PkmnPrices op te vragen is nog niet uitgezocht.
- De rest van de catalogus blijft gewoon meelopen op het huidige niveau, geen harde knip.

### Bugfix: een Supabase-time-out tijdens het opslaan legde de geschiedenis-opbouw stil

Een time-out tijdens het opslaan van een enkele kaart brak de hele kaartgeschiedenis af, waardoor ongeveer 14.000 credits die dag onbenut bleven. Nu:
- Schrijfverzoeken die veilig herhaald kunnen worden (upsert, patch, delete) proberen het bij een time-out of 502/503/504 automatisch tot 3 keer.
- Lukt het opslaan van een kaart toch niet, dan wordt alleen die kaart overgeslagen (de volgende run pakt hem weer op) en gaat de rest door. Na 5 mislukkingen achter elkaar stopt de run, om geen credits te verspillen aan een database die echt weg is.
- Hetzelfde vangnet zit bij laagste aanbiedingen. Daar wordt bovendien eerst opgeslagen en pas daarna opgeruimd, zodat een mislukte opslag nooit de oude aanbiedingen wegneemt.

### Bugfix: de dagelijkse taak crashte op de lange periodes (maandag 28 sep)

Bij kaarten met extreem wilde prijzen in de Near Mint-geschiedenis (bijvoorbeeld €15 naast €590) rekende het model bij lange periodes (6-24 maanden) met een spreiding die zo groot was dat het getal buiten bereik viel (`OverflowError`). Omdat de taak daar geen vangnet had, werden ook het uitgeven van de PkmnPrices-credits, het trackrecord, de meldingen en het opruimen overgeslagen. Hersteld op drie niveaus:
- **Rekenkundig**: de spreiding over de hele periode heeft een bovengrens (`config.MAX_SD_H`), en de verwachte stijging kan nooit boven de doorgetrokken-trendgrens uitkomen. Gewone kaarten rekenen precies hetzelfde als eerst.
- **Per kaart**: een kaart met onbruikbare prijsdata wordt overgeslagen (en gelogd), de rest wordt gewoon doorgerekend.
- **Per stap**: in de dagelijkse taak houdt een mislukte stap de rest niet meer tegen, vooral het uitgeven van de credits niet, want die vervallen elke dag. Is er iets misgegaan, dan meldt de taak zich aan het eind alsnog als mislukt, zodat je het merkt.

### Nieuw: waarschuwing bij dubbele toevoeging en de zoekinteresse-test

- **Dubbele toevoeging**: voeg je een kaart toe die je al hebt (zelfde kaart, zelfde graad of conditie), dan krijg je eerst de vraag "Je hebt hier al N van. Toch nog een toevoegen?". Annuleren voegt niets toe.
- **CSV-export**: bewust nog niet in de app. Die komt later onder een nieuwe tab voor verkopen (puntkomma-gescheiden met komma als decimaalteken, zodat het direct goed opent in Nederlandse Excel).
- **Zoekinteresse-test** (`collector/trends_probe.py`, workflow "Zoekinteresse testen (Google Trends)"): haalt via Scrape.do de Google-zoekinteresse op voor een paar kaarten en legt die naast onze eigen prijsgeschiedenis, om te zien of de interesse vóór een prijssprong al steeg (Electivire LV.X is de testcase). Kost 10 credits per opzoeking; de standaardtest is 80 credits van de gratis 1.000 per maand. Nodig: secret `SCRAPEDO_API_KEY`. Het script print ook de ruwe structuur van het eerste antwoord, zodat we na de eerste echte run kunnen zien of de uitlezing klopt.

### Bugfix + uitbreiding: icoon en logo op elk scherm

Het app-icoon stond scheef uitgesneden (rand ontbrak rechts/onder) door een net iets te krappe uitsnede uit het bronplaatje; opnieuw en ruimer uitgesneden, nu symmetrisch. Het "pokédeals"-logo staat nu op elk scherm (Home, Zoeken, Collectie, Watchlist, Instellingen, Trackrecord), niet meer alleen op Home, en is groter dan eerst.

### Nieuw thema: zwart/rood, met een echt merk

De app heeft nu een eigen, consistent zwart thema (niet meer afhankelijk van de systeeminstelling licht/donker), met:
- Een nieuw app-icoon: "PD" met een kroontje, geen pokébal (bewust vermeden vanwege merkrechten).
- Een "pokédeals"-logo bovenaan het Home-scherm.
- Rode/goud-achtige merkkleur, los van de bestaande groen/rood voor stijging/daling (die blijven ongewijzigd, om verwarring te voorkomen).
- Ronde, "zwevende" kaartvakken met een subtiele schaduw en lichtrand, in plaats van platte, randvolle stroken.

Het app-icoon moet je zelf nog een keer opnieuw installeren op je telefoon (verwijderen van het beginscherm en opnieuw toevoegen) om het bijgewerkte icoon te zien; de PWA-cache ververst niet vanzelf het icoon zelf.

### Nieuw: gegarandeerd budget voor aanbiedingen bij de duurste kaarten

Er is nu een aparte, vroege stap die de 700 duurste kaarten onder €500 van "laagste aanbiedingen" voorziet, met een eigen budget van 14.000 credits, los van wat de geschiedenis-opbouw daarna nog gebruikt (`config.DEALS_MAX_PRICE`, `DEALS_TOP_N`, `DEALS_BUDGET`). Het dagbudget van de geplande taken ging daarvoor omhoog naar 64.000 (was 50.000), en blijft daarmee nog altijd onder het echte plan van 75.000.

### Nieuw: kaarten zonder foto's krijgen er via PPT alsnog een, zonder extra kosten

We halen via PPT (voor de historie van de nieuwste sets) al een fotoveld op, maar gebruikten het nergens. Dat is precies waar het foto-probleem het meest speelde (hele nieuwe sets waar TCGdex zelf nog geen scans van heeft). Kost geen extra API-aanroepen.

### Aangepast: "Goedkope aanbiedingen" ook bij een vast bedrag korting

Een kaart komt nu in het vak te staan als de laagste aanbieding **20% of meer** onder het gemiddelde van de andere aanbiedingen ligt (was 25%), **óf** als het gewoon **€25 of meer** goedkoper is. Dat laatste vangt dure kaarten op waar een fors bedrag toch onder de 20% blijft.

### Nieuw: kaarten zonder foto kunnen worden aangevuld

Op eigen verzoek uitgezocht met echte cijfers: 1.748 van de 23.735 kaarten (~7,4%) missen een foto, los van sealed (die nog volledig wachten op de koppeltaak). Nieuwe eenmalige opdracht:

    python backfill.py --images

Haalt specifiek de kaarten zonder foto opnieuw op bij TCGdex, buiten de normale, prijsgestuurde volgorde om (die dit soort kaarten anders pas na een lange tijd opnieuw zou proberen). Meldt aan het eind hoeveel er alsnog een foto kregen, en hoeveel er bij TCGdex zelf nog steeds ontbreekt (dat is dan een gat in hún scans, geen bug bij ons).

### Controle van ChatGPT-aanpassingen, met reparaties

Je liet me een set wijzigingen controleren die via ChatGPT waren gemaakt (Kansen → Home, zoeken op setcode/nummer, foto's in Zoeken). Bevindingen en reparaties:

- **Kapotte `collection.js`**: twee losse haakjes-fouten (in de nieuwe "aankopen groeperen"-functie) zorgden ervoor dat het hele bestand niet kon laden. Hersteld.
- **Setcode-zoeken werkte niet zoals bedoeld**: er zat een lijstje van 12 hardgecodeerde afkortingen in, die zelfs het eigen voorbeeld ("c30" voor 30th Celebration) niet dekten. Herbouwd zodat het de **eigen sets-tabel** gebruikt: nu werkt zoeken op (een deel van) de echte setnaam of het echte kaartnummer voor de volledige catalogus, bijvoorbeeld "charizard base set 4" of "charizard 4".
- **Foto's uitgezocht**: geen bug in ons eigen ophalen (TCGdex heeft ook voor oude kaarten gewoon foto's). Het echte gat zit bij **sealed producten**, die nog helemaal geen foto hebben omdat de eenmalige koppeltaak (`enrich.py --sealed`) nog nooit is gedraaid.
- **"Goedkope aanbiedingen" vergeleek tegen de trendprijs** in plaats van tegen de andere aanbiedingen onderling — teruggezet naar de veiligere, eerder gekozen methode (zie de Electivire-discussie hierboven).
- **PSA/gegradeerd-label** raakte kwijt in de nieuwe "aankopen groeperen"-functie van Collectie — teruggezet.
- Onderweg nog twee botsingen tussen gelijknamige CSS-klassen gevonden en gerepareerd (`.row` en `.chance` werden dubbel gebruikt), die de Kansen- en kaartdetailpagina in de war stuurden.

Overgenomen, ongewijzigd: de Home-hernoeming (titel + onderbalk), het hartje om direct te volgen vanaf een lijst, de prijsgrafiek die de periodeknoppen volgt, en de cache-versie-ophoging.

### Aangepast: dagbudget naar 50.000, bewust ruimte over

De geplande taken gebruiken voortaan maximaal 50.000 credits per dag in plaats van 72.000 (`config.PK_BUDGET`), zodat er dagelijks zo'n 25.000 credits overblijven die de automatische taken niet aanraken. Die ruimte is bedoeld om zelf mee te experimenteren (bijvoorbeeld nieuwe dingen uitproberen) zonder dat je hoeft te wachten tot na de volgende reset.

### Nieuw: "Goedkope aanbiedingen" boven de lijst met Kansen

Een nieuw vak bovenaan het scherm Kansen, los van de bestaande (trend-gebaseerde) kansberekening: kaarten waar de laagste actuele aanbieding minstens 25% onder het gemiddelde van de andere aanbiedingen ligt. Dit vangt het scenario dat een kaart normaal voor bijvoorbeeld €30 wordt verkocht en er ineens één aanbod van €15 tussen staat — een directe, feitelijke vergelijking met wat er nú te koop staat, in plaats van een voorspelling op basis van prijsgeschiedenis. Werkt alleen voor kaarten waar al aanbiedingen zijn opgehaald (collectie + beste kansen), dus dekt nooit de hele catalogus. Ook een interactieve schuifbalk toegevoegd aan alle prijsgrafieken: sleep of tik erover om de prijs op elke dag te zien.

### Aangepast: "Waarde nu" en "Winst" op basis van echte aanbiedingen, niet de trendprijs

Bij kaarten met weinig verkopen en een grote prijsspreiding kan Cardmarkets trendprijs ver boven wat er nu daadwerkelijk te koop staat liggen (bevestigd met een concreet voorbeeld: trend €1.044, laagste aanbieding €600). De kaartdetailpagina toont nu, zodra er aanbiedingen zijn opgehaald, het gemiddelde van de laagste 5 actuele Near Mint-aanbiedingen als hoofdbedrag ("Waarde nu", "Winst", de winstgrens), met de trendprijs er nog steeds apart bij als vergelijking. Geldt vooralsnog alleen op de detailpagina, niet op het Collectie-overzicht.

### Bugfix: de grafiek klopte niet meer bij net gekochte of Near Mint-gebaseerde kaarten

Twee dingen gevonden en hersteld:
- Bezat je een kaart nog maar kort, dan knipte de grafiek zich af tot alleen de dagen na je aankoopdatum, en liet dus bijna niets zien. De grafiek toont voortaan altijd de volledige geschiedenis; "Prijs sinds aankoop" als apart concept is vervallen.
- Bij kaarten waarvan de kans al op de eigen Near Mint-geschiedenis draait, liet de grafiek toch nog de gemengde Cardmarket-trend zien: twee verschillende bronnen die niet bij elkaar pasten. De grafiek gebruikt nu dezelfde Near Mint-reeks als de kansberekening zodra die de basis is.

### Trackrecord: de backtest gebruikt nu ook de Near Mint-geschiedenis

De backtest (die de kansberekening terugrekent op bestaande data) draaide voor elke kaart nog op de Cardmarket-trend, ook voor kaarten die in het echt inmiddels op hun eigen Near Mint-geschiedenis draaien. Daardoor zei de uitkomst van de backtest niets over de kans die je daadwerkelijk in de app ziet bij die kaarten. Dat is nu gelijkgetrokken: de backtest gebruikt dezelfde basis (Near Mint of trend) als de echte dagelijkse berekening.

### Aangepast: geschiedenisperiode naar 45 dagen (sneller, minder credits)

Na een paar keer heen en weer rekenen: de eenmalige geschiedenis-opbouw vraagt nu 45 dagen op in plaats van 90 (`config.HISTORY_PERIOD`), met de "heeft deze kaart al genoeg?"-grens op 35 dagen. Ruwweg de helft van de tijd en credits van de 90-dagenversie, met nog altijd een echte voorsprong op wat de gewone dagelijkse verversing er vanzelf bij zou doen.

### Bugfix: geschiedenis-opbouw vroeg meer op dan nodig

`card_history.py` en `sealed_history.py` stuurden geen limiet mee voor hoever terug in de tijd, waardoor PkmnPrices waarschijnlijk veel meer historie teruggaf (en in rekening bracht) dan de bedoelde periode. Dat kostte extra credits én extra tijd, zonder dat het iets opleverde. Beide vragen nu expliciet maar 90 dagen op (`config.HISTORY_PERIOD`), wat de opbouw flink sneller en goedkoper zou moeten maken.

### Aangepast: ook de dagelijkse NM-prijs zelf staat tijdelijk stil

Naast het uitzetten van "breder koppelen" staat nu ook het **dagelijks verversen van de actuele Near Mint-prijs** stil (`config.NM_REFRESH_PRICE = False`). Koppelen van nieuwe kaarten aan PkmnPrices blijft wel gewoon doorgaan, want dat is nodig om nieuwe kaarten in aanmerking te laten komen voor `card_history.py`. Vrijwel het hele dagbudget gaat nu naar geschiedenis-opbouw (kaarten en sealed). Zet je dit later weer aan, dan ververst de actuele prijs weer dagelijks zoals voorheen.

### Aangepast: geschiedenis-opbouw krijgt voorrang op verbreden

Zodra de vaste lijst van 1.200 kaarten klaar was, ging de NM-taak vanzelf door met steeds meer kaarten daarbuiten koppelen, wat al het overgebleven budget opsoupeerde vóór de eigenlijke geschiedenis-opbouw (`card_history.py`) aan de beurt kwam. Die verbreding staat nu standaard uit (`config.NM_WIDEN_EXTRA = False`), zodat na de vaste lijst al het resterende budget naar geschiedenis-opbouw gaat. Zet je dit later weer aan (bijvoorbeeld zodra de geschiedenis ver genoeg is), dan gaat de app weer breder koppelen zoals voorheen.

### Bugfix: een kleine controle mocht niet de hele taak laten mislukken

De "wie is er vandaag al gedaan"-controle in `nm.py`, de "wie heeft al genoeg historie"-controle in `card_history.py`, en de "wie is nog vers"-controle in `offers.py` konden bij een haperende databaseverbinding de hele taak laten mislukken, terwijl het maar kleine optimalisaties zijn. Falen ze nu, dan gaat de taak gewoon door alsof niemand nog iets heeft (iets minder efficiënt die ene keer, maar geen verloren run meer).

### Nieuw: kaartdetailpagina flink uitgebreid

- **Echte verkoopkosten overal:** de commissie staat nu op 6% (5% Cardmarket + 1% Trustee Service, als veilige aanname), en de vaste verzendkosten (€1,50) zijn vervangen door een tabel die oploopt met de verkoopprijs (tot €15 bij dure kaarten). Dit raakt de "netto winst"-filter op Kansen, de dagelijkse samenvatting, en de nieuwe winstgrens hieronder. Instellingen heeft geen los verzendveld meer.
- **Winstgrens:** een nieuw blok dat laat zien welke verkoopprijs nodig is om quitte te spelen — bij een kaart die je bezit vanaf je aankoopprijs, bij een kaart die je nog niet hebt vanaf de huidige prijs.
- **Laagste aanbiedingen (Near Mint):** een lijst met de goedkoopste actuele aanbiedingen op Cardmarket (prijs, verkoper, aantal), via PkmnPrices. Alleen voor je collectie en de beste kansen, en niet dagelijks ververst (kost 20 credits per kaart), want dit staat achteraan in de dagelijkse volgorde, na de Near Mint-geschiedenis en sealed-geschiedenis.
- **Duidelijkere "Waarom deze kans?":** elke regel heeft nu een kleurtint en een kort label (Positief/Matig/Hoog) naast een heldere zin, in plaats van alleen een kaal getal.
- **Nieuwe identificatierij:** Zeldzaamheid, Uitgiftedatum en Taal, boven de prijzen.

Dit vraagt weer om het volledige `supabase/schema.sql` opnieuw te draaien (nieuwe tabel `offers`, en `v_search` heeft nu ook de releasedatum van de set).

### Bugfix: crash bij "extra kaarten" door een dubbele sleutel

Zodra er na de vaste lijst nog budget overbleef, kon de taak crashen met een Postgres-foutmelding over een dubbele sleutel. Oorzaak: een kaart heeft nu meerdere periodes (7 dagen tot 24 maanden), en de functie die extra kaarten kiest telde zo'n kaart per ongeluk voor elke periode apart mee. Opgelost op twee plekken: de functie zelf (`extra_targets` in `nm.py`) telt een kaart nu maar 1x, en `store.py` negeert voortaan sowieso een dubbele sleutel binnen dezelfde opslagactie in plaats van te crashen, als extra vangnet.

### Aangepast: dagbudget naar 75.000 en een goedkopere zoekopdracht

Het dagbudget stond nog vast op 15.000 (van vóór de upgrade naar het Pro-plan). Dat staat nu op 72.000 (`config.PK_BUDGET`), met een kleine marge onder de echte 75.000. De zoekopdracht om een kaart aan PkmnPrices te koppelen vroeg tot nu toe veel te veel resultaten op (tot 100 per kaart, elk apart in rekening gebracht) — dat is nu een stuk kleiner (15, en geen tweede pagina meer), plus het kaartnummer wordt meegestuurd voor het geval dat verder helpt filteren. Nog niet in de praktijk getest; de eerste run laat zien of de kosten per kaart echt omlaag gaan.

### Bugfix: tussentijds opslaan, zodat credits nooit voor niets worden uitgegeven

Bij een grote database kon één traag databaseverzoek de hele NM-prijzentaak laten crashen, terwijl er al wel credits bij PkmnPrices waren uitgegeven en er nog niets was opgeslagen. `nm.py` slaat nu elke 150 kaarten tussentijds op in plaats van pas aan het eind, en `store.py` probeert een traag of weggevallen verzoek één keer opnieuw met meer geduld voordat het opgeeft. `card_history.py` en `sealed_history.py` deden dit al goed (per kaart/product), die zijn ongewijzigd.

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

## Ronde 4: gegradeerde geschiedenis sneller en eerlijker
- Je **eigen gegradeerde kaarten** (collectie) gaan voor, ook als de Pokémon niet bij de beroemde hoort (dan alleen jouw graad). Daarna: nooit opgevraagd, langst geleden, best verhandelde graad, duurste kaart (niet meer op alfabet).
- `GRADED_BUDGET` van 4.000 naar 12.000 credits per run; het logboek schat nu hoeveel runs er nog nodig zijn.
- **Foto's** (`collector/images.py`, elke nacht): 1/7 van de kaartfoto's wordt gecontroleerd (404/410 = link leeggemaakt, twijfel = laten staan); kaarten zonder foto krijgen er een via TCGdex (alle talen), daarna via PkmnPrices (max. `IMAGES_PK_BUDGET` = 3.000 credits). Het logboek noemt de sets waar foto's ontbreken. In de app valt een niet ladende foto terug op het lege kaartje (cache v2-18). Handmatig alles in één keer: workflow Historie ophalen met `images = ja`.

## Ronde 5: app-fouten
- **Zoeken:** `30c` dekt nu ook de 30th Classic Collection (daar staat Charizard "30C BS4", bij ons nummer 001). Staat het nummer niet in de bedoelde set, dan toont de zoekfunctie eerst de kaarten met die naam uit díe set (niet meer alle Charizards met nummer 4), en kaarten waarvan de Cardmarket-link al je woorden bevat staan bovenaan.
- **Foto's:** kaart zonder (werkende) foto toont naam en nummer op het lege kaartje. `IMAGES_PK_BUDGET` is 3.000 credits per run.
- **Verkopen:** knop *Selecteren* in de collectielijst (A–Z), vakjes naast de kaarten, balk onderaan met *Verkopen (n)*, en dan één scherm met alle gegevens (aantal per kaart aan te passen). Het tussenscherm is weg.
- **Cardmarkets eigen kaartnaam** (`collector/cm_names.py`, kolom `products.cm_name`): voor elke aan Cardmarket gekoppelde kaart bewaren we uit Cardmarkets openbare lijst (`products_singles_6.json`) de naam met code ("Charizard (30C BS4)"). Zoeken kijkt daar ook in (bij 3+ woorden eerst), toont "Cardmarket: …" onder het resultaat (alleen als die naam een code tussen haakjes heeft) en geeft zulke treffers voorrang. Vereist `supabase/schema.sql` opnieuw te draaien. Alleen voor gekoppelde kaarten; de koppeling loopt via `cm_links`.
- Het nep-databasetje in de offline test controleert nu NOT NULL op de meegestuurde rij, zoals Postgres. Daardoor kwam aan het licht dat de foto-updates de naam mee moesten sturen; dat is aangepast.
- **Zoeken legt uit hoe het je zoekopdracht las** (kleine grijze regel onder de resultaten: naam, set, nummer en via welke weg de treffers kwamen).
- **Aankoop aanvullen:** in het Aankoop-scherm staat bovenaan een keuzelijst "Nieuwe aankoop, of aanvullen" met je laatste aankopen. Kies je er één, dan komen de nieuwe kaarten in dezelfde aankoop (zelfde bestelnummer en verkoper) en worden verzending en trustee fee opnieuw verdeeld over alle kaarten van die aankoop, naar prijs.
