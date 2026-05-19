from __future__ import annotations

from math import prod
from typing import Any
from uuid import uuid4

from app.database import get_connection
from app.services.odds_math import (
    american_to_decimal,
    american_to_implied_probability,
    decimal_to_american,
    expected_value,
    fair_decimal_odds,
    parlay_decimal_odds,
)
from app.services.probability_engine import (
    blend_market_and_model_probability,
    calibrate_probability,
    compute_confidence_score,
    confidence_tier,
    find_prop_for_leg,
    get_joint_probability_for_slip,
    no_vig_market_probability,
)
from app.services.risk_engine import (
    detect_correlation_risk,
    detect_missing_data,
    detect_trap_leg,
    detect_volatility_risk,
    has_critical_trap_warning,
)


def _edge_pct(model_probability: float | None, implied_probability: float | None) -> float | None:
    if model_probability is None or implied_probability is None:
        return None
    return (model_probability - implied_probability) * 100


def _leg_verdict(edge_pct: float | None, ev: float | None, confidence: str, warnings: list[str]) -> str:
    if edge_pct is None or ev is None or confidence == "INSUFFICIENT_DATA":
        return "INSUFFICIENT_DATA"
    if ev <= 0 or edge_pct <= 0 or has_critical_trap_warning(warnings):
        return "PASS"
    if edge_pct >= 5 and confidence in {"HIGH", "MEDIUM"}:
        return "PLACE"
    if confidence == "FRAGILE" or edge_pct < 5:
        return "ADJUST"
    return "HEDGE"


def analyze_leg(conn: Any, leg: dict[str, Any], same_game_count: int, leg_count: int, stake: float) -> dict[str, Any]:
    decimal_odds = american_to_decimal(int(leg["oddsAmerican"]))
    implied_probability = american_to_implied_probability(int(leg["oddsAmerican"]))
    prop = find_prop_for_leg(conn, leg)
    raw_model = float(prop["model_probability"]) if prop and prop.get("model_probability") is not None else None
    market_probability, no_vig_available = no_vig_market_probability(prop, leg)
    calibrated_model = calibrate_probability(raw_model, str(leg.get("marketType") or ""))
    high_volatility = int(leg["oddsAmerican"]) >= 250
    confidence_score = compute_confidence_score(
        prop=prop,
        market_probability=market_probability,
        no_vig_available=no_vig_available,
        leg_count=leg_count,
        same_game_count=same_game_count,
        manual_unmatched=prop is None and str(leg.get("id", "")).startswith("manual"),
        high_volatility=high_volatility,
    )
    model_probability = blend_market_and_model_probability(calibrated_model, market_probability, confidence_score)
    warnings = [
        *detect_missing_data(prop, model_probability),
        *detect_correlation_risk(leg, same_game_count),
        *detect_trap_leg(leg, _edge_pct(model_probability, implied_probability)),
        *detect_volatility_risk(leg, prop),
    ]
    tier = confidence_tier(confidence_score, required_data_missing=model_probability is None)
    edge = _edge_pct(model_probability, implied_probability)
    ev = expected_value(stake, decimal_odds, model_probability)
    verdict = _leg_verdict(edge, ev, tier, warnings)
    explanation = "Not enough data to evaluate this leg." if model_probability is None else f"Model probability {model_probability:.1%} vs market implied {implied_probability:.1%}."
    return {
        "legId": leg["id"],
        "selection": leg["selection"],
        "marketType": leg["marketType"],
        "modelProbability": model_probability,
        "impliedProbability": implied_probability,
        "edgePct": edge,
        "confidenceTier": tier,
        "verdict": verdict,
        "warnings": list(dict.fromkeys(warnings)),
        "explanation": explanation,
        "_decimalOdds": decimal_odds,
        "_confidenceScore": confidence_score,
    }


def choose_recommendation(edge_pct: float | None, ev: float | None, confidence_score: float, warnings: list[str], missing_data: bool) -> tuple[str, str, str]:
    tier = confidence_tier(confidence_score, required_data_missing=missing_data)
    if missing_data or tier == "INSUFFICIENT_DATA":
        return "INSUFFICIENT_DATA", "INSUFFICIENT_DATA", "Not enough data to evaluate this slip yet."
    if ev is None or edge_pct is None or ev <= 0 or edge_pct <= 0:
        return "PASS", tier, "HawkNetic does not see enough value in this slip."
    if has_critical_trap_warning(warnings):
        return "PASS", tier, "A trap warning makes this slip too risky."
    if edge_pct >= 5 and ev > 0 and confidence_score >= 0.55 and not warnings:
        return "PLACE", tier, "HawkNetic sees a positive edge. Decision support only; this does not place bets."
    if ev > 0 and edge_pct >= 1 and confidence_score >= 0.35:
        return "ADJUST", tier, "This slip has value signals, but one or more legs should be reviewed."
    if ev > 0:
        return "HEDGE", tier, "There is some value, but volatility is high."
    return "PASS", tier, "HawkNetic recommends passing or rebuilding the slip."


