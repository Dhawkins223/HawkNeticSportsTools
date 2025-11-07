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

type LineSparklineProps = {
  points: number[];
};

export function LineSparkline({ points }: LineSparklineProps) {
  const data = useMemo(
    () => ({
      labels: points.map((_, index) => `${index + 1}`),
      datasets: [
        {
          data: points,
          borderColor: "#06B6D4",
          backgroundColor: "rgba(6, 182, 212, 0.15)",
          tension: 0.4,
          fill: true,
          pointRadius: 0
        }
      ]
    }),
    [points]
  );

  const options = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          display: false
        },
        y: {
          display: false
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context: any) => `Line: ${context.parsed.y}`
          }
        }
      }
    }),
    []
  );

  return (
    <div className="h-16 w-full">
      <Line data={data} options={options} />
    </div>
  );
}
