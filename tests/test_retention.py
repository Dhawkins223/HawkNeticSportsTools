from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from kalshi_research_bot.collection_ledger import CollectionLedger
from kalshi_research_bot.kalshi_ingestion import load_latest_kalshi_snapshot
from kalshi_research_bot.retention import (
    TOMBSTONE_KEY,
    RetentionWindowTooShort,
    prune_source_payload_bodies,
    render_storage_report,
    source_payload_storage_report,
)

from tests.postgres_support import PostgresTestCase


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RetentionTests(PostgresTestCase):
    def _store_payload(
        self,
        *,
        source: str = "kalshi_public_api",
        entity_type: str = "kalshi_today_snapshot",
        identifier: str,
        age_days: float,
        body: dict | None = None,
    ) -> str:
        """Write one collected payload as though it arrived `age_days` ago."""
        received = (_now() - timedelta(days=age_days)).isoformat()
        ledger = CollectionLedger(self.settings)
        batch = ledger.start_batch(
            idempotency_key=f"batch-{identifier}",
            source=source,
            endpoint="test",
            worker_name="test-worker",
            worker_version="v1",
            collector_version="v1",
            request_parameters={},
            started_at=received,
        )
        stored = ledger.store_payload(
            batch_id=batch.batch_id,
            source=source,
            entity_type=entity_type,
            source_identifier=identifier,
            observed_at=received,
            received_at=received,
            parser_version="v1",
            payload=body if body is not None else {"identifier": identifier, "filler": "x" * 4000},
        )
        ledger.complete_batch(
            batch_id=batch.batch_id,
            records_received=1,
            records_accepted=1,
            records_rejected=0,
            records_duplicated=0,
            payload_hash_value=stored["content_hash"],
        )
        return stored["payload_id"]

    def test_dry_run_reports_candidates_without_writing(self) -> None:
        self._store_payload(identifier="old", age_days=60)
        self._store_payload(identifier="new", age_days=1)

        result = prune_source_payload_bodies(older_than_days=30, settings=self.settings)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(result["pruned"], 0)
        self.assertGreater(result["reclaimable_bytes"], 0)

        rows = self.query_all("SELECT payload_json FROM raw.source_payloads")
        for row in rows:
            self.assertNotIn(TOMBSTONE_KEY, row["payload_json"])

    def test_apply_replaces_only_bodies_past_the_window(self) -> None:
        self._store_payload(identifier="old", age_days=60)
        self._store_payload(identifier="recent", age_days=1)

        result = prune_source_payload_bodies(older_than_days=30, dry_run=False, settings=self.settings)
        self.assertEqual(result["pruned"], 1)

        old = self.query_one(
            "SELECT payload_json FROM raw.source_payloads WHERE source_identifier = %s", ("old",)
        )
        recent = self.query_one(
            "SELECT payload_json FROM raw.source_payloads WHERE source_identifier = %s", ("recent",)
        )
        self.assertIn(TOMBSTONE_KEY, old["payload_json"])
        self.assertEqual(old["payload_json"][TOMBSTONE_KEY]["state"], "body_pruned")
        self.assertGreater(old["payload_json"][TOMBSTONE_KEY]["original_bytes"], 0)
        self.assertNotIn(TOMBSTONE_KEY, recent["payload_json"])

    def test_evidence_survives_the_prune(self) -> None:
        payload_id = self._store_payload(identifier="old", age_days=90)
        self._store_payload(identifier="newest", age_days=60)
        before = self.query_one(
            "SELECT batch_id, source, entity_type, source_identifier, observed_at, received_at,"
            " content_hash, parser_version FROM raw.source_payloads WHERE id = %s",
            (int(payload_id),),
        )

        prune_source_payload_bodies(older_than_days=30, dry_run=False, settings=self.settings)

        after = self.query_one(
            "SELECT batch_id, source, entity_type, source_identifier, observed_at, received_at,"
            " content_hash, parser_version, payload_json FROM raw.source_payloads WHERE id = %s",
            (int(payload_id),),
        )
        for column in (
            "batch_id",
            "source",
            "entity_type",
            "source_identifier",
            "observed_at",
            "received_at",
            "content_hash",
            "parser_version",
        ):
            self.assertEqual(after[column], before[column], f"{column} must survive the prune")
        # The tombstone carries the hash forward so the row remains self-describing.
        self.assertEqual(after["payload_json"][TOMBSTONE_KEY]["content_hash"], before["content_hash"])

    def test_the_newest_payload_per_source_is_never_pruned(self) -> None:
        # Everything is far past the window, so only the newest-per-source guard
        # can keep the dashboard's current snapshot readable.
        self._store_payload(identifier="older", age_days=90)
        self._store_payload(identifier="newest", age_days=60)

        result = prune_source_payload_bodies(older_than_days=30, dry_run=False, settings=self.settings)
        self.assertEqual(result["pruned"], 1)

        newest = self.query_one(
            "SELECT payload_json FROM raw.source_payloads WHERE source_identifier = %s", ("newest",)
        )
        self.assertNotIn(TOMBSTONE_KEY, newest["payload_json"])

    def test_the_dashboard_snapshot_still_loads_after_a_prune(self) -> None:
        self._store_payload(identifier="older", age_days=90)
        self._store_payload(
            identifier="current",
            age_days=60,
            body={"generated_at": "2026-08-15T00:00:00+00:00", "markets": [], "games": []},
        )

        prune_source_payload_bodies(older_than_days=30, dry_run=False, settings=self.settings)

        snapshot = load_latest_kalshi_snapshot(settings=self.settings)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["generated_at"], "2026-08-15T00:00:00+00:00")
        self.assertNotIn(TOMBSTONE_KEY, snapshot)

    def test_pruning_is_idempotent(self) -> None:
        self._store_payload(identifier="old_a", age_days=90)
        self._store_payload(identifier="old_b", age_days=80)
        self._store_payload(identifier="newest", age_days=60)

        first = prune_source_payload_bodies(older_than_days=30, dry_run=False, settings=self.settings)
        second = prune_source_payload_bodies(older_than_days=30, dry_run=False, settings=self.settings)
        self.assertEqual(first["pruned"], 2)
        self.assertEqual(second["pruned"], 0)
        self.assertEqual(second["candidates"], 0)

    def test_a_short_window_is_refused(self) -> None:
        with self.assertRaises(RetentionWindowTooShort):
            prune_source_payload_bodies(older_than_days=1, settings=self.settings)

    def test_limit_bounds_a_pass_and_reports_the_remainder(self) -> None:
        for index in range(4):
            self._store_payload(identifier=f"old_{index}", age_days=90 - index)
        self._store_payload(identifier="newest", age_days=60)

        result = prune_source_payload_bodies(
            older_than_days=30, limit=2, dry_run=False, settings=self.settings
        )
        self.assertEqual(result["pruned"], 2)
        self.assertEqual(result["remaining_after_limit"], 2)

    def test_source_filter_scopes_the_prune(self) -> None:
        self._store_payload(source="kalshi_public_api", identifier="kalshi_old", age_days=90)
        self._store_payload(source="kalshi_public_api", identifier="kalshi_new", age_days=60)
        self._store_payload(source="espn_scoreboard", identifier="espn_old", age_days=90)
        self._store_payload(source="espn_scoreboard", identifier="espn_new", age_days=60)

        result = prune_source_payload_bodies(
            older_than_days=30, source="espn_scoreboard", dry_run=False, settings=self.settings
        )
        self.assertEqual(result["pruned"], 1)

        kalshi_old = self.query_one(
            "SELECT payload_json FROM raw.source_payloads WHERE source_identifier = %s", ("kalshi_old",)
        )
        self.assertNotIn(TOMBSTONE_KEY, kalshi_old["payload_json"])

    def test_storage_report_attributes_space_by_source(self) -> None:
        self._store_payload(source="kalshi_public_api", identifier="kalshi_old", age_days=90)
        self._store_payload(source="kalshi_public_api", identifier="kalshi_new", age_days=1)
        self._store_payload(source="espn_scoreboard", identifier="espn_old", age_days=90)

        report = source_payload_storage_report(settings=self.settings, older_than_days=30)
        self.assertEqual(report["total_rows"], 3)
        self.assertEqual(report["tombstoned_rows"], 0)
        self.assertGreater(report["total_body_bytes"], 0)
        # espn_old is that source's only payload, so the newest-per-source guard
        # protects it and the report says so rather than over-promising.
        self.assertEqual(report["prunable_rows"], 1)
        self.assertEqual({entry["source"] for entry in report["by_source"]}, {"kalshi_public_api", "espn_scoreboard"})

        rendered = render_storage_report(report)
        self.assertIn("Raw Source Payload Storage", rendered)
        self.assertIn("kalshi_public_api", rendered)

    def test_retention_worker_prunes_and_reports_what_it_did(self) -> None:
        from kalshi_research_bot.worker_services import SERVICE_SPECS, build_service_operation

        self._store_payload(identifier="old_a", age_days=90)
        self._store_payload(identifier="old_b", age_days=80)
        self._store_payload(identifier="newest", age_days=60)

        self.assertIn("raw-retention", SERVICE_SPECS)
        operation = build_service_operation(
            "raw-retention", kalshi_run_id="k", crypto_run_id="c", sports_run_id="s"
        )
        result = operation()

        self.assertFalse(result["dry_run"], "a retention worker that only reports leaves the volume filling")
        self.assertEqual(result["payload_bodies_pruned"], 2)
        self.assertEqual(result["records_processed"], 2)
        self.assertFalse(result["no_material_change"])
        self.assertGreater(result["reclaimable_bytes"], 0)
        self.assertEqual(result["still_eligible"], 0)

        # Nothing left to prune is the healthy steady state, not a failure.
        steady = operation()
        self.assertEqual(steady["payload_bodies_pruned"], 0)
        self.assertTrue(steady["no_material_change"])

    def test_storage_census_names_the_largest_relations(self) -> None:
        from kalshi_research_bot.retention import database_storage_census

        for index in range(3):
            self._store_payload(identifier=f"census_{index}", age_days=index)

        census = database_storage_census(settings=self.settings, limit=10)
        self.assertGreater(census["database_bytes"], 0)
        self.assertTrue(census["largest_relations"])

        names = [row["relation"] for row in census["largest_relations"]]
        self.assertIn("raw.source_payloads", names)
        sizes = [row["total_bytes"] for row in census["largest_relations"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True), "largest relation must come first")

    def test_retention_worker_reports_where_the_space_is(self) -> None:
        from kalshi_research_bot.worker_services import build_service_operation

        self._store_payload(identifier="only", age_days=1)
        operation = build_service_operation(
            "raw-retention", kalshi_run_id="k", crypto_run_id="c", sports_run_id="s"
        )
        result = operation()

        # Nothing is old enough to prune, so the census is the only thing that
        # explains a database that is still growing.
        self.assertEqual(result["payload_bodies_pruned"], 0)
        self.assertGreater(result["database_bytes"], 0)
        self.assertTrue(any("raw.source_payloads=" in entry for entry in result["largest_relations"]))

    def test_retention_worker_window_is_configurable_and_floored(self) -> None:
        from unittest import mock

        from kalshi_research_bot.worker_services import build_service_operation

        self._store_payload(identifier="old", age_days=20)
        self._store_payload(identifier="newest", age_days=15)

        with mock.patch.dict("os.environ", {"RAW_RETENTION_DAYS": "10"}):
            operation = build_service_operation(
                "raw-retention", kalshi_run_id="k", crypto_run_id="c", sports_run_id="s"
            )
            widened = operation()
        self.assertEqual(widened["retention_days"], 10)
        self.assertEqual(widened["payload_bodies_pruned"], 1)

        # A window under the floor is raised to it rather than honoured.
        with mock.patch.dict("os.environ", {"RAW_RETENTION_DAYS": "1"}):
            operation = build_service_operation(
                "raw-retention", kalshi_run_id="k", crypto_run_id="c", sports_run_id="s"
            )
            floored = operation()
        self.assertEqual(floored["retention_days"], 7)

    def test_report_counts_tombstones_separately_after_a_prune(self) -> None:
        self._store_payload(identifier="old", age_days=90)
        self._store_payload(identifier="newest", age_days=60)
        prune_source_payload_bodies(older_than_days=30, dry_run=False, settings=self.settings)

        report = source_payload_storage_report(settings=self.settings, older_than_days=30)
        self.assertEqual(report["total_rows"], 2)
        self.assertEqual(report["tombstoned_rows"], 1)
        self.assertEqual(report["prunable_rows"], 0)
