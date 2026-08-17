# Probability and Decision Policy

## Current research status

HawkNetic is a research-only probability system. A high displayed probability is not enough to create a research candidate, and no output authorizes execution.

The current sports collector records bookmaker-implied probabilities as `baseline_only` observations. It does not yet have an independently validated sports outcome model. Those rows are useful for data collection, settlement, calibration research, and baseline comparison, but their decision status is `track_only`.

## Probability quality

Models are compared with proper scoring rules rather than raw accuracy alone:

- Brier score measures squared probability error.
- Log loss strongly penalizes confident wrong predictions.
- Calibration error checks whether events predicted near a probability occur near that rate.
- Accuracy and Wilson confidence intervals remain descriptive, not promotion criteria by themselves.
- Brier skill score reports improvement relative to the market-price baseline.

Evaluation uses chronological train, validation, and test periods. Walk-forward folds may be used for stability checks. Future observations, settlements, feature timestamps after the prediction cutoff, mixed model versions, and mixed feature versions fail validation.

A challenger can enter `validated_research` only when its held-out paired Brier and log-loss improvements over the market baseline are positive and the lower bounds of both 95% improvement intervals are above zero. The held-out sample must also meet the configured threshold and calibration cannot materially degrade.

## Market baseline construction

A posted price is not a probability until the bookmaker's margin is removed, and
how it is removed changes the answer. `kalshi_research_bot.math.devig` implements
five methods — multiplicative, additive, power, Shin, and odds ratio — and the
sports board defaults to Shin, which removes proportionally more margin from
longshots than proportional normalization does.

The board publishes the method it used (`no_vig_method`) and the largest
disagreement between methods for any selection in that market
(`no_vig_method_disagreement`). This matters at decision time: on a -900/+600
market the method choice alone moves fair probability by roughly 2.5 probability
points, which exceeds the 1-cent minimum edge below. An estimated edge smaller
than the cross-method disagreement is a statement about the de-vig assumption,
not about the game.

Research finding E-01/E-02 in `docs/research-backlog.md` must confirm this on
HawkNetic's own point-in-time data before the disagreement figure is treated as
a calibrated threshold rather than a warning.

## Probability calibration

`kalshi_research_bot.evaluation.calibration` provides expected and maximum
calibration error, calibration slope and intercept, and three calibrators:
Platt, beta, and isotonic.

Calibrator selection is adversarial by default. `select_calibrator` scores every
candidate — including the identity map, meaning no calibration at all — by
out-of-fold log loss on contiguous, order-preserving folds, and keeps identity
unless a calibrator genuinely beats it. Samples below the configured minimum are
not calibrated, and isotonic regression is withheld until there are enough rows
to constrain it. Calibration is fit on rows disjoint from the rows used to
measure it.

## Separate market segments

Validation evidence is not transferable across materially different products. Models must be evaluated separately when the outcome process or market construction differs, including:

- single-event contracts versus cross-game combinations;
- moneylines, spreads, totals, and player props;
- sports, crypto, weather, economics, and event markets;
- materially different time-to-expiration buckets.

The runtime decision gate rejects a model whose validated product or horizon does not match the current market. Recent Kalshi research suggests calibration can differ by product and time to expiry, so this repository treats those dimensions as required validation context rather than assuming one universal model.

## Research-candidate gate

`BET_CANDIDATE` is a historical name for a research candidate. It remains paper-only and always has `execution_allowed=false`.

Every candidate must pass all of these gates:

1. The source is fresh, the market is open, and the record is not rejected, blocked, unresolved, or duplicated.
2. The model state is `validated_research` with at least 100 held-out test rows.
3. Model, feature, and dataset versions are recorded.
4. The model probability has a per-prediction confidence interval.
5. The validated product and horizon match the current contract.
6. The quoted spread is no wider than 12 cents.
7. Fee and slippage estimates are present; ROI remains unavailable without them.
8. Point-estimate net edge is at least 1 cent per contract.
9. Lower-confidence-bound net edge is at least 0.5 cents per contract.

The net edge calculation for a YES contract is:

```text
100 × probability − ask price − estimated fee − estimated slippage
```

The same calculation is repeated with the lower confidence bound. A positive point estimate with a non-positive lower-bound edge is `NO_BET`, not a candidate.

When every hard condition passes, the system may report a quarter-Kelly research sizing fraction capped at 1% of simulated bankroll. This is a conservative risk-control default, not evidence of profitability and not permission to place an order.

## Decision states

- `BET_CANDIDATE`: all research gates passed; execution remains disabled.
- `NO_BET`: a hard validation, market, uncertainty, product, spread, or edge rule failed.
- `WAIT_FOR_DATA`: the otherwise eligible evaluation lacks fresh model, interval, price, spread, fee, or slippage data.

Missing model validation is a hard `NO_BET`. The system does not wait indefinitely and does not promote market-implied probability into an independent model probability.

## Data ordering and lineage

The evaluation path is ordered to prevent contamination:

```text
raw source evidence
→ normalized observations
→ point-in-time feature snapshot
→ versioned prediction
→ later settlement
→ separate prediction outcome
→ held-out evaluation
→ research decision gate
```

Prediction values are immutable after creation. Outcomes are stored separately. Rejected, blocked, unresolved, stale, and duplicate rows never enter model-performance or decision metrics.

## References

- The research program behind these rules, its evidence grading, and its red-team review are in [docs/sports-prediction-research-program.md](sports-prediction-research-program.md); open experiments are in [docs/research-backlog.md](research-backlog.md).
- Gneiting and Raftery, [Strictly Proper Scoring Rules, Prediction, and Estimation](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf).
- Štrumbelj, [On determining probability forecasts from betting odds](https://www.sciencedirect.com/science/article/abs/pii/S0169207014000533).
- Kull, Silva Filho, and Flach, [Beta calibration](https://proceedings.mlr.press/v54/kull17a.html).
- Kelly, [A New Interpretation of Information Rate](https://onlinelibrary.wiley.com/doi/abs/10.1002/j.1538-7305.1956.tb03809.x).
- Gupta, Podkopaev, and Ramdas, [Distribution-Free Binary Classification: Prediction Sets, Confidence Intervals and Calibration](https://arxiv.org/abs/2006.10564).
- Walsh and Joshi, [Machine learning for sports betting: should model selection be based on accuracy or calibration?](https://arxiv.org/abs/2303.06021).
- Chu, Wu, and Swartz, [Modified Kelly criteria](https://doi.org/10.1515/jqas-2017-0122).
- [Kalshi sports prediction market calibration preprint](https://arxiv.org/abs/2607.14430). Treat this recent preprint as a hypothesis source that requires validation on HawkNetic's own point-in-time data.
