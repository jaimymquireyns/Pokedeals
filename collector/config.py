"""Instellingen op één plek."""
import re

# ---- Verzamelen ----
WORKERS = 4                # gelijktijdige verzoeken naar TCGdex
MIN_TRACK_PRICE = 1.50     # kaarten onder dit bedrag (EUR) worden maar 1x per week ververst
RECHECK_CHEAP_DAYS = 7
HISTORY_DAYS = 60          # zoveel dagen historie gebruikt het model
PRUNE_CHEAP_DAYS = 14      # goedkope kaarten: alleen de laatste 14 dagen bewaren (bespaart opslag)
FX_FALLBACK = 0.86         # USD -> EUR als de koers niet op te halen is

# ---- Cardmarket (openbare prijslijst) ----
CARDMARKET_GAME_ID = 6     # Pokémon

# ---- PokemonPriceTracker (alleen nog voor kaarthistorie en gegradeerde prijzen) ----
PPT_BASE = "https://www.pokemonpricetracker.com/api/v2"
PPT_DAILY_BUDGET = 15000   # max. credits per dag die we zelf gebruiken (plan: 20.000)
PPT_HISTORY_DAYS = 180     # API-plan: 6 maanden historie

# ---- Wat de app te zien krijgt ----
MIN_PRICE = 2.00
GRID = [(14, 10), (30, 10), (60, 10), (14, 20), (30, 20), (60, 20), (7, 5), (14, 7)]  # (dagen, beweging in %) - dagelijks
LONG_GRID = [(90, 20), (180, 35), (365, 60), (730, 100)]  # periodes op de kaartdetailpagina (3-24 maanden): 1x per week (maandag)
STANDARD = (30, 10)        # combinatie voor trackrecord, aandacht-lijst en samenvatting

# ---- Model ----
MIN_HISTORY_POINTS = 10
SIGMA_FLOOR = 0.03
AVG_MODE_SHRINK = 0.35
FAST_MAX_DRIFT = 0.004     # 'snel'-modus (weinig data): hooguit ±0,4% per dag, dus ±13% over 30 dagen
FAST_MAX_SIGMA = 0.06      # in 'snel'-modus is de spreiding een aanname: nooit meer dan 6% per dag
FAST_SPIKE = 0.30          # prijs >30% van het 30-daags gemiddelde af = sprong; die trekken we niet door
SHRINK_K = 30
MAX_DAILY_DRIFT = 0.02
MAX_HORIZON_RETURN = 3.0   # ook bij lange periodes (tot 24 maanden): de doorgetrokken trend wordt nooit gekker dan +300% of -99%
MAX_SD_H = 3.0               # bovengrens op de spreiding over de hele periode (in ln-eenheden): daarboven weten we toch niets meer, en het rekent anders door tot getallen buiten bereik (uitschieters in de prijsdata)
HORIZON_DAYS = 30
MOVE_THRESHOLD = 0.10
CALIBRATE_MIN_N = 50       # pas kalibreren als een kansklasse minstens zoveel uitkomsten heeft

# ---- Signalen ----
BUY_MIN_P_UP = 0.40
BUY_MAX_P_DOWN = 0.20
SELL_MIN_P_DOWN = 0.40
SELL_MAX_P_UP = 0.20

# ---- Aandacht nodig / samenvatting ----
ATTN_MIN_P_DOWN = 0.35
ATTN_PROFIT = 0.30         # winst vanaf 30% + weinig kans op méér stijging => 'winst nemen?'
ATTN_MAX_P_UP = 0.25
DIGEST_MIN_P_UP = 0.60

# ---- Laagste Near Mint-prijs per kaart (PkmnPrices Pro) ----
# Cardmarket-commissie (5%) + Trustee Service (1%, het voorzichtige uiteinde van 0,5-1%): samen als vaste veilige aanname.
DEFAULT_FEE_PCT = 6.0
# Geschatte verzending die je als KOPER betaalt bij een Cardmarket-aankoop, op basis van de kaartprijs. De verzending
# bij het verkopen betaalt de koper (jij koopt er de postzegel van), dus die telt niet als kost; wel verpakking.
# Onder EUR25 gewone post (rond EUR3), vanaf EUR25 als pakket (duurder). Een schatting naar de ervaring van de gebruiker; pas aan als de tarieven veranderen.
SHIP_TIERS = [(24.99, 3.00), (50, 7.00), (150, 10.00), (float("inf"), 15.00)]
PACKAGING = 0.50   # hoesje, toploader en envelop per verkoop


