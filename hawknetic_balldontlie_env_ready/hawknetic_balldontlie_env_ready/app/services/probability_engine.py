from __future__ import annotations

from typing import Any

from app.database import execute
from app.services.odds_math import american_to_implied_probability, no_vig_probabilities


def clamp_probability(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.001, min(float(value), 0.999))


def _leg_value(leg: dict[str, Any], key: str, default: Any = None) -> Any:
    return leg.get(key, default)


def prop_id_from_leg(leg: dict[str, Any]) -> int | None:
    for token in (_leg_value(leg, "id", ""), _leg_value(leg, "notes", "") or ""):
        for part in str(token).replace(":", "-").split("-"):
            if part.isdigit():
                return int(part)
    return None


def find_prop_for_leg(conn: Any, leg: dict[str, Any]) -> dict[str, Any] | None:
    prop_id = prop_id_from_leg(leg)
    if prop_id:
        row = execute(conn, "SELECT * FROM props WHERE id = ?", (prop_id,)).fetchone()
        if row:
            return dict(row)
    game_id_text = str(_leg_value(leg, "gameId", ""))
    if not game_id_text.isdigit():
        return None
    rows = execute(conn, "SELECT * FROM props WHERE game_id = ? ORDER BY updated_at DESC LIMIT 100", (int(game_id_text),)).fetchall()
    selection = str(_leg_value(leg, "selection", "")).lower()
    line = _leg_value(leg, "line")
    for row in rows:
        item = dict(row)
        text = f"{item.get('market') or ''} {item.get('selection') or ''}".lower()
        line_match = line is None or item.get("line") is None or abs(float(item.get("line")) - float(line)) < 0.01
        if line_match and (selection in text or text in selection):
            return item
    return None


def no_vig_market_probability(prop: dict[str, Any] | None, leg: dict[str, Any]) -> tuple[float | None, bool]:
    if not prop:
        return None, False
    over_odds = prop.get("over_odds")
    under_odds = prop.get("under_odds")
    if over_odds is None or under_odds is None:
        return american_to_implied_probability(int(_leg_value(leg, "oddsAmerican"))), False
    over_fair, under_fair, _ = no_vig_probabilities(int(over_odds), int(under_odds))
    selection = str(_leg_value(leg, "selection", "")).lower()
    if "under" in selection:
        return under_fair, True
    return over_fair, True


def calibrate_probability(probability: float | None, _market_type: str) -> float | None:
    # Hook for Brier/log-loss calibration tables when enough outcomes are stored.
    return clamp_probability(probability)


def blend_market_and_model_probability(model_probability: float | None, market_probability: float | None, confidence: float) -> float | None:
    if model_probability is None:
        return None
    if market_probability is None:
        return clamp_probability(model_probability)
    return clamp_probability(confidence * model_probability + (1 - confidence) * market_probability)


def compute_confidence_score(*, prop: dict[str, Any] | None, market_probability: float | None, no_vig_available: bool, leg_count: int, same_game_count: int, manual_unmatched: bool, high_volatility: bool) -> float:
    confidence = 1.0
    if prop is None or manual_unmatched:
        confidence -= 0.35
    if market_probability is None or not no_vig_available:
        confidence -= 0.10
    if same_game_count > 1:
        confidence -= 0.20
    if high_volatility:
        confidence -= 0.10
    if leg_count > 3:
        confidence -= 0.05 * (leg_count - 3)
    tier = str(prop.get("confidence_tier") if prop else "").lower()
    if "low" in tier:
        confidence -= 0.15
    if "medium" in tier:
        confidence -= 0.05
    return max(0, min(confidence, 1))


def confidence_tier(confidence: float, required_data_missing: bool = False) -> str:
    if required_data_missing or confidence < 0.15:
        return "INSUFFICIENT_DATA"
    if confidence >= 0.75:
        return "HIGH"
    if confidence >= 0.55:
        return "MEDIUM"
    if confidence >= 0.35:
        return "LOW"
    return "FRAGILE"


def get_joint_probability_for_slip(_legs: list[dict[str, Any]]) -> float | None:
    # Future hook for same-run simulation hit checking when simulation outputs store leg hits.
    return None
