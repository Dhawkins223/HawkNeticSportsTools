import type { ParlayLegInput, ParlayResult } from "../lib/api";

function formatOdds(value?: number) {
  if (value === undefined || value === null) return "-";
  return value > 0 ? `+${value}` : String(value);
}

function formatProbability(value?: number) {
  if (value === undefined || value === null) return "50%";
  return `${Math.round(value * 100)}%`;
}

export function ParlaySlip({ legs, result, onRemove, onMove, onBuild }: { legs: ParlayLegInput[]; result?: ParlayResult; onRemove: (index: number) => void; onMove: (from: number, to: number) => void; onBuild: () => void }) {
  return (
    <aside className="panel slipBuilder" id="parlays">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Hawknetic slip builder</p>
          <h3>Prediction ticket</h3>
        </div>
        <span className="pill">{legs.length} legs</span>
      </div>

      <div className="slipScoreboard">
        <span>
          Est. win
          <strong>{result ? `${Math.round(result.win_probability * 100)}%` : "--"}</strong>
        </span>
        <span>
          Risk
          <strong>{result?.risk_tier || "ungraded"}</strong>
        </span>
      </div>

      {legs.length ? (
        <ol className="slipList orderedSlip">
          {legs.map((leg, index) => (
            <li key={`${leg.label}-${index}`} className="slipLeg">
              <span className="legRank">{index + 1}</span>
              <div className="legDetails">
                <strong>{leg.label}</strong>
                <small>Model {formatProbability(leg.probability)} · Odds {formatOdds(leg.odds_value)}</small>
              </div>
              <div className="legActions" aria-label={`Reorder ${leg.label}`}>
                <button disabled={index === 0} onClick={() => onMove(index, index - 1)}>Up</button>
                <button disabled={index === legs.length - 1} onClick={() => onMove(index, index + 1)}>Down</button>
                <button onClick={() => onRemove(index)}>Remove</button>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <div className="emptySlip">
          <strong>No active ticket yet</strong>
          <p>Add legs from the predictor board to build and rank a slip.</p>
        </div>
      )}

      <button className="primaryButton buildTicketButton" disabled={!legs.length} onClick={onBuild}>
        Run predictor / save slip
      </button>

      {result && (
        <div className="resultGrid predictionSummary">
          <span>Odds <strong>{result.estimated_odds ?? "-"}</strong></span>
          <span>Win <strong>{Math.round(result.win_probability * 100)}%</strong></span>
          <span>Loss <strong>{Math.round(result.loss_probability * 100)}%</strong></span>
          <span>EV <strong>{result.expected_value}</strong></span>
          <span>Risk <strong>{result.risk_tier}</strong></span>
          <span>Confidence <strong>{result.confidence_tier || "pending"}</strong></span>
          {result.correlation_warning && <p>{result.correlation_warning}</p>}
          {result.trap_leg_warning && <p>{result.trap_leg_warning}</p>}
        </div>
      )}
    </aside>
  );
}
