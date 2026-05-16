const nav = ["Dashboard", "Games", "Players", "Props", "Parlays", "Simulations", "Odds", "Historical Data", "Live API Data", "Database Status", "Ingestion Status", "Bankroll", "Settings"];

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebarBrand"><span className="brandMark">HN</span><span>HawkNetic</span></div>
      <button className="ghostButton" onClick={onToggle}>{collapsed ? "Open" : "Collapse"}</button>
      <nav>
        {nav.map((item) => <a key={item} href={`#${item.toLowerCase().replaceAll(" ", "-")}`}>{item}</a>)}
      </nav>
    </aside>
  );
}
