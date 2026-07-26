ALTER TABLE ops.worker_status
    ADD COLUMN IF NOT EXISTS current_idempotency_key TEXT;

CREATE INDEX IF NOT EXISTS idx_ops_worker_status_current_idempotency
    ON ops.worker_status (worker_name, current_idempotency_key)
    WHERE current_idempotency_key IS NOT NULL;
