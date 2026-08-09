from __future__ import annotations

import unittest
from decimal import Decimal

from kalshi_research_bot.evaluation.decision import (
    ResearchDecisionPolicy,
    contract_expected_value_cents,
    evaluate_binary_contract_decision,
    uncertainty_adjusted_kelly_fraction,
)


def validated_input(**overrides):
    values = {
        "model_probability": Decimal("0.70"),
        "confidence_interval_low": Decimal("0.66"),
        "confidence_interval_high": Decimal("0.74"),
        "market_price_cents": Decimal("60"),
        "model_state": "validated_research",
        "test_sample_size": 200,
        "source_freshness_state": "fresh",
        "market_status": "open",
        "spread_cents": Decimal("2"),
        "fee_cents": Decimal("0.50"),
        "slippage_cents": Decimal("0.50"),
        "market_product_type": "single_event_contract",
        "validated_product_type": "single_event_contract",
        "market_horizon_bucket": "30m_240m",
        "validated_horizon_bucket": "30m_240m",
        "model_version": "sports-model-v2",
        "feature_version": "sports-features-v3",
        "dataset_version": "sha256:dataset",
    }
    values.update(overrides)
    return values


class ResearchDecisionPolicyTests(unittest.TestCase):
    def test_validated_model_requires_positive_uncertainty_adjusted_net_edge(self) -> None:
        result = evaluate_binary_contract_decision(**validated_input())
        self.assertEqual(result["action"], "BET_CANDIDATE")
        self.assertEqual(result["point_net_edge_cents"], Decimal("9.00"))
        self.assertEqual(result["lower_bound_net_edge_cents"], Decimal("5.00"))
        self.assertGreater(result["uncertainty_adjusted_kelly_fraction"], Decimal("0"))
        self.assertFalse(result["execution_allowed"])
        self.assertTrue(result["research_only"])

    def test_point_edge_without_lower_bound_edge_is_no_bet(self) -> None:
        result = evaluate_binary_contract_decision(
            **validated_input(confidence_interval_low=Decimal("0.605"))
        )
        self.assertEqual(result["action"], "NO_BET")
        self.assertIn("lower_bound_edge_below_threshold", result["reasons"])
        self.assertEqual(result["uncertainty_adjusted_kelly_fraction"], Decimal("0"))

    def test_baseline_only_market_cannot_become_a_bet_candidate(self) -> None:
        result = evaluate_binary_contract_decision(
            **validated_input(model_state="baseline_only")
        )
        self.assertEqual(result["action"], "NO_BET")
        self.assertIn("model_not_validated:baseline_only", result["reasons"])

    def test_unversioned_model_feature_or_dataset_cannot_be_candidate(self) -> None:
        result = evaluate_binary_contract_decision(
            **validated_input(
                model_version="unversioned",
                feature_version="unversioned",
                dataset_version="unversioned",
            )
        )
        self.assertEqual(result["action"], "NO_BET")
        self.assertIn("missing_model_version", result["reasons"])
        self.assertIn("missing_feature_version", result["reasons"])
        self.assertIn("missing_dataset_version", result["reasons"])

    def test_missing_cost_model_waits_and_does_not_claim_roi(self) -> None:
        result = evaluate_binary_contract_decision(
            **validated_input(fee_cents=None, slippage_cents=None)
        )
        self.assertEqual(result["action"], "WAIT_FOR_DATA")
        self.assertIn("execution_cost_model_missing", result["reasons"])
        self.assertIsNone(result["point_net_edge_cents"])

    def test_stale_duplicate_and_segment_mismatch_are_blocked(self) -> None:
        result = evaluate_binary_contract_decision(
            **validated_input(
                source_freshness_state="stale",
                duplicate=True,
                validated_product_type="moneyline",
            )
        )
        self.assertNotEqual(result["action"], "BET_CANDIDATE")
        self.assertIn("source_not_fresh:stale", result["reasons"])
        self.assertIn("duplicate_record", result["reasons"])
        self.assertIn(
            "validation_product_mismatch:moneyline/single_event_contract",
            result["reasons"],
        )

    def test_contract_ev_and_fractional_kelly_are_exact_decimals(self) -> None:
        expected_value = contract_expected_value_cents(
            probability=Decimal("0.62345678"),
            market_price_cents=Decimal("57.125"),
            fee_cents=Decimal("0.375"),
            slippage_cents=Decimal("0.125"),
        )
        fraction = uncertainty_adjusted_kelly_fraction(
            lower_probability=Decimal("0.61"),
            market_price_cents=Decimal("57.125"),
            fee_cents=Decimal("0.375"),
            slippage_cents=Decimal("0.125"),
            multiplier=Decimal("0.25"),
            maximum_fraction=Decimal("0.01"),
        )
        self.assertEqual(expected_value, Decimal("4.72067800"))
        self.assertGreater(fraction, Decimal("0"))
        self.assertLessEqual(fraction, Decimal("0.01"))

    def test_policy_validation_rejects_unsafe_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "kelly_multiplier_outside_unit_interval"):
            ResearchDecisionPolicy(kelly_multiplier=Decimal("1.1")).validate()


if __name__ == "__main__":
    unittest.main()
