"""The slip engine's job is to be right about arithmetic and honest about the rest.

Two kinds of test here, and the distinction matters. The exact ones pin
quantities that have a closed form -- break-even, the independent product, the
copula's behaviour at its limits -- and they assert equality. The simulation
tests assert against analytic values within a stated tolerance derived from the
draw count, never against a recorded output, because a test that pins a Monte
Carlo result to whatever it printed once is a test of the seed, not the maths.
"""

from __future__ import annotations

import unittest
from math import prod

from kalshi_research_bot.slip_analysis import (
    CorrelationModel,
    SlipLeg,
    analyze_slip,
    break_even_probability,
    combined_decimal_odds,
    correlation_matrix,
    count_correlated_pairs,
    factor_correlation,
    independent_probability,
    UnmodellableSlip,
    conflicting_pairs,
    legs_from_board,
    recommend_trim,
    risk_tier,
    simulate_correlation_adjustment,
    simulate_slip,
)


def leg(
    leg_id: str = "L1",
    *,
    odds: float = 2.0,
    p: float = 0.5,
    event: str = "",
    league: str = "",
    team: str = "",
) -> SlipLeg:
    return SlipLeg(
        leg_id=leg_id,
        selection=leg_id,
        decimal_odds=odds,
        fair_probability=p,
        event_id=event or f"event_{leg_id}",
        league=league,
        team=team,
    )


NOW = "2026-06-25T18:00:00+00:00"
FRESH = {"quoted_at": "2026-06-25T17:45:00+00:00", "source_state": "fresh"}


def independent_legs(count: int, *, odds: float = 2.0, p: float = 0.5) -> list[SlipLeg]:
    """Legs sharing nothing, so the copula must reproduce independence."""
    return [leg(f"L{i}", odds=odds, p=p, event=f"e{i}", league=f"lg{i}") for i in range(count)]


def correlated_legs(count: int, *, odds: float = 2.0, p: float = 0.5) -> list[SlipLeg]:
    """Legs on distinct games that share a team, so the joint must be simulated.

    Distinct events and distinct markets keep the slip modellable; the shared
    team is what gives the correlation matrix something off-diagonal, which is
    the only case where a Monte Carlo actually runs.
    """
    return [
        leg(f"C{i}", odds=odds, p=p, event=f"e{i}", league=f"lg{i}", team="shared")
        for i in range(count)
    ]


class ExactArithmeticTests(unittest.TestCase):
    """No estimation involved, so these assert equality."""

    def test_break_even_is_the_reciprocal_of_combined_odds(self) -> None:
        legs = independent_legs(5)
        self.assertEqual(combined_decimal_odds(legs), 32.0)
        self.assertEqual(break_even_probability(legs), 1 / 32)

    def test_break_even_matches_the_price_a_slip_is_sold_at(self) -> None:
        """A $4.99 stake returning $106.38 needs 4.69%, as the product states."""
        odds = 106.38 / 4.99
        self.assertAlmostEqual(1 / odds, 0.046907, places=6)

    def test_a_single_leg_break_even_is_one_over_its_own_odds(self) -> None:
        self.assertAlmostEqual(leg(odds=1.40).break_even, 0.714286, places=6)
        self.assertAlmostEqual(leg(odds=1.909).break_even, 0.523834, places=6)

    def test_edge_is_the_de_vigged_probability_less_its_price(self) -> None:
        # Odds written exactly: -250 is 1.4, -120 is 1 + 100/120, not 1.833.
        self.assertAlmostEqual(leg(odds=1.40, p=0.763).edge, 0.048714, places=6)
        self.assertAlmostEqual(leg(odds=1 + 100 / 120, p=0.472).edge, -0.073455, places=6)

    def test_independent_probability_is_the_plain_product(self) -> None:
        legs = independent_legs(4, p=0.6)
        self.assertAlmostEqual(independent_probability(legs), 0.6**4, places=12)

    def test_an_empty_slip_is_refused_rather_than_defaulted(self) -> None:
        for call in (break_even_probability, independent_probability):
            with self.assertRaises(ValueError):
                call([])

    def test_a_leg_priced_at_or_below_evens_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            SlipLeg(leg_id="x", selection="x", decimal_odds=1.0, fair_probability=0.5)

    def test_an_impossible_probability_is_refused(self) -> None:
        for bad in (0.0, 1.0, -0.2, 1.4):
            with self.assertRaises(ValueError):
                SlipLeg(leg_id="x", selection="x", decimal_odds=2.0, fair_probability=bad)


