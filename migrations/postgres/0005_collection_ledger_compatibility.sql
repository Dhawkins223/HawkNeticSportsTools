CREATE TABLE IF NOT EXISTS ingestion_batches (
    batch_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    worker_name TEXT NOT NULL,
    worker_version TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    collection_mode TEXT NOT NULL CHECK (collection_mode IN ('live', 'historical', 'replay')),
    request_parameters_json TEXT NOT NULL DEFAULT '{}',
    cursor_start TEXT,
    cursor_end TEXT,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN (
        'started', 'completed', 'completed_with_rejections', 'failed', 'blocked', 'cancelled'
    )),
    http_status INTEGER,
    records_received INTEGER NOT NULL DEFAULT 0 CHECK (records_received >= 0),
    records_accepted INTEGER NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
    records_rejected INTEGER NOT NULL DEFAULT 0 CHECK (records_rejected >= 0),
    records_duplicated INTEGER NOT NULL DEFAULT 0 CHECK (records_duplicated >= 0),
    payload_hash TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_source_payloads (
    payload_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id),
    source TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source_identifier TEXT,
    observed_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (batch_id, source_identifier, content_hash)
);

CREATE TABLE IF NOT EXISTS rejected_records (
    rejection_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id),
    payload_id TEXT REFERENCES raw_source_payloads(payload_id),
    entity_type TEXT NOT NULL,
    rejection_code TEXT NOT NULL,
    rejection_detail TEXT,
    parser_version TEXT NOT NULL,
    rejected_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    resolution TEXT
);

CREATE TABLE IF NOT EXISTS collection_checkpoints (
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    partition_scope TEXT NOT NULL DEFAULT '',
    cursor TEXT,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    last_successful_item_time TIMESTAMPTZ,
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id),
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source, endpoint, partition_scope)
);

CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    last_attempted_at TIMESTAMPTZ NOT NULL,
    last_successful_at TIMESTAMPTZ,
    freshness_deadline TIMESTAMPTZ,
    freshness_state TEXT NOT NULL CHECK (freshness_state IN (
        'fresh', 'approaching_stale', 'stale', 'missing', 'blocked', 'failed', 'unknown'
    )),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_results (
    result_id TEXT PRIMARY KEY,
    batch_id TEXT REFERENCES ingestion_batches(batch_id),
    check_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'warning', 'skipped')),
    details_json TEXT NOT NULL DEFAULT '{}',
    checked_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS backfill_jobs (
    job_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    checkpoint TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS report_refreshes (
    refresh_id TEXT PRIMARY KEY,
    report_name TEXT NOT NULL,
    data_cutoff_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    row_count INTEGER CHECK (row_count IS NULL OR row_count >= 0),
    error_code TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingestion_batches_source_started
    ON ingestion_batches(source, endpoint, started_at);
CREATE INDEX IF NOT EXISTS idx_ingestion_batches_status
    ON ingestion_batches(status, started_at);
CREATE INDEX IF NOT EXISTS idx_raw_source_payloads_source_observed
    ON raw_source_payloads(source, entity_type, observed_at);
CREATE INDEX IF NOT EXISTS idx_raw_source_payloads_hash
    ON raw_source_payloads(content_hash);
CREATE INDEX IF NOT EXISTS idx_rejected_records_unresolved
    ON rejected_records(rejected_at) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_source_health_state
    ON source_health(freshness_state, freshness_deadline);
