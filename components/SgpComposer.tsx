"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect } from "react";
import toast from "react-hot-toast";
import { runSimulation } from "../lib/api";
import type { SimulationResponse } from "../lib/types";
import { classForEv, formatPercent } from "../lib/format";

type Leg = {
  id: string;
  description: string;
  odds: number;
};

type SgpComposerProps = {
  legs: Leg[];
  onSimulated?: (response: SimulationResponse) => void;
};

export function SgpComposer({ legs, onSimulated }: SgpComposerProps) {
  const mutation = useMutation({
    mutationFn: runSimulation,
    onSuccess: (data) => {
      toast.success("Simulation complete using joint probability");
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
          disabled={legs.length === 0 || mutation.isLoading}
          onClick={() => mutation.mutate(legs)}
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
              <span className="text-lg font-semibold text-white">{formatPercent(mutation.data.joint.p_joint, 2)}</span>
            </div>
            <div>
              <span className="text-white/60">Model EV (stake 100): </span>
              <span className={classForEv(mutation.data.joint.ev)}>EV: {mutation.data.joint.ev.toFixed(2)}</span>
            </div>
            <p className="text-xs text-white/40">
              We never multiply individual leg probabilities. Joint probability is delivered directly from the
              simulation endpoint.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
