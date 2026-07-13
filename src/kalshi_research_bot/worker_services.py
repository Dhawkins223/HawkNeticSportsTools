from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .agents import ScrapeBot
from .config import repo_path
from .crypto_research import crypto_cycle
from .evaluation.kalshi_decomposition import (
    build_kalshi_return_decomposition,
    default_kalshi_return_decomposition_path,
    write_kalshi_return_decomposition,
)
from .evaluation.paper_live import (
    build_daily_report,
    build_stage3b_audit_report,
    default_daily_report_path,
    default_stage3b_audit_path,
    fetch_official_kalshi_settlements,
    import_settlements,
    write_daily_report,
    write_stage3b_audit_report,
)
from .sports_research import sports_cycle
from .storage import ResearchStore
from .monitoring import build_internal_status, send_monitoring_alerts
from .today import write_today_payload
from .worker_runtime import NonRetryableWorkerError, WorkerSpec


SERVICE_SPECS: dict[str, WorkerSpec] = {
    "kalshi-market-ingestion": WorkerSpec(
        name="kalshi-market-ingestion",
        asset_class="kalshi",
        cadence_seconds=300,
        expect_records=True,
    ),
    "external-source-ingestion": WorkerSpec(
        name="external-source-ingestion",
        asset_class="external",
        cadence_seconds=900,
    ),
    "crypto-research": WorkerSpec(
        name="crypto-research",
        asset_class="crypto",
        cadence_seconds=900,
        expect_records=True,
    ),
    "sports-research": WorkerSpec(
        name="sports-research",
        asset_class="sports",
        cadence_seconds=3600,
        expect_records=True,
    ),
    "settlement-worker": WorkerSpec(
        name="settlement-worker",
        asset_class="kalshi",
        cadence_seconds=3600,
    ),
    "reporting-evaluation": WorkerSpec(
        name="reporting-evaluation",
        asset_class="all",
        cadence_seconds=21600,
    ),
}


SERVICE_COMMANDS = {
    "web": "python -m kalshi_research_bot paper --host 0.0.0.0 --port $PORT --refresh-seconds 0",
    **{
        service: f"python -m kalshi_research_bot worker --service {service}"
        for service in SERVICE_SPECS
    },
}


def _kalshi_ingestion_operation(output_path: str | Path) -> Callable[[], Mapping[str, Any]]:
    def operation() -> Mapping[str, Any]:
        payload = write_today_payload(output_path)
        if payload.get("refresh_error"):
            raise RuntimeError(str(payload.get("refresh_error")))
        count = len(payload.get("games") or []) + len(payload.get("markets") or [])
        return {
            "records_processed": count,
            "data_fresh_at": payload.get("generated_at"),
            "source_fresh_at": payload.get("generated_at"),
            "source_snapshot_hash": payload.get("source_snapshot_hash"),
        }

    return operation


def _external_source_operation(config_path: str | Path, store: ResearchStore) -> Callable[[], Mapping[str, Any]]:
    def operation() -> Mapping[str, Any]:
        path = Path(config_path)
        if not path.exists():
            return {
                "records_processed": 0,
                "no_material_change": True,
                "state": "unconfigured_optional",
                "reason": "external_sources_config_missing",
            }
        records = ScrapeBot().collect(path)
        store.insert_source_records(records)
        return {"records_processed": len(records), "source_fresh_at": None}

    return operation


def _crypto_operation(db_path: str | Path, run_id: str) -> Callable[[], Mapping[str, Any]]:
    def operation() -> Mapping[str, Any]:
        result = crypto_cycle(db_path, run_id=run_id)
        logged = int(result["log_result"].get("logged_predictions") or 0)
        settled = int(result["settle_result"].get("rows_updated") or 0)
        rejected = int(result["log_result"].get("rejected_predictions") or 0)
        report = result["report"]
        source_status = report.get("source_status") or {}
        if not source_status.get("fresh", True) and logged == 0:
            raise NonRetryableWorkerError(str(source_status.get("reason") or "crypto_source_not_fresh"))
        return {
            "records_processed": logged + settled,
            "no_material_change": logged == 0 and settled == 0 and rejected == 0,
            "logged_predictions": logged,
            "settled_predictions": settled,
            "rejected_predictions": rejected,
            "pending_settlements": int(report.get("unresolved_predictions") or 0),
            "data_fresh_at": report.get("generated_at"),
            "source_fresh_at": report.get("latest_source_fetched_at"),
            "model_state": "baseline_only",
        }

    return operation


