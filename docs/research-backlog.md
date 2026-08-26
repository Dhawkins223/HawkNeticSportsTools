# Research Backlog

Fifty ranked experiments for the sports probability program. Findings and
evidence grading are in `docs/sports-prediction-research-program.md`.

## How this backlog is used

Nothing enters a production model because it sounds useful. Every entry follows
the same path:

```text
hypothesis → historical reconstruction → leakage audit → walk-forward test
→ baseline comparison → significance test → prospective shadow test
→ calibration audit → production eligibility
```

Before starting an experiment, call
`research_registry.previously_rejected(hypothesis)`. After finishing it, record
the result with `research_registry.record_experiment(...)` **whether it
succeeded or not**. A rejection is a deliverable. The registry refuses to record
an `accepted` verdict whose confidence interval contains zero, and its hash
chain makes later rewriting detectable.

**Difficulty** and **Value** are 1–5. **Value** is the expected improvement in
out-of-sample calibrated probability quality, not expected profit.

## Tier A — Foundational (run before anything else)

These validate the machinery every later experiment depends on. An error here
invalidates everything downstream.

| ID | Hypothesis | Data required | Test and baseline | Success metric | Diff | Value |
| --- | --- | --- | --- | --- | --- | --- |
| E-01 | Shin de-vig yields better-calibrated market probabilities than proportional on **our** markets | ≥ 2 seasons of two-sided odds + settlements | Paired Brier/log loss, Shin vs multiplicative baseline | Paired improvement CI excludes zero | 2 | 5 |
| E-02 | De-vig method disagreement is large enough to invalidate sub-threshold edges | Same as E-01 | Distribution of `method_disagreement` by market skew | Quantify % of candidates where gap > edge | 1 | 5 |
| E-03 | Our stored "closing" price is genuinely the last available pre-start price | Odds history with timestamps | Audit gap between last quote and start time | < 5 min median gap; no post-start quotes | 2 | 5 |
| E-04 | Player props are less efficient than moneylines | Prop odds + settlements, matched moneylines | Compare de-vigged calibration and margin by market type | Calibration gap CI excludes zero | 3 | 4 |
| E-05 | Our features contain no post-cutoff information | Feature store + timestamps | Automated leakage audit on every feature's availability time | Zero features resolvable after cutoff | 3 | 5 |
| E-06 | Kalshi calibration varies by time-to-expiry (Moshrefi replication) | Kalshi price history + settlements | Fit calibration per TTE bucket | Bucket parameters differ significantly | 3 | 4 |
| E-07 | Consensus across books beats any single book as a baseline | Multi-book odds | Brier of consensus vs best single book | Consensus improvement CI excludes zero | 2 | 4 |
| E-08 | Exchange (Kalshi/Polymarket) prices and sportsbook closes disagree systematically — *tooling delivered in `venue-compare`; needs a fresh board and venue snapshot taken together, over enough matched games to satisfy section J* | Both price series, aligned | Paired comparison at matched timestamps | Persistent signed gap | 2 | 4 |
| E-09 | Sample sizes required for our claimed edges are attainable — **run and rejected**: at 284.8 gradable NFL games/season the observed blend effect (−0.000104) is 0.15x the detectable floor of 0.000703 and would need ~774 seasons; pooling four leagues brings a 1% edge from 68.7 seasons to 3.7. See section P of the research program; `power-audit` runs it | Historical candidate counts | Power analysis on realized candidate volume | Explicit bets-per-year vs required N | 1 | 5 |
| E-10 | Settlement data is correct and never retroactively revised | Settlement history snapshots | Diff snapshots over time | Zero silent revisions | 2 | 5 |

## Tier B — Market structure

