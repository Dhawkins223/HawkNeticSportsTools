INSERT OR IGNORE INTO audit_events (
    event_id, event_type, actor, entity_type, entity_id, details_json, created_at
) VALUES (
    'migration:0004:clear_partial_settlement_false_positive',
    'data_integrity_repair',
    'database_migration',
    'prediction_logs',
    'settlement_issue',
    '{"issue":"settlement_market_id_not_found","scope":"unresolved_only","audit_history_preserved":true}',
    CURRENT_TIMESTAMP
);

UPDATE prediction_logs
SET settlement_issue = NULL
WHERE settlement_state = 'unresolved'
  AND settlement_issue = 'settlement_market_id_not_found';
