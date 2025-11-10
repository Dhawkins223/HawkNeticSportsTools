"use client";

import { useMemo } from "react";
import { classForEv, formatOdds, formatPercent } from "../lib/format";
import type { SgpLegInput, SgpSimulationResponse } from "../lib/types";

type Selection = {
  id: string;
  description: string;
  odds: number;
  leg: SgpLegInput;
};

type BetSlipProps = {
  legs: Selection[];
  stake: number;
  onStakeChange: (value: number) => void;
  onRemoveLeg: (id: string) => void;
  simulation?: SgpSimulationResponse | null;
};

export function BetSlip({ legs, stake, onStakeChange, onRemoveLeg, simulation }: BetSlipProps) {
  const combined = useMemo(() => computeCombinedOdds(legs), [legs]);
  const payout = combined.decimal ? combined.decimal * stake : 0;
  return (
    <section className="card flex flex-col gap-4 p-6">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-white/60">Bet slip</h3>
      <div className="space-y-3 text-sm text-white/70">
        {legs.map((leg) => (
          <div key={leg.id} className="flex items-center justify-between rounded-xl bg-white/5 px-3 py-2">
            <div>
              <div className="text-white">{leg.description}</div>
              <div className="text-xs text-white/40">Odds: {formatOdds(leg.odds)}</div>
            </div>
            <button
              type="button"
              onClick={() => onRemoveLeg(leg.id)}
              className="text-xs text-red-400 hover:text-red-300"
            >
              Remove
            </button>
          </div>
        ))}
        {legs.length === 0 && <p className="text-sm text-white/40">No selections yet.</p>}
      </div>
      <label className="text-sm text-white/60">
        Stake
        <input
          type="number"
          min={0}
          value={stake}
          onChange={(event) => onStakeChange(Number(event.target.value))}
          className="mt-2 w-full"
        />
      </label>
      <div className="rounded-2xl bg-white/5 p-4 text-sm text-white/70">
        <div>Combined decimal odds: <span className="text-white">{combined.decimal.toFixed(2)}</span></div>
        <div>Combined American odds: <span className="text-white">{formatOdds(combined.american)}</span></div>
        <div>Potential payout: <span className="text-white">{payout.toFixed(2)}</span></div>
        {simulation && (
          <div className="mt-2 space-y-1 text-xs text-white/60">
            <div>Joint probability: <span className="text-white">{formatPercent(simulation.jointProb, 2)}</span></div>
            <div>Model EV: <span className={classForEv(simulation.evPct)}>{simulation.evPct.toFixed(2)}%</span></div>
            <div>Fractional Kelly stake: <span className="text-white">{(simulation.kellyFraction * 100).toFixed(2)}%</span></div>
          </div>
        )}
      </div>
    </section>
  );
}

function computeCombinedOdds(legs: Selection[]): { decimal: number; american: number } {
  if (legs.length === 0) return { decimal: 0, american: 0 };
  const decimal = legs.reduce((acc, leg) => acc * toDecimal(leg.odds), 1);
  return { decimal, american: toAmerican(decimal) };
}

function toDecimal(odds: number): number {
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}

function toAmerican(decimal: number): number {
  if (decimal <= 1) return 0;
  if (decimal >= 2) {
    return Math.round((decimal - 1) * 100);
  }
  return Math.round(-100 / (decimal - 1));
}
