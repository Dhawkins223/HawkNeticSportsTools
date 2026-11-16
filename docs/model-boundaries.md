# Model boundaries

This public codebase provides research tools, price comparisons, and experiment
infrastructure. Its example model blend has no validated category-selection
contract. A generic sport plan or a more recent filename does not identify the
best forecasting model for a particular target.

| Path | Role | Model-selection status |
| --- | --- | --- |
| `demo`, `run --baseline-only`, `ResearchPipeline` | Local Poisson/Elo/market-prior baseline experiments | Explicitly unvalidated; canonical selection unresolved |
| `research-model-refresh` worker | Versioned, zero-edge market baseline and coverage records | Baseline only; no independent model edge or model promotion |
| `sports-ratings`, `market-blend`, `research-registry` | Walk-forward experiments and recorded research verdicts | Track-only evidence; no automatic promotion |
| Canonical forecasting workflow | Select a model by sport, target, horizon, and validation scope | Requires its own current registry and evidence admission |

## Local baseline commands

```sh
PYTHONPATH=src python -m kalshi_research_bot demo
PYTHONPATH=src python -m kalshi_research_bot run \
  --games examples/sample_games.json --quotes examples/sample_quotes.json \
  --baseline-only
```

`run` without `--baseline-only` exits 2 before loading input files or touching the
database. Programmatic calls similarly require
`ResearchPipeline(baseline_only=True)`. This acknowledgement enables the example
calculation; it does not certify input freshness, calibration, cutoff integrity,
or model superiority. The example supports home-win calculations only.

Each baseline prediction and resulting edge carries
`model_status=unvalidated_baseline`, `canonical_model_selection=unresolved`, and
its information mode. When a market prior participates, the result is explicitly
`market_conditioned`. The fixed blend weights have no category-level promotion
evidence. No supported input signals means no forecast; the former silent 50%
fallback is removed.

Supplied recognized signals must be finite numbers, excluding booleans. Expected
goals must be nonnegative and market probabilities must fall within `[0, 1]`.
Nulls, malformed values, nonfinite arithmetic and component overflow block the
experiment without generating a probability. A valid but incomplete Poisson or
Elo pair is explicitly noted as skipped if another supported signal exists;
without one, no forecast is generated. Zero remains a valid value.

`demo --save-db` and `run --baseline-only --save-db` exit 2. The research ledger
has no admission contract for these examples, so the CLI does not persist them
as fresh research evidence. Existing records remain intact.

## Using a validated specialist

Resolve the canonical model registry in the private forecasting environment for
the exact sport, target, pregame/live horizon, competition, and evaluation scope.
Record its selected model identity, registry revision, evidence reference, input
manifest hashes, and forecast cutoff. Honor missing or blocked routes. Keep
market data separate until the market-blind forecast is locked.

This repository does not download, embed, or publicly publish the private model
registry, forecast records, or validation datasets. There is no implicit fallback
from an unavailable specialist to `ModelBot`. Any future adapter must consume an
explicit, verified forecast contract and preserve that provenance, with a
reviewed admission rule before persistence or display as validated output.

These changes affect the example CLI path. They do not deploy a model, modify
the database schema, replace the hosted worker, or claim the dashboard runs the
private forecasting system.
