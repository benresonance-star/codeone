from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.persistence import (
    AlignmentRecord,
    CanonicalSnippet,
    EvaluationRecord,
    IngestionFragment,
    IngestionRun,
    IngestionTable,
    PurgeEvent,
    ReviewDecision,
    SnapshotRecord,
    SourceDocument,
    ValidationResultRecord,
)
from app.services.ingestion import IngestionService, PdfFragment, XmlNode


ACTIVE_STATUSES = ("active", "superseded")


def now_utc() -> datetime:
    return datetime.now(UTC)


class RetentionService:
    def __init__(self) -> None:
        self._storage_root = self._resolve_storage_root()
        self._raw_root = self._storage_root / "raw"
        self._raw_root.mkdir(parents=True, exist_ok=True)

    def persist_ingestion(
        self,
        session: Session,
        *,
        payload: dict[str, Any],
        pdf_name: str,
        pdf_bytes: bytes,
        xml_name: str,
        xml_bytes: bytes,
    ) -> dict[str, Any]:
        lineage = payload["lineage"]
        document_family_id = lineage["document_family_id"]

        pdf_document = self._create_source_document(
            session=session,
            document_family_id=document_family_id,
            document_type="pdf",
            file_name=pdf_name,
            media_type="application/pdf",
            content=pdf_bytes,
        )
        xml_document = self._create_source_document(
            session=session,
            document_family_id=document_family_id,
            document_type="xml",
            file_name=xml_name,
            media_type="application/xml",
            content=xml_bytes,
        )

        run = IngestionRun(
            document_family_id=document_family_id,
            status="active",
            can_progress=bool(payload["summary"]["can_progress"]),
            created_at=now_utc(),
            pdf_source_document_id=pdf_document.id,
            xml_source_document_id=xml_document.id,
        )
        session.add(run)
        session.flush()

        self._store_validation_result(session, run.id, pdf_document.id, payload["results"]["pdf_validation"], "pdf")
        self._store_validation_result(session, run.id, xml_document.id, payload["results"]["xml_validation"], "xml")
        self._store_fragments(session, run.id, pdf_document.id, payload["results"]["pdf_validation"]["validation_id"], lineage["pdf_fragments"])
        self._store_tables(
            session,
            run.id,
            pdf_document.id,
            payload["results"]["pdf_validation"]["validation_id"],
            "pdf",
            lineage["pdf_tables"],
        )
        self._store_tables(
            session,
            run.id,
            xml_document.id,
            payload["results"]["xml_validation"]["validation_id"],
            "xml",
            lineage["xml_tables"],
        )
        self._store_alignments(session, run.id, pdf_document.id, payload["results"]["pdf_validation"]["validation_id"], lineage["alignments"])
        self._store_canonical_snippets(
            session,
            run.id,
            pdf_document.id,
            payload["results"]["pdf_validation"]["validation_id"],
            lineage["canonical_snippets"],
        )
        self._store_placeholder_records(
            session,
            run.id,
            pdf_document.id,
            document_strategy=payload["summary"].get("document_strategy", {}),
            parity_scaffold=lineage.get("parity_scaffold", {}),
        )

        session.flush()
        payload["summary"]["ingestion_run_id"] = run.id
        payload["summary"]["document_family_id"] = document_family_id
        payload["summary"]["created_at"] = run.created_at.isoformat()
        payload["summary"]["pdf_source_document_id"] = pdf_document.id
        payload["summary"]["xml_source_document_id"] = xml_document.id
        return payload

    def list_runs(self, session: Session) -> list[dict[str, Any]]:
        runs = session.scalars(select(IngestionRun).order_by(IngestionRun.created_at.desc())).all()
        records: list[dict[str, Any]] = []
        for run in runs:
            records.append(
                {
                    "ingestion_run_id": run.id,
                    "document_family_id": run.document_family_id,
                    "status": run.status,
                    "can_progress": run.can_progress,
                    "invalidated_reason": run.invalidated_reason,
                    "created_at": run.created_at.isoformat(),
                    "invalidated_at": run.invalidated_at.isoformat() if run.invalidated_at else None,
                    "purged_at": run.purged_at.isoformat() if run.purged_at else None,
                    "pdf_source_document_id": run.pdf_source_document_id,
                    "xml_source_document_id": run.xml_source_document_id,
                    "counts": self._run_counts(session, run.id),
                    "document_strategy": self._run_strategy_summary(session, run.id),
                }
            )
        return records

    def load_run_payload(self, session: Session, run_id: str) -> dict[str, Any]:
        run = session.get(IngestionRun, run_id)
        if not run:
            raise LookupError("Ingestion run not found.")
        if run.status == "purged":
            raise ValueError("Purged runs cannot restore the review workspace.")

        pdf_validation = self._validation_payload(session, run_id, "pdf")
        xml_validation = self._validation_payload(session, run_id, "xml")
        if not pdf_validation or not xml_validation:
            raise LookupError("Persisted validation payload is incomplete for this run.")

        xml_document = session.get(SourceDocument, run.xml_source_document_id)
        pdf_document = session.get(SourceDocument, run.pdf_source_document_id)
        if not xml_document or not pdf_document:
            raise LookupError("Source documents for this run are missing.")

        xml_bytes = Path(xml_document.storage_path).read_bytes()
        ingestion_service = IngestionService()
        xml_context = ingestion_service._validate_xml(xml_bytes, xml_document.file_name)

        fragments = self._load_fragments(session, run_id)
        alignments = self._load_alignments(session, run_id, fragments)
        canonical_snippet_records = self._load_canonical_snippet_records(session, run_id)
        canonical_snippets = ingestion_service._build_canonical_snippets(
            can_progress=bool(canonical_snippet_records),
            fragments=fragments,
            alignments=alignments,
        )

        evaluation_payload = self._evaluation_payload(session, run_id)
        parity_scaffold = evaluation_payload.get("parity_scaffold", {}) if isinstance(evaluation_payload, dict) else {}
        document_strategy = (
            evaluation_payload.get("document_strategy", {}) if isinstance(evaluation_payload, dict) else {}
        )

        pdf_tables = self._table_payloads(session, run_id, "pdf")
        xml_tables = self._table_payloads(session, run_id, "xml")
        review_workspace = ingestion_service._build_review_workspace(
            pdf_name=pdf_document.file_name,
            xml_name=xml_document.file_name,
            xml_nodes=xml_context["xml_nodes"],
            fragments=fragments,
            alignments=alignments,
            canonical_snippets=canonical_snippets,
            xml_validation=xml_validation,
            pdf_validation=pdf_validation,
        )

        return {
            "summary": {
                "ingestion_run_id": run.id,
                "ingestion_run_status": run.status,
                "document_family_id": run.document_family_id,
                "created_at": run.created_at.isoformat(),
                "pdf_source_document_id": run.pdf_source_document_id,
                "xml_source_document_id": run.xml_source_document_id,
                "xml_status": xml_validation.get("overall_status", "UNKNOWN"),
                "pdf_status": pdf_validation.get("overall_status", "UNKNOWN"),
                "can_progress": run.can_progress,
                "paired_document_id": pdf_validation.get("document", {}).get("paired_xml_doc_id")
                or xml_validation.get("document", {}).get("paired_pdf_doc_id"),
                "document_strategy": document_strategy if isinstance(document_strategy, dict) else {},
                "parity_summary": parity_scaffold.get("summary", {}) if isinstance(parity_scaffold, dict) else {},
            },
            "results": {
                "xml_validation": xml_validation,
                "pdf_validation": pdf_validation,
            },
            "raw_metrics": {
                "xml": xml_context.get("metrics", {}),
                "pdf": self._rebuild_pdf_metrics(pdf_validation, document_strategy),
            },
            "lineage": {
                "document_family_id": run.document_family_id,
                "xml_nodes": [self._serialize_xml_node(node) for node in xml_context["xml_nodes"]],
                "pdf_fragments": [self._serialize_fragment(fragment) for fragment in fragments],
                "structured_blocks": [],
                "alignments": alignments,
                "parity_scaffold": parity_scaffold if isinstance(parity_scaffold, dict) else {},
                "canonical_snippets": canonical_snippets,
                "pdf_tables": pdf_tables,
                "xml_tables": xml_tables,
            },
            "review_workspace": review_workspace,
        }

    def resolve_run_pdf(self, session: Session, run_id: str) -> tuple[Path, str, str]:
        run = session.get(IngestionRun, run_id)
        if not run:
            raise LookupError("Ingestion run not found.")
        if run.status == "purged":
            raise ValueError("Purged runs cannot restore the retained PDF.")

        pdf_document = session.get(SourceDocument, run.pdf_source_document_id)
        if not pdf_document:
            raise LookupError("Retained PDF source document not found.")

        pdf_path = Path(pdf_document.storage_path)
        if not pdf_path.exists():
            raise LookupError("Retained PDF file is missing from storage.")

        return pdf_path, pdf_document.media_type, pdf_document.file_name

    def list_review_decisions(self, session: Session, run_id: str) -> list[dict[str, Any]]:
        run = session.get(IngestionRun, run_id)
        if not run:
            raise LookupError("Ingestion run not found.")

        records = session.scalars(
            select(ReviewDecision)
            .where(ReviewDecision.ingestion_run_id == run_id, ReviewDecision.status != "purged")
            .order_by(ReviewDecision.updated_at.desc(), ReviewDecision.created_at.desc())
        ).all()
        return [self._serialize_review_decision(record) for record in records]

    def save_review_decision(
        self,
        session: Session,
        *,
        run_id: str,
        candidate_id: str,
        fragment_id: str,
        node_id: str | None,
        decision_status: str,
        note: str | None = None,
        requested_by: str = "system",
    ) -> dict[str, Any]:
        run = session.get(IngestionRun, run_id)
        if not run:
            raise LookupError("Ingestion run not found.")
        if run.status == "purged":
            raise ValueError("Purged runs cannot store review decisions.")

        timestamp = now_utc()
        record = session.scalar(
            select(ReviewDecision).where(
                ReviewDecision.ingestion_run_id == run_id,
                ReviewDecision.candidate_id == candidate_id,
            )
        )
        if record is None:
            record = ReviewDecision(
                ingestion_run_id=run_id,
                candidate_id=candidate_id,
                fragment_id=fragment_id,
                node_id=node_id,
                decision_status=decision_status,
                note=note,
                requested_by=requested_by,
                status="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(record)
        else:
            record.fragment_id = fragment_id
            record.node_id = node_id
            record.decision_status = decision_status
            record.note = note
            record.requested_by = requested_by
            record.status = "active"
            record.updated_at = timestamp
        session.flush()
        return self._serialize_review_decision(record)

    def invalidate_run(self, session: Session, run_id: str, reason: str, requested_by: str = "system") -> dict[str, Any]:
        run = session.get(IngestionRun, run_id)
        if not run:
            raise LookupError("Ingestion run not found.")
        if run.status == "purged":
            raise ValueError("Purged runs cannot be invalidated.")

        timestamp = now_utc()
        run.status = "invalidated"
        run.can_progress = False
        run.invalidated_reason = reason
        run.invalidated_at = timestamp

        self._mark_run_records(session, run_id, "invalidated")
        self._record_event(
            session=session,
            target_type="ingestion_run",
            target_id=run_id,
            action="invalidate",
            requested_by=requested_by,
            summary={"reason": reason},
        )
        return {
            "ingestion_run_id": run.id,
            "status": run.status,
            "invalidated_reason": run.invalidated_reason,
            "invalidated_at": run.invalidated_at.isoformat() if run.invalidated_at else None,
        }

    def dry_run_purge_run(self, session: Session, run_id: str, requested_by: str = "system") -> dict[str, Any]:
        run = session.get(IngestionRun, run_id)
        if not run:
            raise LookupError("Ingestion run not found.")
        summary = self._build_run_purge_summary(session, run_id)
        self._record_event(
            session=session,
            target_type="ingestion_run",
            target_id=run_id,
            action="dry_run",
            requested_by=requested_by,
            summary=summary,
        )
        return summary

    def purge_run(self, session: Session, run_id: str, requested_by: str = "system") -> dict[str, Any]:
        run = session.get(IngestionRun, run_id)
        if not run:
            raise LookupError("Ingestion run not found.")

        summary = self._build_run_purge_summary(session, run_id)
        self._mark_run_records(session, run_id, "purged")
        run.status = "purged"
        run.can_progress = False
        run.purged_at = now_utc()
        self._record_event(
            session=session,
            target_type="ingestion_run",
            target_id=run_id,
            action="purge",
            requested_by=requested_by,
            summary=summary,
        )
        return summary

    def dry_run_purge_source_document(self, session: Session, source_document_id: str, requested_by: str = "system") -> dict[str, Any]:
        document = session.get(SourceDocument, source_document_id)
        if not document:
            raise LookupError("Source document not found.")

        run_ids = self._family_run_ids(session, document.document_family_id)
        summary = self._build_family_purge_summary(session, document.document_family_id, run_ids)
        self._record_event(
            session=session,
            target_type="source_document_family",
            target_id=document.document_family_id,
            action="dry_run",
            requested_by=requested_by,
            summary=summary,
        )
        return summary

    def purge_source_document(self, session: Session, source_document_id: str, requested_by: str = "system") -> dict[str, Any]:
        document = session.get(SourceDocument, source_document_id)
        if not document:
            raise LookupError("Source document not found.")

        run_ids = self._family_run_ids(session, document.document_family_id)
        summary = self._build_family_purge_summary(session, document.document_family_id, run_ids)
        for run_id in run_ids:
            run = session.get(IngestionRun, run_id)
            if run:
                self._mark_run_records(session, run_id, "purged")
                run.status = "purged"
                run.can_progress = False
                run.purged_at = now_utc()
        self._record_event(
            session=session,
            target_type="source_document_family",
            target_id=document.document_family_id,
            action="purge",
            requested_by=requested_by,
            summary=summary,
        )
        return summary

    def _create_source_document(
        self,
        *,
        session: Session,
        document_family_id: str,
        document_type: str,
        file_name: str,
        media_type: str,
        content: bytes,
    ) -> SourceDocument:
        checksum = hashlib.sha256(content).hexdigest()
        source_id = new_id_for(document_type)
        extension = Path(file_name).suffix or (".xml" if document_type == "xml" else ".pdf")
        storage_dir = self._raw_root / document_family_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"{source_id}{extension}"
        storage_path.write_bytes(content)

        document = SourceDocument(
            id=source_id,
            document_family_id=document_family_id,
            document_type=document_type,
            file_name=file_name,
            media_type=media_type,
            checksum_sha256=checksum,
            size_bytes=len(content),
            status="active",
            storage_path=str(storage_path),
            created_at=now_utc(),
        )
        session.add(document)
        session.flush()
        return document

    def _store_validation_result(
        self,
        session: Session,
        ingestion_run_id: str,
        source_document_id: str,
        payload: dict[str, Any],
        document_type: str,
    ) -> None:
        session.add(
            ValidationResultRecord(
                ingestion_run_id=ingestion_run_id,
                source_document_id=source_document_id,
                validation_id=payload["validation_id"],
                document_type=document_type,
                overall_status=payload["overall_status"],
                status="active",
                payload=payload,
                created_at=now_utc(),
            )
        )

    def _store_fragments(
        self,
        session: Session,
        ingestion_run_id: str,
        source_document_id: str,
        validation_id: str,
        fragments: list[PdfFragment],
    ) -> None:
        for fragment in fragments:
            session.add(
                IngestionFragment(
                    ingestion_run_id=ingestion_run_id,
                    source_document_id=source_document_id,
                    validation_id=validation_id,
                    fragment_id=fragment.fragment_id,
                    page_number=fragment.page,
                    bbox_json=json.dumps(fragment.bbox),
                    text_content=fragment.text,
                    status="active",
                    created_at=now_utc(),
                )
            )

    def _store_tables(
        self,
        session: Session,
        ingestion_run_id: str,
        source_document_id: str,
        validation_id: str,
        document_type: str,
        tables: list[dict[str, Any]],
    ) -> None:
        for table in tables:
            session.add(
                IngestionTable(
                    ingestion_run_id=ingestion_run_id,
                    source_document_id=source_document_id,
                    validation_id=validation_id,
                    table_id=table["table_id"],
                    document_type=document_type,
                    node_id=table.get("node_id") or table.get("related_xml_node"),
                    confidence=float(table.get("confidence", 0.0)),
                    rows_expected=table.get("rows_expected"),
                    rows_extracted=table.get("rows_extracted"),
                    payload=table,
                    status="active",
                    created_at=now_utc(),
                )
            )

    def _store_alignments(
        self,
        session: Session,
        ingestion_run_id: str,
        source_document_id: str,
        validation_id: str,
        alignments: list[dict[str, Any]],
    ) -> None:
        for alignment in alignments:
            session.add(
                AlignmentRecord(
                    ingestion_run_id=ingestion_run_id,
                    source_document_id=source_document_id,
                    validation_id=validation_id,
                    fragment_id=alignment["fragment_id"],
                    node_id=alignment.get("node_id"),
                    confidence=float(alignment.get("confidence", 0.0)),
                    status="active" if alignment.get("matched") else "superseded",
                    created_at=now_utc(),
                )
            )

    def _store_canonical_snippets(
        self,
        session: Session,
        ingestion_run_id: str,
        source_document_id: str,
        validation_id: str,
        snippets: list[dict[str, Any]],
    ) -> None:
        for snippet in snippets:
            session.add(
                CanonicalSnippet(
                    ingestion_run_id=ingestion_run_id,
                    source_document_id=source_document_id,
                    validation_id=validation_id,
                    clause_id=snippet["clause_id"],
                    content=snippet["content"],
                    status="active",
                    created_at=now_utc(),
                )
            )

    def _store_placeholder_records(
        self,
        session: Session,
        ingestion_run_id: str,
        source_document_id: str,
        *,
        document_strategy: dict[str, Any],
        parity_scaffold: dict[str, Any],
    ) -> None:
        session.add(
            EvaluationRecord(
                ingestion_run_id=ingestion_run_id,
                source_document_id=source_document_id,
                status="active",
                payload={
                    "state": "pending",
                    "document_strategy": document_strategy,
                    "parity_scaffold": parity_scaffold,
                },
                created_at=now_utc(),
            )
        )
        session.add(
            SnapshotRecord(
                ingestion_run_id=ingestion_run_id,
                source_document_id=source_document_id,
                status="active",
                payload={
                    "state": "pending",
                    "document_strategy": document_strategy,
                    "parity_scaffold_summary": parity_scaffold.get("summary", {}),
                },
                created_at=now_utc(),
            )
        )

    def _run_strategy_summary(self, session: Session, run_id: str) -> dict[str, Any]:
        record = session.scalar(select(EvaluationRecord).where(EvaluationRecord.ingestion_run_id == run_id))
        if not record or not isinstance(record.payload, dict):
            return {}
        value = record.payload.get("document_strategy")
        return value if isinstance(value, dict) else {}

    def _evaluation_payload(self, session: Session, run_id: str) -> dict[str, Any]:
        record = session.scalar(
            select(EvaluationRecord)
            .where(EvaluationRecord.ingestion_run_id == run_id, EvaluationRecord.status != "purged")
            .order_by(EvaluationRecord.created_at.desc())
        )
        if not record or not isinstance(record.payload, dict):
            return {}
        return record.payload

    def _validation_payload(self, session: Session, run_id: str, document_type: str) -> dict[str, Any] | None:
        record = session.scalar(
            select(ValidationResultRecord)
            .where(
                ValidationResultRecord.ingestion_run_id == run_id,
                ValidationResultRecord.document_type == document_type,
                ValidationResultRecord.status != "purged",
            )
            .order_by(ValidationResultRecord.created_at.desc())
        )
        if not record or not isinstance(record.payload, dict):
            return None
        return record.payload

    def _load_fragments(self, session: Session, run_id: str) -> list[PdfFragment]:
        records = session.scalars(
            select(IngestionFragment)
            .where(IngestionFragment.ingestion_run_id == run_id, IngestionFragment.status != "purged")
            .order_by(IngestionFragment.created_at.asc(), IngestionFragment.id.asc())
        ).all()
        return [
            PdfFragment(
                fragment_id=record.fragment_id,
                page=record.page_number,
                text=record.text_content,
                bbox=self._parse_bbox(record.bbox_json),
            )
            for record in records
        ]

    def _load_alignments(
        self,
        session: Session,
        run_id: str,
        fragments: list[PdfFragment],
    ) -> list[dict[str, Any]]:
        fragment_lookup = {fragment.fragment_id: fragment for fragment in fragments}
        records = session.scalars(
            select(AlignmentRecord)
            .where(AlignmentRecord.ingestion_run_id == run_id, AlignmentRecord.status != "purged")
            .order_by(AlignmentRecord.created_at.asc(), AlignmentRecord.id.asc())
        ).all()
        alignments: list[dict[str, Any]] = []
        for record in records:
            fragment = fragment_lookup.get(record.fragment_id)
            alignments.append(
                {
                    "fragment_id": record.fragment_id,
                    "node_id": record.node_id,
                    "confidence": float(record.confidence),
                    "matched": bool(record.node_id),
                    "page": fragment.page if fragment else None,
                    "bbox": fragment.bbox if fragment else [],
                }
            )
        return alignments

    def _load_canonical_snippet_records(self, session: Session, run_id: str) -> list[CanonicalSnippet]:
        return session.scalars(
            select(CanonicalSnippet)
            .where(CanonicalSnippet.ingestion_run_id == run_id, CanonicalSnippet.status != "purged")
            .order_by(CanonicalSnippet.created_at.asc(), CanonicalSnippet.id.asc())
        ).all()

    def _table_payloads(self, session: Session, run_id: str, document_type: str) -> list[dict[str, Any]]:
        records = session.scalars(
            select(IngestionTable)
            .where(
                IngestionTable.ingestion_run_id == run_id,
                IngestionTable.document_type == document_type,
                IngestionTable.status != "purged",
            )
            .order_by(IngestionTable.created_at.asc(), IngestionTable.id.asc())
        ).all()
        return [record.payload for record in records if isinstance(record.payload, dict)]

    def _parse_bbox(self, value: str | None) -> list[float]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [float(item) for item in parsed]

    def _serialize_fragment(self, fragment: PdfFragment) -> dict[str, Any]:
        return {
            "fragment_id": fragment.fragment_id,
            "page": fragment.page,
            "text": fragment.text,
            "bbox": fragment.bbox,
        }

    def _serialize_xml_node(self, node: XmlNode) -> dict[str, Any]:
        return {
            "node_id": node.node_id,
            "clause_id": node.clause_id,
            "text": node.text,
            "path": node.path,
        }

    def _rebuild_pdf_metrics(self, pdf_validation: dict[str, Any], document_strategy: dict[str, Any]) -> dict[str, Any]:
        alignment_summary = pdf_validation.get("alignment_summary", {}) if isinstance(pdf_validation, dict) else {}
        document = pdf_validation.get("document", {}) if isinstance(pdf_validation, dict) else {}
        confidence = pdf_validation.get("confidence", {}) if isinstance(pdf_validation, dict) else {}
        return {
            "text_based_ratio": 0.0,
            "total_words": 0,
            "line_count": 0,
            "aligned": alignment_summary.get("aligned", 0),
            "unresolved": alignment_summary.get("unresolved", 0),
            "quality_score": confidence.get("overall", 0.0),
            "runtime_mode": document_strategy.get("runtime_mode"),
            "pages_processed": document.get("pages_processed", 0),
            "fragments_extracted": document.get("fragments_extracted", 0),
            "tables_extracted": document.get("tables_extracted", 0),
        }

    def _mark_run_records(self, session: Session, run_id: str, status: str) -> None:
        for model in (
            ValidationResultRecord,
            IngestionFragment,
            IngestionTable,
            AlignmentRecord,
            CanonicalSnippet,
            ReviewDecision,
            EvaluationRecord,
            SnapshotRecord,
        ):
            records = session.scalars(select(model).where(model.ingestion_run_id == run_id)).all()
            for record in records:
                record.status = status

    def _build_run_purge_summary(self, session: Session, run_id: str) -> dict[str, Any]:
        run = session.get(IngestionRun, run_id)
        counts = self._run_counts(session, run_id)
        return {
            "target_type": "ingestion_run",
            "target_id": run_id,
            "document_family_id": run.document_family_id if run else None,
            "run_ids": [run_id],
            "counts": counts,
            "purge_order": [
                "review_decisions",
                "alignment_records",
                "ingestion_fragments",
                "ingestion_tables",
                "validation_results",
                "canonical_snippets",
                "evaluations",
                "snapshots",
                "ingestion_runs",
            ],
            "raw_inputs_retained": True,
        }

    def _build_family_purge_summary(self, session: Session, document_family_id: str, run_ids: list[str]) -> dict[str, Any]:
        aggregate = {
            "validation_results": 0,
            "ingestion_fragments": 0,
            "ingestion_tables": 0,
            "review_decisions": 0,
            "alignment_records": 0,
            "canonical_snippets": 0,
            "evaluations": 0,
            "snapshots": 0,
        }
        for run_id in run_ids:
            counts = self._run_counts(session, run_id)
            for key in aggregate:
                aggregate[key] += counts[key]
        return {
            "target_type": "source_document_family",
            "target_id": document_family_id,
            "run_ids": run_ids,
            "counts": aggregate,
            "purge_order": [
                "review_decisions",
                "alignment_records",
                "ingestion_fragments",
                "ingestion_tables",
                "validation_results",
                "canonical_snippets",
                "evaluations",
                "snapshots",
                "ingestion_runs",
            ],
            "raw_inputs_retained": True,
        }

    def _run_counts(self, session: Session, run_id: str) -> dict[str, int]:
        return {
            "validation_results": self._count_by_run(session, ValidationResultRecord, run_id),
            "ingestion_fragments": self._count_by_run(session, IngestionFragment, run_id),
            "ingestion_tables": self._count_by_run(session, IngestionTable, run_id),
            "review_decisions": self._count_by_run(session, ReviewDecision, run_id),
            "alignment_records": self._count_by_run(session, AlignmentRecord, run_id),
            "canonical_snippets": self._count_by_run(session, CanonicalSnippet, run_id),
            "evaluations": self._count_by_run(session, EvaluationRecord, run_id),
            "snapshots": self._count_by_run(session, SnapshotRecord, run_id),
        }

    def _count_by_run(self, session: Session, model: Any, run_id: str) -> int:
        return int(
            session.scalar(
                select(func.count()).select_from(model).where(model.ingestion_run_id == run_id, model.status != "purged")
            )
            or 0
        )

    def _family_run_ids(self, session: Session, document_family_id: str) -> list[str]:
        return list(
            session.scalars(select(IngestionRun.id).where(IngestionRun.document_family_id == document_family_id)).all()
        )

    def _record_event(
        self,
        *,
        session: Session,
        target_type: str,
        target_id: str,
        action: str,
        requested_by: str,
        summary: dict[str, Any],
    ) -> None:
        session.add(
            PurgeEvent(
                target_type=target_type,
                target_id=target_id,
                action=action,
                requested_by=requested_by,
                summary=summary,
                created_at=now_utc(),
            )
        )

    def _serialize_review_decision(self, record: ReviewDecision) -> dict[str, Any]:
        return {
            "id": record.id,
            "ingestion_run_id": record.ingestion_run_id,
            "candidate_id": record.candidate_id,
            "fragment_id": record.fragment_id,
            "node_id": record.node_id,
            "decision_status": record.decision_status,
            "note": record.note,
            "requested_by": record.requested_by,
            "status": record.status,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    def _resolve_storage_root(self) -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "backend").exists() or (parent / "Spec").exists():
                storage_root = parent / "runtime-data"
                storage_root.mkdir(parents=True, exist_ok=True)
                return storage_root
        storage_root = Path("runtime-data")
        storage_root.mkdir(parents=True, exist_ok=True)
        return storage_root


def new_id_for(document_type: str) -> str:
    prefix = "pdfsrc" if document_type == "pdf" else "xmlsrc"
    return f"{prefix}_{hashlib.sha1(f'{document_type}_{datetime.now(UTC).isoformat()}'.encode('utf-8')).hexdigest()[:24]}"
