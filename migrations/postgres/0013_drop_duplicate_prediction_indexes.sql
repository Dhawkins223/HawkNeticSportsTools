-- Migration 0007 recreated three indexes that migration 0001 had already
-- created on the same tables and the same columns, under a schema-qualified
-- name. The pairs are byte-for-byte identical, so the second copy of each never
-- serves a read: it only doubles the index maintenance every insert into the
-- three highest-volume prediction tables pays, and doubles the storage those
-- indexes occupy.
--
-- Each surviving index keeps the name migration 0001 created, so nothing that
-- refers to an index by name needs to change.

DROP INDEX IF EXISTS app.idx_app_prediction_logs_time;
DROP INDEX IF EXISTS app.idx_app_crypto_prediction_time;
DROP INDEX IF EXISTS app.idx_app_sports_prediction_time;
