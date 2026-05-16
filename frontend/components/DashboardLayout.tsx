import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";

export function DashboardLayout({ collapsed, onToggle, children }: { collapsed: boolean; onToggle: () => void; children: ReactNode }) {
  return <main className={`dashboardShell ${collapsed ? "sidebarCollapsed" : ""}`}><Sidebar collapsed={collapsed} onToggle={onToggle} /><section className="workspace">{children}</section></main>;
}
