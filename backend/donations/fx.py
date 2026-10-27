"""Approximate foreign-currency rates for price hints ("about $6"). Visitors always pay in rupees."""
import os

from django.conf import settings
from django.utils import timezone

# Used for any currency missing from settings.FX_RATES (1 INR = x units).
DEFAULT_RATES = {"USD": "0.012", "EUR": "0.011", "GBP": "0.0095", "AED": "0.044"}


def parse_rates(raw):
    """'USD=0.012,EUR=0.011' -> {'USD': 0.012, 'EUR': 0.011}; bad entries are skipped."""
    rates = {}
    for part in (raw or "").split(","):
        code, _, value = part.partition("=")
        code = code.strip().upper()
        try:
            rate = float(value.strip())
        except ValueError:
            continue
        if len(code) == 3 and code.isalpha() and code != "INR" and rate > 0:
            rates[code] = rate
    return rates


def current_rates():
    rates = {code: float(v) for code, v in DEFAULT_RATES.items()}
    rates.update(parse_rates(getattr(settings, "FX_RATES", "")))
    return {
        "base": "INR",
        "rates": dict(sorted(rates.items())),
        # Set FX_RATES_UPDATED=YYYY-MM-DD in .env when the rates are revised; otherwise today's date.
        "updated": os.getenv("FX_RATES_UPDATED") or timezone.localdate().isoformat(),
    }
