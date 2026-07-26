from __future__ import annotations

from copy import deepcopy

from kalshi_research_bot.kalshi_ingestion import persist_kalshi_snapshot
from postgres_support import PostgresTestCase


def _payload() -> dict:
    return {
        "date": "20260726",
        "generated_at": "2026-07-26T05:00:00+00:00",
        "games": [
            {
                "event_id": "game-1",
                "league": "mlb",
                "home_team": "Home",
                "away_team": "Away",
                "start_time": "2026-07-26T18:00:00+00:00",
            }
        ],
        "markets": [
            {
                "ticker": "KXMVE-FIXTURE-1",
                "event_ticker": "KXMVE-FIXTURE-EVENT",
                "mve_collection_ticker": "KXMVE-FIXTURE",
                "title": "Fixture combo",
                "legs_text": "Home wins",
                "status": "active",
                "api_fetched_at": "2026-07-26T04:59:59+00:00",
                "source_updated_at": "2026-07-26T04:59:58+00:00",
                "source_snapshot_hash": "sha256:fixture",
                "source": "kalshi",
                "source_url": "https://api.elections.kalshi.com/trade-api/v2/markets",
                "close_time": "2026-07-26T18:00:00+00:00",
                "expected_expiration_time": "2026-07-26T20:00:00+00:00",
                "yes_bid_cents": "79.12500000",
                "yes_ask_cents": "80.12500000",
                "no_bid_cents": "19.87500000",
                "no_ask_cents": "20.87500000",
                "volume_24h": "9999999999.12345678",
                "liquidity_dollars": "100.50000000",
            }
        ],
    }


class KalshiIngestionTests(PostgresTestCase):
    def test_snapshot_persists_raw_and_normalized_market_history(self):
        result = persist_kalshi_snapshot(
            _payload(),
            worker_name="test-kalshi-ingestion",
            idempotency_key="kalshi:test:one",
            settings=self.settings,
        )

        self.assertTrue(result["created"])
        self.assertEqual(result["records_received"], 1)
        self.assertEqual(result["records_accepted"], 1)
        self.assertEqual(result["records_rejected"], 0)
        self.assertEqual(self.query_one("SELECT COUNT(*) AS count FROM raw.source_payloads")["count"], 1)
        self.assertEqual(self.query_one("SELECT COUNT(*) AS count FROM core.markets")["count"], 1)
        observation = self.query_one(
            "SELECT yes_bid, yes_ask, volume_24h, liquidity FROM core.market_observations"
        )
        self.assertEqual(str(observation["yes_bid"]), "0.79125000")
        self.assertEqual(str(observation["yes_ask"]), "0.80125000")
        self.assertEqual(str(observation["volume_24h"]), "9999999999.12345678")
        self.assertEqual(str(observation["liquidity"]), "100.50000000")

    def test_same_batch_is_idempotent(self):
        first = persist_kalshi_snapshot(
            _payload(),
            worker_name="test-kalshi-ingestion",
            idempotency_key="kalshi:test:same",
            settings=self.settings,
        )
        second = persist_kalshi_snapshot(
            _payload(),
            worker_name="test-kalshi-ingestion",
            idempotency_key="kalshi:test:same",
            settings=self.settings,
        )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(self.query_one("SELECT COUNT(*) AS count FROM raw.ingestion_batches")["count"], 1)
        self.assertEqual(self.query_one("SELECT COUNT(*) AS count FROM core.market_observations")["count"], 1)

    def test_same_key_with_different_content_fails(self):
        persist_kalshi_snapshot(
            _payload(),
            worker_name="test-kalshi-ingestion",
            idempotency_key="kalshi:test:conflict",
            settings=self.settings,
        )
        changed = deepcopy(_payload())
        changed["markets"][0]["yes_ask_cents"] = "81.12500000"

        with self.assertRaisesRegex(RuntimeError, "kalshi_ingestion_batch_content_conflict"):
            persist_kalshi_snapshot(
                changed,
                worker_name="test-kalshi-ingestion",
                idempotency_key="kalshi:test:conflict",
                settings=self.settings,
            )

    def test_malformed_market_is_retained_as_rejected_evidence(self):
        payload = _payload()
        payload["markets"].append(
            {
                "event_ticker": "KXMVE-BROKEN-EVENT",
                "title": "Missing market ticker",
                "api_fetched_at": "2026-07-26T04:59:59+00:00",
            }
        )

        result = persist_kalshi_snapshot(
            payload,
            worker_name="test-kalshi-ingestion",
            idempotency_key="kalshi:test:rejected",
            settings=self.settings,
        )

        self.assertEqual(result["records_received"], 2)
        self.assertEqual(result["records_accepted"], 1)
        self.assertEqual(result["records_rejected"], 1)
        rejection = self.query_one("SELECT rejection_code FROM raw.rejected_records")
        self.assertEqual(rejection["rejection_code"], "missing_market_ticker")
