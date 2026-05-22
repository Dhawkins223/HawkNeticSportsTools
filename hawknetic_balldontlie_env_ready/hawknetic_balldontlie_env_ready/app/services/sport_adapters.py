"""Multi-sport adapter framework.

The core odds/EV/parlay/correlation/Kelly math stays universal in
`services/odds_math.py` + `odds_math_extras.py` + `slip_analysis.py`.
What changes per sport is **projection**: how a leg's outcome is simulated.

This module exposes:

  - `BaseSportAdapter`: the contract every sport must implement
  - `get_adapter(sport)`: route a sport string ("NBA", "NFL", ...) to its adapter
  - 6 concrete adapters: NBA (full), NFL/MLB/NHL/Soccer/Golf (working stubs that
    use sport-tuned league averages, distributions, and trap-leg rules — they
    all run real Monte Carlo trials but with sport-appropriate features)

The existing simulation engine will dispatch player-prop / total / spread /
moneyline projections to the adapter for the leg's sport. Sports without
custom logic fall through to NBA-style behavior.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Protocol


SUPPORTED_SPORTS = ("NBA", "NFL", "MLB", "NHL", "SOCCER", "GOLF")


@dataclass
class SportConfig:
    """League-wide constants used by every sport adapter."""
    name: str
    pace_baseline: float                # team possessions/plays/PA per game
    pace_std: float
    score_baseline_per_team: float      # league avg points/runs/goals per team
    score_std: float
    home_advantage: float
    blowout_threshold: int              # margin where rotations change
    minutes_full_game: int              # 48 / 60 / 90 / nine innings / etc
    market_types: tuple[str, ...]       # markets this sport supports
    correlation_examples: dict[str, str]
    trap_rules: tuple[str, ...]
    readiness_keys: tuple[str, ...]     # required readiness signals


class BaseSportAdapter(Protocol):
    config: SportConfig

    def project_team_score(self, rng: random.Random, off_rating: float, opp_def: float, pace: float) -> float: ...
    def project_player_stat(self, rng: random.Random, stat_key: str, rate_mean: float, rate_std: float, minutes: float, pace_factor: float, form_factor: float) -> float: ...
    def trap_flags(self, *, ev_per_unit: float, model_prob: float, american_odds: int, projection: float, line: float | None, edge: float, confidence: float, context: dict[str, Any]) -> list[str]: ...
    def required_readiness_signals(self) -> tuple[str, ...]: ...


# ---------- NBA ----------

class NBAAdapter:
    config = SportConfig(
        name="NBA",
        pace_baseline=100.0, pace_std=4.0,
        score_baseline_per_team=113.0, score_std=9.0,
        home_advantage=2.5, blowout_threshold=20, minutes_full_game=48,
        market_types=("moneyline", "spread", "total", "team_prop", "player_prop"),
        correlation_examples={
            "team total over + star points over": "positive",
            "blowout spread + opposing starter over": "negative",
        },
        trap_rules=(
            "Heavy juice with thin edge",
            "Player minutes uncertain (foul trouble / injury / blowout)",
            "Projection barely clears the line",
        ),
        readiness_keys=("starting_lineup", "injuries", "minutes", "current_odds", "props"),
    )

    def project_team_score(self, rng, off_rating, opp_def, pace):
        scale = pace / self.config.pace_baseline
        base = (off_rating + (220 - opp_def)) / 2 * scale
        return max(60.0, rng.gauss(base, self.config.score_std))

    def project_player_stat(self, rng, stat_key, rate_mean, rate_std, minutes, pace_factor, form_factor):
        # NBA per-minute model, lifted by pace + form
        rate = max(0.0, rng.gauss(rate_mean * pace_factor * form_factor, rate_std))
        return rate * minutes

    def trap_flags(self, *, ev_per_unit, model_prob, american_odds, projection, line, edge, confidence, context):
        flags: list[str] = []
        if model_prob >= 0.65 and ev_per_unit < 0:
            flags.append("Likely-but-overpriced (high prob, negative EV)")
        if american_odds <= -250 and edge < 0.02:
            flags.append("Heavy juice for thin edge")
        if context.get("blowout_severity", 0) > 0.5:
            flags.append("Blowout risk reduces minutes")
        if context.get("foul_trouble"):
            flags.append("Foul trouble — minutes risk")
        if line is not None and abs(projection - line) < 0.5:
            flags.append("Projection barely clears the line")
        return flags

    def required_readiness_signals(self):
        return self.config.readiness_keys


# ---------- NFL ----------

class NFLAdapter:
    config = SportConfig(
        name="NFL",
        pace_baseline=64.0, pace_std=6.0,           # plays per team
        score_baseline_per_team=22.5, score_std=8.0,
        home_advantage=2.0, blowout_threshold=17, minutes_full_game=60,
        market_types=("moneyline", "spread", "total", "team_prop", "player_prop"),
        correlation_examples={
            "QB passing yards over + WR receiving yards over": "strong positive",
            "Under total + multiple receiving overs": "negative",
        },
        trap_rules=(
            "Bad weather/wind hurts passing props",
            "Backup QB lowers receiver confidence",
            "Heavy-juice anytime-TD prop",
            "RB props sensitive to game script",
        ),
        readiness_keys=("active_inactive", "starting_qb", "weather", "current_odds", "props", "depth_chart"),
    )

    def project_team_score(self, rng, off_rating, opp_def, pace):
        scale = pace / self.config.pace_baseline
        base = self.config.score_baseline_per_team + (off_rating - opp_def) * 0.3
        base *= scale
        return max(0.0, rng.gauss(base, self.config.score_std))

    def project_player_stat(self, rng, stat_key, rate_mean, rate_std, minutes, pace_factor, form_factor):
        # NFL stats are play-volume driven; minutes ≈ play participation
        if stat_key in {"passing_yards", "rushing_yards", "receiving_yards"}:
            mean = rate_mean * minutes * pace_factor * form_factor
            sd = max(rate_std * minutes ** 0.5, mean * 0.18)
            return max(0.0, rng.gauss(mean, sd))
        if stat_key in {"receptions", "carries", "completions"}:
            # Bernoulli/Poisson-style integer count
            lam = max(0.1, rate_mean * minutes * pace_factor * form_factor)
            return float(_poisson_sample(rng, lam))
        if stat_key in {"touchdowns", "interceptions"}:
            # Bernoulli probability per drive
            return float(rng.random() < min(0.95, max(0.0, rate_mean * pace_factor * form_factor)))
        # default fall-through
        rate = max(0.0, rng.gauss(rate_mean * pace_factor * form_factor, rate_std))
        return rate * minutes

    def trap_flags(self, *, ev_per_unit, model_prob, american_odds, projection, line, edge, confidence, context):
        flags = []
        if context.get("backup_qb"):
            flags.append("Backup QB — receiver projections unreliable")
        if context.get("wind_mph", 0) >= 18:
            flags.append("High wind hurts passing props")
        if model_prob >= 0.65 and ev_per_unit < 0:
            flags.append("Likely-but-overpriced")
        if american_odds <= -250 and edge < 0.02:
            flags.append("Heavy juice for thin edge")
        return flags

    def required_readiness_signals(self):
        return self.config.readiness_keys


# ---------- MLB ----------

class MLBAdapter:
    config = SportConfig(
        name="MLB",
        pace_baseline=38.0, pace_std=3.0,           # plate appearances per team
        score_baseline_per_team=4.5, score_std=2.5,
        home_advantage=0.2, blowout_threshold=6, minutes_full_game=9,  # innings
        market_types=("moneyline", "run_line", "total", "team_prop", "player_prop"),
        correlation_examples={
            "Hitter RBI over + teammate runs over": "positive",
            "Pitcher Ks over + opposing team total under": "positive",
            "Hitter over + opposing pitcher Ks over": "negative",
        },
        trap_rules=(
            "No confirmed lineup — block hitter props",
            "Opener / bullpen game — block pitcher props",
            "Weather delay risk lowers confidence",
            "HR props are volatile even with good projection",
        ),
        readiness_keys=("confirmed_lineup", "starting_pitcher", "weather", "park", "bullpen", "current_odds"),
    )

    def project_team_score(self, rng, off_rating, opp_def, pace):
        # Runs ~ Poisson with lambda tuned by off vs opposing pitcher
        lam = max(0.5, self.config.score_baseline_per_team + (off_rating - opp_def) * 0.05)
        return float(_poisson_sample(rng, lam))

    def project_player_stat(self, rng, stat_key, rate_mean, rate_std, minutes, pace_factor, form_factor):
        # `minutes` re-purposed as expected plate-appearances for hitters
        if stat_key in {"hits", "home_runs", "total_bases"}:
            pa = max(1, int(round(minutes * pace_factor * form_factor)))
            p_per_pa = max(0.005, min(0.7, rate_mean))
            return float(sum(1 for _ in range(pa) if rng.random() < p_per_pa))
        if stat_key in {"strikeouts"}:
            # Pitcher Ks ~ Poisson with lambda = K-rate * batters_faced
            lam = max(0.1, rate_mean * minutes * pace_factor * form_factor)
            return float(_poisson_sample(rng, lam))
        # default
        return max(0.0, rng.gauss(rate_mean * pace_factor * form_factor, rate_std)) * minutes

    def trap_flags(self, *, ev_per_unit, model_prob, american_odds, projection, line, edge, confidence, context):
        flags = []
        if context.get("lineup_confirmed") is False:
            flags.append("Lineup not confirmed — hitter props unreliable")
        if context.get("opener_or_bullpen_game"):
            flags.append("Opener/bullpen game — pitcher prop blocked")
        if model_prob >= 0.65 and ev_per_unit < 0:
            flags.append("Likely-but-overpriced")
        return flags

    def required_readiness_signals(self):
        return self.config.readiness_keys


# ---------- NHL ----------

class NHLAdapter:
    config = SportConfig(
        name="NHL",
        pace_baseline=60.0, pace_std=4.0,           # shot attempts per team
        score_baseline_per_team=3.1, score_std=1.5,
        home_advantage=0.25, blowout_threshold=4, minutes_full_game=60,
        market_types=("moneyline", "puck_line", "total", "team_prop", "player_prop"),
        correlation_examples={
            "Team total over + skater point over": "positive",
            "Goalie saves over + opposing shots over": "positive",
        },
        trap_rules=(
            "Goalie not confirmed — block goalie props",
            "Back-to-back goalie — downgrade saves projection",
            "Player goal props are high variance",
        ),
        readiness_keys=("confirmed_goalie", "line_combinations", "injuries", "current_odds", "props"),
    )

    def project_team_score(self, rng, off_rating, opp_def, pace):
        lam = max(0.3, self.config.score_baseline_per_team + (off_rating - opp_def) * 0.04)
        return float(_poisson_sample(rng, lam))

    def project_player_stat(self, rng, stat_key, rate_mean, rate_std, minutes, pace_factor, form_factor):
        # `minutes` is TOI for skaters; goalie 'minutes' = expected shots faced
        if stat_key in {"shots_on_goal"}:
            lam = max(0.1, rate_mean * minutes * pace_factor * form_factor)
            return float(_poisson_sample(rng, lam))
        if stat_key in {"goals", "assists", "points"}:
            lam = max(0.05, rate_mean * minutes * pace_factor * form_factor)
            return float(_poisson_sample(rng, lam))
        if stat_key in {"saves"}:
            shots = max(1, int(round(minutes)))  # minutes here = expected shots
            save_rate = min(0.97, max(0.85, rate_mean))
            return float(sum(1 for _ in range(shots) if rng.random() < save_rate))
        return max(0.0, rng.gauss(rate_mean * pace_factor * form_factor, rate_std)) * minutes

    def trap_flags(self, *, ev_per_unit, model_prob, american_odds, projection, line, edge, confidence, context):
        flags = []
        if context.get("goalie_confirmed") is False:
            flags.append("Goalie not confirmed — saves prop blocked")
        if context.get("back_to_back_goalie"):
            flags.append("Back-to-back goalie — fatigue risk")
        if american_odds <= -250 and edge < 0.02:
            flags.append("Heavy juice for thin edge")
        return flags

    def required_readiness_signals(self):
        return self.config.readiness_keys


# ---------- SOCCER ----------

class SoccerAdapter:
    config = SportConfig(
        name="SOCCER",
        pace_baseline=90.0, pace_std=0.0,           # 90 minutes
        score_baseline_per_team=1.4, score_std=1.2,
        home_advantage=0.35, blowout_threshold=3, minutes_full_game=90,
        market_types=("three_way_moneyline", "draw_no_bet", "double_chance",
                      "total_goals", "btts", "team_total", "player_prop", "cards", "corners"),
        correlation_examples={
            "BTTS yes + both team totals over 0.5": "strong positive",
            "Under goals + anytime goalscorer": "negative",
        },
        trap_rules=(
            "Starter status not confirmed — block player props",
            "Penalty-taker status uncertain",
            "Red-card volatility risk",
            "Three-way moneyline ignores draw probability",
        ),
        readiness_keys=("confirmed_xi", "formation", "weather", "current_odds", "market_lines"),
    )

    def project_team_score(self, rng, off_rating, opp_def, pace):
        lam = max(0.2, self.config.score_baseline_per_team * (off_rating / 1.4) * (1.4 / max(opp_def, 0.5)))
        return float(_poisson_sample(rng, lam))

    def project_player_stat(self, rng, stat_key, rate_mean, rate_std, minutes, pace_factor, form_factor):
        # `minutes` ≈ expected minutes 0..90, scale rate accordingly
        scale = max(0.0, minutes / 90.0)
        if stat_key in {"goals", "anytime_goal"}:
            p_goal = min(0.95, max(0.0, rate_mean * scale * form_factor))
            return float(rng.random() < p_goal)
        if stat_key in {"shots", "shots_on_target"}:
            lam = max(0.0, rate_mean * scale * pace_factor * form_factor)
            return float(_poisson_sample(rng, lam))
        if stat_key in {"cards", "corners"}:
            lam = max(0.0, rate_mean * scale)
            return float(_poisson_sample(rng, lam))
        return max(0.0, rng.gauss(rate_mean * scale * form_factor, rate_std))

    def trap_flags(self, *, ev_per_unit, model_prob, american_odds, projection, line, edge, confidence, context):
        flags = []
        if context.get("xi_confirmed") is False:
            flags.append("Starting XI not confirmed — player prop blocked")
        if context.get("penalty_taker_uncertain"):
            flags.append("Penalty-taker uncertainty")
        if model_prob >= 0.65 and ev_per_unit < 0:
            flags.append("Likely-but-overpriced")
        return flags

    def required_readiness_signals(self):
        return self.config.readiness_keys


# ---------- GOLF ----------

class GolfAdapter:
    config = SportConfig(
        name="GOLF",
        pace_baseline=72.0, pace_std=0.0,           # par 72
        score_baseline_per_team=70.0, score_std=3.5,
        home_advantage=0.0, blowout_threshold=10, minutes_full_game=72,
        market_types=("outright", "top5", "top10", "top20", "make_cut", "matchup", "round_score"),
        correlation_examples={
            "Top10 + matchup win": "positive",
            "Make cut + Top20": "positive",
            "Miss cut + Top20": "negative",
        },
        trap_rules=(
            "Outright odds are extremely volatile",
            "Putting spike unsupported by SG-Putting baseline",
            "Tee-time wave weather disadvantage",
            "Withdrawal risk lowers confidence",
            "Top20 may be better EV than outright at lower payout",
        ),
        readiness_keys=("tournament_field", "tee_times", "weather", "course_data", "withdrawal_status", "current_odds"),
    )

    def project_team_score(self, rng, off_rating, opp_def, pace):
        # Re-purposed: returns one player's projected round-score-to-par.
        return rng.gauss(off_rating - 72, 3.5)

    def project_player_stat(self, rng, stat_key, rate_mean, rate_std, minutes, pace_factor, form_factor):
        if stat_key in {"round_score"}:
            return rng.gauss(rate_mean + (form_factor - 1) * 2, max(2.0, rate_std))
        if stat_key in {"birdies", "bogeys"}:
            return float(_poisson_sample(rng, max(0.5, rate_mean * form_factor)))
        if stat_key in {"make_cut", "top5", "top10", "top20", "outright"}:
            # `rate_mean` is implied probability after course-fit & form
            p = min(0.99, max(0.0, rate_mean * form_factor))
            return float(rng.random() < p)
        return rng.gauss(rate_mean * form_factor, rate_std)

    def trap_flags(self, *, ev_per_unit, model_prob, american_odds, projection, line, edge, confidence, context):
        flags = []
        if context.get("withdrawal_risk"):
            flags.append("Withdrawal risk")
        if context.get("tee_time_disadvantage"):
            flags.append("Tee-time wave disadvantage")
        if american_odds >= 5000:
            flags.append("Outright at 50/1+ — extremely volatile")
        return flags

    def required_readiness_signals(self):
        return self.config.readiness_keys


# ---------- helpers + dispatcher ----------

def _poisson_sample(rng: random.Random, lam: float) -> int:
    """Knuth's Poisson sampler. For small lambda this is fast and accurate."""
    if lam <= 0:
        return 0
    if lam > 30:
        # Normal approximation for performance
        x = rng.gauss(lam, lam ** 0.5)
        return max(0, int(round(x)))
    L = pow(2.71828182845904523536, -lam)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


_ADAPTERS: dict[str, BaseSportAdapter] = {
    "NBA": NBAAdapter(),
    "NFL": NFLAdapter(),
    "MLB": MLBAdapter(),
    "NHL": NHLAdapter(),
    "SOCCER": SoccerAdapter(),
    "GOLF": GolfAdapter(),
}


def get_adapter(sport: str | None) -> BaseSportAdapter:
    """Return the adapter for the given sport, defaulting to NBA."""
    if not sport:
        return _ADAPTERS["NBA"]
    return _ADAPTERS.get(sport.upper(), _ADAPTERS["NBA"])


def supported_sports() -> tuple[str, ...]:
    return SUPPORTED_SPORTS


def adapter_summary() -> list[dict[str, Any]]:
    """Used by /api/sports for the public sport-picker."""
    return [
        {
            "key": name,
            "name": adapter.config.name,
            "marketTypes": list(adapter.config.market_types),
            "trapRules": list(adapter.config.trap_rules),
            "correlationExamples": adapter.config.correlation_examples,
            "readinessKeys": list(adapter.config.readiness_keys),
        }
        for name, adapter in _ADAPTERS.items()
    ]
