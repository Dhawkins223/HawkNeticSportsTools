# Sports Prediction Research Program

Research standard, findings, architecture, and falsification protocol for
HawkNetic's sports probability work.

This document is research guidance. It authorizes no execution, promotes no
model, and claims no profitability. Every gate in
`docs/probability-and-decision-policy.md` continues to apply.

## 0. Scope of the research actually performed

Stated plainly so the confidence attached to each claim below can be judged.

- A targeted literature review was conducted against current sources
  (August 2026), not a systematic review. Roughly a dozen searches across
  betting-market efficiency, de-vigging, calibration, tabular ML, and prediction
  market microstructure.
- Several primary sources were reachable only as abstracts. Where a claim rests
  on an abstract rather than a full-text read, it is marked **[abstract]**.
- Some questions returned no usable peer-reviewed evidence and only industry
  commentary. Those are marked **weak** and are *not* treated as findings.
- Two claims were generated empirically in this repository during the review and
  are reproducible from the test suite. They are marked **[measured here]**.
- No claim in this document has been validated against HawkNetic's own
  point-in-time data. Until that happens, every item is a hypothesis about this
  system, however strong the external evidence.

### Evidence grading key

| Grade | Meaning |
| --- | --- |
| **Established** | Reproduced across independent datasets and authors; not seriously disputed |
| **Strong** | Peer-reviewed, adequately powered, consistent with related work |
| **Moderate** | Peer-reviewed or preprint, but narrow in sport, period, or venue |
| **Weak** | Industry commentary, unreplicated, or subgroup-conditioned |
| **Inference** | Follows from stronger findings, not directly tested |
| **Hypothesis** | Plausible, testable, untested |

## A. Executive conclusion

The system that survives rigorous testing is smaller than the system that sounds
impressive.

1. **The market is the model to beat, and it is the primary input.** The
   de-vigged closing price is the strongest available forecast for major
   markets. A model that does not beat it out-of-sample has no independent
   value, and one that ignores it discards the best single feature it could
   have. Market price belongs in all three roles the mission asks about:
   baseline, prior, and input — but the *evaluation* role is non-negotiable and
   must stay adversarial.
2. **Calibration is the objective, not accuracy.** Selecting models by accuracy
   and selecting by calibration produce materially different systems. This
   repository already scores with Brier/log loss; the missing piece was an
   explicit calibration layer, now added.
3. **The de-vig method is a modeling decision with the same magnitude as the
   model.** [measured here] On a -900/+600 market the choice between
   proportional and Shin normalization moves fair probability by up to **2.5
   probability points** — more than twice the 1-cent minimum edge the decision
   gate requires. Any "edge" smaller than the cross-method disagreement is a
   statement about the de-vig assumption, not about the game.
4. **Complexity has to earn its place, and usually does not.** Gradient-boosted
   trees beat deep learning on tabular data of this size; well-specified
   statistical models beat both in at least one blind forecasting competition.
   Deep learning, RL, and agent swarms are not supported by current evidence for
   the probability-estimation step.
5. **Most of the engineering value is in point-in-time discipline**, not in
   models. Leakage, look-ahead in features, and retroactively corrected stats
   produce backtests that cannot be reproduced prospectively. The repository's
   existing bitemporal instincts are its most valuable asset.
6. **The honest near-term goal is a calibrated model that matches the market,**
   with any edge confined to specific, low-liquidity, high-variance corners —
   and even there, only after the sample-size arithmetic in section J.

## B. Scientific findings, ranked by evidence strength

### B1. Established

**Closing prices are the most accurate widely-available forecast, and opening
lines are measurably worse.** Price discovery is real: information accumulates
into the line as the event approaches. This is the basis for using the closing
no-vig price as the benchmark, which this repository already does in
`sports_clv.py`.

**Bookmaker margin must be removed before a price is a probability.** Raw
inverted odds sum above one. Comparing a model probability to a raw implied
probability manufactures a systematic edge equal to the margin — the most common
and most expensive error in amateur betting analysis.

**Proper scoring rules are required; win rate is not a model metric.** Brier and
log loss are strictly proper (Gneiting and Raftery). Accuracy is not, and a
model can improve accuracy while degrading the probabilities that decisions
depend on. Already enforced in `evaluation/model_validation.py`.

