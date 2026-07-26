CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS archive;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'source_records', 'edge_results', 'prediction_logs', 'paper_test_runs',
        'prediction_rejections', 'settlement_audit', 'crypto_prediction_logs',
        'crypto_prediction_rejections', 'sports_prediction_logs',
        'sports_prediction_rejections', 'model_evaluations',
        'model_evaluation_predictions', 'simulated_executions',
        'exposure_decisions', 'worker_status', 'worker_runs', 'connector_health',
        'migration_imports'
    ] LOOP
        IF to_regclass('public.' || table_name) IS NOT NULL
           AND to_regclass('app.' || table_name) IS NULL THEN
            EXECUTE format('ALTER TABLE public.%I SET SCHEMA app', table_name);
        END IF;
    END LOOP;

    IF to_regclass('public.operator_messages') IS NOT NULL
       AND to_regclass('ops.operator_messages') IS NULL THEN
        ALTER TABLE public.operator_messages SET SCHEMA ops;
    END IF;

    FOREACH table_name IN ARRAY ARRAY['app_users', 'app_sessions', 'login_audit'] LOOP
        IF to_regclass('public.' || table_name) IS NOT NULL
           AND to_regclass('app.' || table_name) IS NULL THEN
            EXECUTE format('ALTER TABLE public.%I SET SCHEMA app', table_name);
        END IF;
        IF to_regclass('app.' || table_name) IS NOT NULL
           AND to_regclass('auth.' || table_name) IS NULL THEN
            EXECUTE format('ALTER TABLE app.%I SET SCHEMA auth', table_name);
        END IF;
    END LOOP;
END $$;

-- Preserve the identity of rows written by the pre-cutover PostgreSQL
-- collection ledger while moving their current representation into the
-- authoritative normalized relations.
ALTER TABLE raw.ingestion_batches
    ADD COLUMN IF NOT EXISTS legacy_batch_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_ingestion_batches_legacy_batch_id
    ON raw.ingestion_batches (legacy_batch_id)
    WHERE legacy_batch_id IS NOT NULL;

ALTER TABLE raw.source_payloads
    ADD COLUMN IF NOT EXISTS legacy_payload_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_source_payloads_legacy_payload_id
    ON raw.source_payloads (legacy_payload_id)
    WHERE legacy_payload_id IS NOT NULL;

ALTER TABLE raw.rejected_records
    ADD COLUMN IF NOT EXISTS legacy_rejection_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_rejected_records_legacy_rejection_id
    ON raw.rejected_records (legacy_rejection_id)
    WHERE legacy_rejection_id IS NOT NULL;

ALTER TABLE ops.data_quality_results
    ADD COLUMN IF NOT EXISTS legacy_result_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_data_quality_results_legacy_result_id
    ON ops.data_quality_results (legacy_result_id)
    WHERE legacy_result_id IS NOT NULL;

ALTER TABLE ops.audit_events
    ADD COLUMN IF NOT EXISTS legacy_event_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_audit_events_legacy_event_id
    ON ops.audit_events (legacy_event_id)
    WHERE legacy_event_id IS NOT NULL;

ALTER TABLE ops.backfill_jobs
    ADD COLUMN IF NOT EXISTS legacy_job_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_backfill_jobs_legacy_job_id
    ON ops.backfill_jobs (legacy_job_id)
    WHERE legacy_job_id IS NOT NULL;

ALTER TABLE ops.report_refreshes
    ADD COLUMN IF NOT EXISTS legacy_refresh_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_report_refreshes_legacy_refresh_id
    ON ops.report_refreshes (legacy_refresh_id)
    WHERE legacy_refresh_id IS NOT NULL;