| ID | Hypothesis | Data required | Test and baseline | Success metric | Diff | Value |
| --- | --- | --- | --- | --- | --- | --- |
| E-11 | Wind above 15 mph is under-priced in NFL totals | NFL totals + hourly weather at venue | Walk-forward vs closing total, **no subgroup conditioning** | Pre-registered single test, CI excludes zero | 3 | 3 |
| E-12 | Line movement predicts outcome after controlling for the closing price | Timestamped movement history | Add movement to a model already containing close | Incremental log loss improvement | 3 | 2 |
| E-13 | Reverse line movement carries signal | Movement + betting-percentage data | Same, controlling for close | Incremental improvement | 3 | 2 |
| E-14 | Opening-line error is predictable | Open and close series | Regress close-open on pregame features | Out-of-sample R² > 0 | 2 | 3 |
| E-15 | Stale prices exist across books long enough to matter | Multi-book tick data | Measure cross-book divergence duration | Divergence > margin for > 60s | 3 | 3 |
| E-16 | Parlay markup grows with leg count on our venue | Parlay and leg prices | Compare parlay price to product of legs by leg count | Monotone markup, CI excludes zero | 2 | 4 |
| E-17 | Margin varies systematically by market type and league | Odds across markets | Booksum distribution by segment | Documented margin map | 1 | 3 |
| E-18 | Low-limit markets are less efficient than high-limit ones | Odds + posted limits | Calibration by limit tier | Calibration degrades with limit | 3 | 4 |
| E-19 | CLV predicts realized return in our own data | Predictions, closes, settlements | Regress return on CLV | Positive slope, CI excludes zero | 2 | 4 |
| E-20 | Favourite-longshot bias is present in our markets | De-vigged probabilities + outcomes | Calibration by probability decile | Signed deviation at the tails | 2 | 4 |

## Tier C — Sports modeling

| ID | Hypothesis | Data required | Test and baseline | Success metric | Diff | Value |
| --- | --- | --- | --- | --- | --- | --- |
| E-21 | Elo beats base rate out-of-sample — **run and accepted**: +0.0171 paired Brier, CI [0.0137, 0.0206], n=7,159 NFL games; see section O of the research program | Schedule + results | Walk-forward Elo vs base rate | Brier improvement CI excludes zero | 1 | 4 |
| E-22 | Opponent-adjusted efficiency beats raw efficiency | Box scores + schedule | Both in same model class | Incremental improvement | 2 | 4 |
| E-23 | Gradient boosting beats logistic regression on identical features | Feature store | Walk-forward, both calibrated | Paired improvement CI excludes zero | 2 | 3 |
| E-24 | Adding market price to a stats model beats both alone — **run, inconclusive with a tight interval**: the blend scores −0.0001 paired Brier against the close, CI [−0.00060, +0.00039], n=4,780, while beating Elo alone by 0.0192. The rating adds nothing detectable to the price on NFL moneylines; `sports_market_model.py` runs it | Features + odds | Three-way comparison | Combined beats each component | 2 | 5 |
| E-25 | Hierarchical/partial pooling beats per-team estimation on sparse data | Multi-season data | Compare shrinkage vs independent fits | Lower log loss early season | 3 | 4 |
| E-26 | Starting pitcher identity is the largest single-player effect (MLB) | Lineups + Statcast | Ablate pitcher features | Large drop when removed | 2 | 4 |
| E-27 | Within-season drift is material | Multi-season predictions | Rolling calibration slope over time | Documented drift magnitude | 2 | 4 |
| E-28 | Rest/back-to-back effects survive controlling for market price | Schedule + odds | Residual regression on rest | CI excludes zero after control | 2 | 3 |
| E-29 | Travel and time-zone effects survive market control | Schedule + venue geography | Same | CI excludes zero | 3 | 2 |
| E-30 | Goalie identity dominates NHL team form | Confirmed starters | Ablation | Large effect | 2 | 3 |
| E-31 | xG-based ratings beat goal-based ratings (soccer) | Shot-level data | Walk-forward comparison | Improvement CI excludes zero | 3 | 4 |
| E-32 | Player minutes are the dominant driver of prop distributions (NBA) | Minutes + box scores | Variance decomposition | Minutes explain majority | 3 | 4 |
| E-33 | Tracking-derived expected stats beat box-score aggregates | Tracking feeds | Incremental test over box score | Improvement after cost | 5 | 3 |
| E-34 | Referee assignment predicts foul/penalty rates | Official assignments | Multi-level model with FDR correction | Survives correction | 3 | 2 |
| E-35 | Pace is more predictable than efficiency | Possession data | Compare predictability of both | R² comparison | 2 | 3 |

## Tier D — Availability, props, and correlation

