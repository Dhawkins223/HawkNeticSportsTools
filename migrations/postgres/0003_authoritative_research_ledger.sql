CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS research;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS reporting;
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS raw.ingestion_batches (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    worker_name TEXT NOT NULL,
    worker_version TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    collection_mode TEXT NOT NULL DEFAULT 'live' CHECK (collection_mode IN ('live', 'historical', 'replay')),
    request_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    cursor_start TEXT,
    cursor_end TEXT,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN (
        'started', 'completed', 'completed_with_rejections', 'failed', 'blocked', 'cancelled'
    )),
    http_status INTEGER CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
    records_received INTEGER NOT NULL DEFAULT 0 CHECK (records_received >= 0),
    records_accepted INTEGER NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
    records_rejected INTEGER NOT NULL DEFAULT 0 CHECK (records_rejected >= 0),
    records_duplicated INTEGER NOT NULL DEFAULT 0 CHECK (records_duplicated >= 0),
    payload_hash TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS raw.source_payloads (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    source TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source_identifier TEXT,
    observed_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    parser_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (batch_id, source_identifier, content_hash)
);

CREATE TABLE IF NOT EXISTS raw.rejected_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    raw_payload_id BIGINT REFERENCES raw.source_payloads(id),
    entity_type TEXT NOT NULL,
    rejection_code TEXT NOT NULL,
    rejection_detail TEXT,
    parser_version TEXT NOT NULL,
    rejected_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    resolution TEXT,
    CHECK (resolved_at IS NULL OR resolved_at >= rejected_at)
);

