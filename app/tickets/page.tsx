"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { getTickets } from "../../lib/api";
import { EvTable } from "../../components/EvTable";
import { LoadingSkeleton } from "../../components/LoadingSkeleton";

export default function TicketsPage() {
  const ticketsQuery = useQuery({ queryKey: ["tickets"], queryFn: getTickets });

  useEffect(() => {
    if (ticketsQuery.isError) {
      toast.error((ticketsQuery.error as Error).message);
    }
  }, [ticketsQuery.isError, ticketsQuery.error]);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold text-white">Tickets board</h2>
        <p className="text-sm text-white/60">
          Highlighting the top +EV tickets surfaced by the simulation engine.
        </p>
      </header>
      {ticketsQuery.isLoading && <LoadingSkeleton lines={5} />}
      {ticketsQuery.data && <EvTable tickets={ticketsQuery.data} />}
    </div>
  );
}
