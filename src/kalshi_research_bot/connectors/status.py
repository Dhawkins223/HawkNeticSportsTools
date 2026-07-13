from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .airtable_status import airtable_configured
from .firecrawl import is_firecrawl_configured
from .google_drive_archive import google_drive_enabled
from .slack_alerts import slack_enabled


def build_connectors_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = os.environ if env is None else env
    firecrawl_configured = is_firecrawl_configured(values)
    drive_enabled = google_drive_enabled(values)
    airtable_ready = airtable_configured(values)
    slack_ready = slack_enabled(values)
    sports_mode = values.get("SPORTS_SOURCE_MODE") or "scraper"
    sports_scraper_enabled = str(values.get("SPORTS_SCRAPER_ENABLED", "true")).lower() in {"1", "true", "yes", "on"}
    odds_api_configured = bool(values.get("THE_ODDS_API_KEY") or values.get("ODDS_API_KEY"))
    firecrawl_required = sports_mode in {"scraper", "scraper_first"} and sports_scraper_enabled and not odds_api_configured
    states = {
        "firecrawl": _configured_state(
            configured=firecrawl_configured,
            enabled=True,
            required=firecrawl_required,
            purpose="public scraper-backed sports/source collection",
        ),
        "google_drive": _configured_state(
            configured=drive_enabled,
            enabled=drive_enabled,
            required=False,
            purpose="optional report archive",
        ),
        "airtable": _configured_state(
            configured=airtable_ready,
            enabled=str(values.get("AIRTABLE_ENABLED", "false")).lower() in {"1", "true", "yes", "on"},
            required=False,
            purpose="optional operational status mirror",
        ),
        "slack": _configured_state(
            configured=slack_ready,
            enabled=str(values.get("SLACK_ALERTS_ENABLED", "false")).lower() in {"1", "true", "yes", "on"},
            required=False,
            purpose="optional actionable alerts",
        ),
    }
    return {
        "firecrawl": "configured" if firecrawl_configured else "unconfigured",
        "google_drive": "configured" if drive_enabled else "unconfigured",
        "airtable": "configured" if airtable_ready else "unconfigured",
        "slack": "configured" if slack_ready else "unconfigured",
        "sports_source_mode": sports_mode,
        "sports_scraper_enabled": sports_scraper_enabled,
        "states": states,
        "last_archive_status": "unknown",
        "last_alert_status": "unknown",
        "disabled_connectors": {
            "vercel": "disabled",
            "posthog": "disabled",
            "stripe": "disabled",
            "kit": "later_only",
            "clay": "later_only",
        },
        "missing_env_vars": _missing_env_vars(values),
    }


def _configured_state(*, configured: bool, enabled: bool, required: bool, purpose: str) -> dict[str, Any]:
    if configured:
        return {
            "state": "configured_degraded",
            "reason": "configured_not_health_checked",
            "purpose": purpose,
            "required": required,
        }
    if required:
        return {
            "state": "missing_required",
            "reason": "required_configuration_missing",
            "purpose": purpose,
            "required": True,
        }
    return {
        "state": "unconfigured_optional",
        "reason": "connector_not_enabled" if not enabled else "configuration_incomplete",
        "purpose": purpose,
        "required": False,
    }


def render_connectors_status(status: Mapping[str, Any]) -> str:
    lines = [
        "Connector Status",
        f"Firecrawl: {status['firecrawl']}",
        f"Google Drive: {status['google_drive']}",
        f"Airtable: {status['airtable']}",
        f"Slack: {status['slack']}",
        f"Sports source mode: {status['sports_source_mode']}",
        f"Sports scraper enabled: {status['sports_scraper_enabled']}",
        f"Last archive status: {status.get('last_archive_status', 'unknown')}",
        f"Last alert status: {status.get('last_alert_status', 'unknown')}",
        f"Disabled connectors: {status.get('disabled_connectors', {})}",
        f"Missing env vars: {status.get('missing_env_vars', [])}",
    ]
    return "\n".join(lines)


def connector_status_report_lines(status: Mapping[str, Any]) -> list[str]:
    return [
        "Connector status:",
        f"- Firecrawl: {status.get('firecrawl', 'unconfigured')}",
        f"- Google Drive: {status.get('google_drive', 'unconfigured')}",
        f"- Airtable: {status.get('airtable', 'unconfigured')}",
        f"- Slack: {status.get('slack', 'unconfigured')}",
        f"- Sports source mode: {status.get('sports_source_mode', 'scraper')}",
        f"- Disabled public/product connectors: {status.get('disabled_connectors', {})}",
    ]


def _missing_env_vars(values: Mapping[str, str]) -> list[str]:
    missing = []
    if not values.get("FIRECRAWL_API_KEY"):
        missing.append("FIRECRAWL_API_KEY")
    if google_drive_enabled(values) and not values.get("GOOGLE_DRIVE_REPORT_FOLDER"):
        missing.append("GOOGLE_DRIVE_REPORT_FOLDER")
    if str(values.get("AIRTABLE_ENABLED", "false")).lower() in {"1", "true", "yes", "on"}:
        for name in ("AIRTABLE_API_KEY", "AIRTABLE_BASE_ID"):
            if not values.get(name):
                missing.append(name)
    if str(values.get("SLACK_ALERTS_ENABLED", "false")).lower() in {"1", "true", "yes", "on"} and not values.get("SLACK_WEBHOOK_URL"):
        missing.append("SLACK_WEBHOOK_URL")
    return missing
