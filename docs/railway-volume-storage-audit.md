# Railway Production Volume Storage Audit

Status: **read-only audit complete; production mutation blocked because backups are unavailable on the current plan**.

## Verified boundary

- Project: `jubilant-liberation`.
- Environment: `production` (`cd5e7bc2-b6e5-4c1a-a442-8e1a2b9cb64a`).
- Service: `HawkNeticSportsTools` (`ebd3b901-5cd5-46c9-990c-bc2c55119ad9`).
- Watched branch: `Master`.
- Active production commit: `aec3886c791e2a733fd1bfbeeb59a4298f40cb67`.
- Volume: `hawkneticsportstools-volume` (`4d5509e0-e9f8-4170-a117-c5c203120ffa`).
- Mount path: `/data`.

No production file, variable, service, deployment, branch, or domain was changed.

## Current storage totals

| Measure | Value |
|---|---:|
| Allocated | 5,000 MB |
| Used | 625.287 MB |
| Free | 4,374.713 MB |
| Utilization | 12.51% |

The prior full-volume signal is not current. Railway now reports the volume `READY` with substantial free capacity.

## File classification

| Class | Path/category | Observed size | Reason |
|---|---|---:|---|
| Authoritative | `/evaluation.sqlite` | 195,575,808 bytes | active production research ledger; never retention-delete |
| Authoritative | `/refresh_audit.jsonl` | 390,313 bytes | operational audit history |
| Authoritative | `/error_events.jsonl` | 51,238 bytes | operational failure history |
| Reconstructable | `/today_paper_view.json` | 3,207,661 bytes | generated dashboard payload |
| Reconstructable | `/http_cache` | 703 files; 215,343,895 logical bytes | bounded source-response cache; oldest 2026-07-13T02:21:47Z, newest 2026-07-13T05:32:54Z |
| Unknown | `/lost+found` | 16,384 bytes reported | filesystem-managed; do not delete |

The root directory listing contains no report archive, browser-artifact, test-output, operator-message, or authentication directory. Those data may exist inside SQLite and remain authoritative through that ledger.

## Retention state

The application already prunes HTTP cache entries by age and total size through `prune_http_cache`:

- default maximum age: 6 hours
- default maximum bytes: 256 MiB
- production observed cache: about 205.4 MiB logical

This is an appropriate bounded policy for reconstructable cache data. It does not apply to SQLite, audit history, rejected records, unresolved records, settlement evidence, prediction lineage, operator messages, or authentication data.

## Backup capability

Railway's production Backups page states:

- Backups and point-in-time recovery require the Pro plan.
- This service volume has no backups.

The current Hobby plan therefore provides no verified Railway backup or PITR for this volume. A restoration test cannot be performed without a backup and was not attempted against production.

## Actions performed

- Read-only volume metadata and file listings collected.
- Dedicated local Railway SSH public key registered for controlled inspection; no private key entered the repository.
- Large-file read-only download was attempted outside the repository, timed out after a partial 32 MiB transfer, and the partial local file was deleted.
- Files removed from production: none.
- Storage recovered: 0 bytes.
- Retention changes: none required; the existing cache cap is operating within bounds.

## Safety decision

No production cleanup is justified now because the volume is only 12.51% utilized. No cleanup is permitted under the repository policy because no verified backup exists. Production database migration and any destructive storage operation remain blocked until a backup method is available and restoration is tested outside production.
