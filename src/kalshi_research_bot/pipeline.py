from __future__ import annotations

from .contracts import Game, MarketQuote
from .agents import EdgeBot, ModelBot


class ResearchPipeline:
    """Explicit baseline experiments; canonical model routing lives elsewhere."""

    def __init__(self, *, baseline_only: bool = False) -> None:
        self.baseline_only = baseline_only
        self.model_bot = ModelBot()
        self.edge_bot = EdgeBot()

    def run(self, games: list[Game], quotes: list[MarketQuote], min_edge_cents: float = 0.0):
        if not self.baseline_only:
            raise ValueError(
                "Canonical model selection is unresolved. This pipeline requires "
                "explicit baseline_only=True for an unvalidated baseline experiment."
            )
        predictions = {game.game_id: self.model_bot.predict_home_win(game) for game in games}
        edges = []
        for quote in quotes:
            prediction = predictions.get(quote.game_id)
            if prediction:
                edges.extend(self.edge_bot.evaluate(quote, prediction, min_edge_cents=min_edge_cents))
        return sorted(edges, key=lambda edge: edge.expected_value_cents, reverse=True)
