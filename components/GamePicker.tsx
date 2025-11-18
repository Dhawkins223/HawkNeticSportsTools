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
      <div className="card p-4">
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-sm text-textSecondary">
            Team
            <select
              value={filters.team ?? ""}
              onChange={(event) => onFiltersChange({ ...filters, team: event.target.value || undefined })}
              className="bg-surface2 border border-border rounded-lg px-3 py-2 text-text focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="">All</option>
              {teams.map((team) => (
                <option key={team} value={team}>
                  {team}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-textSecondary">
            Status
            <select
              value={filters.status ?? ""}
              onChange={(event) => onFiltersChange({ ...filters, status: event.target.value || undefined })}
              className="bg-surface2 border border-border rounded-lg px-3 py-2 text-text focus:outline-none focus:ring-2 focus:ring-accent"
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
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
                "card-hover flex flex-col gap-3 p-5 text-left transition-all",
                isSelected ? "border-2 border-accent shadow-lg shadow-accent/20" : ""
              )}
            >
              <div className="text-xs text-textMuted uppercase tracking-wide">{new Date(game.startTime).toLocaleString()}</div>
              <div className="text-xl font-bold text-text">
                {game.away.abbr} @ {game.home.abbr}
              </div>
              <div className="flex items-center justify-between text-xs">
                <div className="text-textSecondary">
                  <span className="font-semibold text-text">{game.away.abbr}</span> {awayAvg.toFixed(1)}
                </div>
                <div className="text-textMuted">•</div>
                <div className="text-textSecondary">
                  <span className="font-semibold text-text">{game.home.abbr}</span> {homeAvg.toFixed(1)}
                </div>
              </div>
              <div className="mt-1">
                <span className="badge-positive text-xs">{game.status}</span>
              </div>
            </button>
          );
        })}
        {filteredGames.length === 0 && (
          <div className="col-span-full card border border-dashed border-border p-8 text-center text-sm text-textMuted">
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
