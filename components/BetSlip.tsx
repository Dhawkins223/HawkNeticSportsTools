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
    <section className="card-hover flex flex-col gap-6 p-6">
      <h3 className="text-lg font-bold uppercase tracking-wide text-text border-b border-border pb-3">Bet Slip</h3>
      <div className="space-y-3">
        {legs.map((leg) => (
          <div key={leg.id} className="card flex items-center justify-between p-4 border-l-4 border-l-accent">
            <div className="flex-1">
              <div className="text-text font-semibold mb-1">{leg.description}</div>
              <div className="text-xs text-textSecondary">Odds: <span className="text-accent font-bold">{formatOdds(leg.odds)}</span></div>
            </div>
            <button
              type="button"
              onClick={() => onRemoveLeg(leg.id)}
              className="text-xs text-negative hover:text-negative/80 font-semibold px-3 py-1 rounded hover:bg-negative/10 transition-colors"
            >
              ✕
            </button>
          </div>
        ))}
        {legs.length === 0 && (
          <div className="card border border-dashed border-border p-6 text-center text-sm text-textMuted">
            No selections yet.
          </div>
        )}
      </div>
      <label className="text-sm text-textSecondary font-semibold">
        Stake ($)
        <input
          type="number"
          min={0}
          value={stake}
          onChange={(event) => onStakeChange(Number(event.target.value))}
          className="mt-2 w-full"
        />
      </label>
      <div className="card p-5 bg-gradient-to-br from-surface to-surface2 border-2 border-accent/30">
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-textSecondary">Combined decimal odds:</span>
            <span className="text-text font-bold">{combined.decimal.toFixed(2)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-textSecondary">Combined American odds:</span>
            <span className="text-accent font-bold">{formatOdds(combined.american)}</span>
          </div>
          <div className="flex justify-between pt-2 border-t border-border">
            <span className="text-textSecondary font-semibold">Potential payout:</span>
            <span className="text-positive font-bold text-lg">${payout.toFixed(2)}</span>
          </div>
        </div>
        {simulation && (
          <div className="mt-4 pt-4 border-t border-border space-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-textSecondary">Joint probability:</span>
              <span className="text-text font-semibold">{formatPercent(simulation.jointProb, 2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-textSecondary">Model EV:</span>
              <span className={classForEv(simulation.evPct)}>{simulation.evPct > 0 ? '+' : ''}{simulation.evPct.toFixed(2)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-textSecondary">Fractional Kelly stake:</span>
              <span className="text-text font-semibold">{(simulation.kellyFraction * 100).toFixed(2)}%</span>
            </div>
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
