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
    <section className="card-hover p-6">
      <h3 className="text-lg font-bold uppercase tracking-wide text-text mb-6 border-b border-border pb-3">Player Props</h3>
      <div className="overflow-x-auto">
        <table className="table-dark">
          <thead>
            <tr>
              <th className="p-4 text-left">Player</th>
              <th className="p-4 text-left">Line</th>
              <th className="p-4 text-left">Sparkline</th>
              <th className="p-4 text-left">Over</th>
              <th className="p-4 text-left">Under</th>
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
                  <td className="p-4">
                    <div className="text-text font-bold">{prop.player.name}</div>
                    <div className="text-xs text-textMuted mt-1">{prop.player.team} • {prop.market}</div>
                  </td>
                  <td className="p-4">
                    <div className="text-text font-bold text-lg">{prop.line}</div>
                    <div className="text-xs text-textSecondary mt-1">Mean: {prop.projection.mean.toFixed(1)}</div>
                    <div className="text-xs text-textSecondary">Stdev: {prop.projection.stdev.toFixed(1)}</div>
                  </td>
                  <td className="p-4">
                    <LineSparkline points={sparkline} />
                  </td>
                  <td className="p-4">
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
                  <td className="p-4">
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
    <div className="flex flex-col gap-3">
      <div className="text-sm">
        <span className="text-textSecondary">Odds: </span>
        <span className="text-accent font-bold text-lg">{formatOdds(odds)}</span>
      </div>
      <div className="text-xs text-textSecondary">Model prob: <span className="text-text font-semibold">{formatPercent(probability)}</span></div>
      <div className={`text-xs font-semibold ${ev > 0 ? 'text-positive' : 'text-negative'}`}>
        {ev > 0 ? '+' : ''}{ev.toFixed(2)}% EV
      </div>
      <div className="mt-1">
        <span className={`badge-${safety === 'safe' ? 'positive' : 'negative'}`}>
          {safety}
        </span>
      </div>
      <button
        type="button"
        className={`odds-button ${selected ? 'active' : ''}`}
        onClick={onToggle}
      >
        {selected ? "Remove" : "Add to slip"}
      </button>
    </div>
  );
}
