from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Game:
    game_id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    start_time: str
    signals: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketQuote:
    ticker: str
    game_id: str
    title: str
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None


@dataclass(frozen=True)
class SourceRecord:
    source: str
    kind: str
    url: str
    title: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelPrediction:
    game_id: str
    sport: str
    target: str
    probability: float
    fair_price_cents: float
    model_name: str
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EdgeResult:
    ticker: str
    game_id: str
    side: str
    model_probability: float
    entry_price_cents: float
    fair_price_cents: float
    expected_value_cents: float
    title: str
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TotalLeg:
    leg_id: str
    sport: str
    league: str
    event_name: str
    market_title: str
    selection: str
    line: float
    model_probability: float
    entry_price_cents: float
    source_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComboResult:
    combo_id: str
    legs: list[TotalLeg]
    raw_probability: float
    adjusted_probability: float
    correlation_penalty: float
    average_entry_price_cents: float
    fair_price_cents: float
    expected_value_cents: float
    meets_target: bool
    notes: list[str] = field(default_factory=list)
