from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agents import DeepResearchBot, PublicIntelBot
from .connectors.http import HttpClient
from .evaluation.quality import confidence_guardrail


ESPN_SCOREBOARDS = {
    "MLB": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={yyyymmdd}",
    "WNBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={yyyymmdd}",
}

KALSHI_PUBLIC_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
SPORTS_COMBO_WORDS = [
    "over",
    "under",
    "runs",
    "points",
    "goals",
    "touchdowns",
    "score",
    "wins by",
]
DEFAULT_MIN_LEG_PROBABILITY = 0.80
DEFAULT_LEVERAGE_MIN_LEG_PROBABILITY = 0.75
DEFAULT_ALL_DAY_MIN_LEG_PROBABILITY = 0.75
DEFAULT_ALL_DAY_MAX_LEG_PROBABILITY = 0.85
DEFAULT_RESEARCH_EDGE_MIN_PROBABILITY = 0.70
MONTH_NUMBERS = {
    "JAN": "01",
    "FEB": "02",
    "MAR": "03",
    "APR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AUG": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DEC": "12",
}


def today_key(day: date | None = None) -> str:
    return (day or date.today()).strftime("%Y%m%d")


def date_key_from_ticker(*tickers: str) -> str | None:
    for ticker in tickers:
        match = re.search(r"-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})", (ticker or "").upper())
        if match:
            year, month_name, day = match.groups()
            return f"20{year}{MONTH_NUMBERS[month_name]}{day}"
    return None


def date_key_from_iso(value: str | None, timezone: str = "America/New_York") -> str | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone_utc())
    return timestamp.astimezone(local_timezone(timezone, timestamp)).strftime("%Y%m%d")


def timezone_utc() -> timezone:
    return timezone.utc


def local_timezone(timezone_name: str, timestamp: datetime) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name != "America/New_York":
            return timezone.utc
        month = timestamp.month
        day = timestamp.day
        is_dst = 4 <= month <= 10 or (month == 3 and day >= 8) or (month == 11 and day <= 7)
        return timezone(timedelta(hours=-4 if is_dst else -5))


def market_completion_date_keys(market: dict[str, Any]) -> set[str]:
    keys = {
        date_key_from_iso(str(market.get(field) or ""))
        for field in ["close_time", "expected_expiration_time", "expiration_time", "latest_expiration_time"]
    }
    keys.add(date_key_from_ticker(market.get("ticker", ""), market.get("event_ticker", "")))
    return {key for key in keys if key}


def overlap_key_from_ticker(ticker: str, sport: str = "") -> str | None:
    ticker = (ticker or "").upper()
    match = re.search(
        r"-(\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\d{0,4}[A-Z]+)",
        ticker,
    )
    if match:
        return f"{sport}:{match.group(1)}".lower()
    return None


def normalize_matchup_text(value: str) -> str:
    text = (value or "").lower()
    for prefix in [
        "1st half of the ",
        "1st half of ",
        "first half of the ",
        "first half of ",
        "2nd half of the ",
        "2nd half of ",
        "second half of the ",
        "second half of ",
    ]:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    for separator in [
        " soccer tie ",
        " professional ",
        " total ",
        ": round",
        " in the ",
        " after ",
        "?",
    ]:
        if separator in text:
            text = text.split(separator, 1)[0]
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def overlap_key_for_leg(leg: dict[str, Any]) -> str:
    sport = leg.get("sport") or infer_sport(leg)
    ticker_key = overlap_key_from_ticker(leg.get("market_ticker", ""), sport)
    if ticker_key:
        return ticker_key
    for field in ["display_event", "rules", "title", "subtitle", "event_ticker"]:
        normalized = normalize_matchup_text(str(leg.get(field, "")))
        if " vs " in f" {normalized} " or " at " in f" {normalized} ":
            return f"{sport}:{normalized}".lower()
    return f"{sport}:{leg.get('event_ticker') or leg.get('market_ticker')}".lower()


def parse_espn_event(league: str, event: dict[str, Any]) -> dict[str, Any]:
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    home = next((item for item in competitors if item.get("homeAway") == "home"), {})
    away = next((item for item in competitors if item.get("homeAway") == "away"), {})
    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    return {
        "league": league,
        "event_id": event.get("id", ""),
        "name": event.get("name", ""),
        "short_name": event.get("shortName", ""),
        "start_time": event.get("date", ""),
        "status": ((event.get("status") or {}).get("type") or {}).get("description", ""),
        "home_team": home_team.get("displayName") or home_team.get("name", ""),
        "away_team": away_team.get("displayName") or away_team.get("name", ""),
        "home_abbrev": home_team.get("abbreviation", ""),
        "away_abbrev": away_team.get("abbreviation", ""),
        "venue": (competition.get("venue") or {}).get("fullName", ""),
    }


def fetch_espn_schedule(http: HttpClient, yyyymmdd: str) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for league, url_template in ESPN_SCOREBOARDS.items():
        payload = http.get_text(url_template.format(yyyymmdd=yyyymmdd)).json()
        games.extend(parse_espn_event(league, event) for event in payload.get("events", []))
    return games


def cents_from_dollars(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return round(float(value) * 100.0, 2)
    except ValueError:
        return None


def probability_from_cents(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, value / 100.0))


def midpoint_cents(bid: float | None, ask: float | None) -> float | None:
    if bid is not None and ask is not None and ask > 0:
        return round((bid + ask) / 2.0, 2)
    if ask is not None and ask > 0:
        return ask
    if bid is not None and bid > 0:
        return bid
    return None


def split_market_title(title: str) -> list[str]:
    return [part.strip() for part in title.split(",") if part.strip()]


def display_event_from_rules(rules: str) -> str:
    if " wins the " in rules:
        tail = rules.split(" wins the ", 1)[1]
        if " professional" in tail:
            return " ".join(tail.split(" professional", 1)[0].split())
    markers = [
        " in the ",
        " by ",
    ]
    for marker in markers:
        if marker in rules:
            tail = rules.split(marker, 1)[1]
            for suffix in [
                " professional",
                " originally",
                " after ",
                " at ",
                ", then",
            ]:
                if suffix in tail:
                    tail = tail.split(suffix, 1)[0]
            if " vs " in tail or " at " in tail:
                return " ".join(tail.split())
    return ""


def side_quote_from_market(market: dict[str, Any], side: str) -> dict[str, Any]:
    side_key = side.lower()
    if side_key not in {"yes", "no"}:
        side_key = "yes"
    bid = cents_from_dollars(market.get(f"{side_key}_bid_dollars"))
    ask = cents_from_dollars(market.get(f"{side_key}_ask_dollars"))
    midpoint = midpoint_cents(bid, ask)
    return {
        "side": side_key,
        "bid_cents": bid,
        "ask_cents": ask,
        "midpoint_cents": midpoint,
        "market_implied_probability": probability_from_cents(midpoint),
    }


def fetch_market_by_ticker(http: HttpClient, ticker: str) -> dict[str, Any] | None:
    url = f"{KALSHI_PUBLIC_BASE_URL}/markets/{ticker}"
    try:
        response = http.get_text(url)
        market = response.json().get("market")
        if market:
            market["_api_fetched_at"] = response.fetched_at
            market["_source_url"] = response.url
        return market
    except Exception:
        return None


