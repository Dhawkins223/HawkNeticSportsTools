from __future__ import annotations

from ..contracts import Game, ModelPrediction
from ..math import elo_home_probability, poisson_home_win_probability, probability_to_cents, weighted_probability


class ModelBot:
    """Unvalidated example blend, never a category champion selector."""

    def predict_home_win(self, game: Game) -> ModelPrediction:
        signals = game.signals
        parts: list[tuple[float, float]] = []
        notes = [
            "model_status=unvalidated_baseline",
            "canonical_model_selection=unresolved",
            "target_scope=home_win_only",
            "input_availability_at_cutoff=unverified",
        ]

        if "home_expected_goals" in signals and "away_expected_goals" in signals:
            parts.append(
                (
                    poisson_home_win_probability(
                        signals["home_expected_goals"],
                        signals["away_expected_goals"],
                    ),
                    0.65,
                )
            )
            notes.append("used poisson expected-score model")

        if "home_rating" in signals and "away_rating" in signals:
            parts.append(
                (
                    elo_home_probability(
                        signals["home_rating"],
                        signals["away_rating"],
                        signals.get("home_field_points", 0.0),
                    ),
                    0.60,
                )
            )
            notes.append("used elo rating model")

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
