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

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM app.worker_runs AS legacy
        JOIN ops.worker_runs AS target
          ON target.worker_name = legacy.worker_name
         AND target.idempotency_key = legacy.idempotency_key
        WHERE jsonb_build_object(
            'worker_version', target.worker_version,
            'deployment_identifier', target.deployment_identifier,
            'run_id', target.run_id,
            'started_at', target.started_at,
            'heartbeat_at', target.heartbeat_at,
            'completed_at', target.completed_at,
            'status', target.status,
            'records_read', target.records_read,
            'records_written', target.records_written,
            'records_rejected', target.records_rejected,
            'records_duplicated', target.records_duplicated,
            'error_code', target.error_code,
            'error_detail', target.error_detail,
            'details_json', target.details_json
        ) IS DISTINCT FROM jsonb_build_object(
            'worker_version', 'pre_cutover',
            'deployment_identifier', 'application',
            'run_id', legacy.run_id,
            'started_at', legacy.attempted_at,
            'heartbeat_at', COALESCE(legacy.finished_at, legacy.attempted_at),
            'completed_at', legacy.finished_at,
            'status', CASE legacy.status
                WHEN 'success' THEN 'completed'
                WHEN 'running' THEN 'started'
                WHEN 'failed' THEN 'failed'
                ELSE 'cancelled'
            END,
            'records_read', 0,
            'records_written', legacy.records_processed,
            'records_rejected', 0,
            'records_duplicated', 0,
            'error_code', legacy.error_code,
            'error_detail', legacy.error_code,
            'details_json', legacy.details_json
        )
    ) THEN
        RAISE EXCEPTION 'legacy_worker_run_content_conflict';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM app.worker_status AS legacy
        JOIN ops.worker_status AS target ON target.worker_name = legacy.worker_name
        WHERE jsonb_build_object(
            'asset_class', target.asset_class,
            'current_run_id', target.current_run_id,
            'status', target.status,
            'last_attempted_at', target.last_attempted_at,
            'last_successful_at', target.last_successful_at,
            'consecutive_failures', target.consecutive_failures,
            'total_failures', target.total_failures,
            'last_error_code', target.last_error_code,
            'data_fresh_at', target.data_fresh_at,
            'source_fresh_at', target.source_fresh_at,
            'pending_settlements', target.pending_settlements,
            'model_state', target.model_state,
            'heartbeat_at', target.heartbeat_at,
            'details_json', target.details_json
        ) IS DISTINCT FROM jsonb_build_object(
            'asset_class', legacy.asset_class,
            'current_run_id', legacy.current_run_id,
            'status', CASE legacy.status
                WHEN 'running' THEN 'running'
                WHEN 'healthy' THEN 'healthy'
                WHEN 'failed' THEN 'failed'
                ELSE 'stopped'
            END,
            'last_attempted_at', legacy.last_attempted_at,
            'last_successful_at', legacy.last_successful_at,
            'consecutive_failures', legacy.consecutive_failures,
            'total_failures', legacy.total_failures,
            'last_error_code', legacy.last_error_code,
            'data_fresh_at', legacy.data_fresh_at,
            'source_fresh_at', legacy.source_fresh_at,
            'pending_settlements', legacy.pending_settlements,
            'model_state', legacy.model_state,
            'heartbeat_at', legacy.heartbeat_at,
            'details_json', legacy.details_json
        )
    ) THEN
        RAISE EXCEPTION 'legacy_worker_status_content_conflict';
    END IF;
END $$;

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
WHERE NOT EXISTS (
    SELECT 1
    FROM ops.worker_runs AS target
    WHERE target.worker_name = app.worker_runs.worker_name
      AND target.idempotency_key = app.worker_runs.idempotency_key
);

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
WHERE NOT EXISTS (
    SELECT 1
    FROM ops.worker_status AS target
    WHERE target.worker_name = app.worker_status.worker_name
);

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