def repeated_event_penalty(event_tickers: list[str], per_extra_leg: float = 0.03) -> float:
    counts: dict[str, int] = {}
    for ticker in event_tickers:
        if ticker:
            counts[ticker] = counts.get(ticker, 0) + 1
    extra = sum(max(0, count - 1) for count in counts.values())
    return min(0.35, extra * per_extra_leg)


def product_probability(values: list[float]) -> float | None:
    if not values:
        return None
    probability = 1.0
    for value in values:
        probability *= value
    return max(0.0, min(1.0, probability))


def infer_sport(leg: dict[str, Any]) -> str:
    ticker = (leg.get("market_ticker") or "").upper()
    text = f"{leg.get('title', '')} {leg.get('subtitle', '')} {leg.get('rules', '')} {ticker}".lower()
    if "KXMLB" in ticker or "runs scored" in text:
        return "Pro Baseball"
    if "KXWNBA" in ticker or "points scored" in text or "women's" in text:
        return "Pro Basketball (W)"
    if "KXWC" in ticker or "reg time" in text or "goals scored" in text or "advances" in text:
        return "World Soccer Cup"
    if "tennis" in text or "wimbledon" in text or "KXATP" in ticker or "KXWTA" in ticker or "MATCH" in ticker or "CHALLENGER" in ticker:
        return "Tennis"
    return "Sports"


def infer_market_category(market: dict[str, Any]) -> str:
    ticker = (market.get("ticker") or market.get("event_ticker") or "").upper()
    text = " ".join(
        str(market.get(field, ""))
        for field in ["ticker", "event_ticker", "title", "category", "category_slug", "rules_primary"]
    ).lower()
    raw_category = str(market.get("category") or market.get("category_slug") or "").strip()
    if any(word in text for word in ["bitcoin", "btc", "ethereum", "eth", "crypto", "xrp", "solana", "doge", "litecoin", "bnb", "near"]) or ticker.startswith(("KXBTC", "KXETH", "KXCRYPTO", "KXXRP", "KXSOL", "KXDOGE", "KXBNB", "KXNEAR")):
        return "Crypto"
    if any(word in text for word in ["esports", "gaming", "map 1", "map 2", "map 3"]):
        return "Esports"
    if ticker.startswith(("KXMLB", "KXNBA", "KXWNBA", "KXNFL", "KXWC", "KXATP", "KXWTA", "KXITF", "KXPGA", "KXGOLF")):
        return "Sports"
    if any(word in text for word in ["temperature", "rain", "weather", "hurricane", "snow"]):
        return "Weather"
    if any(word in text for word in ["election", "president", "senate", "congress", "mayor", "trump", "donald"]):
        return "Politics"
    if any(word in text for word in ["s&p", "nasdaq", "dow", "stock", "treasury", "fed", "rate cut"]):
        return "Markets"
    if any(word in text for word in ["fox", "tv", "stream", "podcast", "movie", "song", "album", "corden"]):
        return "Media"
    if raw_category:
        normalized = raw_category.replace("_", " ").replace("-", " ").title()
        if normalized.lower() not in {"Other", "All"}:
            return normalized
    return "Kalshi"


def is_supported_slip_leg(leg: dict[str, Any]) -> bool:
    subtitle = (leg.get("subtitle") or "").lower()
    title = (leg.get("title") or "").lower()
    ticker = (leg.get("market_ticker") or "").upper()
    text = f"{subtitle} {title}"
    if "KXMLBHR" in ticker:
        return False
    if ":" in subtitle and not subtitle.startswith(("reg time:", "goal diff reg time:")) and "over" not in subtitle:
        return False
    return any(
        phrase in text
        for phrase in [
            "over",
            "under",
            "points scored",
            "runs scored",
            "goals scored",
            "advances",
            "wins by",
        ]
    ) or "MATCH" in ticker


def total_line_from_text(value: str) -> float | None:
    match = re.search(r"over\s+(\d+(?:\.\d+)?)", (value or "").lower())
    if not match:
        return None
    return float(match.group(1))


def is_colorado_mlb_game(leg: dict[str, Any]) -> bool:
    text = " ".join(
        str(leg.get(field, ""))
        for field in ["market_ticker", "event_ticker", "display_event", "title", "subtitle", "rules"]
    ).lower()
    return "colorado" in text or "miacol" in text or "col" in (leg.get("market_ticker") or "").lower()


def is_mlb_total_runs_leg(leg: dict[str, Any]) -> bool:
    sport = leg.get("sport") or infer_sport(leg)
    subtitle = (leg.get("subtitle") or leg.get("title") or "").lower()
    return sport == "Pro Baseball" and "runs scored" in subtitle and total_line_from_text(subtitle) is not None


def is_high_scoring_total_environment(leg: dict[str, Any]) -> bool:
    if not is_mlb_total_runs_leg(leg):
        return False
    line = total_line_from_text(leg.get("subtitle") or leg.get("title") or "")
    return bool(line is not None and line >= 10.5) or is_colorado_mlb_game(leg)


