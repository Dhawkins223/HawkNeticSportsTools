"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Game, type Prop } from "../../lib/api";

export type SportFilter = "All" | "NBA" | "NFL" | "MLB" | "NHL" | "Soccer" | "Golf";

export const SPORT_FILTERS: readonly SportFilter[] = ["All", "NBA", "NFL", "MLB", "NHL", "Soccer", "Golf"];

type MarketData = {
  games: Game[];
  props: Prop[];
  odds: Array<Record<string, unknown>>;
  gameMap: Map<string, Game>;
  loading: boolean;
  error: string | null;
  activeGameId: string | null;
  setActiveGameId: (id: string | null) => void;
  reload: () => Promise<void>;
};

const MANUAL_GAME_ID = "manual";

export function useMarketData(): MarketData {
  const [games, setGames] = useState<Game[]>([]);
  const [props, setProps] = useState<Prop[]>([]);
  const [odds, setOdds] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeGameId, setActiveGameId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [gameResult, propResult, oddsResult] = await Promise.all([
        api.getGames(),
        api.getProps(),
        api.getOdds(),
      ]);
      const nextGames = gameResult.items || [];
      const nextProps = propResult.items || [];
      const nextOdds = (oddsResult.items || []) as Array<Record<string, unknown>>;
      setGames(nextGames);
      setProps(nextProps);
      setOdds(nextOdds);
      setActiveGameId(String(nextGames[0]?.id || nextProps[0]?.game_id || MANUAL_GAME_ID));
    } catch {
      setError("Markets are temporarily unavailable. You can still add a market manually for the algorithm to score.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const gameMap = useMemo(() => new Map(games.map((game) => [String(game.id), game])), [games]);

  return { games, props, odds, gameMap, loading, error, activeGameId, setActiveGameId, reload };
}