### B2. Strong

**Shin de-vigging produces better-calibrated probabilities than proportional
normalization.** Štrumbelj (2014) evaluates methods for converting odds to
forecasts and finds Shin probabilities more accurate than basic normalization
across five team sports; the result is echoed in Clarke's (2017) survey. The
mechanism is the favourite–longshot bias: books load proportionally more margin
onto longshots, so removing margin proportionally leaves favourites understated.
*Implemented*: `math/devig.py`, now the board default.

**Tree ensembles outperform deep learning on tabular data at this scale.**
Grinsztajn, Oyallon and Varoquaux (NeurIPS 2022) benchmark 45 datasets and find
tree-based models state-of-the-art at ~10K samples, attributing it to inductive
biases — robustness to uninformative features and the ability to learn irregular
functions. A season of one league is 1–2K games. This is squarely the regime
where trees win.

**Calibration-based model selection differs materially from accuracy-based
selection.** Walsh and Joshi (2024) select NBA betting models both ways and
report substantially different outcomes, concluding calibration is the more
important metric for probabilistic decision problems. *Caveat*: their headline
separation is expressed as ROI over one test season, which is a high-variance
statistic on a small sample — the direction is well-supported, the magnitude is
not.

### B3. Moderate

**Prediction-market calibration is not a fixed property; it varies with time to
expiry.** Moshrefi (2026) [abstract], analyzing 23 million Kalshi moneyline
trades, finds calibration parameters at their perfect-calibration reference
mid-contract but departing sharply near expiry, with the final ten minutes
fitting a step-like Prelec curve — consistent with insurance demand from traders
holding losing positions. **This is the single most directly applicable finding
to HawkNetic**, because Kalshi is the venue. It is also already reflected in
this repository's policy that time-to-expiration buckets are a required
validation dimension.

**Cross-game parlays on Kalshi are systematically overpriced relative to the
product of their leg prices, and the overpricing grows with leg count.**
Moshrefi (2026) [abstract] identifies a market-level markup applied at the
parlay-pricing stage, distinct from leg-level pricing. Implication for
`math/combo.py`: the current flat 3%-per-extra-leg penalty is the right shape
but is calibrated by assumption, not by measurement, and the paper suggests the
true markup is leg-count-dependent. Directionally, this makes buying parlays
worse, not better — it is not an edge, it is a warning.

**Odds-only models are hard to beat, and margin-removal choice is a live
research area.** Recent work (arXiv:2604.17194) [abstract] on 90,014 football
matches across five bookmakers proposes new odds-only and favourite-longshot-
adjusted methods that outperform standard multiplicative/Shin/power baselines
for most bookmakers. Two implications: the de-vig family in `math/devig.py`
should be treated as extensible, and any of its members remains an assumption to
be tested rather than a solved problem.

**Sportsbook forecasts are largely but not perfectly weak-form efficient.**
Multiple studies find residual predictability, generally too small to survive
margin and transaction costs. The correct reading is "nearly efficient with
occasional exploitable structure", not "efficient" and certainly not "beatable".

### B4. Weak — recorded, not relied upon

**Player props are less efficient than moneylines and spreads.** This is the
most commonly asserted claim in the industry and the one with the weakest
support found. Searches returned overwhelmingly promotional sources. The
*structural* argument is credible and independent of those sources: books post
far lower limits on props than on sides, which is a direct revealed-preference
signal that books consider themselves more exposed there. But lower limits also
cap the value of any edge and are how books manage it. Grade: **weak**, worth
testing, not worth assuming. See experiment E-04.

**NFL totals under-adjust for wind in the 15–20 mph band.** Borghesi's "Weather
Biases in the NFL Totals Market" is a genuine peer-reviewed starting point, and
the physical mechanism (completion percentage falling with sustained wind) is
well-documented. But the widely-circulated supporting statistic — "~17% ROI on
unders since 2003 in AFC North and NFC North outdoor games in November and
December with 9–11 mph wind" — is a textbook data-dredging artifact. It
conditions on division, month, venue type, and a three-mph wind band. With that
many cuts, a subgroup this profitable is expected under the null. Treat the
wind hypothesis as testable; treat that number as noise. See experiment E-11.

### B5. What the evidence does *not* support

Recorded here so these are not rediscovered as fresh ideas:

- Deep learning outperforming gradient boosting for pregame outcome probability
  at league-season sample sizes.
- Reinforcement learning for probability estimation. RL addresses sequential
  decisions under a reward signal; probability estimation is supervised learning
  with a proper scoring rule.
- Social-media sentiment adding signal after controlling for market price and
  team popularity. Sentiment correlates with public backing, which books already
  price; the burden of proof is on the feature.
- LLMs as numerical forecasters. Useful for extraction, parsing, entity
  resolution, and synthesis; not for producing the number.
- Monte Carlo "improving" prediction. Simulation propagates upstream
  assumptions into joint distributions. It is essential for *correlated*
  quantities and adds exactly zero information to a marginal probability.

## C. Answers to the required research questions

Answered directly, including where the answer is "unknown".

1. **How much better than closing prices can models get?** For major moneylines,
   approximately not at all; matching closing-line calibration is the realistic
   target. Any genuine edge lives before the close, in thin markets, or in
   derivative markets. Grade: strong.
2. **Which sports appear most predictable?** Predictability and *beatability*
   differ. Low-scoring, high-variance sports (NHL, soccer) have outcomes that
   are inherently hard to predict but markets that are correspondingly wide.
   High-information sports (NBA) are more predictable and more efficiently
   priced. Unknown which is more beatable on this venue without measurement.
3. **Which market types are least efficient?** Ranked by prior plausibility:
   low-limit player props > derivative/alternate lines > totals > spreads >
   moneylines. Evidence: weak for the ordering, structural for the direction.
4. **Are props less efficient than moneylines?** Probably, on the limits
   argument. Not established. See E-04.
5. **Does alternative data create persistent edge?** No general evidence found.
   Edges from alternative data are typically latency edges that decay as the
   data commoditizes.
6. **Does ML meaningfully outperform traditional statistics?** Modestly, and
   mostly through better handling of interactions and nonlinearity. Not reliably
   after market price is included as a feature, which absorbs most of the signal.
7. **Does deep learning outperform gradient boosting?** No, at these sample
   sizes. Grade: strong.
8. **Does market information dominate sports statistics?** Yes. If forced to
   choose one feature, choose the de-vigged market price. Grade: strong.
9. **How quickly is information incorporated?** Fast for public information
   (injury news moves lines in minutes). The exploitable window is a latency and
   execution problem, not a modeling problem.
10. **How much data proves a small improvement?** This is the question that
    kills most projects. See section J for the arithmetic: detecting a 1%
    edge requires order 10⁴ resolved bets. A season of one league does not
    produce that.
11. **Highest marginal-value datasets?** (1) timestamped multi-book odds
    history, (2) accurate availability/lineup data at prediction time,
    (3) opponent-adjusted efficiency, (4) tracking-derived expected stats.
12. **Which promoted indicators fail testing?** Head-to-head record, "last three
    games" trends, public betting percentages as a standalone signal, revenge
    narratives, most streak-based rules. Pre-registered as expected rejections
    in `docs/research-backlog.md`.
13. **How should uncertainty be incorporated?** Decide on the lower confidence
    bound of the edge, never the point estimate. Already enforced by the policy
    gate; the addition here is that the bound must also exceed cross-method
    de-vig disagreement.
14. **Which models calibrate best?** Well-specified GLMs and hierarchical
    Bayesian models calibrate natively; boosted trees need post-hoc calibration.
    `evaluation/calibration.py` now selects among Platt, beta, and isotonic by
    out-of-fold log loss, with identity as the default.
15. **How much regime drift occurs?** Within-season drift is mostly roster and
    role change; between-season drift adds rule and tactical change. Magnitude
    unmeasured here — see E-27.
16. **What survives comparison against closing probabilities?** Unknown for this
    system. That is precisely what the validation program exists to determine,
    and the honest current answer for HawkNetic is "nothing yet".

## D. Data hierarchy

### Tier 1 — Essential (do not operate without)

| Data | Why | Leakage risk |
| --- | --- | --- |
| Timestamped odds from multiple books | The baseline, the prior, and the benchmark | **High** — closing odds must never reach a pregame model |
| Canonical schedule with start times | Defines the prediction cutoff | Low |
| Final scores / settlement | The label | **Critical** — outcome fields already blocked by `TARGET_LEAKAGE_FIELDS` |
| Team identity and entity resolution | Everything joins on it | Low |
| Point-in-time snapshot timestamps | Makes backtests reproducible | **Critical** |