def leg_risk_flags(leg: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    sport = leg.get("sport") or infer_sport(leg)
    subtitle = leg.get("subtitle") or leg.get("title") or ""
    line = total_line_from_text(subtitle)
    side = (leg.get("side") or "").lower()
    if sport == "Pro Baseball" and line is not None and "runs scored" in subtitle.lower():
        if side == "no" and is_high_scoring_total_environment(leg):
            flags.append("high_scoring_mlb_total_under_blocked")
        if side == "no" and line >= 14.5:
            flags.append("extreme_mlb_total_under_tail_risk")
        if side == "no" and line >= 12.5 and is_colorado_mlb_game(leg):
            flags.append("coors_or_colorado_total_under_tail_risk")
    return flags


def leg_warning_flags(leg: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if is_mlb_total_runs_leg(leg) and is_colorado_mlb_game(leg):
        flags.append("colorado_run_environment_review")
    if is_high_scoring_total_environment(leg):
        flags.append("high_scoring_total_environment")
    return flags


def required_leg_probability(leg: dict[str, Any], base_probability: float) -> float:
    if not is_mlb_total_runs_leg(leg):
        return base_probability
    side = (leg.get("side") or "").lower()
    if side != "yes":
        return base_probability
    line = total_line_from_text(leg.get("subtitle") or leg.get("title") or "") or 0.0
    if is_colorado_mlb_game(leg) or line >= 12.5:
        return max(base_probability, 0.90)
    if is_high_scoring_total_environment(leg):
        return max(base_probability, 0.85)
    return base_probability


def numeric_text(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in {None, ""} else default)
    except (TypeError, ValueError):
        return default


def leg_spread_cents(leg: dict[str, Any]) -> float:
    bid = leg.get("bid_cents")
    ask = leg.get("ask_cents")
    if bid is None or ask is None:
        return 100.0
    return max(0.0, float(ask) - float(bid))


def exact_bet_score(leg: dict[str, Any]) -> float:
    probability_score = float(leg.get("probability") or leg.get("market_implied_probability") or 0) * 100.0
    spread_penalty = leg_spread_cents(leg) * 0.35
    liquidity = numeric_text(leg.get("open_interest")) + numeric_text(leg.get("volume_24h"))
    liquidity_bonus = min(8.0, liquidity / 250.0)
    subtitle = (leg.get("subtitle") or "").lower()
    market_penalty = 1.5 if "wins by" in subtitle else 0.0
    return round(max(0.0, min(100.0, probability_score - spread_penalty + liquidity_bonus - market_penalty)), 2)


def build_leg_universe(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for market in markets:
        for leg in market.get("leg_details") or []:
            probability = leg.get("market_implied_probability")
            if probability is None or not (0 < probability < 1):
                continue
            if leg.get("status") != "active":
                continue
            key = (leg.get("market_ticker", ""), leg.get("side", "yes"))
            candidate = {
                **leg,
                "sport": infer_sport(leg),
                "probability": probability,
                "spread_cents": leg_spread_cents(leg),
                "open_interest_value": numeric_text(leg.get("open_interest")),
                "volume_24h_value": numeric_text(leg.get("volume_24h")),
                "event_date": date_key_from_ticker(leg.get("market_ticker", ""), leg.get("event_ticker", "")),
            }
            candidate["overlap_key"] = overlap_key_for_leg(candidate)
            candidate["risk_flags"] = leg_risk_flags(candidate)
            candidate["warning_flags"] = leg_warning_flags(candidate)
            candidate["required_probability"] = required_leg_probability(candidate, DEFAULT_MIN_LEG_PROBABILITY)
            candidate["exact_bet_score"] = exact_bet_score(candidate)
            existing = unique.get(key)
            if existing is None or candidate["open_interest_value"] > existing["open_interest_value"]:
                unique[key] = candidate
    return list(unique.values())


def slip_adjusted_probability(legs: list[dict[str, Any]]) -> tuple[float, float, float]:
    probabilities = [leg["probability"] for leg in legs]
    raw = product_probability(probabilities) or 0.0
    penalty = repeated_event_penalty([leg.get("event_ticker", "") for leg in legs])
    return raw, max(0.0, raw * (1.0 - penalty)), penalty


def slip_summary(legs: list[dict[str, Any]], min_leg_probability: float, stake_dollars: float) -> dict[str, Any]:
    raw, adjusted, penalty = slip_adjusted_probability(legs)
    estimated_cost_cents = round(adjusted * 100.0, 2)
    estimated_payout = round(stake_dollars / adjusted, 2) if adjusted > 0 else 0.0
    leg_guardrails = [
        confidence_guardrail(
            probability=float(leg.get("probability") or 0),
            evidence_count=int(leg.get("evidence_count") or 0),
            source_backed=leg.get("research_mode") == "source_backed",
            margin_of_error=leg.get("margin_of_error"),
            spread_cents=leg.get("spread_cents"),
        )
        for leg in legs
    ]
    high_confidence_allowed = bool(leg_guardrails) and all(item["high_confidence_allowed"] for item in leg_guardrails)
    return {
        "action": "BUILD_SLIP",
        "min_leg_probability": min_leg_probability,
        "raw_probability": round(raw, 6),
        "adjusted_probability": round(adjusted, 6),
        "correlation_penalty": round(penalty, 6),
        "estimated_combo_price_cents": estimated_cost_cents,
        "stake_dollars": stake_dollars,
        "estimated_payout_if_right": estimated_payout,
        "estimated_profit_if_right": round(estimated_payout - stake_dollars, 2),
        "leg_count": len(legs),
        "sports": sorted({leg["sport"] for leg in legs}),
        "unique_matchup_count": len({leg.get("overlap_key") for leg in legs}),
        "overlap_safe": len({leg.get("overlap_key") for leg in legs}) == len(legs),
        "overlap_policy": "one normalized matchup per combo slip",
        "confidence_label": "high_confidence" if high_confidence_allowed else "price_implied",
        "high_confidence_allowed": high_confidence_allowed,
        "confidence_guardrail_reasons": sorted({reason for item in leg_guardrails for reason in item.get("reasons", [])}),
        "legs": legs,
        "note": "Built from live Kalshi underlying leg bid/ask probabilities. Each leg clears the minimum individual probability filter, and the selector blocks overlapping same-game legs.",
    }


def build_custom_slip(
    markets: list[dict[str, Any]],
    target_probability: float = DEFAULT_MIN_LEG_PROBABILITY,
    min_leg_probability: float | None = None,
    max_leg_probability: float = 0.985,
    min_legs: int = 3,
    max_legs: int = 20,
    stake_dollars: float = 5.0,
    yyyymmdd: str | None = None,
    intel_by_overlap_key: dict[str, float] | None = None,
) -> dict[str, Any]:
    min_leg_probability = target_probability if min_leg_probability is None else min_leg_probability
    intel_by_overlap_key = intel_by_overlap_key or {}
    universe = [
        leg
        for leg in build_leg_universe(markets)
        if required_leg_probability(leg, min_leg_probability) <= leg["probability"] <= max_leg_probability
        and (yyyymmdd is None or leg.get("event_date") in {None, yyyymmdd})
        and leg["spread_cents"] <= 25
        and is_supported_slip_leg(leg)
        and not leg.get("risk_flags")
    ]
    for leg in universe:
        leg["required_probability"] = required_leg_probability(leg, min_leg_probability)
    for leg in universe:
        public_intel_score = round(float(intel_by_overlap_key.get(leg.get("overlap_key", ""), 0.0)), 2)
        leg["public_intel_score"] = public_intel_score
        leg["exact_bet_score"] = round(min(100.0, float(leg.get("exact_bet_score") or 0) + public_intel_score), 2)
    if len(universe) < min_legs:
        return {
            "action": "NO_SLIP",
            "reason": "Not enough real priced legs passed the safety filters.",
            "min_leg_probability": min_leg_probability,
            "eligible_leg_count": len(universe),
            "legs": [],
        }

    ranked = sorted(
        universe,
        key=lambda leg: (
            abs(leg["probability"] - min_leg_probability),
            -leg["exact_bet_score"],
            leg["spread_cents"],
            -leg["open_interest_value"],
            -leg["volume_24h_value"],
        ),
    )
    selected: list[dict[str, Any]] = []
    selected_overlap_keys: set[str] = set()
    sport_counts: dict[str, int] = {}
    skipped_overlap_count = 0
    max_per_sport = max(3, max_legs // 2)
    for leg in ranked:
        overlap_key = leg.get("overlap_key") or overlap_key_for_leg(leg)
        if overlap_key in selected_overlap_keys:
            skipped_overlap_count += 1
            continue
        if sport_counts.get(leg["sport"], 0) >= max_per_sport:
            continue
        selected.append(leg)
        selected_overlap_keys.add(overlap_key)
        sport_counts[leg["sport"]] = sport_counts.get(leg["sport"], 0) + 1
        if len(selected) == max_legs:
            break

    if len(selected) < min_legs or len({leg["sport"] for leg in selected}) < 2:
        return {
            "action": "NO_SLIP",
            "reason": "Could not build a multi-sport slip from the current real-data filters.",
            "min_leg_probability": min_leg_probability,
            "eligible_leg_count": len(universe),
            "legs": [],
        }

    best = slip_summary(selected, min_leg_probability, stake_dollars)
    best["eligible_leg_count"] = len(universe)
    best["skipped_overlap_count"] = skipped_overlap_count
    return best


def fetch_kalshi_same_day_markets(
    http: HttpClient,
    yyyymmdd: str,
    limit: int = 500,
    max_pages: int = 16,
) -> list[dict[str, Any]]:
    raw_markets: dict[str, dict[str, Any]] = {}
    cursor = ""
    for _ in range(max_pages):
        request = {"limit": limit, "status": "open", "mve_filter": "exclude"}
        if cursor:
            request["cursor"] = cursor
        url = f"{KALSHI_PUBLIC_BASE_URL}/markets?{urlencode(request)}"
        response = http.get_text(url)
        payload = response.json()
        for market in payload.get("markets", []):
            ticker = market.get("ticker", "")
            if ticker and yyyymmdd in market_completion_date_keys(market):
                market["_api_fetched_at"] = response.fetched_at
                market["_source_url"] = response.url
                raw_markets[ticker] = market
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    return list(raw_markets.values())


def all_day_overlap_key(leg: dict[str, Any]) -> str:
    ticker_key = overlap_key_from_ticker(leg.get("market_ticker", ""), "all")
    if ticker_key:
        return ticker_key
    event_ticker = leg.get("event_ticker") or ""
    if event_ticker:
        return f"all:{event_ticker}".lower()
    title_key = normalize_matchup_text(str(leg.get("display_event") or leg.get("title") or ""))
    return f"all:{title_key or leg.get('market_ticker', '')}".lower()


def all_day_candidate_legs(
    markets: list[dict[str, Any]],
    yyyymmdd: str,
    min_leg_probability: float = DEFAULT_ALL_DAY_MIN_LEG_PROBABILITY,
    max_leg_probability: float = DEFAULT_ALL_DAY_MAX_LEG_PROBABILITY,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for market in markets:
        status = str(market.get("status") or "").lower()
        if status not in {"open", "active"}:
            continue
        if yyyymmdd not in market_completion_date_keys(market):
            continue
        for side in ["yes", "no"]:
            quote = side_quote_from_market(market, side)
            probability = quote.get("market_implied_probability")
            if probability is None or not (min_leg_probability <= probability <= max_leg_probability):
                continue
            if quote.get("ask_cents") is None or quote.get("bid_cents") is None:
                continue
            category = infer_market_category(market)
            leg = {
                "market_ticker": market.get("ticker", ""),
                "event_ticker": market.get("event_ticker", ""),
                "side": quote["side"],
                "title": market.get("title", ""),
                "subtitle": market.get(f"{quote['side']}_sub_title", "") or market.get("title", ""),
                "rules": market.get("rules_primary", ""),
                "display_event": market.get("title", "") or market.get("event_ticker", ""),
                "status": market.get("status", ""),
                "volume_24h": market.get("volume_24h_fp", ""),
                "open_interest": market.get("open_interest_fp", ""),
                "event_start_time": market.get("occurrence_datetime", ""),
                "close_time": market.get("close_time", ""),
                "market_close_time": market.get("close_time", ""),
                "expected_expiration_time": market.get("expected_expiration_time", ""),
                "expiration_time": market.get("expiration_time", ""),
                "api_fetched_at": market.get("_api_fetched_at", ""),
                "market_updated_at": market.get("updated_time", ""),
                "source_updated_at": market.get("updated_time", ""),
                "sport": category,
                "probability": probability,
                "required_probability": min_leg_probability,
                "event_date": yyyymmdd,
                **quote,
            }
            leg["spread_cents"] = leg_spread_cents(leg)
            leg["open_interest_value"] = numeric_text(leg.get("open_interest"))
            leg["volume_24h_value"] = numeric_text(leg.get("volume_24h"))
            leg["overlap_key"] = all_day_overlap_key(leg)
            leg["risk_flags"] = leg_risk_flags(leg)
            leg["warning_flags"] = leg_warning_flags(leg)
            leg["exact_bet_score"] = exact_bet_score(leg)
            if leg["spread_cents"] <= 25 and not leg["risk_flags"]:
                candidates.append(leg)
    return candidates


def build_all_day_slip(
    markets: list[dict[str, Any]],
    yyyymmdd: str,
    min_leg_probability: float = DEFAULT_ALL_DAY_MIN_LEG_PROBABILITY,
    max_leg_probability: float = DEFAULT_ALL_DAY_MAX_LEG_PROBABILITY,
    min_legs: int = 8,
    max_legs: int = 24,
    stake_dollars: float = 5.0,
) -> dict[str, Any]:
    universe = all_day_candidate_legs(
        markets,
        yyyymmdd,
        min_leg_probability=min_leg_probability,
        max_leg_probability=max_leg_probability,
    )
    if len(universe) < min_legs:
        return {
            "action": "NO_SLIP",
            "reason": "Not enough same-day Kalshi markets passed the 75–85% filters.",
            "min_leg_probability": min_leg_probability,
            "max_leg_probability": max_leg_probability,
            "eligible_leg_count": len(universe),
            "legs": [],
        }

    ranked = sorted(
        universe,
        key=lambda leg: (
            abs(leg["probability"] - min_leg_probability),
            leg["spread_cents"],
            -leg["exact_bet_score"],
            -leg["open_interest_value"],
            -leg["volume_24h_value"],
        ),
    )
    selected: list[dict[str, Any]] = []
    selected_overlap_keys: set[str] = set()
    selected_market_sides: set[tuple[str, str]] = set()
    category_counts: dict[str, int] = {}
    skipped_overlap_count = 0
    max_per_category = max(4, max_legs // 2)

    def try_add_leg(leg: dict[str, Any]) -> bool:
        nonlocal skipped_overlap_count
        overlap_key = leg.get("overlap_key") or all_day_overlap_key(leg)
        market_side = (leg.get("market_ticker", ""), leg.get("side", ""))
        if market_side in selected_market_sides:
            return False
        if overlap_key in selected_overlap_keys:
            skipped_overlap_count += 1
            return False
        if category_counts.get(leg["sport"], 0) >= max_per_category:
            return False
        selected.append(leg)
        selected_overlap_keys.add(overlap_key)
        selected_market_sides.add(market_side)
        category_counts[leg["sport"]] = category_counts.get(leg["sport"], 0) + 1
        return True

    for category in sorted({leg["sport"] for leg in ranked}):
        for leg in ranked:
            if leg["sport"] == category and try_add_leg(leg):
                break
        if len(selected) == max_legs:
            break

    for leg in ranked:
        if len(selected) == max_legs:
            break
        try_add_leg(leg)

    if len(selected) < min_legs:
        return {
            "action": "NO_SLIP",
            "reason": "Could not build a clean same-day all-market slip without overlapping event families.",
            "min_leg_probability": min_leg_probability,
            "max_leg_probability": max_leg_probability,
            "eligible_leg_count": len(universe),
            "legs": [],
        }

    best = slip_summary(selected, min_leg_probability, stake_dollars)
    best["max_leg_probability"] = max_leg_probability
    best["eligible_leg_count"] = len(universe)
    best["skipped_overlap_count"] = skipped_overlap_count
    best["note"] = (
        "Built from all open Kalshi markets that close or are expected to expire today. "
        "Each selected YES/NO side is priced between 75% and 85%, with one leg per event family."
    )
    return best


def clamp_probability(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, value))


def signal_is_public(signal: dict[str, Any]) -> bool:
    return bool(signal.get("is_public", True)) and bool(signal.get("url") or signal.get("source_url")) and not signal.get("contains_private_info", False)


def signal_source_type_bonus(signal: dict[str, Any]) -> float:
    source_type = str(signal.get("source_type") or signal.get("type") or "").lower().replace("-", "_")
    if source_type in {"primary_source", "official_data", "official_report", "peer_reviewed"}:
        return 1.0
    if source_type in {"expert", "industry_expert", "trusted_bettor", "analyst"}:
        return 0.82
    if source_type in {"news", "public_bettor", "social", "prediction_market"}:
        return 0.62
    return 0.45


def wilson_lower_bound(wins: float, total: float, z_score: float = 1.28) -> float:
    if total <= 0:
        return 0.50
    proportion = wins / total
    denominator = 1.0 + z_score * z_score / total
    center = proportion + z_score * z_score / (2.0 * total)
    margin = z_score * math.sqrt((proportion * (1.0 - proportion) + z_score * z_score / (4.0 * total)) / total)
    return clamp_probability((center - margin) / denominator)


def signal_probability(signal: dict[str, Any]) -> float:
    for field in ["model_probability", "probability", "estimated_probability"]:
        if signal.get(field) is not None:
            value = numeric_text(signal.get(field))
            return clamp_probability(value / 100.0 if value > 1 else value)
    confidence = numeric_text(signal.get("confidence"), 0.5)
    if confidence > 1:
        confidence /= 100.0
    wins = numeric_text(signal.get("historical_wins") or signal.get("wins"))
    total = numeric_text(signal.get("historical_total") or signal.get("sample_size"))
    if total > 0:
        return clamp_probability((clamp_probability(confidence) * 0.45) + (wilson_lower_bound(wins, total) * 0.55))
    return clamp_probability(confidence)


def signal_quality_score(signal: dict[str, Any]) -> float:
    if not signal_is_public(signal):
        return 0.0
    wins = numeric_text(signal.get("historical_wins") or signal.get("wins"))
    total = numeric_text(signal.get("historical_total") or signal.get("sample_size"))
    track_record = wilson_lower_bound(wins, total)
    confidence = signal_probability(signal)
    sample_depth = min(1.0, math.sqrt(total) / 18.0) if total > 0 else 0.12
    declared_quality = numeric_text(signal.get("source_quality"), 0.6)
    if declared_quality > 1:
        declared_quality /= 100.0
    source_type = signal_source_type_bonus(signal)
    score = (
        track_record * 0.28
        + confidence * 0.26
        + clamp_probability(declared_quality, 0.0, 1.0) * 0.18
        + sample_depth * 0.14
        + source_type * 0.14
    )
    return round(score * 100.0, 2)


def token_match_score(hint: str, text: str) -> float:
    tokens = [token for token in re.sub(r"[^a-z0-9]+", " ", (hint or "").lower()).split() if len(token) >= 3]
    if not tokens:
        return 0.0
    haystack = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return sum(1 for token in tokens if token in haystack) / len(tokens)


def research_leg_text(leg: dict[str, Any]) -> str:
    return " ".join(
        str(leg.get(field, ""))
        for field in ["market_ticker", "event_ticker", "display_event", "title", "subtitle", "rules", "side"]
    )


def research_signal_matches(leg: dict[str, Any], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leg_text = research_leg_text(leg)
    matches: list[dict[str, Any]] = []
    for signal in signals:
        if not signal_is_public(signal):
            continue
        market_score = token_match_score(str(signal.get("market_hint") or signal.get("event_hint") or ""), leg_text)
        selection_score = token_match_score(str(signal.get("selection_hint") or ""), leg_text)
        if market_score < 0.42 and selection_score < 0.42:
            continue
        if signal.get("selection_hint") and selection_score < 0.34:
            continue
        quality = signal_quality_score(signal)
        if quality <= 0:
            continue
        matches.append(
            {
                "source": signal.get("source", "unknown"),
                "platform": signal.get("platform", "unknown"),
                "url": signal.get("url") or signal.get("source_url", ""),
                "source_type": signal.get("source_type") or signal.get("type") or "public",
                "quality_score": quality,
                "signal_probability": round(signal_probability(signal), 4),
                "match_score": round(max(market_score, selection_score), 4),
            }
        )
    return sorted(matches, key=lambda item: (item["quality_score"], item["match_score"]), reverse=True)


def research_probability_for_leg(leg: dict[str, Any], matches: list[dict[str, Any]]) -> dict[str, Any]:
    weights = [max(0.01, (match["quality_score"] / 100.0) * match["match_score"]) for match in matches]
    total_weight = sum(weights)
    external_probability = sum(match["signal_probability"] * weight for match, weight in zip(matches, weights)) / total_weight
    kalshi_probability = float(leg.get("probability") or 0.5)
    source_count = len(matches)
    disagreement = 0.0
    if source_count >= 2:
        mean = external_probability
        disagreement = math.sqrt(sum((match["signal_probability"] - mean) ** 2 for match in matches) / source_count)
    spread_penalty = min(0.10, leg_spread_cents(leg) / 100.0 * 0.30)
    source_penalty = 0.08 if source_count == 1 else max(0.0, 0.04 - source_count * 0.005)
    margin_of_error = min(0.25, max(0.035, disagreement + spread_penalty + source_penalty))
    blended = (external_probability * 0.72) + (kalshi_probability * 0.18) + ((sum(match["quality_score"] for match in matches) / source_count) / 100.0 * 0.10)
    research_probability = clamp_probability(blended - margin_of_error)
    return {
        "external_probability": round(external_probability, 6),
        "kalshi_probability": round(kalshi_probability, 6),
        "research_probability": round(research_probability, 6),
        "margin_of_error": round(margin_of_error, 6),
        "evidence_score": round(sum(match["quality_score"] for match in matches) / source_count, 2),
    }


def market_only_research_probability(leg: dict[str, Any]) -> dict[str, Any]:
    kalshi_probability = float(leg.get("probability") or 0.5)
    spread = leg_spread_cents(leg)
    liquidity = numeric_text(leg.get("open_interest")) + numeric_text(leg.get("volume_24h"))
    liquidity_bonus = min(0.035, math.log1p(max(0.0, liquidity)) / 160.0)
    spread_penalty = min(0.085, spread / 100.0 * 0.30)
    category = str(leg.get("sport") or "Kalshi")
    category_penalty = {
        "Weather": 0.025,
        "Markets": 0.045,
        "Crypto": 0.055,
        "Sports": 0.060,
        "Esports": 0.070,
        "Politics": 0.075,
        "Media": 0.080,
        "Kalshi": 0.070,
    }.get(category, 0.070)
    margin_of_error = min(0.18, max(0.075, category_penalty + spread_penalty + (0.025 if liquidity < 25 else 0.0)))
    research_probability = clamp_probability(kalshi_probability + liquidity_bonus - margin_of_error)
    return {
        "external_probability": None,
        "kalshi_probability": round(kalshi_probability, 6),
        "research_probability": round(research_probability, 6),
        "margin_of_error": round(margin_of_error, 6),
        "evidence_score": round(max(35.0, min(62.0, 50.0 + liquidity_bonus * 200.0 - spread_penalty * 100.0)), 2),
    }


def build_research_edge_slip(
    markets: list[dict[str, Any]],
    yyyymmdd: str,
    public_signals: list[dict[str, Any]],
    min_research_probability: float = DEFAULT_RESEARCH_EDGE_MIN_PROBABILITY,
    min_legs: int = 4,
    max_legs: int = 12,
    stake_dollars: float = 5.0,
) -> dict[str, Any]:
    allowed_signals = [signal for signal in public_signals if signal_is_public(signal)]
    scout_mode = not allowed_signals
    base_legs = all_day_candidate_legs(markets, yyyymmdd, min_leg_probability=0.62, max_leg_probability=0.92)
    enriched: list[dict[str, Any]] = []
    for leg in base_legs:
        if scout_mode:
            matches: list[dict[str, Any]] = []
            probability_summary = market_only_research_probability(leg)
        else:
            matches = research_signal_matches(leg, allowed_signals)
            if not matches:
                continue
            has_primary_source = any(str(match.get("source_type", "")).lower().replace("-", "_") in {"primary_source", "official_data", "official_report", "peer_reviewed"} for match in matches)
            if len(matches) < 2 and not has_primary_source:
                continue
            probability_summary = research_probability_for_leg(leg, matches)
        if probability_summary["research_probability"] < min_research_probability:
            continue
        if probability_summary["margin_of_error"] > (0.18 if scout_mode else 0.13):
            continue
        candidate = {
            **leg,
            "probability": probability_summary["research_probability"],
            "research_probability": probability_summary["research_probability"],
            "external_probability": probability_summary["external_probability"],
            "kalshi_probability": probability_summary["kalshi_probability"],
            "margin_of_error": probability_summary["margin_of_error"],
            "evidence_score": probability_summary["evidence_score"],
            "evidence_count": len(matches),
            "evidence": matches[:4],
            "research_mode": "market_only_scout" if scout_mode else "source_backed",
            "required_probability": min_research_probability,
            "exact_bet_score": round(min(100.0, float(leg.get("exact_bet_score") or 0) * 0.35 + probability_summary["evidence_score"] * 0.65), 2),
        }
        enriched.append(candidate)

    if len(enriched) < min_legs:
        return {
            "action": "NO_SLIP",
            "reason": "Not enough same-day markets cleared the Research Edge model.",
            "min_research_probability": min_research_probability,
            "eligible_leg_count": len(enriched),
            "evidence_signal_count": len(allowed_signals),
            "legs": [],
        }

    ranked = sorted(
        enriched,
        key=lambda leg: (
            -leg["research_probability"],
            leg["margin_of_error"],
            -leg["evidence_count"],
            -leg["evidence_score"],
            leg["spread_cents"],
        ),
    )
    selected: list[dict[str, Any]] = []
    overlap_keys: set[str] = set()
    category_counts: dict[str, int] = {}
    skipped_overlap_count = 0
    max_per_category = max(3, max_legs // 2)
    for category in sorted({leg["sport"] for leg in ranked}):
        for leg in ranked:
            if leg["sport"] != category:
                continue
            overlap_key = leg.get("overlap_key") or all_day_overlap_key(leg)
            if overlap_key not in overlap_keys:
                selected.append(leg)
                overlap_keys.add(overlap_key)
                category_counts[leg["sport"]] = category_counts.get(leg["sport"], 0) + 1
                break
    for leg in ranked:
        if len(selected) == max_legs:
            break
        overlap_key = leg.get("overlap_key") or all_day_overlap_key(leg)
        if overlap_key in overlap_keys:
            skipped_overlap_count += 1
            continue
        if category_counts.get(leg["sport"], 0) >= max_per_category:
            continue
        selected.append(leg)
        overlap_keys.add(overlap_key)
        category_counts[leg["sport"]] = category_counts.get(leg["sport"], 0) + 1

    if len(selected) < min_legs:
        return {
            "action": "NO_SLIP",
            "reason": "Research model found candidates, but not enough survived overlap and category caps.",
            "min_research_probability": min_research_probability,
            "eligible_leg_count": len(enriched),
            "evidence_signal_count": len(allowed_signals),
            "legs": [],
        }

    best = slip_summary(selected, min_research_probability, stake_dollars)
    best["model"] = "research_edge_v1"
    best["research_mode"] = "market_only_scout" if scout_mode else "source_backed"
    best["min_research_probability"] = min_research_probability
    best["eligible_leg_count"] = len(enriched)
    best["evidence_signal_count"] = len(allowed_signals)
    best["skipped_overlap_count"] = skipped_overlap_count
    best["note"] = (
        "Scout mode: no outside source file is loaded, so this uses Kalshi price, liquidity, spread, category risk, margin of error, and overlap control."
        if scout_mode
        else "Built from same-day Kalshi markets with public external evidence. Research probability blends outside source probability, Kalshi price, source quality, margin of error, and overlap control."
    )
    return best


def enrich_combo_market(http: HttpClient, market: dict[str, Any], market_cache: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    enriched_legs: list[dict[str, Any]] = []
    probabilities: list[float] = []
    event_tickers: list[str] = []
    for leg in market.get("legs", []):
        ticker = leg.get("market_ticker", "")
        side = leg.get("side", "yes")
        if ticker not in market_cache:
            market_cache[ticker] = fetch_market_by_ticker(http, ticker)
        leg_market = market_cache[ticker]
        if leg_market:
            quote = side_quote_from_market(leg_market, side)
            probability = quote["market_implied_probability"]
            if probability is not None:
                probabilities.append(probability)
            event_tickers.append(leg_market.get("event_ticker", leg.get("event_ticker", "")))
            enriched_legs.append(
                {
                    "market_ticker": ticker,
                    "event_ticker": leg_market.get("event_ticker", leg.get("event_ticker", "")),
                    "side": quote["side"],
                    "title": leg_market.get("title", ""),
                    "subtitle": leg_market.get(f"{quote['side']}_sub_title", ""),
                    "rules": leg_market.get("rules_primary", ""),
                    "display_event": display_event_from_rules(leg_market.get("rules_primary", "")),
                    "status": leg_market.get("status", ""),
                    "volume_24h": leg_market.get("volume_24h_fp", ""),
                    "open_interest": leg_market.get("open_interest_fp", ""),
                    "event_start_time": leg_market.get("occurrence_datetime", ""),
                    "close_time": leg_market.get("close_time", ""),
                    "market_close_time": leg_market.get("close_time", ""),
                    "expected_expiration_time": leg_market.get("expected_expiration_time", ""),
                    "expiration_time": leg_market.get("expiration_time", ""),
                    "api_fetched_at": leg_market.get("_api_fetched_at", ""),
                    "market_updated_at": leg_market.get("updated_time", ""),
                    "source_updated_at": leg_market.get("updated_time", ""),
                    **quote,
                }
            )
        else:
            enriched_legs.append(
                {
                    "market_ticker": ticker,
                    "event_ticker": leg.get("event_ticker", ""),
                    "side": side,
                    "title": "",
                    "subtitle": "",
                    "rules": "",
                    "status": "missing",
                    "market_implied_probability": None,
                }
            )
    raw_probability = product_probability(probabilities)
    penalty = repeated_event_penalty(event_tickers)
    adjusted_probability = None if raw_probability is None else round(raw_probability * (1.0 - penalty), 6)
    combo_yes_ask = market.get("yes_ask_cents")
    combo_ev_cents = (
        None
        if adjusted_probability is None or combo_yes_ask is None or combo_yes_ask <= 0
        else round(adjusted_probability * 100.0 - combo_yes_ask, 2)
    )
    missing_leg_count = sum(1 for leg in enriched_legs if leg.get("market_implied_probability") is None)
    market.update(
        {
            "leg_details": enriched_legs,
            "raw_market_implied_probability": raw_probability,
            "adjusted_market_implied_probability": adjusted_probability,
            "correlation_penalty": penalty,
            "missing_leg_count": missing_leg_count,
            "real_data_ready": missing_leg_count == 0 and raw_probability is not None,
            "combo_ev_cents": combo_ev_cents,
            "real_data_warning": (
                "All leg probabilities are market-implied from live Kalshi bid/ask, not predictive model guarantees."
                if missing_leg_count == 0
                else "Some underlying legs could not be priced from public Kalshi data."
            ),
        }
    )
    return market


def parse_kalshi_market(market: dict[str, Any]) -> dict[str, Any]:
    legs = market.get("mve_selected_legs") or []
    return {
        "ticker": market.get("ticker", ""),
        "event_ticker": market.get("event_ticker", ""),
        "title": market.get("title", ""),
        "legs_text": split_market_title(market.get("title", "")),
        "legs": legs,
        "yes_ask_cents": cents_from_dollars(market.get("yes_ask_dollars")),
        "yes_bid_cents": cents_from_dollars(market.get("yes_bid_dollars")),
        "no_ask_cents": cents_from_dollars(market.get("no_ask_dollars")),
        "no_bid_cents": cents_from_dollars(market.get("no_bid_dollars")),
        "liquidity_dollars": market.get("liquidity_dollars", ""),
        "volume_24h": market.get("volume_24h_fp", ""),
        "close_time": market.get("close_time", ""),
        "expected_expiration_time": market.get("expected_expiration_time", ""),
        "api_fetched_at": market.get("_api_fetched_at", ""),
        "market_updated_at": market.get("updated_time", ""),
        "source_updated_at": market.get("updated_time", ""),
        "status": market.get("status", ""),
        "source": "kalshi_public",
    }


def fetch_kalshi_combo_markets(http: HttpClient, limit: int = 100) -> list[dict[str, Any]]:
    raw_markets: dict[str, dict[str, Any]] = {}
    queries = [
        "MLB WNBA sports total runs points goals",
        "over under runs points goals",
        "",
    ]
    for query in queries:
        cursor = ""
        pages = 1 if query else 5
        for _ in range(pages):
            request = {"limit": limit, "status": "open"}
            if query:
                request["query"] = query
            if cursor:
                request["cursor"] = cursor
            url = f"{KALSHI_PUBLIC_BASE_URL}/markets?{urlencode(request)}"
            response = http.get_text(url)
            payload = response.json()
            for market in payload.get("markets", []):
                ticker = market.get("ticker", "")
                if ticker:
                    market["_api_fetched_at"] = response.fetched_at
                    market["_source_url"] = response.url
                    raw_markets[ticker] = market
            cursor = payload.get("cursor") or ""
            if not cursor:
                break
    markets = [parse_kalshi_market(market) for market in raw_markets.values()]
    filtered_markets = [
        market
        for market in markets
        if market["ticker"].startswith("KXMVE")
        and any(word in market["title"].lower() for word in SPORTS_COMBO_WORDS)
    ]
    market_cache: dict[str, dict[str, Any] | None] = {}
    enriched_markets = [enrich_combo_market(http, market, market_cache) for market in filtered_markets]
    return sorted(
        enriched_markets,
        key=lambda market: (
            market.get("real_data_ready", False),
            market.get("adjusted_market_implied_probability") or 0,
        ),
        reverse=True,
    )


def market_is_tradable(market: dict[str, Any]) -> bool:
    ask = market.get("yes_ask_cents")
    return ask is not None and 0 < ask < 100


def build_bet_candidates(
    markets: list[dict[str, Any]],
    target_probability: float = 0.80,
    min_edge_cents: float = 1.0,
    min_ask_cents: float = 1.0,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for market in markets:
        probability = market.get("adjusted_market_implied_probability")
        ask = market.get("yes_ask_cents")
        edge = market.get("combo_ev_cents")
        if (
            market.get("real_data_ready")
            and probability is not None
            and ask is not None
            and edge is not None
            and market_is_tradable(market)
            and ask >= min_ask_cents
            and probability >= target_probability
            and edge >= min_edge_cents
        ):
            candidates.append(
                {
                    "ticker": market.get("ticker", ""),
                    "title": market.get("title", ""),
                    "adjusted_probability": probability,
                    "yes_ask_cents": ask,
                    "edge_cents": edge,
                    "correlation_penalty": market.get("correlation_penalty", 0),
                    "leg_count": len(market.get("leg_details") or []),
                    "legs": market.get("leg_details") or [],
                    "reason": (
                        f"Live Kalshi leg-implied probability {probability:.2%} "
                        f"vs combo YES ask {ask:.2f}c."
                    ),
                }
            )
    return sorted(candidates, key=lambda item: (item["edge_cents"], item["adjusted_probability"]), reverse=True)


def build_pick_summary(markets: list[dict[str, Any]]) -> dict[str, Any]:
    thresholds = {
        "target_probability": 0.80,
        "min_edge_cents": 1.0,
        "min_ask_cents": 1.0,
    }
    candidates = build_bet_candidates(markets, **thresholds)
    tradable_count = sum(1 for market in markets if market_is_tradable(market))
    if not candidates:
        watchlist = [
            market
            for market in sorted(
                markets,
                key=lambda item: (
                    item.get("combo_ev_cents") if item.get("combo_ev_cents") is not None else -999,
                    item.get("adjusted_market_implied_probability") or 0,
                ),
                reverse=True,
            )
            if market_is_tradable(market)
        ][:10]
        return {
            "action": "NO_BET",
            "reason": (
                "No real-data combo met the 80% probability target and positive-edge threshold. "
                "The bot will not force a real-money bet."
            ),
            "thresholds": thresholds,
            "tradable_combo_count": tradable_count,
            "candidates": [],
            "watchlist": watchlist,
        }
    return {
        "action": "BET_CANDIDATE",
        "reason": "At least one real-data combo passed the probability and edge filters.",
        "thresholds": thresholds,
        "tradable_combo_count": tradable_count,
        "candidates": candidates[:5],
        "watchlist": candidates[5:15],
    }


def build_failure_guardrail_summary() -> dict[str, Any]:
    return {
        "status": "ACTIVE",
        "latest_lesson": "Miami vs Colorado failed because a high-probability-looking NO on Over 16.5 still carried extreme MLB tail risk in a Colorado run environment.",
        "active_blocks": [
            {
                "flag": "high_scoring_mlb_total_under_blocked",
                "rule": "Never take MLB total-runs unders in high-scoring environments.",
            },
            {
                "flag": "extreme_mlb_total_under_tail_risk",
                "rule": "Exclude MLB NO legs on Over 14.5+ total-runs markets.",
            },
            {
                "flag": "coors_or_colorado_total_under_tail_risk",
                "rule": "Exclude Colorado/Coors-style MLB NO legs on Over 12.5+ total-runs markets.",
            },
            {
                "flag": "colorado_run_environment_review",
                "rule": "Colorado/Coors-style over legs require 90%+; unders stay blocked.",
            },
            {
                "flag": "high_scoring_over_threshold",
                "rule": "High-scoring MLB over legs require 85%+; Colorado or 12.5+ lines require 90%+.",
            },
            {
                "flag": "overlap_guard",
                "rule": "Keep one normalized matchup per slip.",
            },
        ],
        "not_fixed_by": [
            "Adding more legs",
            "Trusting market-implied probability alone",
            "Assuming a 19-leg combo should behave like one individual 80%+ leg",
        ],
    }


def build_today_payload(
    yyyymmdd: str | None = None,
    slip_target_probability: float = DEFAULT_MIN_LEG_PROBABILITY,
    slip_min_leg_probability: float | None = None,
    slip_max_leg_probability: float = 0.985,
    slip_min_legs: int = 8,
    slip_max_legs: int = 20,
    slip_stake_dollars: float = 5.0,
    leverage_min_leg_probability: float = DEFAULT_LEVERAGE_MIN_LEG_PROBABILITY,
    public_intel_path: str | Path | None = None,
) -> dict[str, Any]:
    run_date = yyyymmdd or today_key()
    http = HttpClient()
    games = fetch_espn_schedule(http, run_date)
    markets = fetch_kalshi_combo_markets(http)
    all_day_markets = fetch_kalshi_same_day_markets(http, run_date)
    pick_summary = build_pick_summary(markets)
    intel_bot = PublicIntelBot()
    public_signals = intel_bot.load_signals(public_intel_path)
    initial_public_intel = intel_bot.build_summary(markets, public_signals, overlap_key_fn=overlap_key_for_leg)
    intel_by_overlap_key = initial_public_intel.get("intel_by_overlap_key", {})
    custom_slip = build_custom_slip(
        markets,
        target_probability=slip_target_probability,
        min_leg_probability=slip_min_leg_probability,
        max_leg_probability=slip_max_leg_probability,
        min_legs=slip_min_legs,
        max_legs=slip_max_legs,
        stake_dollars=slip_stake_dollars,
        yyyymmdd=run_date,
        intel_by_overlap_key=intel_by_overlap_key,
    )
    leverage_slip = build_custom_slip(
        markets,
        target_probability=leverage_min_leg_probability,
        min_leg_probability=leverage_min_leg_probability,
        max_leg_probability=slip_max_leg_probability,
        min_legs=slip_min_legs,
        max_legs=slip_max_legs,
        stake_dollars=slip_stake_dollars,
        yyyymmdd=run_date,
        intel_by_overlap_key=intel_by_overlap_key,
    )
    if leverage_slip.get("action") == "BUILD_SLIP":
        leverage_slip["note"] = (
            "Leverage tier built from live Kalshi bid/ask probabilities with a lower 75% individual-leg filter. "
            "This can create bigger payouts but materially lowers the full combo probability."
        )
    all_day_slip = build_all_day_slip(
        all_day_markets,
        run_date,
        min_leg_probability=DEFAULT_ALL_DAY_MIN_LEG_PROBABILITY,
        max_leg_probability=DEFAULT_ALL_DAY_MAX_LEG_PROBABILITY,
        min_legs=slip_min_legs,
        max_legs=max(slip_max_legs, 24),
        stake_dollars=slip_stake_dollars,
    )
    research_edge_slip = build_research_edge_slip(
        all_day_markets,
        run_date,
        public_signals,
        min_research_probability=DEFAULT_RESEARCH_EDGE_MIN_PROBABILITY,
        min_legs=4,
        max_legs=12,
        stake_dollars=slip_stake_dollars,
    )
    public_intel_summary = intel_bot.build_summary(
        markets,
        public_signals,
        primary_slip=custom_slip,
        leverage_slip=leverage_slip,
        overlap_key_fn=overlap_key_for_leg,
    )
    research_summary = DeepResearchBot().build_summary(markets, custom_slip, leverage_slip)
    source_cache_status = http.cache_status()
    source_freshness_note = (
        "Some public API responses came from stale cache after a fresh fetch failed; treat slips as research-only watch data."
        if source_cache_status.get("stale_fallback_count")
        else "Public API responses were fetched live or served from the short-lived cache."
    )
    return {
        "date": run_date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_at_note": "Generated from public ESPN scoreboard APIs and public Kalshi market data.",
        "source_cache_status": source_cache_status,
        "source_freshness_note": source_freshness_note,
        "safety_note": "Paper view only. Use this for manual research; no automated real-money trading.",
        "games": games,
        "markets": markets,
        "all_day_market_count": len(all_day_markets),
        "pick_summary": pick_summary,
        "custom_slip": custom_slip,
        "leverage_slip": leverage_slip,
        "all_day_slip": all_day_slip,
        "research_edge_slip": research_edge_slip,
        "research_summary": research_summary,
        "public_intel_summary": public_intel_summary,
        "failure_guardrail_summary": build_failure_guardrail_summary(),
        "manual_probability_note": "Real-data mode: combo probabilities are market-implied from public Kalshi leg bid/ask, not fake projections.",
    }


def write_today_payload(
    path: str | Path,
    yyyymmdd: str | None = None,
    slip_target_probability: float = DEFAULT_MIN_LEG_PROBABILITY,
    slip_min_leg_probability: float | None = None,
    slip_max_leg_probability: float = 0.985,
    slip_min_legs: int = 8,
    slip_max_legs: int = 20,
    slip_stake_dollars: float = 5.0,
    leverage_min_leg_probability: float = DEFAULT_LEVERAGE_MIN_LEG_PROBABILITY,
    public_intel_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = build_today_payload(
        yyyymmdd,
        slip_target_probability=slip_target_probability,
        slip_min_leg_probability=slip_min_leg_probability,
        slip_max_leg_probability=slip_max_leg_probability,
        slip_min_legs=slip_min_legs,
        slip_max_legs=slip_max_legs,
        slip_stake_dollars=slip_stake_dollars,
        leverage_min_leg_probability=leverage_min_leg_probability,
        public_intel_path=public_intel_path,
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary_path.replace(output_path)
    return payload
