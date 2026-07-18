import tempfile
import unittest
from pathlib import Path

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
from kalshi_research_bot.business_store import create_research_store


# Preserve the existing behavioral scenarios while running them against the
# PostgreSQL-only runtime factory.
ResearchStore = create_research_store


def _leg(**overrides):
    leg = {
        "display_event": "Detroit vs Texas",
        "event_ticker": "EVT1",
        "market_ticker": "MKT1",
        "side": "yes",
        "probability": 0.82,
        "ask_cents": 82,
        "bid_cents": 80,
        "midpoint_cents": 81,
        "spread_cents": 2,
        "event_start_time": "2026-07-03T20:00:00Z",
        "market_close_time": "2026-07-03T20:00:00Z",
        "api_fetched_at": "2026-07-03T15:59:00Z",
        "market_updated_at": "2026-07-03T15:55:00Z",
        "title": "Detroit vs Texas total",
        "subtitle": "Over 3.5 runs",
    }
    leg.update(overrides)
    return leg


def _combo_slip(legs, **overrides):
    signature = combo_leg_signature(legs)
    combo_ticker = overrides.pop("listed_combo_market_ticker", "KXMVE-TEST")
    verified_legs = []
    for leg in legs:
        verified_legs.append(
            {
                **leg,
                "combo_eligible": True,
                "combo_market_ticker": combo_ticker,
                "combo_market_status": "active",
                "combo_market_yes_ask_cents": 50,
                "combo_market_fetched_at": leg.get("api_fetched_at") or "2026-07-03T15:59:00Z",
                "combo_market_snapshot_hash": "sha256:combo",
                "combo_market_leg_signature": signature,
                "combo_exact_leg_count": len(legs),
                "combo_evidence_status": VERIFIED_COMBO_EVIDENCE,
                "combo_source": VERIFIED_COMBO_SOURCE,
            }
        )
    return {
        "action": "BUILD_SLIP",
        "leg_count": len(verified_legs),
        "combo_compatibility": {"status": "compatible", "exact_listed_combo": True},
        "listed_combo_market_ticker": combo_ticker,
        "legs": verified_legs,
        **overrides,
    }


class _FakeResponse:
    def __init__(self, url, payload):
        self.url = url
        self._payload = payload
        self.fetched_at = "2026-07-03T16:05:00Z"

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, payload_by_market):
        self.payload_by_market = payload_by_market
        self.urls = []

    def get_text(self, url, timeout=20):
        self.urls.append(url)
        market_id = url.rsplit("/", 1)[-1]
        payload = self.payload_by_market[market_id]
        return _FakeResponse(url, payload)


def _query_one(store, sql, params=()):
    store.initialize()
    with store.connect() as connection:
        row = connection.execute(sql, params).fetchone()
        return None if row is None else {column: row[column] for column in row.keys()}


def _log_valid_prediction(store, run_id="stage3a_settle", **leg_overrides):
    start_paper_test_run(store, run_id=run_id)
    payload = {
        "generated_at": "2026-07-03T15:59:00Z",
        "custom_slip": _combo_slip([_leg(**leg_overrides)]),
    }
    result = log_forward_predictions(store, payload, run_id=run_id, logged_at="2026-07-03T16:00:00Z")
    assert result["logged_predictions"] == 1
    return run_id


def _settled_log(index, *, run_id, market_id=None, strategy="primary_80", state="win", timestamp=None):
    resolved_market = market_id or f"MKT_STAGE3B_{index}"
    is_win = state == "win"
    entry_price = 80
    return {
        "run_id": run_id,
        "timestamp": timestamp or f"2026-07-03T16:{index % 60:02d}:00Z",
        "event": f"Event {index}",
        "event_id": f"EVT_STAGE3B_{index if market_id is None else market_id}",
        "market": resolved_market,
        "market_id": resolved_market,
        "side": "yes",
        "strategy": strategy,
        "event_start_time": "2026-07-10T20:00:00Z",
        "market_close_time": "2026-07-10T20:00:00Z",
        "api_fetched_at": "2026-07-03T15:59:00Z",
        "source_updated_at": "2026-07-03T15:55:00Z",
        "source_snapshot_hash": f"snapshot-{index}-{strategy}",
        "entry_price_cents": entry_price,
        "implied_probability": 0.8,
        "reason_features": {"probability": 0.8},
        "input_data_used": {},
        "odds_used": {"ask_cents": entry_price},
        "model_version": "market_implied_slip_v1",
        "confidence_score": 0.8,
        "confidence_label": "price_implied",
        "predicted_outcome": "yes",
        "settlement_state": state,
        "actual_outcome": is_win,
        "profit_loss_cents": 100 - entry_price if is_win else -entry_price,
        "slip_name": strategy,
    }


