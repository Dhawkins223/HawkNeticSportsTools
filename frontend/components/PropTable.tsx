import type { ParlayLegInput, Prop } from "../lib/api";

function formatOdds(value?: number) {
  if (value === undefined || value === null) return "-";
  return value > 0 ? `+${value}` : String(value);
}

function formatModel(value?: number) {
  if (value === undefined || value === null) return "pending";
  return `${Math.round(value * 100)}%`;
}

function buildLabel(prop: Prop) {
  return `${prop.market || prop.selection || "Prop"} ${prop.line ?? ""}`.trim();
}

export function PropTable({ props, onAdd }: { props: Prop[]; onAdd: (leg: ParlayLegInput) => void }) {
  const boardRows = [...props]
    .sort((a, b) => (b.expected_value || 0) - (a.expected_value || 0))
    .slice(0, 12);

  return (
    <div className="panel marketBoard" id="props">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Live predictor board</p>
          <h3>NBA prop markets</h3>
        </div>
        <span className="pill">{props.length} markets</span>
      </div>
      <table className="marketTable">
        <thead>
          <tr>
            <th>Selection</th>
            <th>Line</th>
            <th>Model</th>
            <th>EV</th>
            <th>Odds</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {boardRows.length ? boardRows.map((prop, index) => (
            <tr key={`${prop.id || "prop"}-${index}`}>
              <td>
                <strong>{prop.market || prop.selection || "Prop"}</strong>
                <small>{prop.confidence_tier || "confidence pending"}</small>
              </td>
              <td>{prop.line ?? "-"}</td>
              <td>{formatModel(prop.model_probability)}</td>
              <td>{prop.expected_value ?? "pending"}</td>
              <td>{formatOdds(prop.over_odds || prop.under_odds)}</td>
              <td>
                <button
                  className="addLegButton"
                  onClick={() => onAdd({
                    prop_id: prop.id,
                    label: buildLabel(prop),
                    odds_value: prop.over_odds || prop.under_odds || 100,
                    probability: prop.model_probability || 0.5,
                    expected_value: prop.expected_value,
                    confidence_tier: prop.confidence_tier,
                  })}
                >
                  Add to slip
                </button>
              </td>
            </tr>
          )) : (
            <tr>
              <td colSpan={6}>No PostgreSQL props yet. This is a real empty state, not mock data.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
