"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { useEffect } from "react";
import { getGameById, getProps } from "../../../lib/api";
import { MatchupCard } from "../../../components/MatchupCard";
import { OddsPanel } from "../../../components/OddsPanel";
import { DistributionChart } from "../../../components/DistributionChart";
import { LoadingSkeleton } from "../../../components/LoadingSkeleton";
import { WhyDrawer } from "../../../components/WhyDrawer";

export default function GameDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const gameQuery = useQuery({ queryKey: ["game", params.id], queryFn: () => getGameById(params.id) });

  useEffect(() => {
    if (gameQuery.isError) {
      toast.error((gameQuery.error as Error).message);
    }
  }, [gameQuery.isError, gameQuery.error]);

  const propsQuery = useQuery({
    queryKey: ["props", params.id, "detail"],
    queryFn: () => getProps(params.id),
    enabled: Boolean(params.id)
  });

  useEffect(() => {
    if (propsQuery.isError) {
      toast.error((propsQuery.error as Error).message);
    }
  }, [propsQuery.isError, propsQuery.error]);

  if (gameQuery.isLoading) {
    return <LoadingSkeleton lines={6} />;
  }

  if (!gameQuery.data) {
    return (
      <div className="space-y-4 text-sm text-white/60">
        <p>Game not found.</p>
        <button type="button" className="text-accent" onClick={() => router.push("/games")}>
          Back to games
        </button>
      </div>
    );
  }

  const topProp = propsQuery.data?.[0];

  return (
    <div className="space-y-6">
      <button type="button" className="text-sm text-accent" onClick={() => router.back()}>
        ← Back
      </button>
      <MatchupCard game={gameQuery.data} />
      <OddsPanel odds={gameQuery.data.odds} />
      {topProp && (
        <section className="card space-y-4 p-6">
          <header>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-white/60">Featured prop distribution</h3>
            <p className="text-white/60">
              {topProp.player} {topProp.market.toLowerCase()} line at {topProp.line} with model mean {topProp.modelMean.toFixed(1)}
            </p>
          </header>
          <DistributionChart mean={topProp.modelMean} stdDev={topProp.modelStdDev} line={topProp.line} />
        </section>
      )}
      {propsQuery.isLoading && <LoadingSkeleton lines={4} />}
      <WhyDrawer game={gameQuery.data} />
    </div>
  );
}
