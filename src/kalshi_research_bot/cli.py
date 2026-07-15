from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .agents import ComboBot, ReportBot, ScrapeBot
from .auth import LocalAuthStore
from .bot_company import bot_company_summary, render_bot_company
from .config import load_json, repo_path
from .connectors.airtable_status import bot_run_payload, sync_status
from .connectors.google_drive_archive import archive_files, default_report_paths
from .connectors.slack_alerts import build_alert_payload, send_alert
from .connectors.status import build_connectors_status, render_connectors_status
from .contracts import Game, MarketQuote, TotalLeg
from .crypto_research import (
    build_crypto_report,
    build_crypto_stage3b_audit_report,
    build_crypto_stage4_diagnostic_report,
    collect_crypto_payload,
    crypto_cycle,
    default_crypto_all_report_path,
    default_crypto_daily_report_path,
    default_crypto_features_path,
    default_crypto_labels_path,
    default_crypto_payload_path,
    default_crypto_stage3b_audit_path,
    default_crypto_stage4_diagnostic_path,
    export_crypto_features,
    log_crypto_predictions,
    render_crypto_report,
    render_crypto_stage3b_audit_report,
    render_crypto_stage4_diagnostic_report,
    settle_crypto_predictions,
    write_crypto_payload,
    write_crypto_report,
    write_crypto_stage3b_audit_report,
    write_crypto_stage4_diagnostic_report,
)
from .daemon import build_daemon_status, render_daemon_status
from .database import database_startup_status
from .db_migrations import apply_postgres_migrations, apply_sqlite_migrations
from .evaluation.backtest import load_backtest_payload, render_backtest_report, run_backtest, write_backtest_report
from .evaluation.paper_live import (
    build_daily_report,
    build_stage3b_audit_report,
    default_daily_report_path,
    default_run_lock_path,
    default_stage3b_audit_path,
    fetch_official_kalshi_settlements,
    import_settlements,
    load_json_payload,
    log_forward_predictions,
    render_daily_report,
    render_stage3b_audit_report,
    start_paper_test_run,
    write_daily_report,
    write_stage3b_audit_report,
)
from .evaluation.kalshi_decomposition import (
    build_kalshi_return_decomposition,
    default_kalshi_return_decomposition_path,
    render_kalshi_return_decomposition,
    write_kalshi_return_decomposition,
)
from .evaluation.model_audit import (
    build_platform_model_audit,
    default_platform_model_audit_path,
    render_platform_model_audit,
    write_platform_model_audit,
)
from .pipeline import ResearchPipeline
from .paper_server import run_server
from .sports_research import (
    append_sports_validation_ledger,
    build_sports_report,
    collect_sports_payload,
    default_sports_all_report_path,
    default_sports_daily_report_path,
    default_sports_features_path,
    default_sports_labels_path,
    default_sports_payload_path,
    default_sports_validation_ledger_path,
    export_sports_features,
    log_sports_predictions,
    read_sports_validation_ledger,
    render_sports_report,
    settle_sports_predictions,
    sports_cycle,
    write_sports_payload,
    write_sports_report,
)
from .source_quality import (
    build_data_quality_report,
    default_data_quality_json_path,
    default_data_quality_report_path,
    render_data_quality_report,
    write_data_quality_report,
)
from .business_store import create_research_store
from .storage import ResearchStore
from .today import write_today_payload
from .monitoring import build_internal_status
from .operator_inbox import OperatorInbox, PRIORITIES, STATUSES, TARGETS
from .postgres_migration import (
    export_sqlite_for_postgres,
    import_sqlite_export_to_postgres,
    validate_sqlite_export,
)
from .worker_runtime import run_worker_forever, run_worker_once
from .worker_services import SERVICE_SPECS, build_service_operation, service_run_id


def load_games(path: str | Path) -> list[Game]:
    payload = load_json(path)
    return [Game(**game) for game in payload.get("games", [])]


def load_quotes(path: str | Path) -> list[MarketQuote]:
    payload = load_json(path)
    return [MarketQuote(**quote) for quote in payload.get("quotes", [])]


def load_total_legs(path: str | Path) -> list[TotalLeg]:
    payload = load_json(path)
    return [TotalLeg(**leg) for leg in payload.get("legs", [])]


def run_demo(args: argparse.Namespace) -> int:
    games = load_games(repo_path("examples", "sample_games.json"))
    quotes = load_quotes(repo_path("examples", "sample_quotes.json"))
    edges = ResearchPipeline().run(games, quotes, min_edge_cents=args.min_edge)
    if args.save_db:
        create_research_store(args.save_db).insert_edge_results(edges)
    print(ReportBot().render_edges(edges))
    return 0


def run_research(args: argparse.Namespace) -> int:
    games = load_games(args.games)
    quotes = load_quotes(args.quotes)
    edges = ResearchPipeline().run(games, quotes, min_edge_cents=args.min_edge)
    if args.save_db:
        create_research_store(args.save_db).insert_edge_results(edges)
    print(ReportBot().render_edges(edges))
    return 0


def run_collect(args: argparse.Namespace) -> int:
    records = ScrapeBot().collect(args.sources)
    if args.save_db:
        create_research_store(args.save_db).insert_source_records(records)
    for record in records:
        print(f"[{record.kind}] {record.source}: {record.title}")
        print(record.url)
        if record.metadata:
            print(record.metadata)
        print()
    return 0


def run_combo(args: argparse.Namespace) -> int:
    legs = load_total_legs(args.legs)
    combos = ComboBot().build_ranked_combos(
        legs,
        target_probability=args.target,
        min_legs=args.min_legs,
        max_legs=args.max_legs,
        max_results=args.max_results,
        min_leg_probability=args.min_leg_probability,
    )
    print(ReportBot().render_combos(combos))
    return 0


def run_today(args: argparse.Namespace) -> int:
    payload = write_today_payload(args.output, args.date, public_intel_path=args.public_intel)
    print(f"Wrote {args.output}")
    print(f"Games: {len(payload.get('games', []))}")
    print(f"Kalshi combo markets: {len(payload.get('markets', []))}")
    pick = payload.get("pick_summary", {})
    print(f"Bot action: {pick.get('action', 'UNKNOWN')}")
    if pick.get("candidates"):
        best = pick["candidates"][0]
        print(f"Top candidate: {best['ticker']} @ {best['yes_ask_cents']:.2f}c")
        print(f"Adjusted probability: {best['adjusted_probability']:.2%}")
        print(f"Edge: {best['edge_cents']:.2f}c")
    return 0


def run_paper(args: argparse.Namespace) -> int:
    run_server(
        args.host,
        args.port,
        data_path=args.output,
        refresh_seconds=args.refresh_seconds,
        yyyymmdd=args.date,
        target_probability=args.target,
        min_leg_probability=args.min_leg_probability,
        max_leg_probability=args.max_leg_probability,
        min_legs=args.min_legs,
        max_legs=args.max_legs,
        stake_dollars=args.stake,
        leverage_min_leg_probability=args.leverage_target,
        public_intel_path=args.public_intel,
    )
    return 0