DO $$
BEGIN
    IF to_regclass('public.ingestion_batches') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM public.ingestion_batches AS legacy
            JOIN raw.ingestion_batches AS target
              ON target.idempotency_key = legacy.idempotency_key
            WHERE target.source IS DISTINCT FROM legacy.source
               OR target.endpoint IS DISTINCT FROM legacy.endpoint
               OR target.worker_name IS DISTINCT FROM legacy.worker_name
               OR target.worker_version IS DISTINCT FROM legacy.worker_version
               OR target.collector_version IS DISTINCT FROM legacy.collector_version
               OR target.collection_mode IS DISTINCT FROM legacy.collection_mode
               OR target.request_parameters IS DISTINCT FROM legacy.request_parameters_json::jsonb
               OR target.started_at IS DISTINCT FROM legacy.started_at
               OR target.status IS DISTINCT FROM legacy.status
        ) THEN
            RAISE EXCEPTION 'legacy_collection_batch_content_conflict';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.raw_source_payloads AS legacy
            JOIN public.ingestion_batches AS legacy_batch
              ON legacy_batch.batch_id = legacy.batch_id
            JOIN raw.ingestion_batches AS batch
              ON batch.idempotency_key = legacy_batch.idempotency_key
            JOIN raw.source_payloads AS target
              ON target.batch_id = batch.id
             AND target.source_identifier IS NOT DISTINCT FROM legacy.source_identifier
             AND target.content_hash = legacy.content_hash
            WHERE jsonb_build_object(
                'source', target.source,
                'entity_type', target.entity_type,
                'source_identifier', target.source_identifier,
                'observed_at', target.observed_at,
                'received_at', target.received_at,
                'content_hash', target.content_hash,
                'payload_json', target.payload_json,
                'parser_version', target.parser_version,
                'created_at', target.created_at
            ) IS DISTINCT FROM jsonb_build_object(
                'source', legacy.source,
                'entity_type', legacy.entity_type,
                'source_identifier', legacy.source_identifier,
                'observed_at', legacy.observed_at,
                'received_at', legacy.received_at,
                'content_hash', legacy.content_hash,
                'payload_json', legacy.payload_json::jsonb,
                'parser_version', legacy.parser_version,
                'created_at', legacy.created_at
            )
        ) THEN
            RAISE EXCEPTION 'legacy_source_payload_content_conflict';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.rejected_records AS legacy
            JOIN public.ingestion_batches AS legacy_batch
              ON legacy_batch.batch_id = legacy.batch_id
            JOIN raw.ingestion_batches AS batch
              ON batch.idempotency_key = legacy_batch.idempotency_key
            LEFT JOIN raw.source_payloads AS payload
              ON payload.legacy_payload_id = legacy.payload_id
            JOIN raw.rejected_records AS target
              ON target.legacy_rejection_id = legacy.rejection_id
            WHERE jsonb_build_object(
                'batch_id', target.batch_id,
                'raw_payload_id', target.raw_payload_id,
                'entity_type', target.entity_type,
                'rejection_code', target.rejection_code,
                'rejection_detail', target.rejection_detail,
                'parser_version', target.parser_version,
                'rejected_at', target.rejected_at,
                'resolved_at', target.resolved_at,
                'resolution', target.resolution
            ) IS DISTINCT FROM jsonb_build_object(
                'batch_id', batch.id,
                'raw_payload_id', payload.id,
                'entity_type', legacy.entity_type,
                'rejection_code', legacy.rejection_code,
                'rejection_detail', legacy.rejection_detail,
                'parser_version', legacy.parser_version,
                'rejected_at', legacy.rejected_at,
                'resolved_at', legacy.resolved_at,
                'resolution', legacy.resolution
            )
        ) THEN
            RAISE EXCEPTION 'legacy_rejected_record_content_conflict';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.collection_checkpoints AS legacy
            JOIN public.ingestion_batches AS legacy_batch
              ON legacy_batch.batch_id = legacy.batch_id
            JOIN raw.ingestion_batches AS batch
              ON batch.idempotency_key = legacy_batch.idempotency_key
            JOIN ops.collection_checkpoints AS target
              ON target.source = legacy.source
             AND target.endpoint = legacy.endpoint
             AND target.partition_scope = legacy.partition_scope
            WHERE jsonb_build_object(
                'cursor', target.cursor,
                'window_start', target.window_start,
                'window_end', target.window_end,
                'last_successful_item_time', target.last_successful_item_time,
                'ingestion_batch_id', target.ingestion_batch_id,
                'updated_at', target.updated_at
            ) IS DISTINCT FROM jsonb_build_object(
                'cursor', legacy.cursor,
                'window_start', legacy.window_start,
                'window_end', legacy.window_end,
                'last_successful_item_time', legacy.last_successful_item_time,
                'ingestion_batch_id', batch.id,
                'updated_at', legacy.updated_at
            )
        ) THEN
            RAISE EXCEPTION 'legacy_collection_checkpoint_content_conflict';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.source_health AS legacy
            JOIN ops.source_health AS target ON target.source = legacy.source
            WHERE jsonb_build_object(
                'last_attempted_at', target.last_attempted_at,
                'last_successful_at', target.last_successful_at,
                'freshness_deadline', target.freshness_deadline,
                'freshness_state', target.freshness_state,
                'consecutive_failures', target.consecutive_failures,
                'last_error', target.last_error,
                'updated_at', target.updated_at
            ) IS DISTINCT FROM jsonb_build_object(
                'last_attempted_at', legacy.last_attempted_at,
                'last_successful_at', legacy.last_successful_at,
                'freshness_deadline', legacy.freshness_deadline,
                'freshness_state', legacy.freshness_state,
                'consecutive_failures', legacy.consecutive_failures,
                'last_error', legacy.last_error,
                'updated_at', legacy.updated_at
            )
        ) THEN
            RAISE EXCEPTION 'legacy_source_health_content_conflict';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.data_quality_results AS legacy
            LEFT JOIN public.ingestion_batches AS legacy_batch
              ON legacy_batch.batch_id = legacy.batch_id
            LEFT JOIN raw.ingestion_batches AS batch
              ON batch.idempotency_key = legacy_batch.idempotency_key
            JOIN ops.data_quality_results AS target
              ON target.legacy_result_id = legacy.result_id
            WHERE jsonb_build_object(
                'ingestion_batch_id', target.ingestion_batch_id,
                'check_name', target.check_name,
                'status', target.status,
                'details', target.details,
                'checked_at', target.checked_at
            ) IS DISTINCT FROM jsonb_build_object(
                'ingestion_batch_id', batch.id,
                'check_name', legacy.check_name,
                'status', legacy.status,
                'details', legacy.details_json::jsonb,
                'checked_at', legacy.checked_at
            )
        ) THEN
            RAISE EXCEPTION 'legacy_data_quality_content_conflict';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.audit_events AS legacy
            JOIN ops.audit_events AS target
              ON target.legacy_event_id = legacy.event_id
            WHERE jsonb_build_object(
                'event_type', target.event_type,
                'actor', target.actor,
                'entity_type', target.entity_type,
                'entity_id', target.entity_id,
                'details', target.details,
                'created_at', target.created_at
            ) IS DISTINCT FROM jsonb_build_object(
                'event_type', legacy.event_type,
                'actor', legacy.actor,
                'entity_type', legacy.entity_type,
                'entity_id', legacy.entity_id,
                'details', legacy.details_json::jsonb,
                'created_at', legacy.created_at
            )
        ) THEN
            RAISE EXCEPTION 'legacy_audit_event_content_conflict';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.backfill_jobs AS legacy
            JOIN ops.backfill_jobs AS target
              ON target.legacy_job_id = legacy.job_id
            WHERE jsonb_build_object(
                'source', target.source,
                'endpoint', target.endpoint,
                'window_start', target.window_start,
                'window_end', target.window_end,
                'status', target.status,
                'checkpoint', target.checkpoint,
                'created_at', target.created_at,
                'updated_at', target.updated_at
            ) IS DISTINCT FROM jsonb_build_object(
                'source', legacy.source,
                'endpoint', legacy.endpoint,
                'window_start', legacy.window_start,
                'window_end', legacy.window_end,
                'status', legacy.status,
                'checkpoint', legacy.checkpoint,
                'created_at', legacy.created_at,
                'updated_at', legacy.updated_at
            )
        ) THEN
            RAISE EXCEPTION 'legacy_backfill_job_content_conflict';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM public.report_refreshes AS legacy
            JOIN ops.report_refreshes AS target
              ON target.legacy_refresh_id = legacy.refresh_id
            WHERE jsonb_build_object(
                'report_name', target.report_name,
                'data_cutoff_at', target.data_cutoff_at,
                'started_at', target.started_at,
                'completed_at', target.completed_at,
                'status', target.status,
                'row_count', target.row_count,
                'error_code', target.error_code
            ) IS DISTINCT FROM jsonb_build_object(
                'report_name', legacy.report_name,
                'data_cutoff_at', legacy.data_cutoff_at,
                'started_at', legacy.started_at,
                'completed_at', legacy.completed_at,
                'status', legacy.status,
                'row_count', legacy.row_count,
                'error_code', legacy.error_code
            )
        ) THEN
            RAISE EXCEPTION 'legacy_report_refresh_content_conflict';
        END IF;

        INSERT INTO raw.ingestion_batches (
            legacy_batch_id, idempotency_key, source, endpoint, worker_name,
            worker_version, collector_version, collection_mode,
            request_parameters, cursor_start, cursor_end, window_start,
            window_end, started_at, completed_at, status, http_status,
            records_received, records_accepted, records_rejected,
            records_duplicated, payload_hash, error_code, error_message,
            created_at
        )
        SELECT
            legacy.batch_id, legacy.idempotency_key, legacy.source,
            legacy.endpoint, legacy.worker_name, legacy.worker_version,
            legacy.collector_version, legacy.collection_mode,
            legacy.request_parameters_json::jsonb, legacy.cursor_start,
            legacy.cursor_end, legacy.window_start, legacy.window_end,
            legacy.started_at, legacy.completed_at, legacy.status,
            legacy.http_status, legacy.records_received,
            legacy.records_accepted, legacy.records_rejected,
            legacy.records_duplicated, legacy.payload_hash, legacy.error_code,
            legacy.error_message, legacy.created_at
        FROM public.ingestion_batches AS legacy
        WHERE NOT EXISTS (
            SELECT 1
            FROM raw.ingestion_batches AS target
            WHERE target.idempotency_key = legacy.idempotency_key
        );

        IF EXISTS (
            SELECT 1
            FROM public.raw_source_payloads AS legacy
            JOIN public.ingestion_batches AS legacy_batch
              ON legacy_batch.batch_id = legacy.batch_id
            JOIN raw.ingestion_batches AS batch
              ON batch.idempotency_key = legacy_batch.idempotency_key
            JOIN raw.source_payloads AS target
              ON target.batch_id = batch.id
             AND target.source_identifier IS NOT DISTINCT FROM legacy.source_identifier
             AND target.content_hash = legacy.content_hash
            WHERE target.legacy_payload_id IS NOT NULL
              AND target.legacy_payload_id IS DISTINCT FROM legacy.payload_id
        ) THEN
            RAISE EXCEPTION 'legacy_source_payload_identity_conflict';
        END IF;

        UPDATE raw.source_payloads AS target
        SET legacy_payload_id = legacy.payload_id
        FROM public.raw_source_payloads AS legacy
        JOIN public.ingestion_batches AS legacy_batch
          ON legacy_batch.batch_id = legacy.batch_id
        JOIN raw.ingestion_batches AS batch
          ON batch.idempotency_key = legacy_batch.idempotency_key
        WHERE target.batch_id = batch.id
          AND target.source_identifier IS NOT DISTINCT FROM legacy.source_identifier
          AND target.content_hash = legacy.content_hash
          AND target.legacy_payload_id IS NULL;

        INSERT INTO raw.source_payloads (
            legacy_payload_id, batch_id, source, entity_type,
            source_identifier, observed_at, received_at, content_hash,
            payload_json, parser_version, created_at
        )
        SELECT
            legacy.payload_id, batch.id, legacy.source, legacy.entity_type,
            legacy.source_identifier, legacy.observed_at, legacy.received_at,
            legacy.content_hash, legacy.payload_json::jsonb,
            legacy.parser_version, legacy.created_at
        FROM public.raw_source_payloads AS legacy
        JOIN public.ingestion_batches AS legacy_batch
          ON legacy_batch.batch_id = legacy.batch_id
        JOIN raw.ingestion_batches AS batch
          ON batch.idempotency_key = legacy_batch.idempotency_key
        WHERE NOT EXISTS (
            SELECT 1
            FROM raw.source_payloads AS target
            WHERE target.batch_id = batch.id
              AND target.source_identifier IS NOT DISTINCT FROM legacy.source_identifier
              AND target.content_hash = legacy.content_hash
        );

        INSERT INTO raw.rejected_records (
            legacy_rejection_id, batch_id, raw_payload_id, entity_type,
            rejection_code, rejection_detail, parser_version, rejected_at,
            resolved_at, resolution
        )
        SELECT
            legacy.rejection_id, batch.id, payload.id, legacy.entity_type,
            legacy.rejection_code, legacy.rejection_detail,
            legacy.parser_version, legacy.rejected_at, legacy.resolved_at,
            legacy.resolution
        FROM public.rejected_records AS legacy
        JOIN public.ingestion_batches AS legacy_batch
          ON legacy_batch.batch_id = legacy.batch_id
        JOIN raw.ingestion_batches AS batch
          ON batch.idempotency_key = legacy_batch.idempotency_key
        LEFT JOIN raw.source_payloads AS payload
          ON payload.legacy_payload_id = legacy.payload_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM raw.rejected_records AS target
            WHERE target.legacy_rejection_id = legacy.rejection_id
        );

        INSERT INTO ops.collection_checkpoints (
            source, endpoint, partition_scope, cursor, window_start,
            window_end, last_successful_item_time, ingestion_batch_id,
            updated_at
        )
        SELECT
            legacy.source, legacy.endpoint, legacy.partition_scope,
            legacy.cursor, legacy.window_start, legacy.window_end,
            legacy.last_successful_item_time, batch.id, legacy.updated_at
        FROM public.collection_checkpoints AS legacy
        JOIN public.ingestion_batches AS legacy_batch
          ON legacy_batch.batch_id = legacy.batch_id
        JOIN raw.ingestion_batches AS batch
          ON batch.idempotency_key = legacy_batch.idempotency_key
        WHERE NOT EXISTS (
            SELECT 1
            FROM ops.collection_checkpoints AS target
            WHERE target.source = legacy.source
              AND target.endpoint = legacy.endpoint
              AND target.partition_scope = legacy.partition_scope
        );

        INSERT INTO ops.source_health (
            source, last_attempted_at, last_successful_at, freshness_deadline,
            freshness_state, consecutive_failures, last_error, updated_at
        )
        SELECT
            source, last_attempted_at, last_successful_at, freshness_deadline,
            freshness_state, consecutive_failures, last_error, updated_at
        FROM public.source_health AS legacy
        WHERE NOT EXISTS (
            SELECT 1
            FROM ops.source_health AS target
            WHERE target.source = legacy.source
        );

        INSERT INTO ops.data_quality_results (
            legacy_result_id, ingestion_batch_id, check_name, status, details,
            checked_at
        )
        SELECT
            legacy.result_id, batch.id, legacy.check_name, legacy.status,
            legacy.details_json::jsonb, legacy.checked_at
        FROM public.data_quality_results AS legacy
        LEFT JOIN public.ingestion_batches AS legacy_batch
          ON legacy_batch.batch_id = legacy.batch_id
        LEFT JOIN raw.ingestion_batches AS batch
          ON batch.idempotency_key = legacy_batch.idempotency_key
        WHERE NOT EXISTS (
            SELECT 1
            FROM ops.data_quality_results AS target
            WHERE target.legacy_result_id = legacy.result_id
        );

        INSERT INTO ops.audit_events (
            legacy_event_id, event_type, actor, entity_type, entity_id,
            details, created_at
        )
        SELECT
            event_id, event_type, actor, entity_type, entity_id,
            details_json::jsonb, created_at
        FROM public.audit_events AS legacy
        WHERE NOT EXISTS (
            SELECT 1
            FROM ops.audit_events AS target
            WHERE target.legacy_event_id = legacy.event_id
        );

        INSERT INTO ops.backfill_jobs (
            legacy_job_id, source, endpoint, window_start, window_end, status,
            checkpoint, created_at, updated_at
        )
        SELECT
            job_id, source, endpoint, window_start, window_end, status,
            checkpoint, created_at, updated_at
        FROM public.backfill_jobs AS legacy
        WHERE NOT EXISTS (
            SELECT 1
            FROM ops.backfill_jobs AS target
            WHERE target.legacy_job_id = legacy.job_id
        );

        INSERT INTO ops.report_refreshes (
            legacy_refresh_id, report_name, data_cutoff_at, started_at,
            completed_at, status, row_count, error_code
        )
        SELECT
            refresh_id, report_name, data_cutoff_at, started_at, completed_at,
            status, row_count, error_code
        FROM public.report_refreshes AS legacy
        WHERE NOT EXISTS (
            SELECT 1
            FROM ops.report_refreshes AS target
            WHERE target.legacy_refresh_id = legacy.refresh_id
        );
    END IF;