def ship_cost(price):
    """Geschatte verzending die je als koper betaalt voor een kaart van deze prijs."""
    for limit, cost in SHIP_TIERS:
        if price <= limit:
            return cost
    return SHIP_TIERS[-1][1]


PK_TARGETS = 1200          # zoveel kaarten volgen we dagelijks: eerst collectie en prijsmeldingen, dan de beste kansen, dan de duurste
PK_MAP_PER_RUN = 300       # zoveel nieuwe kaarten per run aan PkmnPrices koppelen (elk zoekopdracht kost credits)
NM_WIDEN_EXTRA = False     # tijdelijk uit: eerst de Near Mint-geschiedenis van de vaste lijst opbouwen, dan pas breder koppelen
NM_REFRESH_PRICE = False   # tijdelijk uit: de dagelijkse actuele NM-prijs kan wachten; koppelen blijft wel aan, dat voedt de geschiedenis-opbouw
HISTORY_PERIOD = "90d"     # hoever de eenmalige geschiedenis-opbouw terugkijkt: zonder limiet vraagt de API blijkbaar veel meer op dan nodig (en dus duurder/trager)
PK_BUDGET = 64000          # maximaal aantal credits per dag dat de geplande taken zelf gebruiken (Pro-plan: 75.000; de rest blijft bewust ongebruikt om zelf mee te kunnen testen)
DEALS_MAX_PRICE = 500      # 'goedkope aanbiedingen' voor kaarten duurder dan dit worden niet apart opgehaald
DEALS_TOP_N = 500          # ...voor de zoveel duurste kaarten onder die grens
DEALS_FAMOUS_MIN_PRICE = 10   # plus alle kaarten van de 65 beroemde Pokémon vanaf deze prijs
DEALS_BUDGET = 14000       # eigen, gegarandeerd budget hiervoor, los van wat de geschiedenis-opbouw gebruikt
OFFERS_ENABLED = True      # 'Goedkope aanbiedingen' op Home (4 okt weer aangezet): 500 duurste kaarten onder EUR500 + beroemde Pokémon vanaf EUR10, eigen budget DEALS_BUDGET, elke kaart om de 3 dagen ververst

# 65 beroemde Pokémon (dex-nummers), samen met de gebruiker vastgesteld op basis van aantal kaarten x gemiddelde
# prijs in onze eigen data. Krijgen voorrang op geschiedenis, net als de eigen collectie, en mogen dieper terug
# (180 dagen i.p.v. 90) en ook gegradeerd (PSA/BGS/CGC) worden opgebouwd.
FAMOUS_DEX_IDS = {
    150, 6, 151, 25, 94, 197, 384, 249, 149, 380, 381, 130, 248, 9, 8, 7, 4, 5, 1, 2, 3, 131, 196, 251, 258, 658,
    144, 229, 382, 487, 484, 483, 208, 383, 26, 143, 146, 134, 643, 644, 250, 145, 65, 282, 135, 243, 136, 59,
    133, 470, 244, 245, 445, 160, 157, 448, 255, 68, 471, 700, 493, 132, 778, 491, 386,
}
FAMOUS_HISTORY_DAYS = 180

# Opschonen van de Near Mint-reeks. De Near Mint-'prijs' van PkmnPrices blijkt de laagste vraagprijs te zijn, geen
# verkoopgemiddelde: als de goedkope exemplaren verdwijnen springt hij naar een absurd bedrag en blijft daar weken
# staan (Lapras EUR1.450, Snorlax EUR1.949,99). Punten die zo'n piek zijn, tellen niet mee in analyses die dat aanzetten.
EDGE_ENABLED = True            # eigen voorspelmodel (edge.py): elke dag voorspellingen vastleggen in card_signals om ze na 30 dagen echt te toetsen
EDGE_HISTORY_DAYS = 400        # zoveel dagen prijsgeschiedenis om het model op te trainen (de backtest gebruikt dezelfde)
CLEAN_NM = False             # voor de dagelijkse kansberekening; de signalen-backtest vergelijkt altijd beide versies
CLEAN_FACTOR = 3.0           # een punt dat meer dan zoveel keer boven zijn referentie ligt, is een piek
CLEAN_WINDOW_DAYS = 90       # referentie zonder Cardmarket-gemiddelde: de mediaan van de behouden punten van de laatste zoveel dagen
CLEAN_MAX_DROP_DAYS = 60     # een 'piek' die langer aanhoudt dan dit, is waarschijnlijk het nieuwe niveau en wordt weer geaccepteerd
# Pokémon TCG Pocket (de mobiele game: sets A1, A1a, A2..., B1..., P-A) zijn digitale kaarten: ze bestaan niet op papier, hebben geen
# Cardmarket-markt en komen niet bij PkmnPrices voor. Ze worden niet meer opgehaald, niet meer gekoppeld en niet getoond in de app.
DIGITAL_SET_RE = re.compile(r"^(?:[AB]\d+[a-z]?|P-[A-Z])$")