def run_database_status(args: argparse.Namespace) -> int:
    print(json.dumps(database_startup_status(), indent=2, sort_keys=True))
    return 0


def run_database_migrate(args: argparse.Namespace) -> int:
    if args.backend == "sqlite":
        store = ResearchStore(args.db)
        store.initialize()
        with store.connect() as connection:
            result = apply_sqlite_migrations(connection)
    else:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print("PostgreSQL migration blocked: DATABASE_URL is missing.")
            return 2
        result = apply_postgres_migrations(database_url)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def run_database_export(args: argparse.Namespace) -> int:
    manifest = export_sqlite_for_postgres(args.db, args.output)
    validation = validate_sqlite_export(args.db, args.output)
    print(json.dumps({"manifest": manifest, "validation": validation}, indent=2, sort_keys=True))
    return 0 if validation["valid"] else 1


def run_database_validate_export(args: argparse.Namespace) -> int:
    result = validate_sqlite_export(args.db, args.input)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


def run_database_import(args: argparse.Namespace) -> int:
    if args.confirm != "IMPORT_RESEARCH_HISTORY":
        print("PostgreSQL import blocked: pass --confirm IMPORT_RESEARCH_HISTORY after reviewing the manifest.")
        return 2
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("PostgreSQL import blocked: DATABASE_URL is missing.")
        return 2
    result = import_sqlite_export_to_postgres(args.input, database_url=database_url)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"imported", "already_imported"} else 1


def run_auth_create_user(args: argparse.Namespace) -> int:
    if str(os.environ.get("AUTH_REGISTRATION_ENABLED", "false")).lower() not in {"1", "true", "yes", "on"}:
        print("Account creation blocked: set AUTH_REGISTRATION_ENABLED=true for this local command.")
        return 2
    password = os.environ.get("AUTH_NEW_USER_PASSWORD")
    if not password:
        print("Account creation blocked: AUTH_NEW_USER_PASSWORD is missing.")
        return 2
    created = LocalAuthStore(args.db).create_user(args.username, password, role=args.role)
    print(json.dumps(created, indent=2, sort_keys=True))
    return 0


def run_auth_disable_user(args: argparse.Namespace) -> int:
    changed = LocalAuthStore(args.db).set_disabled(args.username, disabled=not args.enable)
    print(json.dumps({"username": args.username, "disabled": not args.enable, "updated": changed}, indent=2))
    return 0 if changed else 1


def run_operator_message_add(args: argparse.Namespace) -> int:
    body_path = Path(args.file)
    if not body_path.is_file():
        print(f"Operator message blocked: file not found: {body_path}")
        return 2
    try:
        message = OperatorInbox(args.db).add(
            title=args.title,
            body=body_path.read_text(encoding="utf-8"),
            created_by=args.created_by,
            priority=args.priority,
            target=args.target,
            source="cli",
            message_id=args.message_id,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"Operator message blocked: {exc}")
        return 2
    print(json.dumps(message, indent=2, sort_keys=True))
    print("Queued for manual agent review; no command or code was executed.")
    return 0


def run_operator_message_list(args: argparse.Namespace) -> int:
    messages = OperatorInbox(args.db).list(
        status=args.status,
        target=args.target,
        limit=args.limit,
    )
    print(json.dumps({"counts": OperatorInbox(args.db).counts(), "messages": messages}, indent=2, sort_keys=True))
    return 0


def run_operator_message_claim(args: argparse.Namespace) -> int:
    try:
        message = OperatorInbox(args.db).claim(args.message_id, agent=args.agent)
    except ValueError as exc:
        print(f"Operator message claim blocked: {exc}")
        return 2
    print(json.dumps(message, indent=2, sort_keys=True))
    return 0


def run_operator_message_complete(args: argparse.Namespace) -> int:
    summary_path = Path(args.summary_file)
    if not summary_path.is_file():
        print(f"Operator message completion blocked: file not found: {summary_path}")
        return 2
    try:
        message = OperatorInbox(args.db).complete(
            args.message_id,
            agent=args.agent,
            summary=summary_path.read_text(encoding="utf-8"),
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"Operator message completion blocked: {exc}")
        return 2
    print(json.dumps(message, indent=2, sort_keys=True))
    return 0


def run_worker_command(args: argparse.Namespace) -> int:
    spec = SERVICE_SPECS[args.service]
    operation = build_service_operation(
        args.service,
        db_path=args.db,
        kalshi_run_id=args.kalshi_run_id,
        crypto_run_id=args.crypto_run_id,
        sports_run_id=args.sports_run_id,
    )
    run_id = service_run_id(
        args.service,
        kalshi_run_id=args.kalshi_run_id,
        crypto_run_id=args.crypto_run_id,
        sports_run_id=args.sports_run_id,
    )
    if args.once:
        result = run_worker_once(
            spec,
            operation,
            db_path=args.db,
            run_id=run_id,
            idempotency_key=args.idempotency_key,
        )
        return 0 if result["status"] in {"success", "skipped_duplicate"} else 1
    return run_worker_forever(spec, operation, db_path=args.db, run_id=run_id)


def run_worker_status(args: argparse.Namespace) -> int:
    print(json.dumps(build_internal_status(args.db), indent=2, sort_keys=True))
    return 0


def run_pick(args: argparse.Namespace) -> int:
    payload = write_today_payload(args.output, args.date)
    pick = payload.get("pick_summary", {})
    print(f"Bot action: {pick.get('action', 'UNKNOWN')}")
    print(pick.get("reason", ""))
    print(f"Tradable combos scanned: {pick.get('tradable_combo_count', 0)}")
    candidates = pick.get("candidates", [])
    if not candidates:
        print("No bet ticket generated.")
        return 0
    best = candidates[0]
    print()
    print("BET TICKET")
    print(f"Ticker: {best['ticker']}")
    print(f"YES ask: {best['yes_ask_cents']:.2f}c")
    print(f"Adjusted probability: {best['adjusted_probability']:.2%}")
    print(f"Estimated edge: {best['edge_cents']:.2f}c")
    print("Legs:")
    for leg in best.get("legs", []):
        probability = leg.get("market_implied_probability")
        probability_text = "n/a" if probability is None else f"{probability:.2%}"
        print(f"- {leg.get('side', '').upper()} {leg.get('subtitle') or leg.get('title')} ({probability_text})")
    return 0


