ALTER TABLE ops.report_refreshes
    ADD COLUMN IF NOT EXISTS refresh_id TEXT;

UPDATE ops.report_refreshes
SET refresh_id = 'legacy:' || id::text
WHERE refresh_id IS NULL;

ALTER TABLE ops.report_refreshes
    ALTER COLUMN refresh_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_report_refreshes_refresh_id
    ON ops.report_refreshes(refresh_id);
