-- Cloud-owned live sports snapshots and refresh requests.
--
-- The web service only enqueues work. Railway workers claim these rows and
-- write source-backed results to PostgreSQL, so neither a browser request nor
-- the owner's laptop becomes a data collector.

CREATE TABLE IF NOT EXISTS core.source_live_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    source_milestone_id TEXT NOT NULL,
    live_data_type TEXT,
    competition TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    details JSONB NOT NULL,
    player_stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    snapshot_hash TEXT NOT NULL,
    raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    ingestion_batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, source_milestone_id, snapshot_hash)
);

CREATE INDEX IF NOT EXISTS idx_source_live_snapshots_current
    ON core.source_live_snapshots (source, source_milestone_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS ops.source_refresh_requests (
    request_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    sources JSONB NOT NULL,
    scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 100,
    not_before TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result JSONB,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (jsonb_typeof(sources) = 'array' AND jsonb_array_length(sources) > 0),
    CHECK (jsonb_typeof(scope) = 'object'),
    CHECK (reason IN ('manual', 'scheduled', 'pregame')),
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'blocked')),
    CHECK (priority BETWEEN 1 AND 1000),
    CHECK (attempt_count >= 0),
    CHECK (max_attempts BETWEEN 1 AND 10)
);

CREATE INDEX IF NOT EXISTS idx_source_refresh_requests_claim
    ON ops.source_refresh_requests (status, not_before, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_source_refresh_requests_lease
    ON ops.source_refresh_requests (lease_expires_at)
    WHERE status = 'running';
