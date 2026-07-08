import unittest

from kalshi_research_bot.paper_server import render_slip_section
from kalshi_research_bot.review_packet import (
    build_review_packet,
    render_review_packet_text,
    safe_review_packet_filename,
)


def _sample_payload():
    leg = {
        "sport": "MLB",
        "market_ticker": "KXMLBTOTAL-26JUL061930NYYBOS-8",
        "event_ticker": "KXMLBTOTAL-26JUL061930NYYBOS",
        "display_event": "New York vs Boston",
        "side": "yes",
        "subtitle": "Over 7.5 runs scored",
        "status": "active",
        "probability": 0.82,
        "required_probability": 0.80,
        "bid_cents": 81.0,
        "ask_cents": 82.0,
        "combo_category": "Sports",
        "combo_eligible": True,
        "manual_entry_ready": True,
        "market_close_time": "2026-07-06T19:25:00-04:00",
        "event_start_time": "2026-07-06T19:30:00-04:00",
        "api_fetched_at": "2026-07-06T12:29:00-04:00",
        "overlap_key": "sports:nyy-bos",
    }
    return {
        "date": "20260706",
        "generated_at": "2026-07-06T12:30:00-04:00",
        "generated_at_note": "Generated from public ESPN scoreboard APIs and public Kalshi market data.",
        "custom_slip": {
            "action": "BUILD_SLIP",
            "leg_count": 1,
            "sports": ["MLB"],
            "estimated_combo_price_cents": 82.0,
            "stake_dollars": 5.0,
            "estimated_payout_if_right": 6.1,
            "raw_probability": 0.82,
            "adjusted_probability": 0.82,
            "correlation_penalty": 0,
            "overlap_safe": True,
            "overlap_policy": "one normalized matchup per combo slip",
            "combo_categories": ["Sports"],
            "category_counts": {"Sports": 1},
            "manual_entry_ready": True,
            "combo_compatibility": {
                "status": "compatible",
                "manual_entry_ready": True,
                "categories": ["Sports"],
                "can_mix_categories": True,
            },
            "legs": [leg],
        },
    }


class ReviewPacketTests(unittest.TestCase):
    def test_review_packet_is_manual_only_and_copy_ready(self):
        packet = build_review_packet(_sample_payload(), "primary")

        self.assertTrue(packet["ready"])
        self.assertEqual(packet["packet_type"], "kalshi_manual_review_packet")
        self.assertTrue(packet["safety"]["manual_review_only"])
        self.assertFalse(packet["safety"]["account_write_enabled"])
        self.assertFalse(packet["safety"]["auto_trade_enabled"])
        self.assertFalse(packet["safety"]["auto_bet_enabled"])
        self.assertFalse(packet["safety"]["order_submission_enabled"])
        self.assertIn("KXMLBTOTAL-26JUL061930NYYBOS-8\tYES", packet["copy_blocks"]["ticker_stack"])
        self.assertIn("Over 7.5 runs scored", packet["copy_blocks"]["fast_entry"])
        self.assertEqual(packet["summary"]["combo_compatibility"]["status"], "compatible")
        self.assertTrue(packet["summary"]["manual_entry_ready"])
        self.assertEqual(packet["legs"][0]["combo_category"], "Sports")
        self.assertEqual(packet["legs"][0]["market_close_time"], "2026-07-06T19:25:00-04:00")

    def test_review_packet_text_has_safety_note_and_fast_lines(self):
        packet = build_review_packet(_sample_payload(), "primary")
        text = render_review_packet_text(packet)

        self.assertIn("NOT AN ORDER", text)
        self.assertIn("No account upload", text)
        self.assertIn("KXMLBTOTAL-26JUL061930NYYBOS-8 | YES", text)
        self.assertIn("Combo compatibility: compatible", text)
        self.assertIn("ENTRY DETAIL", text)
        self.assertIn("category=Sports", text)
        self.assertIn("Packet hash:", text)

    def test_review_packet_hash_is_deterministic_for_same_source_payload(self):
        first = build_review_packet(_sample_payload(), "primary")
        second = build_review_packet(_sample_payload(), "primary")

        self.assertEqual(first["packet_hash"], second["packet_hash"])

    def test_review_packet_rejects_unknown_slip_key(self):
        with self.assertRaises(ValueError):
            build_review_packet(_sample_payload(), "unknown")

    def test_safe_filename_uses_date_and_slip_key(self):
        packet = build_review_packet(_sample_payload(), "primary")

        self.assertEqual(safe_review_packet_filename(packet, "txt"), "20260706_primary_manual_review_packet.txt")

    def test_rendered_slip_section_exposes_packet_actions(self):
        slip = _sample_payload()["custom_slip"]
        rendered = render_slip_section(slip, "80% SLIP", "primary")

        self.assertIn("Copy Fast Packet", rendered)
        self.assertIn("Copy Tickers + Sides", rendered)
        self.assertIn("/review-packet.txt?slip=primary", rendered)
        self.assertIn("No account upload", rendered)


if __name__ == "__main__":
    unittest.main()
