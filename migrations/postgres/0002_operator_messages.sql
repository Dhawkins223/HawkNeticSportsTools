CREATE TABLE IF NOT EXISTS operator_messages (
    message_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    created_by TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    target TEXT NOT NULL CHECK (target IN ('codex', 'code', 'research', 'operations')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'claimed', 'completed', 'rejected')),
    source TEXT NOT NULL CHECK (source IN ('dashboard', 'cli', 'github')),
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result_summary TEXT,
    requires_approval BOOLEAN NOT NULL DEFAULT TRUE CHECK (requires_approval = TRUE),
    execution_allowed BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_allowed = FALSE)
);

CREATE INDEX IF NOT EXISTS idx_operator_messages_status
    ON operator_messages(status, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_operator_messages_target
    ON operator_messages(target, created_at);