def run_slip(args: argparse.Namespace) -> int:
    payload = write_today_payload(
        args.output,
        args.date,
        slip_target_probability=args.target,
        slip_min_leg_probability=args.min_leg_probability,
        slip_max_leg_probability=args.max_leg_probability,
        slip_min_legs=args.min_legs,
        slip_max_legs=args.max_legs,
        slip_stake_dollars=args.stake,
        public_intel_path=args.public_intel,
    )
    slip = payload.get("custom_slip", {})
    print(f"Bot action: {slip.get('action', 'UNKNOWN')}")
    if slip.get("action") != "BUILD_SLIP":
        print(slip.get("reason", "No slip generated."))
        print(f"Eligible legs: {slip.get('eligible_leg_count', 0)}")
        return 0
    print(f"Min individual leg probability: {slip['min_leg_probability']:.0%}")
    print(f"Full slip chance: {slip['adjusted_probability']:.2%}")
    print(f"Raw multiplied chance: {slip['raw_probability']:.2%}")
    print(f"Legs: {slip['leg_count']}")
    print(f"Sports: {', '.join(slip['sports'])}")
    print(f"Estimated combo price: {slip['estimated_combo_price_cents']:.2f}c")
    print(f"${slip['stake_dollars']:.2f} estimated payout if right: ${slip['estimated_payout_if_right']:.2f}")
    print()
    print("SLIP")
    current_sport = None
    for leg in slip.get("legs", []):
        if leg["sport"] != current_sport:
            current_sport = leg["sport"]
            print(current_sport)
        label = leg.get("subtitle") or leg.get("title") or leg.get("market_ticker")
        event = leg.get("display_event") or leg.get("event_ticker", "")
        print(f"- {event}: {leg.get('side', '').upper()} {label} ({leg['probability']:.2%})")
    return 0


def run_backtest_command(args: argparse.Namespace) -> int:
    payload = load_backtest_payload(args.input)
    report = run_backtest(payload)
    if args.output:
        write_backtest_report(report, args.output)
        print(f"Wrote {args.output}")
    print(render_backtest_report(report))
    return 0


def run_paper_run_start(args: argparse.Namespace) -> int:
    store = create_research_store(args.db)
    run = start_paper_test_run(
        store,
        run_id=args.run_id,
        lock_path=args.lock_path,
    )
    print(f"Started private paper run: {run['run_id']}")
    print(f"Config hash: {run['config_hash']}")
    print(f"Lock file: {args.lock_path}")
    return 0


def run_paper_log(args: argparse.Namespace) -> int:
    store = create_research_store(args.db)
    payload = load_json_payload(args.input)
    result = log_forward_predictions(store, payload, run_id=args.run_id)
    print(f"Run: {args.run_id}")
    print(f"Attempted predictions: {result['attempted_predictions']}")
    print(f"Logged predictions: {result['logged_predictions']}")
    print(f"Rejected predictions: {result['rejected_predictions']}")
    print(f"Duplicate rows ignored: {result.get('duplicate_rows_ignored', 0)}")
    if result["rejection_reasons"]:
        print(f"Rejection reasons: {', '.join(result['rejection_reasons'])}")
    if args.report:
        report = build_daily_report(store, run_id=args.run_id, date=args.date)
        write_daily_report(report, args.report)
        print(f"Wrote report: {args.report}")
    return 0


def run_paper_settle(args: argparse.Namespace) -> int:
    store = create_research_store(args.db)
    settlements = load_json_payload(args.settlements)
    result = import_settlements(store, run_id=args.run_id, settlements_payload=settlements)
    print(f"Run: {args.run_id}")
    print(f"Settlement markets available: {result['settlements_available']}")
    print(f"Prediction rows updated: {result['rows_updated']}")
    if args.report:
        report = build_daily_report(store, run_id=args.run_id, date=args.date)
        write_daily_report(report, args.report)
        print(f"Wrote report: {args.report}")
    return 0


def run_paper_settle_kalshi(args: argparse.Namespace) -> int:
    store = create_research_store(args.db)
    settlements = fetch_official_kalshi_settlements(store, run_id=args.run_id)
    result = import_settlements(store, run_id=args.run_id, settlements_payload=settlements)
    print(f"Run: {args.run_id}")
    print(f"Settlement source: {result['settlement_source']}")
    print(f"Settlement markets available: {result['settlements_available']}")
    print(f"Prediction rows updated: {result['rows_updated']}")
    print(f"Settlement issue rows updated: {result['issue_rows_updated']}")
    if result.get("settlement_issue_counts"):
        print(f"Settlement issues: {result['settlement_issue_counts']}")
    if result.get("fetch_errors"):
        print(f"Settlement fetch errors: {len(result['fetch_errors'])}")
    if args.report:
        report = build_daily_report(store, run_id=args.run_id, date=args.date)
        write_daily_report(report, args.report)
        print(f"Wrote report: {args.report}")
    return 0


def run_paper_report(args: argparse.Namespace) -> int:
    store = create_research_store(args.db)
    report = build_daily_report(store, run_id=args.run_id, date=args.date)
    if args.output:
        write_daily_report(report, args.output)
        print(f"Wrote {args.output}")
    print(render_daily_report(report))
    return 0


def run_paper_stage3b_audit(args: argparse.Namespace) -> int:
    store = create_research_store(args.db)
    report = build_stage3b_audit_report(store, run_id=args.run_id)
    if args.output:
        write_stage3b_audit_report(report, args.output)
        print(f"Wrote {args.output}")
    print(render_stage3b_audit_report(report))
    return 0


def run_kalshi_return_audit(args: argparse.Namespace) -> int:
    store = create_research_store(args.db)
    report = build_kalshi_return_decomposition(store, run_id=args.run_id)
    if args.output:
        write_kalshi_return_decomposition(report, args.output)
        print(f"Wrote {args.output}")
        print(f"Wrote {Path(args.output).with_suffix('.json')}")
    print(render_kalshi_return_decomposition(report))
    return 0


def run_model_evaluate(args: argparse.Namespace) -> int:
    report = build_platform_model_audit(
        args.db,
        kalshi_run_id=args.kalshi_run_id,
        crypto_run_id=args.crypto_run_id,
        sports_run_id=args.sports_run_id,
        persist=not args.no_persist,
    )
    if args.output:
        write_platform_model_audit(report, args.output)
        print(f"Wrote {args.output}")
        print(f"Wrote {Path(args.output).with_suffix('.json')}")
    print(render_platform_model_audit(report))
    return 0


def run_crypto_collect(args: argparse.Namespace) -> int:
    payload = collect_crypto_payload()
    write_crypto_payload(args.output, payload)
    print(f"Wrote {args.output}")
    print(f"Crypto records: {len(payload.get('records', []))}")
    if payload.get("errors"):
        print(f"Source errors: {payload['errors']}")
    return 0


def run_crypto_log(args: argparse.Namespace) -> int:
    payload = load_json_payload(args.input)
    result = log_crypto_predictions(args.db, run_id=args.run_id, payload=payload)
    print(f"Run: {args.run_id}")
    print(f"Attempted predictions: {result['attempted_predictions']}")
    print(f"Logged predictions: {result['logged_predictions']}")
    print(f"Rejected predictions: {result['rejected_predictions']}")
    print(f"Duplicate rows ignored: {result['duplicate_rows_ignored']}")
    print(f"Rejection reasons: {result['rejection_reasons']}")
    if args.report:
        report = build_crypto_report(args.db, run_id=args.run_id)
        write_crypto_report(report, args.report)
        print(f"Wrote report: {args.report}")
    return 0


