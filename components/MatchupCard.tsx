"use client";

import type { GameDetail } from "../lib/types";
import { formatPercent } from "../lib/format";

export function MatchupCard({ game }: { game: GameDetail }) {
  const homeAvg = average(game.home.ratings.map((rating) => rating.matchupOverall));
  const awayAvg = average(game.away.ratings.map((rating) => rating.matchupOverall));
  const topHome = game.home.ratings.slice(0, 3);
  const topAway = game.away.ratings.slice(0, 3);

  return (
    <section className="card-hover flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h2 className="text-3xl font-bold text-text mb-2">
            {game.away.name} @ {game.home.name}
          </h2>
          <p className="text-sm text-textSecondary">{new Date(game.startTime).toLocaleString()}</p>
          {game.venue && <p className="text-xs text-textMuted">{game.venue}</p>}
          <p className="mt-2 text-sm text-textSecondary">Status: <span className="text-accent font-semibold">{game.status}</span></p>
        </div>
        <div className="card p-4 text-right text-sm">
          <div className="text-textSecondary mb-1">{game.away.abbr} avg rating</div>
          <div className="text-2xl font-bold text-accent">{awayAvg.toFixed(1)}</div>
          <div className="text-textSecondary mt-3 mb-1">{game.home.abbr} avg rating</div>
          <div className="text-2xl font-bold text-accent">{homeAvg.toFixed(1)}</div>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <RatingColumn label={`${game.away.abbr} leaders`} ratings={topAway} />
        <RatingColumn label={`${game.home.abbr} leaders`} ratings={topHome} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {game.markets.slice(0, 2).map((market) => (
          <div key={market.label} className="card p-4 border-l-4 border-l-accent">
            <div className="text-xs uppercase tracking-wide text-textMuted font-bold mb-3">{market.type.toUpperCase()}</div>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-text font-bold text-lg mb-1">{market.label}</div>
                <div className="text-xs text-textSecondary">Odds: <span className="text-accent font-semibold">{market.odds > 0 ? `+${market.odds}` : market.odds}</span></div>
              </div>
              <div className="text-right">
                <div className="text-xs text-textSecondary mb-1">Model: <span className="text-text font-semibold">{formatPercent(market.edge.trueProb, 1)}</span></div>
                <div className="text-xs text-textSecondary mb-1">EV: <span className={`font-bold ${market.edge.evPct > 0 ? 'text-positive' : 'text-negative'}`}>{market.edge.evPct.toFixed(1)}%</span></div>
                <div className="mt-2">
                  <span className={`badge-${market.edge.safety === 'safe' ? 'positive' : 'negative'}`}>
                    {market.edge.safety}
                  </span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function average(values: number[]): number {
  if (!values.length) return 0;
  return values.reduce((acc, value) => acc + value, 0) / values.length;
}

function RatingColumn({
  label,
  ratings
}: {
  label: string;
  ratings: Array<{ playerName: string; matchupOverall: number; offense: number; defense: number; playmaking: number }>;
}) {
  return (
    <div className="card p-4">
      <div className="text-xs uppercase tracking-wide text-textMuted font-bold mb-3">{label}</div>
      <ul className="space-y-2">
        {ratings.map((rating) => (
          <li key={rating.playerName} className="bg-surface2/50 border border-border rounded-lg px-3 py-2.5 hover:border-borderHover transition-colors">
            <div className="text-text font-bold mb-1">{rating.playerName}</div>
            <div className="text-xs text-textSecondary">
              Overall <span className="text-accent font-semibold">{rating.matchupOverall.toFixed(1)}</span> • 
              Off {rating.offense.toFixed(1)} • 
              Def {rating.defense.toFixed(1)} • 
              Play {rating.playmaking.toFixed(1)}
            </div>
          </li>
        ))}
        {ratings.length === 0 && <li className="text-xs text-textMuted">No ratings available.</li>}
      </ul>
    </div>
  );
}
