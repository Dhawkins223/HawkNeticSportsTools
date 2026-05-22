"""HawkNetic Monte Carlo simulation engine.

Replaces the previous placeholder simulator. For each Run Algorithm request,
this module:

  1. Loads `player_skill` rates and `team_metrics` for every leg's game/player.
  2. Loads live overrides from `live_player_status` / `live_injuries` /
     `live_games` so in-game state can replace pregame baselines.
  3. Runs N independent simulations (default 10,000):
        - sample game pace (Normal around team-pace blend)
        - sample team scores (Normal around offensive vs defensive ratings,
          scaled by the sampled pace)
        - sample player minutes (truncated Normal, capped by minutes_restriction
          and reduced for injuries / blowout risk)
        - sample per-minute rates (Normal) and multiply by minutes
        - for live games: split into "already played" + "remaining minutes"
          and project only the remaining portion
  4. For every leg: count simulations where the leg wins.
  5. For the parlay: count simulations where ALL legs win (this is the
     correlation-aware joint probability).
  6. Returns leg outcome arrays so downstream code can compute pairwise
     correlation matrices.

Correlation emerges naturally because every same-game leg shares the same
sampled pace and team-score draw. This is exactly what spec §11/§12 require.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.database import execute

DEFAULT_RUNS = 10_000

# Reasonable league-wide fallbacks when a player has no `player_skill` row yet.
LEAGUE_DEFAULTS = {
    "minutes_mean": 28.0, "minutes_std": 6.0,
    "points_per_min_mean": 0.55, "points_per_min_std": 0.25,
    "rebounds_per_min_mean": 0.18, "rebounds_per_min_std": 0.10,
    "assists_per_min_mean": 0.13, "assists_per_min_std": 0.08,
    "threes_per_min_mean": 0.07, "threes_per_min_std": 0.05,
    "usage_rate": 0.20, "availability": 0.93,
}
LEAGUE_TEAM_DEFAULTS = {
    "pace": 100.0, "offensive_rating": 113.0,
    "defensive_rating": 113.0, "home_advantage": 2.5,
}


@dataclass
class GameContext:
    game_id: int
    home_team_id: int | None = None
    away_team_id: int | None = None
    pace_baseline: float = 100.0
    home_off: float = 113.0
    home_def: float = 113.0
    away_off: float = 113.0
    away_def: float = 113.0
    home_advantage: float = 2.5
    is_live: bool = False
    period: int | None = None
    home_score: int = 0
    away_score: int = 0
    elapsed_fraction: float = 0.0  # 0.0 = pregame, 1.0 = final
    blowout_severity: float = 0.0  # 0..1


@dataclass
class PlayerContext:
    player_id: int | None
    game_id: int
    team_id: int | None = None
    minutes_mean: float = LEAGUE_DEFAULTS["minutes_mean"]
    minutes_std: float = LEAGUE_DEFAULTS["minutes_std"]
    rates: dict[str, tuple[float, float]] = field(default_factory=dict)
    availability: float = LEAGUE_DEFAULTS["availability"]
    injury_multiplier: float = 1.0  # multiply baseline projection
    minutes_restriction: float | None = None
    live_minutes_played: float = 0.0
    live_stat_so_far: dict[str, float] = field(default_factory=dict)
    is_active: bool = True


@dataclass
class LegSpec:
    leg_id: str
    game_id: int
    market_type: str
    selection: str
    line: float | None
    decimal_odds: float
    american_odds: int
    player_id: int | None = None
    is_under: bool = False  # True if the user picked the under side
    stat_key: str | None = None  # "points" | "rebounds" | "assists" | "threes" | None for game markets


# ---------------- helpers ----------------

def _stat_key_from_label(label: str | None) -> str | None:
    if not label:
        return None
    text = label.lower()
    if "three" in text:
        return "threes"
    if "rebound" in text:
        return "rebounds"
    if "assist" in text:
        return "assists"
    if "point" in text:
        return "points"
    return None


def _truncated_normal(rng: random.Random, mean: float, std: float, low: float, high: float) -> float:
    # Simple rejection sampler — fine for our distributions, fast in pure Python.
    if std <= 0:
        return max(low, min(mean, high))
    for _ in range(8):
        x = rng.gauss(mean, std)
        if low <= x <= high:
            return x
    # If rejection fails, fall back to clamped sample.
    return max(low, min(rng.gauss(mean, std), high))


# ---------------- context loaders ----------------

def _load_game_context(conn: Any, game_id: int) -> GameContext:
    row = execute(conn, "SELECT * FROM historical_games WHERE id = ?", (game_id,)).fetchone()
    home_id = away_id = None
    if row:
        d = dict(row)
        home_id = d.get("home_team_id")
        away_id = d.get("away_team_id")
    home_metrics = _team_metrics(conn, home_id)
    away_metrics = _team_metrics(conn, away_id)
    pace_baseline = (home_metrics["pace"] + away_metrics["pace"] + LEAGUE_TEAM_DEFAULTS["pace"]) / 3
    ctx = GameContext(
        game_id=game_id,
        home_team_id=home_id,
        away_team_id=away_id,
        pace_baseline=pace_baseline,
        home_off=home_metrics["offensive_rating"],
        home_def=home_metrics["defensive_rating"],
        away_off=away_metrics["offensive_rating"],
        away_def=away_metrics["defensive_rating"],
        home_advantage=home_metrics["home_advantage"],
    )
    live = execute(conn, "SELECT * FROM live_games WHERE game_id = ?", (game_id,)).fetchone()
    if live:
        d = dict(live)
        status = (d.get("status") or "").lower()
        if status in {"live", "in_progress", "halftime"}:
            ctx.is_live = True
            ctx.period = int(d.get("period") or 0)
            ctx.home_score = int(d.get("home_score") or 0)
            ctx.away_score = int(d.get("away_score") or 0)
            # Each NBA quarter is roughly 25% of game time. Cap at 0.95.
            ctx.elapsed_fraction = min(0.95, (ctx.period or 0) * 0.25)
            margin = abs(ctx.home_score - ctx.away_score)
            if margin >= 25 and (ctx.period or 0) >= 3:
                ctx.blowout_severity = min(1.0, (margin - 20) / 25)
    return ctx


def _team_metrics(conn: Any, team_id: int | None) -> dict[str, float]:
    if not team_id:
        return dict(LEAGUE_TEAM_DEFAULTS)
    row = execute(conn, "SELECT pace, offensive_rating, defensive_rating, home_advantage FROM team_metrics WHERE team_id = ?", (team_id,)).fetchone()
    if row:
        d = dict(row)
        return {k: float(d.get(k) or v) for k, v in LEAGUE_TEAM_DEFAULTS.items()}
    return dict(LEAGUE_TEAM_DEFAULTS)


def _load_player_context(conn: Any, player_id: int | None, game_id: int) -> PlayerContext:
    ctx = PlayerContext(player_id=player_id, game_id=game_id)
    if player_id:
        row = execute(conn, "SELECT * FROM player_skill WHERE player_id = ?", (player_id,)).fetchone()
        if row:
            d = dict(row)
            ctx.minutes_mean = float(d.get("minutes_mean") or LEAGUE_DEFAULTS["minutes_mean"])
            ctx.minutes_std = float(d.get("minutes_std") or LEAGUE_DEFAULTS["minutes_std"])
            ctx.availability = float(d.get("availability") or LEAGUE_DEFAULTS["availability"])
            for key in ("points", "rebounds", "assists", "threes"):
                mean = float(d.get(f"{key}_per_min_mean") or LEAGUE_DEFAULTS[f"{key}_per_min_mean"])
                std = float(d.get(f"{key}_per_min_std") or LEAGUE_DEFAULTS[f"{key}_per_min_std"])
                ctx.rates[key] = (mean, std)
    if not ctx.rates:
        for key in ("points", "rebounds", "assists", "threes"):
            ctx.rates[key] = (LEAGUE_DEFAULTS[f"{key}_per_min_mean"], LEAGUE_DEFAULTS[f"{key}_per_min_std"])

    # Live overrides
    if player_id:
        live = execute(conn, "SELECT * FROM live_player_status WHERE player_id = ? AND game_id = ?", (player_id, game_id)).fetchone()
        if live:
            d = dict(live)
            status = (d.get("status") or "active").lower()
            ctx.is_active = status not in {"out", "inactive", "ineligible"}
            ctx.live_minutes_played = float(d.get("minutes_played") or 0)
            ctx.live_stat_so_far = {
                "points": float(d.get("points") or 0),
                "rebounds": float(d.get("rebounds") or 0),
                "assists": float(d.get("assists") or 0),
                "threes": float(d.get("threes") or 0),
            }
            if d.get("minutes_restriction"):
                ctx.minutes_restriction = float(d["minutes_restriction"])
            fouls = int(d.get("fouls") or 0)
            if fouls >= 5:
                ctx.injury_multiplier *= 0.65  # foul trouble → fewer minutes
        injury = execute(conn, "SELECT designation FROM live_injuries WHERE player_id = ? ORDER BY reported_at DESC LIMIT 1", (player_id,)).fetchone()
        if injury:
            tag = (dict(injury).get("designation") or "").lower()
            if tag in {"out", "inactive"}:
                ctx.is_active = False
            elif tag in {"questionable", "doubtful"}:
                ctx.injury_multiplier *= 0.85
                ctx.availability *= 0.6
            elif tag == "probable":
                ctx.injury_multiplier *= 0.97
    return ctx


# ---------------- core simulation ----------------

def simulate_slip(conn: Any, legs: list[LegSpec], runs: int = DEFAULT_RUNS, seed: int | None = None) -> dict[str, Any]:
    """Run N simulations and return per-leg + parlay probabilities w/ samples."""
    rng = random.Random(seed) if seed is not None else random.Random()
    runs = max(1000, min(runs, 50_000))

    game_ids = sorted({leg.game_id for leg in legs})
    game_ctx = {gid: _load_game_context(conn, gid) for gid in game_ids}

    player_ctx: dict[tuple[int, int], PlayerContext] = {}
    for leg in legs:
        if leg.player_id and (leg.player_id, leg.game_id) not in player_ctx:
            player_ctx[(leg.player_id, leg.game_id)] = _load_player_context(conn, leg.player_id, leg.game_id)

    leg_outcomes = [[0] * runs for _ in legs]
    leg_projection_sums = [0.0] * len(legs)
    leg_projection_sq_sums = [0.0] * len(legs)
    parlay_hits = 0
    inactive_flags = [False] * len(legs)
    for idx, leg in enumerate(legs):
        if leg.player_id:
            pctx = player_ctx[(leg.player_id, leg.game_id)]
            inactive_flags[idx] = not pctx.is_active

    for run_idx in range(runs):
        per_game_pace: dict[int, float] = {}
        per_game_score: dict[int, tuple[float, float]] = {}
        for gid, gctx in game_ctx.items():
            pace = _truncated_normal(rng, gctx.pace_baseline, max(2.0, gctx.pace_baseline * 0.04), 80, 120)
            per_game_pace[gid] = pace
            scale = pace / 100.0
            base_h = (gctx.home_off + (220 - gctx.away_def)) / 2 * scale + gctx.home_advantage * (1 - gctx.elapsed_fraction)
            base_a = (gctx.away_off + (220 - gctx.home_def)) / 2 * scale
            score_std = 9 * (1 - gctx.elapsed_fraction * 0.5)
            home_total = max(60.0, rng.gauss(base_h, score_std))
            away_total = max(60.0, rng.gauss(base_a, score_std))
            if gctx.is_live:
                # Project only remaining minutes from current score forward.
                remaining = max(0.05, 1 - gctx.elapsed_fraction)
                home_total = gctx.home_score + max(0.0, rng.gauss(base_h * remaining, score_std * remaining))
                away_total = gctx.away_score + max(0.0, rng.gauss(base_a * remaining, score_std * remaining))
            per_game_score[gid] = (home_total, away_total)

        # Sample each player's minutes ONCE per trial so that all legs for the
        # same player share the same minutes draw. This is what creates positive
        # correlation between same-player legs (e.g. Curry threes ↔ points).
        per_player_trial: dict[tuple[int, int], dict[str, float]] = {}
        for (pid, gid), pctx in player_ctx.items():
            gctx = game_ctx[gid]
            base_minutes_mean = pctx.minutes_mean
            if gctx.is_live:
                base_minutes_mean *= max(0.0, 1 - gctx.elapsed_fraction)
            if pctx.minutes_restriction:
                base_minutes_mean = min(base_minutes_mean, pctx.minutes_restriction)
            base_minutes_mean *= 1 - 0.30 * gctx.blowout_severity
            minutes = _truncated_normal(rng, base_minutes_mean, max(1.5, pctx.minutes_std), 0, 48)
            minutes *= pctx.injury_multiplier
            # Sample one "form" multiplier per trial that lifts ALL stats together
            # (a "good night" for the player). Mild lift, std 0.10.
            form_factor = max(0.4, rng.gauss(1.0, 0.10))
            per_player_trial[(pid, gid)] = {"minutes": minutes, "form": form_factor}

        all_hit = True
        for idx, leg in enumerate(legs):
            if inactive_flags[idx]:
                # Inactive player → leg automatically loses.
                all_hit = False
                continue
            home_total, away_total = per_game_score[leg.game_id]
            pace_factor = per_game_pace[leg.game_id] / 100.0
            projected = _project_leg(rng, leg, game_ctx[leg.game_id], player_ctx, pace_factor, home_total, away_total, per_player_trial)
            leg_projection_sums[idx] += projected
            leg_projection_sq_sums[idx] += projected * projected
            wins = _leg_wins(leg, projected, home_total, away_total)
            leg_outcomes[idx][run_idx] = 1 if wins else 0
            if not wins:
                all_hit = False
        if all_hit and not any(inactive_flags):
            parlay_hits += 1

    leg_probabilities = [sum(outcomes) / runs for outcomes in leg_outcomes]
    parlay_probability = parlay_hits / runs if not any(inactive_flags) else 0.0
    leg_projections = [s / runs for s in leg_projection_sums]
    leg_stds = []
    for idx in range(len(legs)):
        mean = leg_projections[idx]
        sq_mean = leg_projection_sq_sums[idx] / runs
        var = max(0.0, sq_mean - mean * mean)
        leg_stds.append(math.sqrt(var))

    return {
        "runs": runs,
        "leg_probabilities": leg_probabilities,
        "leg_projections": leg_projections,
        "leg_projection_stds": leg_stds,
        "leg_outcomes": leg_outcomes,
        "parlay_probability": parlay_probability,
        "inactive_flags": inactive_flags,
    }


def _project_leg(
    rng: random.Random,
    leg: LegSpec,
    gctx: GameContext,
    player_ctx: dict[tuple[int, int], PlayerContext],
    pace_factor: float,
    home_total: float,
    away_total: float,
    per_player_trial: dict[tuple[int, int], dict[str, float]] | None = None,
) -> float:
    if leg.market_type == "moneyline":
        return home_total - away_total  # positive = home wins; we'll interpret in _leg_wins
    if leg.market_type == "spread":
        return home_total - away_total
    if leg.market_type == "total":
        return home_total + away_total

    # Player props
    if not leg.player_id or not leg.stat_key:
        # Manual or unknown player prop — fall back to line-anchored sample
        if leg.line is not None:
            return rng.gauss(leg.line, 4.0)
        return rng.gauss(20, 8)
    pctx = player_ctx[(leg.player_id, leg.game_id)]

    # Read SHARED per-trial minutes + form so same-player legs correlate.
    trial = per_player_trial.get((leg.player_id, leg.game_id)) if per_player_trial else None
    if trial:
        minutes = trial["minutes"]
        form_factor = trial["form"]
    else:
        # Fallback (single-leg path / legacy callers)
        base_minutes_mean = pctx.minutes_mean
        if gctx.is_live:
            base_minutes_mean *= max(0.0, 1 - gctx.elapsed_fraction)
        if pctx.minutes_restriction:
            base_minutes_mean = min(base_minutes_mean, pctx.minutes_restriction)
        base_minutes_mean *= 1 - 0.30 * gctx.blowout_severity
        minutes = _truncated_normal(rng, base_minutes_mean, max(1.5, pctx.minutes_std), 0, 48)
        minutes *= pctx.injury_multiplier
        form_factor = 1.0

    rate_mean, rate_std = pctx.rates[leg.stat_key]
    rate_mean *= pace_factor * form_factor  # pace + form lift the rate together
    rate = max(0.0, rng.gauss(rate_mean, rate_std))
    remaining_projection = rate * minutes
    return pctx.live_stat_so_far.get(leg.stat_key, 0.0) + remaining_projection


def _leg_wins(leg: LegSpec, projection: float, home_total: float, away_total: float) -> bool:
    if leg.market_type == "moneyline":
        # `selection` is the team that needs to win. We don't always know which side is home,
        # but for scoring it's sufficient to interpret: home wins when projection>0.
        # The caller orients selection via the `is_under` heuristic on the upstream side.
        return projection > 0 if not leg.is_under else projection < 0
    if leg.market_type == "spread":
        line = leg.line if leg.line is not None else 0.0
        margin = projection
        return (margin + line) > 0 if not leg.is_under else (margin + line) < 0
    if leg.market_type in {"total", "team_prop"}:
        line = leg.line if leg.line is not None else (home_total + away_total)
        total = home_total + away_total if leg.market_type == "total" else projection
        return total > line if not leg.is_under else total < line
    # Player prop default
    line = leg.line if leg.line is not None else projection
    return projection > line if not leg.is_under else projection < line


# ---------------- correlation ----------------

def correlation_matrix(leg_outcomes: list[list[int]]) -> list[list[float]]:
    """Pairwise Pearson correlation across simulation outcomes (binary 0/1)."""
    n = len(leg_outcomes)
    runs = len(leg_outcomes[0]) if leg_outcomes else 0
    if n == 0 or runs == 0:
        return []
    means = [sum(row) / runs for row in leg_outcomes]
    stds = [math.sqrt(max(1e-12, sum((x - means[i]) ** 2 for x in leg_outcomes[i]) / runs)) for i in range(n)]
    matrix = [[1.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            cov = sum((leg_outcomes[i][k] - means[i]) * (leg_outcomes[j][k] - means[j]) for k in range(runs)) / runs
            denom = stds[i] * stds[j]
            rho = cov / denom if denom > 1e-12 else 0.0
            matrix[i][j] = matrix[j][i] = rho
    return matrix


def parse_leg_inputs(legs: list[dict[str, Any]]) -> list[LegSpec]:
    """Build LegSpec instances from API leg dicts."""
    out: list[LegSpec] = []
    for leg in legs:
        selection = str(leg.get("selection") or "").lower()
        is_under = "under" in selection
        market_type = str(leg.get("marketType") or "")
        stat_key = _stat_key_from_label(leg.get("selection") or leg.get("notes")) if market_type == "player_prop" else None
        out.append(LegSpec(
            leg_id=str(leg.get("id") or ""),
            game_id=int(leg.get("gameId") or 0),
            market_type=market_type,
            selection=str(leg.get("selection") or ""),
            line=float(leg["line"]) if leg.get("line") is not None else None,
            decimal_odds=0.0,  # filled by caller
            american_odds=int(leg.get("oddsAmerican") or 0),
            player_id=int(leg["playerId"]) if leg.get("playerId") else None,
            is_under=is_under,
            stat_key=stat_key,
        ))
    return out


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