def run_crypto_settle(args: argparse.Namespace) -> int:
    payload = load_json_payload(args.input)
    result = settle_crypto_predictions(args.db, run_id=args.run_id, payload=payload)
    print(f"Run: {args.run_id}")
    print(f"Prediction rows updated: {result['rows_updated']}")
    print(f"Unresolved rows: {result['unresolved_rows']}")
    print(f"Settlement issues: {result['settlement_issue_counts']}")
    if args.report:
        report = build_crypto_report(args.db, run_id=args.run_id)
        write_crypto_report(report, args.report)
        print(f"Wrote report: {args.report}")
    return 0


def run_crypto_report(args: argparse.Namespace) -> int:
    report = build_crypto_report(args.db, run_id=args.run_id)
    if args.output:
        write_crypto_report(report, args.output)
        print(f"Wrote {args.output}")
    print(render_crypto_report(report))
    return 0


def run_crypto_stage3b_audit(args: argparse.Namespace) -> int:
    report = build_crypto_stage3b_audit_report(args.db, run_id=args.run_id)
    if args.output:
        write_crypto_stage3b_audit_report(report, args.output)
        print(f"Wrote {args.output}")
    print(render_crypto_stage3b_audit_report(report))
    return 0


def run_crypto_stage4_diagnostic(args: argparse.Namespace) -> int:
    report = build_crypto_stage4_diagnostic_report(args.db, run_id=args.run_id)
    if args.output:
        write_crypto_stage4_diagnostic_report(report, args.output)
        print(f"Wrote {args.output}")
    print(render_crypto_stage4_diagnostic_report(report))
    return 0


def run_crypto_cycle(args: argparse.Namespace) -> int:
    result = crypto_cycle(args.db, run_id=args.run_id, output=args.output)
    report = result["report"]
    print(f"Run: {args.run_id}")
    print(f"Payload: {result['payload_path']}")
    print(f"Heartbeat status: {report.get('heartbeat_status', 'unknown')}")
    print(f"Logged predictions: {result['log_result']['logged_predictions']}")
    print(f"Rejected predictions: {result['log_result']['rejected_predictions']}")
    if result["log_result"].get("rejection_reasons"):
        print(f"Rejection reasons: {result['log_result']['rejection_reasons']}")
    print(f"Settled rows: {result['settle_result']['rows_updated']}")
    print(f"Unresolved predictions: {report.get('unresolved_predictions')}")
    print(f"Source error count: {report.get('source_error_count', 0)}")
    if report.get("blockers"):
        print(f"Blockers: {report['blockers']}")
    if report.get("source_errors"):
        reasons = sorted({str(error.get("error") or error.get("reason") or "source_fetch_error") for error in report["source_errors"]})
        print(f"Source error reasons: {reasons}")
    print(f"Gate: {report['gate_result']}")
    return 0


def run_crypto_export_features(args: argparse.Namespace) -> int:
    result = export_crypto_features(args.db, run_id=args.run_id, output=args.output, labels_output=args.labels_output)
    print(f"Feature rows: {result['feature_rows']}")
    print(f"Label rows: {result['label_rows']}")
    print(f"Wrote {result['output']}")
    if result.get("labels_output"):
        print(f"Wrote {result['labels_output']}")
    return 0


def run_sports_collect(args: argparse.Namespace) -> int:
    payload = collect_sports_payload(sport_key=args.sport)
    write_sports_payload(args.output, payload)
    print(f"Wrote {args.output}")
    if payload.get("blocker"):
        print(f"Blocker: {payload['blocker']} ({payload.get('required_env_var')})")
    print(f"Sports records: {len(payload.get('records', []))}")
    return 0


def run_sports_log(args: argparse.Namespace) -> int:
    payload = load_json_payload(args.input)
    result = log_sports_predictions(args.db, run_id=args.run_id, payload=payload)
    print(f"Run: {args.run_id}")
    if result.get("blocker"):
        print(f"Blocker: {result['blocker']}")
    print(f"Attempted predictions: {result['attempted_predictions']}")
    print(f"Logged predictions: {result['logged_predictions']}")
    print(f"Rejected predictions: {result['rejected_predictions']}")
    print(f"Duplicate rows ignored: {result['duplicate_rows_ignored']}")
    print(f"Rejection reasons: {result['rejection_reasons']}")
    if args.report:
        report = build_sports_report(args.db, run_id=args.run_id)
        write_sports_report(report, args.report)
        print(f"Wrote report: {args.report}")
    return 0


def run_sports_settle(args: argparse.Namespace) -> int:
    finals = load_json_payload(args.finals)
    result = settle_sports_predictions(args.db, run_id=args.run_id, finals_payload=finals)
    print(f"Run: {args.run_id}")
    print(f"Prediction rows updated: {result['rows_updated']}")
    print(f"Unresolved rows: {result['unresolved_rows']}")
    print(f"Settlement issues: {result['settlement_issue_counts']}")
    if args.report:
        report = build_sports_report(args.db, run_id=args.run_id)
        write_sports_report(report, args.report)
        print(f"Wrote report: {args.report}")
    return 0


def run_sports_report(args: argparse.Namespace) -> int:
    report = build_sports_report(args.db, run_id=args.run_id)
    if args.output:
        write_sports_report(report, args.output)
        print(f"Wrote {args.output}")
    print(render_sports_report(report))
    return 0


def run_sports_record_status(args: argparse.Namespace) -> int:
    report = build_sports_report(args.db, run_id=args.run_id)
    ledger_path = args.output or str(default_sports_validation_ledger_path(args.run_id))
    entry = append_sports_validation_ledger(report, path=ledger_path)
    report["validation_ledger_path"] = ledger_path
    report["validation_ledger_status"] = "recorded"
    report["latest_validation_record"] = entry
    if args.report:
        write_sports_report(report, args.report)
        print(f"Wrote report: {args.report}")
    print(f"Recorded sports validation ledger: {ledger_path}")
    print(f"Valid sports predictions total: {entry['valid_sports_predictions_total']}")
    print(f"Settled de-duped exposures: {entry['deduped_settled_exposures']}")
    print(f"Rejected rows: {entry['rejected_rows']}")
    print(f"Win rate: {entry['win_rate'] if entry['win_rate'] is not None else entry['win_rate_status']}")
    if args.tail:
        rows = read_sports_validation_ledger(ledger_path, limit=args.tail)
        print(f"Ledger rows shown: {len(rows)}")
        for row in rows:
            print(
                f"- {row.get('recorded_at')} valid={row.get('valid_sports_predictions_total')} "
                f"settled_deduped={row.get('deduped_settled_exposures')} "
                f"rejected={row.get('rejected_rows')} win_rate_status={row.get('win_rate_status')}"
            )
    return 0


