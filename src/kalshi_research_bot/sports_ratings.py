"""Team ratings built from the games this platform has already settled.

`math/elo.py` has always been able to turn two ratings into a probability, but
nothing produced ratings: `ModelBot` reads them out of a `Game.signals` dict that
only the sample-JSON demo ever fills. The consequence is that every sports number
the platform publishes is a bookmaker price wearing different units. The board
says so honestly -- `baseline_only`, `track_only` -- but a baseline is not a
model, and without one there is nothing to compare a market price against.

This module closes that gap using data already in PostgreSQL. Settled rows in
`app.sports_prediction_logs` carry `final_score_json`, so the platform's own
collection history reconstructs the game results an Elo rating needs.

Three properties matter more than the rating arithmetic:

1. **No leakage.** Games are processed in start-time order and every prediction
   is made from ratings that contain only games that had already finished. A
   game never contributes to its own forecast. This is backlog E-05 enforced by
   construction rather than audited afterwards.

2. **The market is a baseline, not an opponent to ignore.** Elo is graded against
   the home base rate *and* against the de-vigged closing price, because beating
   a coin flip is not evidence and a model that loses to the closing line has
   found nothing. This is backlog E-21 and E-24.

3. **A verdict, including a negative one.** The comparison reports a paired
   confidence interval and how many games the effect would need. An interval
   containing zero is reported as inconclusive and can be recorded in the
   research registry as such. Nothing here promotes a model: promotion stays
   behind `MODEL_PROMOTION_ENABLED`, and the report states `track_only`.

Ratings are `Decimal` end to end, matching the repository rule that exact
probability values keep their scale until a serialization boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from math import sqrt
from typing import Any, Mapping, Sequence

from .business_store import ensure_database_ready
from .database import DatabaseSettings, connection_pool
from .evaluation.calibration import select_calibrator
from .evaluation.power import (
    normal_quantile,
    required_sample_for_score_improvement,
    two_sided_p_value,
)
from .math.devig import DEFAULT_DEVIG_METHOD, remove_margin
from .sports_board import american_implied_probability


MODEL_NAME = "elo_walk_forward_v1"
PROBABILITY_SCALE = Decimal("0.000001")
METRIC_SCALE = Decimal("0.00000001")
DECIMAL_PRECISION = 28

DEFAULT_K_FACTOR = Decimal("20")
DEFAULT_HOME_ADVANTAGE = Decimal("55")
DEFAULT_RATING_SCALE = Decimal("400")
DEFAULT_BASE_RATING = Decimal("1500")
DEFAULT_MIN_TEAM_GAMES = 5
DEFAULT_MIN_EVALUATED_GAMES = 30

HYPOTHESIS = "Walk-forward Elo beats the home base rate out-of-sample on collected settled games"


@dataclass(frozen=True)
class EloConfig:
    """The rating parameters, stated so a result can be reproduced.

    ``min_team_games`` is not a tuning knob but a validity gate: a team's first
    predictions come from the shared starting rating and measure nothing, so they
    update the ratings without entering the metrics.
    """

    k_factor: Decimal = DEFAULT_K_FACTOR
    home_advantage: Decimal = DEFAULT_HOME_ADVANTAGE
    rating_scale: Decimal = DEFAULT_RATING_SCALE
    base_rating: Decimal = DEFAULT_BASE_RATING
    min_team_games: int = DEFAULT_MIN_TEAM_GAMES

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": MODEL_NAME,
            "k_factor": format(self.k_factor, "f"),
            "home_advantage_rating_points": format(self.home_advantage, "f"),
            "rating_scale": format(self.rating_scale, "f"),
            "base_rating": format(self.base_rating, "f"),
            "min_team_games": self.min_team_games,
        }


@dataclass(frozen=True)
class GameResult:
    """One finished game, reconstructed from settled collection rows."""

    event_id: str
    sport: str
    league: str
    start_time: datetime
    home_team: str
    away_team: str
    home_score: Decimal
    away_score: Decimal

    @property
    def home_win(self) -> int | None:
        """1, 0, or None for a tie. A tie has no binary outcome to score."""
        if self.home_score > self.away_score:
            return 1
        if self.home_score < self.away_score:
            return 0
        return None

    @property
    def home_rating_score(self) -> Decimal:
        """The Elo update target: 1 for a home win, 0 for a loss, 0.5 for a tie."""
        if self.home_score > self.away_score:
            return Decimal(1)
        if self.home_score < self.away_score:
            return Decimal(0)
        return Decimal("0.5")


@dataclass(frozen=True)
class WalkForwardRow:
    """One out-of-sample forecast and the baselines it is graded against."""

    event_id: str
    league: str
    start_time: datetime
    home_team: str
    away_team: str
    home_win: int
    elo_probability: Decimal
    base_rate_probability: Decimal
    market_probability: Decimal | None
    home_rating_before: Decimal
    away_rating_before: Decimal

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "league": self.league,
            "start_time": self.start_time.astimezone(timezone.utc).isoformat(),
            "home_team": self.home_team,
            "away_team": self.away_team,
            "home_win": self.home_win,
            "elo_probability": _probability_text(self.elo_probability),
            "base_rate_probability": _probability_text(self.base_rate_probability),
            "market_probability": None if self.market_probability is None else _probability_text(self.market_probability),
            "home_rating_before": format(self.home_rating_before.quantize(Decimal("0.01")), "f"),
            "away_rating_before": format(self.away_rating_before.quantize(Decimal("0.01")), "f"),
        }


def _probability_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(PROBABILITY_SCALE), "f")


def _metric_text(value: Decimal | float | None) -> str | None:
    if value is None:
        return None
    number = value if isinstance(value, Decimal) else Decimal(repr(value))
    return format(number.quantize(METRIC_SCALE), "f")


def elo_win_probability(
    home_rating: Decimal,
    away_rating: Decimal,
    *,
    home_advantage: Decimal = DEFAULT_HOME_ADVANTAGE,
    rating_scale: Decimal = DEFAULT_RATING_SCALE,
) -> Decimal:
    """Exact logistic Elo probability, computed at a fixed decimal precision."""
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        difference = (home_rating + home_advantage) - away_rating
        return Decimal(1) / (Decimal(1) + Decimal(10) ** (-difference / rating_scale))


# --------------------------------------------------------------------------
# Reading finished games back out of the collection history
# --------------------------------------------------------------------------


def _final_scores(connection: Any, *, league: str | None, since: datetime | None) -> list[Mapping[str, Any]]:
    """Every distinct final score the settled rows of an event report.

    Grouping rather than picking one row per event is deliberate: an event whose
    settled rows disagree about the score has a settlement problem, and silently
    taking the first row would hide it. That disagreement is backlog E-10, and it
    is cheaper to detect here than to discover in a metric.
    """
    return connection.execute(
        """
        SELECT event_id,
               MIN(sport) AS sport,
               MIN(league) AS league,
               MIN(game_start_time) AS start_time,
               MIN(home_team) AS home_team,
               MIN(away_team) AS away_team,
               final_score_json ->> 'home_score' AS home_score,
               final_score_json ->> 'away_score' AS away_score,
               COUNT(*) AS row_count
        FROM app.sports_prediction_logs
        WHERE validation_status = 'valid'
          AND settlement_state IN ('settled', 'push')
          AND final_score_json IS NOT NULL
          AND final_score_json ->> 'home_score' IS NOT NULL
          AND final_score_json ->> 'away_score' IS NOT NULL
          AND (%s::text IS NULL OR league = %s)
          AND (%s::timestamptz IS NULL OR game_start_time >= %s)
        GROUP BY event_id, final_score_json ->> 'home_score', final_score_json ->> 'away_score'
        ORDER BY event_id
        """,
        (league, league, since, since),
    ).fetchall()


def load_settled_games(
    *,
    settings: DatabaseSettings | None = None,
    league: str | None = None,
    since: datetime | None = None,
) -> tuple[list[GameResult], dict[str, int]]:
    """Reconstruct finished games from settled rows, refusing ambiguous ones.

    Returns the games in start-time order together with a count of what was
    excluded and why. An event whose settled rows report two different final
    scores is dropped, not guessed at.
    """
    configured = ensure_database_ready(settings)
    with connection_pool(configured).connection() as connection:
        rows = _final_scores(connection, league=league, since=since)

    by_event: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_event.setdefault(str(row["event_id"]), []).append(row)

    excluded: dict[str, int] = {}
    games: list[GameResult] = []
    for event_id, scores in by_event.items():
        if len(scores) > 1:
            excluded["conflicting_final_scores"] = excluded.get("conflicting_final_scores", 0) + 1
            continue
        row = scores[0]
        try:
            home_score = Decimal(str(row["home_score"]))
            away_score = Decimal(str(row["away_score"]))
        except (ArithmeticError, ValueError):
            excluded["unparsable_final_score"] = excluded.get("unparsable_final_score", 0) + 1
            continue
        start_time = row["start_time"]
        if start_time is None:
            excluded["missing_start_time"] = excluded.get("missing_start_time", 0) + 1
            continue
        games.append(
            GameResult(
                event_id=event_id,
                sport=str(row["sport"]),
                league=str(row["league"]),
                start_time=start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc),
                home_team=str(row["home_team"]),
                away_team=str(row["away_team"]),
                home_score=home_score,
                away_score=away_score,
            )
        )

    games.sort(key=lambda game: (game.start_time, game.event_id))
    return games, excluded


# --------------------------------------------------------------------------
# The market baseline
# --------------------------------------------------------------------------


def _closing_moneylines(connection: Any, *, league: str | None, since: datetime | None) -> list[Mapping[str, Any]]:
    return connection.execute(
        """
        SELECT DISTINCT ON (event_id, bookmaker, selection)
               event_id, bookmaker, selection, home_team, closing_line
        FROM app.sports_prediction_logs
        WHERE validation_status = 'valid'
          AND market_type = 'moneyline'
          AND closing_line IS NOT NULL
          AND (%s::text IS NULL OR league = %s)
          AND (%s::timestamptz IS NULL OR game_start_time >= %s)
        ORDER BY event_id, bookmaker, selection, odds_timestamp DESC, id DESC
        """,
        (league, league, since, since),
    ).fetchall()


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def market_home_probabilities(
    *,
    settings: DatabaseSettings | None = None,
    league: str | None = None,
    since: datetime | None = None,
) -> dict[str, Decimal]:
    """The de-vigged consensus closing probability that the home team wins.

    Each book's own two-sided close is de-vigged on its own, and the consensus is
    the median across books. Taking the median of already-fair probabilities,
    rather than de-vigging an average price, keeps one book's margin from leaking
    into the consensus, and the median keeps a single stale book from moving it.
    """
    configured = ensure_database_ready(settings)
    with connection_pool(configured).connection() as connection:
        rows = _closing_moneylines(connection, league=league, since=since)

    by_event_book: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["event_id"]), str(row["bookmaker"]))
        entry = by_event_book.setdefault(key, {"home_team": str(row["home_team"]), "prices": {}})
        entry["prices"][str(row["selection"])] = Decimal(str(row["closing_line"]))

    per_event: dict[str, list[Decimal]] = {}
    for (event_id, _bookmaker), entry in by_event_book.items():
        prices = entry["prices"]
        home_team = entry["home_team"]
        home_price = prices.get(home_team)
        away_prices = [price for selection, price in prices.items() if selection != home_team]
        if home_price is None or len(away_prices) != 1:
            continue
        home_implied = american_implied_probability(home_price)
        away_implied = american_implied_probability(away_prices[0])
        if home_implied is None or away_implied is None:
            continue
        try:
            devigged = remove_margin([home_implied, away_implied], method=DEFAULT_DEVIG_METHOD)
        except (ValueError, ArithmeticError):
            continue
        if not devigged.converged:
            continue
        per_event.setdefault(event_id, []).append(devigged.probabilities[0])

    return {event_id: _median(values) for event_id, values in per_event.items() if values}


# --------------------------------------------------------------------------
# Walk-forward evaluation
# --------------------------------------------------------------------------


@dataclass
class _RatingState:
    config: EloConfig
    ratings: dict[str, Decimal] = field(default_factory=dict)
    games_played: dict[str, int] = field(default_factory=dict)
    home_wins: int = 0
    decided_games: int = 0

    def rating(self, team: str) -> Decimal:
        return self.ratings.get(team, self.config.base_rating)

    def base_rate(self) -> Decimal:
        """Home-win rate over games already finished, with a uniform prior.

        The prior keeps the first prediction from being 0 or 1 on a single game,
        which log loss would score as infinite certainty.
        """
        return (Decimal(self.home_wins) + Decimal(1)) / (Decimal(self.decided_games) + Decimal(2))

    def observe(self, game: GameResult) -> None:
        home = game.home_team
        away = game.away_team
        expected = elo_win_probability(
            self.rating(home),
            self.rating(away),
            home_advantage=self.config.home_advantage,
            rating_scale=self.config.rating_scale,
        )
        adjustment = self.config.k_factor * (game.home_rating_score - expected)
        self.ratings[home] = self.rating(home) + adjustment
        self.ratings[away] = self.rating(away) - adjustment
        self.games_played[home] = self.games_played.get(home, 0) + 1
        self.games_played[away] = self.games_played.get(away, 0) + 1
        if game.home_win is not None:
            self.decided_games += 1
            self.home_wins += game.home_win


def walk_forward(
    games: Sequence[GameResult],
    *,
    config: EloConfig | None = None,
    market_probabilities: Mapping[str, Decimal] | None = None,
) -> tuple[list[WalkForwardRow], dict[str, int]]:
    """Forecast every game from the games that finished before it.

    The order is strict: predict, then update. A game therefore cannot inform its
    own forecast, and neither can any game that had not finished when it started.
    """
    settings = config or EloConfig()
    state = _RatingState(config=settings)
    market = dict(market_probabilities or {})
    rows: list[WalkForwardRow] = []
    skipped: dict[str, int] = {}

    for game in sorted(games, key=lambda entry: (entry.start_time, entry.event_id)):
        home_played = state.games_played.get(game.home_team, 0)
        away_played = state.games_played.get(game.away_team, 0)
        outcome = game.home_win
        if outcome is None:
            skipped["tie_has_no_binary_outcome"] = skipped.get("tie_has_no_binary_outcome", 0) + 1
        elif min(home_played, away_played) < settings.min_team_games:
            skipped["team_below_minimum_games"] = skipped.get("team_below_minimum_games", 0) + 1
        else:
            rows.append(
                WalkForwardRow(
                    event_id=game.event_id,
                    league=game.league,
                    start_time=game.start_time,
                    home_team=game.home_team,
                    away_team=game.away_team,
                    home_win=outcome,
                    elo_probability=elo_win_probability(
                        state.rating(game.home_team),
                        state.rating(game.away_team),
                        home_advantage=settings.home_advantage,
                        rating_scale=settings.rating_scale,
                    ),
                    base_rate_probability=state.base_rate(),
                    market_probability=market.get(game.event_id),
                    home_rating_before=state.rating(game.home_team),
                    away_rating_before=state.rating(game.away_team),
                )
            )
        state.observe(game)

    return rows, skipped


# --------------------------------------------------------------------------
# Scoring and paired comparison
# --------------------------------------------------------------------------


def brier_scores(probabilities: Sequence[Decimal], outcomes: Sequence[int]) -> list[Decimal]:
    return [(probability - Decimal(outcome)) ** 2 for probability, outcome in zip(probabilities, outcomes, strict=True)]


def _score_summary(probabilities: Sequence[Decimal], outcomes: Sequence[int]) -> dict[str, Any]:
    if not probabilities:
        return {"sample_size": 0, "brier_score": None, "log_loss": None, "accuracy": None}
    scores = brier_scores(probabilities, outcomes)
    brier = sum(scores, Decimal(0)) / Decimal(len(scores))
    correct = sum(
        1
        for probability, outcome in zip(probabilities, outcomes, strict=True)
        if (probability >= Decimal("0.5")) == bool(outcome)
    )
    from .evaluation.calibration import log_loss

    return {
        "sample_size": len(scores),
        "brier_score": _metric_text(brier),
        "log_loss": _metric_text(log_loss(probabilities, list(outcomes))),
        "accuracy": _metric_text(Decimal(correct) / Decimal(len(scores))),
    }


def paired_comparison(
    *,
    model_probabilities: Sequence[Decimal],
    baseline_probabilities: Sequence[Decimal],
    outcomes: Sequence[int],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Paired difference in Brier score, positive when the model is better.

    The pairing is what makes the comparison informative: both forecasts see the
    same games, so the shared difficulty of those games cancels instead of
    swamping the effect.
    """
    model_scores = brier_scores(model_probabilities, outcomes)
    baseline_scores = brier_scores(baseline_probabilities, outcomes)
    exact_differences = [
        baseline - model for baseline, model in zip(baseline_scores, model_scores, strict=True)
    ]
    differences = [float(value) for value in exact_differences]
    sample_size = len(differences)
    if sample_size < 2:
        return {
            "sample_size": sample_size,
            "mean_difference": None,
            "confidence_interval": None,
            "p_value": None,
            "verdict": "insufficient_sample",
            "metric": "paired_brier_improvement",
        }

    # Whether every game separated the two forecasts by the same amount is an
    # exact question, and the Decimal scores answer it exactly. Asking it in
    # floating point instead made the verdict depend on rounding noise: eighty
    # identical differences of 0.24 sum to 0.2399999999999999, which leaves a
    # 1e-16 residue in every deviation, so the zero-variance guard below never
    # fired and a degenerate sample was reported as `model_better` behind a
    # standard error of 1e-17. Whether that residue appears at all varies by
    # interpreter build, so the same data was `model_better` on one Python and
    # `degenerate_variance` on another.
    #
    # A sample whose differences are all identical carries no information about
    # the spread of that difference, so no confidence interval can be honest
    # about it, however large the mean is.
    if len(set(exact_differences)) == 1:
        common = exact_differences[0]
        return {
            "sample_size": sample_size,
            "mean_difference": float(common),
            "confidence_interval": None,
            "p_value": None,
            "verdict": "identical_forecasts" if common == 0 else "degenerate_variance",
            "metric": "paired_brier_improvement",
        }

    mean = sum(differences) / sample_size
    variance = sum((value - mean) ** 2 for value in differences) / (sample_size - 1)
    deviation = sqrt(variance)
    standard_error = deviation / sqrt(sample_size)
    if standard_error == 0.0:
        verdict = "identical_forecasts" if mean == 0.0 else "degenerate_variance"
        return {
            "sample_size": sample_size,
            "mean_difference": mean,
            "confidence_interval": None,
            "p_value": None,
            "verdict": verdict,
            "metric": "paired_brier_improvement",
        }

    critical = normal_quantile(1.0 - alpha / 2.0)
    lower = mean - critical * standard_error
    upper = mean + critical * standard_error
    p_value = two_sided_p_value(mean / standard_error)
    if lower > 0:
        verdict = "model_better"
    elif upper < 0:
        verdict = "baseline_better"
    else:
        verdict = "inconclusive"

    required: dict[str, Any] | None = None
    if verdict == "inconclusive" and mean > 0 and deviation > 0:
        required = required_sample_for_score_improvement(
            mean_difference=mean, difference_std=deviation
        ).as_dict()

    return {
        "sample_size": sample_size,
        "mean_difference": mean,
        "difference_std": deviation,
        "confidence_interval": [lower, upper],
        "p_value": p_value,
        "alpha": alpha,
        "verdict": verdict,
        "metric": "paired_brier_improvement",
        "required_sample_for_this_effect": required,
    }


