from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kalshi_research_bot.collection_ledger import CollectionLedger
from kalshi_research_bot.connectors.polymarket import normalize_polymarket_markets
from kalshi_research_bot.source_catalog_store import SourceCatalogStore
from kalshi_research_bot.source_data_store import SourceDataStore
from tests.postgres_support import PostgresTestCase


class SourceDataStoreTests(PostgresTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.observed_at = self.now.isoformat()
        self.ledger = CollectionLedger(self.settings)
        self.catalog = SourceCatalogStore(self.settings)
        self.source_data = SourceDataStore(self.settings)
        self.batch = self.ledger.start_batch(
            idempotency_key="source-data-read-model",
            source="source-data-test",
            endpoint="fixture",
            worker_name="source-data-test",
            worker_version="test",
            collector_version="test",
            started_at=self.observed_at,
        )
        self.raw = self.ledger.store_payload(
            batch_id=self.batch.batch_id,
            source="source-data-test",
            entity_type="fixture",
            source_identifier="fixture",
            observed_at=self.observed_at,
            received_at=self.observed_at,
            payload={"fixture": True},
            parser_version="test",
        )

    def test_fresh_entities_and_source_assets_are_exposed(self) -> None:
        entity = {
            "source": "kalshi",
            "source_entity_id": "player-1",
            "entity_type": "basketball_player",
            "display_name": "Example Player",
            "competition": "NBA",
            "source_id": "upstream-1",
            "source_ids": {},
            "details": {"player_stats": {"points": 21.4}},
            "source_updated_at": self.observed_at,
        }
        self.catalog.upsert_entities(
            [entity],
            raw_payload_id=self.raw["payload_id"],
            ingestion_batch_id=self.batch.batch_id,
            observed_at=self.observed_at,
        )
        self.catalog.upsert_assets(
            [
                {
                    "source": "kalshi",
                    "owner_type": "entity",
                    "owner_source_id": "player-1",
                    "asset_kind": "headshot",
                    "asset_url": "https://assets.example/player.png",
                }
            ],
            raw_payload_id=self.raw["payload_id"],
            observed_at=self.observed_at,
        )

        result = self.source_data.list_entities(
            entity_type="basketball_player",
            competition="NBA",
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["items"][0]["display_name"], "Example Player")
        self.assertEqual(result["items"][0]["asset_url"], "https://assets.example/player.png")

    def test_current_external_markets_include_latest_outcomes(self) -> None:
        start = (self.now + timedelta(minutes=30)).isoformat()
        normalized = normalize_polymarket_markets(
            [
                {
                    "id": "market-1",
                    "question": "Will Boston win?",
                    "outcomes": '["Boston", "New York"]',
                    "outcomePrices": '["0.55", "0.45"]',
                    "clobTokenIds": '["yes-token", "no-token"]',
                    "sportsMarketType": "moneyline",
                    "gameStartTime": start,
                    "active": True,
                    "closed": False,
                }
            ],
            api_fetched_at=self.observed_at,
        )
        self.catalog.upsert_external_markets(
            normalized.markets,
            raw_payload_id=self.raw["payload_id"],
            ingestion_batch_id=self.batch.batch_id,
            observed_at=self.observed_at,
        )

        result = self.source_data.list_external_markets(starts_within_hours=1)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["items"][0]["market_type"], "moneyline")
        self.assertEqual([row["name"] for row in result["items"][0]["outcomes"]], ["Boston", "New York"])

    def test_refresh_queue_is_idempotent_claimable_and_auditable(self) -> None:
        first = self.source_data.enqueue_refresh(
            sources=("polymarket", "kalshi_current"),
            reason="manual",
            requested_by="owner",
            idempotency_key="manual-refresh-1",
        )
        repeated = self.source_data.enqueue_refresh(
            sources=("polymarket", "kalshi_current"),
            reason="manual",
            requested_by="owner",
            idempotency_key="manual-refresh-1",
        )

        self.assertEqual(first["request_id"], repeated["request_id"])
        claimed = self.source_data.claim_refresh(worker_id="worker-1")
        self.assertEqual(claimed["request_id"], first["request_id"])
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["attempt_count"], 1)
        finished = self.source_data.finish_refresh(
            first["request_id"],
            status="completed",
            result={"polymarket": {"records_processed": 12}},
        )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(self.source_data.get_refresh(first["request_id"])["result"]["polymarket"]["records_processed"], 12)

    def test_pregame_planner_creates_one_deduplicated_cloud_request(self) -> None:
        start = self.now + timedelta(minutes=15)
        normalized = normalize_polymarket_markets(
            [
                {
                    "id": "market-pregame",
                    "question": "Will the home team win?",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.52", "0.48"]',
                    "sportsMarketType": "moneyline",
                    "gameStartTime": start.isoformat(),
                    "active": True,
                    "closed": False,
                }
            ],
            api_fetched_at=self.observed_at,
        )
        self.catalog.upsert_external_markets(
            normalized.markets,
            raw_payload_id=self.raw["payload_id"],
            ingestion_batch_id=self.batch.batch_id,
            observed_at=self.observed_at,
        )

        first = self.source_data.schedule_pregame_refreshes(now=self.now)
        repeated = self.source_data.schedule_pregame_refreshes(now=self.now)

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["request_id"], repeated[0]["request_id"])
        self.assertEqual(first[0]["sources"], ["polymarket", "kalshi_current", "sports_current"])

