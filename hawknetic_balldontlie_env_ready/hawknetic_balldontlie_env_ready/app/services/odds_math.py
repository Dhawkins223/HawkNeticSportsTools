from __future__ import annotations

from math import prod


def american_to_decimal(american_odds: int) -> float:
    if int(american_odds) == 0:
        raise ValueError("American odds cannot be zero.")
    return 1 + american_odds / 100 if american_odds > 0 else 1 + 100 / abs(american_odds)


def american_to_implied_probability(american_odds: int) -> float:
    if int(american_odds) == 0:
        raise ValueError("American odds cannot be zero.")
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return abs(american_odds) / (abs(american_odds) + 100)


def decimal_to_american(decimal_odds: float | None) -> int | None:
    if decimal_odds is None or decimal_odds <= 1:
        return None
    if decimal_odds >= 2:
        return int(round((decimal_odds - 1) * 100))
    return int(round(-100 / (decimal_odds - 1)))


def no_vig_probabilities(side_a_odds: int, side_b_odds: int) -> tuple[float, float, float]:
    p_a = american_to_implied_probability(side_a_odds)
    p_b = american_to_implied_probability(side_b_odds)
    overround = p_a + p_b
    if overround <= 0:
        return p_a, p_b, overround
    return p_a / overround, p_b / overround, overround


def parlay_decimal_odds(decimal_odds: list[float]) -> float:
    return prod(decimal_odds) if decimal_odds else 0


def expected_value(stake: float, decimal_odds: float, model_probability: float | None) -> float | None:
    if model_probability is None:
        return None
    profit_if_win = stake * (decimal_odds - 1)
    return model_probability * profit_if_win - (1 - model_probability) * stake


def fair_decimal_odds(model_probability: float | None) -> float | None:
    if model_probability is None or model_probability <= 0:
        return None
    return 1 / model_probability
