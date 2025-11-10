"use client";

import { useMemo, useState } from "react";
import type { GameDetail } from "../lib/types";
import { formatPercent } from "../lib/format";

export function WhyDrawer({ game }: { game: GameDetail }) {
  const [open, setOpen] = useState(false);

  const insights = useMemo(() => {
    const avgHome = average(game.home.ratings.map((rating) => rating.matchupOverall));
    const avgAway = average(game.away.ratings.map((rating) => rating.matchupOverall));
    const safest = [...game.markets].sort((a, b) => b.edge.evPct - a.edge.evPct)[0];
    const injuries = game.home.ratings.concat(game.away.ratings).filter((rating) => rating.fatigue > 0.6);
    return {
      avgHome,
      avgAway,
      safest,
      fatigueNotes: injuries.slice(0, 4).map((rating) => `${rating.playerName} fatigue ${formatPercent(rating.fatigue)}`)
    };
  }, [game]);

  return (
    <section className="card p-6">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between text-left text-sm font-semibold text-accent"
      >
        <span>Why does the model like this angle?</span>
        <span>{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="mt-4 space-y-4 text-sm text-white/70">
          <div>
            <h4 className="text-xs uppercase tracking-wide text-white/40">Matchup ratings</h4>
            <p>
              {game.away.abbr} average matchup overall {insights.avgAway.toFixed(1)} vs {game.home.abbr} average {insights.avgHome.toFixed(1)}.
              Rating delta feeds the market edge calculations.
            </p>
          </div>
          {insights.safest && (
            <div>
              <h4 className="text-xs uppercase tracking-wide text-white/40">Top opportunity</h4>
              <p>
                Highest EV market: <span className="text-white">{insights.safest.label}</span> ({insights.safest.edge.evPct.toFixed(1)}% edge,
                model probability {formatPercent(insights.safest.edge.trueProb)}).
              </p>
            </div>
          )}
          {insights.fatigueNotes.length > 0 && (
            <div>
              <h4 className="text-xs uppercase tracking-wide text-white/40">Fatigue factors</h4>
              <ul className="mt-2 space-y-1">
                {insights.fatigueNotes.map((note) => (
                  <li key={note} className="rounded-xl bg-white/5 px-3 py-2">
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function average(values: number[]): number {
  if (!values.length) return 0;
  return values.reduce((acc, value) => acc + value, 0) / values.length;
}
