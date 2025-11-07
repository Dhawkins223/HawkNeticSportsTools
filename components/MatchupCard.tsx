"use client";

import type { Game } from "../lib/types";

export function MatchupCard({ game }: { game: Game }) {
  return (
    <section className="card flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">
            {game.awayTeam.name} @ {game.homeTeam.name}
          </h2>
          <p className="text-sm text-white/60">{new Date(game.date).toLocaleString()}</p>
          <p className="mt-2 text-sm text-white/50">Status: {game.status}</p>
        </div>
        <div className="flex gap-3 text-sm text-white/70">
          <div className="rounded-xl bg-white/5 px-3 py-2">
            Away record: {game.awayTeam.record}
          </div>
          <div className="rounded-xl bg-white/5 px-3 py-2">
            Home record: {game.homeTeam.record}
          </div>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-2xl bg-white/5 p-4 text-sm text-white/70">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/60">Travel fatigue</h3>
          {Object.entries(game.model.travelFatigue).map(([team, score]) => (
            <div key={team} className="flex items-center justify-between">
              <span>{team}</span>
              <span>{Math.round(score * 100)}%</span>
            </div>
          ))}
        </div>
        <div className="rounded-2xl bg-white/5 p-4 text-sm text-white/70">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/60">Injury report</h3>
          <ul className="space-y-1">
            {game.model.injuryReport.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
      <div className="flex items-center justify-between text-sm text-white/60">
        <span>Pace projection: <strong className="text-white">{game.model.pace.toFixed(1)}</strong></span>
        <span>Blowout risk: <strong className="text-white">{(game.model.blowoutRisk * 100).toFixed(0)}%</strong></span>
      </div>
    </section>
  );
}
