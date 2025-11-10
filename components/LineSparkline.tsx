"use client";

import { useMemo } from "react";

type LineSparklineProps = {
  points: number[];
};

export function LineSparkline({ points }: LineSparklineProps) {
  const { path, min, max } = useMemo(() => generatePath(points), [points]);

  if (!points.length) {
    return <div className="h-16 w-full rounded-xl bg-white/5" />;
  }

  return (
    <div className="h-16 w-full rounded-xl bg-white/5">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full text-accent">
        <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
        <text x="2" y="14" className="fill-white/40 text-[8px]">
          {min.toFixed(1)}
        </text>
        <text x="2" y="96" className="fill-white/40 text-[8px]">
          {max.toFixed(1)}
        </text>
      </svg>
    </div>
  );
}

function generatePath(points: number[]): { path: string; min: number; max: number } {
  if (points.length === 0) {
    return { path: "", min: 0, max: 0 };
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;

  const step = 100 / Math.max(points.length - 1, 1);

  let path = "";
  points.forEach((value, index) => {
    const x = index * step;
    const normalized = (value - min) / range;
    const y = 100 - normalized * 90 - 5; // padding from edges
    path += index === 0 ? `M ${x} ${y}` : ` L ${x} ${y}`;
  });

  return { path, min, max };
}