END $$;

DO $$
DECLARE
    table_name TEXT;
    archived_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'ingestion_batches', 'raw_source_payloads', 'rejected_records'
    ] LOOP
        archived_name := 'legacy_0005_' || table_name;
        IF to_regclass('public.' || table_name) IS NOT NULL
           AND to_regclass('archive.' || archived_name) IS NULL THEN
            EXECUTE format('ALTER TABLE public.%I RENAME TO %I', table_name, archived_name);
            EXECUTE format('ALTER TABLE public.%I SET SCHEMA archive', archived_name);
        END IF;
    END LOOP;

    FOREACH table_name IN ARRAY ARRAY[
        'collection_checkpoints', 'source_health', 'data_quality_results',
        'audit_events', 'backfill_jobs', 'report_refreshes'
    ] LOOP
        archived_name := 'legacy_0005_' || table_name;
        IF to_regclass('public.' || table_name) IS NOT NULL
           AND to_regclass('archive.' || archived_name) IS NULL THEN
            EXECUTE format('ALTER TABLE public.%I RENAME TO %I', table_name, archived_name);
            EXECUTE format('ALTER TABLE public.%I SET SCHEMA archive', archived_name);
        END IF;
    END LOOP;
END $$;

ALTER TABLE app.source_records ALTER COLUMN metadata_json DROP DEFAULT;
ALTER TABLE app.source_records ALTER COLUMN metadata_json TYPE JSONB USING metadata_json::jsonb;
ALTER TABLE app.source_records ALTER COLUMN metadata_json SET DEFAULT '{}'::jsonb;