def build_better_alternatives(leg_analyses: list[dict[str, Any]], leg_count: int) -> list[dict[str, str]]:
    alternatives: list[dict[str, str]] = []
    weak = [leg for leg in leg_analyses if leg["verdict"] in {"PASS", "ADJUST", "INSUFFICIENT_DATA"}]
    if weak:
        alternatives.append({"title": "Review weakest leg", "reason": f"{weak[0]['selection']} is limiting the slip: {weak[0]['explanation']}"})
    if leg_count > 3:
        alternatives.append({"title": "Try fewer legs", "reason": "Removing the weakest leg can improve the chance that the slip is worth taking to Bet365."})
    return alternatives


def analyze_slip(request: dict[str, Any]) -> dict[str, Any]:
    legs = request.get("legs") or []
    if not legs:
        raise ValueError("At least one slip leg is required.")
    for leg in legs:
        if not leg.get("gameId") or not leg.get("marketType") or not leg.get("selection") or leg.get("oddsAmerican") in {None, 0}:
            raise ValueError("Every leg requires gameId, marketType, selection, and oddsAmerican.")
        american_to_decimal(int(leg["oddsAmerican"]))

    same_game_counts: dict[str, int] = {}
    for leg in legs:
        same_game_counts[str(leg["gameId"])] = same_game_counts.get(str(leg["gameId"]), 0) + 1

    stake = float(request.get("stake") or 0)
    with get_connection() as conn:
        leg_analyses = [analyze_leg(conn, leg, same_game_counts[str(leg["gameId"])], len(legs), stake) for leg in legs]

    decimal_values = [float(analysis.pop("_decimalOdds")) for analysis in leg_analyses]
    confidence_scores = [float(analysis.pop("_confidenceScore")) for analysis in leg_analyses]
    parlay_decimal = parlay_decimal_odds(decimal_values)
    implied_probability = 1 / parlay_decimal if parlay_decimal else None
    missing_count = sum(1 for analysis in leg_analyses if analysis["modelProbability"] is None)
    missing_ratio = missing_count / len(legs)
    joint_probability = get_joint_probability_for_slip(legs)
    model_probabilities = [analysis["modelProbability"] for analysis in leg_analyses if analysis["modelProbability"] is not None]
    model_win_probability = joint_probability
    if model_win_probability is None and not missing_count:
        model_win_probability = prod(float(probability) for probability in model_probabilities)
    if missing_ratio > 0.4 or missing_count:
        model_win_probability = None

    slip_warnings: list[str] = []
    if len(legs) > 3:
        slip_warnings.append("More legs increases slip fragility.")
    if any(count > 1 for count in same_game_counts.values()) and joint_probability is None:
        slip_warnings.append("Same-game correlation could affect the true slip probability.")
    if missing_count:
        slip_warnings.append("One or more legs do not have enough data yet.")
    weakest_leg = min(
        leg_analyses,
        key=lambda analysis: analysis["edgePct"] if analysis["edgePct"] is not None else -999,
    )
    if weakest_leg["verdict"] in {"PASS", "ADJUST", "INSUFFICIENT_DATA"}:
        slip_warnings.append(f"Weakest leg: {weakest_leg['selection']}.")

    ev = expected_value(stake, parlay_decimal, model_win_probability)
    edge = _edge_pct(model_win_probability, implied_probability)
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
    recommendation, confidence, summary = choose_recommendation(
        edge,
        ev,
        avg_confidence,
        slip_warnings + [warning for analysis in leg_analyses for warning in analysis["warnings"]],
        missing_data=model_win_probability is None or missing_ratio > 0.4,
    )
    fair_decimal = fair_decimal_odds(model_win_probability)
    return {
        "ok": True,
        "slipId": str(uuid4()),
        "bookmaker": request.get("bookmaker", "bet365"),
        "stake": stake,
        "legCount": len(legs),
        "parlayAmericanOdds": decimal_to_american(parlay_decimal),
        "impliedProbability": implied_probability,
        "modelWinProbability": model_win_probability,
        "edgePct": edge,
        "expectedValue": ev,
        "fairAmericanOdds": decimal_to_american(fair_decimal),
        "recommendation": recommendation,
        "confidenceTier": confidence,
        "summary": summary,
        "warnings": list(dict.fromkeys(slip_warnings)),
        "legAnalyses": leg_analyses,
        "betterAlternatives": build_better_alternatives(leg_analyses, len(legs)),
    }