class CorrelationMatrixTests(unittest.TestCase):
    def test_legs_in_one_game_take_the_same_event_correlation(self) -> None:
        legs = [leg("A", event="g1"), leg("B", event="g1")]
        self.assertEqual(correlation_matrix(legs)[0][1], CorrelationModel().same_event)

    def test_precedence_runs_event_then_team_then_league(self) -> None:
        model = CorrelationModel()
        same_team = [leg("A", event="g1", team="LAL"), leg("B", event="g2", team="LAL")]
        same_slate = [
            SlipLeg(leg_id="A", selection="A", decimal_odds=2.0, fair_probability=0.5,
                    event_id="g1", league="NBA", slate="2026-06-25"),
            SlipLeg(leg_id="B", selection="B", decimal_odds=2.0, fair_probability=0.5,
                    event_id="g2", league="NBA", slate="2026-06-25"),
        ]
        self.assertEqual(correlation_matrix(same_team, model)[0][1], model.same_team)
        self.assertEqual(correlation_matrix(same_slate, model)[0][1], model.same_league_same_slate)

    def test_one_league_on_different_days_is_not_correlated(self) -> None:
        """The coefficient is a same-slate effect; a shared league alone is not one."""
        apart = [
            SlipLeg(leg_id="A", selection="A", decimal_odds=2.0, fair_probability=0.5,
                    event_id="g1", league="NBA", slate="2026-01-05"),
            SlipLeg(leg_id="B", selection="B", decimal_odds=2.0, fair_probability=0.5,
                    event_id="g2", league="NBA", slate="2026-06-25"),
        ]
        self.assertEqual(correlation_matrix(apart)[0][1], 0.0)

    def test_unrelated_legs_are_uncorrelated(self) -> None:
        legs = [leg("A", event="g1", league="NBA"), leg("B", event="g2", league="MLB")]
        self.assertEqual(correlation_matrix(legs)[0][1], 0.0)

    def test_the_matrix_is_symmetric_with_a_unit_diagonal(self) -> None:
        legs = [leg("A", event="g1"), leg("B", event="g1"), leg("C", event="g2", league="X")]
        matrix = correlation_matrix(legs)
        for i in range(3):
            self.assertEqual(matrix[i][i], 1.0)
            for j in range(3):
                self.assertEqual(matrix[i][j], matrix[j][i])

    def test_an_admissible_matrix_needs_no_shrinkage(self) -> None:
        _, shrinkage = factor_correlation(correlation_matrix(independent_legs(4)))
        self.assertEqual(shrinkage, 0.0)

    def test_an_incoherent_matrix_is_shrunk_rather_than_accepted(self) -> None:
        """Pairwise rules can describe a joint distribution that cannot exist."""
        impossible = [[1.0, 0.95, -0.95], [0.95, 1.0, 0.95], [-0.95, 0.95, 1.0]]
        factored, shrinkage = factor_correlation(impossible)
        self.assertGreater(shrinkage, 0.0)
        self.assertEqual(len(factored), 3)

    def test_only_meaningfully_correlated_pairs_are_counted(self) -> None:
        legs = [leg("A", event="g1"), leg("B", event="g1"), leg("C", event="g2", league="X")]
        # One same-event pair clears the threshold; the league-only pairs do not.
        self.assertEqual(count_correlated_pairs(legs), 1)


