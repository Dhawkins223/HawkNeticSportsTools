import type { BdlStatus } from "../lib/api";

export function LiveApiStatusPanel({ status }: { status?: BdlStatus }) {
  const counts = status?.counts || {};
  return <div className="panel" id="live-api-data"><h3>Ball Don&apos;t Lie API</h3><div className="statRow"><span>{counts.teams || 0} teams</span><span>{counts.players || 0} players</span><span>{counts.games || 0} games</span></div><p>BDL data is stored separately and linked through identity maps.</p></div>;
}
