"use client";

import { useMemo } from "react";
import { classForEv, expectedValue, formatOdds, formatPercent } from "../lib/format";

type Leg = {
  id: string;
  description: string;
  odds: number;
};

type BetSlipProps = {
  legs: Leg[];
  stake: number;
  onStakeChange: (value: number) => void;
  onRemoveLeg: (id: string) => void;
  jointProbability?: number;
};

export function BetSlip({ legs, stake, onStakeChange, onRemoveLeg, jointProbability }: BetSlipProps) {
  const combinedDecimal = useMemo(() => {
    if (legs.length === 0) return 0;
    return legs.reduce((acc, leg) => {
      const decimal = leg.odds > 0 ? leg.odds / 100 + 1 : 100 / -leg.odds + 1;
      return acc * decimal;
    }, 1);
  }, [legs]);

  const implied = useMemo(() => {
    if (!jointProbability || jointProbability <= 0) return undefined;
    return jointProbability;
  }, [jointProbability]);

  const payout = combinedDecimal ? combinedDecimal * stake : 0;
  const ev = implied ? expectedValue({ odds: Math.round((combinedDecimal - 1) * 100), probability: implied, stake }) : 0;

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
        <div>Combined decimal odds: <span className="text-white">{combinedDecimal.toFixed(2)}</span></div>
        <div>Potential payout: <span className="text-white">{payout.toFixed(2)}</span></div>
        {implied && (
          <div>
            Joint probability (from API): <span className="text-white">{formatPercent(implied, 2)}</span>
          </div>
        )}
        {implied && <div className={classForEv(ev)}>EV: {ev.toFixed(2)}</div>}
      </div>
    </section>
  );
}
