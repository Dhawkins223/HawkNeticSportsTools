"use client";

import { useMemo } from "react";
import { classForEv, formatOdds, formatPercent } from "../lib/format";
import type { PropEdge, SgpLegInput } from "../lib/types";
import { LineSparkline } from "./LineSparkline";

type PropSelection = {
  id: string;
  description: string;
  odds: number;
  leg: SgpLegInput;
};

type PropTableProps = {
  props: PropEdge[];
  selectedLegIds: string[];
  onToggleLeg: (selection: PropSelection) => void;
  gameId: number;
};

export function PropTable({ props, selectedLegIds, onToggleLeg, gameId }: PropTableProps) {
  const rows = useMemo(
    () =>
      props.map((prop) => {
        const sparkline = Array.from({ length: 12 }, (_, index) => {
          const shift = (index - 6) / 2;
          return Number((prop.projection.mean + shift).toFixed(1));
        });
        return { prop, sparkline };
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
            {rows.map(({ prop, sparkline }) => {
              const overId = `${prop.id}-over`;
              const underId = `${prop.id}-under`;
              const overSelected = selectedLegIds.includes(overId);
              const underSelected = selectedLegIds.includes(underId);
              return (
                <tr key={prop.id} className="align-top">
                  <td className="p-3">
                    <div className="text-white font-semibold">{prop.player.name}</div>
                    <div className="text-xs text-white/40">{prop.player.team} • {prop.market}</div>
                  </td>
                  <td className="p-3">
                    <div className="text-white/80">{prop.line}</div>
                    <div className="text-xs text-white/40">Mean: {prop.projection.mean.toFixed(1)}</div>
                    <div className="text-xs text-white/40">Stdev: {prop.projection.stdev.toFixed(1)}</div>
                  </td>
                  <td className="p-3">
                    <LineSparkline points={sparkline} />
                  </td>
                  <td className="p-3">
                    <PropLegCell
                      id={overId}
                      selected={overSelected}
                      odds={prop.overOdds}
                      probability={prop.over.trueProb}
                      ev={prop.over.evPct}
                      safety={prop.over.safety}
                      onToggle={() =>
                        onToggleLeg({
                          id: overId,
                          description: `${prop.player.name} over ${prop.line} ${prop.market.toLowerCase()}`,
                          odds: prop.overOdds,
                          leg: {
                            gameId,
                            playerId: prop.player.id,
                            market: prop.market,
                            line: prop.line,
                            direction: "over",
                            odds: prop.overOdds
                          }
                        })
                      }
                    />
                  </td>
                  <td className="p-3">
                    <PropLegCell
                      id={underId}
                      selected={underSelected}
                      odds={prop.underOdds}
                      probability={prop.under.trueProb}
                      ev={prop.under.evPct}
                      safety={prop.under.safety}
                      onToggle={() =>
                        onToggleLeg({
                          id: underId,
                          description: `${prop.player.name} under ${prop.line} ${prop.market.toLowerCase()}`,
                          odds: prop.underOdds,
                          leg: {
                            gameId,
                            playerId: prop.player.id,
                            market: prop.market,
                            line: prop.line,
                            direction: "under",
                            odds: prop.underOdds
                          }
                        })
                      }
                    />
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

function PropLegCell({
  id,
  selected,
  odds,
  probability,
  ev,
  safety,
  onToggle
}: {
  id: string;
  selected: boolean;
  odds: number;
  probability: number;
  ev: number;
  safety: string;
  onToggle: () => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="text-sm text-white/70">
        Odds: <span className="text-white">{formatOdds(odds)}</span>
      </div>
      <div className="text-xs text-white/40">Model prob: {formatPercent(probability)}</div>
      <div className={classForEv(ev)}>{ev.toFixed(2)}% EV ({safety})</div>
      <button
        type="button"
        className={`rounded-xl border border-white/10 px-3 py-2 text-sm transition ${
          selected ? "bg-accent/20 text-accent" : "hover:bg-white/10"
        }`}
        onClick={onToggle}
      >
        {selected ? "Remove" : "Add to slip"}
      </button>
    </div>
  );
}