class SimulationTests(unittest.TestCase):
    """Asserted against analytic truth within Monte Carlo tolerance."""

    def test_uncorrelated_legs_reproduce_the_independent_product(self) -> None:
        legs = independent_legs(5)
        report = simulate_slip(legs, draws=40_000)
        exact = independent_probability(legs)
        # Four standard errors: fails on a real bug, not on sampling noise.
        self.assertLess(
            abs(report["hit_probability"] - exact), 4 * report["standard_error"] + 1e-9
        )

    def test_near_perfect_correlation_collapses_to_a_single_leg(self) -> None:
        """Five legs that always agree are worth one leg, not one to the fifth."""
        legs = [leg(f"S{i}", p=0.5, event="same") for i in range(5)]
        report = simulate_slip(legs, model=CorrelationModel(same_event=0.995), draws=40_000)
        self.assertGreater(report["hit_probability"], 0.40)
        self.assertLess(report["hit_probability"], 0.52)

    def test_correlation_lifts_a_parlay_above_the_naive_product(self) -> None:
        legs = [leg(f"S{i}", p=0.6, event="same") for i in range(4)]
        correlated = simulate_slip(legs, model=CorrelationModel(same_event=0.6), draws=20_000)
        self.assertGreater(correlated["hit_probability"], independent_probability(legs))

    def test_the_marginals_survive_the_copula(self) -> None:
        """Correlation changes joint behaviour only; each leg keeps its own price."""
        legs = [leg(f"S{i}", p=0.62, event="same") for i in range(4)]
        report = simulate_slip(legs, model=CorrelationModel(same_event=0.7), draws=40_000)
        for rate in report["realized_leg_rates"]:
            self.assertAlmostEqual(rate, 0.62, delta=0.02)

    def test_the_same_slip_always_returns_the_same_answer(self) -> None:
        legs = independent_legs(4)
        self.assertEqual(
            simulate_slip(legs, draws=3_000)["hit_probability"],
            simulate_slip(legs, draws=3_000)["hit_probability"],
        )

    def test_a_different_seed_moves_the_answer_only_within_noise(self) -> None:
        legs = independent_legs(4)
        a = simulate_slip(legs, draws=20_000, seed=1)
        b = simulate_slip(legs, draws=20_000, seed=2)
        self.assertLess(abs(a["hit_probability"] - b["hit_probability"]), 0.01)

    def test_more_draws_tighten_the_interval(self) -> None:
        legs = independent_legs(4)
        wide = simulate_slip(legs, draws=1_000)
        tight = simulate_slip(legs, draws=25_000)
        self.assertLess(tight["standard_error"], wide["standard_error"])

    def test_a_slip_with_no_draws_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            simulate_slip(independent_legs(2), draws=0)


class IndependenceErrorTests(unittest.TestCase):
    """Backlog E-44, evaluated on whatever slip is in front of it."""

    def test_correlated_legs_make_independent_multiplication_wrong(self) -> None:
        legs = [leg(f"S{i}", p=0.55, event="same") for i in range(6)]
        report = analyze_slip(legs, model=CorrelationModel(same_event=0.5), draws=20_000)
        self.assertGreater(report["independence_error"], 0.0)
        self.assertGreater(report["independence_error_ratio"], 2.0)

    def test_uncorrelated_legs_make_it_very_nearly_right(self) -> None:
        report = analyze_slip(independent_legs(5), draws=40_000)
        self.assertAlmostEqual(report["independence_error_ratio"], 1.0, delta=0.12)


class AnalyzeSlipTests(unittest.TestCase):
    def test_the_report_carries_its_own_research_only_labels(self) -> None:
        """These travel with the numbers so they cannot be rendered without them."""
        report = analyze_slip(independent_legs(3), draws=2_000)
        self.assertEqual(report["evidence_class"], "market_derived_arithmetic")
        self.assertEqual(report["model_state"], "baseline_only")
        self.assertEqual(report["decision_status"], "track_only")

    def test_the_correlation_model_is_reported_as_an_assumption(self) -> None:
        report = analyze_slip(independent_legs(3), draws=1_000)
        self.assertFalse(report["correlation_model"]["measured"])
        self.assertEqual(report["correlation_model"]["source"], "structural_assumption")

    def test_payout_and_expected_value_agree_with_the_stake(self) -> None:
        legs = independent_legs(3)
        report = analyze_slip(legs, stake=10.0, draws=20_000)
        self.assertAlmostEqual(report["payout_if_won"], 10.0 * 8.0, places=9)
        expected = report["hit_probability"] * (80.0 - 10.0) - (1 - report["hit_probability"]) * 10.0
        self.assertAlmostEqual(report["expected_value"], expected, places=9)

    def test_a_slip_priced_below_its_odds_is_told_to_trim(self) -> None:
        """Ten legs at a hair under fair value: the product says so."""
        legs = [leg(f"L{i}", odds=2.0, p=0.44, event=f"e{i}", league=f"lg{i}") for i in range(10)]
        report = analyze_slip(legs, draws=20_000)
        self.assertEqual(report["verdict"], "trim_slip")
        self.assertLess(report["edge_over_break_even"], 0.0)

    def test_a_genuinely_priced_slip_is_not_told_to_trim(self) -> None:
        legs = [leg(f"L{i}", odds=2.0, p=0.62, event=f"e{i}", league=f"lg{i}") for i in range(3)]
        report = analyze_slip(legs, draws=20_000)
        self.assertIn(report["verdict"], {"strong_value", "playable"})

    def test_a_zero_or_negative_stake_is_refused(self) -> None:
        for bad in (0.0, -5.0):
            with self.assertRaises(ValueError):
                analyze_slip(independent_legs(2), stake=bad)


