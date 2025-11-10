"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import toast from "react-hot-toast";
import { GamePicker, type GameFilters } from "../../components/GamePicker";
import { MatchupCard } from "../../components/MatchupCard";
import { OddsPanel } from "../../components/OddsPanel";
import { PropTable } from "../../components/PropTable";
import { SgpComposer } from "../../components/SgpComposer";
import { BetSlip } from "../../components/BetSlip";
import { LoadingSkeleton } from "../../components/LoadingSkeleton";
import { WhyDrawer } from "../../components/WhyDrawer";
import { getGameDetail, getGames } from "../../lib/api";
import type { GameDetail, GameSummary, SgpLegInput, SgpSimulationResponse } from "../../lib/types";

export default function GamesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const [stake, setStake] = useState(100);
  const [selectedLegs, setSelectedLegs] = useState<Selection[]>([]);
  const [simulation, setSimulation] = useState<SgpSimulationResponse | null>(null);

  const filters: GameFilters = useMemo(
    () => ({
      team: searchParams.get("team") ?? undefined,
      status: searchParams.get("status") ?? undefined
    }),
    [searchParams]
  );

  const selectedGameIdFromUrl = searchParams.get("gameId");

  const gamesQuery = useQuery<GameSummary[]>({ queryKey: ["games"], queryFn: getGames });

  useEffect(() => {
    if (gamesQuery.isError) {
      toast.error((gamesQuery.error as Error).message);
    }
  }, [gamesQuery.isError, gamesQuery.error]);

  const selectedGameId = useMemo(() => {
    if (!gamesQuery.data || gamesQuery.data.length === 0) {
      return undefined;
    }
    const id = selectedGameIdFromUrl ? Number(selectedGameIdFromUrl) : gamesQuery.data[0].id;
    return Number.isNaN(id) ? gamesQuery.data[0].id : id;
  }, [gamesQuery.data, selectedGameIdFromUrl]);

  useEffect(() => {
    if (gamesQuery.data && gamesQuery.data.length > 0 && !selectedGameIdFromUrl) {
      startTransition(() => {
        const params = new URLSearchParams(searchParams.toString());
        params.set("gameId", gamesQuery.data[0].id.toString());
        router.replace(`?${params.toString()}`, { scroll: false });
      });
    }
  }, [gamesQuery.data, router, searchParams, selectedGameIdFromUrl, startTransition]);

  const gameDetailQuery = useQuery<GameDetail | null>({
    queryKey: ["game-detail", selectedGameId],
    queryFn: () => (selectedGameId ? getGameDetail(selectedGameId) : Promise.resolve(null)),
    enabled: Boolean(selectedGameId)
  });

  useEffect(() => {
    if (gameDetailQuery.isError) {
      toast.error((gameDetailQuery.error as Error).message);
    }
  }, [gameDetailQuery.isError, gameDetailQuery.error]);

  const handleSelectGame = (gameId: number) => {
    startTransition(() => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("gameId", gameId.toString());
      router.replace(`?${params.toString()}`, { scroll: false });
    });
    setSelectedLegs([]);
    setSimulation(null);
  };

  const handleFiltersChange = (nextFilters: GameFilters) => {
    startTransition(() => {
      const params = new URLSearchParams(searchParams.toString());
      if (nextFilters.team) {
        params.set("team", nextFilters.team);
      } else {
        params.delete("team");
      }
      if (nextFilters.status) {
        params.set("status", nextFilters.status);
      } else {
        params.delete("status");
      }
      router.replace(`?${params.toString()}`, { scroll: false });
    });
  };

  const handleToggleLeg = (selection: Selection) => {
    setSelectedLegs((prev) => {
      const exists = prev.some((item) => item.id === selection.id);
      const next = exists ? prev.filter((item) => item.id !== selection.id) : [...prev, selection];
      if (next.length === 0) {
        setSimulation(null);
      }
      return next;
    });
  };

  const handleRemoveLeg = (id: string) => {
    setSelectedLegs((prev) => {
      const next = prev.filter((leg) => leg.id !== id);
      if (next.length === 0) {
        setSimulation(null);
      }
      return next;
    });
  };

  const handleSimulation = (response: SgpSimulationResponse) => {
    setSimulation(response);
  };

  return (
    <div className="grid gap-6">
      {gamesQuery.isLoading ? (
        <LoadingSkeleton lines={6} />
      ) : (
        gamesQuery.data && (
          <GamePicker
            games={gamesQuery.data}
            selectedGameId={selectedGameId}
            onSelect={handleSelectGame}
            filters={filters}
            onFiltersChange={handleFiltersChange}
          />
        )
      )}

      {gameDetailQuery.isLoading && <LoadingSkeleton lines={6} />}
      {gameDetailQuery.data && selectedGameId && (
        <div className="grid gap-6 lg:grid-cols-[2fr,1fr]">
          <div className="space-y-6">
            <MatchupCard game={gameDetailQuery.data} />
            <OddsPanel markets={gameDetailQuery.data.markets} />
            <PropTable
              props={gameDetailQuery.data.props}
              selectedLegIds={selectedLegs.map((leg) => leg.id)}
              onToggleLeg={handleToggleLeg}
              gameId={gameDetailQuery.data.id}
            />
            <WhyDrawer game={gameDetailQuery.data} />
          </div>
          <div className="space-y-6">
            <BetSlip
              legs={selectedLegs}
              stake={stake}
              onStakeChange={setStake}
              onRemoveLeg={handleRemoveLeg}
              simulation={simulation}
            />
            <SgpComposer legs={selectedLegs} onSimulated={handleSimulation} />
          </div>
        </div>
      )}
    </div>
  );
}

type Selection = {
  id: string;
  description: string;
  odds: number;
  leg: SgpLegInput;
};
