"use client";

import type { ReactElement } from "react";

const BOLD_FONT_WEIGHT = 700;
const SEMI_BOLD_FONT_WEIGHT = 600;

export type ComparisonRow = readonly [string, boolean, boolean, boolean, boolean, boolean];

const COMPARISON_ROWS: readonly ComparisonRow[] = [
  ["Real Monte Carlo simulation (≥10k runs)", true, false, false, false, true],
  ["Same-game correlation matrix (per pair)", true, false, false, false, false],
  ["No-vig edge per leg", true, false, false, true, true],
  ["Kelly fraction recommendation", true, false, false, false, true],
  ["95% confidence interval per probability", true, false, false, false, false],
  ["Trap-leg detection with explanations", true, false, false, false, false],
  ["Live freshness gating (blocks stale data)", true, false, false, false, false],
  ["Multi-sport (NBA + NFL + MLB + NHL + Soccer + Golf)", true, true, true, true, true],
  ["Saved slips & history", true, false, false, true, true],
  ["Decision-support (does NOT accept wagers)", true, false, false, true, true],
];

const COMPETITORS: readonly string[] = ["HawkneticSports", "PrizePicks", "Underdog", "Action Network", "OddsJam"];

function check(value: boolean): ReactElement {
  if (value) {
    return <span aria-label="yes" style={{ color: "#d8f63a", fontWeight: BOLD_FONT_WEIGHT }}>✓</span>;
  }
  return <span aria-label="no" style={{ opacity: 0.35 }}>—</span>;
}

function HeaderRow() {
  return (
    <tr>
      <th style={{ textAlign: "left", padding: "0.6rem 0.4rem", fontWeight: SEMI_BOLD_FONT_WEIGHT, color: "#d8f63a" }}>Capability</th>
      {COMPETITORS.map((name) => (
        <th
          key={name}
          style={{
            textAlign: "center",
            padding: "0.6rem 0.4rem",
            fontWeight: SEMI_BOLD_FONT_WEIGHT,
            color: name === "HawkneticSports" ? "#d8f63a" : "rgba(255,255,255,0.7)",
          }}
        >
          {name}
        </th>
      ))}
    </tr>
  );
}

function BodyRow({ row, isFirst }: { row: ComparisonRow; isFirst: boolean }) {
  const borderTop = isFirst ? "1px solid rgba(255,255,255,0.08)" : "1px solid rgba(255,255,255,0.04)";
  return (
    <tr style={{ borderTop }}>
      <td style={{ padding: "0.5rem 0.4rem", opacity: 0.85 }}>{row[0]}</td>
      {row.slice(1).map((value, vIdx) => (
        <td key={COMPETITORS[vIdx]} style={{ textAlign: "center", padding: "0.5rem 0.4rem" }}>{check(Boolean(value))}</td>
      ))}
    </tr>
  );
}

export function CompetitorComparison() {
  return (
    <section
      data-testid="competitor-comparison"
      style={{ background: "rgba(0,0,0,0.4)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "18px", padding: "1.8rem", marginBottom: "2.5rem", overflowX: "auto" }}
    >
      <h2 style={{ margin: "0 0 0.4rem", fontSize: "1.4rem" }}>How HawkneticSports compares</h2>
      <p style={{ margin: "0 0 1.5rem", opacity: 0.65, fontSize: "0.9rem" }}>What other tools surface vs. what we surface for every algorithm run.</p>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
        <thead><HeaderRow /></thead>
        <tbody>
          {COMPARISON_ROWS.map((row, idx) => (
            <BodyRow key={String(row[0])} row={row} isFirst={idx === 0} />
          ))}
        </tbody>
      </table>
      <p style={{ margin: "1.2rem 0 0", fontSize: "0.78rem", opacity: 0.55 }}>
        Capability matrix based on publicly documented features as of Jan 2026. PrizePicks &amp; Underdog operate as DFS pick’em platforms; Action Network is a research/tracking app; OddsJam focuses on +EV / arbitrage scanning. HawkneticSports is the only one of these tools that exposes the simulation-based correlation matrix and confidence interval per leg.
      </p>
    </section>
  );
}
