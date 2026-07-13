# Research Platform Hardening

Status date: 2026-07-12

This phase adds research infrastructure only. It does not change live slip-selection rules, train an ML model, place orders, upload orders, or establish a profitability claim.

## Probability Validation

`evaluation/model_validation.py` provides a category-scoped evaluation framework with:

- chronological train/validation/test splits (60/20/20);
- expanding-window walk-forward folds;
- market-implied and historical-base-rate baselines;
- supplied category-model probability evaluation;
- training-only histogram calibration;
- validation-selected market/model ensembles;
- Brier score, log loss, calibration error, accuracy, 95% intervals, and calibration buckets;
- deterministic dataset versions plus model and feature versions;
- target-field and future-feature timestamp leakage rejection;
- explicit states: `experimental`, `insufficient_sample`, `failed_validation`, `baseline_only`, `validated_research`, `drift_detected`, and `disabled`.

`model-evaluate` evaluates Kalshi categories, crypto, and sports separately. It never pools them into one generic model. A challenger is `validated_research` only when its untouched test set is large enough and it improves both Brier score and log loss over market probability without materially worsening calibration.

Current evidence remains research-only. The generated report is `data/model_validation_audit.txt` (with a JSON companion). Existing live rules are not promoted from this report.

## Execution Simulation

`evaluation/execution.py` supports conservative paper execution:

- current top-of-book and depth levels;
- market and limit orders;
- full, partial, no-fill, and rejected outcomes;
- explicit source and order timestamps;
- market closure and expiration checks;
- position and capital limits;
- adverse signal-to-order movement and price ceilings;
- versioned maker/taker fee assumptions;
- gross and net settlement accounting.

The default general fee formula is versioned as `kalshi_general_2026-02-05`. Special-product schedules must be configured and validated separately. Historical Kalshi rows do not contain full depth, so the serious return audit uses one-contract top-of-book simulation and states that limitation rather than inventing depth.

## Return Accounting

Run:

```powershell
$env:PYTHONPATH='src'
python -m kalshi_research_bot kalshi-return-audit --run-id stage3a_20260703_170707
```

The audit reports raw rows, market-level de-duplication, event-level correlation adjustment, portfolio limits, winners, losses, average win/loss, entry price, gross return, fees, slippage, net return, and price/category/confidence/expiration/liquidity buckets.

High accuracy is not treated as economic edge. For a contract entered at 90 cents, a win earns about 10 cents before costs while a loss loses about 90 cents. The report calculates the observed average-price break-even accuracy and compares it with actual accuracy.

## Exposure Accounting

`evaluation/exposure.py` preserves raw predictions and creates a separate portfolio decision for each one. It detects or limits:

- repeated market-side exposure;
- multiple markets on one event;
- opposing positions on one market;
- event, category, underlying, and correlation-group concentration;
- maximum position and simulated portfolio capital.

Both raw and exposure-adjusted results remain available. Nothing is silently deleted.

## Known Research Blockers

- Kalshi public tiers remain market-price screens, not independent validated probabilities.
- Crypto's current challenger fails the market/neutral baseline on the untouched test set.
- Legacy sports rows include source timestamps one second after their recorded prediction timestamp; collection timing is fixed for new rows, but contaminated history remains immutable and blocks sports validation until enough clean rows accumulate.
- Historical order-book depth is unavailable, so historical partial-fill estimates cannot be proven.
- A positive probability score alone would not establish tradable profitability; cost-aware portfolio evidence is also required.

## Guardrails

- No live trading or account-write code is enabled.
- No model state changes live prediction rules.
- Rejected, unresolved, stale, future-stamped, or leakage-contaminated rows cannot enter validation metrics.
- `validated_research` is not equivalent to `production_ready` or profitable.