### Tier 2 — High value

Opponent-adjusted efficiency ratings; player availability and confirmed lineups
at prediction time; rest and schedule congestion; starting pitcher (MLB) and
starting goalie (NHL), which are the largest single-player effects in team
sports; venue and roof status; expected-stat aggregates (xG, EPA, Statcast
derivatives).

### Tier 3 — Experimental (validate before use)

Tracking-derived features; referee assignment; weather beyond wind and
precipitation; coaching tendency metrics; line-movement features conditional on
the final price; travel distance and time-zone change.

### Tier 4 — Unsupported or negative

Social sentiment; public betting percentages alone; head-to-head history beyond
what ratings capture; short-window "form" streaks; narrative/motivation
variables; LLM-generated numeric forecasts.

## E. Mathematical architecture

Fair price from probability, before fees and uncertainty:

```text
decimal odds   = 1 / p
contract price = 100 * p cents
```

Margin removal, implemented in `math/devig.py` (S = booksum = Σ πᵢ):

```text
multiplicative   pᵢ = πᵢ / S
additive         pᵢ = πᵢ - (S - 1) / n
power            pᵢ = πᵢ^k                      solve k for Σp = 1
shin             pᵢ = (√(z² + 4(1-z)πᵢ²/S) - z) / (2(1-z))   solve z for Σp = 1
odds ratio       pᵢ = OR·πᵢ / (1 - πᵢ + OR·πᵢ)  solve OR for Σp = 1
```

Net edge for a YES contract, unchanged from existing policy:

```text
edge = 100·p - ask - fee - slippage
```

**Amendment proposed by this research.** The edge must clear the de-vig
assumption as well as the price:

```text
edge_lower_bound > 0
edge_lower_bound > 100 · devig_method_disagreement
```

[measured here] Cross-method disagreement, computed by
`math.devig.method_disagreement` and reproduced in `tests/test_devig.py`:

| Market | Booksum | Proportional (fav) | Shin (fav) | Max method gap |
| --- | --- | --- | --- | --- |
| -110 / -110 | 1.0476 | 0.5000 | 0.5000 | **0.00 pts** |
| -300 / +250 | 1.0357 | 0.7241 | 0.7321 | **1.22 pts** |
| -900 / +600 | 1.0429 | 0.8630 | 0.8786 | **2.51 pts** |
| -2000 / +1200 | 1.0293 | 0.9253 | 0.9377 | **2.07 pts** |

On balanced markets the choice is irrelevant. On skewed markets it exceeds the
decision threshold. The board now publishes both the method used and the
disagreement (`no_vig_method`, `no_vig_method_disagreement`).

## F. Model architecture

Ordered by what the evidence supports, not by sophistication.

```text
Layer 0  Market baseline      de-vigged consensus price          [always on]
Layer 1  Rating model         Elo / Bradley-Terry / Poisson      [per sport]
Layer 2  Feature model        gradient-boosted trees, market price included
Layer 3  Calibration          out-of-fold selected, identity default
Layer 4  Uncertainty          interval per prediction
Layer 5  Decision             lower-bound edge vs price and vs devig spread
```

Layers 1 and 2 must each independently beat Layer 0 out-of-sample or they do not
ship. Simulation is added only where correlation is required (player props,
same-game combinations), and is understood to propagate assumptions rather than
create information.

**On the proposed multi-agent architecture** (Data/Injury/Market/Statistical/ML/
Simulation/Calibration/Falsification/Meta agents): the *decomposition* is sound
as a module boundary map, and this repository already implements most of it as
deterministic services. Making them LLM agents is not supported. Probability
estimation, simulation, calibration, and backtesting must be deterministic and
reproducible; an LLM in that path destroys reproducibility for no accuracy gain.
LLMs are appropriate for injury-text extraction, entity resolution, source
discovery, and anomaly explanation — all of which produce *inputs* that
deterministic code then validates.

## G. Validation system

1. **Temporal splits only.** Chronological train/validation/test, walk-forward
   for stability. Random k-fold is invalid for forecasting; the one exception in
   this codebase is calibrator selection, which uses *contiguous* folds
   (`_contiguous_folds`) precisely to preserve ordering.
