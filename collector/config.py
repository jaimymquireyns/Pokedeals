"""Instellingen op één plek."""

# ---- Verzamelen ----
WORKERS = 4                # gelijktijdige verzoeken naar TCGdex
MIN_TRACK_PRICE = 1.50     # kaarten onder dit bedrag (EUR) worden maar 1x per week ververst
RECHECK_CHEAP_DAYS = 7
HISTORY_DAYS = 60          # zoveel dagen historie gebruikt het model
PRUNE_CHEAP_DAYS = 14      # goedkope kaarten: alleen de laatste 14 dagen bewaren (bespaart opslag)
FX_FALLBACK = 0.86         # USD -> EUR als de koers niet op te halen is

# ---- PokemonPriceTracker ----
PPT_BASE = "https://www.pokemonpricetracker.com/api/v2"
PPT_DAILY_BUDGET = 15000   # max. credits per dag die we zelf gebruiken (plan: 20.000)
PPT_HISTORY_DAYS = 180     # API-plan: 6 maanden historie

# ---- Wat de app te zien krijgt ----
MIN_PRICE = 2.00
GRID = [(14, 10), (30, 10), (60, 10), (14, 20), (30, 20), (60, 20)]  # (dagen, beweging in %)
STANDARD = (30, 10)        # combinatie voor trackrecord, aandacht-lijst en samenvatting

# ---- Model ----
MIN_HISTORY_POINTS = 10
SIGMA_FLOOR = 0.03
AVG_MODE_SHRINK = 0.35
SHRINK_K = 30
MAX_DAILY_DRIFT = 0.02
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
