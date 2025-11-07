"use client";

import { formatOdds, classForEv } from "../lib/format";
import type { Ticket } from "../lib/types";

export function EvTable({ tickets }: { tickets: Ticket[] }) {
  return (
    <section className="card p-6">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-white/60">High EV tickets</h3>
      <div className="mt-4 overflow-x-auto text-sm">
        <table className="table-dark">
          <thead>
            <tr>
              <th className="p-3 text-left">Ticket</th>
              <th className="p-3 text-left">Legs</th>
              <th className="p-3 text-left">Odds</th>
              <th className="p-3 text-left">Stake</th>
              <th className="p-3 text-left">EV</th>
            </tr>
          </thead>
          <tbody>
            {tickets.map((ticket) => (
              <tr key={ticket.id}>
                <td className="p-3">
                  <div className="text-white font-semibold">{ticket.title}</div>
                  <div className="text-xs text-white/40">Game ID: {ticket.gameId}</div>
                </td>
                <td className="p-3">
                  <ul className="space-y-1 text-xs text-white/60">
                    {ticket.legs.map((leg) => (
                      <li key={leg.id}>
                        {leg.description} • {formatOdds(leg.odds)}
                      </li>
                    ))}
                  </ul>
                </td>
                <td className="p-3 text-white">{formatOdds(ticket.odds)}</td>
                <td className="p-3 text-white">${ticket.stake.toFixed(2)}</td>
                <td className="p-3">
                  <span className={classForEv(ticket.expectedValue)}>EV: {ticket.expectedValue.toFixed(2)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