class PaperLiveTests(unittest.TestCase):
    def test_run_logging_rejection_settlement_and_legacy_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "eval.sqlite"
            lock_path = Path(directory) / "run_lock.json"
            store = ResearchStore(db_path)
            run = start_paper_test_run(store, run_id="stage3a_test", lock_path=lock_path)
            self.assertEqual(run["run_id"], "stage3a_test")
            self.assertTrue(lock_path.exists())

            store.insert_prediction_logs(
                [
                    {
                        "timestamp": "2026-07-03T15:00:00Z",
                        "event": "Legacy",
                        "market": "LEGACY1",
                        "side": "yes",
                        "event_start_time": "2026-07-03T20:00:00Z",
                        "market_close_time": "2026-07-03T20:00:00Z",
                        "input_data_used": {},
                        "odds_used": {"ask_cents": 80},
                        "model_version": "legacy",
                        "confidence_score": 0.8,
                        "confidence_label": "price_implied",
                        "predicted_outcome": "yes",
                    }
                ]
            )

            payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip(
                    [
                        _leg(),
                        _leg(market_ticker="MKT_BAD", event_start_time="", market_close_time=""),
                    ],
                    min_leg_probability=0.8,
                ),
            }
            result = log_forward_predictions(
                store,
                payload,
                run_id="stage3a_test",
                logged_at="2026-07-03T16:00:00Z",
            )
            self.assertEqual(result["attempted_predictions"], 2)
            self.assertEqual(result["logged_predictions"], 1)
            self.assertEqual(result["rejected_predictions"], 1)
            self.assertIn("missing_event_start_time", result["rejection_reasons"])

            report = build_daily_report(store, run_id="stage3a_test")
            self.assertEqual(report["new_predictions_logged"], 1)
            self.assertEqual(report["invalid_rejected_predictions"], 1)
            self.assertEqual(report["rejection_reason_counts"]["missing_event_start_time"], 1)
            self.assertEqual(report["rejection_reason_counts"]["missing_market_close_time"], 1)
            self.assertEqual(report["unresolved_predictions"], 1)
            self.assertEqual(report["legacy_rows_excluded"], 1)
            self.assertEqual(report["settled_profit_loss_cents_fee_excluded"], 0)
            self.assertIsNone(report["win_rate"])
            self.assertIsNone(report["roi_fee_excluded"])
            self.assertEqual(report["sample_status"], "insufficient_sample (0/100)")

            settlement = import_settlements(
                store,
                run_id="stage3a_test",
                settlements_payload={"outcomes": [{"market_id": "MKT1", "winning_side": "yes"}]},
            )
            self.assertEqual(settlement["rows_updated"], 1)
            settled_report = build_daily_report(store, run_id="stage3a_test")
            self.assertEqual(settled_report["settled_predictions"], 1)
            self.assertEqual(settled_report["unresolved_predictions"], 0)
            self.assertEqual(settled_report["settled_profit_loss_cents_fee_excluded"], 18.0)
            self.assertIsNone(settled_report["win_rate"])
            self.assertIsNone(settled_report["roi_fee_excluded"])
            self.assertEqual(settled_report["sample_status"], "insufficient_sample (1/100)")

    def test_missing_event_start_missing_close_and_late_timestamp_are_rejected_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_rejects")
            payload = {
                "generated_at": "2026-07-03T16:00:00Z",
                "custom_slip": _combo_slip(
                    [
                        _leg(market_ticker="MKT_NO_START", event_start_time=""),
                        _leg(market_ticker="MKT_NO_CLOSE", market_close_time="", close_time=""),
                        _leg(market_ticker="MKT_LATE", event_start_time="2026-07-03T16:00:00Z"),
                        _leg(market_ticker="MKT_CLOSED", event_start_time="2026-07-03T20:00:00Z", market_close_time="2026-07-03T16:00:00Z"),
                        _leg(market_ticker="MKT_STATUS", status="closed"),
                    ],
                ),
            }
            result = log_forward_predictions(
                store,
                payload,
                run_id="stage3a_rejects",
                logged_at="2026-07-03T16:00:00Z",
            )
            self.assertEqual(result["logged_predictions"], 0)
            self.assertEqual(result["rejected_predictions"], 5)
            report = build_daily_report(store, run_id="stage3a_rejects")
            self.assertEqual(report["new_predictions_logged"], 0)
            self.assertEqual(report["settled_predictions"], 0)
            self.assertEqual(report["unresolved_predictions"], 0)
            self.assertEqual(report["settled_profit_loss_cents_fee_excluded"], 0)
            self.assertIsNone(report["win_rate"])
            self.assertIsNone(report["roi_fee_excluded"])
            self.assertEqual(report["rejection_reason_counts"]["missing_event_start_time"], 1)
            self.assertEqual(report["rejection_reason_counts"]["missing_market_close_time"], 1)
            self.assertEqual(report["rejection_reason_counts"]["prediction_after_event_start"], 1)
            self.assertEqual(report["rejection_reason_counts"]["prediction_after_market_close"], 1)
            self.assertEqual(report["rejection_reason_counts"]["market_not_tradable:closed"], 1)

    def test_source_snapshot_hash_is_deterministic(self):
        payload = {
            "generated_at": "2026-07-03T15:59:00Z",
            "custom_slip": _combo_slip([_leg()]),
        }
        first = extract_prediction_logs_from_payload(payload, prediction_timestamp="2026-07-03T16:00:00Z", run_id="run")
        second = extract_prediction_logs_from_payload(payload, prediction_timestamp="2026-07-03T16:05:00Z", run_id="run")
        self.assertEqual(first[0]["source_snapshot_hash"], second[0]["source_snapshot_hash"])
        self.assertEqual(first[0]["source_snapshot_id"], first[0]["source_snapshot_hash"])

    def test_stale_payload_is_rejected_before_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_stale")
            payload = {
                "generated_at": "2026-07-03T16:00:00Z",
                "custom_slip": _combo_slip([_leg(api_fetched_at="2026-07-03T14:00:00Z")]),
            }
            result = log_forward_predictions(
                store,
                payload,
                run_id="stage3a_stale",
                logged_at="2026-07-03T16:00:00Z",
                max_payload_age_seconds=1800,
            )
            self.assertEqual(result["logged_predictions"], 0)
            self.assertEqual(result["rejected_predictions"], 1)
            report = build_daily_report(store, run_id="stage3a_stale")
            self.assertEqual(report["new_predictions_logged"], 0)
            self.assertEqual(report["rejection_reason_counts"]["stale_payload"], 1)
            self.assertIsNone(report["win_rate"])
            self.assertIsNone(report["roi_fee_excluded"])

    def test_exact_duplicate_prediction_is_ignored_not_double_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_exact_dupe")
            payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg()]),
            }
            first = log_forward_predictions(store, payload, run_id="stage3a_exact_dupe", logged_at="2026-07-03T16:00:00Z")
            second = log_forward_predictions(store, payload, run_id="stage3a_exact_dupe", logged_at="2026-07-03T16:00:00Z")
            self.assertEqual(first["logged_predictions"], 1)
            self.assertEqual(second["logged_predictions"], 0)
            self.assertEqual(second["duplicate_rows_ignored"], 1)
            report = build_daily_report(store, run_id="stage3a_exact_dupe")
            self.assertEqual(report["new_predictions_logged"], 1)

    def test_unchanged_repeat_snapshot_is_rejected_not_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_repeat")
            payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg()]),
            }
            first = log_forward_predictions(store, payload, run_id="stage3a_repeat", logged_at="2026-07-03T16:00:00Z")
            second = log_forward_predictions(store, payload, run_id="stage3a_repeat", logged_at="2026-07-03T16:05:00Z")
            self.assertEqual(first["logged_predictions"], 1)
            self.assertEqual(second["logged_predictions"], 0)
            self.assertEqual(second["rejected_predictions"], 1)
            self.assertIn("unchanged_repeat_snapshot", second["rejection_reasons"])
            report = build_daily_report(store, run_id="stage3a_repeat")
            self.assertEqual(report["new_predictions_logged"], 1)
            self.assertEqual(report["rejection_reason_counts"]["unchanged_repeat_snapshot"], 1)

    def test_changed_repeat_snapshot_is_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_changed_repeat")
            first_payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg()]),
            }
            changed_payload = {
                "generated_at": "2026-07-03T16:04:00Z",
                "custom_slip": _combo_slip(
                    [_leg(ask_cents=81, bid_cents=79, midpoint_cents=80, probability=0.81, api_fetched_at="2026-07-03T16:04:00Z")]
                ),
            }
            first = log_forward_predictions(store, first_payload, run_id="stage3a_changed_repeat", logged_at="2026-07-03T16:00:00Z")
            second = log_forward_predictions(store, changed_payload, run_id="stage3a_changed_repeat", logged_at="2026-07-03T16:05:00Z")
            self.assertEqual(first["logged_predictions"], 1)
            self.assertEqual(second["logged_predictions"], 1)
            report = build_daily_report(store, run_id="stage3a_changed_repeat")
            self.assertEqual(report["new_predictions_logged"], 2)
            self.assertEqual(report["changed_snapshots"], 1)
            self.assertEqual(report["repeated_snapshot_groups"], 1)
            row = _query_one(
                store,
                "SELECT MAX(snapshot_sequence) AS max_sequence FROM prediction_logs WHERE run_id = ?",
                ("stage3a_changed_repeat",),
            )
            self.assertEqual(row["max_sequence"], 2)

    def test_api_fetched_at_only_change_is_unchanged_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_fetch_only")
            first_payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg()]),
            }
            second_payload = {
                "generated_at": "2026-07-03T16:04:00Z",
                "custom_slip": _combo_slip([_leg(api_fetched_at="2026-07-03T16:04:00Z")]),
            }
            first = log_forward_predictions(store, first_payload, run_id="stage3a_fetch_only", logged_at="2026-07-03T16:00:00Z")
            second = log_forward_predictions(store, second_payload, run_id="stage3a_fetch_only", logged_at="2026-07-03T16:05:00Z")
            self.assertEqual(first["logged_predictions"], 1)
            self.assertEqual(second["logged_predictions"], 0)
            self.assertEqual(second["rejected_predictions"], 1)
            self.assertIn("unchanged_repeat_snapshot", second["rejection_reasons"])
            report = build_daily_report(store, run_id="stage3a_fetch_only")
            self.assertEqual(report["new_predictions_logged"], 1)
            self.assertEqual(report["unchanged_repeat_snapshot_rejections"], 1)
            self.assertEqual(report["changed_snapshots"], 0)

    def test_confidence_score_change_creates_changed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_score_change")
            first_payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg(probability=0.82)]),
            }
            changed_payload = {
                "generated_at": "2026-07-03T16:04:00Z",
                "custom_slip": _combo_slip([_leg(probability=0.88, api_fetched_at="2026-07-03T16:04:00Z")]),
            }
            first = log_forward_predictions(store, first_payload, run_id="stage3a_score_change", logged_at="2026-07-03T16:00:00Z")
            second = log_forward_predictions(store, changed_payload, run_id="stage3a_score_change", logged_at="2026-07-03T16:05:00Z")
            self.assertEqual(first["logged_predictions"], 1)
            self.assertEqual(second["logged_predictions"], 1)
            report = build_daily_report(store, run_id="stage3a_score_change")
            self.assertEqual(report["new_predictions_logged"], 2)
            self.assertEqual(report["changed_snapshots"], 1)

    def test_market_status_change_creates_changed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_status_change")
            first_payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg(status="active")]),
            }
            changed_payload = {
                "generated_at": "2026-07-03T16:04:00Z",
                "custom_slip": _combo_slip([_leg(status="open", api_fetched_at="2026-07-03T16:04:00Z")]),
            }
            first = log_forward_predictions(store, first_payload, run_id="stage3a_status_change", logged_at="2026-07-03T16:00:00Z")
            second = log_forward_predictions(store, changed_payload, run_id="stage3a_status_change", logged_at="2026-07-03T16:05:00Z")
            self.assertEqual(first["logged_predictions"], 1)
            self.assertEqual(second["logged_predictions"], 1)
            report = build_daily_report(store, run_id="stage3a_status_change")
            self.assertEqual(report["changed_snapshots"], 1)

    def test_identical_payload_with_volatile_timestamp_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_volatile_only")
            first_payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg()]),
            }
            second_payload = {
                "generated_at": "2026-07-03T16:04:00Z",
                "custom_slip": _combo_slip([_leg()]),
            }
            first = log_forward_predictions(store, first_payload, run_id="stage3a_volatile_only", logged_at="2026-07-03T16:00:00Z")
            second = log_forward_predictions(store, second_payload, run_id="stage3a_volatile_only", logged_at="2026-07-03T16:05:00Z")
            self.assertEqual(first["logged_predictions"], 1)
            self.assertEqual(second["logged_predictions"], 0)
            self.assertIn("unchanged_repeat_snapshot", second["rejection_reasons"])

    def test_report_shows_no_material_change_for_unchanged_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_no_material")
            base_leg = _leg(
                event_start_time="2026-07-05T20:00:00Z",
                market_close_time="2026-07-05T20:00:00Z",
            )
            first_payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([base_leg]),
            }
            repeat_payload = {
                "generated_at": "2026-07-04T15:59:00Z",
                "custom_slip": _combo_slip([{**base_leg, "api_fetched_at": "2026-07-04T15:59:00Z"}]),
            }
            log_forward_predictions(store, first_payload, run_id="stage3a_no_material", logged_at="2026-07-03T16:00:00Z")
            repeat = log_forward_predictions(store, repeat_payload, run_id="stage3a_no_material", logged_at="2026-07-04T16:00:00Z")
            self.assertEqual(repeat["logged_predictions"], 0)
            self.assertIn("unchanged_repeat_snapshot", repeat["rejection_reasons"])
            report = build_daily_report(store, run_id="stage3a_no_material", date="20260704")
            rendered = render_daily_report(report)
            self.assertEqual(report["heartbeat_status"], "no_material_change")
            self.assertEqual(report["new_predictions_logged"], 0)
            self.assertIn("Heartbeat status: no_material_change", rendered)

    def test_deduped_stage_gate_uses_earliest_market_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_deduped_gate")
            first_payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg()]),
            }
            changed_payload = {
                "generated_at": "2026-07-03T16:04:00Z",
                "custom_slip": _combo_slip(
                    [_leg(ask_cents=81, bid_cents=79, midpoint_cents=80, probability=0.81, api_fetched_at="2026-07-03T16:04:00Z")]
                ),
            }
            log_forward_predictions(store, first_payload, run_id="stage3a_deduped_gate", logged_at="2026-07-03T16:00:00Z")
            log_forward_predictions(store, changed_payload, run_id="stage3a_deduped_gate", logged_at="2026-07-03T16:05:00Z")
            import_settlements(
                store,
                run_id="stage3a_deduped_gate",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT1", "winning_side": "yes"}]},
            )
            report = build_daily_report(store, run_id="stage3a_deduped_gate")
            self.assertEqual(report["settled_raw_rows"], 2)
            self.assertEqual(report["settled_deduped_market_exposures"], 1)
            self.assertEqual(report["unique_market_exposures"], 1)
            self.assertEqual(report["deduped_sample_status"], "insufficient_sample (1/100)")
            self.assertEqual(report["stage3b_gate_status"], "blocked_by_sample_size")

    def test_duplicate_exposure_warning_is_run_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_dupes")
            payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip([_leg()]),
                "all_day_slip": _combo_slip([_leg()], listed_combo_market_ticker="KXMVE-ALL-DAY"),
            }
            log_forward_predictions(store, payload, run_id="stage3a_dupes", logged_at="2026-07-03T16:00:00Z")
            report = build_daily_report(store, run_id="stage3a_dupes")
            self.assertEqual(report["new_predictions_logged"], 2)
            self.assertEqual(len(report["duplicate_exposure_warnings"]), 1)
            warning = report["duplicate_exposure_warnings"][0]
            self.assertEqual(warning["market_id"], "MKT1")
            self.assertEqual(warning["count"], 2)
            self.assertEqual(warning["strategies"], ["all_day_75_85", "primary_80"])

    def test_official_kalshi_settlement_fetch_uses_market_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_fetch", market_ticker="MKT1")
            http = _FakeHttp({"MKT1": {"market": {"ticker": "MKT1", "status": "active"}}})
            payload = fetch_official_kalshi_settlements(store, run_id="stage3a_fetch", http=http)
            self.assertEqual(payload["source"], "kalshi_public_market_detail")
            self.assertEqual(payload["outcomes"][0]["market_id"], "MKT1")
            self.assertEqual(payload["outcomes"][0]["_api_fetched_at"], "2026-07-03T16:05:00Z")
            self.assertTrue(http.urls[0].endswith("/markets/MKT1"))
            self.assertEqual(payload["markets_pending"], 1)
            self.assertEqual(payload["markets_deferred"], 0)

    def test_official_settlement_fetch_excludes_already_settled_markets(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_fetch", market_ticker="MKT1")
            import_settlements(
                store,
                run_id="stage3a_fetch",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT1", "result": "yes"}]},
            )
            http = _FakeHttp({})
            payload = fetch_official_kalshi_settlements(store, run_id="stage3a_fetch", http=http)
            self.assertEqual(payload["markets_pending"], 0)
            self.assertEqual(payload["outcomes"], [])
            self.assertEqual(http.urls, [])

    def test_official_win_and_loss_settlement_calculates_pl(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_win", market_ticker="MKT_WIN", ask_cents=82)
            _log_valid_prediction(store, run_id="stage3a_loss", market_ticker="MKT_LOSS", ask_cents=82)

            win = import_settlements(
                store,
                run_id="stage3a_win",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_WIN", "result": "yes"}]},
            )
            loss = import_settlements(
                store,
                run_id="stage3a_loss",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_LOSS", "result": "no"}]},
            )

            self.assertEqual(win["rows_updated"], 1)
            self.assertEqual(loss["rows_updated"], 1)
            win_row = _query_one(store, "SELECT settlement_state, actual_outcome, profit_loss_cents FROM prediction_logs WHERE run_id = ?", ("stage3a_win",))
            loss_row = _query_one(store, "SELECT settlement_state, actual_outcome, profit_loss_cents FROM prediction_logs WHERE run_id = ?", ("stage3a_loss",))
            self.assertEqual(win_row["settlement_state"], "win")
            self.assertEqual(win_row["actual_outcome"], 1)
            self.assertEqual(win_row["profit_loss_cents"], 18.0)
            self.assertEqual(loss_row["settlement_state"], "loss")
            self.assertEqual(loss_row["actual_outcome"], 0)
            self.assertEqual(loss_row["profit_loss_cents"], -82.0)

    def test_partial_settlement_payload_does_not_contaminate_unrelated_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_partial", market_ticker="MKT_ONE")
            second = {
                "generated_at": "2026-07-03T15:59:01Z",
                "custom_slip": _combo_slip([_leg(market_ticker="MKT_TWO")]),
            }
            log_forward_predictions(store, second, run_id="stage3a_partial", logged_at="2026-07-03T16:00:01Z")
            result = import_settlements(
                store,
                run_id="stage3a_partial",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_ONE", "result": "yes"}]},
            )
            untouched = _query_one(
                store,
                "SELECT settlement_state, settlement_issue FROM prediction_logs WHERE run_id = ? AND market_id = ?",
                ("stage3a_partial", "MKT_TWO"),
            )
            self.assertEqual(result["rows_updated"], 1)
            self.assertEqual(result["settlement_issue_counts"], {})
            self.assertEqual(untouched["settlement_state"], "unresolved")
            self.assertIsNone(untouched["settlement_issue"])

    def test_push_void_and_cancelled_settlements_are_not_losses(self):
        cases = [
            ("stage3a_push", "MKT_PUSH", {"settlement_state": "push"}, "push"),
            ("stage3a_void", "MKT_VOID", {"settlement_state": "void"}, "void"),
            ("stage3a_cancelled", "MKT_CANCEL", {"settlement_state": "canceled"}, "cancelled"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            for run_id, market_id, outcome, expected_state in cases:
                with self.subTest(expected_state=expected_state):
                    _log_valid_prediction(store, run_id=run_id, market_ticker=market_id)
                    import_settlements(
                        store,
                        run_id=run_id,
                        settlements_payload={"source": "test", "outcomes": [{"market_id": market_id, **outcome}]},
                    )
                    row = _query_one(store, "SELECT settlement_state, actual_outcome, profit_loss_cents FROM prediction_logs WHERE run_id = ?", (run_id,))
                    self.assertEqual(row["settlement_state"], expected_state)
                    self.assertIsNone(row["actual_outcome"])
                    self.assertEqual(row["profit_loss_cents"], 0.0)

    def test_fair_market_settlement_requires_official_price(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_fair_price", market_ticker="MKT_FAIR", ask_cents=82)
            _log_valid_prediction(store, run_id="stage3a_fair_missing", market_ticker="MKT_FAIR_MISSING", ask_cents=82)

            priced = import_settlements(
                store,
                run_id="stage3a_fair_price",
                settlements_payload={
                    "source": "test",
                    "outcomes": [{"market_id": "MKT_FAIR", "settlement_state": "fair_market", "settlement_price_cents": 45}],
                },
            )
            missing = import_settlements(
                store,
                run_id="stage3a_fair_missing",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_FAIR_MISSING", "settlement_state": "fair_market"}]},
            )

            self.assertEqual(priced["rows_updated"], 1)
            self.assertEqual(missing["rows_updated"], 0)
            self.assertEqual(missing["settlement_issue_counts"]["missing_fair_market_settlement_price"], 1)
            priced_row = _query_one(store, "SELECT settlement_state, profit_loss_cents FROM prediction_logs WHERE run_id = ?", ("stage3a_fair_price",))
            missing_row = _query_one(store, "SELECT settlement_state, profit_loss_cents, settlement_issue FROM prediction_logs WHERE run_id = ?", ("stage3a_fair_missing",))
            self.assertEqual(priced_row["settlement_state"], "fair_market")
            self.assertEqual(priced_row["profit_loss_cents"], -37.0)
            self.assertEqual(missing_row["settlement_state"], "unresolved")
            self.assertIsNone(missing_row["profit_loss_cents"])
            self.assertEqual(missing_row["settlement_issue"], "missing_fair_market_settlement_price")

    def test_early_exit_requires_exit_price(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_exit_price", market_ticker="MKT_EXIT", ask_cents=82)
            _log_valid_prediction(store, run_id="stage3a_exit_missing", market_ticker="MKT_EXIT_MISSING", ask_cents=82)

            import_settlements(
                store,
                run_id="stage3a_exit_price",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_EXIT", "settlement_state": "early_exit", "exit_price_cents": 65}]},
            )
            missing = import_settlements(
                store,
                run_id="stage3a_exit_missing",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_EXIT_MISSING", "settlement_state": "early_exit"}]},
            )

            priced_row = _query_one(store, "SELECT settlement_state, profit_loss_cents FROM prediction_logs WHERE run_id = ?", ("stage3a_exit_price",))
            missing_row = _query_one(store, "SELECT settlement_state, profit_loss_cents, settlement_issue FROM prediction_logs WHERE run_id = ?", ("stage3a_exit_missing",))
            self.assertEqual(priced_row["settlement_state"], "early_exit")
            self.assertEqual(priced_row["profit_loss_cents"], -17.0)
            self.assertEqual(missing["settlement_issue_counts"]["missing_exit_price"], 1)
            self.assertEqual(missing_row["settlement_state"], "unresolved")
            self.assertIsNone(missing_row["profit_loss_cents"])
            self.assertEqual(missing_row["settlement_issue"], "missing_exit_price")

    def test_unknown_and_open_settlement_states_do_not_create_pl(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_open", market_ticker="MKT_OPEN")
            _log_valid_prediction(store, run_id="stage3a_inactive", market_ticker="MKT_INACTIVE")
            _log_valid_prediction(store, run_id="stage3a_unknown", market_ticker="MKT_UNKNOWN")

            open_result = import_settlements(
                store,
                run_id="stage3a_open",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_OPEN", "status": "active"}]},
            )
            inactive_result = import_settlements(
                store,
                run_id="stage3a_inactive",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_INACTIVE", "status": "inactive"}]},
            )
            unknown_result = import_settlements(
                store,
                run_id="stage3a_unknown",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_UNKNOWN", "status": "settled"}]},
            )

            self.assertEqual(open_result["rows_updated"], 0)
            self.assertEqual(inactive_result["rows_updated"], 0)
            self.assertEqual(unknown_result["rows_updated"], 0)
            self.assertEqual(unknown_result["settlement_issue_counts"]["unknown_settlement_state"], 1)
            open_row = _query_one(store, "SELECT settlement_state, profit_loss_cents, settlement_issue FROM prediction_logs WHERE run_id = ?", ("stage3a_open",))
            inactive_row = _query_one(store, "SELECT settlement_state, profit_loss_cents, settlement_issue FROM prediction_logs WHERE run_id = ?", ("stage3a_inactive",))
            unknown_row = _query_one(store, "SELECT settlement_state, profit_loss_cents, settlement_issue FROM prediction_logs WHERE run_id = ?", ("stage3a_unknown",))
            self.assertEqual(open_row["settlement_state"], "unresolved")
            self.assertIsNone(open_row["profit_loss_cents"])
            self.assertIsNone(open_row["settlement_issue"])
            self.assertEqual(inactive_row["settlement_state"], "unresolved")
            self.assertIsNone(inactive_row["profit_loss_cents"])
            self.assertIsNone(inactive_row["settlement_issue"])
            self.assertEqual(unknown_row["settlement_state"], "unresolved")
            self.assertIsNone(unknown_row["profit_loss_cents"])
            self.assertEqual(unknown_row["settlement_issue"], "unknown_settlement_state")

    def test_settlement_import_is_idempotent_and_audited_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_idempotent", market_ticker="MKT_IDEM")
            payload = {"source": "test", "outcomes": [{"market_id": "MKT_IDEM", "winning_side": "yes"}]}

            first = import_settlements(store, run_id="stage3a_idempotent", settlements_payload=payload)
            second = import_settlements(store, run_id="stage3a_idempotent", settlements_payload=payload)

            self.assertEqual(first["rows_updated"], 1)
            self.assertEqual(second["rows_updated"], 0)
            row = _query_one(store, "SELECT settlement_state, profit_loss_cents FROM prediction_logs WHERE run_id = ?", ("stage3a_idempotent",))
            audit = _query_one(store, "SELECT COUNT(*) AS count FROM settlement_audit WHERE run_id = ?", ("stage3a_idempotent",))
            self.assertEqual(row["settlement_state"], "win")
            self.assertEqual(row["profit_loss_cents"], 18.0)
            self.assertEqual(audit["count"], 1)

    def test_settlement_does_not_mutate_original_prediction_evidence(self):
        immutable_fields = [
            "prediction_timestamp",
            "event_start_time",
            "market_close_time",
            "api_fetched_at",
            "source_snapshot_hash",
            "entry_price_cents",
            "model_version",
            "strategy",
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            _log_valid_prediction(store, run_id="stage3a_immutable", market_ticker="MKT_IMMUTABLE")
            before = _query_one(store, f"SELECT {', '.join(immutable_fields)} FROM prediction_logs WHERE run_id = ?", ("stage3a_immutable",))

            import_settlements(
                store,
                run_id="stage3a_immutable",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_IMMUTABLE", "result": "no"}]},
            )

            after = _query_one(store, f"SELECT {', '.join(immutable_fields)} FROM prediction_logs WHERE run_id = ?", ("stage3a_immutable",))
            self.assertEqual(after, before)

    def test_roi_and_win_rate_exclude_unresolved_invalid_legacy_and_rejected_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            start_paper_test_run(store, run_id="stage3a_metric_filters")
            payload = {
                "generated_at": "2026-07-03T15:59:00Z",
                "custom_slip": _combo_slip(
                    [
                        _leg(market_ticker="MKT_SETTLED", ask_cents=82),
                        _leg(market_ticker="MKT_UNRESOLVED", ask_cents=82),
                        _leg(market_ticker="MKT_REJECTED", event_start_time=""),
                    ],
                ),
            }
            log_forward_predictions(store, payload, run_id="stage3a_metric_filters", logged_at="2026-07-03T16:00:00Z")
            store.insert_prediction_logs(
                [
                    {
                        "run_id": "stage3a_metric_filters",
                        "timestamp": "2026-07-03T16:00:00Z",
                        "event": "Invalid",
                        "market": "MKT_INVALID",
                        "market_id": "MKT_INVALID",
                        "side": "yes",
                        "event_start_time": "",
                        "market_close_time": "",
                        "input_data_used": {},
                        "odds_used": {"ask_cents": 82},
                        "model_version": "test",
                        "confidence_score": 0.82,
                        "confidence_label": "price_implied",
                        "predicted_outcome": "yes",
                    },
                    {
                        "timestamp": "2026-07-03T15:00:00Z",
                        "event": "Legacy",
                        "market": "MKT_LEGACY",
                        "side": "yes",
                        "event_start_time": "2026-07-03T20:00:00Z",
                        "market_close_time": "2026-07-03T20:00:00Z",
                        "input_data_used": {},
                        "odds_used": {"ask_cents": 82},
                        "model_version": "legacy",
                        "confidence_score": 0.82,
                        "confidence_label": "price_implied",
                        "predicted_outcome": "yes",
                    },
                ]
            )
            import_settlements(
                store,
                run_id="stage3a_metric_filters",
                settlements_payload={"source": "test", "outcomes": [{"market_id": "MKT_SETTLED", "winning_side": "yes"}]},
            )

            report = build_daily_report(store, run_id="stage3a_metric_filters")
            rendered = render_daily_report(report)
            self.assertEqual(report["new_predictions_logged"], 2)
            self.assertEqual(report["settled_predictions"], 1)
            self.assertEqual(report["unresolved_predictions"], 1)
            self.assertEqual(report["invalid_rejected_predictions"], 1)
            self.assertEqual(report["invalid_prediction_log_rows"], 1)
            self.assertEqual(report["legacy_rows_excluded"], 1)
            self.assertEqual(report["settled_profit_loss_cents_fee_excluded"], 18.0)
            self.assertEqual(report["settled_risked_cents"], 82.0)
            self.assertIsNone(report["win_rate"])
            self.assertIsNone(report["roi_fee_excluded"])
            self.assertIn("ROI fee-excluded", rendered)
            self.assertIn("sample too small; research-only", rendered)

    def test_stage3b_audit_blocks_when_raw_settled_is_duplicate_bloat(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            run_id = "stage3b_duplicate_bloat"
            start_paper_test_run(store, run_id=run_id)
            rows = [
                _settled_log(
                    index,
                    run_id=run_id,
                    market_id="MKT_DUPLICATE",
                    strategy=f"strategy_{index % 4}",
                    timestamp=f"2026-07-03T16:{index // 2:02d}:{index % 2:02d}Z",
                )
                for index in range(100)
            ]
            store.insert_prediction_logs(rows)

            audit = build_stage3b_audit_report(store, run_id=run_id)
            rendered = render_stage3b_audit_report(audit)

            self.assertEqual(audit["raw_settled_rows"], 100)
            self.assertEqual(audit["deduped_settled_market_exposures"], 1)
            self.assertEqual(audit["gate_status"], "blocked_by_sample_size")
            self.assertIsNone(audit["deduped_market_performance"]["roi_fee_excluded"])
            self.assertIn("No profitability, edge, or calibration claim", rendered)

    def test_stage3b_audit_reports_research_only_after_deduped_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "eval.sqlite")
            run_id = "stage3b_ready"
            start_paper_test_run(store, run_id=run_id)
            rows = [
                _settled_log(
                    index,
                    run_id=run_id,
                    state="win" if index < 80 else "loss",
                    strategy="primary_80" if index % 2 == 0 else "leverage_75",
                )
                for index in range(100)
            ]
            store.insert_prediction_logs(rows)

            audit = build_stage3b_audit_report(store, run_id=run_id)
            rendered = render_stage3b_audit_report(audit)

            self.assertEqual(audit["gate_status"], "stage3b_audit_ready")
            self.assertEqual(audit["raw_settled_rows"], 100)
            self.assertEqual(audit["deduped_settled_market_exposures"], 100)
            self.assertEqual(audit["deduped_market_performance"]["win_rate"], 0.8)
            self.assertEqual(audit["deduped_market_performance"]["roi_fee_excluded"], 0.0)
            self.assertIn("research-only", rendered)
            self.assertIn("No profitability, edge, or calibration claim", rendered)


if __name__ == "__main__":
    unittest.main()
