import type { Player } from "../lib/api";

export function PlayerSearch({ players }: { players: Player[] }) {
  return <div className="panel"><h3>Player Search</h3><input placeholder="Search players loaded from FastAPI" onChange={() => undefined} /><ul className="compactList">{players.slice(0, 8).map((p) => <li key={p.id}>{p.full_name}<span>{p.team_abbr || p.position || "NBA"}</span></li>)}</ul></div>;
}
