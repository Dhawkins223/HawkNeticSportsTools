"use client";

import { useMemo, useState } from "react";
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useAuth } from "../../lib/auth";
import { TopEvScanner } from "../insights/TopEvScanner";
import type { MarketType } from "../../types/betting";
import { AuthBar } from "./AuthBar";
import { DashboardTopbar } from "./DashboardTopbar";
import { MarketBoard, type MarketTab } from "./MarketBoard";
import { SportsBoard } from "./SportsBoard";
import { SlipPanel } from "./SlipPanel";
import { useMarketData, type SportFilter } from "./useMarketData";
import { useSlipBuilder } from "./useSlipBuilder";
import {
  oddsRowToMarketOption,
  propToMarketOptions,
  type MarketOption,
} from "./marketOptions";

const TAB_TO_MARKET_TYPE: Partial<Record<MarketTab, MarketType>> = {
  "Player Props": "player_prop",
  Moneyline: "moneyline",
  Spread: "spread",
  Total: "total",
};

function tabMatchesOption(tab: MarketTab, option: MarketOption): boolean {
  if (tab === "Popular" || tab === "Same Game") return true;
  return TAB_TO_MARKET_TYPE[tab] === option.marketType;
}

function gameMatchesOption(activeGameId: string | null, option: MarketOption): boolean {
  return !activeGameId || activeGameId === "manual" || option.gameId === activeGameId;
}

export default function HawkBet365DecisionDashboard() {
  const { user, logout } = useAuth();
  const market = useMarketData();
  const slip = useSlipBuilder();
  const [sport, setSport] = useState<SportFilter>("NBA");
  const [activeTab, setActiveTab] = useState<MarketTab>("Popular");

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const marketOptions = useMemo<MarketOption[]>(() => {
    const fromProps = market.props.flatMap((prop) => propToMarketOptions(prop, market.gameMap));
    const fromOdds = market.odds.map((row, index) => oddsRowToMarketOption(row, index, market.gameMap));
    return [...fromProps, ...fromOdds];
  }, [market.gameMap, market.odds, market.props]);

  const filteredOptions = useMemo(
    () => marketOptions.filter((option) => gameMatchesOption(market.activeGameId, option) && tabMatchesOption(activeTab, option)),
    [marketOptions, market.activeGameId, activeTab],
  );

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const activeId = String(active.id);
    const overId = String(over.id);
    if (activeId.startsWith("option:") && overId === "slip-drop") {
      const option = marketOptions.find((item) => `option:${item.id}` === activeId);
      if (option) slip.addOption(option);
      return;
    }
    if (activeId !== overId && slip.legs.some((leg) => leg.id === activeId)) {
      const oldIndex = slip.legs.findIndex((leg) => leg.id === activeId);
      const newIndex = slip.legs.findIndex((leg) => leg.id === overId);
      if (oldIndex !== -1 && newIndex !== -1) slip.reorderLegs(oldIndex, newIndex);
    }
  }

  const slipPanel = (
    <SlipPanel
      legs={slip.legs}
      bookmaker={slip.bookmaker}
      setBookmaker={slip.setBookmaker}
      stake={slip.stake}
      setStake={slip.setStake}
      manual={slip.manual}
      setManual={slip.setManual}
      onAddManual={() => slip.addManualLeg(sport)}
      onRemove={slip.removeLeg}
      onMove={slip.moveLeg}
      onAnalyze={slip.analyze}
      onSave={() => slip.saveSlip(sport, Boolean(user))}
      analyzing={slip.analyzing}
      analysis={slip.analysis}
      savingSlip={slip.savingSlip}
      savedSlipMsg={slip.savedSlipMsg}
      isAuthenticated={Boolean(user)}
    />
  );

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <main className="hnBetDashboard" data-testid="hawknetic-dashboard">
        <AuthBar user={user} logout={logout} />
        <DashboardTopbar loading={market.loading} onRefresh={market.reload} />
        {market.loading && <div className="hnNotice">Loading available markets...</div>}
        {market.error && <div className="hnError">{market.error}</div>}
        {slip.analyzeError && <div className="hnError">{slip.analyzeError}</div>}
        <TopEvScanner />
        <section className="hnMainGrid">
          <SportsBoard
            games={market.games}
            sport={sport}
            setSport={setSport}
            activeGameId={market.activeGameId}
            setActiveGameId={market.setActiveGameId}
          />
          <MarketBoard
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            options={filteredOptions}
            onAddOption={slip.addOption}
          />
          <div className="hnDesktopSlip">{slipPanel}</div>
        </section>
        <button
          className="mobileSlipToggle"
          type="button"
          onClick={() => slip.setSlipOpen(!slip.slipOpen)}
          data-testid="mobile-slip-toggle"
        >
          Run ({slip.legs.length}) · Predict
        </button>
        <div className={`hnMobileSlip ${slip.slipOpen ? "open" : ""}`}>{slipPanel}</div>
        <footer className="hnFooter">
          <span>HawkneticSports — prediction tool only. We do not accept or place wagers.</span>
        </footer>
      </main>
    </DndContext>
  );
}
