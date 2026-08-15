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

## Usage

```bash
# Where the space is going, and how much is eligible.
PYTHONPATH=src python -m kalshi_research_bot raw-retention --report-only

# Dry run against the default 30-day window.
PYTHONPATH=src python -m kalshi_research_bot raw-retention --older-than-days 30

# Apply, one source at a time, in bounded passes.
PYTHONPATH=src python -m kalshi_research_bot raw-retention \
    --older-than-days 30 --source kalshi_public_api --limit 2000 --apply
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

## Choosing a window

Thirty days is the default because it keeps a month of raw bodies available for
re-parsing while bounding the table. The right window is a function of volume
size and collection cadence, not a universal number — measure with
`--report-only` before choosing.
