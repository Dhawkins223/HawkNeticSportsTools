# Railway Production Volume Storage Audit

Status: **blocked pending interactive Railway CLI authentication**.

## Verified boundary

- Production service: `HawkNeticSportsTools` in project `jubilant-liberation`.
- Production watches `Master` and remains unchanged.
- Attached volume: `hawkneticsportstools-volume`.
- Railway previously reported the volume as full.
- `railway.cmd --version` succeeds with version `5.23.3`.
- `railway.cmd whoami` and `railway.cmd status` return `Unauthorized`.

No Railway environment, service, variable, backup, volume file, or deployment was changed during this continuation. No production file was deleted, moved, truncated, or read.

## Audit required after login

After the operator completes interactive `railway login`, inspect without printing file contents or secret values:

1. Verify the linked project, production environment, service, volume name, and mount path.
2. Record allocated and used storage.
3. Categorize directory and file sizes by path, modification time, and owning process.
4. Verify whether SQLite, audit records, operator messages, source evidence, reports, cache, logs, test output, or browser artifacts use the volume.
5. Verify backup support and create a manual backup before any cleanup.
6. Confirm the backup appears against the intended volume; test restoration only outside production.

## Classification policy

| Class | Examples | Action |
|---|---|---|
| Authoritative | active SQLite database, operator records, audit records, irreplaceable source/settlement/prediction evidence, auth data | back up and migrate deliberately; never retention-delete |
| Reconstructable | generated reports, derived cache, rendered artifacts reproducible from evidence | remove only after backup/path/reader verification |
| Temporary | expired downloads, abandoned test output, debug logs, old build artifacts | bounded retention only after backup and exact path verification |
| Unknown | unowned or unexplained files | do not delete; identify writer and reader first |

## Current storage totals

Unavailable until Railway CLI authentication and project linking are complete. The full-volume signal is a production blocker, not evidence that any particular file category is safe to delete.

## Backup and removal state

- Backup verified: no.
- Restoration tested outside production: no.
- Authoritative data identified by path: no.
- Removable data identified by path: no.
- Actions performed: none.
- Remaining capacity: unverified/full signal remains unresolved.
