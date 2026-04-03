from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.retention import RetentionService


class RetentionServiceStatusGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RetentionService()

    def test_load_run_payload_rejects_invalidated_runs(self) -> None:
        session = Mock()
        session.get.return_value = SimpleNamespace(status="invalidated")

        with self.assertRaisesRegex(ValueError, "Invalidated runs cannot restore the review workspace."):
            self.service.load_run_payload(session, "run_invalidated")

    def test_load_run_payload_rejects_purged_runs(self) -> None:
        session = Mock()
        session.get.return_value = SimpleNamespace(status="purged")

        with self.assertRaisesRegex(ValueError, "Purged runs cannot restore the review workspace."):
            self.service.load_run_payload(session, "run_purged")

    def test_resolve_run_pdf_rejects_invalidated_runs(self) -> None:
        session = Mock()
        session.get.return_value = SimpleNamespace(status="invalidated")

        with self.assertRaisesRegex(ValueError, "Invalidated runs cannot restore the retained PDF."):
            self.service.resolve_run_pdf(session, "run_invalidated")

    def test_save_review_decision_rejects_invalidated_runs(self) -> None:
        session = Mock()
        session.get.return_value = SimpleNamespace(status="invalidated")

        with self.assertRaisesRegex(ValueError, "Invalidated runs cannot store review decisions."):
            self.service.save_review_decision(
                session,
                run_id="run_invalidated",
                candidate_id="candidate:frag_1",
                fragment_id="frag_1",
                node_id="node_1",
                decision_status="approved",
            )