2. **Leakage audit before every result.** Any feature whose value could change
   after the prediction timestamp is disqualified. Closing odds are the most
   dangerous single feature in this domain: they are enormously predictive and
   completely unavailable at pregame prediction time.
3. **Baseline ladder.** Every model reports against: base rate → Elo → logistic
   regression → market open → market current → **market close**. Beating the
   first four means nothing on its own.
4. **Prospective shadow test.** Freeze, timestamp, store immutably, wait. A
   backtest is a hypothesis; only the shadow test is evidence.
5. **Registry.** Every experiment recorded in `research_registry.py`, whose
   hash chain makes post-hoc rewriting detectable rather than merely
   discouraged, and which refuses to record an `accepted` verdict whose
   confidence interval contains zero.

## H. Calibration framework

Implemented in `evaluation/calibration.py`.

- **Metrics**: ECE, MCE, calibration slope and intercept, reliability buckets,
  log loss. Slope below 1 is the signature of overconfidence.
- **Calibrators**: Platt (small samples), beta (can represent identity exactly,
  so recalibrating an honest model does not distort it), isotonic (gated behind
  1,000 rows per Niculescu-Mizil and Caruana).
- **Selection rule**: out-of-fold log loss with identity as a candidate.
  Identity wins ties and wins by default. *A model that is already calibrated is
  left alone* — verified in `tests/test_calibration.py`.
- **Discipline**: calibration is fit on rows disjoint from the rows used to
  measure it. Fitting and scoring on the same predictions flatters everything.
- **Kalshi-specific**: calibrate within time-to-expiry buckets, per Moshrefi
  (2026). A single global calibrator will average across a regime that the data
  says is not constant.

## I. Market-comparison framework

CLV is the benchmark, with its limits stated. Beating the close is evidence that
predictions carry information the market later agreed with. It is **not** proof
of profitability, and the industry claim that it is amounts to assuming the
conclusion. Specifically:

- CLV is measured against a price that may not have been available at the
  claimed size.
- CLV against a soft book's close is much weaker evidence than against a sharp
  book's or an exchange's close.
- Positive CLV with negative realized return over a large sample means the CLV
  measurement is wrong, not that variance explains it.

`sports_clv.py` already grades recorded prices against the last pre-start quote
and correctly refuses to call the result profit. That framing is right and
should not be softened.

## J. The sample-size problem

The constraint that determines whether this project can succeed at all.

To detect a true edge of size *e* on roughly even-money markets, required
resolved bets scale as ~1/e². Order-of-magnitude:

| True edge | Bets to detect at 95% confidence |
| --- | --- |
| 5% | ~1,000 |
| 2% | ~6,000 |
| 1% | ~25,000 |

An NBA season is ~1,300 games. A model claiming a 1% edge cannot be validated in
one season, or two. Consequences that must be designed for, not discovered
later:

- Report intervals always; a point estimate of ROI over a few hundred bets is
  noise.
- Prefer CLV as the leading indicator *because* it converges faster than
  realized return — while remembering it is an indicator, not the outcome.
- Correct for multiple testing across every hypothesis in the backlog. Fifty
  experiments at α=0.05 produce ~2.5 false discoveries by construction.
- Treat correlated observations (same game, same slate) as fewer effective
  observations than the raw count.

## K. Monitoring and retirement

Monitor continuously: rolling Brier and log loss versus market baseline;
calibration slope drift; ECE by time-to-expiry bucket; prediction distribution
shift; feature drift; source freshness and outage; per-league and per-market
performance.

Quantitative stop conditions:

| Condition | Action |
| --- | --- |
| Calibration slope outside [0.8, 1.25] over 500 rows | Recalibrate |
| Brier skill vs market negative over 500 rows | Down-weight |
| Brier skill vs market negative over 1,000 rows | Disable |
| Feature source unavailable or stale | Withhold predictions (no fallback) |
| Drift detected in input distribution | Re-fit, re-validate before re-enabling |

The existing `WAIT_FOR_DATA` state is the correct response to missing inputs. A
model that degrades gracefully by guessing is worse than one that declines.

## L. Implementation roadmap