def run_sports_cycle(args: argparse.Namespace) -> int:
    result = sports_cycle(args.db, run_id=args.run_id, output=args.output, finals=args.finals)
    print(f"Run: {args.run_id}")
    print(f"Payload: {result['payload_path']}")
    if result["log_result"].get("blocker"):
        print(f"Blocker: {result['log_result']['blocker']}")
    print(f"Logged predictions: {result['log_result']['logged_predictions']}")
    print(f"Rejected predictions: {result['log_result']['rejected_predictions']}")
    print(f"Settled rows: {result['settle_result']['rows_updated']}")
    print(f"Validation ledger: {result['report'].get('validation_ledger_path')}")
    print(f"Gate: {result['report']['gate_result']}")
    return 0


def run_sports_export_features(args: argparse.Namespace) -> int:
    result = export_sports_features(args.db, run_id=args.run_id, output=args.output, labels_output=args.labels_output)
    print(f"Feature rows: {result['feature_rows']}")
    print(f"Label rows: {result['label_rows']}")
    print(f"Wrote {result['output']}")
    if result.get("labels_output"):
        print(f"Wrote {result['labels_output']}")
    return 0


def run_connectors_status(args: argparse.Namespace) -> int:
    print(render_connectors_status(build_connectors_status()))
    return 0


def run_archive_reports(args: argparse.Namespace) -> int:
    paths = [Path(path) for path in args.paths] if args.paths else default_report_paths()
    result = archive_files(paths)
    print(f"Archive status: {result['status']}")
    print(f"Uploaded: {result['uploaded_count']}")
    print(f"Failed: {result['failed_count']}")
    return 0


def run_sync_status(args: argparse.Namespace) -> int:
    report: dict[str, Any] | None = None
    if args.run_id and args.asset_class == "crypto":
        report = build_crypto_report(args.db, run_id=args.run_id)
    elif args.run_id and args.asset_class == "sports":
        report = build_sports_report(args.db, run_id=args.run_id)
    elif args.run_id and args.asset_class == "kalshi":
        report = build_daily_report(create_research_store(args.db), run_id=args.run_id)
    payloads = {"bot_runs": []}
    if report:
        payloads["bot_runs"].append(
            bot_run_payload(
                report,
                bot_name=args.bot_name or args.asset_class,
                asset_class=args.asset_class,
                stage=args.stage,
                mode="private_research",
            )
        )
    result = sync_status(payloads)
    print(f"Airtable status: {result['status']}")
    print(f"Synced: {result['synced_count']}")
    return 0


def run_send_alert_test(args: argparse.Namespace) -> int:
    alert = build_alert_payload(
        bot_name=args.bot_name,
        asset_class=args.asset_class,
        run_id=args.run_id,
        severity=args.severity,
        event_type="connector_test",
        message="Private research bot connector test alert.",
        report_path=args.report_path,
        next_action="confirm Slack delivery only if alerts are enabled",
    )
    result = send_alert(alert)
    print(f"Slack status: {result['status']}")
    print(f"Sent: {result['sent']}")
    return 0


def run_daemon_status(args: argparse.Namespace) -> int:
    status = build_daemon_status(
        dashboard_url=args.dashboard_url,
        crypto_run_id=args.crypto_run_id,
        sports_run_id=args.sports_run_id,
        kalshi_run_id=args.kalshi_run_id,
    )
    print(render_daemon_status(status))
    return 0


def run_data_quality(args: argparse.Namespace) -> int:
    report = build_data_quality_report(
        db_path=args.db,
        dashboard_payload_path=args.dashboard_payload,
        audit_path=args.audit_path,
        error_path=args.error_path,
        crypto_run_id=args.crypto_run_id,
        sports_run_id=args.sports_run_id,
        kalshi_run_id=args.kalshi_run_id,
    )
    if args.output:
        write_data_quality_report(report, args.output, args.json_output)
        print(f"Wrote {args.output}")
        if args.json_output:
            print(f"Wrote {args.json_output}")
    print(render_data_quality_report(report))
    return 0


