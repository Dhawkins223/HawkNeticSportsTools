# Railway Volume Storage Audit

Production storage was not accessed during the PostgreSQL-only repository conversion. Treat this document as a required pre-cutover audit, not evidence of a completed hosted inspection.

Before any mutation, record volume identity, mount path, capacity, free space, major directories, file ages, and data ownership. Classify material as:

- authoritative: operational records, raw evidence, prediction lineage, settlement evidence, authentication state, messages, and audit data;
- reconstructable: generated reports and reproducible caches;
- temporary: bounded downloads, debug output, and abandoned test artifacts;
- unknown: investigate before action.

Create and verify a backup before deleting or rotating any production-volume content. Never remove authoritative or unknown material through retention. Test restoration outside production before treating backup coverage as proven.