class PrecisionTests(unittest.TestCase):
    """A long slip is a deep-tail event, and a fixed draw count stops working.

    Relative error on a simulated proportion goes as 1/sqrt(hits), so the same
    10,000 draws that pin a 4% parlay to a tenth of a point leave a 0.05% one
    swinging by a third between seeds. The report says which it is.

    These use *correlated* legs deliberately. A slip whose legs share nothing is
    not simulated at all -- the two paths cannot disagree, so the answer is the
    closed-form product -- and grading a known-exact number by hit count would
    be meaningless.
    """

    def test_a_slip_sharing_nothing_is_exact_rather_than_graded(self) -> None:
        legs = independent_legs(12, odds=1.91, p=0.55)
        report = analyze_slip(legs, draws=10_000)
        self.assertEqual(report["precision"], "exact")
        # Exact equality: no estimate is involved, even 12 legs deep.
        self.assertEqual(report["hit_probability"], independent_probability(legs))
        self.assertEqual(report["independence_error"], 0.0)

    def test_a_shallow_slip_is_estimated_well_at_the_default_draws(self) -> None:
        report = analyze_slip(correlated_legs(6, odds=1.91, p=0.55), draws=10_000)
        self.assertIn(report["precision"], {"good", "usable"})

    def test_a_deep_tail_slip_reports_that_it_cannot_be_estimated(self) -> None:
        # p=0.30 rather than 0.55: correlation lifts a deep-tail slip
        # substantially, so a 12-leg slip at 0.55 is no longer deep-tail once
        # the legs share a team. It lands around 15 hits per 10,000 draws here.
        report = analyze_slip(correlated_legs(12, odds=1.91, p=0.30), draws=10_000)
        self.assertEqual(report["precision"], "insufficient_draws")
        self.assertLess(report["simulation"]["correlated_hits"], 30)

    def test_more_draws_restore_the_estimate(self) -> None:
        legs = correlated_legs(12, odds=1.91, p=0.30)
        self.assertNotEqual(analyze_slip(legs, draws=400_000)["precision"], "insufficient_draws")

    def test_precision_follows_the_hit_count_not_the_draw_count(self) -> None:
        from kalshi_research_bot.slip_analysis import _precision

        self.assertEqual(_precision(500), "good")
        self.assertEqual(_precision(150), "usable")
        self.assertEqual(_precision(50), "coarse")
        self.assertEqual(_precision(5), "insufficient_draws")


class UnbiasednessTests(unittest.TestCase):
    """The simulator must not systematically miss the analytic answer.

    Checked by pooling seeds rather than trusting one: a single deep-tail run
    swings far enough that any individual seed can look like a bug.
    """

    def test_pooled_seeds_recover_the_independent_product(self) -> None:
        legs = independent_legs(8, odds=1.91, p=0.55)
        exact = independent_probability(legs)
        estimates = [
            simulate_slip(legs, draws=40_000, seed=seed)["hit_probability"] for seed in range(8)
        ]
        pooled = sum(estimates) / len(estimates)
        self.assertAlmostEqual(pooled / exact, 1.0, delta=0.10)


