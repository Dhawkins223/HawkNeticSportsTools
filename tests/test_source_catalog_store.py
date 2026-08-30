from __future__ import annotations

from kalshi_research_bot.collection_ledger import CollectionLedger
from kalshi_research_bot.connectors.polymarket import normalize_polymarket_markets
from kalshi_research_bot.source_catalog_store import SourceCatalogStore
from tests.postgres_support import PostgresTestCase


OBSERVED_AT = "2026-08-29T15:00:00+00:00"


class SourceCatalogStoreTests(PostgresTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ledger = CollectionLedger(self.settings)
        self.catalog = SourceCatalogStore(self.settings)
        self.batch = self.ledger.start_batch(
            idempotency_key="source-catalog-test",
            source="catalog_test",
            endpoint="fixture",
            worker_name="source-catalog-test",
            worker_version="test",
            collector_version="test",
            started_at=OBSERVED_AT,
        )

    def payload(self, identifier: str, value: dict):
        return self.ledger.store_payload(
            batch_id=self.batch.batch_id,
            source="catalog_test",
            entity_type="fixture",
            source_identifier=identifier,
            observed_at=OBSERVED_AT,
            received_at=OBSERVED_AT,
            payload=value,
            parser_version="test",
        )

    def test_entity_details_are_current_while_changed_stats_keep_snapshots(self) -> None:
        first = self.payload("players-1", {"version": 1})
        base = {
            "source": "kalshi",
            "source_entity_id": "player-1",
            "entity_type": "basketball_player",
            "display_name": "Example Player",
            "competition": "NBA",
            "source_id": "upstream-1",
            "source_ids": {"source_3_id": "upstream-1"},
            "details": {"player_stats": {"points": 20.0}},
            "source_updated_at": OBSERVED_AT,
        }
        inserted = self.catalog.upsert_entities(
            [base],
            raw_payload_id=first["payload_id"],
            ingestion_batch_id=self.batch.batch_id,
            observed_at=OBSERVED_AT,
        )
        duplicate = self.catalog.upsert_entities(
            [base],
            raw_payload_id=first["payload_id"],
            ingestion_batch_id=self.batch.batch_id,
            observed_at=OBSERVED_AT,
        )
        changed_raw = self.payload("players-2", {"version": 2})
        changed = {**base, "details": {"player_stats": {"points": 21.5}}}
        changed_result = self.catalog.upsert_entities(
            [changed],
            raw_payload_id=changed_raw["payload_id"],
            ingestion_batch_id=self.batch.batch_id,
            observed_at="2026-08-29T16:00:00+00:00",
        )

        self.assertEqual(inserted["snapshots_inserted"], 1)
        self.assertEqual(duplicate["snapshots_inserted"], 0)
        self.assertEqual(changed_result["snapshots_inserted"], 1)
        self.assertEqual(self.catalog.summary()["entities"], 1)
        self.assertEqual(self.catalog.summary()["entity_snapshots"], 2)
        current = self.query_one(
            "SELECT details FROM core.source_entities WHERE source_entity_id = %s",
            ("player-1",),
        )
        self.assertEqual(float(current["details"]["player_stats"]["points"]), 21.5)

    def test_external_market_keeps_each_observation_and_outcome(self) -> None:
        raw = self.payload("markets", {"markets": 1})
        normalized = normalize_polymarket_markets(
            [
                {
                    "id": "market-1",
                    "slug": "boston-new-york",
                    "question": "Will Boston win?",
                    "outcomes": '["Boston", "New York"]',
                    "outcomePrices": '["0.55", "0.45"]',
                    "clobTokenIds": '["yes-token", "no-token"]',
                    "bestBid": "0.54",
                    "bestAsk": "0.56",
                    "volumeNum": "1000",
                    "liquidityNum": "500",
                    "sportsMarketType": "moneyline",
                    "active": True,
                    "closed": False,
                }
            ],
            api_fetched_at=OBSERVED_AT,
        )
        persisted = self.catalog.upsert_external_markets(
            normalized.markets,
            raw_payload_id=raw["payload_id"],
            ingestion_batch_id=self.batch.batch_id,
            observed_at=OBSERVED_AT,
        )
        repeated = self.catalog.upsert_external_markets(
            normalized.markets,
            raw_payload_id=raw["payload_id"],
            ingestion_batch_id=self.batch.batch_id,
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(persisted["accepted"], 1)
        self.assertEqual(persisted["observations_inserted"], 1)
        self.assertEqual(persisted["outcomes_inserted"], 2)
        self.assertEqual(repeated["observations_inserted"], 0)
        self.assertEqual(self.catalog.summary()["external_markets"], 1)
        self.assertEqual(self.catalog.summary()["market_observations"], 1)
        outcomes = self.query_all(
            "SELECT outcome_name FROM core.external_market_outcomes ORDER BY outcome_position"
        )
        self.assertEqual([row["outcome_name"] for row in outcomes], ["Boston", "New York"])
