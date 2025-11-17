"use client";

import type { MarketSummary } from "../lib/types";
import { formatOdds, formatPercent } from "../lib/format";

export function OddsPanel({ markets }: { markets: MarketSummary[] }) {
  return (
    <section className="card-hover p-6">
      <h3 className="text-lg font-bold uppercase tracking-wide text-text mb-6">Market Edges</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {markets.map((market) => (
          <div key={market.label} className="card p-4 border-l-4 border-l-accent hover:border-l-accentHover transition-colors">
            <div className="text-xs uppercase tracking-wide text-textMuted font-bold mb-3">{market.type}</div>
            <div className="flex items-center justify-between gap-4">
              <div className="flex-1">
                <div className="text-text font-bold text-lg mb-2">{market.label}</div>
                <div className="space-y-1 text-xs">
                  <div className="text-textSecondary">Book odds: <span className="text-accent font-semibold">{formatOdds(market.odds)}</span></div>
                  <div className="text-textSecondary">Fair odds: <span className="text-text font-semibold">{formatOdds(Math.round(market.edge.fairOdds))}</span></div>
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs text-textSecondary mb-1">Implied: <span className="text-text font-semibold">{formatPercent(market.edge.marketProb, 1)}</span></div>
                <div className="text-xs text-textSecondary mb-1">Model: <span className="text-text font-semibold">{formatPercent(market.edge.trueProb, 1)}</span></div>
                <div className="mt-2 mb-2">
                  <span className={`badge-${market.edge.safety === 'safe' ? 'positive' : 'negative'}`}>
                    {market.edge.safety}
                  </span>
                </div>
                <div className={`text-sm font-bold ${market.edge.evPct > 0 ? 'text-positive' : 'text-negative'}`}>
                  EV: {market.edge.evPct > 0 ? '+' : ''}{market.edge.evPct.toFixed(1)}%
                </div>
              </div>
            </div>
          </div>
        ))}
        {markets.length === 0 && (
          <div className="col-span-2 card border border-dashed border-border p-6 text-sm text-textMuted text-center">No markets available.</div>
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
