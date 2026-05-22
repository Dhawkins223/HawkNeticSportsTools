"use client";

import Link from "next/link";

const BOLD_FONT_WEIGHT = 700;
const SEMI_BOLD_FONT_WEIGHT = 600;

export type PricingPlan = {
  name: string;
  price: string;
  cadence: string;
  features: readonly string[];
  cta: { href: string; label: string; testid: string };
  accent?: boolean;
};

const PLAN_CARD_BASE = {
  padding: "1.8rem 1.6rem",
  borderRadius: "16px",
};

export function PricingPlanCard({ plan }: { plan: PricingPlan }) {
  return (
    <article
      data-testid={`plan-${plan.name.toLowerCase()}`}
      style={{
        ...PLAN_CARD_BASE,
        border: plan.accent ? "1px solid #d8f63a" : "1px solid rgba(255,255,255,0.14)",
        background: plan.accent ? "rgba(216,246,58,0.06)" : "rgba(255,255,255,0.04)",
      }}
    >
      <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{plan.name}</h2>
      <p style={{ margin: "0.6rem 0 1rem", fontSize: "2rem", fontWeight: BOLD_FONT_WEIGHT }}>
        {plan.price}
        <span style={{ fontSize: "0.85rem", opacity: 0.6, fontWeight: 400 }}>{plan.cadence}</span>
      </p>
      <ul style={{ listStyle: "none", padding: 0, margin: "0 0 1.5rem", display: "grid", gap: "0.5rem", fontSize: "0.88rem", opacity: 0.85 }}>
        {plan.features.map((f) => <li key={f}>· {f}</li>)}
      </ul>
      <Link
        href={plan.cta.href}
        data-testid={plan.cta.testid}
        style={{
          display: "block",
          textAlign: "center",
          padding: "0.7rem 1rem",
          borderRadius: "999px",
          textDecoration: "none",
          fontWeight: SEMI_BOLD_FONT_WEIGHT,
          background: plan.accent ? "#d8f63a" : "rgba(255,255,255,0.12)",
          color: plan.accent ? "#0b1606" : "inherit",
        }}
      >
        {plan.cta.label}
      </Link>
    </article>
  );
}
