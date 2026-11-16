from __future__ import annotations

import math

from ..contracts import Game, ModelPrediction
from ..math import elo_home_probability, poisson_home_win_probability, probability_to_cents, weighted_probability


class ModelBot:
    """Unvalidated example blend, never a category champion selector."""

    def predict_home_win(self, game: Game) -> ModelPrediction:
        signals = game.signals
        if not isinstance(signals, dict):
            raise ValueError(
                f"Invalid model signals for game {game.game_id}: expected an object; "
                "no probability was generated."
            )
        for name in (
            "home_expected_goals", "away_expected_goals", "home_rating", "away_rating",
            "home_field_points", "market_prior_home_prob",
        ):
            if name not in signals:
                continue
            value = signals[name]
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            if valid:
                try:
                    valid = math.isfinite(value)
                except OverflowError:
                    valid = False
            requirement = "a finite number supported by baseline arithmetic"
            if valid and name in {"home_expected_goals", "away_expected_goals"}:
                valid = value >= 0
                requirement = "a nonnegative expected-goal value"
            elif valid and name == "market_prior_home_prob":
                valid = 0 <= value <= 1
                requirement = "a probability between 0 and 1 inclusive"
            if not valid:
                raise ValueError(
                    f"Invalid model signal {name} for game {game.game_id}: expected {requirement}; "
                    "no probability was generated."
                )
        parts: list[tuple[float, float]] = []
        notes = [
            "model_status=unvalidated_baseline",
            "canonical_model_selection=unresolved",
            "target_scope=home_win_only",
            "input_availability_at_cutoff=unverified",
        ]

        if "home_expected_goals" in signals and "away_expected_goals" in signals:
            try:
                probability = poisson_home_win_probability(
                    signals["home_expected_goals"],
                    signals["away_expected_goals"],
                )
            except OverflowError as exc:
                raise ValueError(
                    f"Poisson expected-goal arithmetic overflow for game {game.game_id}; "
                    "no probability was generated."
                ) from exc
            parts.append((probability, 0.65))
            notes.append("used poisson expected-score model")
        elif "home_expected_goals" in signals or "away_expected_goals" in signals:
            notes.append("skipped poisson: incomplete expected-score pair")

        if "home_rating" in signals and "away_rating" in signals:
            try:
                adjusted_diff = (
                    signals["home_rating"] + signals.get("home_field_points", 0.0)
                ) - signals["away_rating"]
                if not math.isfinite(adjusted_diff):
                    raise ValueError(
                        f"Elo inputs produce a nonfinite adjusted rating difference for game {game.game_id}; "
                        "no probability was generated."
                    )
                probability = elo_home_probability(
                    signals["home_rating"],
                    signals["away_rating"],
                    signals.get("home_field_points", 0.0),
                )
            except OverflowError as exc:
                raise ValueError(
                    f"Elo rating arithmetic overflow for game {game.game_id}; "
                    "no probability was generated."
                ) from exc
            parts.append((probability, 0.60))
            notes.append("used elo rating model")
        elif any(name in signals for name in ("home_rating", "away_rating", "home_field_points")):
            notes.append("skipped elo: incomplete rating pair")

        if "market_prior_home_prob" in signals:
            parts.append((signals["market_prior_home_prob"], 0.35))
            notes.append("information_mode=market_conditioned")
        else:
            notes.append("information_mode=local_signals_unverified")

        if not parts:
            raise ValueError(
                f"No supported model signals for game {game.game_id}; no probability was generated."
            )

        probability = weighted_probability(parts)
        return ModelPrediction(
            game_id=game.game_id,
            sport=game.sport,
            target="home_win",
            probability=probability,
            fair_price_cents=probability_to_cents(probability),
            model_name="unvalidated_weighted_sport_baseline",
            notes=notes,
        )
