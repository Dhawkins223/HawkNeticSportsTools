"use client";

import type { Game } from "../../lib/api";
import { SPORT_FILTERS, type SportFilter } from "./useMarketData";
import { eventLabelForGame } from "./marketOptions";

type Props = {
  games: Game[];
  sport: SportFilter;
  setSport: (sport: SportFilter) => void;
  activeGameId: string | null;
  setActiveGameId: (id: string) => void;
};

export function SportsBoard({ games, sport, setSport, activeGameId, setActiveGameId }: Props) {
  return (
    <aside className="hnSportsBoard" data-testid="sports-board">
      <h2>Sports &amp; Events</h2>
      <div className="sportFilters">
        {SPORT_FILTERS.map((item) => (
          <button
            key={item}
            className={sport === item ? "active" : ""}
            onClick={() => setSport(item)}
            data-testid={`sport-filter-${item.toLowerCase()}`}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="gameList">
        {games.length ? games.map((game) => (
          <button
            type="button"
            key={game.id}
            className={activeGameId === String(game.id) ? "active" : ""}
            onClick={() => setActiveGameId(String(game.id))}
            data-testid={`game-${game.id}`}
          >
            <strong>{eventLabelForGame(game)}</strong>
            <span>{game.game_date || "Start time pending"}</span>
            <small>{game.status || "Market status pending"}</small>
          </button>
        )) : (
          <p>Not enough data available yet. You can still add a market manually for the algorithm to score.</p>
        )}
      </div>
    </aside>
  );
}
