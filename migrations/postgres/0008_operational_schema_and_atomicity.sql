-- PostgreSQL 15+ is required for NULLS NOT DISTINCT unique indexes.
-- `app` owns the preserved research workflows while `raw`, `core`, `research`,
-- `ops`, and `auth` own their respective immutable, normalized, operational,
-- and authentication ledgers. Runtime connections use `app,pg_catalog` only,
-- and every cross-schema operation is explicitly qualified.

ALTER TABLE ops.worker_runs
    ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS details_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS ops.worker_status (
    worker_name TEXT PRIMARY KEY,
    asset_class TEXT NOT NULL,
    current_run_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'healthy', 'failed', 'stopped')),
    last_attempted_at TIMESTAMPTZ,
    last_successful_at TIMESTAMPTZ,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    total_failures INTEGER NOT NULL DEFAULT 0 CHECK (total_failures >= 0),
    last_error_code TEXT,
    data_fresh_at TIMESTAMPTZ,
    source_fresh_at TIMESTAMPTZ,
    pending_settlements INTEGER NOT NULL DEFAULT 0 CHECK (pending_settlements >= 0),
    model_state TEXT,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

INSERT INTO ops.worker_runs (
    worker_name, worker_version, deployment_identifier, run_id, idempotency_key,
    started_at, heartbeat_at, completed_at, status, records_read, records_written,
    records_rejected, records_duplicated, error_code, error_detail, details_json
)
SELECT
    worker_name,
    'pre_cutover',
    'application',
    run_id,
    idempotency_key,
    attempted_at,
    COALESCE(finished_at, attempted_at),
    finished_at,
    CASE status
        WHEN 'success' THEN 'completed'
        WHEN 'running' THEN 'started'
        WHEN 'failed' THEN 'failed'
        ELSE 'cancelled'
    END,
    0,
    records_processed,
    0,
    0,
    error_code,
    error_code,
    details_json
FROM app.worker_runs
ON CONFLICT (worker_name, idempotency_key) DO NOTHING;

INSERT INTO ops.worker_status (
    worker_name, asset_class, current_run_id, status, last_attempted_at,
    last_successful_at, consecutive_failures, total_failures, last_error_code,
    data_fresh_at, source_fresh_at, pending_settlements, model_state,
    heartbeat_at, details_json
)
SELECT
    worker_name,
    asset_class,
    current_run_id,
    CASE status
        WHEN 'running' THEN 'running'
        WHEN 'healthy' THEN 'healthy'
        WHEN 'failed' THEN 'failed'
        ELSE 'stopped'
    END,
    last_attempted_at,
    last_successful_at,
    consecutive_failures,
    total_failures,
    last_error_code,
    data_fresh_at,
    source_fresh_at,
    pending_settlements,
    model_state,
    heartbeat_at,
    details_json
FROM app.worker_status
ON CONFLICT (worker_name) DO UPDATE SET
    asset_class = EXCLUDED.asset_class,
    current_run_id = EXCLUDED.current_run_id,
    status = EXCLUDED.status,
    last_attempted_at = EXCLUDED.last_attempted_at,
    last_successful_at = EXCLUDED.last_successful_at,
    consecutive_failures = EXCLUDED.consecutive_failures,
    total_failures = EXCLUDED.total_failures,
    last_error_code = EXCLUDED.last_error_code,
    data_fresh_at = EXCLUDED.data_fresh_at,
    source_fresh_at = EXCLUDED.source_fresh_at,
    pending_settlements = EXCLUDED.pending_settlements,
    model_state = EXCLUDED.model_state,
    heartbeat_at = EXCLUDED.heartbeat_at,
    details_json = EXCLUDED.details_json;

DROP TABLE IF EXISTS app.worker_status;
DROP TABLE IF EXISTS app.worker_runs;

DROP INDEX IF EXISTS app.idx_settlement_audit_dedupe;
CREATE UNIQUE INDEX idx_settlement_audit_dedupe
    ON app.settlement_audit (
        prediction_log_id,
        source,
        issue,
        new_settlement_state,
        raw_settlement_hash
    ) NULLS NOT DISTINCT;

DROP INDEX IF EXISTS app.idx_sports_prediction_exact;
CREATE UNIQUE INDEX idx_sports_prediction_exact
    ON app.sports_prediction_logs (
        asset_class,
        run_id,
        strategy,
        sport,
        league,
        event_id,
        market_type,
        selection,
        line,
        bookmaker,
        prediction_timestamp
    ) NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_ops_worker_status_heartbeat
    ON ops.worker_status (heartbeat_at, status);
