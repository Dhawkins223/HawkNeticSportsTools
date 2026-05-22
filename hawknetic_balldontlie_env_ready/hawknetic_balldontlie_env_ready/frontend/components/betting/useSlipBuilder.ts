"use client";

import { useState } from "react";
import { api } from "../../lib/api";
import type { BetSlipLeg, Bookmaker, SlipAnalysisResponse } from "../../types/betting";
import type { MarketOption } from "./marketOptions";
import type { SportFilter } from "./useMarketData";
import {
  EMPTY_MANUAL_LEG,
  isManualLegValid,
  makeLegFromManual,
  makeLegFromOption,
  useLegsState,
  type ManualLegInput,
} from "./slipBuilderHelpers";

const DEFAULT_STAKE = 10;
const DEFAULT_BOOKMAKER: Bookmaker = "bet365";

export { EMPTY_MANUAL_LEG, type ManualLegInput };

function buildPersistLegs(legs: BetSlipLeg[], analysis: SlipAnalysisResponse | null) {
  return legs.map((leg) => ({
    label: leg.selection,
    market_type: leg.marketType,
    odds_value: leg.oddsAmerican,
    line: leg.line,
    probability: analysis?.legAnalyses.find((a) => a.legId === leg.id)?.modelProbability ?? null,
    game_id: leg.gameId,
    player_id: leg.playerId,
  }));
}

export function useSlipBuilder() {
  const [bookmaker, setBookmaker] = useState<Bookmaker>(DEFAULT_BOOKMAKER);
  const [stake, setStake] = useState(DEFAULT_STAKE);
  const [analysis, setAnalysis] = useState<SlipAnalysisResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [slipOpen, setSlipOpen] = useState(false);
  const [manual, setManual] = useState<ManualLegInput>(EMPTY_MANUAL_LEG);
  const [savingSlip, setSavingSlip] = useState(false);
  const [savedSlipMsg, setSavedSlipMsg] = useState<string | null>(null);

  const legsState = useLegsState();

  function addOption(option: MarketOption) {
    if (option.oddsAmerican === null) return;
    setAnalysis(null);
    legsState.append(makeLegFromOption(option, bookmaker));
    setSlipOpen(true);
  }

  function addManualLeg(sport: SportFilter) {
    if (!isManualLegValid(manual)) return;
    setAnalysis(null);
    legsState.append(makeLegFromManual(manual, bookmaker, sport));
    setManual(EMPTY_MANUAL_LEG);
    setSlipOpen(true);
  }

  function removeLeg(id: string) {
    setAnalysis(null);
    legsState.remove(id);
  }

  function moveLeg(index: number, direction: -1 | 1) {
    setAnalysis(null);
    legsState.move(index, direction);
  }

  async function analyze() {
    if (!legsState.legs.length) return;
    setAnalyzing(true);
    setAnalyzeError(null);
    setSavedSlipMsg(null);
    try {
      setAnalysis(await api.analyzeSlip({ bookmaker, stake, legs: legsState.legs }));
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
    if (!legsState.legs.length) return;
    setSavingSlip(true);
    setSavedSlipMsg(null);
    try {
      const slipName = `${sport} slip · ${new Date().toLocaleString()}`;
      const persistLegs = buildPersistLegs(legsState.legs, analysis);
      const sportKey = sport === "All" ? "NBA" : sport;
      const meta = analysis ? (analysis as unknown as Record<string, unknown>) : undefined;
      await api.saveSlip(slipName, sportKey, persistLegs, meta);
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
    legs: legsState.legs,
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
    reorderLegs: legsState.reorder,
    addManualLeg,
    analyze,
    saveSlip,
  };
}
