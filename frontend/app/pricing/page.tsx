"use client";

import Link from "next/link";

const PLANS = [
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
    features: ["50 runs/day", "All sports (NBA · NFL · MLB · NHL · Soccer · Golf)", "Full EV / edge / Kelly", "50 saved slips", "Live readiness alerts"],
    cta: { href: "/signup?plan=pro", label: "Start Pro", testid: "plan-pro-cta" },
    accent: true,
  },
  {
    name: "Premium",
    price: "$49",
    cadence: "/month",
    features: ["250+ runs/day", "Advanced 25k Monte Carlo runs", "Line-movement intel", "Correlation matrix exports", "Priority support"],
    cta: { href: "/signup?plan=premium", label: "Start Premium", testid: "plan-premium-cta" },
  },
];

export default function PricingPage() {
  return (
    <main style={{ minHeight: "100vh", padding: "3rem 1.5rem 4rem", maxWidth: "1100px", margin: "0 auto" }} data-testid="pricing-page">
      <header style={{ textAlign: "center", marginBottom: "2.5rem" }}>
        <p style={{ fontSize: "0.7rem", letterSpacing: "0.2em", color: "#d8f63a", margin: 0 }}>PRICING</p>
        <h1 style={{ margin: "0.4rem 0", fontSize: "2.4rem" }}>Run the algorithm. Decide smarter.</h1>
        <p style={{ opacity: 0.7, maxWidth: "62ch", margin: "0 auto" }}>HawkNetic provides sports analytics and betting-decision support. It does not accept wagers, place bets, or guarantee outcomes.</p>
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1.5rem" }}>
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
      <p style={{ textAlign: "center", marginTop: "3rem", fontSize: "0.78rem", opacity: 0.55 }}>
        Stripe checkout integration ships once you provide STRIPE_SECRET_KEY + STRIPE_PRICE_ID_PRO + STRIPE_PRICE_ID_PREMIUM. The plan and webhook tables are already in place.
      </p>
    </main>
  );
}