| Phase | Work | Exit criterion |
| --- | --- | --- |
| 0 | Data audit; point-in-time integrity; entity resolution | Every feature has a provable availability timestamp |
| 1 | Baselines: base rate, Elo, logistic | Beats base rate on walk-forward |
| 2 | Market benchmark: de-vig family, CLV, closing comparison | Market baseline reproducible; **complete** |
| 3 | Calibration layer | Out-of-fold selection live; **complete** |
| 4 | Player models and availability | Minutes/usage distributions validated |
| 5 | Feature model with market price included | Beats market baseline out-of-sample, or is rejected and recorded |
| 6 | Correlation and simulation | Joint distributions calibrated on realized correlations |
| 7 | Prospective shadow validation | ≥ 6 months, ≥ 1,000 predictions, positive CLV with interval excluding zero |
| 8 | Production monitoring | Drift and retirement gates automated |

Phases 2 and 3 are delivered by this change. Phase 7 cannot be shortened.

## M. Component ranking

Scores are 0–100. Predictive value and evidence strength are the axes that
matter; difficulty and risk are the costs.

| Component | Pred. value | Evidence | Data quality | Difficulty | Leakage risk | Overfit risk | Priority |
| --- | --- | --- | --- | --- | --- | --- | --- |
| De-vigged market baseline | 95 | 95 | 90 | 20 | 85 | 5 | **Critical** |
| Point-in-time feature store | 85 | 90 | 95 | 70 | 95 | 5 | **Critical** |
| Probability calibration layer | 80 | 85 | 90 | 30 | 20 | 25 | **Critical** |
| Proper scoring + intervals | 80 | 95 | 95 | 25 | 10 | 5 | **Critical** |
| Shin/power de-vig family | 70 | 80 | 90 | 25 | 10 | 10 | **Critical** |
| Walk-forward validation | 75 | 95 | 90 | 40 | 90 | 10 | **Critical** |
| Elo / rating baseline | 60 | 90 | 95 | 20 | 10 | 15 | High |
| Availability + lineup model | 70 | 70 | 60 | 75 | 70 | 35 | High |
| Opponent-adjusted efficiency | 60 | 80 | 85 | 45 | 40 | 25 | High |
| Experiment/negative registry | 55 | 60 | 95 | 20 | 5 | 5 | High |
| Gradient-boosted feature model | 55 | 75 | 80 | 50 | 60 | 60 | High |
| Starting pitcher / goalie | 65 | 75 | 85 | 35 | 45 | 20 | High |
| Correlation-aware simulation | 50 | 60 | 60 | 80 | 30 | 55 | Medium |
| Time-to-expiry calibration buckets | 55 | 65 | 80 | 35 | 25 | 30 | Medium |
| Tracking-derived features | 45 | 55 | 70 | 85 | 50 | 55 | Medium |
| Referee tendencies | 30 | 35 | 60 | 40 | 30 | 75 | Medium |
| Weather (wind, precipitation) | 35 | 45 | 80 | 30 | 35 | 60 | Medium |
| Line-movement features | 35 | 40 | 70 | 55 | **90** | 65 | Low |
| Deep learning / sequence models | 20 | 25 | 70 | 85 | 50 | 85 | **Reject** |
| Reinforcement learning | 10 | 10 | 60 | 90 | 40 | 90 | **Reject** |
| Social sentiment | 10 | 15 | 40 | 60 | 45 | 85 | **Reject** |
| LLM numeric forecasting | 5 | 10 | 50 | 30 | 60 | 90 | **Reject** |

## N. Red-team review

Assume the architecture above is wrong.

**1. The de-vig change could make things worse.** Shin is better *on average
across five team sports in one 2014 study*. This repository's markets are Kalshi
event contracts and US sportsbook odds in 2026. Shin's z parameter is a fitted
insider-trading share, and if the two prices come from different books or
different timestamps, z absorbs the mismatch and returns a confident wrong
answer. *Survives with conditions*: the default is defensible, the disagreement
metric is published rather than hidden, and E-01 must test it on this system's
own data before the improvement is claimed rather than assumed.

**2. Publishing a disagreement metric invites its misuse.** An operator may read
"edge exceeds disagreement" as "edge is real". It is a necessary condition, not
a sufficient one. The gate language must stay negative: it disqualifies
candidates, it never qualifies them.