ALTER TABLE app.edge_results ALTER COLUMN model_probability TYPE NUMERIC(30, 12) USING model_probability::numeric;
ALTER TABLE app.edge_results ALTER COLUMN entry_price_cents TYPE NUMERIC(30, 12) USING entry_price_cents::numeric;
ALTER TABLE app.edge_results ALTER COLUMN fair_price_cents TYPE NUMERIC(30, 12) USING fair_price_cents::numeric;
ALTER TABLE app.edge_results ALTER COLUMN expected_value_cents TYPE NUMERIC(30, 12) USING expected_value_cents::numeric;
ALTER TABLE app.edge_results ALTER COLUMN notes_json DROP DEFAULT;
ALTER TABLE app.edge_results ALTER COLUMN notes_json TYPE JSONB USING notes_json::jsonb;
ALTER TABLE app.edge_results ALTER COLUMN notes_json SET DEFAULT '{}'::jsonb;

ALTER TABLE app.prediction_logs ALTER COLUMN input_data_json DROP DEFAULT;
ALTER TABLE app.prediction_logs ALTER COLUMN input_data_json TYPE JSONB USING input_data_json::jsonb;
ALTER TABLE app.prediction_logs ALTER COLUMN input_data_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.prediction_logs ALTER COLUMN odds_json DROP DEFAULT;
ALTER TABLE app.prediction_logs ALTER COLUMN odds_json TYPE JSONB USING odds_json::jsonb;
ALTER TABLE app.prediction_logs ALTER COLUMN odds_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.prediction_logs ALTER COLUMN reason_features_json DROP DEFAULT;
ALTER TABLE app.prediction_logs ALTER COLUMN reason_features_json TYPE JSONB USING reason_features_json::jsonb;
ALTER TABLE app.prediction_logs ALTER COLUMN reason_features_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.prediction_logs ALTER COLUMN validation_errors_json DROP DEFAULT;
ALTER TABLE app.prediction_logs ALTER COLUMN validation_errors_json TYPE JSONB USING validation_errors_json::jsonb;
ALTER TABLE app.prediction_logs ALTER COLUMN validation_errors_json SET DEFAULT '[]'::jsonb;
ALTER TABLE app.prediction_logs ALTER COLUMN confidence_score TYPE NUMERIC(30, 12) USING confidence_score::numeric;
ALTER TABLE app.prediction_logs ALTER COLUMN entry_price_cents TYPE NUMERIC(30, 12) USING entry_price_cents::numeric;
ALTER TABLE app.prediction_logs ALTER COLUMN implied_probability TYPE NUMERIC(30, 12) USING implied_probability::numeric;
ALTER TABLE app.prediction_logs ALTER COLUMN profit_loss_cents TYPE NUMERIC(30, 12) USING profit_loss_cents::numeric;

