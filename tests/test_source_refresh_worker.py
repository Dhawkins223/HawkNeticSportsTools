from __future__ import annotations

import unittest

from kalshi_research_bot.source_refresh_worker import process_refresh_request


class _Store:
    def __init__(self) -> None:
        self.finished = None

    def finish_refresh(self, request_id, *, status, result, error_code=None):
        self.finished = {
            "request_id": request_id,
            "status": status,
            "result": result,
            "error_code": error_code,
        }
        return self.finished

    def record_refresh_failure(self, request_id, *, result, error_code):
        self.finished = {
            "request_id": request_id,
            "status": "queued",
            "result": result,
            "error_code": error_code,
        }
        return self.finished


class SourceRefreshWorkerTests(unittest.TestCase):
    def test_each_requested_source_runs_and_completion_is_recorded(self) -> None:
        store = _Store()
        result = process_refresh_request(
            {"request_id": "request-1", "sources": ["polymarket", "kalshi_reference"]},
            store=store,  # type: ignore[arg-type]
            operations={
                "polymarket": lambda: {"records_processed": 10},
                "kalshi_reference": lambda: {"records_processed": 20},
            },
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["sources"]["kalshi_reference"]["records_processed"], 20)

    def test_one_source_failure_is_named_without_hiding_successful_sources(self) -> None:
        def broken():
            raise RuntimeError("upstream unavailable")

        result = process_refresh_request(
            {"request_id": "request-2", "sources": ["polymarket", "sports_current"]},
            store=_Store(),  # type: ignore[arg-type]
            operations={
                "polymarket": lambda: {"records_processed": 10},
                "sports_current": broken,
            },
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["result"]["sources"]["polymarket"]["records_processed"], 10)
        self.assertIn("RuntimeError:upstream unavailable", result["result"]["errors"]["sports_current"])


if __name__ == "__main__":
    unittest.main()