class CorrelationAdjustmentTests(unittest.TestCase):
    """The adjustment is a difference, and needs its own error bar.

    Estimating the correlated joint on its own and subtracting the product
    differences two numbers near 0.85 whose Monte Carlo error swamps the gap
    between them. ``simulate_correlation_adjustment`` evaluates both outcomes on
    the same draws and takes the independent side from the exact product, so the
    error scales with how often the two disagree instead.
    """

    def correlated_pair(self) -> list[SlipLeg]:
        return [
            SlipLeg("a", "A", 1 / 0.93, 0.93, event_id="e1", team="LAL", market="m1"),
            SlipLeg("b", "B", 1 / 0.91, 0.91, event_id="e2", team="LAL", market="m2"),
        ]

    def test_the_independent_part_is_exact_not_simulated(self) -> None:
        legs = self.correlated_pair()
        report = simulate_correlation_adjustment(legs, draws=2_000, seed=1)
        # Exact equality: this number is the product, never an estimate of it.
        self.assertEqual(report["independent_probability"], independent_probability(legs))
        self.assertAlmostEqual(
            report["hit_probability"],
            report["independent_probability"] + report["correlation_adjustment"],
            places=12,
        )

    def test_uncorrelated_legs_give_exactly_zero_adjustment(self) -> None:
        """With an identity correlation matrix the two outcomes never disagree."""

        report = simulate_correlation_adjustment(independent_legs(4), draws=2_000, seed=1)
        self.assertEqual(report["correlation_adjustment"], 0.0)
        self.assertEqual(report["disagreement_rate"], 0.0)
        self.assertEqual(report["adjustment_standard_error"], 0.0)
        self.assertEqual(report["hit_probability"], report["independent_probability"])
        self.assertEqual(report["precision"], "exact")
        # Resolved, not unresolved: an exact zero is known, not undetermined.
        self.assertTrue(report["adjustment_resolved"])

    def test_positive_correlation_raises_the_joint(self) -> None:
        """The sign the superseded penalty had backwards, at enough draws to resolve it."""

        report = simulate_correlation_adjustment(self.correlated_pair(), draws=60_000, seed=4)
        self.assertGreater(report["correlation_adjustment"], 0.0)
        self.assertTrue(report["adjustment_resolved"])
        self.assertGreater(report["hit_probability"], report["independent_probability"])

    def test_too_few_draws_to_disagree_is_not_the_same_as_exact(self) -> None:
        """A sampling zero must not be reported as a structural one.

        At 60 draws a correlated pair can happen to produce no disagreement at
        all, and reading "exact" off that zero would call a simulated slip
        precisely known on the strength of having barely simulated it. The
        discriminator is the correlation matrix, not the draw count.
        """

        report = simulate_correlation_adjustment(self.correlated_pair(), draws=60, seed=1)
        self.assertFalse(report["structurally_independent"])
        self.assertNotEqual(report["precision"], "exact")

    def test_an_unresolvable_adjustment_says_so(self) -> None:
        """Too few draws must be reported as unresolved, not passed off as a measurement."""

        report = simulate_correlation_adjustment(self.correlated_pair(), draws=60, seed=1)
        self.assertFalse(report["adjustment_resolved"])
        # Unresolved means exactly this: the interval still contains zero, so
        # the sign of the adjustment is not established.
        low, high = report["adjustment_confidence_interval"]
        self.assertLessEqual(low, 0.0)
        self.assertGreaterEqual(high, 0.0)

    def test_the_estimator_is_unbiased_against_a_long_reference_run(self) -> None:
        """Pooled short runs must land on a long run's answer.

        Pooled rather than single-seed: one run of a difference this small is
        not evidence about bias in either direction.
        """

        legs = self.correlated_pair()
        reference = simulate_correlation_adjustment(legs, draws=400_000, seed=99)
        estimates = [
            simulate_correlation_adjustment(legs, draws=20_000, seed=seed)["correlation_adjustment"]
            for seed in range(24)
        ]
        pooled = sum(estimates) / len(estimates)
        self.assertAlmostEqual(
            pooled,
            reference["correlation_adjustment"],
            delta=4.0 * reference["adjustment_standard_error"] + 0.0008,
        )

    def test_a_mutually_exclusive_pair_is_refused_here_too(self) -> None:
        legs = [
            SlipLeg("a", "home", 2.0, 0.5, event_id="g1", market="moneyline"),
            SlipLeg("b", "away", 2.0, 0.5, event_id="g1", market="moneyline"),
        ]
        with self.assertRaises(UnmodellableSlip):
            simulate_correlation_adjustment(legs, draws=100, seed=1)


