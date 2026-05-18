const nav = [
  { label: "Dashboard", href: "#dashboard" },
  { label: "Predictor Board", href: "#props" },
  { label: "Slip Builder", href: "#parlays" },
  { label: "Games", href: "#games" },
  { label: "Simulations", href: "#simulations" },
  { label: "Ticket History", href: "#bankroll" },
  { label: "Database Status", href: "#database-status" },
  { label: "Ingestion Status", href: "#ingestion-status" },
];

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebarBrand"><span className="brandMark">HN</span><span>HawkNetic</span></div>
      <button className="ghostButton" onClick={onToggle}>{collapsed ? "Open" : "Collapse"}</button>
      <nav>
        {nav.map((item) => <a key={item.label} href={item.href}>{item.label}</a>)}
      </nav>
    </aside>
  );
}