ALTER TABLE app.paper_test_runs ALTER COLUMN model_versions_json DROP DEFAULT;
ALTER TABLE app.paper_test_runs ALTER COLUMN model_versions_json TYPE JSONB USING model_versions_json::jsonb;
ALTER TABLE app.paper_test_runs ALTER COLUMN model_versions_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.paper_test_runs ALTER COLUMN config_json DROP DEFAULT;
ALTER TABLE app.paper_test_runs ALTER COLUMN config_json TYPE JSONB USING config_json::jsonb;
ALTER TABLE app.paper_test_runs ALTER COLUMN config_json SET DEFAULT '{}'::jsonb;

ALTER TABLE app.prediction_rejections ALTER COLUMN validation_errors_json DROP DEFAULT;
ALTER TABLE app.prediction_rejections ALTER COLUMN validation_errors_json TYPE JSONB USING validation_errors_json::jsonb;
ALTER TABLE app.prediction_rejections ALTER COLUMN validation_errors_json SET DEFAULT '[]'::jsonb;
ALTER TABLE app.prediction_rejections ALTER COLUMN raw_log_json DROP DEFAULT;
ALTER TABLE app.prediction_rejections ALTER COLUMN raw_log_json TYPE JSONB USING raw_log_json::jsonb;
ALTER TABLE app.prediction_rejections ALTER COLUMN raw_log_json SET DEFAULT '{}'::jsonb;

