"use client";

import { DragOddsButton, type MarketOption } from "./marketOptions";

export type MarketTab = "Popular" | "Moneyline" | "Spread" | "Total" | "Player Props" | "Same Game";

export const MARKET_TABS: readonly MarketTab[] = ["Popular", "Moneyline", "Spread", "Total", "Player Props", "Same Game"];

type Props = {
  activeTab: MarketTab;
  setActiveTab: (tab: MarketTab) => void;
  options: MarketOption[];
  onAddOption: (option: MarketOption) => void;
};

export function MarketBoard({ activeTab, setActiveTab, options, onAddOption }: Props) {
  return (
    <section className="hnMarketBoard" data-testid="market-board">
      <div className="marketTabs">
        {MARKET_TABS.map((tab) => (
          <button
            key={tab}
            className={activeTab === tab ? "active" : ""}
            onClick={() => setActiveTab(tab)}
            data-testid={`market-tab-${tab.toLowerCase().replace(/ /g, "-")}`}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="marketRows">
        {options.length ? options.map((option) => (
          <article key={option.id} className="marketRow">
            <div>
              <strong>{option.eventLabel}</strong>
              <span>{option.marketType.replaceAll("_", " ")}</span>
            </div>
            <DragOddsButton option={option} onAdd={onAddOption} />
          </article>
        )) : (
          <div className="hnEmptyMarket">
            Not enough data available yet. Add a market manually and HawkNetic will score what it can.
          </div>
        )}
      </div>
    </section>
  );
}
