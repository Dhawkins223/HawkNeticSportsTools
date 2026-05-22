"use client";

import type { SlipAnalysisResponse } from "../../types/betting";

function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function formatPercentRounded(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(2)}`;
}

function winProbabilityLabel(analysis: SlipAnalysisResponse): string {
  if (analysis.parlayProbability !== undefined) return formatPercent(analysis.parlayProbability);
  return formatPercentRounded(analysis.modelWinProbability);
}

function edgeLabel(analysis: SlipAnalysisResponse): string {
  if (analysis.parlayEdge !== undefined) return formatPercent(analysis.parlayEdge);
  if (analysis.edgePct === null || analysis.edgePct === undefined) return "—";
  return `${analysis.edgePct.toFixed(1)}%`;
}

function evLabel(analysis: SlipAnalysisResponse): string {
  if (analysis.parlayEvPerUnit !== undefined) return formatPercent(analysis.parlayEvPerUnit);
  return formatCurrency(analysis.expectedValue);
}

function confidenceLabel(analysis: SlipAnalysisResponse): string {
  if (analysis.parlayConfidenceScore !== undefined) return analysis.parlayConfidenceScore.toFixed(0);
  return analysis.confidenceTier;
}

type LegResult = SlipAnalysisResponse["legAnalyses"][number];

function LegMetricsRow({ leg }: { leg: LegResult }) {
  return (
    <div className="legMetrics" style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem 0.9rem", fontSize: "0.78rem", opacity: 0.85, marginTop: "0.35rem" }}>
      {leg.modelProbability !== null && <span>Win <b>{(leg.modelProbability * 100).toFixed(1)}%</b></span>}
      {leg.noVigProbability !== undefined && <span>No-vig <b>{(leg.noVigProbability * 100).toFixed(1)}%</b></span>}
      {leg.edgePct !== null && <span>Edge <b>{leg.edgePct.toFixed(1)}%</b></span>}
      {leg.evPerUnit !== undefined && <span>EV <b>{(leg.evPerUnit * 100).toFixed(1)}%</b></span>}
      {leg.projection !== undefined && <span>Projection <b>{leg.projection.toFixed(1)}</b></span>}
      {leg.kellyRecommended !== undefined && leg.kellyRecommended > 0 && <span>Kelly (¼) <b>{(leg.kellyRecommended * 100).toFixed(2)}%</b></span>}
      {leg.ci95 && <span>95% CI <b>{(leg.ci95[0] * 100).toFixed(0)}–{(leg.ci95[1] * 100).toFixed(0)}%</b></span>}
    </div>
  );
}

function LegResultCard({ leg }: { leg: LegResult }) {
  return (
    <article key={leg.legId} data-testid={`leg-result-${leg.legId}`}>
      <strong>{leg.selection} · {leg.classification ?? leg.verdict}</strong>
      <p>{leg.explanation}</p>
      <LegMetricsRow leg={leg} />
      {leg.trapFlags && leg.trapFlags.length ? leg.trapFlags.map((flag) => <small key={flag}>⚠️ {flag}</small>) : null}
    </article>
  );
}

function AnalysisMetrics({ analysis }: { analysis: SlipAnalysisResponse }) {
  return (
    <div className="analysisMetrics">
      <span>Win prob <b>{winProbabilityLabel(analysis)}</b></span>
      <span>Market implied <b>{formatPercent(analysis.impliedProbability)}</b></span>
      <span>Edge <b>{edgeLabel(analysis)}</b></span>
      <span>EV / unit <b>{evLabel(analysis)}</b></span>
      <span>Fair odds <b>{analysis.fairAmericanOdds ?? "—"}</b></span>
      <span>Confidence <b>{confidenceLabel(analysis)}</b></span>
      {analysis.parlayKellyRecommended !== undefined && <span>Kelly (¼) <b>{(analysis.parlayKellyRecommended * 100).toFixed(2)}%</b></span>}
      {analysis.parlayCi95 && <span>95% CI <b>{(analysis.parlayCi95[0] * 100).toFixed(1)}–{(analysis.parlayCi95[1] * 100).toFixed(1)}%</b></span>}
      {analysis.simulationRuns && <span>Runs <b>{analysis.simulationRuns.toLocaleString()}</b></span>}
    </div>
  );
}

export function AnalysisPanel({ analysis }: { analysis: SlipAnalysisResponse }) {
  return (
    <section className={`analysisPanel ${analysis.recommendation.toLowerCase()}`} data-testid="algorithm-result">
      <p>Algorithm verdict</p>
      <h3>{analysis.parlayClassification ?? analysis.recommendation.replaceAll("_", " ")}</h3>
      <strong>{analysis.summary}</strong>
      <AnalysisMetrics analysis={analysis} />
      {analysis.readiness && !analysis.readiness.ready && (
        <div className="warningList" data-testid="readiness-banner">
          <b>Live data not ready</b>
          {analysis.readiness.blocking_reasons.map((r) => <span key={r}>{r}</span>)}
        </div>
      )}
      {analysis.correlationWarning && (
        <div className="warningList"><b>Correlation</b><span>{analysis.correlationWarning}</span></div>
      )}
      {analysis.warnings.length ? (
        <div className="warningList"><b>Warnings</b>{analysis.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div>
      ) : null}
      <div className="legAnalysisList">
        {analysis.legAnalyses.map((leg) => <LegResultCard key={leg.legId} leg={leg} />)}
      </div>
      {analysis.betterAlternatives.length ? (
        <div className="betterAlternatives">
          <b>Smarter alternatives</b>
          {analysis.betterAlternatives.map((item) => <span key={item.title}>{item.title}: {item.reason}</span>)}
        </div>
      ) : null}
    </section>
  );
}
