"""E-09: whether the claims this project wants to make are answerable at all.

The audit converts a realized comparison into a statement about what that
comparison could ever have detected. These tests pin the conversion down in both
directions — that the floor is consistent with the sample-size arithmetic it
inverts, and that a result sitting under the floor is recorded as undemonstrable
rather than as a discovery.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kalshi_research_bot.evaluation.power import (
    minimum_detectable_score_improvement,
    required_sample_for_score_improvement,
)
from kalshi_research_bot.research_registry import read_experiments, verify_registry
from kalshi_research_bot.sports_power_audit import (
    NFL_VOLUME,
    PUBLISHED_SCHEDULES,
    LeagueVolume,
    audit_detectability,
    combined_volume,
    quote_inflation,
    record_power_audit_experiment,
    render_power_audit_report,
)

# The measured market-blend comparison against the de-vigged reported close,
# from the nflverse archive. Reproduced here so the audit's arithmetic is pinned
# to the numbers the program actually produced.
BLEND_VS_CLOSE = {
    "model": "market_blend_v1",
    "baseline": "devigged_reported_close",
    "sample_size": 4780,
    "mean_difference": -0.00010355756564686896,
    "difference_std": 0.01735812983859151,
    "confidence_interval": [-0.0005956391080325041, 0.00038852397673876614],
    "p_value": 0.6799946297371208,
    "alpha": 0.05,
    "verdict": "inconclusive",
    "metric": "paired_brier_improvement",
}


class MinimumDetectableImprovementTests(unittest.TestCase):
    def test_it_inverts_the_required_sample_calculation(self) -> None:
        """The floor at n is exactly the effect that would have needed n."""
        std = 0.017358
        for sample_size in (250, 1000, 4780):
            detectable = minimum_detectable_score_improvement(
                sample_size=sample_size, difference_std=std
            )
            required = required_sample_for_score_improvement(
                mean_difference=detectable, difference_std=std
            )
            self.assertEqual(required.required_sample, sample_size)

    def test_the_floor_falls_with_the_square_root_of_the_sample(self) -> None:
        """Quadrupling the evidence halves the smallest visible effect, no more."""
        small = minimum_detectable_score_improvement(sample_size=1000, difference_std=0.02)
        large = minimum_detectable_score_improvement(sample_size=4000, difference_std=0.02)
        self.assertAlmostEqual(small / large, 2.0, places=9)

    def test_it_refuses_a_sample_or_spread_it_cannot_use(self) -> None:
        with self.assertRaises(ValueError):
            minimum_detectable_score_improvement(sample_size=0, difference_std=0.02)
        with self.assertRaises(ValueError):
            minimum_detectable_score_improvement(sample_size=100, difference_std=0.0)


class LeagueVolumeTests(unittest.TestCase):
    def test_only_gradable_games_count_as_evidence(self) -> None:
        half = LeagueVolume("nfl", 284.8, 0.5, "test")
        self.assertAlmostEqual(half.gradable_games_per_season(), 142.4)
        self.assertAlmostEqual(half.seasons_for(1424), 10.0)

    def test_pooling_leagues_sums_their_gradable_games(self) -> None:
        pooled = combined_volume(PUBLISHED_SCHEDULES)
        self.assertAlmostEqual(
            pooled.gradable_games_per_season(),
            sum(entry.gradable_games_per_season() for entry in PUBLISHED_SCHEDULES),
        )

    def test_a_pool_is_measured_only_when_every_member_is(self) -> None:
        """One published schedule size makes the whole pool an estimate."""
        self.assertTrue(NFL_VOLUME.measured)
        self.assertFalse(combined_volume(PUBLISHED_SCHEDULES).measured)
        self.assertTrue(combined_volume([NFL_VOLUME]).measured)

    def test_pooling_nothing_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            combined_volume([])


class QuoteInflationTests(unittest.TestCase):
    def test_perfectly_correlated_quotes_collapse_to_the_game_count(self) -> None:
        """Five books quoting one game produce five prices and one outcome."""
        report = quote_inflation(gradable_games=1000, quotes_per_game=5)
        self.assertEqual(report["raw_quote_count"], 5000)
        self.assertAlmostEqual(report["effective_sample"], 1000.0)
        self.assertAlmostEqual(report["inflation_factor"], 5.0)

    def test_uncorrelated_quotes_would_each_count(self) -> None:
        report = quote_inflation(
            gradable_games=1000, quotes_per_game=5, intraclass_correlation=0.0
        )
        self.assertAlmostEqual(report["effective_sample"], 5000.0)


class AuditDetectabilityTests(unittest.TestCase):
    def test_the_measured_blend_result_sits_below_its_own_detectable_floor(self) -> None:
        """The decisive finding: that comparison could never have seen this effect."""
        audit = audit_detectability(BLEND_VS_CLOSE, volume=NFL_VOLUME)

        self.assertEqual(audit["status"], "audited")
        self.assertEqual(audit["realized_sample"], 4780)
        # 4,780 games is already almost seventeen NFL seasons of evidence.
        self.assertAlmostEqual(audit["realized_sample_seasons"], 4780 / 284.8, places=6)
        self.assertLess(abs(audit["observed_mean_difference"]), audit["minimum_detectable_improvement"])
        self.assertLess(audit["observed_over_detectable"], 1.0)

    def test_detecting_the_observed_effect_would_take_centuries(self) -> None:
        audit = audit_detectability(BLEND_VS_CLOSE, volume=NFL_VOLUME)
        smallest = min(audit["score_effect_costs"], key=lambda row: row["paired_brier_improvement"])
        self.assertAlmostEqual(smallest["paired_brier_improvement"], 0.0001)
        self.assertGreater(smallest["seasons_required"], 500)

    def test_a_two_percent_edge_needs_more_seasons_than_a_business_has(self) -> None:
        audit = audit_detectability(BLEND_VS_CLOSE, volume=NFL_VOLUME)
        by_edge = {row["edge_above_break_even"]: row for row in audit["win_rate_edge_costs"]}
        self.assertGreater(by_edge[0.02]["seasons_required"], 15)
        # The inverse-square law, visible: half the edge, four times the bets.
        self.assertAlmostEqual(
            by_edge[0.01]["required_bets"] / by_edge[0.02]["required_bets"], 4.0, places=1
        )

    def test_pooling_every_league_shortens_the_wait_without_removing_it(self) -> None:
        pooled = audit_detectability(BLEND_VS_CLOSE, volume=combined_volume(PUBLISHED_SCHEDULES))
        nfl_only = audit_detectability(BLEND_VS_CLOSE, volume=NFL_VOLUME)
        pooled_1pct = next(
            row for row in pooled["win_rate_edge_costs"] if row["edge_above_break_even"] == 0.01
        )
        nfl_1pct = next(
            row for row in nfl_only["win_rate_edge_costs"] if row["edge_above_break_even"] == 0.01
        )
        self.assertLess(pooled_1pct["seasons_required"], nfl_1pct["seasons_required"])
        # Pooling changes the volume, never the evidence a fixed sample carries.
        self.assertEqual(
            pooled["minimum_detectable_improvement"], nfl_only["minimum_detectable_improvement"]
        )

    def test_a_comparison_with_no_variance_is_refused_rather_than_guessed(self) -> None:
        degenerate = dict(BLEND_VS_CLOSE, difference_std=None, verdict="degenerate_variance")
        audit = audit_detectability(degenerate, volume=NFL_VOLUME)
        self.assertEqual(audit["status"], "no_measured_variance")
        self.assertNotIn("minimum_detectable_improvement", audit)

    def test_a_comparison_with_no_sample_is_refused(self) -> None:
        audit = audit_detectability({"sample_size": 0}, volume=NFL_VOLUME)
        self.assertEqual(audit["status"], "no_realized_sample")

    def test_the_rendering_states_the_floor_and_the_observed_effect(self) -> None:
        text = render_power_audit_report(audit_detectability(BLEND_VS_CLOSE, volume=NFL_VOLUME))
        self.assertIn("Smallest detectable gain", text)
        self.assertIn("Observed difference", text)
        self.assertIn("nfl", text)

    def test_an_unavailable_audit_renders_its_reason(self) -> None:
        text = render_power_audit_report({"status": "no_realized_sample", "reason": "empty"})
        self.assertIn("no_realized_sample", text)


class RecordPowerAuditTests(unittest.TestCase):
    def _registry(self) -> Path:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name) / "registry.jsonl"

    def test_an_effect_under_the_floor_is_recorded_as_rejected(self) -> None:
        path = self._registry()
        audit = audit_detectability(BLEND_VS_CLOSE, volume=NFL_VOLUME)

        entry = record_power_audit_experiment(audit, path=path)

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["decision"], "rejected")
        self.assertIn("E-09", entry["tags"])
        self.assertIn("minimum_detectable_improvement", entry["notes"])
        self.assertTrue(verify_registry(path)["valid"])
        self.assertEqual(len(read_experiments(path)), 1)

    def test_a_demonstrable_effect_is_recorded_with_the_interval_that_showed_it(self) -> None:
        """Elo over a base rate clears its floor, and the registry takes it."""
        path = self._registry()
        strong = {
            "sample_size": 7159,
            "mean_difference": 0.017123255642382033,
            "difference_std": 0.1479174147981703,
            "confidence_interval": [0.013696830740172347, 0.02054968054459172],
            "verdict": "model_better",
            "metric": "paired_brier_improvement",
        }
        audit = audit_detectability(strong, volume=NFL_VOLUME)
        self.assertGreater(audit["observed_over_detectable"], 1.0)

        entry = record_power_audit_experiment(audit, path=path)

        assert entry is not None
        self.assertEqual(entry["decision"], "accepted")
        self.assertEqual(entry["confidence_interval"], strong["confidence_interval"])

    def test_an_effect_over_the_floor_whose_interval_spans_zero_is_still_rejected(self) -> None:
        """The registry's rule and the power floor must both be satisfied."""
        path = self._registry()
        contradictory = dict(BLEND_VS_CLOSE, mean_difference=0.01, confidence_interval=[-0.01, 0.03])
        audit = audit_detectability(contradictory, volume=NFL_VOLUME)
        self.assertGreater(audit["observed_over_detectable"], 1.0)

        entry = record_power_audit_experiment(audit, path=path)

        assert entry is not None
        self.assertEqual(entry["decision"], "rejected")
        self.assertIsNone(entry["confidence_interval"])

    def test_the_recorded_wait_is_priced_from_the_observed_effect(self) -> None:
        """Not from the nearest row of the effect grid, which flatters it.

        The observed -0.000104 needs ~236,000 games, about 830 NFL seasons.
        Snapping up to the grid's 0.0005 row would have reported 33.
        """
        path = self._registry()
        audit = audit_detectability(BLEND_VS_CLOSE, volume=NFL_VOLUME)

        entry = record_power_audit_experiment(audit, path=path)

        assert entry is not None
        note = next(
            part for part in entry["notes"].split("; ")
            if part.startswith("seasons_to_detect_observed_effect=")
        )
        seasons = float(note.split("=")[1])
        self.assertGreater(seasons, 500)

    def test_an_unavailable_audit_records_nothing(self) -> None:
        path = self._registry()
        self.assertIsNone(record_power_audit_experiment({"status": "no_realized_sample"}, path=path))
        self.assertEqual(read_experiments(path), [])


if __name__ == "__main__":
    unittest.main()
