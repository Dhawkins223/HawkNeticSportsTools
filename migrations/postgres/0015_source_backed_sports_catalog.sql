-- Source-backed sports reference data and external venue observations.
--
-- These tables deliberately keep source identities separate. A Kalshi target
-- and a Polymarket participant are not declared to be the same person or team
-- until an explicit, reviewable mapping exists. Every normalized row points
-- back to the retained raw response that produced it.

CREATE TABLE IF NOT EXISTS core.source_sports (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    source_sport_id TEXT NOT NULL,
    sport_code TEXT NOT NULL,
    display_name TEXT NOT NULL,
    ordering TEXT,
    primary_tag_id TEXT,
    series_id TEXT,
    resolution_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, source_sport_id),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE INDEX IF NOT EXISTS idx_source_sports_code
    ON core.source_sports (source, sport_code);

CREATE TABLE IF NOT EXISTS core.source_entities (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    competition TEXT,
    source_id TEXT,
    source_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_updated_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, source_entity_id),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE INDEX IF NOT EXISTS idx_source_entities_type_competition
    ON core.source_entities (source, entity_type, competition, display_name);

CREATE TABLE IF NOT EXISTS core.source_entity_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_entity_id BIGINT NOT NULL REFERENCES core.source_entities(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ,
    details JSONB NOT NULL,
    snapshot_hash TEXT NOT NULL,
    raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    ingestion_batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_entity_id, snapshot_hash)
);

CREATE INDEX IF NOT EXISTS idx_source_entity_snapshots_observed
    ON core.source_entity_snapshots (source_entity_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS core.source_milestones (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    source_milestone_id TEXT NOT NULL,
    category TEXT NOT NULL,
    milestone_type TEXT NOT NULL,
    title TEXT NOT NULL,
    notification_message TEXT,
    competition TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    primary_event_tickers JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_event_tickers JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_id TEXT,
    source_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_updated_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, source_milestone_id),
    CHECK (last_seen_at >= first_seen_at),
    CHECK (end_time IS NULL OR start_time IS NULL OR end_time >= start_time)
);

CREATE INDEX IF NOT EXISTS idx_source_milestones_schedule
    ON core.source_milestones (category, competition, start_time DESC);

CREATE TABLE IF NOT EXISTS core.source_assets (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    owner_source_id TEXT NOT NULL,
    asset_kind TEXT NOT NULL,
    asset_url TEXT NOT NULL,
    source_page_url TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, owner_type, owner_source_id, asset_kind, asset_url)
);

CREATE INDEX IF NOT EXISTS idx_source_assets_owner
    ON core.source_assets (source, owner_type, owner_source_id);

CREATE TABLE IF NOT EXISTS core.external_markets (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue TEXT NOT NULL,
    source_market_id TEXT NOT NULL,
    source_event_id TEXT,
    condition_id TEXT,
    game_id TEXT,
    slug TEXT,
    question TEXT NOT NULL,
    description TEXT,
    market_type TEXT,
    line NUMERIC(30, 12),
    active BOOLEAN,
    closed BOOLEAN NOT NULL DEFAULT FALSE,
    game_start_time TIMESTAMPTZ,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (venue, source_market_id),
    CHECK (last_seen_at >= first_seen_at),
    CHECK (end_time IS NULL OR start_time IS NULL OR end_time >= start_time)
);

CREATE INDEX IF NOT EXISTS idx_external_markets_live
    ON core.external_markets (venue, closed, active, game_start_time);

CREATE INDEX IF NOT EXISTS idx_external_markets_type
    ON core.external_markets (venue, market_type, game_start_time);

CREATE TABLE IF NOT EXISTS core.external_market_observations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_market_id BIGINT NOT NULL REFERENCES core.external_markets(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ NOT NULL,
    best_bid NUMERIC(12, 8) CHECK (best_bid IS NULL OR best_bid BETWEEN 0 AND 1),
    best_ask NUMERIC(12, 8) CHECK (best_ask IS NULL OR best_ask BETWEEN 0 AND 1),
    spread NUMERIC(12, 8) CHECK (spread IS NULL OR spread >= 0),
    last_trade_price NUMERIC(12, 8) CHECK (last_trade_price IS NULL OR last_trade_price BETWEEN 0 AND 1),
    price_sum NUMERIC(12, 8) NOT NULL CHECK (price_sum > 0),
    volume NUMERIC(30, 8) CHECK (volume IS NULL OR volume >= 0),
    liquidity NUMERIC(30, 8) CHECK (liquidity IS NULL OR liquidity >= 0),
    normalization TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    raw_payload_id BIGINT NOT NULL REFERENCES raw.source_payloads(id),
    ingestion_batch_id BIGINT NOT NULL REFERENCES raw.ingestion_batches(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (external_market_id, observed_at, snapshot_hash),
    CHECK (best_bid IS NULL OR best_ask IS NULL OR best_bid <= best_ask)
);

CREATE INDEX IF NOT EXISTS idx_external_market_observations_time
    ON core.external_market_observations (external_market_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS core.external_market_outcomes (
    observation_id BIGINT NOT NULL REFERENCES core.external_market_observations(id) ON DELETE CASCADE,
    outcome_position INTEGER NOT NULL CHECK (outcome_position >= 0),
    outcome_name TEXT NOT NULL,
    price NUMERIC(12, 8) NOT NULL CHECK (price BETWEEN 0 AND 1),
    normalized_probability NUMERIC(12, 8) NOT NULL CHECK (normalized_probability BETWEEN 0 AND 1),
    source_token_id TEXT,
    PRIMARY KEY (observation_id, outcome_position),
    UNIQUE (observation_id, outcome_name)
);
