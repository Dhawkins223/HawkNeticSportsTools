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
        Stripe checkout integration ships once you provide STRIPE_SECRET_KEY + STRIPE_PRICE_ID_PRO + STRIPE_PRICE_ID_PREMIUM. The plan and webhook tables are already in place.
      </p>
    </main>
  );
}
