from __future__ import annotations

import concurrent.futures
import copy
from decimal import Decimal

from kalshi_research_bot.combo_safety import VERIFIED_COMBO_EVIDENCE, VERIFIED_COMBO_SOURCE, combo_leg_signature
from kalshi_research_bot.evaluation.paper_live import (
    build_daily_report,
    build_stage3b_audit_report,
    fetch_official_kalshi_settlements,
    import_settlements,
    log_forward_predictions,
    render_daily_report,
    render_stage3b_audit_report,
    start_paper_test_run,
)
from kalshi_research_bot.evaluation.logging import extract_prediction_logs_from_payload

from tests.postgres_support import PostgresTestCase


def _verified_slip(*, market_id: str = "MKT1", timestamp: str = "2026-07-03T16:00:00+00:00") -> dict:
    leg = {
        "display_event": "Detroit vs Texas",
        "event_ticker": "EVT1",
        "market_ticker": market_id,
        "side": "yes",
        "probability": Decimal("0.82"),
        "ask_cents": Decimal("82"),
        "bid_cents": Decimal("80"),
        "midpoint_cents": Decimal("81"),
        "spread_cents": Decimal("2"),
        "event_start_time": "2026-07-03T20:00:00+00:00",
        "market_close_time": "2026-07-03T20:00:00+00:00",
        "api_fetched_at": timestamp,
        "market_updated_at": timestamp,
        "title": "Detroit vs Texas total",
        "subtitle": "Over 3.5 runs",
        "research_mode": "source_backed",
        "evidence_count": 2,
    }
    signature = combo_leg_signature([leg])
    leg.update(
        {
            "combo_eligible": True,
            "combo_market_ticker": "KXMVE-TEST",
            "combo_market_status": "active",
            "combo_market_yes_ask_cents": 50,
            "combo_market_fetched_at": timestamp,
            "combo_market_snapshot_hash": "sha256:combo",
            "combo_market_leg_signature": signature,
            "combo_exact_leg_count": 1,
            "combo_evidence_status": VERIFIED_COMBO_EVIDENCE,
            "combo_source": VERIFIED_COMBO_SOURCE,
        }
    )
    return {
        "generated_at": timestamp,
        "custom_slip": {
            "action": "BUILD_SLIP",
            "leg_count": 1,
            "combo_compatibility": {"status": "compatible", "exact_listed_combo": True},
            "listed_combo_market_ticker": "KXMVE-TEST",
            "legs": [leg],
        },
    }


def _slip_payload(
    *,
    market_id: str = "MKT1",
    timestamp: str = "2026-07-03T16:00:00+00:00",
    **overrides,
) -> dict:
    payload = _verified_slip(market_id=market_id, timestamp=timestamp)
    leg = payload["custom_slip"]["legs"][0]
    leg.update(overrides)
    signature = combo_leg_signature([leg])
    leg.update(
        {
            "combo_market_leg_signature": signature,
            "combo_exact_leg_count": 1,
            "combo_market_fetched_at": timestamp,
        }
    )
    payload["generated_at"] = timestamp
    return payload


def _synthetic_settled_log(
    index: int,
    *,
    run_id: str,
    market_id: str | None = None,
    strategy: str = "primary_80",
    state: str = "win",
) -> dict:
    resolved_market = market_id or f"MKT-{index}"
    is_win = state == "win"
    return {
        "run_id": run_id,
        "timestamp": f"2026-07-03T{16 + index // 60:02d}:{index % 60:02d}:00+00:00",
        "event": f"Event {index}",
        "event_id": f"EVT-{index if market_id is None else market_id}",
        "market": resolved_market,
        "market_id": resolved_market,
        "side": "yes",
        "strategy": strategy,
        "event_start_time": "2026-07-10T20:00:00+00:00",
        "market_close_time": "2026-07-10T20:00:00+00:00",
        "api_fetched_at": "2026-07-03T15:59:00+00:00",
        "source_updated_at": "2026-07-03T15:55:00+00:00",
        "source_snapshot_hash": f"snapshot-{index}-{strategy}",
        "entry_price_cents": Decimal("80"),
        "implied_probability": Decimal("0.8"),
        "reason_features": {"probability": Decimal("0.8")},
        "input_data_used": {},
        "odds_used": {"ask_cents": 80},
        "model_version": "market_implied_slip_v1",
        "confidence_score": Decimal("0.8"),
        "confidence_label": "price_implied",
        "predicted_outcome": "yes",
        "settlement_state": state,
        "actual_outcome": is_win if state in {"win", "loss"} else None,
        "profit_loss_cents": Decimal("20") if is_win else Decimal("-80"),
        "slip_name": strategy,
    }


