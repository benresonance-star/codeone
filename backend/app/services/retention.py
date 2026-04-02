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
    SnapshotRecord,
    SourceDocument,
    ValidationResultRecord,
)
from app.services.ingestion import PdfFragment, XmlNode


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

    def _mark_run_records(self, session: Session, run_id: str, status: str) -> None:
        for model in (
            ValidationResultRecord,
            IngestionFragment,
            IngestionTable,
            AlignmentRecord,
            CanonicalSnippet,
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
