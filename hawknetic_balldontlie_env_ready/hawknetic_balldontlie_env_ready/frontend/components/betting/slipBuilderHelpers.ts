"use client";

import { useState } from "react";
import { arrayMove } from "@dnd-kit/sortable";
import type { BetSlipLeg, Bookmaker } from "../../types/betting";
import type { MarketOption } from "./marketOptions";
import type { SportFilter } from "./useMarketData";

const DEFAULT_AMERICAN_ODDS = 100;

export function makeLegFromOption(option: MarketOption, bookmaker: Bookmaker): BetSlipLeg {
  return {
    id: `${option.id}-${Date.now()}`,
    sport: "NBA",
    bookmaker,
    gameId: option.gameId,
    eventLabel: option.eventLabel,
    startsAt: option.startsAt,
    marketType: option.marketType,
    selection: option.label,
    line: option.line ?? null,
    oddsAmerican: option.oddsAmerican || DEFAULT_AMERICAN_ODDS,
    playerId: option.playerId ?? null,
    playerName: option.playerName ?? null,
    notes: option.source === "props" ? option.id : null,
  };
}

export type ManualLegInput = {
  eventLabel: string;
  marketType: BetSlipLeg["marketType"];
  selection: string;
  line: string;
  oddsAmerican: string;
};

export const EMPTY_MANUAL_LEG: ManualLegInput = {
  eventLabel: "",
  marketType: "player_prop",
  selection: "",
  line: "",
  oddsAmerican: "",
};

export function isManualLegValid(manual: ManualLegInput): boolean {
  const oddsAmerican = Number(manual.oddsAmerican);
  return Boolean(manual.eventLabel) && Boolean(manual.selection) && Number.isFinite(oddsAmerican) && oddsAmerican !== 0;
}

export function makeLegFromManual(manual: ManualLegInput, bookmaker: Bookmaker, sport: SportFilter): BetSlipLeg {
  return {
    id: `manual-${Date.now()}`,
    sport: sport === "All" ? "NBA" : sport,
    bookmaker,
    gameId: `manual-${manual.eventLabel.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    eventLabel: manual.eventLabel,
    marketType: manual.marketType,
    selection: manual.selection,
    line: manual.line ? Number(manual.line) : null,
    oddsAmerican: Number(manual.oddsAmerican),
    notes: "Manual market entry",
  };
}

/** Tiny hook that owns the legs array + immutable updaters. */
export function useLegsState() {
  const [legs, setLegs] = useState<BetSlipLeg[]>([]);

  return {
    legs,
    append(leg: BetSlipLeg) {
      setLegs((current) => [...current, leg]);
    },
    remove(id: string) {
      setLegs((current) => current.filter((leg) => leg.id !== id));
    },
    move(index: number, direction: -1 | 1) {
      setLegs((current) => {
        const target = index + direction;
        if (target < 0 || target >= current.length) return current;
        return arrayMove(current, index, target);
      });
    },
    reorder(oldIndex: number, newIndex: number) {
      setLegs((current) => arrayMove(current, oldIndex, newIndex));
    },
  };
}