class StakeValidationTests(unittest.TestCase):
    def test_a_non_finite_stake_is_refused_at_the_math_boundary(self) -> None:
        legs = independent_legs(2)
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                analyze_slip(legs, stake=bad, draws=100)

    def test_a_non_positive_stake_is_refused(self) -> None:
        legs = independent_legs(2)
        for bad in (0.0, -1.0):
            with self.assertRaises(ValueError):
                analyze_slip(legs, stake=bad, draws=100)


class SameEventRepricingTests(unittest.TestCase):
    """The guard against the engine's own most flattering output.

    Correlation genuinely lifts a same-game parlay above the independent product.
    Combining that lift with *standalone* leg prices then manufactures enormous
    expected value that no book would sell, so the value is marked unachievable
    and the verdict withheld rather than reported as an edge.
    """

    def same_game_slip(self) -> list[SlipLeg]:
        return [leg(f"SG{i}", odds=1.91, p=0.545, event="one_game", league="WNBA") for i in range(4)]

    def test_a_same_game_slip_is_marked_unachievable(self) -> None:
        report = analyze_slip(self.same_game_slip(), draws=8_000)
        self.assertFalse(report["expected_value_is_achievable"])
        self.assertIsNotNone(report["same_event_repricing_warning"])

    def test_its_verdict_is_withheld_rather_than_called_value(self) -> None:
        report = analyze_slip(self.same_game_slip(), draws=8_000)
        self.assertEqual(report["verdict"], "not_priceable_from_standalone_legs")
        self.assertNotEqual(report["verdict"], "strong_value")

    def test_the_warning_counts_the_games_and_the_legs(self) -> None:
        warning = analyze_slip(self.same_game_slip(), draws=2_000)["same_event_repricing_warning"]
        self.assertEqual(warning["events_with_multiple_legs"], 1)
        self.assertEqual(warning["legs_sharing_an_event"], 4)

    def test_a_slip_of_separate_games_carries_no_warning(self) -> None:
        report = analyze_slip(independent_legs(4, p=0.62), draws=8_000)
        self.assertTrue(report["expected_value_is_achievable"])
        self.assertIsNone(report["same_event_repricing_warning"])

    def test_a_losing_same_game_slip_still_gets_its_honest_verdict(self) -> None:
        """The guard withholds value it cannot stand behind, not bad news."""
        legs = [leg(f"SG{i}", odds=2.0, p=0.30, event="one_game") for i in range(4)]
        report = analyze_slip(legs, draws=8_000)
        self.assertEqual(report["verdict"], "trim_slip")


class RiskTierTests(unittest.TestCase):
    def test_a_short_uncorrelated_slip_is_low_risk(self) -> None:
        self.assertEqual(risk_tier(leg_count=2, correlated_pairs=0, hit_probability=0.4), "low")

    def test_length_correlation_and_thin_odds_all_push_it_up(self) -> None:
        self.assertEqual(
            risk_tier(leg_count=19, correlated_pairs=6, hit_probability=0.042), "very_high"
        )

    def test_the_tier_never_runs_past_its_scale(self) -> None:
        self.assertEqual(
            risk_tier(leg_count=99, correlated_pairs=99, hit_probability=0.0001), "very_high"
        )


class TrimTests(unittest.TestCase):
    def test_trimming_drops_the_worst_priced_legs_first(self) -> None:
        good = [leg(f"G{i}", odds=2.0, p=0.60, event=f"g{i}", league=f"lg{i}") for i in range(4)]
        bad = [leg(f"B{i}", odds=2.0, p=0.30, event=f"b{i}", league=f"lb{i}") for i in range(3)]
        result = recommend_trim(good + bad, draws=1_500)
        self.assertTrue(all(leg_id.startswith("B") for leg_id in result["drop"]))

    def test_the_ladder_covers_every_length_down_to_the_floor(self) -> None:
        result = recommend_trim(independent_legs(6), draws=800, minimum_legs=2)
        self.assertEqual([row["leg_count"] for row in result["ladder"]], [6, 5, 4, 3, 2])

    def test_trimming_never_recommends_a_worse_slip_than_the_original(self) -> None:
        result = recommend_trim(independent_legs(5, p=0.45), draws=1_500)
        self.assertGreaterEqual(result["improvement_in_expected_value_ratio"], 0.0)

    def test_a_slip_too_short_to_trim_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            recommend_trim([leg("only")], minimum_legs=2)


