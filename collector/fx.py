"""Wisselkoers USD -> EUR (sealed en graded prijzen komen in dollars binnen)."""
import config


def usd_to_eur(session):
    """Probeert de dagkoers (ECB via Frankfurter); valt terug op config.FX_FALLBACK."""
    try:
        r = session.get("https://api.frankfurter.dev/v1/latest", params={"base": "USD", "symbols": "EUR"}, timeout=15)
        r.raise_for_status()
        rate = float(r.json()["rates"]["EUR"])
        if 0.3 < rate < 3:
            return rate, "frankfurter"
    except Exception:
        pass
    return config.FX_FALLBACK, "fallback"
