CREATE TABLE IF NOT EXISTS operator_messages (
    message_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    target TEXT NOT NULL CHECK (target IN ('codex', 'code', 'research', 'operations')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'claimed', 'completed', 'rejected')),
    source TEXT NOT NULL CHECK (source IN ('dashboard', 'cli', 'github')),
    claimed_by TEXT,
    claimed_at TEXT,
    completed_at TEXT,
    result_summary TEXT,
    requires_approval INTEGER NOT NULL DEFAULT 1 CHECK (requires_approval = 1),
    execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (execution_allowed = 0)
);

CREATE INDEX IF NOT EXISTS idx_operator_messages_status
    ON operator_messages(status, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_operator_messages_target
    ON operator_messages(target, created_at);
