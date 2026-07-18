from __future__ import annotations

from kalshi_research_bot.collection_ledger import CollectionLedger, content_hash

from tests.postgres_support import PostgresTestCase


class CollectionLedgerTests(PostgresTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ledger = CollectionLedger(self.settings)

    def _batch(self, key: str):
        return self.ledger.start_batch(
            idempotency_key=key,
            source="kalshi",
            endpoint="markets",
            worker_name="kalshi-market-ingestion",
            worker_version="test",
            collector_version="test",
        )

    def test_batch_and_payload_are_idempotent(self) -> None:
        first = self._batch("markets-page-1")
        second = self._batch("markets-page-1")
        payload = {"ticker": "KXTEST", "yes_bid": 41}
        stored = self.ledger.store_payload(
            batch_id=first.batch_id,
            source="kalshi",
            entity_type="market",
            source_identifier="KXTEST",
            payload=payload,
            parser_version="test",
        )
        repeated = self.ledger.store_payload(
            batch_id=first.batch_id,
            source="kalshi",
            entity_type="market",
            source_identifier="KXTEST",
            payload=payload,
            parser_version="test",
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.batch_id, second.batch_id)
        self.assertEqual(stored["content_hash"], content_hash(payload))
        self.assertFalse(stored["duplicate"])
        self.assertTrue(repeated["duplicate"])

    def test_checkpoint_only_advances_after_completed_batch(self) -> None:
        failed = self._batch("failed")
        self.assertTrue(self.ledger.fail_batch(batch_id=failed.batch_id, error_code="timeout"))
        self.assertIsNone(self.ledger.checkpoint(source="kalshi", endpoint="markets"))

        completed = self._batch("completed")
        self.assertTrue(
            self.ledger.complete_batch(
                batch_id=completed.batch_id,
                records_received=2,
                records_accepted=2,
                records_rejected=0,
                records_duplicated=0,
                checkpoint={"source": "kalshi", "endpoint": "markets", "cursor": "cursor-2"},
            )
        )
        checkpoint = self.ledger.checkpoint(source="kalshi", endpoint="markets")
        self.assertEqual(checkpoint["cursor"], "cursor-2")
        self.assertEqual(checkpoint["batch_id"], int(completed.batch_id))

    def test_rejections_and_blocked_source_health_are_retained(self) -> None:
        batch = self._batch("blocked")
        rejection_id = self.ledger.reject(
            batch_id=batch.batch_id,
            entity_type="market",
            rejection_code="blocked_source",
            parser_version="test",
        )
        self.assertTrue(self.ledger.fail_batch(batch_id=batch.batch_id, error_code="blocked_source", blocked=True))
        self.ledger.update_source_health(
            source="sports-public",
            last_attempted_at="2026-07-18T12:00:00+00:00",
            freshness_state="blocked",
            last_error="blocked_source",
        )

        rejected = self.query_one("SELECT rejection_code FROM raw.rejected_records WHERE id = %s", (int(rejection_id),))
        health = self.query_one("SELECT freshness_state FROM ops.source_health WHERE source = %s", ("sports-public",))
        self.assertEqual(rejected["rejection_code"], "blocked_source")
        self.assertEqual(health["freshness_state"], "blocked")
