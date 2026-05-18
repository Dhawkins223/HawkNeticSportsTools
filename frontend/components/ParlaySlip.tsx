import type { ParlayLegInput, ParlayResult } from "../lib/api";
import { calculateSlipMetrics, type SlipOptimizerMode } from "../lib/parlayMath";

function formatOdds(value?: number) {
  if (value === undefined || value === null) return "-";
  return value > 0 ? `+${value}` : String(value);
}

function formatProbability(value?: number) {
  if (value === undefined || value === null) return "50%";
  return `${Math.round(value * 100)}%`;
}

function formatSignedPercent(value: number) {
  const rounded = Math.round(value * 100);
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

function impactWidth(edge: number) {
  return `${Math.max(8, Math.min(100, 50 + edge * 240))}%`;
}

export function ParlaySlip({ legs, result, onRemove, onMove, onBuild, onOptimize }: { legs: ParlayLegInput[]; result?: ParlayResult; onRemove: (index: number) => void; onMove: (from: number, to: number) => void; onBuild: () => void; onOptimize: (mode: SlipOptimizerMode) => void }) {
  const metrics = calculateSlipMetrics(legs);
  const displayedWin = result?.win_probability ?? metrics.winProbability;
  const displayedLoss = result?.loss_probability ?? metrics.lossProbability;
  const displayedRisk = result?.risk_tier || metrics.riskTier;
  const displayedOdds = result?.estimated_odds ?? metrics.estimatedOdds;

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
          <strong>{legs.length ? `${Math.round(displayedWin * 100)}%` : "--"}</strong>
        </span>
        <span>
          Risk
          <strong>{displayedRisk}</strong>
        </span>
      </div>

      <div className="smartSlipLab">
        <div className="labGrade">
          <span>2K slip grade</span>
          <strong>{metrics.grade}</strong>
        </div>
        <div className="labSignals">
          <span>{metrics.volatility}</span>
          <span>Avg edge {formatSignedPercent(metrics.averageEdge)}</span>
          <span>Projected odds {displayedOdds ?? "--"}</span>
        </div>
        <p>{metrics.recommendation}</p>
      </div>

      <div className="optimizerBar">
        <button disabled={legs.length < 2} onClick={() => onOptimize("safer")}>Safer</button>
        <button disabled={legs.length < 2} onClick={() => onOptimize("upside")}>Higher upside</button>
        <button disabled={legs.length < 2} onClick={() => onOptimize("ev")}>Best EV</button>
        <button disabled={!legs.length} onClick={() => onOptimize("trap")}>Remove trap</button>
      </div>

      {legs.length ? (
        <ol className="slipList orderedSlip">
          {legs.map((leg, index) => (
            <li key={`${leg.label}-${index}`} className="slipLeg">
              <span className="legRank">{index + 1}</span>
              <div className="legDetails">
                <strong>{leg.label}</strong>
                <small>Model {formatProbability(leg.probability)} · Odds {formatOdds(leg.odds_value)}</small>
                <div className="impactMeter">
                  <span style={{ width: impactWidth(metrics.legImpacts[index]?.edge ?? 0) }} />
                </div>
                <small>{metrics.legImpacts[index]?.label || "Impact pending"} · edge {formatSignedPercent(metrics.legImpacts[index]?.edge ?? 0)} · drag {formatSignedPercent(metrics.legImpacts[index]?.drag ?? 0)}</small>
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

      <div className="correlationRadar">
        <strong>Correlation radar</strong>
        <p>{result?.correlation_warning || (legs.length > 1 ? "Backend correlation review runs when the ticket is saved." : "Add multiple legs to check same-game and same-player risk.")}</p>
        <p>{result?.trap_leg_warning || (metrics.legImpacts[metrics.weakestLegIndex]?.label === "Trap risk" ? "Trap leg detected by price/model edge." : "No trap leg flagged in the live lab yet.")}</p>
      </div>

      <button className="primaryButton buildTicketButton" disabled={!legs.length} onClick={onBuild}>
        Run predictor / save slip
      </button>

      {result && (
        <div className="resultGrid predictionSummary">
          <span>Odds <strong>{displayedOdds ?? "-"}</strong></span>
          <span>Win <strong>{Math.round(displayedWin * 100)}%</strong></span>
          <span>Loss <strong>{Math.round(displayedLoss * 100)}%</strong></span>
          <span>EV <strong>{result.expected_value}</strong></span>
          <span>Risk <strong>{displayedRisk}</strong></span>
          <span>Confidence <strong>{result.confidence_tier || "pending"}</strong></span>
        </div>
      )}
    </aside>
  );
}
