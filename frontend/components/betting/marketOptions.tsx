"use client";

import { useDraggable } from "@dnd-kit/core";
import type { Game, Prop } from "../../lib/api";
import type { MarketType } from "../../types/betting";

export type MarketOption = {
  id: string;
  label: string;
  line?: number | null;
  oddsAmerican: number | null;
  marketType: MarketType;
  eventLabel: string;
  gameId: string;
  startsAt?: string;
  playerId?: string | null;
  playerName?: string | null;
  source: "props" | "odds";
};

// Single-source lookup table replaces five-branch if/else chains.
// Order matters — first matching keyword wins.
const KEYWORD_TO_MARKET_TYPE: ReadonlyArray<readonly [string, MarketType]> = [
  ["moneyline", "moneyline"],
  ["spread", "spread"],
  ["total", "total"],
  ["over", "total"],
  ["under", "total"],
  ["player", "player_prop"],
  ["points", "player_prop"],
  ["rebounds", "player_prop"],
  ["assists", "player_prop"],
  ["team", "team_prop"],
];

export function formatOdds(value?: number | null): string {
  if (value === undefined || value === null) return "No odds";
  return value > 0 ? `+${value}` : String(value);
}

export function americanToDecimal(odds: number): number {
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}

export function marketTypeFromLabel(label?: string): MarketType {
  const text = (label || "").toLowerCase();
  const found = KEYWORD_TO_MARKET_TYPE.find(([keyword]) => text.includes(keyword));
  return found ? found[1] : "player_prop";
}

export function eventLabelForGame(game?: Game): string {
  if (!game) return "Event data unavailable";
  return `${game.visitor_team_name || game.visitor_team_abbr || "Away"} @ ${game.home_team_name || game.home_team_abbr || "Home"}`;
}

export function propToMarketOptions(prop: Prop, gameMap: Map<string, Game>): MarketOption[] {
  const gameId = String(prop.game_id || "manual");
  const game = gameMap.get(gameId);
  const base = {
    line: prop.line ?? null,
    marketType: marketTypeFromLabel(prop.market || prop.selection),
    eventLabel: eventLabelForGame(game),
    gameId,
    startsAt: game?.game_date,
    playerId: prop.player_id ? String(prop.player_id) : null,
    source: "props" as const,
  };
  const label = `${prop.market || prop.selection || "Prop"} ${prop.line ?? ""}`.trim();
  const overOption: MarketOption = { ...base, id: `prop-${prop.id || label}-over`, label, oddsAmerican: prop.over_odds ?? null };
  const underLabel = label.toLowerCase().includes("under") ? label : `${label} under`;
  const underOption: MarketOption = { ...base, id: `prop-${prop.id || label}-under`, label: underLabel, oddsAmerican: prop.under_odds ?? null };
  const propHasOddsFields = prop.over_odds !== undefined || prop.under_odds !== undefined;
  return [overOption, underOption].filter((option) => option.oddsAmerican !== null || !propHasOddsFields);
}

export function oddsRowToMarketOption(row: Record<string, unknown>, index: number, gameMap: Map<string, Game>): MarketOption {
  const gameId = String(row.game_id || "manual");
  return {
    id: `odds-${row.id || index}`,
    label: String(row.selection || row.market || "Market"),
    line: null,
    oddsAmerican: typeof row.odds_value === "number" ? row.odds_value : null,
    marketType: marketTypeFromLabel(String(row.market || "")),
    eventLabel: eventLabelForGame(gameMap.get(gameId)),
    gameId,
    source: "odds",
  };
}

export function DragOddsButton({ option, onAdd }: { option: MarketOption; onAdd: (option: MarketOption) => void }) {
  const disabled = option.oddsAmerican === null;
  const { attributes, listeners, setNodeRef, transform } = useDraggable({ id: `option:${option.id}`, disabled });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  return (
    <button ref={setNodeRef} style={style} className="oddsButton" disabled={disabled} onClick={() => onAdd(option)} {...listeners} {...attributes}>
      <span>{option.label}</span>
      {option.line !== undefined && option.line !== null && <small>Line {option.line}</small>}
      <strong>{disabled ? "No odds available" : formatOdds(option.oddsAmerican)}</strong>
    </button>
  );
}
