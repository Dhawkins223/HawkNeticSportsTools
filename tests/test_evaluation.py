from __future__ import annotations

from kalshi_research_bot.evaluation import build_backtest_report, confidence_guardrail, data_quality_failures, run_backtest
from kalshi_research_bot.evaluation.quality import prediction_validation_errors


def _snapshot(index: int, *, probability: float = 0.8, snapshot_at: str = "2026-07-03T15:00:00+00:00") -> dict:
    return {
        "snapshot_at": snapshot_at,
        "event": {"event_id": f"event-{index}", "name": f"Game {index}", "start_time": "2026-07-03T20:00:00+00:00"},
        "market": {"ticker": f"MKT{index}", "side": "yes", "yes_bid_cents": 49, "yes_ask_cents": 50, "no_ask_cents": 52, "close_time": "2026-07-03T20:00:00+00:00", "updated_time": "2026-07-03T14:55:00+00:00"},
        "prediction": {"side": "yes", "probability": probability, "model_version": "fixture", "evidence_count": 2, "source_backed": True, "margin_of_error": 0.04},
    }


def test_lookahead_and_post_start_snapshots_are_blocked() -> None:
    snapshot = _snapshot(1, snapshot_at="2026-07-03T21:00:00+00:00")
    snapshot["features"] = {"final_score": "7-4"}
    failures = data_quality_failures(snapshot)
    assert "snapshot_not_before_event_start" in failures
    assert "lookahead_field:final_score" in failures


def test_prediction_validation_and_confidence_guardrail_preserve_research_controls() -> None:
    missing = prediction_validation_errors({"timestamp": "2026-07-03T16:00:00+00:00"})
    assert "missing_run_id" in missing
    assert "missing_event_start_time" in missing
    blocked = confidence_guardrail(probability=0.91, evidence_count=0, source_backed=False, spread_cents=2)
    allowed = confidence_guardrail(probability=0.84, evidence_count=2, source_backed=True, spread_cents=2, margin_of_error=0.04)
    assert not blocked["high_confidence_allowed"]
    assert allowed["high_confidence_allowed"]


def test_backtest_uses_pre_event_data_and_withholds_tiny_samples() -> None:
    payload = {"snapshots": [_snapshot(1), _snapshot(2, probability=0.2)]}
    result = run_backtest(payload)
    report = build_backtest_report(result)
    assert result["data_quality"]["eligible_snapshots"] == 2
    assert "research-only" in report.lower()
