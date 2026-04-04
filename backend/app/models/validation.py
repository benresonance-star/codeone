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
    created_at: str | None = None
    pdf_source_document_id: str | None = None
    xml_source_document_id: str | None = None
    xml_status: str
    pdf_status: str
    can_progress: bool
    paired_document_id: str | None = None
    schema_family_id: str | None = None
    schema_family_version: str | None = None
    schema_registry_version: str | None = None
    schema_normalizer_version: str | None = None
    schema_recheck_status: str | None = None
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


class ReviewDecisionRecord(BaseModel):
    id: str
    ingestion_run_id: str
    candidate_id: str
    fragment_id: str
    node_id: str | None = None
    decision_status: str
    note: str | None = None
    requested_by: str
    status: str
    created_at: str
    updated_at: str


class ReviewDecisionRequest(BaseModel):
    candidate_id: str
    fragment_id: str
    node_id: str | None = None
    decision_status: str
    note: str | None = None


class ReviewDecisionListResponse(BaseModel):
    decisions: list[ReviewDecisionRecord] = Field(default_factory=list)


class CandidateValidationIssueRecord(BaseModel):
    code: str
    severity: str
    message: str
    blocking: bool = False


class CandidateValidationRecord(BaseModel):
    candidate_id: str
    validation_state: str
    lifecycle_status: str
    promotion_eligible: bool = False
    review_override_applied: bool = False
    review_decision_status: str | None = None
    issue_count: int = 0
    blocking_issue_count: int = 0
    advisory_issue_count: int = 0
    issues: list[CandidateValidationIssueRecord] = Field(default_factory=list)


class CandidateValidationSummaryRecord(BaseModel):
    schema_version: str = "1"
    candidate_count: int = 0
    pass_count: int = 0
    requires_review_count: int = 0
    fail_count: int = 0
    promotion_eligible_count: int = 0
    review_override_count: int = 0


class PurgeSummaryResponse(BaseModel):
    target_type: str
    target_id: str
    document_family_id: str | None = None
    run_ids: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    purge_order: list[str] = Field(default_factory=list)
    raw_inputs_retained: bool = True


class XmlSchemaFamilyListResponse(BaseModel):
    registry_type: str
    registry_version: str | None = None
    generated_at: str | None = None
    scanned_file_count: int | None = None
    family_count: int | None = None
    families: list[dict[str, Any]] = Field(default_factory=list)
    scan_errors: list[dict[str, Any]] = Field(default_factory=list)
    repo_sync: dict[str, Any] = Field(default_factory=dict)


class XmlSchemaTagListResponse(BaseModel):
    registry_type: str
    registry_version: str | None = None
    generated_at: str | None = None
    scanned_file_count: int | None = None
    tag_count: int | None = None
    tags: list[dict[str, Any]] = Field(default_factory=list)
    scan_errors: list[dict[str, Any]] = Field(default_factory=list)
    repo_sync: dict[str, Any] = Field(default_factory=dict)


class XmlSchemaFamilyDetailResponse(BaseModel):
    registry_type: str
    registry_version: str | None = None
    family: dict[str, Any] = Field(default_factory=dict)
    repo_sync: dict[str, Any] = Field(default_factory=dict)


class XmlSchemaTagDetailResponse(BaseModel):
    registry_type: str
    registry_version: str | None = None
    tag: dict[str, Any] = Field(default_factory=dict)
    repo_sync: dict[str, Any] = Field(default_factory=dict)


class XmlSchemaScanResponse(BaseModel):
    registry_version: str
    generated_at: str
    scanned_file_count: int
    family_count: int
    tag_count: int = 0
    approved_registry_version: str | None = None
    approved_tag_registry_version: str | None = None
    scan_errors: list[dict[str, Any]] = Field(default_factory=list)
    repo_sync: dict[str, Any] = Field(default_factory=dict)


class XmlSchemaBatchResponse(BaseModel):
    batch_job_id: str
    generated_at: str
    uploaded_file_count: int
    scanned_file_count: int
    family_count: int
    tag_count: int = 0
    families: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[dict[str, Any]] = Field(default_factory=list)
    scan_errors: list[dict[str, Any]] = Field(default_factory=list)
    approved_registry_version: str | None = None
    approved_tag_registry_version: str | None = None
    observed_registry_version: str | None = None
    observed_family_count: int | None = None
    observed_tag_count: int | None = None
    observed_merge_applied: bool = False
    repo_sync: dict[str, Any] = Field(default_factory=dict)


class XmlSchemaApprovalRequest(BaseModel):
    fingerprint_hash: str
    schema_family_id: str | None = None
    parser_profile: str | None = None
    registry_type: str | None = None
    batch_job_id: str | None = None


class XmlSchemaApprovalResponse(BaseModel):
    registry_version: str
    fingerprint_hash: str
    approved_family: dict[str, Any] = Field(default_factory=dict)
    repo_sync: dict[str, Any] = Field(default_factory=dict)


class XmlSchemaTagApprovalRequest(BaseModel):
    tag_fingerprint_hash: str
    schema_tag_id: str | None = None
    parser_profile: str | None = None
    registry_type: str | None = None
    batch_job_id: str | None = None


class XmlSchemaTagApprovalResponse(BaseModel):
    registry_version: str
    tag_fingerprint_hash: str
    approved_tag: dict[str, Any] = Field(default_factory=dict)
    repo_sync: dict[str, Any] = Field(default_factory=dict)
