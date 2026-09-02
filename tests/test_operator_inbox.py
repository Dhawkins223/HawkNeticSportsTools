from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

from kalshi_research_bot.database import json_default
from kalshi_research_bot.monitoring import build_internal_status
from kalshi_research_bot.operator_inbox import OperatorInbox
from kalshi_research_bot.paper_server import render_operator_page

from tests.postgres_support import PostgresTestCase


class OperatorInboxTests(PostgresTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.inbox = OperatorInbox(self.settings)

    def test_queue_claim_complete_preserves_manual_boundary(self) -> None:
        queued = self.inbox.add(
            message_id="review-worker-health",
            title="Review worker health",
            body="Inspect and propose a safe patch.",
            created_by="owner",
            priority="high",
        )
        claimed = self.inbox.claim(queued["message_id"], agent="codex")
        completed = self.inbox.complete(
            queued["message_id"], agent="codex", summary="Reviewed without automatic action."
        )

        self.assertTrue(queued["requires_approval"])
        self.assertFalse(queued["execution_allowed"])
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(completed["execution_allowed"])

    def test_idempotent_message_rejects_changed_content(self) -> None:
        first = self.inbox.add(message_id="same", title="Same", body="Same", created_by="owner")
        repeated = self.inbox.add(message_id="same", title="Same", body="Same", created_by="owner")
        with self.assertRaisesRegex(ValueError, "message_id_conflict"):
            self.inbox.add(message_id="same", title="Changed", body="Different", created_by="owner")
        self.assertEqual(first["message_id"], repeated["message_id"])

    def test_other_agent_cannot_complete_claim(self) -> None:
        message = self.inbox.add(title="Task", body="Body", created_by="owner")
        self.inbox.claim(message["message_id"], agent="codex")
        with self.assertRaisesRegex(ValueError, "message_claimed_by_another_agent"):
            self.inbox.complete(message["message_id"], agent="other", summary="Done")

    def test_page_and_environment_document_manual_review_only(self) -> None:
        page = render_operator_page()
        environment = Path(".env.example").read_text(encoding="utf-8")
        self.assertIn("Private operator inbox", page)
        self.assertIn("never run commands", page)
        self.assertNotIn("Place order", page)
        self.assertIn("never executes commands", environment)

    def test_concurrent_same_message_id_returns_one_queued_message(self) -> None:
        def add_message(_: int) -> dict:
            return self.inbox.add(
                message_id="concurrent-message",
                title="Review",
                body="Review without execution.",
                created_by="owner",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            messages = list(executor.map(add_message, range(2)))
        count = self.query_one(
            "SELECT COUNT(*) AS total FROM ops.operator_messages WHERE message_id = %s",
            ("concurrent-message",),
        )
        self.assertEqual({message["message_id"] for message in messages}, {"concurrent-message"})
        self.assertEqual(count["total"], 1)

    def test_invalid_priority_target_and_source_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_priority"):
            self.inbox.add(title="Task", body="Body", created_by="owner", priority="immediate")
        with self.assertRaisesRegex(ValueError, "invalid_target"):
            self.inbox.add(title="Task", body="Body", created_by="owner", target="execution")
        with self.assertRaisesRegex(ValueError, "invalid_source"):
            self.inbox.add(title="Task", body="Body", created_by="owner", source="remote")


class CommandOutputSerialisationTests(PostgresTestCase):
    """The CLI printed these dicts with a bare json.dumps and crashed on them.

    Every operator-message command and worker-status ended in
    ``print(json.dumps(...))`` without ``default=json_default``, and the rows
    carry ``created_at`` / ``updated_at`` datetimes -- so the whole operator
    inbox CLI raised ``TypeError: Object of type datetime is not JSON
    serializable`` the moment the queue was non-empty. ``operator-message-list``
    passed by accident against an empty queue, which is why nothing caught it.

    The database writes had already committed by then, so a claim that
    succeeded exited non-zero and looked like a failure to any script.
    """

    def setUp(self) -> None:
        super().setUp()
        self.inbox = OperatorInbox(self.settings)

    def queued_message(self) -> dict:
        return self.inbox.add(
            message_id="serialisation-probe",
            title="Probe",
            body="Body.",
            created_by="owner",
            priority="normal",
        )

    def test_a_queued_message_carries_datetimes(self) -> None:
        """The precondition: without these the test below proves nothing."""

        message = self.queued_message()
        stamped = [key for key, value in message.items() if hasattr(value, "isoformat")]
        self.assertTrue(stamped, "expected datetime-valued keys on a queued message")

    def test_every_message_lifecycle_payload_serialises(self) -> None:
        message = self.queued_message()
        claimed = self.inbox.claim(message["message_id"], agent="codex")
        completed = self.inbox.complete(
            message["message_id"], agent="codex", summary="Reviewed."
        )
        listing = {"counts": self.inbox.counts(), "messages": self.inbox.list(limit=10)}
        for payload in (message, claimed, completed, listing):
            json.dumps(payload, indent=2, sort_keys=True, default=json_default)

    def test_a_non_empty_listing_is_what_breaks_without_the_encoder(self) -> None:
        self.queued_message()
        listing = {"counts": self.inbox.counts(), "messages": self.inbox.list(limit=10)}
        self.assertTrue(listing["messages"])
        with self.assertRaises(TypeError):
            json.dumps(listing, indent=2, sort_keys=True)
        json.dumps(listing, indent=2, sort_keys=True, default=json_default)

    def test_worker_status_serialises(self) -> None:
        json.dumps(build_internal_status(), indent=2, sort_keys=True, default=json_default)
