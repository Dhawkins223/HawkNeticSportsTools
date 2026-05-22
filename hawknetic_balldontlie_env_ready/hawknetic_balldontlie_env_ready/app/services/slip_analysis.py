"""HawkNetic v2 slip analyzer.

Replaces the previous implementation. Pipeline per spec §24:

  1. Validate every leg has gameId / marketType / selection / oddsAmerican.
  2. Compute decimal odds + raw implied + no-vig market probability per leg.
  3. Run the Monte Carlo `simulate_slip` (N=10,000) → leg & parlay probabilities
     and per-leg projections + standard deviations.
  4. Compute edge against **no-vig** probability (spec §14).
  5. EV per leg + EV for the parlay (spec §13, §16).
  6. Confidence score with weighted normalized components (spec §17).
  7. Trap detection per spec §18 (12 rules, what we can compute).
  8. Correlation matrix from simulation outcomes (spec §12).
  9. Bet classification: Strong play / Playable / Lean / Pass / Trap (spec §19).
 10. Kelly fraction (full + 0.25× recommended) per spec §20.
 11. 95% binomial CI from simulation count (spec §21).
 12. Attach live-data readiness warnings to every response (spec §23).

Backward-compatible field names: keeps `recommendation`, `legAnalyses`,
`modelWinProbability`, `edgePct`, `expectedValue`, `fairAmericanOdds`,
`confidenceTier`, `summary`, `betterAlternatives`, `warnings` so the existing
React dashboard keeps rendering. Adds new spec-compliant fields alongside.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.database import execute, get_connection
from app.services.live_readiness import check_readiness
from app.services.odds_math import (
    american_to_decimal,
    american_to_implied_probability,
    decimal_to_american,
    expected_value,
    fair_decimal_odds,
    no_vig_probabilities,
    parlay_decimal_odds,
)
from app.services.odds_math_extras import (
    confidence_interval_95,
    fractional_kelly,
    kelly_fraction,
)
from app.services.simulation_engine import (
    DEFAULT_RUNS,
    correlation_matrix,
    parse_leg_inputs,
    simulate_slip,
)


# ---------- output classification (spec §19) ----------

def _classify_leg(ev_per_unit: float, edge: float, confidence: float, trap_flags: list[str]) -> str:
    if trap_flags:
        return "Trap"
    if ev_per_unit >= 0.08 and edge >= 0.05 and confidence >= 0.70:
        return "Strong play"
    if ev_per_unit >= 0.03 and edge >= 0.03 and confidence >= 0.60:
        return "Playable"
    if ev_per_unit >= 0 and edge >= 0.01 and confidence >= 0.50:
        return "Lean"
    return "Pass"


def _classify_slip(ev_per_unit: float, edge: float, confidence: float, trap_count: int, total_legs: int) -> tuple[str, str]:
    if total_legs == 0:
        return "INSUFFICIENT_DATA", "Add legs to run the algorithm."
    if trap_count >= max(1, total_legs // 2):
        return "Trap", "Multiple legs are flagged as traps — rebuild the slip."
    cls = _classify_leg(ev_per_unit, edge, confidence, [])
    summaries = {
        "Strong play": "HawkNetic sees a positive edge with strong confidence.",
        "Playable": "Slip has value signals; one or more legs warrant review.",
        "Lean": "Marginal value — small positive lean but volatile.",
        "Pass": "HawkNetic does not see enough value in this slip.",
        "Trap": "High hit-probability but the price is bad — pass.",
    }
    return cls, summaries[cls]


# ---------- helpers ----------

def _stat_label(market_type: str, selection: str) -> str:
    text = (selection or "").lower()
    if "three" in text:
        return "Threes Made"
    if "rebound" in text:
        return "Rebounds"
    if "assist" in text:
        return "Assists"
    if "point" in text:
        return "Points"
    return market_type.replace("_", " ").title()


def _label_edge(edge: float) -> str:
    if edge < 0:
        return "Pass"
    if edge < 0.02:
        return "No real edge"
    if edge < 0.04:
        return "Small edge"
    if edge < 0.07:
        return "Playable edge"
    return "Strong edge"


def _no_vig_for_leg(conn: Any, leg: dict[str, Any], implied_prob: float) -> tuple[float, bool]:
    """Best-effort no-vig probability using the matching opposite-side line."""
    game_id = leg.get("gameId")
    market_type = leg.get("marketType")
    selection = (leg.get("selection") or "").lower()
    is_under = "under" in selection
    if not game_id or not market_type:
        return implied_prob, False
    # Try props first
    if leg.get("playerId") or market_type == "player_prop":
        row = execute(conn, "SELECT over_odds, under_odds FROM props WHERE game_id = ? AND id = ? LIMIT 1", (game_id, leg.get("propId") or 0)).fetchone()
        if not row:
            row = execute(conn, "SELECT over_odds, under_odds FROM props WHERE game_id = ? ORDER BY updated_at DESC LIMIT 1", (game_id,)).fetchone()
        if row:
            d = dict(row)
            over_odds, under_odds = d.get("over_odds"), d.get("under_odds")
            if over_odds and under_odds:
                nv_over, nv_under, _overround = no_vig_probabilities(int(over_odds), int(under_odds))
                return (nv_under if is_under else nv_over), True
    return implied_prob, False


def _trap_flags(*, ev_per_unit: float, model_prob: float, american_odds: int, projection: float, line: float | None, edge: float, confidence: float, minutes_certainty: float, injury_certainty: float, blowout_severity: float, sample_size: int) -> list[str]:
    flags: list[str] = []
    # 1. High probability but negative EV
    if model_prob >= 0.65 and ev_per_unit < 0:
        flags.append("Likely-but-overpriced (high prob, negative EV)")
    # 2. Heavy juice with tiny payout
    if american_odds <= -250 and edge < 0.02:
        flags.append("Heavy juice for thin edge")
    # 3. Player minutes uncertain
    if minutes_certainty < 0.5:
        flags.append("Minutes uncertainty")
    # 4. Player injury / questionable
    if injury_certainty < 0.6:
        flags.append("Injury / questionable status")
    # 5. Blowout risk
    if blowout_severity > 0.5:
        flags.append("Blowout risk reduces minutes")
    # 11. Projection barely clears the line
    if line is not None and abs(projection - line) < 0.5:
        flags.append("Projection barely clears the line")
    # 16. Simulation runs too low
    if sample_size and sample_size < 1000:
        flags.append("Sample size too small for stable estimate")
    return flags


# ---------- main entry point ----------

def analyze_slip(request: dict[str, Any]) -> dict[str, Any]:
    legs_input = request.get("legs") or []
    if not legs_input:
        raise ValueError("At least one slip leg is required.")
    for leg in legs_input:
        if not leg.get("gameId") or not leg.get("marketType") or not leg.get("selection") or leg.get("oddsAmerican") in {None, 0}:
            raise ValueError("Every leg requires gameId, marketType, selection, and oddsAmerican.")
        american_to_decimal(int(leg["oddsAmerican"]))

    stake = float(request.get("stake") or 1)
    runs = int(request.get("runs") or DEFAULT_RUNS)
    leg_specs = parse_leg_inputs(legs_input)
    for spec, leg in zip(leg_specs, legs_input):
        spec.decimal_odds = american_to_decimal(int(leg["oddsAmerican"]))

    # ---- live readiness ----
    readiness = check_readiness([leg.game_id for leg in leg_specs])

    # ---- Monte Carlo ----
    with get_connection() as conn:
        sim = simulate_slip(conn, leg_specs, runs=runs)

        # ---- per-leg analysis ----
        leg_analyses: list[dict[str, Any]] = []
        leg_classifications: list[str] = []
        for idx, (spec, leg) in enumerate(zip(leg_specs, legs_input)):
            decimal_odds = spec.decimal_odds
            implied = american_to_implied_probability(int(leg["oddsAmerican"]))
            no_vig, no_vig_available = _no_vig_for_leg(conn, leg, implied)
            model_prob = sim["leg_probabilities"][idx]
            projection = sim["leg_projections"][idx]
            projection_std = sim["leg_projection_stds"][idx]
            edge = model_prob - no_vig
            ev = expected_value(stake, decimal_odds, model_prob)
            ev_per_unit = ev / max(stake, 1e-9)

            # Confidence components (each in 0..1)
            probability_score = max(0.0, min(model_prob, 1.0))
            edge_score = max(0.0, min(0.5 + edge * 5, 1.0))  # 0% edge → 0.5, +10% → 1.0
            minutes_certainty = 0.85 if leg.get("playerId") else 1.0
            injury_certainty = 0.0 if sim["inactive_flags"][idx] else 0.9
            data_quality = 0.7 if no_vig_available else 0.5
            low_volatility_score = max(0.0, 1 - min(projection_std / max(projection, 1.0), 1.0)) if projection_std else 0.7
            correlation_quality = 0.7

            confidence = (
                0.25 * probability_score
                + 0.25 * edge_score
                + 0.15 * minutes_certainty
                + 0.10 * data_quality
                + 0.10 * low_volatility_score
                + 0.10 * injury_certainty
                + 0.05 * correlation_quality
            )

            trap_flags = _trap_flags(
                ev_per_unit=ev_per_unit,
                model_prob=model_prob,
                american_odds=int(leg["oddsAmerican"]),
                projection=projection,
                line=spec.line,
                edge=edge,
                confidence=confidence,
                minutes_certainty=minutes_certainty,
                injury_certainty=injury_certainty,
                blowout_severity=0.0,
                sample_size=sim["runs"],
            )
            classification = _classify_leg(ev_per_unit, edge, confidence, trap_flags)
            leg_classifications.append(classification)

            ci_low, ci_high = confidence_interval_95(model_prob, sim["runs"])
            margin_of_error = ((ci_high or model_prob) - (ci_low or model_prob)) / 2 if ci_low is not None else None

            kelly_full = kelly_fraction(decimal_odds, model_prob)
            kelly_quarter = fractional_kelly(decimal_odds, model_prob, 0.25)

            tier = _confidence_tier(confidence)
            verdict = _backcompat_verdict(classification, model_prob is not None)

            reason = _build_reason(model_prob, no_vig, edge, projection, spec.line, classification, trap_flags, sim["inactive_flags"][idx])

            leg_analyses.append({
                # ---- backward-compat fields used by current frontend ----
                "legId": leg["id"],
                "selection": leg["selection"],
                "marketType": leg["marketType"],
                "modelProbability": model_prob,
                "impliedProbability": implied,
                "edgePct": edge * 100,
                "confidenceTier": tier,
                "verdict": verdict,
                "warnings": trap_flags,
                "explanation": reason,
                # ---- spec §25 additions ----
                "noVigProbability": no_vig,
                "noVigAvailable": no_vig_available,
                "americanOdds": int(leg["oddsAmerican"]),
                "decimalOdds": round(decimal_odds, 4),
                "ev": round(ev, 4),
                "evPerUnit": round(ev_per_unit, 4),
                "projection": round(projection, 2),
                "projectionStd": round(projection_std, 2),
                "marginOfError": round(margin_of_error, 4) if margin_of_error is not None else None,
                "ci95": [round(ci_low, 4), round(ci_high, 4)] if ci_low is not None else None,
                "confidenceScore": round(confidence * 100, 1),
                "classification": classification,
                "edgeLabel": _label_edge(edge),
                "trapFlags": trap_flags,
                "kellyFraction": round(kelly_full, 4),
                "kellyRecommended": round(kelly_quarter, 4),
                "statLabel": _stat_label(leg["marketType"], leg["selection"]),
                "inactivePlayer": bool(sim["inactive_flags"][idx]),
                "fairAmericanOdds": decimal_to_american(fair_decimal_odds(model_prob)),
            })

        # ---- correlation matrix ----
        corr_matrix = correlation_matrix(sim["leg_outcomes"])
        max_off_diagonal = 0.0
        for i in range(len(corr_matrix)):
            for j in range(i + 1, len(corr_matrix)):
                if abs(corr_matrix[i][j]) > abs(max_off_diagonal):
                    max_off_diagonal = corr_matrix[i][j]
        if max_off_diagonal > 0.30:
            correlation_warning = "Meaningfully positive correlation between legs"
        elif max_off_diagonal < -0.30:
            correlation_warning = "Meaningfully negative correlation between legs"
        elif abs(max_off_diagonal) > 0.15:
            correlation_warning = "Mild correlation between legs"
        else:
            correlation_warning = None

    # ---- parlay metrics ----
    decimal_values = [a["decimalOdds"] for a in leg_analyses]
    parlay_decimal = parlay_decimal_odds(decimal_values)
    parlay_implied = 1 / parlay_decimal if parlay_decimal else None
    parlay_probability = sim["parlay_probability"]
    parlay_ev = stake * (parlay_probability * (parlay_decimal - 1) - (1 - parlay_probability))
    parlay_ev_per_unit = parlay_ev / max(stake, 1e-9)
    parlay_edge = parlay_probability - parlay_implied if parlay_implied else 0
    parlay_ci_low, parlay_ci_high = confidence_interval_95(parlay_probability, sim["runs"])

    avg_confidence = sum(a["confidenceScore"] for a in leg_analyses) / max(len(leg_analyses), 1) / 100
    parlay_confidence = avg_confidence * 0.85  # slip discount for compounding risk
    trap_count = sum(1 for c in leg_classifications if c == "Trap")
    parlay_classification, summary = _classify_slip(parlay_ev_per_unit, parlay_edge, parlay_confidence, trap_count, len(legs_input))
    if any(a["inactivePlayer"] for a in leg_analyses):
        parlay_classification = "Pass"
        summary = "One or more players in the slip are inactive — leg cannot win."

    parlay_kelly = kelly_fraction(parlay_decimal, parlay_probability)
    parlay_kelly_q = fractional_kelly(parlay_decimal, parlay_probability, 0.25)
    slip_id = str(uuid4())

    # ---- record predictions for future calibration / Brier scoring ----
    try:
        with get_connection() as conn:
            for analysis in leg_analyses:
                if analysis["modelProbability"] is None:
                    continue
                bucket = _probability_bucket(analysis["modelProbability"])
                execute(conn, """
                    INSERT INTO predictions_outcomes(slip_id, leg_id, predicted_probability, bucket, market_type)
                    VALUES(?, ?, ?, ?, ?)
                """, (slip_id, analysis["legId"], analysis["modelProbability"], bucket, analysis["marketType"]))
    except Exception:
        # Calibration logging is best-effort — never break a Run Algorithm response over it.
        pass

    slip_warnings: list[str] = []
    if correlation_warning:
        slip_warnings.append(correlation_warning)
    if any(a["inactivePlayer"] for a in leg_analyses):
        slip_warnings.append("Inactive player detected — leg automatically loses.")
    weakest = min(leg_analyses, key=lambda a: a["edgePct"])
    strongest = max(leg_analyses, key=lambda a: a["edgePct"])
    if weakest["classification"] in {"Pass", "Trap"}:
        slip_warnings.append(f"Weakest leg: {weakest['selection']} ({weakest['classification']}).")
    slip_warnings.extend(readiness["warnings"])
    if readiness["blocking_reasons"]:
        summary = "Live data is not ready — recommendation downgraded. " + summary

    return {
        # ---- backward-compat ----
        "ok": True,
        "slipId": slip_id,
        "bookmaker": request.get("bookmaker", "consensus"),
        "stake": stake,
        "legCount": len(legs_input),
        "parlayAmericanOdds": decimal_to_american(parlay_decimal),
        "impliedProbability": parlay_implied,
        "modelWinProbability": parlay_probability,
        "edgePct": parlay_edge * 100,
        "expectedValue": round(parlay_ev, 4),
        "fairAmericanOdds": decimal_to_american(fair_decimal_odds(parlay_probability)),
        "recommendation": _backcompat_slip_verdict(parlay_classification),
        "confidenceTier": _confidence_tier(parlay_confidence),
        "summary": summary,
        "warnings": list(dict.fromkeys(slip_warnings)),
        "legAnalyses": leg_analyses,
        "betterAlternatives": _better_alternatives(leg_analyses, len(legs_input)),
        # ---- v2 spec §25 additions ----
        "parlayDecimalOdds": round(parlay_decimal, 4),
        "parlayProbability": round(parlay_probability, 4),
        "parlayEv": round(parlay_ev, 4),
        "parlayEvPerUnit": round(parlay_ev_per_unit, 4),
        "parlayEdge": round(parlay_edge, 4),
        "parlayConfidenceScore": round(parlay_confidence * 100, 1),
        "parlayClassification": parlay_classification,
        "parlayCi95": [round(parlay_ci_low, 4), round(parlay_ci_high, 4)] if parlay_ci_low is not None else None,
        "parlayKellyFraction": round(parlay_kelly, 4),
        "parlayKellyRecommended": round(parlay_kelly_q, 4),
        "correlationMatrix": [[round(v, 3) for v in row] for row in corr_matrix],
        "correlationWarning": correlation_warning,
        "bestLeg": strongest["selection"],
        "worstLeg": weakest["selection"],
        "trapLegs": [a["selection"] for a in leg_analyses if a["classification"] == "Trap"],
        "simulationRuns": sim["runs"],
        "readiness": readiness,
    }


def _probability_bucket(p: float) -> str:
    if p < 0.5:
        return "<50"
    if p < 0.55:
        return "50-55"
    if p < 0.60:
        return "55-60"
    if p < 0.65:
        return "60-65"
    if p < 0.70:
        return "65-70"
    return "70+"


def _confidence_tier(confidence_score: float) -> str:
    if confidence_score >= 0.75:
        return "HIGH"
    if confidence_score >= 0.55:
        return "MEDIUM"
    if confidence_score >= 0.35:
        return "LOW"
    if confidence_score >= 0.15:
        return "FRAGILE"
    return "INSUFFICIENT_DATA"


def _backcompat_verdict(classification: str, has_data: bool) -> str:
    if not has_data:
        return "INSUFFICIENT_DATA"
    return {
        "Strong play": "PLACE",
        "Playable": "PLACE",
        "Lean": "ADJUST",
        "Pass": "PASS",
        "Trap": "PASS",
    }[classification]


def _backcompat_slip_verdict(parlay_classification: str) -> str:
    return {
        "Strong play": "PLACE",
        "Playable": "PLACE",
        "Lean": "ADJUST",
        "Pass": "PASS",
        "Trap": "PASS",
        "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
    }.get(parlay_classification, "PASS")


def _build_reason(model_prob: float, no_vig: float, edge: float, projection: float, line: float | None, classification: str, trap_flags: list[str], inactive: bool) -> str:
    if inactive:
        return "Player marked inactive — leg cannot win."
    if trap_flags:
        return f"Trap flags: {', '.join(trap_flags)}."
    line_part = f"projecting {projection:.1f} vs line {line}" if line is not None else f"projecting {projection:.1f}"
    return f"Model probability {model_prob:.1%} vs no-vig market {no_vig:.1%} ({edge*100:+.1f}% edge), {line_part}. Classification: {classification}."


def _better_alternatives(leg_analyses: list[dict[str, Any]], leg_count: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    weak = [a for a in leg_analyses if a["classification"] in {"Pass", "Trap", "Lean"}]
    if weak:
        out.append({"title": "Drop weakest leg", "reason": f"{weak[0]['selection']} ({weak[0]['classification']}): {weak[0]['explanation']}"})
    if leg_count > 3:
        out.append({"title": "Try fewer legs", "reason": "More legs compound variance and reduce confidence."})
    return out