def is_digital_set(set_id):
    return bool(set_id) and DIGITAL_SET_RE.match(str(set_id)) is not None


GRADED_ENABLED = True        # gegradeerde geschiedenis (PSA/BGS/CGC) voor de beroemde Pokémon. Stond uit sinds 6 okt (de uitlezing herkende niets); hersteld op 7 okt met het echte antwoord van PkmnPrices als uitgangspunt. Op False zetten om uit te schakelen.
GRADED_BUDGET = 12000        # nooit meer dan dit per dag (1 credit per teruggegeven verkoop); bewust klein begonnen, na een paar goede nachten te verhogen
GRADED_MAX_PAGES = 3         # hoogstens zoveel pagina's (van 20 verkopen) per kaart/graad per opvraging
GRADED_RECHECK_DAYS = 14     # een kaart/graad met verkopen: pas na zoveel dagen opnieuw opvragen
GRADED_RECHECK_EMPTY_DAYS = 45   # een kaart/graad zonder enige verkoop: pas na zoveel dagen opnieuw
GRADED_MAX_UNPARSED = 20     # noodrem: zoveel opvragingen achter elkaar WEL verkopen teruggekregen maar GEEN prijspunt herkend = de uitlezing klopt niet, stoppen
PK_MISS_RETRY_DAYS = 30      # een kaart die PkmnPrices niet kon vinden, pas na zoveel dagen opnieuw zoeken (kostte elke nacht ~1 credit per kaart)
PK_MISS_RETRY_DAYS_FAMOUS = 7    # beroemde Pokémon zijn belangrijker en PkmnPrices vult zijn lijst aan: die proberen we elke week opnieuw (de rest na PK_MISS_RETRY_DAYS)
CM_LINKS_BUDGET = 1500       # PkmnPrices-credits per dag om per kaart de exacte Cardmarket-pagina op te zoeken (1 credit per kaart; ~6.000 kaarten = ongeveer 4 nachten)
CM_RETRY_DAYS = 7              # een kaart die je gebruikt (collectie, watchlist, aanbiedingen) of van een beroemde Pokémon, waar PkmnPrices geen Cardmarket-adres voor had: elke week opnieuw proberen
SNAPSHOT_PK_BUDGET = 6000    # PkmnPrices-credits per dag voor de marktmomentopname (alleen kandidaten; PokemonPriceTracker staat op het gratis plan)
SNAPSHOT_PER_PAGE = 20       # aanbiedingen per kaart per opvraging; PkmnPrices rekent per rij, dus dit is ook het maximum aan credits per kaart
SNAPSHOT_MAX_MINUTES = 40     # de aparte signalentaak krijgt 60 minuten van GitHub; de momentopname stopt ruim daarvoor
# Meersignalenplan, stap 2: grenzen per signaal (zie signals.py)
SIG_BELOW_AVG = 0.15          # >= 15% onder het 6-maandsgemiddelde = positief; >= 15% erboven = negatief
SIG_MOM_MAX = 0.10            # momentum 14 dagen tussen 0% en +10% = begint te herstellen (positief)
SIG_MOM_SPIKE = 0.25          # meer dan +25% in 14 dagen = piek, zakt vaak terug (negatief)
SIG_MOM_FALLING = -0.10       # meer dan 10% gedaald in 14 dagen = valt nog (negatief)
SIG_STABLE_CV = 0.05          # schommeling laatste 14 dagen onder 5% = gestabiliseerd
SIG_MIN_SELLERS = 3           # minder verkopers = dunne markt (zoals Lapras op EUR1.450): negatief
SIG_MIN_SNAPSHOT_DAYS = 14    # aanbod/vraag-trend pas meetellen na zoveel dagen momentopnames   # beroemde Pokémon: geschiedenis (ongegradeerd én gegradeerd) mag dieper terug dan de standaard 90 dagen
PK_TIME_BUDGET = 4 * 3600         # dagelijkse update: stopt zelf na 4 uur, ruim binnen de 5 uur die GitHub Actions daarvoor krijgt
PK_CREDITS_ONLY_TIME_BUDGET = 50 * 60  # late 'credits opmaken'-taak: die heeft zelf maar 1 uur van GitHub, dus stopt na 50 minuten
