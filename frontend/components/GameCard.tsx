import type { Game } from "../lib/api";

export function GameCard({ game }: { game: Game }) {
  return <article className="miniCard"><strong>{game.visitor_team_name || game.visitor_team_abbr || "Visitor"} @ {game.home_team_name || game.home_team_abbr || "Home"}</strong><span>{game.status || "Scheduled"}</span><small>{game.game_date || "Date pending"}</small></article>;
}