def build_sports_ratings_report(
    *,
    settings: DatabaseSettings | None = None,
    league: str | None = None,
    since: datetime | None = None,
    config: EloConfig | None = None,
    min_evaluated_games: int = DEFAULT_MIN_EVALUATED_GAMES,
) -> dict[str, Any]:
    """Rate teams from settled games and grade the result against its baselines."""
    elo_config = config or EloConfig()
    games, excluded = load_settled_games(settings=settings, league=league, since=since)
    market = market_home_probabilities(settings=settings, league=league, since=since)
    rows, skipped = walk_forward(games, config=elo_config, market_probabilities=market)

    outcomes = [row.home_win for row in rows]
    elo_probabilities = [row.elo_probability for row in rows]
    base_rate_probabilities = [row.base_rate_probability for row in rows]
    market_rows = [row for row in rows if row.market_probability is not None]

    comparisons = [
        {
            "model": "elo",
            "baseline": "home_base_rate",
            **paired_comparison(
                model_probabilities=elo_probabilities,
                baseline_probabilities=base_rate_probabilities,
                outcomes=outcomes,
            ),
        }
    ]
    if market_rows:
        comparisons.append(
            {
                "model": "elo",
                "baseline": "devigged_closing_consensus",
                **paired_comparison(
                    model_probabilities=[row.elo_probability for row in market_rows],
                    baseline_probabilities=[row.market_probability for row in market_rows],  # type: ignore[misc]
                    outcomes=[row.home_win for row in market_rows],
                ),
            }
        )

    calibration = select_calibrator(elo_probabilities, outcomes).as_dict() if rows else None

    evaluated = len(rows)
    if evaluated < min_evaluated_games:
        decision = "insufficient_evidence"
        decision_reason = f"evaluated_games_below_minimum:{evaluated}<{min_evaluated_games}"
    else:
        verdicts = {entry["baseline"]: entry["verdict"] for entry in comparisons}
        if any(verdict == "baseline_better" for verdict in verdicts.values()):
            decision = "rejected"
            decision_reason = "a_baseline_scored_better_than_the_model"
        elif all(verdict == "model_better" for verdict in verdicts.values()):
            decision = "accepted"
            decision_reason = "every_baseline_comparison_excludes_zero"
        else:
            decision = "inconclusive"
            decision_reason = "at_least_one_comparison_interval_contains_zero"

    return {
        "asset_class": "sports",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "league": league,
        "since": None if since is None else since.astimezone(timezone.utc).isoformat(),
        "configuration": elo_config.as_dict(),
        "games_reconstructed": len(games),
        "games_excluded": excluded,
        "forecasts_skipped": skipped,
        "evaluated_games": evaluated,
        "market_baseline_games": len(market_rows),
        "metrics": {
            "elo": _score_summary(elo_probabilities, outcomes),
            "home_base_rate": _score_summary(base_rate_probabilities, outcomes),
            "devigged_closing_consensus": _score_summary(
                [row.market_probability for row in market_rows],  # type: ignore[misc]
                [row.home_win for row in market_rows],
            ),
        },
        "comparisons": comparisons,
        "calibration": calibration,
        "decision": decision,
        "decision_reason": decision_reason,
        "minimum_evaluated_games": min_evaluated_games,
        "model_state": "track_only",
        "promotion": "blocked_by_policy",
        "ratings": _current_ratings(games, elo_config),
        "disclaimer": (
            "Walk-forward research output. A rating and its paired comparison describe "
            "past collected games; they are not a validated production model, not an "
            "edge, and never a betting recommendation."
        ),
    }


