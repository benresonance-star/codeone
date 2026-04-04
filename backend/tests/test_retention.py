from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import persistence as _persistence_models  # noqa: F401
from app.models.document_strategy import ExtractedPdf, StructuredBlock
from app.models.persistence import SnapshotRecord
from app.services.ingestion import IngestionService
from app.services import retention as retention_module
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


class RetentionCandidateRuntimeContractTests(unittest.TestCase):
    def test_persist_ingestion_serializes_enrichment_lineage_keys(self) -> None:
        src = inspect.getsource(RetentionService.persist_ingestion)
        self.assertIn("candidate_relations", src)
        self.assertIn("reconciliation_records", src)
        self.assertIn("candidate_validation_results", src)
        self.assertIn("candidate_validation_summary", src)
        self.assertIn("graph_edges", src)
        self.assertIn("enrichment_summary", src)
        self.assertIn("candidate_quality", src)
        self.assertIn("graph_readiness", src)
        self.assertIn("foundational_baseline_corpus", src)
        self.assertIn("schema_runtime", src)

    def test_load_run_payload_replays_shared_candidate_runtime(self) -> None:
        src = inspect.getsource(retention_module.RetentionService.load_run_payload)
        self.assertIn("_run_candidate_runtime", src)
        self.assertIn("review_decisions", src)
        self.assertIn("reconciliation_records", src)
        self.assertIn("candidate_validation_results", src)
        self.assertIn("candidate_quality", src)
        self.assertIn("foundational_baseline_corpus", src)

    def test_load_run_payload_restores_schema_version_summary_fields(self) -> None:
        src = inspect.getsource(retention_module.RetentionService.load_run_payload)
        self.assertIn("schema_family_version", src)
        self.assertIn("schema_registry_version", src)
        self.assertIn("schema_normalizer_version", src)


class _TestRetentionService(RetentionService):
    def __init__(self, storage_root: Path) -> None:
        self._test_storage_root = storage_root
        super().__init__()

    def _resolve_storage_root(self) -> Path:
        self._test_storage_root.mkdir(parents=True, exist_ok=True)
        return self._test_storage_root


class RetentionPayloadRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.storage_root = Path(self.tempdir.name)
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self.retention = _TestRetentionService(self.storage_root)
        self.ingestion = IngestionService()

    def _build_payload(self) -> tuple[dict[str, object], bytes, bytes, str, str]:
        xml_name = "bench-clause.xml"
        pdf_name = "bench-clause.pdf"
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_c" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="C">
  <num>C</num>
  <title>Test part</title>
  <clause id="C3D15"><p>Division of public corridors greater than 40 m in length.</p></clause>
  <clause id="clause_ref_source"><p>Refer to C3D15 for division of public corridors greater than 40 m in length.</p></clause>
