from __future__ import annotations

import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from kalshi_research_bot.connectors.kalshi import KalshiPublicClient
from kalshi_research_bot.connectors.kalshi_catalog import (
    fetch_kalshi_catalog,
    normalize_event_metadata,
    normalize_milestones,
    normalize_structured_targets,
)
from kalshi_research_bot.connectors.polymarket import normalize_polymarket_sports
from kalshi_research_bot.source_catalog_worker import worker_spec


class KalshiCatalogNormalizationTests(unittest.TestCase):
    def test_player_identity_and_source_stats_are_preserved(self) -> None:
        payload = {
            "structured_targets": [
                {
                    "id": "player-1",
                    "name": "Example Player",
                    "type": "basketball_player",
                    "last_updated_ts": "2026-08-20T10:00:00Z",
                    "source_id": "source-player-1",
                    "source_ids": {"source_3_id": "source-player-1"},
                    "details": {
                        "league": "NBA",
                        "position": "G",
                        "team_id": "team-1",
                        "player_stats": {"points": 21.4, "assists": 6.1},
                        "series_stats": {"games": 70},
                    },
                }
            ],
            "cursor": "next",
        }

        normalized = normalize_structured_targets(payload)

        self.assertEqual(normalized.rejections, [])
        player = normalized.records[0]
        self.assertEqual(player["source_entity_id"], "player-1")
        self.assertEqual(player["entity_type"], "basketball_player")
        self.assertEqual(player["competition"], "NBA")
        self.assertEqual(player["details"]["player_stats"]["points"], 21.4)
        self.assertEqual(player["details"]["series_stats"]["games"], 70)

    def test_incomplete_player_is_rejected_instead_of_guessed(self) -> None:
        normalized = normalize_structured_targets(
            {"structured_targets": [{"id": "player-1", "type": "basketball_player"}]}
        )
        self.assertEqual(normalized.records, [])
        self.assertEqual(normalized.rejections[0]["reason"], "missing_target_identity")

    def test_sports_milestone_keeps_event_links_and_competition(self) -> None:
        normalized = normalize_milestones(
            {
                "milestones": [
                    {
                        "id": "milestone-1",
                        "category": "Sports",
                        "type": "basketball_game",
                        "title": "Boston at New York",
                        "start_date": "2026-08-29T19:00:00Z",
                        "end_date": "2026-08-29T22:00:00Z",
                        "primary_event_tickers": ["KXNBAGAME-EXAMPLE"],
                        "related_event_tickers": ["KXNBAGAME-EXAMPLE", "KXNBAPOINTS-EXAMPLE"],
                        "details": {"league": "NBA"},
                    }
                ]
            }
        )
        row = normalized.records[0]
        self.assertEqual(row["competition"], "NBA")
        self.assertEqual(row["primary_event_tickers"], ["KXNBAGAME-EXAMPLE"])
        self.assertEqual(row["start_time"], "2026-08-29T19:00:00+00:00")

    def test_event_metadata_extracts_event_and_market_assets_only(self) -> None:
        normalized = normalize_event_metadata(
            "KXNBAGAME-EXAMPLE",
            {
                "image_url": "https://assets.kalshi.com/series.webp",
                "featured_image_url": "https://assets.kalshi.com/featured.webp",
                "market_details": [
                    {
                        "market_ticker": "KXNBAGAME-EXAMPLE-BOS",
                        "image_url": "https://assets.kalshi.com/boston.webp",
                    }
                ],
                "settlement_sources": [{"url": "https://nba.com"}],
            },
        )
        self.assertEqual(len(normalized.assets), 3)
        self.assertEqual(normalized.assets[-1]["owner_type"], "market")
        self.assertEqual(normalized.assets[-1]["owner_source_id"], "KXNBAGAME-EXAMPLE-BOS")


class PolymarketSportsDirectoryTests(unittest.TestCase):
    def test_sport_directory_retains_image_and_resolution_provenance(self) -> None:
        normalized = normalize_polymarket_sports(
            [
                {
                    "id": 42,
                    "sport": "nba",
                    "name": "NBA",
                    "image": "https://polymarket.example/nba.png",
                    "resolution": "https://nba.com",
                    "ordering": "away",
                    "primaryTagId": 745,
                    "series": "10345",
                    "tags": "1,745",
                }
            ],
            api_fetched_at="2026-08-29T10:00:00+00:00",
        )
        sport = normalized.markets[0]
        self.assertEqual(sport["sport_code"], "nba")
        self.assertEqual(sport["image_url"], "https://polymarket.example/nba.png")
        self.assertEqual(sport["resolution_url"], "https://nba.com")


class SourceCatalogWorkerTests(unittest.TestCase):
    def test_market_observations_run_frequently_and_reference_data_runs_slowly(self) -> None:
        polymarket = worker_spec("polymarket")
        kalshi = worker_spec("kalshi")
        self.assertEqual(polymarket.cadence_seconds, 3600)
        self.assertEqual(kalshi.cadence_seconds, 21600)
        self.assertTrue(polymarket.expect_records)
        self.assertTrue(kalshi.expect_records)


class KalshiCatalogRequestTests(unittest.TestCase):
    class _Response:
        status = 200
        fetched_at = "2026-08-29T10:00:00+00:00"
        from_cache = False
        stale = False
        stale_reason = ""

        def json(self):
            return {"milestones": [], "cursor": ""}

    class _Http:
        def __init__(self):
            self.url = ""

        def get_text(self, url: str, timeout: int = 20):
            self.url = url
            return KalshiCatalogRequestTests._Response()

    def test_milestones_use_limit_while_structured_targets_use_page_size(self) -> None:
        http = self._Http()
        client = KalshiPublicClient()
        client.http = http
        client.milestones(page_size=2)
        milestone_query = parse_qs(urlparse(http.url).query)
        self.assertEqual(milestone_query["limit"], ["2"])
        self.assertNotIn("page_size", milestone_query)

        client.structured_targets(target_type="basketball_player", page_size=3)
        target_query = parse_qs(urlparse(http.url).query)
        self.assertEqual(target_query["page_size"], ["3"])

    def test_missing_event_metadata_returns_a_recordable_status(self) -> None:
        class _MissingHttp:
            def get_text(self, url: str, timeout: int = 20):
                raise HTTPError(url, 404, "Not Found", {}, None)

        response = fetch_kalshi_catalog("events/retired/metadata", client=_MissingHttp())
        self.assertEqual(response.status, 404)
        self.assertIsNone(response.payload)


if __name__ == "__main__":
    unittest.main()
