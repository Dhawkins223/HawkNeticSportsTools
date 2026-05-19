from __future__ import annotations

from typing import Any


def detect_trap_leg(leg: dict[str, Any], edge_pct: float | None) -> list[str]:
    warnings: list[str] = []
    odds = int(leg.get("oddsAmerican"))
    if odds < 0 and abs(odds) >= 200 and (edge_pct is None or edge_pct < 2):
        warnings.append("Extreme juice trap warning.")
    if odds >= 250:
        warnings.append("High volatility long-odds leg.")
    return warnings


def detect_missing_data(prop: dict[str, Any] | None, model_probability: float | None) -> list[str]:
    warnings: list[str] = []
    if model_probability is None:
        warnings.append("Not enough data to evaluate this leg.")
    if prop is None:
        warnings.append("This market is temporarily unavailable.")
    return warnings


def detect_correlation_risk(leg: dict[str, Any], same_game_count: int) -> list[str]:
    if same_game_count > 1:
        return ["Same-game dependency risk detected."]
    if leg.get("marketType") == "same_game_parlay":
        return ["Same-game parlay needs stronger correlation coverage."]
    return []


def detect_volatility_risk(leg: dict[str, Any], prop: dict[str, Any] | None) -> list[str]:
    warnings: list[str] = []
    if leg.get("marketType") in {"player_prop", "team_prop"}:
        warnings.append("Player status, minutes, fatigue, and travel can affect this leg.")
    if prop and str(prop.get("confidence_tier") or "").lower() == "low":
        warnings.append("Low confidence market.")
    return warnings


def has_critical_trap_warning(warnings: list[str]) -> bool:
    text = " ".join(warnings).lower()
    return "extreme juice trap" in text
