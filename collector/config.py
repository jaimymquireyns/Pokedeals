"""Instellingen op één plek."""

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
# Geschatte verzendkosten, oplopend met de verkoopprijs (Cardmarkets eigen tarieven zijn niet automatisch op te halen).
SHIP_TIERS = [(5, 1.50), (20, 4.00), (50, 7.00), (150, 10.00), (float("inf"), 15.00)]


def ship_cost(price):
    """Geschatte verzendkosten bij een verkoop van deze waarde."""
    for limit, cost in SHIP_TIERS:
        if price <= limit:
            return cost
    return SHIP_TIERS[-1][1]


PK_TARGETS = 1200          # zoveel kaarten volgen we dagelijks: eerst collectie en prijsmeldingen, dan de beste kansen, dan de duurste
PK_MAP_PER_RUN = 300       # zoveel nieuwe kaarten per run aan PkmnPrices koppelen (elk zoekopdracht kost credits)
NM_WIDEN_EXTRA = False     # tijdelijk uit: eerst de Near Mint-geschiedenis van de vaste lijst opbouwen, dan pas breder koppelen
NM_REFRESH_PRICE = False   # tijdelijk uit: de dagelijkse actuele NM-prijs kan wachten; koppelen blijft wel aan, dat voedt de geschiedenis-opbouw
PK_BUDGET = 72000          # maximaal aantal credits per dag (Pro-plan: 75.000; kleine marge ingebouwd)
PK_TIME_BUDGET = 4 * 3600         # dagelijkse update: stopt zelf na 4 uur, ruim binnen de 5 uur die GitHub Actions daarvoor krijgt
PK_CREDITS_ONLY_TIME_BUDGET = 50 * 60  # late 'credits opmaken'-taak: die heeft zelf maar 1 uur van GitHub, dus stopt na 50 minuten