**3. Calibration on non-stationary data is fitting the past.** A calibrator
fitted on last season corrects last season's miscalibration. If drift is
material, calibration transfers poorly and can *increase* error. Mitigations:
identity is the default; selection is out-of-fold; calibrators are refit on a
rolling window; the Kalshi finding that calibration varies with time-to-expiry
implies a *global* calibrator is misspecified from the start.

**4. The parlay finding does not license parlay trading.** Overpricing that
grows with leg count means parlays are worse than their legs. The correct use of
this finding is defensive — it argues for tightening `combo_safety`, not for
building a parlay product. Anyone reading it as an opportunity has the sign
backwards.

**5. The sample-size arithmetic may be fatal to the whole program.** If the
attainable edge is ~1%, validation needs ~25,000 resolved predictions. At a few
hundred usable candidates a month, that is years. This is the strongest argument
against the project as an edge-finding exercise, and it does not have a clever
solution. It survives only by redefining success: a well-calibrated probability
system with honest uncertainty is valuable as research infrastructure
independent of whether it ever demonstrates edge.

**6. Survivorship and selection bias in the literature.** Published betting
strategies are the ones that worked on the data the author had. Failed
strategies are rarely published. Every effect size quoted above should be
mentally discounted, and the weather subgroup result discarded entirely.

**7. Infrastructure risk is understated.** Odds APIs rate-limit, change schemas,
and revise history. A provider silently backfilling corrected odds destroys
point-in-time integrity without any error surfacing. The append-only raw payload
design already in place is the right defense; the hash chain now extends it to
research conclusions.

**8. This document is itself a multiple-testing machine.** Fifty backlog
experiments at α=0.05 yield ~2.5 spurious "discoveries". Without correction, the
registry will fill with false positives that look rigorous because they have
confidence intervals. The registry's interval-excludes-zero rule is necessary
but not sufficient; family-wise correction is a required addition (E-50).

### Revisions adopted after red-teaming

- The de-vig default ships **with** the disagreement metric published, not
  silently. Done.
- The edge gate gains a second necessary condition (edge > de-vig
  disagreement). Proposed in section E, pending E-01.
- Calibration defaults to identity and must beat it out-of-fold. Done.
- Calibration must be bucketed by time-to-expiry on Kalshi. Backlog E-06.
- Multiple-testing correction is mandatory before any registry entry is read as
  a discovery. Backlog E-50.
- Success is redefined as calibration quality, not demonstrated edge.

## References

- Štrumbelj, [On determining probability forecasts from betting odds](https://www.sciencedirect.com/science/article/abs/pii/S0169207014000533), International Journal of Forecasting 30(4), 2014.
- Clarke, [Adjusting bookmaker's odds to allow for overround](https://outlier.bet/wp-content/uploads/2023/08/2017-clarke-adjusting_bookmakers_odds.pdf), 2017.
- Grinsztajn, Oyallon and Varoquaux, [Why do tree-based models still outperform deep learning on typical tabular data?](https://arxiv.org/abs/2207.08815), NeurIPS 2022.
- Walsh and Joshi, [Machine learning for sports betting: should model selection be based on accuracy or calibration?](https://arxiv.org/abs/2303.06021), 2023.
- Moshrefi, [Prices, Probabilities, and Parlays: Systematic Bias in Sports Prediction Markets](https://arxiv.org/abs/2607.14430), 2026.
- [Forecast Sports Outcomes under Efficient Market Hypothesis](https://arxiv.org/abs/2604.17194), 2026.
- Niculescu-Mizil and Caruana, [Predicting Good Probabilities With Supervised Learning](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf), ICML 2005.
- Kull, Silva Filho and Flach, [Beta calibration](https://proceedings.mlr.press/v54/kull17a.html), AISTATS 2017.
- Gneiting and Raftery, [Strictly Proper Scoring Rules, Prediction, and Estimation](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf), JASA 2007.
- Borghesi, [Weather Biases in the NFL Totals Market](https://www.researchgate.net/publication/24071150_Weather_Biases_in_the_NFL_Totals_Market).
- Winkelmann, Ötting, Deutscher and Makarewicz, [Are Betting Markets Inefficient? Evidence From Simulations and Real Data](https://journals.sagepub.com/doi/10.1177/15270025231204997), 2024.
