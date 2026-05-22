"use client";

import { useState } from "react";
import { useAuth } from "../../lib/auth";
import { TopEvScanner } from "../insights/TopEvScanner";
import { AuthBar } from "./AuthBar";
import { DashboardTopbar } from "./DashboardTopbar";
import { DashboardDndProvider, makeDragEndHandler } from "./dashboardDnd";
import { MarketBoard, type MarketTab } from "./MarketBoard";
import { SportsBoard } from "./SportsBoard";
import { SlipPanel } from "./SlipPanel";
import { useMarketData, type SportFilter } from "./useMarketData";
import { useMarketOptions } from "./useMarketOptions";
import { useSlipBuilder } from "./useSlipBuilder";

type SlipBuilder = ReturnType<typeof useSlipBuilder>;

function buildSlipPanelProps(slip: SlipBuilder, sport: SportFilter, isAuthenticated: boolean) {
  return {
    legs: slip.legs,
    bookmaker: slip.bookmaker,
    setBookmaker: slip.setBookmaker,
    stake: slip.stake,
    setStake: slip.setStake,
    manual: slip.manual,
    setManual: slip.setManual,
    onAddManual: () => slip.addManualLeg(sport),
    onRemove: slip.removeLeg,
    onMove: slip.moveLeg,
    onAnalyze: slip.analyze,
    onSave: () => slip.saveSlip(sport, isAuthenticated),
    analyzing: slip.analyzing,
    analysis: slip.analysis,
    savingSlip: slip.savingSlip,
    savedSlipMsg: slip.savedSlipMsg,
    isAuthenticated,
  };
}

function MobileSlipToggle({ legCount, onToggle }: { legCount: number; onToggle: () => void }) {
  return (
    <button
      className="mobileSlipToggle"
      type="button"
      onClick={onToggle}
      data-testid="mobile-slip-toggle"
    >
      Run ({legCount}) · Predict
    </button>
  );
}

export default function HawkBet365DecisionDashboard() {
  const { user, logout } = useAuth();
  const market = useMarketData();
  const slip = useSlipBuilder();
  const [sport, setSport] = useState<SportFilter>("NBA");
  const [activeTab, setActiveTab] = useState<MarketTab>("Popular");

  const { allOptions, filteredOptions } = useMarketOptions({
    props: market.props,
    odds: market.odds,
    gameMap: market.gameMap,
    activeGameId: market.activeGameId,
    activeTab,
  });

  const onDragEnd = makeDragEndHandler({
    onAddOption: slip.addOption,
    onReorderLegs: slip.reorderLegs,
    marketOptions: allOptions,
    legs: slip.legs,
  });

  const slipPanelProps = buildSlipPanelProps(slip, sport, Boolean(user));

  return (
    <DashboardDndProvider onDragEnd={onDragEnd}>
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
          <div className="hnDesktopSlip"><SlipPanel {...slipPanelProps} variant="desktop" /></div>
        </section>
        <MobileSlipToggle legCount={slip.legs.length} onToggle={() => slip.setSlipOpen(!slip.slipOpen)} />
        <div className={`hnMobileSlip ${slip.slipOpen ? "open" : ""}`}><SlipPanel {...slipPanelProps} variant="mobile" /></div>
        <footer className="hnFooter">
          <span>HawkneticSports — prediction tool only. We do not accept or place wagers.</span>
        </footer>
      </main>
    </DashboardDndProvider>
  );
}
