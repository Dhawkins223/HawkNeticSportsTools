CREATE TABLE IF NOT EXISTS model_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    evaluation_timestamp TEXT NOT NULL,
    training_start TEXT,
    training_end TEXT,
    validation_start TEXT,
    validation_end TEXT,
    test_start TEXT,
    test_end TEXT,
    sample_size INTEGER NOT NULL,
    brier_score REAL,
    log_loss REAL,
    calibration_error REAL,
    accuracy REAL,
    accuracy_ci_low REAL,
    accuracy_ci_high REAL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_evaluation_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    split_name TEXT NOT NULL CHECK (split_name IN ('train', 'validation', 'test')),
    prediction_timestamp TEXT NOT NULL,
    model_probability REAL,
    market_implied_probability REAL NOT NULL,
    probability_difference REAL,
    actual_outcome INTEGER NOT NULL CHECK (actual_outcome IN (0, 1)),
    model_version TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (evaluation_id, record_id, split_name),
    FOREIGN KEY (evaluation_id) REFERENCES model_evaluations(evaluation_id)
);

CREATE TABLE IF NOT EXISTS simulated_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    prediction_id TEXT,
    market_id TEXT NOT NULL,
    signal_timestamp TEXT NOT NULL,
    order_timestamp TEXT NOT NULL,
    snapshot_timestamp TEXT NOT NULL,
    market_snapshot_json TEXT NOT NULL,
    contract_side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    fill_state TEXT NOT NULL,
    intended_price_cents REAL NOT NULL,
    simulated_fill_price_cents REAL,
    requested_quantity INTEGER NOT NULL,
    filled_quantity INTEGER NOT NULL,
    unfilled_quantity INTEGER NOT NULL,
    fee_estimate_cents REAL NOT NULL,
    slippage_cents REAL NOT NULL,
    fee_schedule_version TEXT NOT NULL,
    liquidity_role TEXT,
    rejection_reason TEXT,
    final_payout_cents REAL,
    gross_return_cents REAL,
    net_return_cents REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exposure_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_run_id TEXT NOT NULL,
    prediction_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    category TEXT NOT NULL,
    underlying_id TEXT,
    correlation_group TEXT NOT NULL,
    accepted INTEGER NOT NULL CHECK (accepted IN (0, 1)),
    reasons_json TEXT NOT NULL,
    raw_capital_at_risk_cents REAL NOT NULL,
    accepted_capital_at_risk_cents REAL NOT NULL,
    limits_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (portfolio_run_id, prediction_id)
);

CREATE TABLE IF NOT EXISTS worker_status (
    worker_name TEXT PRIMARY KEY,
    asset_class TEXT NOT NULL,
    current_run_id TEXT,
    status TEXT NOT NULL,
    last_attempted_at TEXT,
    last_successful_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    total_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    data_fresh_at TEXT,
    source_fresh_at TEXT,
    pending_settlements INTEGER NOT NULL DEFAULT 0,
    model_state TEXT,
    heartbeat_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS worker_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_name TEXT NOT NULL,
    run_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    finished_at TEXT,
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
    last_attempted_at TEXT,
    last_successful_at TEXT,
    last_failure_at TEXT,
    failure_reason TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (connector_name, asset_class)
);

CREATE TABLE IF NOT EXISTS app_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_algorithm TEXT NOT NULL DEFAULT 'scrypt',
    role TEXT NOT NULL CHECK (role IN ('admin', 'researcher', 'read_only')),
    is_disabled INTEGER NOT NULL DEFAULT 0 CHECK (is_disabled IN (0, 1)),
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_sessions (
    session_id_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    csrf_token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES app_users(id)
);

CREATE TABLE IF NOT EXISTS login_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    successful INTEGER NOT NULL CHECK (successful IN (0, 1)),
    failure_reason TEXT,
    remote_address_hash TEXT,
    user_agent_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_prediction_logs_timestamp ON prediction_logs(prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_prediction_logs_market ON prediction_logs(market_id, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_prediction_logs_settlement ON prediction_logs(settlement_state, settlement_updated_at);
CREATE INDEX IF NOT EXISTS idx_prediction_logs_model ON prediction_logs(model_version, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_prediction_rejections_run ON prediction_rejections(run_id, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_model_evaluations_version ON model_evaluations(model_version, dataset_version, feature_version);
CREATE INDEX IF NOT EXISTS idx_model_evaluation_predictions_time ON model_evaluation_predictions(prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_simulated_executions_run ON simulated_executions(run_id, order_timestamp);
CREATE INDEX IF NOT EXISTS idx_exposure_decisions_group ON exposure_decisions(correlation_group, created_at);
CREATE INDEX IF NOT EXISTS idx_worker_runs_status ON worker_runs(worker_name, status, attempted_at);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON app_sessions(expires_at, revoked_at);
CREATE INDEX IF NOT EXISTS idx_login_audit_username ON login_audit(username, attempted_at);
