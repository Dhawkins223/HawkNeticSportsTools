from __future__ import annotations

import unittest

from kalshi_research_bot.paper_server import (
    MAX_DETAIL_PAGE_SIZE,
    build_data_catalog_payload,
    build_detail_collection_payload,
)


def payload(*, ready: bool = True) -> dict:
    return {
        "generated_at": "2026-08-17T17:49:13Z",
        "public_data_gate": {
            "status": "ready" if ready else "blocked",
            "code": "fresh" if ready else "blocked_stale_payload",
        },
        "games": [{"id": f"game-{index}"} for index in range(3)],
        "markets": [{"ticker": f"market-{index}"} for index in range(5)],
    }


class DetailApiTests(unittest.TestCase):
    def test_market_collection_is_paginated(self) -> None:
        result = build_detail_collection_payload(
            payload(),
            "markets",
            {"limit": ["2"], "offset": ["1"]},
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["total_count"], 5)
        self.assertEqual(result["returned_count"], 2)
        self.assertEqual(result["next_offset"], 3)
        self.assertEqual([item["ticker"] for item in result["items"]], ["market-1", "market-2"])

    def test_stale_collection_is_withheld(self) -> None:
        result = build_detail_collection_payload(payload(ready=False), "games")

        self.assertEqual(result["status"], "withheld")
        self.assertEqual(result["returned_count"], 0)
        self.assertEqual(result["withheld_count"], 3)
        self.assertEqual(result["items"], [])

    def test_limit_is_bounded_and_invalid_offset_uses_default(self) -> None:
        result = build_detail_collection_payload(
            payload(),
            "markets",
            {"limit": ["999999"], "offset": ["not-a-number"]},
        )

        self.assertEqual(result["limit"], MAX_DETAIL_PAGE_SIZE)
        self.assertEqual(result["offset"], 0)
        self.assertEqual(result["returned_count"], 5)
        self.assertIsNone(result["next_offset"])

    def test_catalog_points_to_bounded_authenticated_routes(self) -> None:
        result = build_data_catalog_payload(payload())

        self.assertEqual(result["collections"]["games"]["count"], 3)
        self.assertEqual(result["collections"]["markets"]["count"], 5)
        self.assertIn("limit=50", result["collections"]["markets"]["href"])
        self.assertEqual(result["collections"]["source_data"]["href"], "/api/v1/source-data")


if __name__ == "__main__":
    unittest.main()
