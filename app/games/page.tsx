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
import { EvTable } from "../../components/EvTable";
import { getGames, getProps, getTickets } from "../../lib/api";
import type { Game, SimulationResponse } from "../../lib/types";

export default function GamesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const [stake, setStake] = useState(100);
  const [selectedLegs, setSelectedLegs] = useState<{ id: string; description: string; odds: number }[]>([]);
  const [jointProbability, setJointProbability] = useState<number | undefined>();

  const filters: GameFilters = useMemo(
    () => ({
      team: searchParams.get("team") ?? undefined,
      status: searchParams.get("status") ?? undefined
    }),
    [searchParams]
  );

  const selectedGameIdFromUrl = searchParams.get("gameId") ?? undefined;

  const gamesQuery = useQuery({ queryKey: ["games"], queryFn: getGames });

  useEffect(() => {
    if (gamesQuery.isError) {
      toast.error((gamesQuery.error as Error).message);
    }
  }, [gamesQuery.isError, gamesQuery.error]);

  const selectedGame: Game | undefined = useMemo(() => {
    if (!gamesQuery.data || gamesQuery.data.length === 0) {
      return undefined;
    }
    if (selectedGameIdFromUrl) {
      return gamesQuery.data.find((game) => game.id === selectedGameIdFromUrl) ?? gamesQuery.data[0];
    }
    return gamesQuery.data[0];
  }, [gamesQuery.data, selectedGameIdFromUrl]);

  useEffect(() => {
    if (gamesQuery.data && gamesQuery.data.length > 0 && !selectedGameIdFromUrl) {
      startTransition(() => {
        const params = new URLSearchParams(searchParams.toString());
        params.set("gameId", gamesQuery.data[0].id);
        router.replace(`?${params.toString()}`, { scroll: false });
      });
    }
  }, [gamesQuery.data, router, searchParams, selectedGameIdFromUrl, startTransition]);

  const propsQuery = useQuery({
    queryKey: ["props", selectedGame?.id],
    queryFn: () => getProps(selectedGame?.id),
    enabled: Boolean(selectedGame?.id)
  });

  useEffect(() => {
    if (propsQuery.isError) {
      toast.error((propsQuery.error as Error).message);
    }
  }, [propsQuery.isError, propsQuery.error]);

  const ticketsQuery = useQuery({ queryKey: ["tickets"], queryFn: getTickets });

  useEffect(() => {
    if (ticketsQuery.isError) {
      toast.error((ticketsQuery.error as Error).message);
    }
  }, [ticketsQuery.isError, ticketsQuery.error]);

  const handleSelectGame = (gameId: string) => {
    startTransition(() => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("gameId", gameId);
      router.replace(`?${params.toString()}`, { scroll: false });
    });
    setSelectedLegs([]);
    setJointProbability(undefined);
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

  const handleToggleLeg = (leg: { id: string; description: string; odds: number }) => {
    setSelectedLegs((prev) => {
      const exists = prev.some((item) => item.id === leg.id);
      const next = exists ? prev.filter((item) => item.id !== leg.id) : [...prev, leg];
      if (next.length === 0) {
        setJointProbability(undefined);
      }
      return next;
    });
  };

  const handleRemoveLeg = (id: string) => {
    setSelectedLegs((prev) => {
      const next = prev.filter((leg) => leg.id !== id);
      if (next.length === 0) {
        setJointProbability(undefined);
      }
      return next;
    });
  };

  const handleSimulation = (response: SimulationResponse) => {
    setJointProbability(response.joint.p_joint);
  };

  return (
    <div className="grid gap-6">
      {gamesQuery.isLoading ? (
        <LoadingSkeleton lines={6} />
      ) : (
        gamesQuery.data && (
          <GamePicker
            games={gamesQuery.data}
            selectedGameId={selectedGame?.id}
            onSelect={handleSelectGame}
            filters={filters}
            onFiltersChange={handleFiltersChange}
          />
        )
      )}

      {selectedGame && (
        <div className="grid gap-6 lg:grid-cols-[2fr,1fr]">
          <div className="space-y-6">
            <MatchupCard game={selectedGame} />
            <OddsPanel odds={selectedGame.odds} />
            {propsQuery.isLoading && <LoadingSkeleton lines={8} />}
            {propsQuery.data && (
              <PropTable
                props={propsQuery.data}
                selectedLegIds={selectedLegs.map((leg) => leg.id)}
                onToggleLeg={handleToggleLeg}
              />
            )}
            <WhyDrawer game={selectedGame} />
          </div>
          <div className="space-y-6">
            <BetSlip
              legs={selectedLegs}
              stake={stake}
              onStakeChange={setStake}
              onRemoveLeg={handleRemoveLeg}
              jointProbability={jointProbability}
            />
            <SgpComposer legs={selectedLegs} onSimulated={handleSimulation} />
          </div>
        </div>
      )}

      {ticketsQuery.isLoading && <LoadingSkeleton lines={4} />}
      {ticketsQuery.data && ticketsQuery.data.length > 0 && <EvTable tickets={ticketsQuery.data} />}
    </div>
  );
}
