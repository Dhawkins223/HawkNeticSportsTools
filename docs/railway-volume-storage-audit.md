# Railway Volume Storage Audit

Railway metadata was inspected read-only on 2026-07-25. The production volume
is mounted at `/data`, reports 778.44 MB used of 5,000 MB, and is attached only
to the production web service. The staging PostgreSQL volume is mounted at
`/var/lib/postgresql/data` and reports 341.11 MB used of 5,000 MB. No file
contents were opened, and backup or restore capability was not verified.

The earlier full-volume condition is not present in current Railway metadata,
but production content classification remains pending. Treat this document as
a required pre-cutover audit, not evidence of a completed backup or restore.

Before any mutation, record volume identity, mount path, capacity, free space, major directories, file ages, and data ownership. Classify material as:

- authoritative: operational records, raw evidence, prediction lineage, settlement evidence, authentication state, messages, and audit data;
- reconstructable: generated reports and reproducible caches;
- temporary: bounded downloads, debug output, and abandoned test artifacts;
- unknown: investigate before action.

Create and verify a backup before deleting or rotating any production-volume content. Never remove authoritative or unknown material through retention. Test restoration outside production before treating backup coverage as proven.
