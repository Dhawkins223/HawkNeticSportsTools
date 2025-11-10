"use client";

import type { GameDetail } from "../lib/types";
import { formatPercent } from "../lib/format";

export function MatchupCard({ game }: { game: GameDetail }) {
  const homeAvg = average(game.home.ratings.map((rating) => rating.matchupOverall));
  const awayAvg = average(game.away.ratings.map((rating) => rating.matchupOverall));
  const topHome = game.home.ratings.slice(0, 3);
  const topAway = game.away.ratings.slice(0, 3);

  return (
    <section className="card flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">
            {game.away.name} @ {game.home.name}
          </h2>
          <p className="text-sm text-white/60">{new Date(game.startTime).toLocaleString()}</p>
          {game.venue && <p className="text-xs text-white/40">{game.venue}</p>}
          <p className="mt-2 text-sm text-white/50">Status: {game.status}</p>
        </div>
        <div className="rounded-xl bg-white/5 px-4 py-2 text-right text-sm text-white/70">
          <div>{game.away.abbr} avg rating: <span className="text-white">{awayAvg.toFixed(1)}</span></div>
          <div>{game.home.abbr} avg rating: <span className="text-white">{homeAvg.toFixed(1)}</span></div>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <RatingColumn label={`${game.away.abbr} leaders`} ratings={topAway} />
        <RatingColumn label={`${game.home.abbr} leaders`} ratings={topHome} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {game.markets.slice(0, 2).map((market) => (
          <div key={market.label} className="rounded-2xl bg-white/5 p-4 text-sm text-white/70">
            <div className="text-xs uppercase tracking-wide text-white/40">{market.type.toUpperCase()}</div>
            <div className="mt-2 flex items-center justify-between">
              <div>
                <div className="text-white font-semibold">{market.label}</div>
                <div className="text-xs text-white/40">Odds: {market.odds > 0 ? `+${market.odds}` : market.odds}</div>
              </div>
              <div className="text-right text-xs text-white/60">
                <div>Model: {formatPercent(market.edge.trueProb, 1)}</div>
                <div>EV: {market.edge.evPct.toFixed(1)}%</div>
                <div>Safety: <span className="uppercase text-accent">{market.edge.safety}</span></div>
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
    <div className="rounded-2xl bg-white/5 p-4 text-sm text-white/70">
      <div className="text-xs uppercase tracking-wide text-white/40">{label}</div>
      <ul className="mt-3 space-y-2">
        {ratings.map((rating) => (
          <li key={rating.playerName} className="rounded-xl bg-black/20 px-3 py-2">
            <div className="text-white font-semibold">{rating.playerName}</div>
            <div className="text-xs text-white/50">
              Overall {rating.matchupOverall.toFixed(1)} • Off {rating.offense.toFixed(1)} • Def {rating.defense.toFixed(1)} • Play {rating.playmaking.toFixed(1)}
            </div>
          </li>
        ))}
        {ratings.length === 0 && <li className="text-xs text-white/40">No ratings available.</li>}
      </ul>
    </div>
  );
}
