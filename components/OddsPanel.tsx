"use client";

import type { GameOdds } from "../lib/types";
import { americanToImpliedProbability, formatOdds, formatPercent } from "../lib/format";

export function OddsPanel({ odds }: { odds: GameOdds }) {
  const rows = [
    {
      label: "Moneyline",
      items: [
        { label: "Home", value: odds.moneylineHome },
        { label: "Away", value: odds.moneylineAway }
      ]
    },
    {
      label: "Spread",
      items: [
        { label: `Home ${odds.spread}`, value: odds.spreadHome },
        { label: `Away ${-odds.spread}`, value: odds.spreadAway }
      ]
    },
    {
      label: "Total",
      items: [
        { label: `Over ${odds.total}`, value: odds.over },
        { label: `Under ${odds.total}`, value: odds.under }
      ]
    }
  ];

  return (
    <section className="card p-6">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-white/50">Market odds</h3>
      <div className="mt-4 space-y-4 text-sm">
        {rows.map((row) => (
          <div key={row.label} className="rounded-xl bg-white/5 p-4">
            <div className="text-xs uppercase tracking-wide text-white/50">{row.label}</div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {row.items.map((item) => {
                const implied = americanToImpliedProbability(item.value);
                return (
                  <div key={item.label} className="flex items-center justify-between">
                    <div>
                      <div className="text-white/80">{item.label}</div>
                      <div className="text-xs text-white/40">Implied: {formatPercent(implied)}</div>
                    </div>
                    <div className="text-lg font-semibold text-accent">{formatOdds(item.value)}</div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
