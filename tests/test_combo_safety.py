import unittest

from kalshi_research_bot.combo_safety import (
    VERIFIED_COMBO_EVIDENCE,
    VERIFIED_COMBO_SOURCE,
    authoritative_combo_slip_rejection_reasons,
    combo_leg_signature,
    slip_has_authoritative_combo_evidence,
)


def _verified_slip(legs, *, combo_ticker="KXMVE-TEST"):
    signature = combo_leg_signature(legs)
    verified_legs = [
        {
            **leg,
            "combo_eligible": True,
            "combo_market_ticker": combo_ticker,
            "combo_market_status": "active",
            "combo_market_yes_ask_cents": 50,
            "combo_market_fetched_at": "2026-07-13T12:00:00Z",
            "combo_market_snapshot_hash": "sha256:combo-snapshot",
            "combo_market_leg_signature": signature,
            "combo_exact_leg_count": len(legs),
            "combo_evidence_status": VERIFIED_COMBO_EVIDENCE,
            "combo_source": VERIFIED_COMBO_SOURCE,
        }
        for leg in legs
    ]
    return {
        "action": "BUILD_SLIP",
        "combo_compatibility": {"status": "compatible", "exact_listed_combo": True},
        "listed_combo_market_ticker": combo_ticker,
        "legs": verified_legs,
    }


class ComboSafetyTests(unittest.TestCase):
    def test_signature_is_deterministic_across_leg_order(self):
        first = [
            {"market_ticker": "MKT-B", "side": "NO"},
            {"market_ticker": "MKT-A", "side": "YES"},
        ]
        second = list(reversed(first))
        self.assertEqual(combo_leg_signature(first), combo_leg_signature(second))

    def test_exact_listed_combo_is_accepted(self):
        slip = _verified_slip(
            [
                {"market_ticker": "KXMLB-A", "side": "yes"},
                {"market_ticker": "KXBTC-B", "side": "no"},
            ]
        )
        self.assertTrue(slip_has_authoritative_combo_evidence(slip))
        self.assertEqual(authoritative_combo_slip_rejection_reasons(slip["legs"]), [])

    def test_missing_combo_evidence_is_rejected(self):
        slip = {
            "action": "BUILD_SLIP",
            "combo_compatibility": {"status": "compatible", "exact_listed_combo": True},
            "legs": [{"market_ticker": "MKT-A", "side": "yes", "combo_eligible": True}],
        }
        self.assertFalse(slip_has_authoritative_combo_evidence(slip))
        self.assertIn(
            "missing_authoritative_combo_evidence",
            authoritative_combo_slip_rejection_reasons(slip["legs"]),
        )

    def test_legs_from_two_combo_markets_are_rejected(self):
        slip = _verified_slip(
            [
                {"market_ticker": "MKT-A", "side": "yes"},
                {"market_ticker": "MKT-B", "side": "no"},
            ]
        )
        slip["legs"][1]["combo_market_ticker"] = "KXMVE-OTHER"
        reasons = authoritative_combo_slip_rejection_reasons(slip["legs"])
        self.assertIn("legs_not_from_one_listed_combo_market", reasons)
        self.assertFalse(slip_has_authoritative_combo_evidence(slip))

    def test_subset_of_listed_combo_is_rejected(self):
        slip = _verified_slip(
            [
                {"market_ticker": "MKT-A", "side": "yes"},
                {"market_ticker": "MKT-B", "side": "no"},
            ]
        )
        slip["legs"] = slip["legs"][:1]
        reasons = authoritative_combo_slip_rejection_reasons(slip["legs"])
        self.assertIn("combo_leg_count_mismatch", reasons)
        self.assertIn("combo_leg_signature_mismatch", reasons)
        self.assertFalse(slip_has_authoritative_combo_evidence(slip))


if __name__ == "__main__":
    unittest.main()
