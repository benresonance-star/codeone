from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("src"))
    document_family_id: Mapped[str] = mapped_column(String(80), index=True)
    document_type: Mapped[str] = mapped_column(String(16), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(64))
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    storage_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    runs_as_pdf: Mapped[list["IngestionRun"]] = relationship(
        back_populates="pdf_source_document",
        foreign_keys="IngestionRun.pdf_source_document_id",
    )
    runs_as_xml: Mapped[list["IngestionRun"]] = relationship(
        back_populates="xml_source_document",
        foreign_keys="IngestionRun.xml_source_document_id",
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("run"))
    document_family_id: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    can_progress: Mapped[bool] = mapped_column(Boolean, default=False)
    invalidated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pdf_source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    xml_source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)

    pdf_source_document: Mapped[SourceDocument] = relationship(
        back_populates="runs_as_pdf",
        foreign_keys=[pdf_source_document_id],
    )
    xml_source_document: Mapped[SourceDocument] = relationship(
        back_populates="runs_as_xml",
        foreign_keys=[xml_source_document_id],
    )
    validation_results: Mapped[list["ValidationResultRecord"]] = relationship(back_populates="ingestion_run")
    fragments: Mapped[list["IngestionFragment"]] = relationship(back_populates="ingestion_run")
    tables: Mapped[list["IngestionTable"]] = relationship(back_populates="ingestion_run")
    alignments: Mapped[list["AlignmentRecord"]] = relationship(back_populates="ingestion_run")
    canonical_snippets: Mapped[list["CanonicalSnippet"]] = relationship(back_populates="ingestion_run")
    evaluations: Mapped[list["EvaluationRecord"]] = relationship(back_populates="ingestion_run")
    snapshots: Mapped[list["SnapshotRecord"]] = relationship(back_populates="ingestion_run")


class ValidationResultRecord(Base):
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("valr"))
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    validation_id: Mapped[str] = mapped_column(String(128), index=True)
    document_type: Mapped[str] = mapped_column(String(16), index=True)
    overall_status: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="validation_results")


class IngestionFragment(Base):
    __tablename__ = "ingestion_fragments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fragrec"))
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    validation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fragment_id: Mapped[str] = mapped_column(String(128), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    bbox_json: Mapped[str] = mapped_column(String(128))
    text_content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="fragments")


class IngestionTable(Base):
    __tablename__ = "ingestion_tables"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tabrec"))
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    validation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    table_id: Mapped[str] = mapped_column(String(128), index=True)
    document_type: Mapped[str] = mapped_column(String(16), index=True)
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    rows_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_extracted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="tables")


class AlignmentRecord(Base):
    __tablename__ = "alignment_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("align"))
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    validation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fragment_id: Mapped[str] = mapped_column(String(128), index=True)
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="alignments")


class CanonicalSnippet(Base):
    __tablename__ = "canonical_snippets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("snippet"))
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    validation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    clause_id: Mapped[str] = mapped_column(String(128), index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="canonical_snippets")


class EvaluationRecord(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("eval"))
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="evaluations")


class SnapshotRecord(Base):
    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("snap"))
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="snapshots")


class PurgeEvent(Base):
    __tablename__ = "purge_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("purge"))
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    requested_by: Mapped[str] = mapped_column(String(80), default="system")
    summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
