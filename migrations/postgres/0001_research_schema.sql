CREATE TABLE IF NOT EXISTS source_records (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS edge_results (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    game_id TEXT NOT NULL,
    side TEXT NOT NULL,
    model_probability DOUBLE PRECISION NOT NULL,
    entry_price_cents DOUBLE PRECISION NOT NULL,
    fair_price_cents DOUBLE PRECISION NOT NULL,
    expected_value_cents DOUBLE PRECISION NOT NULL,
    title TEXT NOT NULL,
    notes_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prediction_logs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT,
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    event TEXT NOT NULL,
    event_id TEXT,
    market TEXT NOT NULL,
    market_id TEXT,
    side TEXT NOT NULL,
    strategy TEXT,
    input_data_json TEXT NOT NULL,
    odds_json TEXT NOT NULL,
    model_version TEXT NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL,
    confidence_label TEXT NOT NULL,
    predicted_outcome TEXT NOT NULL,
    event_start_time TIMESTAMPTZ,
    market_close_time TIMESTAMPTZ,
    api_fetched_at TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    source_snapshot_id TEXT,
    source_snapshot_hash TEXT,
    snapshot_sequence INTEGER NOT NULL DEFAULT 1,
    entry_price_cents DOUBLE PRECISION,
    implied_probability DOUBLE PRECISION,
    reason_features_json TEXT NOT NULL DEFAULT '{}',
    validation_status TEXT NOT NULL DEFAULT 'invalid',
    validation_errors_json TEXT NOT NULL DEFAULT '[]',
    settlement_state TEXT NOT NULL DEFAULT 'unresolved',
    actual_outcome BOOLEAN,
    profit_loss_cents DOUBLE PRECISION,
    settlement_updated_at TIMESTAMPTZ,
    settlement_source TEXT,
    settlement_issue TEXT,
    slip_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_logs_run_dedupe
ON prediction_logs (run_id, strategy, event_id, market_id, side, prediction_timestamp)
WHERE run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS paper_test_runs (
    run_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    model_versions_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prediction_rejections (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    event TEXT NOT NULL,
    event_id TEXT,
    market TEXT NOT NULL,
    market_id TEXT,
    side TEXT NOT NULL,
    strategy TEXT,
    validation_errors_json TEXT NOT NULL,
    raw_log_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settlement_audit (
    id BIGSERIAL PRIMARY KEY,
    prediction_log_id BIGINT NOT NULL REFERENCES prediction_logs(id),
    run_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    previous_settlement_state TEXT,
    new_settlement_state TEXT,
    previous_actual_outcome BOOLEAN,
    new_actual_outcome BOOLEAN,
    previous_profit_loss_cents DOUBLE PRECISION,
    new_profit_loss_cents DOUBLE PRECISION,
    source TEXT NOT NULL,
    source_fetched_at TIMESTAMPTZ,
    issue TEXT,
    raw_settlement_hash TEXT NOT NULL,
    raw_settlement_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_settlement_audit_dedupe
ON settlement_audit (prediction_log_id, source, issue, new_settlement_state, raw_settlement_hash);

CREATE TABLE IF NOT EXISTS crypto_prediction_logs (
    id BIGSERIAL PRIMARY KEY,
    asset_class TEXT NOT NULL DEFAULT 'crypto',
    run_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    strategy TEXT NOT NULL,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    horizon TEXT NOT NULL,
    side TEXT NOT NULL,
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    settlement_time TIMESTAMPTZ NOT NULL,
    api_fetched_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ,
    source_snapshot_hash TEXT NOT NULL,
    source_payload_ref TEXT,
    timeframe TEXT NOT NULL,
    candle_open_time TIMESTAMPTZ NOT NULL,
    candle_close_time TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    bid DOUBLE PRECISION,
    ask DOUBLE PRECISION,
    mid_price DOUBLE PRECISION,
    spread DOUBLE PRECISION,
    implied_probability DOUBLE PRECISION,
    confidence_score DOUBLE PRECISION NOT NULL,
    features_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    rejection_reason TEXT,
    snapshot_sequence INTEGER NOT NULL DEFAULT 1,
    settlement_state TEXT NOT NULL DEFAULT 'unresolved',
    actual_outcome TEXT,
    settlement_price DOUBLE PRECISION,
    return_bps DOUBLE PRECISION,
    settlement_updated_at TIMESTAMPTZ,
    settlement_source TEXT,
    settlement_issue TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_crypto_prediction_exact
ON crypto_prediction_logs (asset_class, run_id, strategy, exchange, symbol, horizon, side, prediction_timestamp);

CREATE TABLE IF NOT EXISTS crypto_prediction_rejections (
    id BIGSERIAL PRIMARY KEY,
    asset_class TEXT NOT NULL DEFAULT 'crypto',
    run_id TEXT NOT NULL,
    strategy TEXT,
    exchange TEXT,
    symbol TEXT,
    horizon TEXT,
    side TEXT,
    prediction_timestamp TIMESTAMPTZ,
    rejection_reason TEXT NOT NULL,
    raw_log_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sports_prediction_logs (
    id BIGSERIAL PRIMARY KEY,
    asset_class TEXT NOT NULL DEFAULT 'sports',
    run_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    strategy TEXT NOT NULL,
    sport TEXT NOT NULL,
    league TEXT NOT NULL,
    event_id TEXT NOT NULL,
    game_id TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    market_type TEXT NOT NULL,
    selection TEXT NOT NULL,
    line DOUBLE PRECISION,
    odds DOUBLE PRECISION NOT NULL,
    odds_format TEXT NOT NULL,
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    odds_timestamp TIMESTAMPTZ NOT NULL,
    game_start_time TIMESTAMPTZ NOT NULL,
    market_close_time TIMESTAMPTZ,
    api_fetched_at TIMESTAMPTZ NOT NULL,
    source_snapshot_hash TEXT NOT NULL,
    source_payload_ref TEXT,
    confidence_score DOUBLE PRECISION NOT NULL,
    features_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    rejection_reason TEXT,
    snapshot_sequence INTEGER NOT NULL DEFAULT 1,
    settlement_state TEXT NOT NULL DEFAULT 'unresolved',
    actual_outcome TEXT,
    final_score_json TEXT,
    closing_line DOUBLE PRECISION,
    clv DOUBLE PRECISION,
    settlement_updated_at TIMESTAMPTZ,
    settlement_source TEXT,
    settlement_issue TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sports_prediction_exact
ON sports_prediction_logs (
    asset_class, run_id, strategy, sport, league, event_id, market_type,
    selection, line, bookmaker, prediction_timestamp
);

CREATE TABLE IF NOT EXISTS sports_prediction_rejections (
    id BIGSERIAL PRIMARY KEY,
    asset_class TEXT NOT NULL DEFAULT 'sports',
    run_id TEXT NOT NULL,
    strategy TEXT,
    sport TEXT,
    league TEXT,
    event_id TEXT,
    market_type TEXT,
    selection TEXT,
    line DOUBLE PRECISION,
    bookmaker TEXT,
    prediction_timestamp TIMESTAMPTZ,
    rejection_reason TEXT NOT NULL,
    raw_log_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_evaluations (
    id BIGSERIAL PRIMARY KEY,
    evaluation_id TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    model_state TEXT NOT NULL CHECK (model_state IN (
        'experimental', 'insufficient_sample', 'failed_validation',
        'baseline_only', 'validated_research', 'drift_detected', 'disabled'
    )),
    model_version TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    baseline_name TEXT NOT NULL,
    selected_model TEXT,
    evaluation_timestamp TIMESTAMPTZ NOT NULL,
    training_start TIMESTAMPTZ,
    training_end TIMESTAMPTZ,
    validation_start TIMESTAMPTZ,
    validation_end TIMESTAMPTZ,
    test_start TIMESTAMPTZ,
    test_end TIMESTAMPTZ,
    sample_size INTEGER NOT NULL,
    brier_score DOUBLE PRECISION,
    log_loss DOUBLE PRECISION,
    calibration_error DOUBLE PRECISION,
    accuracy DOUBLE PRECISION,
    accuracy_ci_low DOUBLE PRECISION,
    accuracy_ci_high DOUBLE PRECISION,
    evidence_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_evaluation_predictions (
    id BIGSERIAL PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES model_evaluations(evaluation_id),
    record_id TEXT NOT NULL,
    split_name TEXT NOT NULL CHECK (split_name IN ('train', 'validation', 'test')),
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    model_probability DOUBLE PRECISION,
    market_implied_probability DOUBLE PRECISION NOT NULL,
    probability_difference DOUBLE PRECISION,
    actual_outcome BOOLEAN NOT NULL,
    model_version TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (evaluation_id, record_id, split_name)
);

CREATE TABLE IF NOT EXISTS simulated_executions (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    prediction_id TEXT,
    market_id TEXT NOT NULL,
    signal_timestamp TIMESTAMPTZ NOT NULL,
    order_timestamp TIMESTAMPTZ NOT NULL,
    snapshot_timestamp TIMESTAMPTZ NOT NULL,
    market_snapshot_json TEXT NOT NULL,
    contract_side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    fill_state TEXT NOT NULL,
    intended_price_cents DOUBLE PRECISION NOT NULL,
    simulated_fill_price_cents DOUBLE PRECISION,
    requested_quantity INTEGER NOT NULL,
    filled_quantity INTEGER NOT NULL,
    unfilled_quantity INTEGER NOT NULL,
    fee_estimate_cents DOUBLE PRECISION NOT NULL,
    slippage_cents DOUBLE PRECISION NOT NULL,
    fee_schedule_version TEXT NOT NULL,
    liquidity_role TEXT,
    rejection_reason TEXT,
    final_payout_cents DOUBLE PRECISION,
    gross_return_cents DOUBLE PRECISION,
    net_return_cents DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exposure_decisions (
    id BIGSERIAL PRIMARY KEY,
    portfolio_run_id TEXT NOT NULL,
    prediction_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    category TEXT NOT NULL,
    underlying_id TEXT,
    correlation_group TEXT NOT NULL,
    accepted BOOLEAN NOT NULL,
    reasons_json TEXT NOT NULL,
    raw_capital_at_risk_cents DOUBLE PRECISION NOT NULL,
    accepted_capital_at_risk_cents DOUBLE PRECISION NOT NULL,
    limits_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (portfolio_run_id, prediction_id)
);

CREATE TABLE IF NOT EXISTS worker_status (
    worker_name TEXT PRIMARY KEY,
    asset_class TEXT NOT NULL,
    current_run_id TEXT,
    status TEXT NOT NULL,
    last_attempted_at TIMESTAMPTZ,
    last_successful_at TIMESTAMPTZ,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    total_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    data_fresh_at TIMESTAMPTZ,
    source_fresh_at TIMESTAMPTZ,
    pending_settlements INTEGER NOT NULL DEFAULT 0,
    model_state TEXT,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS worker_runs (
    id BIGSERIAL PRIMARY KEY,
    worker_name TEXT NOT NULL,
    run_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    records_processed INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (worker_name, idempotency_key)
);

CREATE TABLE IF NOT EXISTS connector_health (
    connector_name TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'configured_healthy', 'configured_degraded', 'configured_failed',
        'unconfigured_optional', 'missing_required'
    )),
    last_attempted_at TIMESTAMPTZ,
    last_successful_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    failure_reason TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (connector_name, asset_class)
);

CREATE TABLE IF NOT EXISTS app_users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_algorithm TEXT NOT NULL DEFAULT 'scrypt',
    role TEXT NOT NULL CHECK (role IN ('admin', 'researcher', 'read_only')),
    is_disabled BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_sessions (
    session_id_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app_users(id),
    csrf_token_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS login_audit (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL,
    successful BOOLEAN NOT NULL,
    failure_reason TEXT,
    remote_address_hash TEXT,
    user_agent_hash TEXT
);

CREATE TABLE IF NOT EXISTS migration_imports (
    export_id TEXT PRIMARY KEY,
    source_manifest_json TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prediction_logs_timestamp ON prediction_logs(prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_prediction_logs_market ON prediction_logs(market_id, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_prediction_logs_settlement ON prediction_logs(settlement_state, settlement_updated_at);
CREATE INDEX IF NOT EXISTS idx_prediction_logs_model ON prediction_logs(model_version, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_prediction_rejections_run ON prediction_rejections(run_id, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_crypto_prediction_time ON crypto_prediction_logs(symbol, horizon, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_crypto_settlement ON crypto_prediction_logs(settlement_state, settlement_time);
CREATE INDEX IF NOT EXISTS idx_sports_prediction_time ON sports_prediction_logs(event_id, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_sports_settlement ON sports_prediction_logs(settlement_state, game_start_time);
CREATE INDEX IF NOT EXISTS idx_model_evaluations_version ON model_evaluations(model_version, dataset_version, feature_version);
CREATE INDEX IF NOT EXISTS idx_model_evaluation_predictions_time ON model_evaluation_predictions(prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_simulated_executions_run ON simulated_executions(run_id, order_timestamp);
CREATE INDEX IF NOT EXISTS idx_exposure_decisions_group ON exposure_decisions(correlation_group, created_at);
CREATE INDEX IF NOT EXISTS idx_worker_runs_status ON worker_runs(worker_name, status, attempted_at);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON app_sessions(expires_at, revoked_at);
CREATE INDEX IF NOT EXISTS idx_login_audit_username ON login_audit(username, attempted_at);
