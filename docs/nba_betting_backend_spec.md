# NBA Betting Backend Specification

This document captures the high-level design and implementation-ready pseudocode for the NBA betting backend. It is intended to be dropped directly into a coding workflow so that an LLM or developer can translate the logic into framework-specific code (e.g., a Next.js app).

## 0. High-Level Design

**Goal:**

Given player baselines, betting lines, and game context (injuries, rest, travel, etc.), return:

* Per-prop projections and expected value (EV)
* Correlated same-game parlay (SGP) simulation results:
  * Joint hit probability
  * Fair odds
  * EV compared to the bookmaker odds

## 1. Data Inputs

```
DATA:
  For each GAME:
    id, date, home_team, away_team, odds (spread, total, moneyline), venue

  For each PLAYER:
    team
    rolling_stats = {
      last_n_games,
      season_average,
      home/away splits,
      vs_opponent (if enough samples)
    }

  For each PLAYER-STAT baseline:
    player_id
    stat_type in {points, rebounds, assists, threes, pra}
    mean         # baseline expectation
    stdev        # baseline volatility
    usage_rate   # offensive usage %
    minutes      # typical minutes

  For each GAME CONTEXT:
    injury_report (who out, minutes limits)
    rest_days[team]
    travel_distance[team]
    pace_estimate (from both teams)
    matchup_notes (e.g., tough rim protection, switchy defense)
    blowout_risk_estimate
```

The algorithm is agnostic to the data source, so long as the above information is provided.

## 2. Build Context Adjustments

```
FUNCTION build_context(game):
  ctx = {}

  # 1) Pace factor
  base_pace = league_avg_pace
  team_paces = [team_pace[home_team], team_pace[away_team]]
  ctx.pace_factor = weighted_average(team_paces) / base_pace

  # 2) Injury impact (per team)
  FOR each team in {home, away}:
    missing_minutes = sum(projected_minutes_of_out_players)
    ctx.injury_impact_team[team] = f(missing_minutes) 
      # -> convert missing usage/min into +/-% opportunity for remaining players

  # 3) Matchup difficulty (per player)
  FOR each key_player:
    ctx.matchup_difficulty[player] = number_between(0.85, 1.15)
      # <1.0 = tough matchup, >1.0 = favorable, based on opponent scheme & personnel

  # 4) Rest / travel
  FOR each team:
    ctx.rest_days[team] = days_since_last_game
    ctx.travel_penalty[team] = small_negative_if(b2b_or_long_travel)

  # 5) Blowout risk
  ctx.blowout_risk = function_of(spread, injuries, depth)

  RETURN ctx
```

## 3. Adjusted Player Projections

```
FUNCTION project_player_stat(player, stat_type, baseline, ctx):
  mean = baseline.mean
  stdev = baseline.stdev

  # pace
  mean *= ctx.pace_factor

  # team injury: more usage if teammates out
  team_boost = ctx.injury_impact_team[player.team]
  mean *= (1 + team_boost)

  # matchup difficulty
  matchup_mul = ctx.matchup_difficulty[player] OR 1.0
  mean *= matchup_mul

  # rest & travel (small effects)
  rest_days = ctx.rest_days[player.team]
  IF rest_days <= 1:
    mean *= 0.97
  travel_mul = ctx.travel_penalty[player.team] OR 0
  mean *= (1 + travel_mul)

  # blowout: reduce some minutes for stars
  mean *= (1 - 0.25 * ctx.blowout_risk)

  # adjust volatility with blowout & usage
  stdev *= (1 + 0.15 * ctx.blowout_risk)

  RETURN { mean, stdev }
```

Call this for every player/stat market you want to price.

## 4. Single Prop EV Calculation

```
FUNCTION prop_ev(player, stat_type, line, over_odds, under_odds, projection):
  # Assume normal distribution for simplicity
  mu = projection.mean
  sigma = projection.stdev

  p_over = 1 - NormalCDF((line - mu) / sigma)
  p_under = 1 - p_over

  imp_over = american_to_prob(over_odds)
  imp_under = american_to_prob(under_odds)

  ev_over = EV_percent(p_over, over_odds)
  ev_under = EV_percent(p_under, under_odds)

  IF ev_over > ev_under:
    best_side = "over"
    best_ev = ev_over
    best_imp = imp_over
  ELSE:
    best_side = "under"
    best_ev = ev_under
    best_imp = imp_under

  RETURN {
    best_side,
    projection: mu,
    ev_percent: best_ev,
    implied_prob: best_imp
  }
```

**Helper formulas:**

