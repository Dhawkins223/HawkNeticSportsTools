import type { Prop } from "../lib/api";

export function EVTable({ props }: { props: Prop[] }) {
  const rows = [...props].sort((a, b) => (b.expected_value || 0) - (a.expected_value || 0)).slice(0, 5);
  return <div className="panel"><h3>Best EV Plays</h3>{rows.length ? <ul className="compactList">{rows.map((p, i) => <li key={i}>{p.market || "Market"}<span>EV {p.expected_value ?? "pending"}</span></li>)}</ul> : <p>No EV records in PostgreSQL yet.</p>}</div>;
}