def _sports_operation(db_path: str | Path, run_id: str) -> Callable[[], Mapping[str, Any]]:
    def operation() -> Mapping[str, Any]:
        result = sports_cycle(db_path, run_id=run_id)
        logged = int(result["log_result"].get("logged_predictions") or 0)
        settled = int(result["settle_result"].get("rows_updated") or 0)
        rejected = int(result["log_result"].get("rejected_predictions") or 0)
        report = result["report"]
        if report.get("blockers") and logged == 0:
            raise NonRetryableWorkerError(str(report["blockers"][0]))
        return {
            "records_processed": logged + settled,
            "no_material_change": logged == 0 and settled == 0 and rejected == 0,
            "logged_predictions": logged,
            "settled_predictions": settled,
            "rejected_predictions": rejected,
            "pending_settlements": int(report.get("unresolved_predictions") or 0),
            "data_fresh_at": report.get("generated_at"),
            "source_fresh_at": report.get("latest_source_fetched_at"),
            "model_state": "baseline_only",
        }

    return operation


def _settlement_operation(store: ResearchStore, run_id: str) -> Callable[[], Mapping[str, Any]]:
    def operation() -> Mapping[str, Any]:
        payload = fetch_official_kalshi_settlements(store, run_id=run_id)
        if not payload.get("outcomes") and payload.get("fetch_errors"):
            raise NonRetryableWorkerError("kalshi_settlement_source_failed")
        result = import_settlements(store, run_id=run_id, settlements_payload=payload)
        report = build_daily_report(store, run_id=run_id)
        return {
            "records_processed": int(result.get("rows_updated") or 0),
            "no_material_change": int(result.get("rows_updated") or 0) == 0 and not result.get("fetch_errors"),
            "pending_settlements": int(report.get("unresolved_predictions") or 0),
            "settlement_issue_counts": result.get("settlement_issue_counts") or {},
            "source_fresh_at": payload.get("fetched_at"),
            "markets_requested": int(payload.get("markets_requested") or 0),
            "markets_deferred": int(payload.get("markets_deferred") or 0),
        }

    return operation


def _reporting_operation(store: ResearchStore, run_id: str) -> Callable[[], Mapping[str, Any]]:
    def operation() -> Mapping[str, Any]:
        daily = build_daily_report(store, run_id=run_id)
        stage3b = build_stage3b_audit_report(store, run_id=run_id)
        decomposition = build_kalshi_return_decomposition(store, run_id=run_id)
        write_daily_report(daily, default_daily_report_path(run_id))
        write_stage3b_audit_report(stage3b, default_stage3b_audit_path(run_id))
        write_kalshi_return_decomposition(decomposition, default_kalshi_return_decomposition_path(run_id))
        monitoring_status = build_internal_status(store.path)
        alert_results = send_monitoring_alerts(
            monitoring_status,
            run_id=run_id,
            report_path=str(default_daily_report_path(run_id)),
        )
        return {
            "records_processed": 3,
            "pending_settlements": int(daily.get("unresolved_predictions") or 0),
            "model_state": "baseline_only",
            "reports": [
                str(default_daily_report_path(run_id)),
                str(default_stage3b_audit_path(run_id)),
                str(default_kalshi_return_decomposition_path(run_id)),
            ],
            "monitoring_alert_results": [result.get("status") for result in alert_results],
        }

    return operation


def build_service_operation(
    service: str,
    *,
    db_path: str | Path,
    kalshi_run_id: str,
    crypto_run_id: str,
    sports_run_id: str,
) -> Callable[[], Mapping[str, Any]]:
    store = ResearchStore(db_path)
    if service == "kalshi-market-ingestion":
        return _kalshi_ingestion_operation(repo_path("data", "today_paper_view.json"))
    if service == "external-source-ingestion":
        config_path = os.environ.get("EXTERNAL_SOURCES_CONFIG", str(repo_path("config", "sources.json")))
        return _external_source_operation(config_path, store)
    if service == "crypto-research":
        return _crypto_operation(db_path, crypto_run_id)
    if service == "sports-research":
        return _sports_operation(db_path, sports_run_id)
    if service == "settlement-worker":
        return _settlement_operation(store, kalshi_run_id)
    if service == "reporting-evaluation":
        return _reporting_operation(store, kalshi_run_id)
    raise ValueError(f"unknown_worker_service:{service}")


def service_run_id(
    service: str,
    *,
    kalshi_run_id: str,
    crypto_run_id: str,
    sports_run_id: str,
) -> str:
    if service == "crypto-research":
        return crypto_run_id
    if service == "sports-research":
        return sports_run_id
    if service == "external-source-ingestion":
        return "external_sources"
    return kalshi_run_id
