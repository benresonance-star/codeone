from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ValidationBundleResponse(BaseModel):
    xml_validation: dict[str, Any]
    pdf_validation: dict[str, Any]


class ValidationSummary(BaseModel):
    xml_status: str
    pdf_status: str
    can_progress: bool
    paired_document_id: str | None = None


class IngestionResponse(BaseModel):
    summary: ValidationSummary
    results: ValidationBundleResponse
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