ALTER TABLE app.settlement_audit ALTER COLUMN previous_profit_loss_cents TYPE NUMERIC(30, 12) USING previous_profit_loss_cents::numeric;
ALTER TABLE app.settlement_audit ALTER COLUMN new_profit_loss_cents TYPE NUMERIC(30, 12) USING new_profit_loss_cents::numeric;
ALTER TABLE app.settlement_audit ALTER COLUMN raw_settlement_json DROP DEFAULT;
ALTER TABLE app.settlement_audit ALTER COLUMN raw_settlement_json TYPE JSONB USING raw_settlement_json::jsonb;
ALTER TABLE app.settlement_audit ALTER COLUMN raw_settlement_json SET DEFAULT '{}'::jsonb;

ALTER TABLE app.crypto_prediction_logs ALTER COLUMN entry_price TYPE NUMERIC(30, 12) USING entry_price::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN open TYPE NUMERIC(30, 12) USING open::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN high TYPE NUMERIC(30, 12) USING high::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN low TYPE NUMERIC(30, 12) USING low::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN close TYPE NUMERIC(30, 12) USING close::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN volume TYPE NUMERIC(30, 12) USING volume::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN bid TYPE NUMERIC(30, 12) USING bid::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN ask TYPE NUMERIC(30, 12) USING ask::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN mid_price TYPE NUMERIC(30, 12) USING mid_price::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN spread TYPE NUMERIC(30, 12) USING spread::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN implied_probability TYPE NUMERIC(30, 12) USING implied_probability::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN confidence_score TYPE NUMERIC(30, 12) USING confidence_score::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN settlement_price TYPE NUMERIC(30, 12) USING settlement_price::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN return_bps TYPE NUMERIC(30, 12) USING return_bps::numeric;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN features_json DROP DEFAULT;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN features_json TYPE JSONB USING features_json::jsonb;
ALTER TABLE app.crypto_prediction_logs ALTER COLUMN features_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.crypto_prediction_rejections ALTER COLUMN raw_log_json DROP DEFAULT;
ALTER TABLE app.crypto_prediction_rejections ALTER COLUMN raw_log_json TYPE JSONB USING raw_log_json::jsonb;
ALTER TABLE app.crypto_prediction_rejections ALTER COLUMN raw_log_json SET DEFAULT '{}'::jsonb;

