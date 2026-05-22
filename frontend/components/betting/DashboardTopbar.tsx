"use client";

type Props = {
  loading: boolean;
  onRefresh: () => void;
};

export function DashboardTopbar({ loading, onRefresh }: Props) {
  return (
    <header className="hnTopbar">
      <div>
        <p>HawkneticSports · prediction tool · no wagers placed</p>
        <h1>HawkneticSportsTools</h1>
        <span>
          Build an event slate the way a sportsbook would display one, then press <strong>Run Algorithm</strong> to score every leg with the HawkneticSports prediction models.
        </span>
      </div>
      <div className="hnStatusChips" data-testid="status-chips">
        <span>Algorithm-Powered</span>
        <span>No wagers placed here</span>
        <span>Prediction &amp; Decision Support</span>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          data-testid="refresh-markets-btn"
          style={{ background: "rgba(216,246,58,.14)", color: "#d8f63a", borderColor: "rgba(216,246,58,.4)" }}
        >
          {loading ? "Refreshing…" : "Refresh markets"}
        </button>
      </div>
    </header>
  );
}
