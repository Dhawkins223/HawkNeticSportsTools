from __future__ import annotations

from collections import Counter
from math import prod

from .implied import clamp_probability, probability_to_cents


def combined_probability(probabilities: list[float]) -> float:
    if not probabilities:
        raise ValueError("combo requires at least one leg")
    return clamp_probability(prod(clamp_probability(probability) for probability in probabilities))


def repeated_context_penalty(contexts: list[str], per_extra_leg: float = 0.03) -> float:
    counts = Counter(contexts)
    extra_legs = sum(max(0, count - 1) for count in counts.values())
    return min(0.35, extra_legs * per_extra_leg)


def adjusted_combo_probability(probabilities: list[float], contexts: list[str]) -> tuple[float, float, float]:
    raw_probability = combined_probability(probabilities)
    penalty = repeated_context_penalty(contexts)
    adjusted_probability = clamp_probability(raw_probability * (1.0 - penalty))
    return raw_probability, adjusted_probability, penalty


def combo_ev_cents(adjusted_probability: float, average_entry_price_cents: float) -> float:
    return round(probability_to_cents(adjusted_probability) - average_entry_price_cents, 2)


def parlay_decimal_odds(probabilities: list[float]) -> float:
    probability = combined_probability(probabilities)
    if probability <= 0:
        raise ValueError("combined probability must be greater than zero")
    return round(1.0 / probability, 6)


def payout_for_stake(stake_dollars: float, combo_probability: float) -> float:
    combo_probability = clamp_probability(combo_probability)
    if stake_dollars < 0:
        raise ValueError("stake cannot be negative")
    if combo_probability <= 0:
        return 0.0
    return round(stake_dollars / combo_probability, 2)
