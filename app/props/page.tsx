"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import toast from "react-hot-toast";
import { GamePicker, type GameFilters } from "../../components/GamePicker";
import { PropTable } from "../../components/PropTable";
import { BetSlip } from "../../components/BetSlip";
import { SgpComposer } from "../../components/SgpComposer";
import { LoadingSkeleton } from "../../components/LoadingSkeleton";
import { getGameDetail, getGames } from "../../lib/api";
import type { GameDetail, GameSummary, SgpLegInput, SgpSimulationResponse } from "../../lib/types";

export default function PropsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const [stake, setStake] = useState(50);
  const [selectedLegs, setSelectedLegs] = useState<Selection[]>([]);
  const [simulation, setSimulation] = useState<SgpSimulationResponse | null>(null);

  const filters: GameFilters = useMemo(
    () => ({
      team: searchParams.get("team") ?? undefined,
      status: searchParams.get("status") ?? undefined
    }),
    [searchParams]
  );

  const marketFilter = searchParams.get("market") ?? undefined;
  const selectedGameIdFromUrl = searchParams.get("gameId");

  const gamesQuery = useQuery<GameSummary[]>({ queryKey: ["props-games"], queryFn: getGames });

  useEffect(() => {
    if (gamesQuery.isError) {
      toast.error((gamesQuery.error as Error).message);
    }
  }, [gamesQuery.isError, gamesQuery.error]);

  const selectedGameId = useMemo(() => {
    if (!gamesQuery.data || gamesQuery.data.length === 0) return undefined;
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
    queryKey: ["props-game-detail", selectedGameId],
    queryFn: () => (selectedGameId ? getGameDetail(selectedGameId) : Promise.resolve(null)),
    enabled: Boolean(selectedGameId)
  });

  useEffect(() => {
    if (gameDetailQuery.isError) {
      toast.error((gameDetailQuery.error as Error).message);
    }
  }, [gameDetailQuery.isError, gameDetailQuery.error]);

  const propsForDisplay = useMemo(() => {
    if (!gameDetailQuery.data) return [];
    return marketFilter
      ? gameDetailQuery.data.props.filter((prop) => prop.market === marketFilter)
      : gameDetailQuery.data.props;
  }, [gameDetailQuery.data, marketFilter]);

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

  const handleMarketChange = (market?: string) => {
    startTransition(() => {
      const params = new URLSearchParams(searchParams.toString());
      if (market) {
        params.set("market", market);
      } else {
        params.delete("market");
      }
      router.replace(`?${params.toString()}`, { scroll: false });
    });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr,1fr]">
      <div className="space-y-6">
        {gamesQuery.isLoading ? (
          <LoadingSkeleton lines={4} />
        ) : (
          gamesQuery.data && (
            <GamePicker
              games={gamesQuery.data}
              selectedGameId={selectedGameId}
              onSelect={(id) => {
                const params = new URLSearchParams(searchParams.toString());
                params.set("gameId", id.toString());
                router.replace(`?${params.toString()}`, { scroll: false });
                setSelectedLegs([]);
                setSimulation(null);
              }}
              filters={filters}
              onFiltersChange={handleFiltersChange}
            />
          )
        )}

        <section className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/70">
          <div>
            <div className="text-xs uppercase tracking-wide text-white/40">Filter</div>
            <div className="text-white">Market type</div>
          </div>
          <select value={marketFilter ?? ""} onChange={(event) => handleMarketChange(event.target.value || undefined)}>
            <option value="">All markets</option>
            {gameDetailQuery.data &&
              Array.from(new Set(gameDetailQuery.data.props.map((prop) => prop.market))).map((market) => (
                <option key={market} value={market}>
                  {market}
                </option>
              ))}
          </select>
        </section>

        {gameDetailQuery.isLoading && <LoadingSkeleton lines={6} />}
        {gameDetailQuery.data && propsForDisplay.length > 0 && (
          <PropTable
            props={propsForDisplay}
            selectedLegIds={selectedLegs.map((leg) => leg.id)}
            onToggleLeg={handleToggleLeg}
            gameId={gameDetailQuery.data.id}
          />
        )}
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
  );
}

type Selection = {
  id: string;
  description: string;
  odds: number;
  leg: SgpLegInput;
};
