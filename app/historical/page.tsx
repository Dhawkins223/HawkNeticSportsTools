"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";

async function fetchStatus() {
  const response = await fetch("/api/historical/import/status");
  if (!response.ok) {
    throw new Error("Failed to fetch status");
  }
  return response.json();
}

async function startImport(startYear: number, endYear: number) {
  const response = await fetch("/api/historical/import", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-admin-token": "dev_admin_123", // In production, get this from user session
    },
    body: JSON.stringify({ startYear, endYear }),
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.error || "Import failed");
  }

  return response.json();
}

export default function HistoricalImportPage() {
  const [startYear, setStartYear] = useState(2000);
  const [endYear, setEndYear] = useState(new Date().getFullYear());
  const [isImporting, setIsImporting] = useState(false);

  const statusQuery = useQuery({
    queryKey: ["historical-status"],
    queryFn: fetchStatus,
    refetchInterval: 30000, // Refetch every 30 seconds
  });

  const handleImport = async () => {
    if (startYear < 2000 || startYear > new Date().getFullYear()) {
      toast.error("Start year must be between 2000 and current year");
      return;
    }

    if (endYear < startYear || endYear > new Date().getFullYear()) {
      toast.error("End year must be between start year and current year");
      return;
    }

    setIsImporting(true);
    try {
      const result = await startImport(startYear, endYear);
      toast.success(`Import started for ${startYear}-${endYear}. This will take a long time.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Import failed");
    } finally {
      setIsImporting(false);
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto space-y-6">
      <div className="card p-6">
        <h2 className="text-2xl font-bold text-text mb-6">Historical Data Import</h2>

        <div className="space-y-6">
          {/* Import Controls */}
          <section>
            <h3 className="text-xl font-semibold text-text mb-4">Import Historical Data</h3>
            <div className="space-y-4">
              <div className="p-4 bg-surface2 border border-border rounded-lg">
                <p className="text-sm text-textSecondary mb-2">
                  Import NBA games, box scores, and results from 2000 to today.
                  This process will take a very long time (hours to days) depending on the date range.
                </p>
                <p className="text-sm text-textSecondary">
                  <strong>Note:</strong> The import runs in the background. Check server logs for progress.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-text mb-2">
                    Start Year
                  </label>
                  <input
                    type="number"
                    min="2000"
                    max={new Date().getFullYear()}
                    value={startYear}
                    onChange={(e) => setStartYear(parseInt(e.target.value) || 2000)}
                    className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                  />
                </div>

                <div>
                  <label className="block text-sm font-semibold text-text mb-2">
                    End Year
                  </label>
                  <input
                    type="number"
                    min={startYear}
                    max={new Date().getFullYear()}
                    value={endYear}
                    onChange={(e) => setEndYear(parseInt(e.target.value) || new Date().getFullYear())}
                    className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                  />
                </div>
              </div>

              <button
                onClick={handleImport}
                disabled={isImporting}
                className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isImporting ? "Starting Import..." : `Import ${endYear - startYear + 1} Seasons`}
              </button>
            </div>
          </section>

          {/* Status */}
          <section>
            <h3 className="text-xl font-semibold text-text mb-4">Import Status</h3>
            {statusQuery.isLoading && (
              <div className="text-sm text-textSecondary">Loading status...</div>
            )}
            {statusQuery.error && (
              <div className="text-sm text-negative">
                Error loading status: {statusQuery.error instanceof Error ? statusQuery.error.message : "Unknown error"}
              </div>
            )}
            {statusQuery.data && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-surface2 border border-border rounded-lg p-4">
                    <div className="text-xs text-textSecondary uppercase mb-1">Total Games</div>
                    <div className="text-2xl font-bold text-accent">
                      {statusQuery.data.summary.totalGames.toLocaleString()}
                    </div>
                  </div>
                  <div className="bg-surface2 border border-border rounded-lg p-4">
                    <div className="text-xs text-textSecondary uppercase mb-1">Games with Results</div>
                    <div className="text-2xl font-bold text-accent">
                      {statusQuery.data.summary.gamesWithResults.toLocaleString()}
                    </div>
                  </div>
                  <div className="bg-surface2 border border-border rounded-lg p-4">
                    <div className="text-xs text-textSecondary uppercase mb-1">Total Players</div>
                    <div className="text-2xl font-bold text-accent">
                      {statusQuery.data.summary.totalPlayers.toLocaleString()}
                    </div>
                  </div>
                  <div className="bg-surface2 border border-border rounded-lg p-4">
                    <div className="text-xs text-textSecondary uppercase mb-1">Player Stats</div>
                    <div className="text-2xl font-bold text-accent">
                      {statusQuery.data.summary.totalStats.toLocaleString()}
                    </div>
                  </div>
                </div>

                <div className="bg-surface2 border border-border rounded-lg p-4">
                  <div className="text-sm text-textSecondary mb-2">Date Range</div>
                  <div className="text-text">
                    {statusQuery.data.summary.oldestGame
                      ? new Date(statusQuery.data.summary.oldestGame).toLocaleDateString()
                      : "N/A"}{" "}
                    to{" "}
                    {statusQuery.data.summary.newestGame
                      ? new Date(statusQuery.data.summary.newestGame).toLocaleDateString()
                      : "N/A"}
                  </div>
                </div>

                {statusQuery.data.gamesByYear && statusQuery.data.gamesByYear.length > 0 && (
                  <div className="bg-surface2 border border-border rounded-lg p-4">
                    <div className="text-sm font-semibold text-text mb-3">Games by Year</div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 max-h-64 overflow-y-auto">
                      {statusQuery.data.gamesByYear.map((item: { year: number; count: number }) => (
                        <div key={item.year} className="text-sm">
                          <span className="text-textSecondary">{item.year}:</span>{" "}
                          <span className="text-text font-semibold">{item.count}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

