"use client";

import { useMemo } from "react";
import type { Game, Prop } from "../../lib/api";
import type { MarketType } from "../../types/betting";
import type { MarketTab } from "./MarketBoard";
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

type Args = {
  props: Prop[];
  odds: Array<Record<string, unknown>>;
  gameMap: Map<string, Game>;
  activeGameId: string | null;
  activeTab: MarketTab;
};

export function useMarketOptions({ props, odds, gameMap, activeGameId, activeTab }: Args) {
  const allOptions = useMemo<MarketOption[]>(() => {
    const fromProps = props.flatMap((prop) => propToMarketOptions(prop, gameMap));
    const fromOdds = odds.map((row, index) => oddsRowToMarketOption(row, index, gameMap));
    return [...fromProps, ...fromOdds];
  }, [props, odds, gameMap]);

  const filteredOptions = useMemo(
    () => allOptions.filter((option) => gameMatchesOption(activeGameId, option) && tabMatchesOption(activeTab, option)),
    [allOptions, activeGameId, activeTab],
  );

  return { allOptions, filteredOptions };
}