ALTER TABLE app.sports_prediction_logs ALTER COLUMN line TYPE NUMERIC(30, 12) USING line::numeric;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN odds TYPE NUMERIC(30, 12) USING odds::numeric;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN confidence_score TYPE NUMERIC(30, 12) USING confidence_score::numeric;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN closing_line TYPE NUMERIC(30, 12) USING closing_line::numeric;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN clv TYPE NUMERIC(30, 12) USING clv::numeric;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN features_json DROP DEFAULT;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN features_json TYPE JSONB USING features_json::jsonb;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN features_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN final_score_json DROP DEFAULT;
ALTER TABLE app.sports_prediction_logs ALTER COLUMN final_score_json TYPE JSONB USING final_score_json::jsonb;
ALTER TABLE app.sports_prediction_rejections ALTER COLUMN raw_log_json DROP DEFAULT;
ALTER TABLE app.sports_prediction_rejections ALTER COLUMN raw_log_json TYPE JSONB USING raw_log_json::jsonb;
ALTER TABLE app.sports_prediction_rejections ALTER COLUMN raw_log_json SET DEFAULT '{}'::jsonb;

ALTER TABLE app.model_evaluations ALTER COLUMN brier_score TYPE NUMERIC(30, 16) USING brier_score::numeric;
ALTER TABLE app.model_evaluations ALTER COLUMN log_loss TYPE NUMERIC(30, 16) USING log_loss::numeric;
ALTER TABLE app.model_evaluations ALTER COLUMN calibration_error TYPE NUMERIC(30, 16) USING calibration_error::numeric;
ALTER TABLE app.model_evaluations ALTER COLUMN accuracy TYPE NUMERIC(30, 16) USING accuracy::numeric;
ALTER TABLE app.model_evaluations ALTER COLUMN accuracy_ci_low TYPE NUMERIC(30, 16) USING accuracy_ci_low::numeric;
ALTER TABLE app.model_evaluations ALTER COLUMN accuracy_ci_high TYPE NUMERIC(30, 16) USING accuracy_ci_high::numeric;
ALTER TABLE app.model_evaluations ALTER COLUMN evidence_json DROP DEFAULT;
ALTER TABLE app.model_evaluations ALTER COLUMN evidence_json TYPE JSONB USING evidence_json::jsonb;
ALTER TABLE app.model_evaluations ALTER COLUMN evidence_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.model_evaluation_predictions ALTER COLUMN model_probability TYPE NUMERIC(30, 16) USING model_probability::numeric;
ALTER TABLE app.model_evaluation_predictions ALTER COLUMN market_implied_probability TYPE NUMERIC(30, 16) USING market_implied_probability::numeric;
ALTER TABLE app.model_evaluation_predictions ALTER COLUMN probability_difference TYPE NUMERIC(30, 16) USING probability_difference::numeric;

