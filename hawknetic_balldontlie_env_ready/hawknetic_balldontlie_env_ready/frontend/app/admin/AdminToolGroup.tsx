"use client";

import type { ReactElement } from "react";

export type AdminAction = () => Promise<unknown>;
export type AdminTool = { id: string; label: string; run: AdminAction };
export type ToolGroup = { title: string; description: string; tools: AdminTool[] };

type ToolButtonProps = {
  tool: AdminTool;
  loadingId: string | null;
  activeId: string | null;
  onRun: (tool: AdminTool) => void;
};

function ToolButton({ tool, loadingId, activeId, onRun }: ToolButtonProps): ReactElement {
  const isLoading = loadingId === tool.id;
  return (
    <button
      key={tool.id}
      disabled={loadingId !== null}
      onClick={() => onRun(tool)}
      data-testid={`admin-${tool.id}`}
      style={{
        padding: "0.7rem 0.9rem",
        borderRadius: "8px",
        border: "1px solid rgba(255,255,255,0.15)",
        background: activeId === tool.id ? "rgba(216,246,58,0.18)" : "rgba(255,255,255,0.04)",
        color: "inherit",
        textAlign: "left",
        cursor: loadingId ? "not-allowed" : "pointer",
        fontSize: "0.85rem",
      }}
    >
      {isLoading ? `${tool.label} (running…)` : tool.label}
    </button>
  );
}

type Props = {
  group: ToolGroup;
  loadingId: string | null;
  activeId: string | null;
  onRun: (tool: AdminTool) => void;
};

export function AdminToolGroup({ group, loadingId, activeId, onRun }: Props): ReactElement {
  return (
    <section
      style={{ marginBottom: "2rem" }}
      data-testid={`admin-group-${group.title.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <h2 style={{ margin: "0 0 0.3rem", fontSize: "1.05rem", letterSpacing: "0.06em", textTransform: "uppercase", color: "#d8f63a" }}>
        {group.title}
      </h2>
      <p style={{ opacity: 0.6, fontSize: "0.85rem", marginTop: 0 }}>{group.description}</p>
      <div
        className="adminToolGrid"
        style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "0.6rem", marginTop: "0.7rem" }}
      >
        {group.tools.map((tool) => (
          <ToolButton key={tool.id} tool={tool} loadingId={loadingId} activeId={activeId} onRun={onRun} />
        ))}
      </div>
    </section>
  );
}