```
FUNCTION american_to_prob(odds):
  IF odds > 0: RETURN 100 / (odds + 100)
  ELSE:       RETURN abs(odds) / (abs(odds) + 100)

FUNCTION prob_to_american(p):
  IF p >= 0.5: RETURN - (p / (1-p)) * 100
  ELSE:       RETURN ((1-p) / p) * 100

FUNCTION EV_percent(p_model, odds):
  decimal = (odds > 0) ? (1 + odds/100) : (1 + 100/abs(odds))
  RETURN (p_model * decimal - 1) * 100
```

## 5. Correlated SGP Simulation

### 5.1 Correlation Rules

```
FUNCTION leg_correlation(legA, legB):
  IF legA.player == legB.player:
    IF legA.stat == legB.stat:
      RETURN 0.8        # same stat same player
    ELSE:
      RETURN 0.4        # points/assists/etc correlated
  IF legA.team == legB.team:
    RETURN 0.2          # same team scoring environments
  IF legA.team != legB.team:
    RETURN 0.05         # mild game-level link
```

### 5.2 Build Correlation Matrix

```
FUNCTION build_corr_matrix(legs):
  n = len(legs)
  M = n x n matrix

  FOR i in 0..n-1:
    FOR j in 0..n-1:
      IF i == j: M[i][j] = 1
      ELSE:      M[i][j] = leg_correlation(legs[i], legs[j])

  ENSURE positive_definite(M) via small adjustments if needed
  RETURN M
```

### 5.3 Monte Carlo SGP

```
FUNCTION simulate_sgp(legs, bookmaker_odds, baselines, ctx, iterations = 20000):
  # 1) get projections for each leg
  configs = []
  FOR each leg IN legs:
    proj = project_player_stat(
      leg.player,
      leg.stat,
      find_baseline(baselines, leg.player, leg.stat),
      ctx
    )
    IF proj is null:
      # fallback: center at line with generic stdev
      proj.mean = leg.line
      proj.stdev = max(2, 0.25 * leg.line)

    configs.append({ leg, mean: proj.mean, stdev: proj.stdev })

  # 2) build correlation matrix & Cholesky
  C = build_corr_matrix(legs)
  L = cholesky(C)    # lower-triangular

  # 3) run simulations
  hits = 0

  FOR t in 1..iterations:
    # sample independent normals
    z[0..n-1] = iid_standard_normals()

    # create correlated normals: y = L * z
    y[i] = sum(L[i][k] * z[k] for k in 0..i)

    # check all legs
    all_hit = TRUE
    FOR i in 0..n-1:
      cfg = configs[i]
      sample_value = cfg.mean + cfg.stdev * y[i]

      IF cfg.leg.direction == 'over':
        IF sample_value < cfg.leg.line: all_hit = FALSE; BREAK
      ELSE:
        IF sample_value > cfg.leg.line: all_hit = FALSE; BREAK

    IF all_hit: hits += 1

  p_joint = hits / iterations

  book_imp = american_to_prob(bookmaker_odds)
  fair_odds = prob_to_american(p_joint)
  ev = EV_percent(p_joint, bookmaker_odds)

  RETURN {
    legs: legs,
    p_joint: p_joint,
    implied_prob: book_imp,
    fair_odds: fair_odds,
    ev_percent: ev,
    bookmaker_odds: bookmaker_odds,
    model_inputs: ctx
  }
```

## 6. API Shape

```
ENDPOINT GET /api/props
  INPUT: game_id (optional), stat_type (optional), min_ev (optional)
  STEPS:
    - build_context(game)
    - for each offered prop line:
        - get projection
        - calculate EV
        - filter by min_ev if provided
    - return list of {player, stat_type, line, projection, ev_percent, implied_prob, odds}

ENDPOINT POST /api/simulations/run
  BODY: { legs: SimulationLeg[], odds: number, optional_context_overrides }
  STEPS:
    - build_context(game) (or override with body)
    - result = simulate_sgp(legs, odds, baselines, context)
    - return result
```

Where `SimulationLeg` is:

```
SimulationLeg:
  prop_id: string
  player: string
  team: string
  stat: "points" | "rebounds" | "assists" | "3pm" | "pts+reb+ast"
  direction: "over" | "under"
  line: number
  odds: number  # American odds for that leg (for display only)
```

## 7. Prompt Hint for Code Generation

Provide your implementation partner (e.g., GPT-4, GitHub Copilot) with instructions such as:

> "Implement this pseudocode in TypeScript/Node for my Next.js app. Use `/app/api/.../route.ts` handlers. Use pure functions in `lib/model/*` for math, projections, and simulation. Do not change my front-end types; just conform to them."

This ensures the generated backend code remains aligned with the spec above.
