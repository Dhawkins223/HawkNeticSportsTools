from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


SLIP_SOURCES = {
    "primary": ("custom_slip", "80% Slip"),
    "leverage": ("leverage_slip", "75% Leverage Slip"),
    "all_day": ("all_day_slip", "All-Day 75-85% Slip"),
    "research_edge": ("research_edge_slip", "Research Edge Slip"),
}


def build_review_packet(payload: dict[str, Any], slip_key: str = "primary") -> dict[str, Any]:
    if slip_key not in SLIP_SOURCES:
        raise ValueError(f"unknown_slip_key:{slip_key}")
    payload_key, label = SLIP_SOURCES[slip_key]
    slip = payload.get(payload_key) or {}
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    legs = [_packet_leg(index, leg) for index, leg in enumerate(slip.get("legs") or [], start=1)]
    ready = slip.get("action") == "BUILD_SLIP" and bool(legs)
    summary = {
        "action": slip.get("action", "UNKNOWN"),
        "leg_count": int(slip.get("leg_count") or len(legs)),
        "sports": list(slip.get("sports") or []),
        "estimated_combo_price_cents": slip.get("estimated_combo_price_cents"),
        "stake_dollars": slip.get("stake_dollars"),
        "estimated_payout_if_right": slip.get("estimated_payout_if_right"),
        "raw_probability": slip.get("raw_probability"),
        "adjusted_probability": slip.get("adjusted_probability"),
        "correlation_penalty": slip.get("correlation_penalty"),
        "overlap_safe": slip.get("overlap_safe"),
        "overlap_policy": slip.get("overlap_policy"),
        "reason": slip.get("reason"),
    }
    packet = {
        "packet_type": "kalshi_manual_review_packet",
        "slip_key": slip_key,
        "slip_label": label,
        "ready": ready,
        "created_at": created_at,
        "source_date": payload.get("date"),
        "source_generated_at": payload.get("generated_at"),
        "source_note": payload.get("generated_at_note"),
        "safety": {
            "manual_review_only": True,
            "account_write_enabled": False,
            "auto_trade_enabled": False,
            "auto_bet_enabled": False,
            "order_submission_enabled": False,
            "requires_human_review_before_any_bet": True,
            "note": "Local review packet only. It does not create, stage, upload, or submit any Kalshi order.",
        },
        "summary": summary,
        "legs": legs,
        "review_checklist": [
            "Confirm each market ticker in Kalshi before doing anything.",
            "Confirm side, live price, close time, and market status.",
            "Skip the slip if any leg changed materially, closed, or cannot be found.",
            "Do not treat this packet as proof of edge or profitability.",
        ],
    }
    packet["packet_hash"] = _packet_hash(packet)
    packet["copy_blocks"] = _copy_blocks(packet)
    return packet


def build_all_review_packets(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_type": "kalshi_manual_review_packet_bundle",
        "source_date": payload.get("date"),
        "source_generated_at": payload.get("generated_at"),
        "safety": {
            "manual_review_only": True,
            "account_write_enabled": False,
            "auto_trade_enabled": False,
            "auto_bet_enabled": False,
            "order_submission_enabled": False,
        },
        "packets": {slip_key: build_review_packet(payload, slip_key) for slip_key in SLIP_SOURCES},
    }


def render_review_packet_text(packet: dict[str, Any]) -> str:
    summary = packet.get("summary") or {}
    safety = packet.get("safety") or {}
    lines = [
        f"MANUAL REVIEW PACKET - {packet.get('slip_label', 'Slip')}",
        "NOT AN ORDER. No account upload. No auto-bet. Review manually before any action.",
        f"Source generated: {packet.get('source_generated_at') or 'unknown'}",
        f"Packet hash: {packet.get('packet_hash') or 'pending'}",
        "",
        "SUMMARY",
        f"- Ready: {packet.get('ready')}",
        f"- Legs: {summary.get('leg_count', 0)}",
        f"- Estimated combo price hint: {_format_cents(summary.get('estimated_combo_price_cents'))}",
        f"- Estimated payout if every leg hits: {_format_dollars(summary.get('estimated_payout_if_right'))}",
        f"- Adjusted combo probability: {_format_percent(summary.get('adjusted_probability'))}",
        f"- Overlap safe: {summary.get('overlap_safe')}",
        f"- Manual review only: {safety.get('manual_review_only')}",
        "",
        "FAST ENTRY LINES",
    ]
    for leg in packet.get("legs") or []:
        lines.append(
            f"{leg.get('position')}. {leg.get('market_ticker')} | {leg.get('side')} | "
            f"{leg.get('selection')} | ask {_format_cents(leg.get('ask_cents'))} | {leg.get('display_event')}"
        )
    lines.extend(["", "TICKERS + SIDES", packet.get("copy_blocks", {}).get("ticker_stack", ""), "", "CHECKLIST"])
    for item in packet.get("review_checklist") or []:
        lines.append(f"[ ] {item}")
    return "\n".join(lines).strip() + "\n"


def safe_review_packet_filename(packet: dict[str, Any], extension: str) -> str:
    source_date = "".join(ch for ch in str(packet.get("source_date") or "today") if ch.isalnum() or ch in {"-", "_"})
    slip_key = "".join(ch for ch in str(packet.get("slip_key") or "slip") if ch.isalnum() or ch in {"-", "_"})
    clean_extension = extension.lstrip(".") or "txt"
    return f"{source_date}_{slip_key}_manual_review_packet.{clean_extension}"


def _packet_leg(position: int, leg: dict[str, Any]) -> dict[str, Any]:
    side = str(leg.get("side") or "").upper()
    selection = str(leg.get("subtitle") or leg.get("title") or leg.get("market_ticker") or "")
    return {
        "position": position,
        "sport": leg.get("sport"),
        "market_ticker": leg.get("market_ticker"),
        "event_ticker": leg.get("event_ticker"),
        "display_event": leg.get("display_event") or leg.get("event_ticker"),
        "side": side,
        "selection": selection,
        "probability": leg.get("probability"),
        "required_probability": leg.get("required_probability"),
        "bid_cents": leg.get("bid_cents"),
        "ask_cents": leg.get("ask_cents"),
        "status": leg.get("status"),
        "source": "local_public_kalshi_market_data",
    }


def _copy_blocks(packet: dict[str, Any]) -> dict[str, str]:
    fast_lines = []
    ticker_lines = []
    for leg in packet.get("legs") or []:
        ticker = leg.get("market_ticker") or ""
        side = leg.get("side") or ""
        fast_lines.append(
            f"{leg.get('position')}. {ticker} | {side} | {_format_cents(leg.get('ask_cents'))} | "
            f"{leg.get('selection')} | {leg.get('display_event')}"
        )
        ticker_lines.append(f"{ticker}\t{side}")
    return {
        "fast_entry": "\n".join(fast_lines),
        "ticker_stack": "\n".join(ticker_lines),
        "review_packet": render_review_packet_text({**packet, "copy_blocks": {"ticker_stack": "\n".join(ticker_lines)}}),
    }


def _packet_hash(packet: dict[str, Any]) -> str:
    stable = {
        "packet_type": packet.get("packet_type"),
        "slip_key": packet.get("slip_key"),
        "source_date": packet.get("source_date"),
        "source_generated_at": packet.get("source_generated_at"),
        "summary": packet.get("summary"),
        "legs": packet.get("legs"),
        "safety": packet.get("safety"),
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _format_cents(value: Any) -> str:
    try:
        return f"{float(value):.2f}c"
    except (TypeError, ValueError):
        return "n/a"


def _format_dollars(value: Any) -> str:
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"
