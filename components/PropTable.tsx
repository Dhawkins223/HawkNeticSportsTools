"use client";

import { useMemo } from "react";
import { classForEv, expectedValue, formatOdds, formatPercent } from "../lib/format";
import type { Prop } from "../lib/types";
import { LineSparkline } from "./LineSparkline";

function erf(x: number): number {
  const sign = x >= 0 ? 1 : -1;
  const absX = Math.abs(x);
  const t = 1 / (1 + 0.5 * absX);
  const tau =
    t *
    Math.exp(
      -absX * absX -
        1.26551223 +
        1.00002368 * t +
        0.37409196 * t ** 2 +
        0.09678418 * t ** 3 -
        0.18628806 * t ** 4 +
        0.27886807 * t ** 5 -
        1.13520398 * t ** 6 +
        1.48851587 * t ** 7 -
        0.82215223 * t ** 8 +
        0.17087277 * t ** 9
    );
  return sign * (1 - tau);
}

function normalCdf(x: number): number {
  return 0.5 * (1 + erf(x / Math.sqrt(2)));
}

type PropTableProps = {
  props: Prop[];
  selectedLegIds: string[];
  onToggleLeg: (leg: { id: string; description: string; odds: number }) => void;
};

export function PropTable({ props, selectedLegIds, onToggleLeg }: PropTableProps) {
  const rows = useMemo(
    () =>
      props.map((prop) => {
        const z = (prop.line - prop.modelMean) / prop.modelStdDev;
        const underProb = normalCdf(z);
        const overProb = 1 - underProb;
        const overEv = expectedValue({ odds: prop.overOdds, probability: overProb, stake: 100 });
        const underEv = expectedValue({ odds: prop.underOdds, probability: underProb, stake: 100 });
        const sparkline = Array.from({ length: 12 }, (_, index) => {
          const shift = (index - 6) / 2;
          return Number((prop.modelMean + shift).toFixed(1));
        });
        return {
          prop,
          overProb,
          underProb,
          overEv,
          underEv,
          sparkline
        };
      }),
    [props]
  );

  return (
    <section className="card p-6">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-white/60">Player props</h3>
      <div className="mt-4 overflow-x-auto">
        <table className="table-dark">
          <thead>
            <tr>
              <th className="p-3 text-left">Player</th>
              <th className="p-3 text-left">Line</th>
              <th className="p-3 text-left">Sparkline</th>
              <th className="p-3 text-left">Over</th>
              <th className="p-3 text-left">Under</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ prop, overProb, underProb, overEv, underEv, sparkline }) => {
              const overId = `${prop.id}-over`;
              const underId = `${prop.id}-under`;
              const overSelected = selectedLegIds.includes(overId);
              const underSelected = selectedLegIds.includes(underId);
              return (
                <tr key={prop.id} className="align-top">
                  <td className="p-3">
                    <div className="text-white font-semibold">{prop.player}</div>
                    <div className="text-xs text-white/40">{prop.team} • {prop.market}</div>
                  </td>
                  <td className="p-3">
                    <div className="text-white/80">{prop.line}</div>
                    <div className="text-xs text-white/40">Model mean: {prop.modelMean.toFixed(1)}</div>
                  </td>
                  <td className="p-3">
                    <LineSparkline points={sparkline} />
                  </td>
                  <td className="p-3">
                    <div className="flex flex-col gap-2">
                      <div className="text-sm text-white/70">
                        Odds: <span className="text-white">{formatOdds(prop.overOdds)}</span>
                      </div>
                      <div className="text-xs text-white/40">Model prob: {formatPercent(overProb)}</div>
                      <span className={classForEv(overEv)}>EV: {overEv.toFixed(2)}</span>
                      <button
                        type="button"
                        className={`rounded-xl border border-white/10 px-3 py-2 text-sm transition ${
                          overSelected ? "bg-accent/20 text-accent" : "hover:bg-white/10"
                        }`}
                        onClick={() =>
                          onToggleLeg({
                            id: overId,
                            description: `${prop.player} over ${prop.line} ${prop.market.toLowerCase()}`,
                            odds: prop.overOdds
                          })
                        }
                      >
                        {overSelected ? "Remove" : "Add to slip"}
                      </button>
                    </div>
                  </td>
                  <td className="p-3">
                    <div className="flex flex-col gap-2">
                      <div className="text-sm text-white/70">
                        Odds: <span className="text-white">{formatOdds(prop.underOdds)}</span>
                      </div>
                      <div className="text-xs text-white/40">Model prob: {formatPercent(underProb)}</div>
                      <span className={classForEv(underEv)}>EV: {underEv.toFixed(2)}</span>
                      <button
                        type="button"
                        className={`rounded-xl border border-white/10 px-3 py-2 text-sm transition ${
                          underSelected ? "bg-accent/20 text-accent" : "hover:bg-white/10"
                        }`}
                        onClick={() =>
                          onToggleLeg({
                            id: underId,
                            description: `${prop.player} under ${prop.line} ${prop.market.toLowerCase()}`,
                            odds: prop.underOdds
                          })
                        }
                      >
                        {underSelected ? "Remove" : "Add to slip"}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
