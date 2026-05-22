"use client";

import { useState } from "react";
import { arrayMove } from "@dnd-kit/sortable";
import { api } from "../../lib/api";
import type { BetSlipLeg, Bookmaker, MarketType, SlipAnalysisResponse } from "../../types/betting";
import type { MarketOption } from "./marketOptions";
import type { SportFilter } from "./useMarketData";

const DEFAULT_AMERICAN_ODDS = 100;
const DEFAULT_STAKE = 10;
const DEFAULT_BOOKMAKER: Bookmaker = "bet365";

function makeLeg(option: MarketOption, bookmaker: Bookmaker): BetSlipLeg {
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
  marketType: MarketType;
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

export function useSlipBuilder() {
  const [bookmaker, setBookmaker] = useState<Bookmaker>(DEFAULT_BOOKMAKER);
  const [stake, setStake] = useState(DEFAULT_STAKE);
  const [legs, setLegs] = useState<BetSlipLeg[]>([]);
  const [analysis, setAnalysis] = useState<SlipAnalysisResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [slipOpen, setSlipOpen] = useState(false);
  const [manual, setManual] = useState<ManualLegInput>(EMPTY_MANUAL_LEG);
  const [savingSlip, setSavingSlip] = useState(false);
  const [savedSlipMsg, setSavedSlipMsg] = useState<string | null>(null);

  function addOption(option: MarketOption) {
    if (option.oddsAmerican === null) return;
    setAnalysis(null);
    setLegs((current) => [...current, makeLeg(option, bookmaker)]);
    setSlipOpen(true);
  }

  function removeLeg(id: string) {
    setAnalysis(null);
    setLegs((current) => current.filter((leg) => leg.id !== id));
  }

  function moveLeg(index: number, direction: -1 | 1) {
    setAnalysis(null);
    setLegs((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      return arrayMove(current, index, target);
    });
  }

  function reorderLegs(oldIndex: number, newIndex: number) {
    setLegs((current) => arrayMove(current, oldIndex, newIndex));
  }

  function addManualLeg(sport: SportFilter) {
    const oddsAmerican = Number(manual.oddsAmerican);
    if (!manual.eventLabel || !manual.selection || !Number.isFinite(oddsAmerican) || oddsAmerican === 0) return;
    setAnalysis(null);
    setLegs((current) => [...current, {
      id: `manual-${Date.now()}`,
      sport: sport === "All" ? "NBA" : sport,
      bookmaker,
      gameId: `manual-${manual.eventLabel.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      eventLabel: manual.eventLabel,
      marketType: manual.marketType,
      selection: manual.selection,
      line: manual.line ? Number(manual.line) : null,
      oddsAmerican,
      notes: "Manual market entry",
    }]);
    setManual(EMPTY_MANUAL_LEG);
    setSlipOpen(true);
  }

  async function analyze() {
    if (!legs.length) return;
    setAnalyzing(true);
    setAnalyzeError(null);
    setSavedSlipMsg(null);
    try {
      setAnalysis(await api.analyzeSlip({ bookmaker, stake, legs }));
      setSlipOpen(true);
    } catch {
      setAnalyzeError("Algorithm run is temporarily unavailable. Try again shortly.");
    } finally {
      setAnalyzing(false);
    }
  }

  async function saveSlip(sport: SportFilter, userIsAuthenticated: boolean) {
    if (!userIsAuthenticated) {
      window.location.href = "/login";
      return;
    }
    if (!legs.length) return;
    setSavingSlip(true);
    setSavedSlipMsg(null);
    try {
      const slipName = `${sport} slip · ${new Date().toLocaleString()}`;
      const persistLegs = legs.map((leg) => ({
        label: leg.selection,
        market_type: leg.marketType,
        odds_value: leg.oddsAmerican,
        line: leg.line,
        probability: analysis?.legAnalyses.find((a) => a.legId === leg.id)?.modelProbability ?? null,
        game_id: leg.gameId,
        player_id: leg.playerId,
      }));
      await api.saveSlip(slipName, sport === "All" ? "NBA" : sport, persistLegs, analysis ? (analysis as unknown as Record<string, unknown>) : undefined);
      setSavedSlipMsg("Slip saved to your account.");
    } catch (ex) {
      setSavedSlipMsg(ex instanceof Error ? ex.message : "Failed to save slip.");
    } finally {
      setSavingSlip(false);
    }
  }

  return {
    bookmaker, setBookmaker,
    stake, setStake,
    legs,
    analysis,
    analyzing,
    analyzeError,
    slipOpen, setSlipOpen,
    manual, setManual,
    savingSlip,
    savedSlipMsg,
    addOption,
    removeLeg,
    moveLeg,
    reorderLegs,
    addManualLeg,
    analyze,
    saveSlip,
  };
}
