from __future__ import annotations

from itertools import combinations

from ..contracts import ComboResult, TotalLeg
from ..math import adjusted_combo_probability, combo_ev_cents, probability_to_cents


class ComboBot:
    def build_ranked_combos(
        self,
        legs: list[TotalLeg],
        target_probability: float = 0.80,
        min_legs: int = 2,
        max_legs: int = 5,
        max_results: int = 20,
        min_leg_probability: float = 0.75,
    ) -> list[ComboResult]:
        eligible_legs = [
            leg
            for leg in legs
            if leg.model_probability >= min_leg_probability and leg.entry_price_cents > 0
        ]
        results: list[ComboResult] = []
        upper_bound = min(max_legs, len(eligible_legs))
        for size in range(min_legs, upper_bound + 1):
            for selected_legs in combinations(eligible_legs, size):
                probabilities = [leg.model_probability for leg in selected_legs]
                contexts = [f"{leg.sport}:{leg.event_name}" for leg in selected_legs]
                raw_probability, adjusted_probability, penalty = adjusted_combo_probability(probabilities, contexts)
                average_entry = sum(leg.entry_price_cents for leg in selected_legs) / len(selected_legs)
                fair_price = probability_to_cents(adjusted_probability)
                ev = combo_ev_cents(adjusted_probability, average_entry)
                result = ComboResult(
                    combo_id="+".join(leg.leg_id for leg in selected_legs),
                    legs=list(selected_legs),
                    raw_probability=raw_probability,
                    adjusted_probability=adjusted_probability,
                    correlation_penalty=penalty,
                    average_entry_price_cents=round(average_entry, 2),
                    fair_price_cents=fair_price,
                    expected_value_cents=ev,
                    meets_target=adjusted_probability >= target_probability,
                    notes=[
                        f"target={target_probability:.0%}",
                        f"min_leg_probability={min_leg_probability:.0%}",
                    ],
                )
                if result.meets_target:
                    results.append(result)
        return sorted(
            results,
            key=lambda result: (result.expected_value_cents, result.adjusted_probability),
            reverse=True,
        )[:max_results]