</part>
"""
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=12,
            blocks=[
                StructuredBlock(
                    block_id="frag_ref",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="Refer to C3D15 for division of public corridors greater than 40 m in length.",
                    source_strategy="docling",
                )
            ],
            tables=[],
            strategy_name="docling",
            runtime_mode="native_text",
        )
        self.ingestion._extract_pdf = lambda pdf_bytes, strategy: extracted  # type: ignore[method-assign]
        payload = self.ingestion.process(
            b"pdf",
            pdf_name=pdf_name,
            xml_bytes=xml_bytes,
            xml_name=xml_name,
        )
        return payload, b"%PDF-1.4\n%", xml_bytes, pdf_name, xml_name

    def test_persist_and_load_run_payload_restores_dual_engine_runtime_fields(self) -> None:
        payload, pdf_bytes, xml_bytes, pdf_name, xml_name = self._build_payload()

        with self.SessionLocal() as session:
            persisted = self.retention.persist_ingestion(
                session,
                payload=payload,
                pdf_name=pdf_name,
                pdf_bytes=pdf_bytes,
                xml_name=xml_name,
                xml_bytes=xml_bytes,
            )
            session.commit()

            restored = self.retention.load_run_payload(session, persisted["summary"]["ingestion_run_id"])

        self.assertGreaterEqual(len(restored["lineage"]["candidate_relations"]), 1)
        self.assertGreaterEqual(len(restored["lineage"]["reconciliation_records"]), 1)
        self.assertGreaterEqual(len(restored["lineage"]["candidate_validation_results"]), 1)
        self.assertGreaterEqual(len(restored["review_workspace"]["candidate_relations"]), 1)
        self.assertGreaterEqual(len(restored["review_workspace"]["reconciliation_records"]), 1)
        self.assertGreaterEqual(len(restored["review_workspace"]["candidate_validation_results"]), 1)

        source_candidate = next(
            candidate for candidate in restored["lineage"]["candidate_objects"] if candidate.get("xml_node_id") == "clause_ref_source"
        )
        self.assertIn("candidate:unit:C3D15", source_candidate.get("depends_on") or [])

        relation = restored["lineage"]["candidate_relations"][0]
        self.assertIn(relation.get("relation_authority"), {"text_resolved", "xml_explicit"})
        self.assertIn("candidate_validation_summary", restored["lineage"])
        self.assertIn("schema_family_version", restored["summary"])
        self.assertIn("schema_registry_version", restored["summary"])
        self.assertIn("schema_normalizer_version", restored["summary"])

    def test_load_run_payload_applies_review_decisions_to_candidate_validation_state(self) -> None:
        payload, pdf_bytes, xml_bytes, pdf_name, xml_name = self._build_payload()

        with self.SessionLocal() as session:
            persisted = self.retention.persist_ingestion(
                session,
                payload=payload,
                pdf_name=pdf_name,
                pdf_bytes=pdf_bytes,
                xml_name=xml_name,
                xml_bytes=xml_bytes,
            )
            candidate_id = next(
                candidate["candidate_id"]
                for candidate in payload["lineage"]["candidate_objects"]
                if candidate.get("xml_node_id") == "C3D15"
            )
            self.retention.save_review_decision(
                session,
                run_id=persisted["summary"]["ingestion_run_id"],
                candidate_id=candidate_id,
                fragment_id="xml_only:C3D15",
                node_id="C3D15",
                decision_status="approved",
                note="Reviewed and accepted despite missing PDF evidence.",
            )
            session.commit()

            restored = self.retention.load_run_payload(session, persisted["summary"]["ingestion_run_id"])

        reviewed_candidate = next(
            candidate for candidate in restored["lineage"]["candidate_objects"] if candidate.get("candidate_id") == candidate_id
        )
        validation_record = next(
            item for item in restored["lineage"]["candidate_validation_results"] if item.get("candidate_id") == candidate_id
        )
        self.assertEqual(reviewed_candidate["review"]["human_decision_status"], "approved")
        self.assertEqual(reviewed_candidate["validation_state"], "pass")
        self.assertEqual(validation_record["review_decision_status"], "approved")
        self.assertFalse(validation_record["promotion_eligible"])
        self.assertEqual(restored["review_workspace"]["review_decisions"][0]["decision_status"], "approved")

    def test_persist_ingestion_snapshot_echoes_relation_and_reconciliation_counts(self) -> None:
        payload, pdf_bytes, xml_bytes, pdf_name, xml_name = self._build_payload()

        with self.SessionLocal() as session:
            persisted = self.retention.persist_ingestion(
                session,
                payload=payload,
                pdf_name=pdf_name,
                pdf_bytes=pdf_bytes,
                xml_name=xml_name,
                xml_bytes=xml_bytes,
            )
            session.commit()

            snapshot = session.scalar(
                select(SnapshotRecord).where(SnapshotRecord.ingestion_run_id == persisted["summary"]["ingestion_run_id"])
            )

        self.assertIsNotNone(snapshot)
        summary = snapshot.payload["candidate_runtime_summary"]
        self.assertGreaterEqual(summary["candidate_relations"], 1)
        self.assertGreaterEqual(summary["reconciliation_records"], 1)
        self.assertGreaterEqual(summary["candidate_validation_results"], 1)
