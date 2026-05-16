import type { ParlayLegInput, Prop } from "../lib/api";

export function PropTable({ props, onAdd }: { props: Prop[]; onAdd: (leg: ParlayLegInput) => void }) {
  return <div className="panel" id="props"><h3>Top Props</h3><table><thead><tr><th>Market</th><th>Line</th><th>EV</th><th>Confidence</th><th /></tr></thead><tbody>{props.length ? props.map((prop, index) => <tr key={`${prop.id || "prop"}-${index}`}><td>{prop.market || prop.selection || "Prop"}</td><td>{prop.line ?? "-"}</td><td>{prop.expected_value ?? "-"}</td><td>{prop.confidence_tier || "pending"}</td><td><button onClick={() => onAdd({ prop_id: prop.id, label: `${prop.market || "Prop"} ${prop.line ?? ""}`.trim(), odds_value: prop.over_odds || prop.under_odds || 100, probability: prop.model_probability || 0.5 })}>Add</button></td></tr>) : <tr><td colSpan={5}>No PostgreSQL props yet. This is a real empty state, not mock data.</td></tr>}</tbody></table></div>;
}
