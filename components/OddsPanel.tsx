"use client";

import type { MarketSummary } from "../lib/types";
import { formatOdds, formatPercent } from "../lib/format";

export function OddsPanel({ markets }: { markets: MarketSummary[] }) {
  return (
    <section className="card p-6">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-white/50">Market edges</h3>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {markets.map((market) => (
          <div key={market.label} className="rounded-2xl bg-white/5 p-4 text-sm text-white/70">
            <div className="text-xs uppercase tracking-wide text-white/40">{market.type}</div>
            <div className="mt-2 flex items-center justify-between gap-4">
              <div>
                <div className="text-white font-semibold">{market.label}</div>
                <div className="text-xs text-white/40">Book odds: {formatOdds(market.odds)}</div>
                <div className="text-xs text-white/40">Fair odds: {formatOdds(Math.round(market.edge.fairOdds))}</div>
              </div>
              <div className="text-right text-xs text-white/60">
                <div>Implied: {formatPercent(market.edge.marketProb, 1)}</div>
                <div>Model: {formatPercent(market.edge.trueProb, 1)}</div>
                <div className={`mt-2 inline-flex rounded-full px-2 py-1 text-[10px] uppercase ${badgeClass(market.edge.safety)}`}>
                  {market.edge.safety}
                </div>
                <div className="mt-1 text-accent">EV: {market.edge.evPct.toFixed(1)}%</div>
              </div>
            </div>
          </div>
        ))}
        {markets.length === 0 && (
          <div className="rounded-2xl border border-dashed border-white/10 p-6 text-sm text-white/40">No markets available.</div>
        )}
      </div>
    </section>
  );
}

function badgeClass(safety: string): string {
  if (safety === "safe") return "bg-emerald-500/20 text-emerald-300";
  if (safety === "risky") return "bg-red-500/20 text-red-300";
  return "bg-white/10 text-white/60";
}
