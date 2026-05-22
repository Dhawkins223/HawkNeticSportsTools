"use client";

import { useEffect, useState } from "react";
import { api, type TopEvInsight } from "@/lib/api";

export function TopEvScanner() {
  const [items, setItems] = useState<TopEvInsight[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.topEv(8);
        if (!cancelled) setItems(data.items);
      } catch (ex) {
        if (!cancelled) setErr(ex instanceof Error ? ex.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <aside data-testid="top-ev-scanner" style={{ background: "rgba(216,246,58,0.04)", border: "1px solid rgba(216,246,58,0.18)", borderRadius: "12px", padding: "1rem 1.1rem", margin: "1rem 1.2rem 0", color: "inherit" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "0.4rem" }}>
        <div>
          <p style={{ margin: 0, fontSize: "0.7rem", letterSpacing: "0.18em", color: "#d8f63a" }}>+EV SCANNER · LIVE</p>
          <h2 style={{ margin: "0.2rem 0 0", fontSize: "1.05rem" }}>Today's highest-edge plays</h2>
        </div>
        <span style={{ fontSize: "0.72rem", opacity: 0.6 }}>{loading ? "scanning…" : items ? `${items.length} edges found` : ""}</span>
      </header>
      {err && <div style={{ fontSize: "0.85rem", color: "#ff8888" }}>{err}</div>}
      {!loading && items && items.length === 0 && <div style={{ fontSize: "0.85rem", opacity: 0.7 }}>No positive-EV plays detected right now. Refresh after the next prop sync.</div>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "0.6rem", marginTop: "0.6rem" }}>
        {(items || []).slice(0, 8).map((insight) => (
          <article key={`${insight.propId}-${insight.side}`} data-testid={`top-ev-${insight.propId}-${insight.side}`} style={{ background: "rgba(0,0,0,0.45)", borderRadius: "9px", padding: "0.65rem 0.75rem", fontSize: "0.78rem", lineHeight: 1.35 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <strong style={{ fontSize: "0.82rem" }}>{insight.playerName || insight.market}</strong>
              <span style={{ color: "#d8f63a", fontWeight: 700 }}>+{insight.evPercent.toFixed(1)}%</span>
            </div>
            <div style={{ opacity: 0.75 }}>{insight.market} · {insight.line ?? ""} {insight.side}</div>
            <div style={{ opacity: 0.55, fontSize: "0.72rem", marginTop: "0.25rem" }}>
              {insight.americanOdds > 0 ? `+${insight.americanOdds}` : insight.americanOdds} · model {(insight.modelProbability * 100).toFixed(0)}% vs market {(insight.impliedProbability * 100).toFixed(0)}%
            </div>
            <div style={{ opacity: 0.55, fontSize: "0.72rem" }}>{insight.eventLabel}</div>
          </article>
        ))}
      </div>
    </aside>
  );
}