def run_company_status(args: argparse.Namespace) -> int:
    print(render_bot_company(bot_company_summary()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kalshi-research-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="run the sample research pipeline")
    demo.add_argument("--min-edge", type=float, default=0.0)
    demo.add_argument("--save-db")
    demo.set_defaults(func=run_demo)

    run = subparsers.add_parser("run", help="run research with local game and quote JSON")
    run.add_argument("--games", required=True)
    run.add_argument("--quotes", required=True)
    run.add_argument("--min-edge", type=float, default=0.0)
    run.add_argument("--save-db")
    run.set_defaults(func=run_research)

    collect = subparsers.add_parser("collect", help="collect enabled sources from a source config")
    collect.add_argument("--sources", default=str(repo_path("config", "sources.example.json")))
    collect.add_argument("--save-db")
    collect.set_defaults(func=run_collect)

    combo = subparsers.add_parser("combo", help="rank over/under combos by combined probability")
    combo.add_argument("--legs", default=str(repo_path("examples", "sample_totals.json")))
    combo.add_argument("--target", type=float, default=0.80)
    combo.add_argument("--min-legs", type=int, default=2)
    combo.add_argument("--max-legs", type=int, default=5)
    combo.add_argument("--max-results", type=int, default=20)
    combo.add_argument("--min-leg-probability", type=float, default=0.75)
    combo.set_defaults(func=run_combo)

    today = subparsers.add_parser("today", help="fetch today's public schedule and Kalshi combo markets")
    today.add_argument("--date", help="date as YYYYMMDD; defaults to local today")
    today.add_argument("--output", default=str(repo_path("data", "today_paper_view.json")))
    today.add_argument("--public-intel", help="optional JSON file of public bettor/trader signals")
    today.set_defaults(func=run_today)

    paper = subparsers.add_parser("paper", help="serve the local paper-view dashboard")
    paper.add_argument("--host", default="127.0.0.1")
    paper.add_argument("--port", type=int, default=8765)
    paper.add_argument("--date", help="date as YYYYMMDD; defaults to local today")
    paper.add_argument("--output", default=str(repo_path("data", "today_paper_view.json")))
    paper.add_argument("--refresh-seconds", type=int, default=600)
    paper.add_argument("--target", type=float, default=0.80, help="minimum individual leg probability")
    paper.add_argument("--min-legs", type=int, default=8)
    paper.add_argument("--max-legs", type=int, default=20)
    paper.add_argument("--min-leg-probability", type=float, default=None, help="override --target for each leg")
    paper.add_argument("--max-leg-probability", type=float, default=0.985)
    paper.add_argument("--leverage-target", type=float, default=0.75, help="minimum individual leg probability for leverage slip")
    paper.add_argument("--public-intel", help="optional JSON file of public bettor/trader signals")
    paper.add_argument("--stake", type=float, default=5.0)
    paper.set_defaults(func=run_paper)

    database_status = subparsers.add_parser("database-status", help="private database readiness summary")
    database_status.set_defaults(func=run_database_status)

    database_migrate = subparsers.add_parser("database-migrate", help="apply versioned local or PostgreSQL migrations")
    database_migrate.add_argument("--backend", choices=["sqlite", "postgres"], default="sqlite")
    database_migrate.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    database_migrate.set_defaults(func=run_database_migrate)

    database_export = subparsers.add_parser("database-export-sqlite", help="export immutable SQLite history for PostgreSQL")
    database_export.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    database_export.add_argument("--output", default=str(repo_path("data", "postgres_export")))
    database_export.set_defaults(func=run_database_export)

    database_validate = subparsers.add_parser("database-validate-export", help="revalidate a SQLite export manifest")
    database_validate.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    database_validate.add_argument("--input", default=str(repo_path("data", "postgres_export")))
    database_validate.set_defaults(func=run_database_validate_export)

    database_import = subparsers.add_parser("database-import-postgres", help="idempotently import reviewed SQLite export")
    database_import.add_argument("--input", default=str(repo_path("data", "postgres_export")))
    database_import.add_argument("--confirm", default="")
    database_import.set_defaults(func=run_database_import)

    auth_create = subparsers.add_parser("auth-create-user", help="create a private local dashboard account when enabled")
    auth_create.add_argument("--username", required=True)
    auth_create.add_argument("--role", choices=["admin", "researcher", "read_only"], required=True)
    auth_create.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    auth_create.set_defaults(func=run_auth_create_user)

    auth_disable = subparsers.add_parser("auth-disable-user", help="disable or re-enable a private dashboard account")
    auth_disable.add_argument("--username", required=True)
    auth_disable.add_argument("--enable", action="store_true")
    auth_disable.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    auth_disable.set_defaults(func=run_auth_disable_user)

    operator_add = subparsers.add_parser(
        "operator-message-add",
        help="queue a private Codex/operator instruction from a local UTF-8 file",
    )
    operator_add.add_argument("--title", required=True)
    operator_add.add_argument("--file", required=True, help="instruction body file; avoids shell-history exposure")
    operator_add.add_argument("--created-by", default=os.environ.get("OPERATOR_NAME", "owner"))
    operator_add.add_argument("--priority", choices=PRIORITIES, default="normal")
    operator_add.add_argument("--target", choices=TARGETS, default="codex")
    operator_add.add_argument("--message-id")
    operator_add.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    operator_add.set_defaults(func=run_operator_message_add)

    operator_list = subparsers.add_parser(
        "operator-message-list",
        help="list the private manual-review instruction queue",
    )
    operator_list.add_argument("--status", choices=STATUSES)
    operator_list.add_argument("--target", choices=TARGETS)
    operator_list.add_argument("--limit", type=int, default=100)
    operator_list.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    operator_list.set_defaults(func=run_operator_message_list)

    operator_claim = subparsers.add_parser(
        "operator-message-claim",
        help="mark one private instruction as claimed without executing it",
    )
    operator_claim.add_argument("--message-id", required=True)
    operator_claim.add_argument("--agent", default="codex")
    operator_claim.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    operator_claim.set_defaults(func=run_operator_message_claim)

    operator_complete = subparsers.add_parser(
        "operator-message-complete",
        help="record a reviewed instruction result from a local UTF-8 summary file",
    )
    operator_complete.add_argument("--message-id", required=True)
    operator_complete.add_argument("--summary-file", required=True)
    operator_complete.add_argument("--agent", default="codex")
    operator_complete.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    operator_complete.set_defaults(func=run_operator_message_complete)

    worker = subparsers.add_parser("worker", help="run one isolated private research worker service")
    worker.add_argument("--service", choices=sorted(SERVICE_SPECS), required=True)
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--idempotency-key")
    worker.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    worker.add_argument("--kalshi-run-id", default=os.environ.get("KALSHI_RUN_ID", "stage3a_20260703_170707"))
    worker.add_argument("--crypto-run-id", default=os.environ.get("CRYPTO_RUN_ID", "crypto_private_20260704"))
    worker.add_argument("--sports-run-id", default=os.environ.get("SPORTS_RUN_ID", "sports_private_20260704"))
    worker.set_defaults(func=run_worker_command)

    worker_status = subparsers.add_parser("worker-status", help="private worker/database/model status JSON")
    worker_status.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    worker_status.set_defaults(func=run_worker_status)

    pick = subparsers.add_parser("pick", help="generate a strict real-data bet ticket or no-bet decision")
    pick.add_argument("--date", help="date as YYYYMMDD; defaults to local today")
    pick.add_argument("--output", default=str(repo_path("data", "today_paper_view.json")))
    pick.set_defaults(func=run_pick)

    slip = subparsers.add_parser("slip", help="build a fresh mixed-sport combo slip from high-probability legs")
    slip.add_argument("--date", help="date as YYYYMMDD; defaults to local today")
    slip.add_argument("--output", default=str(repo_path("data", "today_paper_view.json")))
    slip.add_argument("--target", type=float, default=0.80, help="minimum individual leg probability")
    slip.add_argument("--min-legs", type=int, default=8)
    slip.add_argument("--max-legs", type=int, default=20)
    slip.add_argument("--min-leg-probability", type=float, default=None, help="override --target for each leg")
    slip.add_argument("--max-leg-probability", type=float, default=0.985)
    slip.add_argument("--public-intel", help="optional JSON file of public bettor/trader signals")
    slip.add_argument("--stake", type=float, default=5.0)
    slip.set_defaults(func=run_slip)

    backtest = subparsers.add_parser("backtest", help="replay historical pre-event prediction snapshots")
    backtest.add_argument("--input", default=str(repo_path("examples", "backtest_sample.json")))
    backtest.add_argument("--output", default=str(repo_path("data", "backtest_report.txt")))
    backtest.set_defaults(func=run_backtest_command)

    paper_run_start = subparsers.add_parser("paper-run-start", help="start a private Stage 3A paper-test run")
    paper_run_start.add_argument("--run-id")
    paper_run_start.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    paper_run_start.add_argument("--lock-path", default=None)
    paper_run_start.set_defaults(func=lambda args: _paper_run_start_with_defaults(args))

    paper_log = subparsers.add_parser("paper-log", help="log private forward-only paper predictions from a payload")
    paper_log.add_argument("--run-id", required=True)
    paper_log.add_argument("--input", default=str(repo_path("data", "today_paper_view.json")))
    paper_log.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    paper_log.add_argument("--date")
    paper_log.add_argument("--report")
    paper_log.set_defaults(func=lambda args: _paper_log_with_defaults(args))

    paper_settle = subparsers.add_parser("paper-settle", help="import private paper settlement outcomes")
    paper_settle.add_argument("--run-id", required=True)
    paper_settle.add_argument("--settlements", required=True)
    paper_settle.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    paper_settle.add_argument("--date")
    paper_settle.add_argument("--report")
    paper_settle.set_defaults(func=lambda args: _paper_settle_with_defaults(args))

    paper_settle_kalshi = subparsers.add_parser("paper-settle-kalshi", help="import official Kalshi settlement data for a paper run")
    paper_settle_kalshi.add_argument("--run-id", required=True)
    paper_settle_kalshi.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    paper_settle_kalshi.add_argument("--date")
    paper_settle_kalshi.add_argument("--report")
    paper_settle_kalshi.set_defaults(func=lambda args: _paper_settle_kalshi_with_defaults(args))

    paper_report = subparsers.add_parser("paper-report", help="render a private Stage 3A daily paper-test report")
    paper_report.add_argument("--run-id", required=True)
    paper_report.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    paper_report.add_argument("--date")
    paper_report.add_argument("--output")
    paper_report.set_defaults(func=lambda args: _paper_report_with_defaults(args))

    paper_stage3b = subparsers.add_parser("paper-stage3b-audit", help="render a private Stage 3B settled performance audit")
    paper_stage3b.add_argument("--run-id", required=True)
    paper_stage3b.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    paper_stage3b.add_argument("--output")
    paper_stage3b.set_defaults(func=lambda args: _paper_stage3b_audit_with_defaults(args))

    kalshi_return_audit = subparsers.add_parser(
        "kalshi-return-audit",
        help="render private Kalshi fee, execution, and correlated-exposure decomposition",
    )
    kalshi_return_audit.add_argument("--run-id", required=True)
    kalshi_return_audit.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    kalshi_return_audit.add_argument("--output")
    kalshi_return_audit.set_defaults(func=lambda args: _kalshi_return_audit_with_defaults(args))

    model_evaluate = subparsers.add_parser(
        "model-evaluate",
        help="evaluate category-specific research probabilities against time-aware baselines",
    )
    model_evaluate.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    model_evaluate.add_argument("--kalshi-run-id", default=os.environ.get("KALSHI_RUN_ID", "stage3a_20260703_170707"))
    model_evaluate.add_argument("--crypto-run-id", default=os.environ.get("CRYPTO_RUN_ID", "crypto_private_20260704"))
    model_evaluate.add_argument("--sports-run-id", default=os.environ.get("SPORTS_RUN_ID", "sports_private_20260704"))
    model_evaluate.add_argument("--output")
    model_evaluate.add_argument("--no-persist", action="store_true")
    model_evaluate.set_defaults(func=lambda args: _model_evaluate_with_defaults(args))

    crypto_collect = subparsers.add_parser("crypto-collect", help="private crypto source collection")
    crypto_collect.add_argument("--output", default=str(repo_path("data", "crypto_runs", "latest_source.json")))
    crypto_collect.set_defaults(func=run_crypto_collect)

    crypto_log = subparsers.add_parser("crypto-log", help="log private crypto research predictions")
    crypto_log.add_argument("--run-id", required=True)
    crypto_log.add_argument("--input", default=str(repo_path("data", "crypto_runs", "latest_source.json")))
    crypto_log.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    crypto_log.add_argument("--report")
    crypto_log.set_defaults(func=lambda args: _crypto_log_with_defaults(args))

    crypto_settle = subparsers.add_parser("crypto-settle", help="settle eligible private crypto predictions")
    crypto_settle.add_argument("--run-id", required=True)
    crypto_settle.add_argument("--input", default=str(repo_path("data", "crypto_runs", "latest_source.json")))
    crypto_settle.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    crypto_settle.add_argument("--report")
    crypto_settle.set_defaults(func=lambda args: _crypto_settle_with_defaults(args))

    crypto_report = subparsers.add_parser("crypto-report", help="render private crypto research report")
    crypto_report.add_argument("--run-id", required=True)
    crypto_report.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    crypto_report.add_argument("--output")
    crypto_report.set_defaults(func=lambda args: _crypto_report_with_defaults(args))

    crypto_stage3b = subparsers.add_parser("crypto-stage3b-audit", help="render private crypto Stage 3B settled performance audit")
    crypto_stage3b.add_argument("--run-id", required=True)
    crypto_stage3b.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    crypto_stage3b.add_argument("--output")
    crypto_stage3b.set_defaults(func=lambda args: _crypto_stage3b_audit_with_defaults(args))

    crypto_stage4 = subparsers.add_parser("crypto-stage4-diagnostic", help="render private crypto Stage 4 controlled diagnostic report")
    crypto_stage4.add_argument("--run-id", required=True)
    crypto_stage4.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    crypto_stage4.add_argument("--output")
    crypto_stage4.set_defaults(func=lambda args: _crypto_stage4_diagnostic_with_defaults(args))

    crypto_cycle_cmd = subparsers.add_parser("crypto-cycle", help="private crypto collect/log/settle/report cycle")
    crypto_cycle_cmd.add_argument("--run-id", required=True)
    crypto_cycle_cmd.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    crypto_cycle_cmd.add_argument("--output")
    crypto_cycle_cmd.set_defaults(func=lambda args: _crypto_cycle_with_defaults(args))

    crypto_export = subparsers.add_parser("crypto-export-features", help="export crypto ML-ready features without leakage")
    crypto_export.add_argument("--run-id", required=True)
    crypto_export.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    crypto_export.add_argument("--output")
    crypto_export.add_argument("--labels-output")
    crypto_export.set_defaults(func=lambda args: _crypto_export_features_with_defaults(args))

    sports_collect = subparsers.add_parser("sports-collect", help="private sports odds source collection")
    sports_collect.add_argument("--sport", default="baseball_mlb")
    sports_collect.add_argument("--output", default=str(repo_path("data", "sports_runs", "latest_odds.json")))
    sports_collect.set_defaults(func=run_sports_collect)

    sports_log = subparsers.add_parser("sports-log", help="log private sports odds research predictions")
    sports_log.add_argument("--run-id", required=True)
    sports_log.add_argument("--input", default=str(repo_path("data", "sports_runs", "latest_odds.json")))
    sports_log.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    sports_log.add_argument("--report")
    sports_log.set_defaults(func=lambda args: _sports_log_with_defaults(args))

    sports_settle = subparsers.add_parser("sports-settle", help="settle private sports predictions from official final scores")
    sports_settle.add_argument("--run-id", required=True)
    sports_settle.add_argument("--finals", required=True)
    sports_settle.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    sports_settle.add_argument("--report")
    sports_settle.set_defaults(func=lambda args: _sports_settle_with_defaults(args))

    sports_report = subparsers.add_parser("sports-report", help="render private sports research report")
    sports_report.add_argument("--run-id", required=True)
    sports_report.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    sports_report.add_argument("--output")
    sports_report.set_defaults(func=lambda args: _sports_report_with_defaults(args))

    sports_record = subparsers.add_parser("sports-record-status", help="append latest sports research metrics to the validation ledger")
    sports_record.add_argument("--run-id", required=True)
    sports_record.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    sports_record.add_argument("--output")
    sports_record.add_argument("--report")
    sports_record.add_argument("--tail", type=int, default=0)
    sports_record.set_defaults(func=lambda args: _sports_record_status_with_defaults(args))

    sports_cycle_cmd = subparsers.add_parser("sports-cycle", help="private sports collect/log/settle/report cycle")
    sports_cycle_cmd.add_argument("--run-id", required=True)
    sports_cycle_cmd.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    sports_cycle_cmd.add_argument("--output")
    sports_cycle_cmd.add_argument("--finals")
    sports_cycle_cmd.set_defaults(func=lambda args: _sports_cycle_with_defaults(args))

    sports_export = subparsers.add_parser("sports-export-features", help="export sports ML-ready features without leakage")
    sports_export.add_argument("--run-id", required=True)
    sports_export.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    sports_export.add_argument("--output")
    sports_export.add_argument("--labels-output")
    sports_export.set_defaults(func=lambda args: _sports_export_features_with_defaults(args))

    connectors_status = subparsers.add_parser("connectors-status", help="private connector configuration/status summary")
    connectors_status.set_defaults(func=run_connectors_status)

    archive_reports = subparsers.add_parser("archive-reports", help="archive private reports to Google Drive when enabled")
    archive_reports.add_argument("paths", nargs="*")
    archive_reports.set_defaults(func=run_archive_reports)

    sync_status_cmd = subparsers.add_parser("sync-status", help="sync private bot status to Airtable when enabled")
    sync_status_cmd.add_argument("--asset-class", choices=["crypto", "sports", "kalshi"], default="crypto")
    sync_status_cmd.add_argument("--run-id")
    sync_status_cmd.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    sync_status_cmd.add_argument("--bot-name")
    sync_status_cmd.add_argument("--stage", default="Stage 3A")
    sync_status_cmd.set_defaults(func=run_sync_status)

    alert_test = subparsers.add_parser("send-alert-test", help="send a private Slack connector test alert when enabled")
    alert_test.add_argument("--bot-name", default="connector-test")
    alert_test.add_argument("--asset-class", default="system")
    alert_test.add_argument("--run-id", default="connector_test")
    alert_test.add_argument("--severity", default="info")
    alert_test.add_argument("--report-path")
    alert_test.set_defaults(func=run_send_alert_test)

    daemon_status = subparsers.add_parser("daemon-status", help="private always-on scheduler/watchdog status")
    daemon_status.add_argument("--dashboard-url", default="http://127.0.0.1:8765")
    daemon_status.add_argument("--crypto-run-id", default="crypto_private_20260704")
    daemon_status.add_argument("--sports-run-id", default="sports_private_20260704")
    daemon_status.add_argument("--kalshi-run-id", default="stage3a_20260703_170707")
    daemon_status.set_defaults(func=run_daemon_status)

    data_quality = subparsers.add_parser("data-quality", help="private source quality and metric contamination audit")
    data_quality.add_argument("--db", default=str(repo_path("data", "evaluation.sqlite")))
    data_quality.add_argument("--dashboard-payload", default=str(repo_path("data", "today_paper_view.json")))
    data_quality.add_argument("--audit-path", default=str(repo_path("data", "refresh_audit.jsonl")))
    data_quality.add_argument("--error-path", default=str(repo_path("data", "error_events.jsonl")))
    data_quality.add_argument("--crypto-run-id", default="crypto_private_20260704")
    data_quality.add_argument("--sports-run-id", default="sports_private_20260704")
    data_quality.add_argument("--kalshi-run-id", default="stage3a_20260703_170707")
    data_quality.add_argument("--output", default=str(default_data_quality_report_path()))
    data_quality.add_argument("--json-output", default=str(default_data_quality_json_path()))
    data_quality.set_defaults(func=run_data_quality)

    company_status = subparsers.add_parser("company-status", help="private bot-company roster and cadence plan")
    company_status.set_defaults(func=run_company_status)

    return parser


def _paper_run_start_with_defaults(args: argparse.Namespace) -> int:
    if args.lock_path is None:
        preview_run = start_paper_test_run(
            create_research_store(args.db),
            run_id=args.run_id,
            lock_path=None,
        )
        args.run_id = preview_run["run_id"]
        args.lock_path = str(default_run_lock_path(args.run_id))
        Path(args.lock_path).parent.mkdir(parents=True, exist_ok=True)
        Path(args.lock_path).write_text(__import__("json").dumps(preview_run, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Started private paper run: {preview_run['run_id']}")
        print(f"Config hash: {preview_run['config_hash']}")
        print(f"Lock file: {args.lock_path}")
        return 0
    return run_paper_run_start(args)


def _paper_log_with_defaults(args: argparse.Namespace) -> int:
    if args.report is None:
        args.report = str(default_daily_report_path(args.run_id))
    return run_paper_log(args)


def _paper_settle_with_defaults(args: argparse.Namespace) -> int:
    if args.report is None:
        args.report = str(default_daily_report_path(args.run_id))
    return run_paper_settle(args)


def _paper_settle_kalshi_with_defaults(args: argparse.Namespace) -> int:
    if args.report is None:
        args.report = str(default_daily_report_path(args.run_id))
    return run_paper_settle_kalshi(args)


def _paper_report_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_daily_report_path(args.run_id))
    return run_paper_report(args)


def _paper_stage3b_audit_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_stage3b_audit_path(args.run_id))
    return run_paper_stage3b_audit(args)


def _kalshi_return_audit_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_kalshi_return_decomposition_path(args.run_id))
    return run_kalshi_return_audit(args)


