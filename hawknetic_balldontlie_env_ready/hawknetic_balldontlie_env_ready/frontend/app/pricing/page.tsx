"use client";

import { CompetitorComparison } from "./CompetitorComparison";
import { PricingPlanCard, type PricingPlan } from "./PricingPlanCard";

const PLANS: readonly PricingPlan[] = [
  {
    name: "Free",
    price: "$0",
    cadence: "/forever",
    features: ["3 algorithm runs/day", "NBA + NFL only", "Basic verdict", "3 saved slips"],
    cta: { href: "/signup", label: "Start free", testid: "plan-free-cta" },
  },
  {
    name: "Starter",
    price: "$9",
    cadence: "/month",
    features: ["15 runs/day", "All sports (NBA · NFL · MLB · NHL · Soccer · Golf)", "No-vig edge per leg", "10 saved slips", "Live readiness alerts"],
    cta: { href: "/signup?plan=starter", label: "Start Starter", testid: "plan-starter-cta" },
  },
  {
    name: "Pro",
    price: "$29",
    cadence: "/month",
    features: ["75 runs/day", "Full EV / edge / Kelly", "50 saved slips", "Same-game correlation matrix", "Trap-leg detection", "95% CI per probability"],
    cta: { href: "/signup?plan=pro", label: "Start Pro", testid: "plan-pro-cta" },
    accent: true,
  },
  {
    name: "Elite",
    price: "$79",
    cadence: "/month",
    features: ["300 runs/day", "Advanced 25k Monte Carlo runs", "Line-movement intel", "Correlation matrix exports", "+EV scanner across all books", "Priority support"],
    cta: { href: "/signup?plan=elite", label: "Start Elite", testid: "plan-elite-cta" },
  },
];

function PricingHero() {
  return (
    <header style={{ textAlign: "center", marginBottom: "2.5rem" }}>
      <p style={{ fontSize: "0.7rem", letterSpacing: "0.2em", color: "#d8f63a", margin: 0 }}>HAWKNETICSPORTS · PRICING</p>
      <h1 style={{ margin: "0.4rem 0", fontSize: "2.4rem" }}>Run the algorithm. Decide smarter.</h1>
      <p style={{ opacity: 0.7, maxWidth: "62ch", margin: "0 auto" }}>
        HawkneticSports provides sports analytics and betting-decision support. It does not accept wagers, place bets, or guarantee outcomes.
      </p>
    </header>
  );
}

function PlansGrid() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1.5rem", marginBottom: "3.5rem" }}>
      {PLANS.map((plan) => <PricingPlanCard key={plan.name} plan={plan} />)}
    </div>
  );
}

export default function PricingPage() {
  return (
    <main style={{ minHeight: "100vh", padding: "3rem 1.5rem 4rem", maxWidth: "1100px", margin: "0 auto" }} data-testid="pricing-page">
      <PricingHero />
      <PlansGrid />
      <CompetitorComparison />
      <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.78rem", opacity: 0.55 }}>
        Powered by Stripe. Cancel any time from your account. HawkneticSports provides decision support — we do not place wagers.
      </p>
    </main>
  );
}