CREATE TABLE IF NOT EXISTS core.series (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    series_ticker TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT,
    frequency TEXT,
    settlement_source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_raw_payload_id BIGINT REFERENCES raw.source_payloads(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (last_seen_at >= first_seen_at)
);

CREATE TABLE IF NOT EXISTS core.events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_ticker TEXT NOT NULL UNIQUE,
    series_id BIGINT REFERENCES core.series(id),
    title TEXT NOT NULL,
    subtitle TEXT,
    category TEXT,
    status TEXT NOT NULL,
    expected_expiration TIMESTAMPTZ,
    settlement_source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_raw_payload_id BIGINT REFERENCES raw.source_payloads(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (last_seen_at >= first_seen_at)
);

CREATE TABLE IF NOT EXISTS core.markets (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_ticker TEXT NOT NULL UNIQUE,
    event_id BIGINT NOT NULL REFERENCES core.events(id),
    market_type TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT,
    yes_label TEXT,
    no_label TEXT,
    status TEXT NOT NULL,
    open_time TIMESTAMPTZ,
    close_time TIMESTAMPTZ,
    expiration_time TIMESTAMPTZ,
    settled_time TIMESTAMPTZ,
    result TEXT CHECK (result IS NULL OR result IN ('yes', 'no', 'scalar', 'void', 'cancelled')),
    rules TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_raw_payload_id BIGINT REFERENCES raw.source_payloads(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (last_seen_at >= first_seen_at),
    CHECK (close_time IS NULL OR open_time IS NULL OR close_time >= open_time),
    CHECK (expiration_time IS NULL OR open_time IS NULL OR expiration_time >= open_time),
    CHECK (settled_time IS NULL OR open_time IS NULL OR settled_time >= open_time)
);

CREATE TABLE IF NOT EXISTS core.market_observations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES core.markets(id),
    observed_at TIMESTAMPTZ NOT NULL,
    source_received_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    yes_bid NUMERIC(12, 8) CHECK (yes_bid IS NULL OR yes_bid BETWEEN 0 AND 1),
    yes_ask NUMERIC(12, 8) CHECK (yes_ask IS NULL OR yes_ask BETWEEN 0 AND 1),
    no_bid NUMERIC(12, 8) CHECK (no_bid IS NULL OR no_bid BETWEEN 0 AND 1),
    no_ask NUMERIC(12, 8) CHECK (no_ask IS NULL OR no_ask BETWEEN 0 AND 1),
    last_price NUMERIC(12, 8) CHECK (last_price IS NULL OR last_price BETWEEN 0 AND 1),
    volume NUMERIC(30, 8) CHECK (volume IS NULL OR volume >= 0),
    volume_24h NUMERIC(30, 8) CHECK (volume_24h IS NULL OR volume_24h >= 0),
    open_interest NUMERIC(30, 8) CHECK (open_interest IS NULL OR open_interest >= 0),
    liquidity NUMERIC(30, 8) CHECK (liquidity IS NULL OR liquidity >= 0),
    raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    ingestion_batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (market_id, observed_at, raw_payload_id),
    CHECK (yes_bid IS NULL OR yes_ask IS NULL OR yes_bid <= yes_ask),
    CHECK (no_bid IS NULL OR no_ask IS NULL OR no_bid <= no_ask)
);

CREATE TABLE IF NOT EXISTS core.trades (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_trade_id TEXT NOT NULL UNIQUE,
    market_id BIGINT NOT NULL REFERENCES core.markets(id),
    executed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    yes_price NUMERIC(12, 8) NOT NULL CHECK (yes_price BETWEEN 0 AND 1),
    no_price NUMERIC(12, 8) NOT NULL CHECK (no_price BETWEEN 0 AND 1),
    quantity NUMERIC(30, 8) NOT NULL CHECK (quantity > 0),
    taker_side TEXT CHECK (taker_side IS NULL OR taker_side IN ('yes', 'no', 'unknown')),
    raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    ingestion_batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (received_at >= executed_at),
    CHECK (yes_price + no_price BETWEEN 0.999999 AND 1.000001)
);

CREATE TABLE IF NOT EXISTS core.orderbook_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES core.markets(id),
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    source_sequence TEXT,
    requested_depth INTEGER CHECK (requested_depth IS NULL OR requested_depth > 0),
    raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    ingestion_batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    is_complete BOOLEAN NOT NULL,
    reconstruction_status TEXT NOT NULL CHECK (reconstruction_status IN ('complete', 'partial', 'gap', 'not_applicable')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (market_id, observed_at, source_sequence)
);

CREATE TABLE IF NOT EXISTS core.orderbook_levels (
    snapshot_id BIGINT NOT NULL REFERENCES core.orderbook_snapshots(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK (side IN ('yes_bid', 'yes_ask', 'no_bid', 'no_ask')),
    price NUMERIC(12, 8) NOT NULL CHECK (price BETWEEN 0 AND 1),
    quantity NUMERIC(30, 8) NOT NULL CHECK (quantity > 0),
    level_position INTEGER NOT NULL CHECK (level_position >= 0),
    PRIMARY KEY (snapshot_id, side, level_position),
    UNIQUE (snapshot_id, side, price)
);

CREATE TABLE IF NOT EXISTS core.settlements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES core.markets(id),
    source_result TEXT NOT NULL,
    settlement_value NUMERIC(30, 12),
    source_settled_at TIMESTAMPTZ NOT NULL,
    determination_source TEXT NOT NULL,
    raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    verification_status TEXT NOT NULL CHECK (verification_status IN ('unverified', 'verified', 'disputed', 'invalid')),
    verified_at TIMESTAMPTZ,
    correction_status TEXT NOT NULL DEFAULT 'original' CHECK (correction_status IN ('original', 'superseded', 'correction')),
    supersedes_settlement_id BIGINT REFERENCES core.settlements(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (market_id, raw_payload_id),
    CHECK (verified_at IS NULL OR verification_status IN ('verified', 'disputed', 'invalid'))
);

CREATE TABLE IF NOT EXISTS research.model_versions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    configuration JSONB NOT NULL,
    feature_schema_version TEXT NOT NULL,
    training_dataset_hash TEXT,
    training_cutoff_time TIMESTAMPTZ,
    training_started_at TIMESTAMPTZ,
    training_completed_at TIMESTAMPTZ,
    artifact_location TEXT,
    promotion_status TEXT NOT NULL CHECK (promotion_status IN (
        'experimental', 'insufficient_sample', 'failed_validation', 'baseline_only',
        'validated_research', 'drift_detected', 'disabled'
    )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (model_name, model_version, code_commit),
    CHECK (training_completed_at IS NULL OR training_started_at IS NULL OR training_completed_at >= training_started_at)
);

CREATE TABLE IF NOT EXISTS research.feature_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES core.markets(id),
    feature_time TIMESTAMPTZ NOT NULL,
    source_cutoff_time TIMESTAMPTZ NOT NULL,
    feature_schema_version TEXT NOT NULL,
    source_data_hash TEXT NOT NULL,
    market_implied_probability NUMERIC(12, 8) CHECK (market_implied_probability IS NULL OR market_implied_probability BETWEEN 0 AND 1),
    spread NUMERIC(12, 8) CHECK (spread IS NULL OR spread >= 0),
    liquidity NUMERIC(30, 8) CHECK (liquidity IS NULL OR liquidity >= 0),
    feature_values JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (market_id, feature_time, feature_schema_version, source_data_hash),
    CHECK (source_cutoff_time <= feature_time)
);

CREATE TABLE IF NOT EXISTS research.prediction_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_version_id BIGINT NOT NULL REFERENCES research.model_versions(id),
    run_type TEXT NOT NULL CHECK (run_type IN ('forward', 'backtest', 'walk_forward', 'validation')),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    as_of_time TIMESTAMPTZ NOT NULL,
    data_cutoff_time TIMESTAMPTZ NOT NULL,
    code_commit TEXT NOT NULL,
    configuration JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'completed_with_rejections', 'failed', 'cancelled')),
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (data_cutoff_time <= as_of_time),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS research.predictions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prediction_run_id BIGINT NOT NULL REFERENCES research.prediction_runs(id),
    market_id BIGINT NOT NULL REFERENCES core.markets(id),
    feature_snapshot_id BIGINT NOT NULL REFERENCES research.feature_snapshots(id),
    predicted_yes_probability NUMERIC(12, 8) NOT NULL CHECK (predicted_yes_probability BETWEEN 0 AND 1),
    market_implied_probability NUMERIC(12, 8) NOT NULL CHECK (market_implied_probability BETWEEN 0 AND 1),
    calculated_edge NUMERIC(12, 8) NOT NULL,
    confidence_interval_low NUMERIC(12, 8) CHECK (confidence_interval_low IS NULL OR confidence_interval_low BETWEEN 0 AND 1),
    confidence_interval_high NUMERIC(12, 8) CHECK (confidence_interval_high IS NULL OR confidence_interval_high BETWEEN 0 AND 1),
    decision_status TEXT NOT NULL CHECK (decision_status IN ('accepted', 'rejected', 'blocked', 'no_edge')),
    rejection_reason TEXT,
    source_freshness_state TEXT NOT NULL CHECK (source_freshness_state IN (
        'fresh', 'approaching_stale', 'stale', 'missing', 'blocked', 'failed', 'unknown', 'historical'
    )),
    duplicate_of_prediction_id BIGINT REFERENCES research.predictions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (prediction_run_id, market_id),
    CHECK (confidence_interval_low IS NULL OR confidence_interval_high IS NULL OR confidence_interval_low <= confidence_interval_high),
    CHECK (decision_status <> 'accepted' OR source_freshness_state IN ('fresh', 'historical')),
    CHECK (decision_status <> 'accepted' OR duplicate_of_prediction_id IS NULL)
);