def _current_ratings(games: Sequence[GameResult], config: EloConfig, *, limit: int = 40) -> list[dict[str, Any]]:
    """Ratings after every collected game, highest first."""
    state = _RatingState(config=config)
    for game in sorted(games, key=lambda entry: (entry.start_time, entry.event_id)):
        state.observe(game)
    ranked = sorted(state.ratings.items(), key=lambda item: item[1], reverse=True)
    return [
        {
            "team": team,
            "rating": format(rating.quantize(Decimal("0.01")), "f"),
            "games": state.games_played.get(team, 0),
        }
        for team, rating in ranked[:limit]
    ]


def render_sports_ratings_report(report: Mapping[str, Any]) -> str:
    """Operator-readable summary. States the verdict, including a negative one."""
    lines = [
        "Sports ratings (walk-forward Elo)",
        f"  league: {report.get('league') or 'all'}",
        f"  games reconstructed: {report.get('games_reconstructed')}",
        f"  games evaluated: {report.get('evaluated_games')} (market baseline on {report.get('market_baseline_games')})",
        f"  decision: {report.get('decision')} ({report.get('decision_reason')})",
        f"  model state: {report.get('model_state')} / promotion {report.get('promotion')}",
    ]
    excluded = report.get("games_excluded") or {}
    if excluded:
        lines.append("  excluded: " + ", ".join(f"{reason}={count}" for reason, count in sorted(excluded.items())))
    metrics = report.get("metrics") or {}
    for name in ("elo", "home_base_rate", "devigged_closing_consensus"):
        entry = metrics.get(name) or {}
        if entry.get("sample_size"):
            lines.append(
                f"  {name}: brier={entry.get('brier_score')} log_loss={entry.get('log_loss')} "
                f"accuracy={entry.get('accuracy')} n={entry.get('sample_size')}"
            )
    for comparison in report.get("comparisons") or []:
        interval = comparison.get("confidence_interval")
        interval_text = (
            "n/a" if not interval else f"[{interval[0]:.6f}, {interval[1]:.6f}]"
        )
        lines.append(
            f"  vs {comparison.get('baseline')}: {comparison.get('verdict')} "
            f"mean={comparison.get('mean_difference')} ci={interval_text} n={comparison.get('sample_size')}"
        )
        required = comparison.get("required_sample_for_this_effect")
        if required:
            lines.append(f"    games needed for this effect: {required.get('required_sample')}")
    calibration = report.get("calibration")
    if calibration:
        lines.append(f"  calibration: {calibration.get('method')} ({calibration.get('reason')})")
    lines.append(f"  {report.get('disclaimer')}")
    return "\n".join(lines)