ALTER TABLE app.simulated_executions ALTER COLUMN market_snapshot_json DROP DEFAULT;
ALTER TABLE app.simulated_executions ALTER COLUMN market_snapshot_json TYPE JSONB USING market_snapshot_json::jsonb;
ALTER TABLE app.simulated_executions ALTER COLUMN market_snapshot_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.simulated_executions ALTER COLUMN intended_price_cents TYPE NUMERIC(30, 12) USING intended_price_cents::numeric;
ALTER TABLE app.simulated_executions ALTER COLUMN simulated_fill_price_cents TYPE NUMERIC(30, 12) USING simulated_fill_price_cents::numeric;
ALTER TABLE app.simulated_executions ALTER COLUMN fee_estimate_cents TYPE NUMERIC(30, 12) USING fee_estimate_cents::numeric;
ALTER TABLE app.simulated_executions ALTER COLUMN slippage_cents TYPE NUMERIC(30, 12) USING slippage_cents::numeric;
ALTER TABLE app.simulated_executions ALTER COLUMN final_payout_cents TYPE NUMERIC(30, 12) USING final_payout_cents::numeric;
ALTER TABLE app.simulated_executions ALTER COLUMN gross_return_cents TYPE NUMERIC(30, 12) USING gross_return_cents::numeric;
ALTER TABLE app.simulated_executions ALTER COLUMN net_return_cents TYPE NUMERIC(30, 12) USING net_return_cents::numeric;
ALTER TABLE app.exposure_decisions ALTER COLUMN reasons_json DROP DEFAULT;
ALTER TABLE app.exposure_decisions ALTER COLUMN reasons_json TYPE JSONB USING reasons_json::jsonb;
ALTER TABLE app.exposure_decisions ALTER COLUMN reasons_json SET DEFAULT '[]'::jsonb;
ALTER TABLE app.exposure_decisions ALTER COLUMN limits_json DROP DEFAULT;
ALTER TABLE app.exposure_decisions ALTER COLUMN limits_json TYPE JSONB USING limits_json::jsonb;
ALTER TABLE app.exposure_decisions ALTER COLUMN limits_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.exposure_decisions ALTER COLUMN raw_capital_at_risk_cents TYPE NUMERIC(30, 12) USING raw_capital_at_risk_cents::numeric;
ALTER TABLE app.exposure_decisions ALTER COLUMN accepted_capital_at_risk_cents TYPE NUMERIC(30, 12) USING accepted_capital_at_risk_cents::numeric;
ALTER TABLE app.worker_status ALTER COLUMN details_json DROP DEFAULT;
ALTER TABLE app.worker_status ALTER COLUMN details_json TYPE JSONB USING details_json::jsonb;
ALTER TABLE app.worker_status ALTER COLUMN details_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.worker_runs ALTER COLUMN details_json DROP DEFAULT;
ALTER TABLE app.worker_runs ALTER COLUMN details_json TYPE JSONB USING details_json::jsonb;
ALTER TABLE app.worker_runs ALTER COLUMN details_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.connector_health ALTER COLUMN details_json DROP DEFAULT;
ALTER TABLE app.connector_health ALTER COLUMN details_json TYPE JSONB USING details_json::jsonb;
ALTER TABLE app.connector_health ALTER COLUMN details_json SET DEFAULT '{}'::jsonb;
ALTER TABLE app.migration_imports ALTER COLUMN source_manifest_json DROP DEFAULT;
ALTER TABLE app.migration_imports ALTER COLUMN source_manifest_json TYPE JSONB USING source_manifest_json::jsonb;
ALTER TABLE app.migration_imports ALTER COLUMN source_manifest_json SET DEFAULT '{}'::jsonb;
CREATE TABLE IF NOT EXISTS app.reporting_contract (
    contract_name TEXT PRIMARY KEY,
    timezone_name TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO app.reporting_contract (contract_name, timezone_name)
VALUES ('daily_aggregation', 'America/New_York')
ON CONFLICT (contract_name) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_app_prediction_logs_time ON app.prediction_logs (prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_app_crypto_prediction_time ON app.crypto_prediction_logs (symbol, horizon, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_app_sports_prediction_time ON app.sports_prediction_logs (event_id, prediction_timestamp);
CREATE INDEX IF NOT EXISTS idx_ops_operator_messages_claim ON ops.operator_messages (status, created_at);