class _FixtureResponse:
    def __init__(self, url: str, payload: dict) -> None:
        self.url = url
        self.payload = payload
        self.fetched_at = "2026-07-03T16:05:00+00:00"

    def json(self) -> dict:
        return self.payload


class _FixtureHttp:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def get_text(self, url: str, timeout: int = 20) -> _FixtureResponse:
        self.urls.append(url)
        market_id = url.rsplit("/", 1)[-1]
        return _FixtureResponse(url, self.payloads[market_id])


class PaperLiveTests(PostgresTestCase):
    def test_fresh_verified_combo_logs_once_and_repeated_snapshot_is_rejected(self) -> None:
        store = self.store("paper-live")
        run_id = "paper-live"
        start_paper_test_run(store, run_id=run_id)
        payload = _verified_slip()
        first = log_forward_predictions(store, payload, run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        repeated = log_forward_predictions(store, payload, run_id=run_id, logged_at="2026-07-03T16:01:00+00:00")

        self.assertEqual(first["logged_predictions"], 1)
        self.assertEqual(first["rejected_predictions"], 0)
        self.assertEqual(repeated["logged_predictions"], 0)
        self.assertIn("unchanged_repeat_snapshot", repeated["rejection_reasons"])
        self.assertEqual(self.query_one("SELECT COUNT(*) AS total FROM app.prediction_logs")["total"], 1)
        self.assertEqual(self.query_one("SELECT COUNT(*) AS total FROM app.prediction_rejections")["total"], 1)

    def test_settlement_is_audited_and_unresolved_rows_do_not_enter_win_rate(self) -> None:
        store = self.store("settlement")
        run_id = "settlement"
        start_paper_test_run(store, run_id=run_id)
        self.assertEqual(log_forward_predictions(store, _verified_slip(), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")["logged_predictions"], 1)
        settlement = import_settlements(
            store,
            run_id=run_id,
            settlements_payload={
                "source": "fixture",
                "fetched_at": "2026-07-03T22:00:00+00:00",
                "markets": [{"ticker": "MKT1", "status": "settled", "result": "yes"}],
            },
        )
        report = build_daily_report(store, run_id=run_id, date="2026-07-03")

        self.assertEqual(settlement["rows_updated"], 1)
        self.assertEqual(report["settled_predictions"], 1)
        self.assertEqual(report["win_loss_predictions"], 1)
        self.assertEqual(report["win_rate"], None)
        audit = self.query_one("SELECT new_profit_loss_cents FROM app.settlement_audit")
        self.assertEqual(audit["new_profit_loss_cents"], Decimal("18"))

    def test_stale_payload_is_rejected_without_prediction_log(self) -> None:
        store = self.store("stale")
        run_id = "stale"
        start_paper_test_run(store, run_id=run_id)
        result = log_forward_predictions(
            store,
            _verified_slip(timestamp="2026-07-01T16:00:00+00:00"),
            run_id=run_id,
            logged_at="2026-07-03T16:00:00+00:00",
            max_payload_age_seconds=60,
        )
        self.assertEqual(result["logged_predictions"], 0)
        self.assertIn("stale_payload", result["rejection_reasons"])
        self.assertEqual(self.query_one("SELECT COUNT(*) AS total FROM app.prediction_logs")["total"], 0)

    def test_concurrent_settlement_import_claims_a_prediction_once(self) -> None:
        store = self.store("concurrent-settlement")
        run_id = "concurrent-settlement"
        start_paper_test_run(store, run_id=run_id)
        self.assertEqual(log_forward_predictions(store, _verified_slip(), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")["logged_predictions"], 1)
        payload = {
            "source": "fixture",
            "fetched_at": "2026-07-03T22:00:00+00:00",
            "markets": [{"ticker": "MKT1", "status": "settled", "result": "yes"}],
        }
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: import_settlements(store, run_id=run_id, settlements_payload=payload), range(2)))
        self.assertEqual(sum(result["rows_updated"] for result in results), 1)
        self.assertEqual(self.query_one("SELECT COUNT(*) AS total FROM app.settlement_audit")["total"], 1)

    def test_missing_event_start_is_rejected_before_metrics(self) -> None:
        store = self.store("missing-start")
        run_id = "missing-start"
        start_paper_test_run(store, run_id=run_id)
        result = log_forward_predictions(
            store,
            _slip_payload(event_start_time=""),
            run_id=run_id,
            logged_at="2026-07-03T16:00:00+00:00",
        )
        report = build_daily_report(store, run_id=run_id)
        self.assertEqual(result["logged_predictions"], 0)
        self.assertEqual(report["new_predictions_logged"], 0)
        self.assertEqual(report["rejection_reason_counts"]["missing_event_start_time"], 1)

    def test_missing_market_close_is_rejected_before_metrics(self) -> None:
        store = self.store("missing-close")
        run_id = "missing-close"
        start_paper_test_run(store, run_id=run_id)
        result = log_forward_predictions(
            store,
            _slip_payload(market_close_time=""),
            run_id=run_id,
            logged_at="2026-07-03T16:00:00+00:00",
        )
        report = build_daily_report(store, run_id=run_id)
        self.assertEqual(result["logged_predictions"], 0)
        self.assertEqual(report["rejection_reason_counts"]["missing_market_close_time"], 1)

    def test_late_prediction_is_rejected_before_metrics(self) -> None:
        store = self.store("late")
        run_id = "late"
        start_paper_test_run(store, run_id=run_id)
        result = log_forward_predictions(
            store,
            _slip_payload(event_start_time="2026-07-03T16:00:00+00:00"),
            run_id=run_id,
            logged_at="2026-07-03T16:00:00+00:00",
        )
        report = build_daily_report(store, run_id=run_id)
        self.assertEqual(result["logged_predictions"], 0)
        self.assertEqual(report["rejection_reason_counts"]["prediction_after_event_start"], 1)

    def test_closed_market_is_rejected_before_metrics(self) -> None:
        store = self.store("closed")
        run_id = "closed"
        start_paper_test_run(store, run_id=run_id)
        result = log_forward_predictions(
            store,
            _slip_payload(status="closed"),
            run_id=run_id,
            logged_at="2026-07-03T16:00:00+00:00",
        )
        report = build_daily_report(store, run_id=run_id)
        self.assertEqual(result["logged_predictions"], 0)
        self.assertEqual(report["rejection_reason_counts"]["market_not_tradable:closed"], 1)

    def test_snapshot_hash_ignores_collection_timestamp(self) -> None:
        payload = _verified_slip()
        first = extract_prediction_logs_from_payload(
            payload,
            prediction_timestamp="2026-07-03T16:00:00+00:00",
            run_id="hash",
        )
        second = extract_prediction_logs_from_payload(
            payload,
            prediction_timestamp="2026-07-03T16:05:00+00:00",
            run_id="hash",
        )
        self.assertEqual(first[0]["source_snapshot_hash"], second[0]["source_snapshot_hash"])

    def test_exact_duplicate_is_ignored_without_double_counting(self) -> None:
        store = self.store("exact-duplicate")
        run_id = "exact-duplicate"
        start_paper_test_run(store, run_id=run_id)
        payload = _verified_slip()
        first = log_forward_predictions(store, payload, run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        second = log_forward_predictions(store, payload, run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        self.assertEqual(first["logged_predictions"], 1)
        self.assertEqual(second["logged_predictions"], 0)
        self.assertEqual(second["duplicate_rows_ignored"], 1)

    def test_changed_market_snapshot_gets_next_sequence(self) -> None:
        store = self.store("changed")
        run_id = "changed"
        start_paper_test_run(store, run_id=run_id)
        first = log_forward_predictions(
            store,
            _slip_payload(),
            run_id=run_id,
            logged_at="2026-07-03T16:00:00+00:00",
        )
        second = log_forward_predictions(
            store,
            _slip_payload(
                timestamp="2026-07-03T16:04:00+00:00",
                ask_cents=Decimal("81"),
                bid_cents=Decimal("79"),
                midpoint_cents=Decimal("80"),
                probability=Decimal("0.81"),
            ),
            run_id=run_id,
            logged_at="2026-07-03T16:05:00+00:00",
        )
        report = build_daily_report(store, run_id=run_id)
        row = self.query_one(
            "SELECT MAX(snapshot_sequence) AS sequence FROM app.prediction_logs WHERE run_id = %s",
            (run_id,),
        )
        self.assertEqual(first["logged_predictions"], 1)
        self.assertEqual(second["logged_predictions"], 1)
        self.assertEqual(report["changed_snapshots"], 1)
        self.assertEqual(row["sequence"], 2)

    def test_fetch_time_only_change_is_an_unchanged_snapshot(self) -> None:
        store = self.store("fetch-time")
        run_id = "fetch-time"
        start_paper_test_run(store, run_id=run_id)
        first = log_forward_predictions(store, _slip_payload(), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        repeated_payload = _slip_payload()
        repeated_payload["generated_at"] = "2026-07-03T16:04:00+00:00"
        repeated_payload["custom_slip"]["legs"][0]["api_fetched_at"] = "2026-07-03T16:04:00+00:00"
        repeated = log_forward_predictions(
            store,
            repeated_payload,
            run_id=run_id,
            logged_at="2026-07-03T16:05:00+00:00",
        )
        report = build_daily_report(store, run_id=run_id)
        self.assertEqual(first["logged_predictions"], 1)
        self.assertEqual(repeated["logged_predictions"], 0)
        self.assertIn("unchanged_repeat_snapshot", repeated["rejection_reasons"])
        self.assertEqual(report["unchanged_repeat_snapshot_rejections"], 1)

    def test_confidence_change_creates_changed_snapshot(self) -> None:
        store = self.store("confidence-change")
        run_id = "confidence-change"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        changed = log_forward_predictions(
            store,
            _slip_payload(timestamp="2026-07-03T16:04:00+00:00", probability=Decimal("0.88")),
            run_id=run_id,
            logged_at="2026-07-03T16:05:00+00:00",
        )
        self.assertEqual(changed["logged_predictions"], 1)
        self.assertEqual(build_daily_report(store, run_id=run_id)["changed_snapshots"], 1)

    def test_market_status_change_creates_changed_snapshot(self) -> None:
        store = self.store("status-change")
        run_id = "status-change"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(status="active"), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        changed = log_forward_predictions(
            store,
            _slip_payload(timestamp="2026-07-03T16:04:00+00:00", status="open"),
            run_id=run_id,
            logged_at="2026-07-03T16:05:00+00:00",
        )
        self.assertEqual(changed["logged_predictions"], 1)
        self.assertEqual(build_daily_report(store, run_id=run_id)["changed_snapshots"], 1)

    def test_unchanged_heartbeat_is_reported_as_no_material_change(self) -> None:
        store = self.store("heartbeat")
        run_id = "heartbeat"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(
            store,
            _slip_payload(event_start_time="2026-07-05T20:00:00+00:00", market_close_time="2026-07-05T20:00:00+00:00"),
            run_id=run_id,
            logged_at="2026-07-03T16:00:00+00:00",
        )
        repeated_payload = _slip_payload(
            event_start_time="2026-07-05T20:00:00+00:00",
            market_close_time="2026-07-05T20:00:00+00:00",
        )
        repeated_payload["generated_at"] = "2026-07-04T15:59:00+00:00"
        repeated_payload["custom_slip"]["legs"][0]["api_fetched_at"] = "2026-07-04T15:59:00+00:00"
        log_forward_predictions(
            store,
            repeated_payload,
            run_id=run_id,
            logged_at="2026-07-04T16:00:00+00:00",
        )
        report = build_daily_report(store, run_id=run_id, date="20260704")
        self.assertEqual(report["heartbeat_status"], "no_material_change")
        self.assertIn("Heartbeat status: no_material_change", render_daily_report(report))

    def test_settled_snapshots_are_deduped_by_earliest_market_exposure(self) -> None:
        store = self.store("deduped-exposure")
        run_id = "deduped-exposure"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        log_forward_predictions(
            store,
            _slip_payload(
                timestamp="2026-07-03T16:04:00+00:00",
                ask_cents=Decimal("81"),
                bid_cents=Decimal("79"),
                midpoint_cents=Decimal("80"),
                probability=Decimal("0.81"),
            ),
            run_id=run_id,
            logged_at="2026-07-03T16:05:00+00:00",
        )
        import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "MKT1", "status": "settled", "result": "yes"}]},
        )
        report = build_daily_report(store, run_id=run_id)
        self.assertEqual(report["settled_raw_rows"], 2)
        self.assertEqual(report["settled_deduped_market_exposures"], 1)
        self.assertEqual(report["stage3b_gate_status"], "blocked_by_sample_size")

    def test_tier_duplicate_exposure_warning_is_run_scoped(self) -> None:
        store = self.store("tier-duplicate")
        run_id = "tier-duplicate"
        start_paper_test_run(store, run_id=run_id)
        payload = _verified_slip()
        payload["all_day_slip"] = copy.deepcopy(payload["custom_slip"])
        payload["all_day_slip"]["listed_combo_market_ticker"] = "KXMVE-ALL-DAY"
        payload["all_day_slip"]["legs"][0]["combo_market_ticker"] = "KXMVE-ALL-DAY"
        logged = log_forward_predictions(store, payload, run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        report = build_daily_report(store, run_id=run_id)
        self.assertEqual(logged["logged_predictions"], 2)
        self.assertEqual(len(report["duplicate_exposure_warnings"]), 1)
        self.assertEqual(report["duplicate_exposure_warnings"][0]["market_id"], "MKT1")

    def test_official_settlement_fetch_uses_pending_market_ids(self) -> None:
        store = self.store("official-fetch")
        run_id = "official-fetch"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        http = _FixtureHttp({"MKT1": {"market": {"ticker": "MKT1", "status": "active"}}})
        payload = fetch_official_kalshi_settlements(store, run_id=run_id, http=http)
        self.assertEqual(payload["source"], "kalshi_public_market_detail")
        self.assertEqual(payload["outcomes"][0]["market_id"], "MKT1")
        self.assertTrue(http.urls[0].endswith("/markets/MKT1"))
        self.assertEqual(payload["markets_pending"], 1)

    def test_official_settlement_fetch_skips_already_settled_market(self) -> None:
        store = self.store("official-skip")
        run_id = "official-skip"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "MKT1", "status": "settled", "result": "yes"}]},
        )
        http = _FixtureHttp({})
        payload = fetch_official_kalshi_settlements(store, run_id=run_id, http=http)
        self.assertEqual(payload["markets_pending"], 0)
        self.assertEqual(payload["outcomes"], [])
        self.assertEqual(http.urls, [])

    def test_win_settlement_records_exact_profit_and_loss(self) -> None:
        store = self.store("win")
        run_id = "win"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="WIN", ask_cents=Decimal("82")), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        settled = import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "WIN", "status": "settled", "result": "yes"}]},
        )
        row = self.query_one("SELECT settlement_state, actual_outcome, profit_loss_cents FROM app.prediction_logs WHERE run_id = %s", (run_id,))
        self.assertEqual(settled["rows_updated"], 1)
        self.assertEqual(row["settlement_state"], "win")
        self.assertTrue(row["actual_outcome"])
        self.assertEqual(row["profit_loss_cents"], Decimal("18"))

    def test_loss_settlement_records_exact_profit_and_loss(self) -> None:
        store = self.store("loss")
        run_id = "loss"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="LOSS", ask_cents=Decimal("82")), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        settled = import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "LOSS", "status": "settled", "result": "no"}]},
        )
        row = self.query_one("SELECT settlement_state, actual_outcome, profit_loss_cents FROM app.prediction_logs WHERE run_id = %s", (run_id,))
        self.assertEqual(settled["rows_updated"], 1)
        self.assertEqual(row["settlement_state"], "loss")
        self.assertFalse(row["actual_outcome"])
        self.assertEqual(row["profit_loss_cents"], Decimal("-82"))

    def test_partial_settlement_leaves_other_rows_unresolved(self) -> None:
        store = self.store("partial")
        run_id = "partial"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="ONE"), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        log_forward_predictions(store, _slip_payload(market_id="TWO"), run_id=run_id, logged_at="2026-07-03T16:01:00+00:00")
        settled = import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "ONE", "status": "settled", "result": "yes"}]},
        )
        untouched = self.query_one(
            "SELECT settlement_state, settlement_issue FROM app.prediction_logs WHERE run_id = %s AND market_id = %s",
            (run_id, "TWO"),
        )
        self.assertEqual(settled["rows_updated"], 1)
        self.assertEqual(untouched["settlement_state"], "unresolved")
        self.assertIsNone(untouched["settlement_issue"])

    def test_push_settlement_is_not_a_loss(self) -> None:
        store = self.store("push")
        run_id = "push"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="PUSH"), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "PUSH", "settlement_state": "push"}]},
        )
        row = self.query_one("SELECT settlement_state, actual_outcome, profit_loss_cents FROM app.prediction_logs WHERE run_id = %s", (run_id,))
        self.assertEqual(row["settlement_state"], "push")
        self.assertIsNone(row["actual_outcome"])
        self.assertEqual(row["profit_loss_cents"], Decimal("0"))

    def test_void_settlement_is_not_a_loss(self) -> None:
        store = self.store("void")
        run_id = "void"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="VOID"), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "VOID", "settlement_state": "void"}]},
        )
        row = self.query_one("SELECT settlement_state, actual_outcome, profit_loss_cents FROM app.prediction_logs WHERE run_id = %s", (run_id,))
        self.assertEqual(row["settlement_state"], "void")
        self.assertIsNone(row["actual_outcome"])
        self.assertEqual(row["profit_loss_cents"], Decimal("0"))

    def test_fair_market_requires_explicit_price(self) -> None:
        store = self.store("fair-price")
        run_id = "fair-price"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="FAIR", ask_cents=Decimal("82")), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        missing = import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "FAIR", "settlement_state": "fair_market"}]},
        )
        row = self.query_one("SELECT settlement_state, profit_loss_cents, settlement_issue FROM app.prediction_logs WHERE run_id = %s", (run_id,))
        self.assertEqual(missing["rows_updated"], 0)
        self.assertEqual(row["settlement_state"], "unresolved")
        self.assertIsNone(row["profit_loss_cents"])
        self.assertEqual(row["settlement_issue"], "missing_fair_market_settlement_price")

    def test_early_exit_requires_explicit_price(self) -> None:
        store = self.store("early-exit")
        run_id = "early-exit"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="EXIT", ask_cents=Decimal("82")), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        missing = import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "EXIT", "settlement_state": "early_exit"}]},
        )
        row = self.query_one("SELECT settlement_state, profit_loss_cents, settlement_issue FROM app.prediction_logs WHERE run_id = %s", (run_id,))
        self.assertEqual(missing["rows_updated"], 0)
        self.assertEqual(row["settlement_state"], "unresolved")
        self.assertIsNone(row["profit_loss_cents"])
        self.assertEqual(row["settlement_issue"], "missing_exit_price")

    def test_unknown_settlement_does_not_create_profit_or_loss(self) -> None:
        store = self.store("unknown")
        run_id = "unknown"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="UNKNOWN"), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        result = import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "UNKNOWN", "status": "settled"}]},
        )
        row = self.query_one("SELECT settlement_state, profit_loss_cents, settlement_issue FROM app.prediction_logs WHERE run_id = %s", (run_id,))
        self.assertEqual(result["rows_updated"], 0)
        self.assertEqual(row["settlement_state"], "unresolved")
        self.assertIsNone(row["profit_loss_cents"])
        self.assertEqual(row["settlement_issue"], "unknown_settlement_state")

    def test_repeated_settlement_is_idempotent_and_audited_once(self) -> None:
        store = self.store("idempotent-settlement")
        run_id = "idempotent-settlement"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="IDEMPOTENT"), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        payload = {"source": "fixture", "markets": [{"ticker": "IDEMPOTENT", "status": "settled", "result": "yes"}]}
        first = import_settlements(store, run_id=run_id, settlements_payload=payload)
        repeated = import_settlements(store, run_id=run_id, settlements_payload=payload)
        row = self.query_one("SELECT COUNT(*) AS total FROM app.settlement_audit WHERE run_id = %s", (run_id,))
        self.assertEqual(first["rows_updated"], 1)
        self.assertEqual(repeated["rows_updated"], 0)
        self.assertEqual(row["total"], 1)

    def test_settlement_preserves_original_prediction_evidence(self) -> None:
        store = self.store("immutable-evidence")
        run_id = "immutable-evidence"
        start_paper_test_run(store, run_id=run_id)
        log_forward_predictions(store, _slip_payload(market_id="IMMUTABLE"), run_id=run_id, logged_at="2026-07-03T16:00:00+00:00")
        fields = "prediction_timestamp, event_start_time, market_close_time, api_fetched_at, source_snapshot_hash, entry_price_cents, model_version, strategy"
        before = dict(self.query_one(f"SELECT {fields} FROM app.prediction_logs WHERE run_id = %s", (run_id,)))
        import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "IMMUTABLE", "status": "settled", "result": "no"}]},
        )
        after = dict(self.query_one(f"SELECT {fields} FROM app.prediction_logs WHERE run_id = %s", (run_id,)))
        self.assertEqual(after, before)

    def test_metrics_exclude_invalid_unresolved_and_rejected_rows(self) -> None:
        store = self.store("metric-filters")
        run_id = "metric-filters"
        start_paper_test_run(store, run_id=run_id)
        first = log_forward_predictions(
            store,
            _slip_payload(market_id="MKT1"),
            run_id=run_id,
            logged_at="2026-07-03T16:00:00+00:00",
        )
        second = log_forward_predictions(
            store,
            _slip_payload(market_id="UNRESOLVED", timestamp="2026-07-03T16:01:00+00:00"),
            run_id=run_id,
            logged_at="2026-07-03T16:01:00+00:00",
        )
        rejected = log_forward_predictions(
            store,
            _slip_payload(market_id="REJECTED", event_start_time=""),
            run_id=run_id,
            logged_at="2026-07-03T16:02:00+00:00",
        )
        store.insert_prediction_logs(
            [
                {
                    "run_id": run_id,
                    "timestamp": "2026-07-03T16:00:00+00:00",
                    "event": "Invalid",
                    "market": "INVALID",
                    "market_id": "INVALID",
                    "side": "yes",
                    "model_version": "test",
                    "confidence_score": Decimal("0.82"),
                    "confidence_label": "price_implied",
                    "predicted_outcome": "yes",
                }
            ]
        )
        import_settlements(
            store,
            run_id=run_id,
            settlements_payload={"source": "fixture", "markets": [{"ticker": "MKT1", "status": "settled", "result": "yes"}]},
        )
        report = build_daily_report(store, run_id=run_id)
        self.assertEqual(first["logged_predictions"], 1)
        self.assertEqual(second["logged_predictions"], 1)
        self.assertEqual(rejected["rejected_predictions"], 1)
        self.assertEqual(report["settled_predictions"], 1)
        self.assertEqual(report["unresolved_predictions"], 1)
        self.assertEqual(report["invalid_rejected_predictions"], 1)
        self.assertIsNone(report["win_rate"])
        self.assertIsNone(report["roi_fee_excluded"])

    def test_stage_audit_blocks_duplicate_exposure_bloat(self) -> None:
        store = self.store("audit-duplicate")
        run_id = "audit-duplicate"
        start_paper_test_run(store, run_id=run_id)
        store.insert_prediction_logs(
            [
                _synthetic_settled_log(index, run_id=run_id, market_id="DUPLICATE", strategy=f"tier-{index % 4}")
                for index in range(100)
            ]
        )
        audit = build_stage3b_audit_report(store, run_id=run_id)
        self.assertEqual(audit["raw_settled_rows"], 100)
        self.assertEqual(audit["deduped_settled_market_exposures"], 1)
        self.assertEqual(audit["gate_status"], "blocked_by_sample_size")
        self.assertIn("No profitability, edge, or calibration claim", render_stage3b_audit_report(audit))

    def test_stage_audit_remains_research_only_after_sample_gate(self) -> None:
        store = self.store("audit-ready")
        run_id = "audit-ready"
        start_paper_test_run(store, run_id=run_id)
        store.insert_prediction_logs(
            [
                _synthetic_settled_log(
                    index,
                    run_id=run_id,
                    state="win" if index < 80 else "loss",
                    strategy="primary_80" if index % 2 == 0 else "leverage_75",
                )
                for index in range(100)
            ]
        )
        audit = build_stage3b_audit_report(store, run_id=run_id)
        self.assertEqual(audit["gate_status"], "stage3b_audit_ready")
        self.assertEqual(audit["deduped_settled_market_exposures"], 100)
        self.assertEqual(audit["deduped_market_performance"]["win_rate"], Decimal("0.8"))
        self.assertIn("research-only", render_stage3b_audit_report(audit))