class BoardIngestTests(unittest.TestCase):
    def test_rows_without_a_de_vigged_price_are_skipped_not_defaulted(self) -> None:
        """Falling back to the raw price would smuggle the margin back in."""
        rows = [
            dict(FRESH, leg_id="a", no_vig_probability=0.55, decimal_odds=1.9),
            dict(FRESH, leg_id="b", decimal_odds=1.9),
            dict(FRESH, leg_id="c", no_vig_probability=0.6),
        ]
        legs = legs_from_board(rows, now=NOW)
        self.assertEqual([entry.leg_id for entry in legs], ["a"])

    def test_an_unparsable_row_is_skipped_rather_than_raising(self) -> None:
        rows = [
            dict(FRESH, leg_id="bad", no_vig_probability="nonsense", decimal_odds=1.9),
            dict(FRESH, leg_id="ok", no_vig_probability=0.5, decimal_odds=2.0),
        ]
        self.assertEqual([e.leg_id for e in legs_from_board(rows, now=NOW)], ["ok"])

    def test_identity_and_grouping_fields_survive_the_trip(self) -> None:
        rows = [
            dict(FRESH, leg_id="x", no_vig_probability=0.5, decimal_odds=2.0,
                 event_id="g9", league="NBA", market_type="h2h", selection="Home")
        ]
        entry = legs_from_board(rows, now=NOW)[0]
        self.assertEqual((entry.event_id, entry.league, entry.market), ("g9", "NBA", "h2h"))


class MockupParityTests(unittest.TestCase):
    """The design's own numbers, recomputed from its own stated odds.

    The mockups quote a break-even beside every leg. Those are reproducible from
    the price alone, so they are a free correctness check on the engine against
    a source that was not written by it.
    """

    CASES = [
        (-250, 0.714286),
        (-162, 0.618321),
        (-178, 0.640288),
        (-110, 0.523810),
        (-320, 0.761905),
        (-115, 0.534884),
        (-120, 0.545455),
    ]

    @staticmethod
    def decimal(american: int) -> float:
        return 1 + (american / 100 if american > 0 else 100 / -american)

    def test_every_quoted_break_even_is_reproduced(self) -> None:
        for american, expected in self.CASES:
            entry = leg(odds=self.decimal(american), p=0.5)
            self.assertAlmostEqual(entry.break_even, expected, places=6)

    def test_the_quoted_slip_price_implies_the_quoted_break_even(self) -> None:
        self.assertAlmostEqual(4.99 / 106.38, 0.046907, places=6)



class MutuallyExclusiveTests(unittest.TestCase):
    """A copula models dependence. It cannot model "these cannot both happen".

    Home and away on one moneyline share an event, so the same-event rule gave
    them a positive correlation and the simulator cheerfully reported a joint
    probability near a third for an outcome that can never occur -- and every
    downstream figure inherited it.
    """

    def opposing(self) -> list[SlipLeg]:
        return [
            SlipLeg(leg_id="home", selection="Home", decimal_odds=2.0, fair_probability=0.5,
                    event_id="g1", market="h2h"),
            SlipLeg(leg_id="away", selection="Away", decimal_odds=2.0, fair_probability=0.5,
                    event_id="g1", market="h2h"),
        ]

    def test_opposing_sides_of_one_market_are_refused(self) -> None:
        with self.assertRaises(UnmodellableSlip):
            analyze_slip(self.opposing(), draws=500)

    def test_the_simulator_refuses_them_too(self) -> None:
        with self.assertRaises(UnmodellableSlip):
            simulate_slip(self.opposing(), draws=500)

    def test_the_refusal_names_the_offending_pair(self) -> None:
        with self.assertRaises(UnmodellableSlip) as caught:
            analyze_slip(self.opposing(), draws=500)
        self.assertIn("home+away", str(caught.exception))

    def test_nested_lines_on_one_market_are_refused_as_well(self) -> None:
        """Over 152.5 and Over 157.5 are linked deterministically, not by a rho."""
        nested = [
            SlipLeg(leg_id="o1", selection="Over 152.5", decimal_odds=1.91, fair_probability=0.55,
                    event_id="g1", market="total"),
            SlipLeg(leg_id="o2", selection="Over 157.5", decimal_odds=2.10, fair_probability=0.45,
                    event_id="g1", market="total"),
        ]
        with self.assertRaises(UnmodellableSlip):
            analyze_slip(nested, draws=500)

    def test_different_markets_in_one_game_remain_modellable(self) -> None:
        """A total and a moneyline in one game are dependent, not exclusive."""
        legs = [
            SlipLeg(leg_id="ml", selection="Home", decimal_odds=1.91, fair_probability=0.55,
                    event_id="g1", market="h2h"),
            SlipLeg(leg_id="tot", selection="Over 152.5", decimal_odds=1.91, fair_probability=0.55,
                    event_id="g1", market="total"),
        ]
        self.assertEqual(conflicting_pairs(legs), [])
        self.assertGreater(analyze_slip(legs, draws=2_000)["hit_probability"], 0.0)