| ID | Hypothesis | Data required | Test and baseline | Success metric | Diff | Value |
| --- | --- | --- | --- | --- | --- | --- |
| E-36 | Replacement-level modeling beats a binary player-out flag | Lineups + on/off data | Compare both encodings | Improvement CI excludes zero | 4 | 4 |
| E-37 | Late scratches move true probability more than the market adjusts | Timestamped injury news + odds | Event study around announcements | Residual mispricing | 4 | 3 |
| E-38 | Questionable/probable tags carry graded information | Injury report history + outcomes | Model P(plays) by tag | Calibrated availability model | 3 | 4 |
| E-39 | Minutes restrictions are predictable from prior return patterns | Return-from-injury histories | Survival/duration model | Beats naive baseline | 4 | 3 |
| E-40 | Player stat distributions are better modeled as negative-binomial than Poisson | Player game logs | Fit comparison, overdispersion test | Lower log loss | 2 | 4 |
| E-41 | Prop thresholds should be read off a full distribution, not a point estimate | Player logs + prop lines | Distribution vs point-estimate comparison | Better calibrated over/under | 3 | 5 |
| E-42 | Teammate opportunity is negatively correlated (usage competition) | Game logs | Estimate correlation matrix | Significant negative correlation | 3 | 4 |
| E-43 | QB passing yards and WR receiving yards are strongly positively correlated | NFL game logs | Copula/joint model | Correlation stable out-of-sample | 3 | 4 |
| E-44 | Independent multiplication materially misprices multi-leg combinations | Joint outcomes | Compare independent vs joint simulation | Documented error magnitude | 3 | 5 |
| E-45 | Correlation estimates are stable enough to use at our sample sizes | Multi-season logs | Bootstrap correlation stability | Narrow CI, stable sign | 3 | 5 |

## Tier E — Process and infrastructure

| ID | Hypothesis | Data required | Test and baseline | Success metric | Diff | Value |
| --- | --- | --- | --- | --- | --- | --- |
| E-46 | Beta calibration outperforms Platt on our prediction distributions | Predictions + outcomes | Out-of-fold log loss comparison | Lower log loss | 1 | 3 |
| E-47 | Rolling recalibration beats a fixed calibrator | Multi-season predictions | Compare rolling vs static | Lower log loss | 2 | 3 |
| E-48 | Automated data-quality gates catch real upstream failures | Injected fault fixtures | Fault injection test | 100% detection of injected faults | 2 | 4 |
| E-49 | Entity resolution across providers is lossless | Multi-provider identifiers | Reconciliation audit | Zero unresolved entities in production path | 3 | 4 |
| E-50 | Family-wise error control changes which backlog results survive — *tooling delivered in `research_registry.significance_review()`; run it before citing any entry as a result and read the `demoted` list first* | All experiment results | Apply Benjamini-Hochberg across the registry | Corrected significance list | 1 | 5 |

## Pre-registered expected rejections

Registering these *before* testing prevents a null result from being quietly
reframed as "inconclusive, needs more data". Each should be run once, properly,
and recorded as `rejected` when it fails.

| Hypothesis | Expected outcome | Rationale |
| --- | --- | --- |
| Head-to-head record adds signal beyond ratings | Rejected | Small samples; ratings already encode strength |
| Last-three-games form beats season-long rating | Rejected | Recency weighting is noise amplification at this window |
| Social-media sentiment improves win probability | Rejected | Correlates with public backing, which is already priced |
| Public betting percentages alone predict outcomes | Rejected | Books price public bias directly |
| Revenge-game and motivation narratives predict outcomes | Rejected | Unfalsifiable as usually specified |
| Deep sequence models beat gradient boosting pregame | Rejected | Sample size regime favors trees |
| LLM-generated numeric probabilities beat statistical models | Rejected | Not a numerical estimator |

## Priority order

Run in this order. Later tiers are not worth starting until Tier A passes,
because Tier A determines whether any downstream measurement can be trusted.

1. **E-05, E-03, E-10** — integrity first. If features leak or settlements are
   revised, every other result is fiction.
2. **E-09** — the sample-size reality check. Cheap, and it determines whether
   the rest of the program is answerable. **Run; it came back rejected for
   NFL-only volume.** Its consequence outranks most of the entries below: adding
   leagues multiplies evidence per season roughly eighteenfold, which no
   modelling entry in Tier C can match. Prefer the entries that widen coverage
   (E-26, E-30, E-31 bring MLB, NHL and soccer with them) over those that deepen
   a single-league model, and re-run `power-audit --pooled` as coverage grows.
3. **E-01, E-02, E-07** — the market baseline, since everything is graded
   against it.
4. **E-21, E-24** — the simplest models that could work.
5. **E-50** — apply before reading any accumulated result as a discovery.
6. Everything else, by value/difficulty ratio.