def _model_evaluate_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_platform_model_audit_path())
    return run_model_evaluate(args)


def _crypto_log_with_defaults(args: argparse.Namespace) -> int:
    if args.report is None:
        args.report = str(default_crypto_daily_report_path(args.run_id))
    return run_crypto_log(args)


def _crypto_settle_with_defaults(args: argparse.Namespace) -> int:
    if args.report is None:
        args.report = str(default_crypto_daily_report_path(args.run_id))
    return run_crypto_settle(args)


def _crypto_report_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_crypto_all_report_path(args.run_id))
    return run_crypto_report(args)


def _crypto_stage3b_audit_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_crypto_stage3b_audit_path(args.run_id))
    return run_crypto_stage3b_audit(args)


def _crypto_stage4_diagnostic_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_crypto_stage4_diagnostic_path(args.run_id))
    return run_crypto_stage4_diagnostic(args)


def _crypto_cycle_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_crypto_payload_path(args.run_id))
    return run_crypto_cycle(args)


def _crypto_export_features_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_crypto_features_path(args.run_id))
    if args.labels_output is None:
        args.labels_output = str(default_crypto_labels_path(args.run_id))
    return run_crypto_export_features(args)


def _sports_log_with_defaults(args: argparse.Namespace) -> int:
    if args.report is None:
        args.report = str(default_sports_daily_report_path(args.run_id))
    return run_sports_log(args)


def _sports_settle_with_defaults(args: argparse.Namespace) -> int:
    if args.report is None:
        args.report = str(default_sports_daily_report_path(args.run_id))
    return run_sports_settle(args)


def _sports_report_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_sports_all_report_path(args.run_id))
    return run_sports_report(args)


def _sports_record_status_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_sports_validation_ledger_path(args.run_id))
    return run_sports_record_status(args)


def _sports_cycle_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_sports_payload_path(args.run_id))
    return run_sports_cycle(args)


def _sports_export_features_with_defaults(args: argparse.Namespace) -> int:
    if args.output is None:
        args.output = str(default_sports_features_path(args.run_id))
    if args.labels_output is None:
        args.labels_output = str(default_sports_labels_path(args.run_id))
    return run_sports_export_features(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
