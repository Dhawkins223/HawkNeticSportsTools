"use client";

import { Line } from "react-chartjs-2";
import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip
} from "chart.js";
import { useMemo } from "react";

ChartJS.register(CategoryScale, LinearScale, LineElement, PointElement, Tooltip, Legend, Filler);

type DistributionChartProps = {
  mean: number;
  stdDev: number;
  line: number;
};

function normalDensity(x: number, mean: number, stdDev: number) {
  const coefficient = 1 / (stdDev * Math.sqrt(2 * Math.PI));
  const exponent = -((x - mean) ** 2) / (2 * stdDev ** 2);
  return coefficient * Math.exp(exponent);
}

export function DistributionChart({ mean, stdDev, line }: DistributionChartProps) {
  const points = useMemo(() => {
    const values: number[] = [];
    const start = mean - 4 * stdDev;
    const step = (8 * stdDev) / 40;
    for (let i = 0; i <= 40; i += 1) {
      const x = start + i * step;
      values.push(x);
    }
    return values;
  }, [mean, stdDev]);

  const data = useMemo(
    () => ({
      labels: points.map((x) => x.toFixed(1)),
      datasets: [
        {
          label: "Model distribution",
          data: points.map((x) => normalDensity(x, mean, stdDev)),
          borderColor: "#06B6D4",
          backgroundColor: "rgba(6, 182, 212, 0.25)",
          fill: true,
          tension: 0.4,
          pointRadius: 0
        },
        {
          label: "Line",
          data: points.map((x) => (Math.abs(x - line) < 0.01 ? normalDensity(x, mean, stdDev) : NaN)),
          borderColor: "#f97316",
          backgroundColor: "transparent",
          borderWidth: 2,
          pointRadius: 0
        }
      ]
    }),
    [points, mean, stdDev, line]
  );

  const options = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: {
            color: "#f9fafb"
          }
        },
        tooltip: {
          callbacks: {
            label: (context: any) => `${context.dataset.label}: ${(context.parsed.y as number).toFixed(4)}`
          }
        }
      },
      scales: {
        x: {
          ticks: {
            color: "#94a3b8"
          },
          grid: {
            color: "rgba(148, 163, 184, 0.15)"
          }
        },
        y: {
          ticks: {
            color: "#94a3b8"
          },
          grid: {
            color: "rgba(148, 163, 184, 0.1)"
          }
        }
      }
    }),
    []
  );

  return (
    <div className="h-64 w-full">
      <Line data={data} options={options} />
    </div>
  );
}
