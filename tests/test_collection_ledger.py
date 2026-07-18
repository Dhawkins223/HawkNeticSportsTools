import sqlite3
import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.collection_ledger import CollectionLedger, content_hash


class CollectionLedgerTests(unittest.TestCase):
    def test_batch_and_payload_writes_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = CollectionLedger(Path(directory) / "ledger.sqlite")
            first = ledger.start_batch(
                idempotency_key="kalshi:markets:page-1",
                source="kalshi",
                endpoint="markets",
                worker_name="kalshi-market-ingestion",
                worker_version="1",
                collector_version="1",
            )
            second = ledger.start_batch(
                idempotency_key="kalshi:markets:page-1",
                source="kalshi",
                endpoint="markets",
                worker_name="kalshi-market-ingestion",
                worker_version="1",
                collector_version="1",
            )
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(first.batch_id, second.batch_id)
            payload = {"ticker": "KXTEST", "yes_bid": 41}
            stored = ledger.store_payload(
                batch_id=first.batch_id,
                source="kalshi",
                entity_type="market",
                source_identifier="KXTEST",
                payload=payload,
                parser_version="1",
            )
            duplicate = ledger.store_payload(
                batch_id=first.batch_id,
                source="kalshi",
                entity_type="market",
                source_identifier="KXTEST",
                payload=payload,
                parser_version="1",
            )
            self.assertFalse(stored["duplicate"])
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(stored["content_hash"], content_hash(payload))

    def test_checkpoint_advances_only_on_completed_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            ledger = CollectionLedger(path)
            failed = ledger.start_batch(
                idempotency_key="failed",
                source="kalshi",
                endpoint="trades",
                worker_name="kalshi-market-ingestion",
                worker_version="1",
                collector_version="1",
            )
            ledger.fail_batch(batch_id=failed.batch_id, error_code="timeout")
            self.assertIsNone(ledger.checkpoint(source="kalshi", endpoint="trades"))

            completed = ledger.start_batch(
                idempotency_key="completed",
                source="kalshi",
                endpoint="trades",
                worker_name="kalshi-market-ingestion",
                worker_version="1",
                collector_version="1",
            )
            ledger.complete_batch(
                batch_id=completed.batch_id,
                records_received=2,
                records_accepted=2,
                records_rejected=0,
                records_duplicated=0,
                cursor_end="cursor-2",
                checkpoint={"source": "kalshi", "endpoint": "trades", "cursor": "cursor-2"},
            )
            self.assertEqual(ledger.checkpoint(source="kalshi", endpoint="trades")["cursor"], "cursor-2")

    def test_rejections_are_retained_and_source_freshness_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            ledger = CollectionLedger(path)
            batch = ledger.start_batch(
                idempotency_key="blocked",
                source="sports-public",
                endpoint="odds",
                worker_name="sports-research",
                worker_version="1",
                collector_version="1",
            )
            ledger.reject(
                batch_id=batch.batch_id,
                entity_type="odds",
                rejection_code="blocked_source",
                parser_version="1",
            )
            ledger.fail_batch(batch_id=batch.batch_id, error_code="blocked_source", blocked=True)
            ledger.update_source_health(
                source="sports-public",
                last_attempted_at="2026-07-12T12:00:00+00:00",
                freshness_state="blocked",
                last_error="blocked_source",
            )
            connection = sqlite3.connect(path)
            try:
                rejected = connection.execute("SELECT COUNT(*) FROM rejected_records").fetchone()[0]
                state = connection.execute("SELECT freshness_state FROM source_health").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(rejected, 1)
            self.assertEqual(state, "blocked")


if __name__ == "__main__":
    unittest.main()
