"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import toast from "react-hot-toast";
import { runSimulation } from "../lib/api";
import type { SgpLegInput, SgpSimulationResponse } from "../lib/types";
import { classForEv, formatOdds, formatPercent } from "../lib/format";

type Selection = {
  id: string;
  description: string;
  odds: number;
  leg: SgpLegInput;
};

type SgpComposerProps = {
  legs: Selection[];
  onSimulated?: (response: SgpSimulationResponse) => void;
};

export function SgpComposer({ legs, onSimulated }: SgpComposerProps) {
  const offeredOdds = useMemo(() => computeCombinedAmerican(legs), [legs]);

  const mutation = useMutation({
    mutationFn: () => runSimulation(legs.map((leg) => leg.leg), offeredOdds),
    onSuccess: (data) => {
      toast.success("Simulation complete");
      onSimulated?.(data);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    }
  });

  useEffect(() => {
    if (legs.length === 0) {
      mutation.reset();
    }
  }, [legs, mutation]);

  return (
    <section className="card-hover flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between border-b border-border pb-4">
        <h3 className="text-lg font-bold uppercase tracking-wide text-text">Same-Game Parlay Composer</h3>
        <button
          type="button"
          disabled={legs.length === 0 || mutation.isLoading || offeredOdds === 0}
          onClick={() => mutation.mutate()}
          className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-accent"
        >
          {mutation.isLoading ? "Running..." : "Run Simulation"}
        </button>
      </div>
      <ul className="space-y-3">
        {legs.map((leg) => (
          <li key={leg.id} className="card flex items-center justify-between p-4 border-l-4 border-l-accent">
            <span className="text-text font-semibold">{leg.description}</span>
            <span className="text-accent font-bold text-lg">{leg.odds > 0 ? `+${leg.odds}` : leg.odds}</span>
          </li>
        ))}
        {legs.length === 0 && (
          <div className="card border border-dashed border-border p-6 text-center text-sm text-textMuted">
            Select props to build a ticket.
          </div>
        )}
      </ul>
      {mutation.data && (
        <div className="card p-5 bg-gradient-to-br from-surface to-surface2 border-2 border-accent/30">
          <div className="text-xs uppercase tracking-wide text-textMuted font-bold mb-4">Joint Outcome</div>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-textSecondary">Joint probability:</span>
              <span className="text-text font-bold text-lg">{formatPercent(mutation.data.jointProb, 2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-textSecondary">Model EV:</span>
              <span className={`font-bold ${mutation.data.evPct > 0 ? 'text-positive' : 'text-negative'}`}>
                {mutation.data.evPct > 0 ? '+' : ''}{mutation.data.evPct.toFixed(2)}%
              </span>
            </div>
            <div className="flex justify-between pt-2 border-t border-border">
              <span className="text-textSecondary">Suggested Kelly stake:</span>
              <span className="text-text font-semibold">{(mutation.data.kellyFraction * 100).toFixed(2)}%</span>
            </div>
          </div>
        </div>
      )}
      {legs.length > 0 && (
        <div className="card p-4">
          <div className="text-sm text-textSecondary">
            Combined offered odds: <span className="text-accent font-bold text-lg ml-2">{formatOdds(offeredOdds)}</span>
          </div>
        </div>
      )}
    </section>
  );
}

function computeCombinedAmerican(legs: Selection[]): number {
  if (legs.length === 0) return 0;
  const decimal = legs.reduce((acc, leg) => acc * (leg.odds > 0 ? 1 + leg.odds / 100 : 1 + 100 / Math.abs(leg.odds)), 1);
  if (decimal <= 1) return 0;
  if (decimal >= 2) {
    return Math.round((decimal - 1) * 100);
  }
  return Math.round(-100 / (decimal - 1));
}
