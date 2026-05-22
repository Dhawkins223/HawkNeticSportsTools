"""Math additions to odds_math: Kelly criterion + binomial margin of error.

Existing primitives (american_to_decimal, american_to_implied_probability,
decimal_to_american, no_vig_probabilities, parlay_decimal_odds,
expected_value, fair_decimal_odds) live in odds_math.py and remain unchanged.
"""
from __future__ import annotations

from math import sqrt
from typing import Optional


def kelly_fraction(decimal_odds: float, model_probability: float) -> float:
    """Full Kelly stake fraction. Negative edge → 0 (do not bet)."""
    if decimal_odds is None or decimal_odds <= 1 or model_probability is None:
        return 0.0
    b = decimal_odds - 1
    p = max(0.0, min(model_probability, 1.0))
    q = 1 - p
    full = (b * p - q) / b
    return max(0.0, full)


def fractional_kelly(decimal_odds: float, model_probability: float, fraction: float = 0.25) -> float:
    """Recommended bankroll fraction using a 1/4-Kelly safety multiplier by default."""
    return kelly_fraction(decimal_odds, model_probability) * max(0.0, fraction)


def binomial_standard_error(probability: float, sample_size: int) -> float:
    """SE = sqrt(p*(1-p)/N). Used to derive the 95% CI of a simulation estimate."""
    if sample_size <= 0:
        return 0.0
    p = max(0.0, min(probability, 1.0))
    return sqrt(p * (1 - p) / sample_size)


def confidence_interval_95(probability: float, sample_size: int) -> tuple[Optional[float], Optional[float]]:
    """Returns (lower, upper) 95% CI for a binomial proportion."""
    if sample_size <= 0:
        return None, None
    se = binomial_standard_error(probability, sample_size)
    half = 1.96 * se
    return max(0.0, probability - half), min(1.0, probability + half)
