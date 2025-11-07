"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import toast from "react-hot-toast";
import { getProps } from "../../lib/api";
import { PropTable } from "../../components/PropTable";
import { BetSlip } from "../../components/BetSlip";
import { SgpComposer } from "../../components/SgpComposer";
import { LoadingSkeleton } from "../../components/LoadingSkeleton";
import type { SimulationResponse } from "../../lib/types";

export default function PropsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const [stake, setStake] = useState(50);
  const [selectedLegs, setSelectedLegs] = useState<{ id: string; description: string; odds: number }[]>([]);
  const [jointProbability, setJointProbability] = useState<number | undefined>();

  const marketFilter = searchParams.get("market") ?? undefined;

  const propsQuery = useQuery({ queryKey: ["props", "all"], queryFn: () => getProps() });

  useEffect(() => {
    if (propsQuery.isError) {
      toast.error((propsQuery.error as Error).message);
    }
  }, [propsQuery.isError, propsQuery.error]);

  const markets = useMemo(() => {
    if (!propsQuery.data) return [];
    return Array.from(new Set(propsQuery.data.map((prop) => prop.market))).sort();
  }, [propsQuery.data]);

  const filteredProps = useMemo(() => {
    if (!propsQuery.data) return [];
    return marketFilter ? propsQuery.data.filter((prop) => prop.market === marketFilter) : propsQuery.data;
  }, [propsQuery.data, marketFilter]);

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
        <section className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/70">
          <div>
            <div className="text-xs uppercase tracking-wide text-white/40">Filter</div>
            <div className="text-white">Market type</div>
          </div>
          <select value={marketFilter ?? ""} onChange={(event) => handleMarketChange(event.target.value || undefined)}>
            <option value="">All markets</option>
            {markets.map((market) => (
              <option key={market} value={market}>
                {market}
              </option>
            ))}
          </select>
        </section>
        {propsQuery.isLoading && <LoadingSkeleton lines={6} />}
        {filteredProps.length > 0 && (
          <PropTable props={filteredProps} selectedLegIds={selectedLegs.map((leg) => leg.id)} onToggleLeg={handleToggleLeg} />
        )}
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
  );
}
