"use client";

export function LoadingSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: lines }, (_, index) => (
        <div key={index} className="skeleton h-6 w-full" />
      ))}
    </div>
  );
}
