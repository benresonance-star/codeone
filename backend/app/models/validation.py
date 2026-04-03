from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ValidationBundleResponse(BaseModel):
    xml_validation: dict[str, Any]
    pdf_validation: dict[str, Any]


class ValidationSummary(BaseModel):
    ingestion_run_id: str | None = None
    ingestion_run_status: str | None = None
    document_family_id: str | None = None
    pdf_source_document_id: str | None = None
    xml_source_document_id: str | None = None
    xml_status: str
    pdf_status: str
    can_progress: bool
    paired_document_id: str | None = None
    document_strategy: dict[str, Any] = Field(default_factory=dict)
    parity_summary: dict[str, Any] = Field(default_factory=dict)


class IngestionResponse(BaseModel):
    summary: ValidationSummary
    results: ValidationBundleResponse
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
    lineage: dict[str, Any] = Field(default_factory=dict)
    review_workspace: dict[str, Any] = Field(default_factory=dict)


class IngestionRunRecord(BaseModel):
    ingestion_run_id: str
    document_family_id: str
    status: str
    can_progress: bool
    invalidated_reason: str | None = None
    created_at: str
    invalidated_at: str | None = None
    purged_at: str | None = None
    pdf_source_document_id: str
    xml_source_document_id: str
    counts: dict[str, int] = Field(default_factory=dict)
    document_strategy: dict[str, Any] = Field(default_factory=dict)


class IngestionRunListResponse(BaseModel):
    runs: list[IngestionRunRecord] = Field(default_factory=list)


class InvalidationResponse(BaseModel):
    ingestion_run_id: str
    status: str
    invalidated_reason: str | None = None
    invalidated_at: str | None = None


class PurgeSummaryResponse(BaseModel):
    target_type: str
    target_id: str
    document_family_id: str | None = None
    run_ids: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    purge_order: list[str] = Field(default_factory=list)
    raw_inputs_retained: bool = True