class FreshnessTests(unittest.TestCase):
    """A verdict computed from a stale board reads as a statement about now."""

    def row(self, **over: object) -> dict:
        base = {
            "leg_id": "a", "no_vig_probability": 0.55, "decimal_odds": 1.9,
            "quoted_at": "2026-06-25T17:45:00+00:00", "source_state": "fresh",
        }
        base.update(over)
        return base

    def test_a_fresh_priced_row_is_accepted(self) -> None:
        self.assertEqual(len(legs_from_board([self.row()], now=NOW)), 1)

    def test_a_row_with_no_quote_time_is_skipped(self) -> None:
        self.assertEqual(legs_from_board([self.row(quoted_at=None)], now=NOW), [])

    def test_a_quote_older_than_the_window_is_skipped(self) -> None:
        old = self.row(quoted_at="2026-06-25T09:00:00+00:00")
        self.assertEqual(legs_from_board([old], now=NOW), [])

    def test_a_blocked_or_stale_source_is_skipped_however_recent(self) -> None:
        for state in ("stale", "blocked", "failed", "cached", "unavailable"):
            with self.subTest(state=state):
                self.assertEqual(legs_from_board([self.row(source_state=state)], now=NOW), [])

    def test_freshness_can_be_waived_only_deliberately(self) -> None:
        """Grading a historical slip on purpose is fine; nothing claims it is current."""
        old = self.row(quoted_at="2020-01-01T00:00:00+00:00")
        self.assertEqual(len(legs_from_board([old], now=NOW, require_freshness=False)), 1)

    def test_freshness_metadata_is_retained_on_the_leg(self) -> None:
        entry = legs_from_board([self.row(slate="2026-06-25")], now=NOW)[0]
        self.assertEqual(entry.source_state, "fresh")
        self.assertEqual(entry.slate, "2026-06-25")


class TrimHonestyTests(unittest.TestCase):
    """The trim must not rank on value the report itself withholds."""

    def test_a_wholly_same_game_slip_yields_no_recommendation(self) -> None:
        legs = [
            SlipLeg(leg_id=f"L{i}", selection=f"s{i}", decimal_odds=1.91, fair_probability=0.55,
                    event_id="one_game", market=f"m{i}")
            for i in range(5)
        ]
        result = recommend_trim(legs, draws=800)
        self.assertIsNone(result["recommended_leg_count"])
        self.assertEqual(result["keep"], [])
        self.assertIn("not takeable", result["note"])

    def test_every_ladder_row_records_whether_its_value_is_takeable(self) -> None:
        result = recommend_trim(independent_legs(4), draws=800)
        self.assertTrue(all("expected_value_is_achievable" in row for row in result["ladder"]))

    def test_a_clean_slip_still_gets_a_recommendation(self) -> None:
        result = recommend_trim(independent_legs(5, p=0.45), draws=1_200)
        self.assertIsNotNone(result["recommended_leg_count"])


if __name__ == "__main__":
    unittest.main()
