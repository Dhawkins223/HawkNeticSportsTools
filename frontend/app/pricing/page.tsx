"use client";

import Link from "next/link";

type PricingPlan = {
  name: string;
  price: string;
  cadence: string;
  features: readonly string[];
  cta: { href: string; label: string; testid: string };
  accent?: boolean;
};

type ComparisonRow = readonly [string, boolean, boolean, boolean, boolean, boolean];

const PLANS: readonly PricingPlan[] = [
  {
    name: "Free",
    price: "$0",
    cadence: "/forever",
    features: ["3 algorithm runs/day", "NBA + NFL only", "Basic verdict", "3 saved slips"],
    cta: { href: "/signup", label: "Start free", testid: "plan-free-cta" },
  },
  {
    name: "Pro",
    price: "$19",
    cadence: "/month",
    features: ["50 runs/day", "All sports (NBA · NFL · MLB · NHL · Soccer · Golf)", "Full EV / edge / Kelly", "50 saved slips", "Live readiness alerts", "Same-game correlation matrix"],
    cta: { href: "/signup?plan=pro", label: "Start Pro", testid: "plan-pro-cta" },
    accent: true,
  },
  {
    name: "Premium",
    price: "$49",
    cadence: "/month",
    features: ["250+ runs/day", "Advanced 25k Monte Carlo runs", "Line-movement intel", "Correlation matrix exports", "+EV scanner across all books", "Priority support"],
    cta: { href: "/signup?plan=premium", label: "Start Premium", testid: "plan-premium-cta" },
  },
];

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

function check(value: boolean): React.ReactElement {
  return value
    ? <span aria-label="yes" style={{ color: "#d8f63a", fontWeight: 700 }}>✓</span>
    : <span aria-label="no" style={{ opacity: 0.35 }}>—</span>;
}

export default function PricingPage() {
  return (
    <main style={{ minHeight: "100vh", padding: "3rem 1.5rem 4rem", maxWidth: "1100px", margin: "0 auto" }} data-testid="pricing-page">
      <header style={{ textAlign: "center", marginBottom: "2.5rem" }}>
        <p style={{ fontSize: "0.7rem", letterSpacing: "0.2em", color: "#d8f63a", margin: 0 }}>HAWKNETICSPORTS · PRICING</p>
        <h1 style={{ margin: "0.4rem 0", fontSize: "2.4rem" }}>Run the algorithm. Decide smarter.</h1>
        <p style={{ opacity: 0.7, maxWidth: "62ch", margin: "0 auto" }}>HawkneticSports provides sports analytics and betting-decision support. It does not accept wagers, place bets, or guarantee outcomes.</p>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1.5rem", marginBottom: "3.5rem" }}>
        {PLANS.map((plan) => (
          <article key={plan.name} data-testid={`plan-${plan.name.toLowerCase()}`} style={{ padding: "1.8rem 1.6rem", borderRadius: "16px", border: plan.accent ? "1px solid #d8f63a" : "1px solid rgba(255,255,255,0.14)", background: plan.accent ? "rgba(216,246,58,0.06)" : "rgba(255,255,255,0.04)" }}>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{plan.name}</h2>
            <p style={{ margin: "0.6rem 0 1rem", fontSize: "2rem", fontWeight: 700 }}>{plan.price}<span style={{ fontSize: "0.85rem", opacity: 0.6, fontWeight: 400 }}>{plan.cadence}</span></p>
            <ul style={{ listStyle: "none", padding: 0, margin: "0 0 1.5rem", display: "grid", gap: "0.5rem", fontSize: "0.88rem", opacity: 0.85 }}>
              {plan.features.map((f) => <li key={f}>· {f}</li>)}
            </ul>
            <Link href={plan.cta.href} data-testid={plan.cta.testid} style={{ display: "block", textAlign: "center", padding: "0.7rem 1rem", borderRadius: "999px", textDecoration: "none", fontWeight: 600, background: plan.accent ? "#d8f63a" : "rgba(255,255,255,0.12)", color: plan.accent ? "#0b1606" : "inherit" }}>
              {plan.cta.label}
            </Link>
          </article>
        ))}
      </div>

      <section data-testid="competitor-comparison" style={{ background: "rgba(0,0,0,0.4)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "18px", padding: "1.8rem", marginBottom: "2.5rem", overflowX: "auto" }}>
        <h2 style={{ margin: "0 0 0.4rem", fontSize: "1.4rem" }}>How HawkneticSports compares</h2>
        <p style={{ margin: "0 0 1.5rem", opacity: 0.65, fontSize: "0.9rem" }}>What other tools surface vs. what we surface for every algorithm run.</p>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "0.6rem 0.4rem", fontWeight: 600, color: "#d8f63a" }}>Capability</th>
              {COMPETITORS.map((name) => (
                <th key={name} style={{ textAlign: "center", padding: "0.6rem 0.4rem", fontWeight: 600, color: name === "HawkneticSports" ? "#d8f63a" : "rgba(255,255,255,0.7)" }}>
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {COMPARISON_ROWS.map((row, idx) => (
              <tr key={String(row[0])} style={{ borderTop: idx === 0 ? "1px solid rgba(255,255,255,0.08)" : "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "0.5rem 0.4rem", opacity: 0.85 }}>{row[0]}</td>
                {row.slice(1).map((value, vIdx) => (
                  <td key={COMPETITORS[vIdx]} style={{ textAlign: "center", padding: "0.5rem 0.4rem" }}>{check(Boolean(value))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p style={{ margin: "1.2rem 0 0", fontSize: "0.78rem", opacity: 0.55 }}>
          Capability matrix based on publicly documented features as of Jan 2026. PrizePicks &amp; Underdog operate as DFS pick’em platforms; Action Network is a research/tracking app; OddsJam focuses on +EV / arbitrage scanning. HawkneticSports is the only one of these tools that exposes the simulation-based correlation matrix and confidence interval per leg.
        </p>
      </section>

      <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.78rem", opacity: 0.55 }}>
        Stripe checkout integration ships once you provide STRIPE_SECRET_KEY + STRIPE_PRICE_ID_PRO + STRIPE_PRICE_ID_PREMIUM. The plan and webhook tables are already in place.
      </p>
    </main>
  );
}
