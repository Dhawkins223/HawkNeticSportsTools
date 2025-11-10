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
    <section className="card flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-white/60">Same-game parlay composer</h3>
        <button
          type="button"
          disabled={legs.length === 0 || mutation.isLoading || offeredOdds === 0}
          onClick={() => mutation.mutate()}
          className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-black transition hover:bg-accent/80 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/40"
        >
          {mutation.isLoading ? "Running..." : "Run simulation"}
        </button>
      </div>
      <ul className="space-y-3 text-sm text-white/70">
        {legs.map((leg) => (
          <li key={leg.id} className="flex items-center justify-between rounded-xl bg-white/5 px-3 py-2">
            <span>{leg.description}</span>
            <span className="text-accent">{leg.odds > 0 ? `+${leg.odds}` : leg.odds}</span>
          </li>
        ))}
        {legs.length === 0 && <p className="text-sm text-white/40">Select props to build a ticket.</p>}
      </ul>
      {mutation.data && (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/70">
          <div className="text-xs uppercase tracking-wide text-white/40">Joint outcome</div>
          <div className="mt-2 flex flex-col gap-2">
            <div>
              <span className="text-white/60">Joint probability: </span>
              <span className="text-lg font-semibold text-white">{formatPercent(mutation.data.jointProb, 2)}</span>
            </div>
            <div>
              <span className="text-white/60">Model EV: </span>
              <span className={classForEv(mutation.data.evPct)}>{mutation.data.evPct.toFixed(2)}%</span>
            </div>
            <div className="text-xs text-white/40">Suggested Kelly stake: {(mutation.data.kellyFraction * 100).toFixed(2)}%</div>
          </div>
        </div>
      )}
      {legs.length > 0 && (
        <div className="rounded-2xl bg-white/5 p-4 text-xs text-white/50">
          Combined offered odds: <span className="text-white">{formatOdds(offeredOdds)}</span>
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
