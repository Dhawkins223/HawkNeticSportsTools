"use client";

import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { getGames } from "../../lib/api";
import type { GameSummary, MarketSummary } from "../../lib/types";
import { formatOdds, formatPercent, classForEv } from "../../lib/format";
import { LoadingSkeleton } from "../../components/LoadingSkeleton";

export default function TicketsPage() {
  const gamesQuery = useQuery<GameSummary[]>({ queryKey: ["tickets-games"], queryFn: getGames });

  useEffect(() => {
    if (gamesQuery.isError) {
      toast.error((gamesQuery.error as Error).message);
    }
  }, [gamesQuery.isError, gamesQuery.error]);

  const topMarkets = useMemo(() => {
    if (!gamesQuery.data) return [] as Highlight[];
    const highlights: Highlight[] = [];
    for (const game of gamesQuery.data) {
      for (const market of game.markets) {
        highlights.push({
          game,
          market
        });
      }
    }
    return highlights
      .filter((item) => item.market.edge.evPct > 0)
      .sort((a, b) => b.market.edge.evPct - a.market.edge.evPct)
      .slice(0, 12);
  }, [gamesQuery.data]);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold text-white">Tickets board</h2>
        <p className="text-sm text-white/60">
          Highest expected value markets pulled from the model across today&apos;s slate. Build SGPs directly from these angles.
        </p>
      </header>
      {gamesQuery.isLoading && <LoadingSkeleton lines={5} />}
      {gamesQuery.data && (
        <div className="card p-6">
          <table className="table-dark text-sm">
            <thead>
              <tr>
                <th className="p-3 text-left">Game</th>
                <th className="p-3 text-left">Market</th>
                <th className="p-3 text-left">Odds</th>
                <th className="p-3 text-left">Model Prob</th>
                <th className="p-3 text-left">EV%</th>
                <th className="p-3 text-left">Safety</th>
              </tr>
            </thead>
            <tbody>
              {topMarkets.map((item) => (
                <tr key={`${item.game.id}-${item.market.label}`}>
                  <td className="p-3">
                    <div className="text-white font-semibold">
                      {item.game.away.abbr} @ {item.game.home.abbr}
                    </div>
                    <div className="text-xs text-white/40">{new Date(item.game.startTime).toLocaleString()}</div>
                  </td>
                  <td className="p-3 text-white/80">{item.market.label}</td>
                  <td className="p-3 text-white">{formatOdds(item.market.odds)}</td>
                  <td className="p-3 text-white/70">{formatPercent(item.market.edge.trueProb, 1)}</td>
                  <td className="p-3">
                    <span className={classForEv(item.market.edge.evPct)}>{item.market.edge.evPct.toFixed(2)}%</span>
                  </td>
                  <td className="p-3">
                    <span className="rounded-full bg-white/10 px-2 py-1 text-xs uppercase text-white/60">{item.market.edge.safety}</span>
                  </td>
                </tr>
              ))}
              {topMarkets.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-6 text-center text-sm text-white/40">
                    No positive edge tickets available yet. Run a sync to populate data.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type Highlight = {
  game: GameSummary;
  market: MarketSummary;
};
