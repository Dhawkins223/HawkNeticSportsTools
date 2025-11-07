"use client";

import { useState } from "react";
import type { Game } from "../lib/types";

export function WhyDrawer({ game }: { game: Game }) {
  const [open, setOpen] = useState(false);

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
            <h4 className="text-xs uppercase tracking-wide text-white/40">Injury inputs</h4>
            <ul className="mt-2 space-y-1">
              {game.model.injuryReport.map((note) => (
                <li key={note} className="rounded-xl bg-white/5 px-3 py-2">
                  {note}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-xs uppercase tracking-wide text-white/40">Travel fatigue</h4>
            <p className="mt-2">
              {Object.entries(game.model.travelFatigue)
                .map(([team, score]) => `${team}: ${(score * 100).toFixed(0)}% fatigue penalty`)
                .join(" • ")}
            </p>
          </div>
          <div>
            <h4 className="text-xs uppercase tracking-wide text-white/40">Pace + blowout risk</h4>
            <p className="mt-2">
              Modeled pace is <span className="text-white">{game.model.pace.toFixed(1)}</span> possessions with a blowout
              risk of <span className="text-white">{(game.model.blowoutRisk * 100).toFixed(0)}%</span>. Pace adjustments
              feed into prop distributions while blowout risk discounts late-game usage.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
