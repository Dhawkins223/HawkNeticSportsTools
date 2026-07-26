CREATE TABLE IF NOT EXISTS ops.import_lineage (
    import_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_key TEXT NOT NULL,
    target_table TEXT NOT NULL,
    target_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (import_id, source_table, source_key)
);

CREATE INDEX IF NOT EXISTS idx_ops_import_lineage_target
    ON ops.import_lineage (target_table, target_key);
