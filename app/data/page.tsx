"use client";

import { useState } from "react";
import toast from "react-hot-toast";

export default function DataPage() {
  const [exportFormat, setExportFormat] = useState<"json" | "csv">("json");
  const [exportType, setExportType] = useState<"all" | "games" | "players" | "odds" | "historical">("all");
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const response = await fetch(
        `/api/data/export?format=${exportFormat}&type=${exportType}`
      );

      if (!response.ok) {
        throw new Error("Export failed");
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `nba_data_${Date.now()}.${exportFormat}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      toast.success("Data exported successfully!");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    } finally {
      setIsExporting(false);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsImporting(true);
    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch("/api/data/import", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Import failed");
      }

      toast.success(`Successfully imported ${data.recordCount} records!`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Import failed");
    } finally {
      setIsImporting(false);
      // Reset file input
      e.target.value = "";
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto space-y-6">
      <div className="card p-6">
        <h2 className="text-2xl font-bold text-text mb-6">Data Import & Export</h2>

        {/* Export Section */}
        <section className="mb-8">
          <h3 className="text-xl font-semibold text-text mb-4">Export Data</h3>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-semibold text-text mb-2">
                Export Format
              </label>
              <select
                value={exportFormat}
                onChange={(e) => setExportFormat(e.target.value as "json" | "csv")}
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
              >
                <option value="json">JSON</option>
                <option value="csv">CSV</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-semibold text-text mb-2">
                Data Type
              </label>
              <select
                value={exportType}
                onChange={(e) => setExportType(e.target.value as any)}
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
              >
                <option value="all">All Data</option>
                <option value="games">Games</option>
                <option value="players">Players</option>
                <option value="odds">Odds</option>
                <option value="historical">Historical Data</option>
              </select>
            </div>

            <button
              onClick={handleExport}
              disabled={isExporting}
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isExporting ? "Exporting..." : "Export Data"}
            </button>
          </div>
        </section>

        {/* Import Section */}
        <section>
          <h3 className="text-xl font-semibold text-text mb-4">Import Data</h3>
          <div className="space-y-4">
            <div className="p-4 bg-surface2 border border-border rounded-lg">
              <p className="text-sm text-textSecondary mb-2">
                Import data from a JSON file. The file should contain game, player, or odds data in the same format as exported data.
              </p>
            </div>

            <div>
              <label className="block text-sm font-semibold text-text mb-2">
                Select File
              </label>
              <input
                type="file"
                accept=".json,.csv"
                onChange={handleImport}
                disabled={isImporting}
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all disabled:opacity-50"
              />
            </div>

            {isImporting && (
              <div className="text-sm text-textSecondary">
                Importing data...
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

