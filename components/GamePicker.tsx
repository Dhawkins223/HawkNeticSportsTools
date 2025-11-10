"use client";

import { useMemo } from "react";
import type { GameSummary } from "../lib/types";
import clsx from "clsx";

export type GameFilters = {
  team?: string;
  status?: string;
};

type GamePickerProps = {
  games: GameSummary[];
  selectedGameId?: number;
  onSelect: (gameId: number) => void;
  filters: GameFilters;
  onFiltersChange: (filters: GameFilters) => void;
};

export function GamePicker({ games, selectedGameId, onSelect, filters, onFiltersChange }: GamePickerProps) {
  const teams = useMemo(() => {
    const unique = new Set<string>();
    games.forEach((game) => {
      unique.add(game.home.abbr);
      unique.add(game.away.abbr);
    });
    return Array.from(unique).sort();
  }, [games]);

  const statuses = useMemo(() => Array.from(new Set(games.map((g) => g.status))).sort(), [games]);

  const filteredGames = games.filter((game) => {
    const matchesTeam = filters.team ? game.home.abbr === filters.team || game.away.abbr === filters.team : true;
    const matchesStatus = filters.status ? game.status === filters.status : true;
    return matchesTeam && matchesStatus;
  });

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-4">
        <label className="flex items-center gap-2 text-sm text-white/60">
          Team
          <select
            value={filters.team ?? ""}
            onChange={(event) => onFiltersChange({ ...filters, team: event.target.value || undefined })}
          >
            <option value="">All</option>
            {teams.map((team) => (
              <option key={team} value={team}>
                {team}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-white/60">
          Status
          <select
            value={filters.status ?? ""}
            onChange={(event) => onFiltersChange({ ...filters, status: event.target.value || undefined })}
          >
            <option value="">All</option>
            {statuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {filteredGames.map((game) => {
          const isSelected = game.id === selectedGameId;
          const homeAvg = averageRating(game.home.ratings);
          const awayAvg = averageRating(game.away.ratings);
          return (
            <button
              key={game.id}
              type="button"
              onClick={() => onSelect(game.id)}
              className={clsx(
                "card flex flex-col gap-2 p-4 text-left transition",
                isSelected ? "border-accent shadow-accent/30" : "hover:border-accent/60"
              )}
            >
              <div className="text-xs text-white/60">{new Date(game.startTime).toLocaleString()}</div>
              <div className="text-lg font-semibold">
                {game.away.abbr} @ {game.home.abbr}
              </div>
              <div className="text-xs text-white/50">
                Ratings: {game.away.abbr} {awayAvg.toFixed(1)} • {game.home.abbr} {homeAvg.toFixed(1)}
              </div>
              <div className="mt-2 text-xs uppercase tracking-wide text-accent">{game.status}</div>
            </button>
          );
        })}
        {filteredGames.length === 0 && (
          <div className="rounded-2xl border border-dashed border-white/10 p-8 text-center text-sm text-white/50">
            No games match the selected filters.
          </div>
        )}
      </div>
    </section>
  );
}

function averageRating(ratings: { matchupOverall: number }[]): number {
  if (ratings.length === 0) return 0;
  return ratings.reduce((acc, rating) => acc + rating.matchupOverall, 0) / ratings.length;
}
