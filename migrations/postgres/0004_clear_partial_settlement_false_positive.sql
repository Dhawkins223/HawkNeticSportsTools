INSERT INTO ops.audit_events (
    event_type, actor, entity_type, entity_id, details
) VALUES (
    'data_integrity_repair',
    'database_migration',
    'prediction_logs',
    'settlement_issue',
    '{"issue":"settlement_market_id_not_found","scope":"unresolved_only","audit_history_preserved":true}'::jsonb
);

UPDATE prediction_logs
SET settlement_issue = NULL
WHERE settlement_state = 'unresolved'
  AND settlement_issue = 'settlement_market_id_not_found';
