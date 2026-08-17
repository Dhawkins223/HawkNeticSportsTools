# Raw Payload Retention

## Why this exists

`raw.source_payloads` stores one full response body per collection cycle. Kalshi
ingestion runs every five minutes, so the table grows without bound. It filled
the staging volume outright, and production has been growing at roughly 230 MB
per day. See `docs/staging-sports-worker-verification.md` for the measurements.

## What it does and does not remove

Deleting those rows is not an option. `core.markets`, `core.market_observations`,
`core.events`, `core.series`, `core.trades`, `core.settlements`,
`core.orderbook_snapshots`, and `raw.rejected_records` all carry foreign keys
into `raw.source_payloads`, and the project's integrity contract treats a
payload's content hash as evidence that a collection happened and what it
contained.

So retention prunes the **body** and keeps everything that proves the collection:

| Preserved | Removed |
| --- | --- |
| The row and its id | The payload body |
| `batch_id` and its batch lineage | |
| `source`, `entity_type`, `source_identifier` | |
| `observed_at`, `received_at` | |
| `content_hash` | |
| `parser_version` | |

The body is replaced by a tombstone recording the prune time, the original byte
size, and the content hash, so a pruned row stays self-describing. Collection
dedup and import lineage compare the `content_hash` column and never re-hash the
body, so pruning disturbs neither.

**The body itself is not recoverable.** Take a backup first.

## Guards

- The window has a hard floor of seven days. A shorter request is refused with
  `RetentionWindowTooShort` rather than honoured.
- The newest payload per `(source, entity_type)` is never a candidate at any
  window. That is the row the dashboard reads for its current snapshot, so the
  guard means retention can never blank the live view.
- Every run defaults to a dry run. Nothing is written without `--apply`.
- `--limit` bounds a single pass, and the result reports how much remains
  eligible, so a large backlog can be worked through in controlled batches.

## Run it as a worker

Storage is a collection concern, not an occasional chore: raw payload bodies
accumulate on every cycle of every collector, and a volume that fills stops all
of them. `raw-retention` is a worker role, deployed like any other:

```text
HAWKNETIC_SERVICE=raw-retention
```

It runs hourly and applies by default — a retention worker that only ever
reported would leave the volume filling. A bounded prune is cheap, and the worker
guarding the volume should not leave a long blind window after every deploy: a
restart forfeits the rest of the current cadence bucket, so a six-hour cadence
cost six hours of no measurement every time it was redeployed. The same guards
still hold: the window floor, the newest-payload-per-source exemption, and the
per-pass limit.

| Variable | Default | Meaning |
| --- | --- | --- |
| `RAW_RETENTION_DAYS` | 30 | Window in days. Anything under the seven-day floor is raised to it. Production runs 10 — see the arithmetic below. |
| `RAW_RETENTION_BATCH_LIMIT` | 5000 | Maximum bodies pruned in one pass. |
| `RAW_RETENTION_DRY_RUN` | false | Set true to report without writing. |

Each pass reports:

| Field | Meaning |
| --- | --- |
| `payload_bodies_pruned` | Bodies replaced by a tombstone this pass |
| `reclaimable_bytes` | Space those bodies occupied |
| `still_eligible` | Bodies past the window this pass did not reach |
| `retained_span_days` | How many days of payloads the table holds |
| `oldest_received_at` | Age of the oldest retained payload |
| `window_bites` | Whether the window can reach anything at all |
| `database_bytes` + `largest_relations` | Where the space actually is |

A pass with nothing left to prune is the healthy steady state and is recorded as
`no_material_change`, not a failure. A pass with `window_bites: false` is
different and worth acting on: the window is wider than the data's own age, so
this configuration will prune nothing until the table ages into it — which on a
bounded volume may never happen.

Point the service's config-as-code path at `railway.worker.json` like every other
worker, so it carries no pre-deploy migration.

## Usage

```bash
# Where the space is going, and how much is eligible.
PYTHONPATH=src python -m kalshi_research_bot raw-retention --report-only

# Dry run against production's ten-day window.
PYTHONPATH=src python -m kalshi_research_bot raw-retention --older-than-days 10

# Apply, one source at a time, in bounded passes.
PYTHONPATH=src python -m kalshi_research_bot raw-retention \
    --older-than-days 10 --source kalshi_public_api --limit 2000 --apply
```

## Reclaiming space on a full volume

Pruning frees space *inside* the table. PostgreSQL reuses it for new rows, but it
does not return it to the filesystem without a `VACUUM FULL`, and `VACUUM FULL`
needs free space of its own to rewrite the table. On a volume that is already at
its ceiling there is nothing to rewrite into.

The workable order on a full volume is:

1. Raise the volume size first. Nothing else can succeed while writes fail.
2. Back up.
3. Prune in bounded passes, verifying counts between them.
4. `VACUUM (ANALYZE) raw.source_payloads` to make the freed space reusable.
5. Only run `VACUUM FULL` if the space must return to the filesystem, and only
   with headroom equal to the table's current size.

After that, ordinary autovacuum plus a scheduled prune keeps the table flat
without further intervention.

## Measured cost of a collector

One `sports-research` cycle stores about 2.46 MB of raw payload bodies — fifteen
ESPN summary responses plus one scoreboard. At its hourly cadence that is roughly
**59 MB per day**, on top of the ~230 MB per day production already grows.

That is the case for running retention alongside a new collector rather than
after it: each collector added without a retention window shortens the runway,
and `raw.source_payloads` is where nearly all of the mass sits.

## Choosing a window: it is arithmetic, not taste

A retention window sets the table's steady-state size:

```text
steady_state_size  =  daily_growth  x  window_days
```

That makes most windows impossible rather than merely generous. Production
measured on 2026-08-17:

| Relation | Size | Share |
| --- | ---: | ---: |
| `raw.source_payloads` | 1.98 GB | 67% |
| `core.markets` | 0.42 GB | 14% |
| `core.events` | 0.28 GB | 9% |
| `app.prediction_rejections` | 0.10 GB | 3% |
| `core.market_observations` | 0.10 GB | 3% |
| `app.prediction_logs` | 0.05 GB | 2% |
| **Database total** | **2.95 GB** | |

At roughly 230-280 MB per day, on a 5 GB volume:

| Window | Steady-state raw | Plus ~1 GB core | Verdict |
| ---: | ---: | ---: | --- |
| 30 days | ~6.7 GB | ~7.7 GB | impossible — exceeds the volume |
| 14 days | ~3.1 GB | ~4.1 GB | 82% full, no room for growth |
| 10 days | ~2.2 GB | ~3.2 GB | workable |
| 7 days | ~1.6 GB | ~2.6 GB | ample headroom |

Production runs a ten-day window. A thirty-day window was tried first and pruned
nothing — not because retention was broken, but because nothing was thirty days
old yet and never would be: the volume fills first. A window that never becomes
eligible is indistinguishable from having no retention at all.

Compute the window from the volume and the measured growth rate. Widen it only
after the volume grows, and re-measure with
`raw-retention --report-only` rather than assuming.

## What pruning does and does not do to disk usage

Pruning frees space *inside* the table for PostgreSQL to reuse. Reported disk
usage does not fall; it stops rising. Expect a plateau, not a drop. Returning
space to the filesystem needs `VACUUM FULL`, which needs free space of its own —
see the ordering above.