def record_sports_ratings_experiment(
    report: Mapping[str, Any],
    *,
    path: str | Any | None = None,
    recorded_at: datetime | str | None = None,
) -> dict[str, Any] | None:
    """Append this run's verdict to the research registry, negative or not.

    A rejection is the deliverable the backlog asks for, so the only outcome that
    is *not* recorded is a run with too few evaluated games to have tested
    anything. The registry itself refuses an ``accepted`` verdict whose interval
    contains zero, which is why the decision is derived from the interval rather
    than asserted alongside it.
    """
    from .research_registry import ExperimentRecord, record_experiment

    decision = str(report.get("decision"))
    if decision == "insufficient_evidence":
        return None

    comparisons = {str(entry.get("baseline")): entry for entry in report.get("comparisons") or []}
    primary = comparisons.get("home_base_rate") or {}
    market = comparisons.get("devigged_closing_consensus")
    notes = [f"decision_reason={report.get('decision_reason')}"]
    if market:
        notes.append(
            f"vs_devigged_closing_consensus={market.get('verdict')} on {market.get('sample_size')} games"
        )
    else:
        notes.append("no_market_baseline_available")
    excluded = report.get("games_excluded") or {}
    if excluded:
        notes.append("excluded=" + ",".join(f"{reason}:{count}" for reason, count in sorted(excluded.items())))

    record = ExperimentRecord(
        hypothesis=HYPOTHESIS,
        rationale=(
            "A market price is a baseline, not a model. Elo is the cheapest model that could "
            "beat it, and its walk-forward result decides whether the rating program continues."
        ),
        dataset_version=(
            f"collected_settled_games:{report.get('league') or 'all'}:{report.get('games_reconstructed')}"
        ),
        target="home_win_probability",
        baseline="home_base_rate",
        test_method="walk_forward_paired_brier_difference_normal_interval",
        decision=decision,
        effect_size=primary.get("mean_difference"),
        effect_metric="paired_brier_improvement",
        confidence_interval=primary.get("confidence_interval"),
        sample_size=primary.get("sample_size"),
        model_version=MODEL_NAME,
        notes="; ".join(notes),
        tags=("sports", "elo", "E-21", "E-24"),
    )
    return record_experiment(record, path=path, recorded_at=recorded_at)