CREATE TABLE IF NOT EXISTS research.prediction_outcomes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prediction_id BIGINT NOT NULL REFERENCES research.predictions(id),
    settlement_id BIGINT NOT NULL REFERENCES core.settlements(id),
    outcome_available_at TIMESTAMPTZ NOT NULL,
    brier_score NUMERIC(20, 16) CHECK (brier_score BETWEEN 0 AND 1),
    log_loss NUMERIC(24, 16) CHECK (log_loss >= 0),
    binary_correctness BOOLEAN,
    evaluation_version TEXT NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (prediction_id, settlement_id, evaluation_version),
    CHECK (evaluated_at >= outcome_available_at)
);

CREATE TABLE IF NOT EXISTS research.simulation_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_identifier TEXT NOT NULL UNIQUE,
    execution_model_version TEXT NOT NULL,
    configuration JSONB NOT NULL,
    capital_limit NUMERIC(30, 8) NOT NULL CHECK (capital_limit >= 0),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research.simulated_orders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    simulation_run_id BIGINT NOT NULL REFERENCES research.simulation_runs(id),
    prediction_id BIGINT NOT NULL REFERENCES research.predictions(id),
    signal_timestamp TIMESTAMPTZ NOT NULL,
    order_timestamp TIMESTAMPTZ NOT NULL,
    market_observation_id BIGINT NOT NULL REFERENCES core.market_observations(id),
    order_side TEXT NOT NULL CHECK (order_side IN ('yes', 'no')),
    order_type TEXT NOT NULL CHECK (order_type IN ('market', 'limit')),
    intended_price NUMERIC(12, 8) NOT NULL CHECK (intended_price BETWEEN 0 AND 1),
    requested_quantity NUMERIC(30, 8) NOT NULL CHECK (requested_quantity > 0),
    fill_state TEXT NOT NULL CHECK (fill_state IN ('unfilled', 'partial', 'filled', 'rejected', 'expired')),
    filled_quantity NUMERIC(30, 8) NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0),
    unfilled_quantity NUMERIC(30, 8) NOT NULL CHECK (unfilled_quantity >= 0),
    fee_estimate NUMERIC(30, 12) NOT NULL DEFAULT 0 CHECK (fee_estimate >= 0),
    slippage NUMERIC(30, 12) NOT NULL DEFAULT 0,
    final_payout NUMERIC(30, 12),
    gross_return NUMERIC(30, 12),
    net_return NUMERIC(30, 12),
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (simulation_run_id, prediction_id),
    CHECK (filled_quantity + unfilled_quantity = requested_quantity)
);

CREATE TABLE IF NOT EXISTS research.simulated_fills (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    simulated_order_id BIGINT NOT NULL REFERENCES research.simulated_orders(id),
    filled_at TIMESTAMPTZ NOT NULL,
    fill_price NUMERIC(12, 8) NOT NULL CHECK (fill_price BETWEEN 0 AND 1),
    quantity NUMERIC(30, 8) NOT NULL CHECK (quantity > 0),
    fee NUMERIC(30, 12) NOT NULL DEFAULT 0 CHECK (fee >= 0),
    liquidity_role TEXT CHECK (liquidity_role IS NULL OR liquidity_role IN ('maker', 'taker', 'unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research.correlation_groups (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    group_identifier TEXT NOT NULL UNIQUE,
    event_id BIGINT REFERENCES core.events(id),
    category TEXT NOT NULL,
    underlying_identifier TEXT,
    time_window_start TIMESTAMPTZ,
    time_window_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (time_window_end IS NULL OR time_window_start IS NULL OR time_window_end >= time_window_start)
);

CREATE TABLE IF NOT EXISTS research.exposure_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    simulation_run_id BIGINT NOT NULL REFERENCES research.simulation_runs(id),
    correlation_group_id BIGINT NOT NULL REFERENCES research.correlation_groups(id),
    observed_at TIMESTAMPTZ NOT NULL,
    raw_capital_at_risk NUMERIC(30, 12) NOT NULL CHECK (raw_capital_at_risk >= 0),
    accepted_capital_at_risk NUMERIC(30, 12) NOT NULL CHECK (accepted_capital_at_risk >= 0),
    maximum_allowed NUMERIC(30, 12) NOT NULL CHECK (maximum_allowed >= 0),
    decision_status TEXT NOT NULL CHECK (decision_status IN ('accepted', 'limited', 'rejected')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (simulation_run_id, correlation_group_id, observed_at),
    CHECK (accepted_capital_at_risk <= raw_capital_at_risk),
    CHECK (accepted_capital_at_risk <= maximum_allowed)
);

CREATE TABLE IF NOT EXISTS research.metric_results (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    metric_name TEXT NOT NULL CHECK (metric_name IN (
        'brier_score', 'log_loss', 'calibration_error', 'accuracy', 'gross_return',
        'fees', 'slippage', 'net_return', 'fill_rate', 'sample_size'
    )),
    metric_version TEXT NOT NULL,
    run_identifier TEXT NOT NULL,
    segment JSONB NOT NULL DEFAULT '{}'::jsonb,
    sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
    value NUMERIC(30, 16),
    confidence_interval_low NUMERIC(30, 16),
    confidence_interval_high NUMERIC(30, 16),
    calculated_at TIMESTAMPTZ NOT NULL,
    data_cutoff_time TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (metric_name, metric_version, run_identifier, segment),
    CHECK (confidence_interval_low IS NULL OR confidence_interval_high IS NULL OR confidence_interval_low <= confidence_interval_high)
);

CREATE TABLE IF NOT EXISTS ops.worker_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    worker_name TEXT NOT NULL,
    worker_version TEXT NOT NULL,
    deployment_identifier TEXT,
    idempotency_key TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed', 'blocked', 'cancelled')),
    records_read INTEGER NOT NULL DEFAULT 0 CHECK (records_read >= 0),
    records_written INTEGER NOT NULL DEFAULT 0 CHECK (records_written >= 0),
    records_rejected INTEGER NOT NULL DEFAULT 0 CHECK (records_rejected >= 0),
    records_duplicated INTEGER NOT NULL DEFAULT 0 CHECK (records_duplicated >= 0),
    error_code TEXT,
    error_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (worker_name, idempotency_key),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS ops.source_health (
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

CREATE TABLE IF NOT EXISTS ops.collection_checkpoints (
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    partition_scope TEXT NOT NULL DEFAULT '',
    cursor TEXT,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    last_successful_item_time TIMESTAMPTZ,
    ingestion_batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source, endpoint, partition_scope)
);

CREATE TABLE IF NOT EXISTS ops.backfill_jobs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    checkpoint TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (window_end >= window_start)
);

CREATE TABLE IF NOT EXISTS ops.data_quality_results (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_batch_id BIGINT REFERENCES raw.ingestion_batches(id),
    check_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'warning', 'skipped')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    checked_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.audit_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ops.migration_executions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    migration_revision TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    environment TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (migration_revision, environment),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS ops.report_refreshes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_name TEXT NOT NULL,
    data_cutoff_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    row_count INTEGER CHECK (row_count IS NULL OR row_count >= 0),
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_raw_batches_source_started
    ON raw.ingestion_batches(source, endpoint, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_batches_status
    ON raw.ingestion_batches(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_payload_source_observed
    ON raw.source_payloads(source, entity_type, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_payload_hash
    ON raw.source_payloads(content_hash);
CREATE INDEX IF NOT EXISTS idx_raw_rejections_unresolved
    ON raw.rejected_records(rejected_at DESC) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_core_market_observations_time
    ON core.market_observations(market_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_trades_time
    ON core.trades(market_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_settlements_verification
    ON core.settlements(verification_status, source_settled_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_feature_cutoff
    ON research.feature_snapshots(market_id, source_cutoff_time DESC);
CREATE INDEX IF NOT EXISTS idx_research_predictions_market
    ON research.predictions(prediction_run_id, market_id);
CREATE INDEX IF NOT EXISTS idx_research_predictions_exclusions
    ON research.predictions(decision_status, source_freshness_state)
    WHERE decision_status <> 'accepted' OR duplicate_of_prediction_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_research_outcomes_evaluated
    ON research.prediction_outcomes(evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_worker_started
    ON ops.worker_runs(worker_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_source_stale
    ON ops.source_health(freshness_state, freshness_deadline)
    WHERE freshness_state IN ('approaching_stale', 'stale', 'missing', 'blocked', 'failed', 'unknown');

CREATE OR REPLACE VIEW reporting.latest_market_state AS
SELECT DISTINCT ON (observation.market_id)
    observation.market_id,
    market.market_ticker,
    observation.observed_at,
    observation.source_received_at,
    observation.status,
    observation.yes_bid,
    observation.yes_ask,
    observation.no_bid,
    observation.no_ask,
    observation.last_price,
    observation.volume,
    observation.open_interest,
    observation.liquidity
FROM core.market_observations AS observation
JOIN core.markets AS market ON market.id = observation.market_id
ORDER BY observation.market_id, observation.observed_at DESC, observation.id DESC;

CREATE OR REPLACE VIEW reporting.market_data_freshness AS
SELECT
    market.market_ticker,
    latest.observed_at,
    latest.source_received_at,
    CURRENT_TIMESTAMP - latest.source_received_at AS receipt_age,
    latest.status
FROM reporting.latest_market_state AS latest
JOIN core.markets AS market ON market.id = latest.market_id;

CREATE OR REPLACE VIEW reporting.worker_health AS
SELECT DISTINCT ON (worker_name)
    worker_name,
    worker_version,
    deployment_identifier,
    started_at,
    heartbeat_at,
    completed_at,
    status,
    records_read,
    records_written,
    records_rejected,
    records_duplicated,
    error_code
FROM ops.worker_runs
ORDER BY worker_name, started_at DESC, id DESC;

CREATE OR REPLACE VIEW reporting.unresolved_data_quality_issues AS
SELECT
    rejection.id,
    rejection.batch_id,
    batch.source,
    batch.endpoint,
    rejection.entity_type,
    rejection.rejection_code,
    rejection.rejection_detail,
    rejection.rejected_at
FROM raw.rejected_records AS rejection
JOIN raw.ingestion_batches AS batch ON batch.id = rejection.batch_id
WHERE rejection.resolved_at IS NULL;

CREATE OR REPLACE VIEW reporting.prediction_evaluation AS
SELECT
    prediction.id AS prediction_id,
    prediction.prediction_run_id,
    market.market_ticker,
    prediction.predicted_yes_probability,
    prediction.market_implied_probability,
    prediction.calculated_edge,
    outcome.brier_score,
    outcome.log_loss,
    outcome.binary_correctness,
    outcome.evaluated_at
FROM research.predictions AS prediction
JOIN core.markets AS market ON market.id = prediction.market_id
JOIN research.prediction_outcomes AS outcome ON outcome.prediction_id = prediction.id
JOIN core.settlements AS settlement ON settlement.id = outcome.settlement_id
WHERE prediction.decision_status = 'accepted'
  AND prediction.duplicate_of_prediction_id IS NULL
  AND prediction.source_freshness_state IN ('fresh', 'historical')
  AND settlement.verification_status = 'verified';

CREATE OR REPLACE VIEW reporting.settlement_backlog AS
SELECT
    market.id AS market_id,
    market.market_ticker,
    market.status,
    market.expiration_time,
    market.settled_time
FROM core.markets AS market
WHERE market.status IN ('closed', 'settled', 'resolved')
  AND NOT EXISTS (
      SELECT 1
      FROM core.settlements AS settlement
      WHERE settlement.market_id = market.id
        AND settlement.verification_status = 'verified'
  );
