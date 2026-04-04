from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.database import session_scope
from app.models.validation import (
    IngestionResponse,
    IngestionRunListResponse,
    InvalidationResponse,
    PurgeSummaryResponse,
    ReviewDecisionListResponse,
    ReviewDecisionRecord,
    ReviewDecisionRequest,
    XmlSchemaApprovalRequest,
    XmlSchemaApprovalResponse,
    XmlSchemaBatchResponse,
    XmlSchemaFamilyDetailResponse,
    XmlSchemaFamilyListResponse,
    XmlSchemaScanResponse,
    XmlSchemaTagApprovalRequest,
    XmlSchemaTagApprovalResponse,
    XmlSchemaTagDetailResponse,
    XmlSchemaTagListResponse,
)
from app.services.ingestion import IngestionService
from app.services.retention import RetentionService
from app.services.xml_schema_registry import XmlSchemaRegistryService

router = APIRouter()
service = IngestionService()
retention_service = RetentionService()
xml_schema_registry_service = XmlSchemaRegistryService()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/xml-schemas/scan", response_model=XmlSchemaScanResponse)
def scan_xml_schema_corpus() -> XmlSchemaScanResponse:
    try:
        observed_registry = xml_schema_registry_service.scan_repo_xml_corpus()
        approved_registry = xml_schema_registry_service.load_approved_registry()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to scan XML schema corpus: {exc}") from exc
    return XmlSchemaScanResponse(
        registry_version=str(observed_registry.get("registry_version") or ""),
        generated_at=str(observed_registry.get("generated_at") or ""),
        scanned_file_count=int(observed_registry.get("scanned_file_count") or 0),
        family_count=int(observed_registry.get("family_count") or 0),
        tag_count=int(observed_registry.get("tag_count") or 0),
        approved_registry_version=approved_registry.get("registry_version"),
        approved_tag_registry_version=xml_schema_registry_service.load_approved_tag_registry().get("registry_version"),
        scan_errors=list(observed_registry.get("scan_errors") or []),
        repo_sync=dict(approved_registry.get("repo_sync") or {}),
    )


@router.post("/xml-schemas/batches/upload", response_model=XmlSchemaBatchResponse)
async def upload_xml_schema_batch(files: list[UploadFile] = File(...)) -> XmlSchemaBatchResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one XML file is required.")
    try:
        uploaded_files: list[tuple[str, bytes]] = []
        for file in files:
            if not file.filename:
                continue
            uploaded_files.append((file.filename, await file.read()))
        if not uploaded_files:
            raise HTTPException(status_code=400, detail="No uploadable XML files were provided.")
        payload = xml_schema_registry_service.scan_uploaded_xml_batch(uploaded_files)
        approved_registry = xml_schema_registry_service.load_approved_registry()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to scan uploaded XML batch: {exc}") from exc
    return XmlSchemaBatchResponse(
        batch_job_id=str(payload.get("batch_job_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        uploaded_file_count=int(payload.get("uploaded_file_count") or 0),
        scanned_file_count=int(payload.get("scanned_file_count") or 0),
        family_count=int(payload.get("family_count") or 0),
        tag_count=int(payload.get("tag_count") or 0),
        families=list(payload.get("families") or []),
        tags=list(payload.get("tags") or []),
        scan_errors=list(payload.get("scan_errors") or []),
        approved_registry_version=payload.get("approved_registry_version"),
        approved_tag_registry_version=payload.get("approved_tag_registry_version"),
        observed_registry_version=payload.get("observed_registry_version"),
        observed_family_count=payload.get("observed_family_count"),
        observed_tag_count=payload.get("observed_tag_count"),
        observed_merge_applied=bool(payload.get("observed_merge_applied")),
        repo_sync=dict(approved_registry.get("repo_sync") or {}),
    )


@router.get("/xml-schemas/batches/{batch_job_id}", response_model=XmlSchemaBatchResponse)
def load_xml_schema_batch(batch_job_id: str) -> XmlSchemaBatchResponse:
    try:
        payload = xml_schema_registry_service.load_batch_job(batch_job_id)
        approved_registry = xml_schema_registry_service.load_approved_registry()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load schema batch job: {exc}") from exc
    return XmlSchemaBatchResponse(
        batch_job_id=str(payload.get("batch_job_id") or batch_job_id),
        generated_at=str(payload.get("generated_at") or ""),
        uploaded_file_count=int(payload.get("uploaded_file_count") or 0),
        scanned_file_count=int(payload.get("scanned_file_count") or 0),
        family_count=int(payload.get("family_count") or 0),
        tag_count=int(payload.get("tag_count") or 0),
        families=list(payload.get("families") or []),
        tags=list(payload.get("tags") or []),
        scan_errors=list(payload.get("scan_errors") or []),
        approved_registry_version=payload.get("approved_registry_version"),
        approved_tag_registry_version=payload.get("approved_tag_registry_version"),
        observed_registry_version=payload.get("observed_registry_version"),
        observed_family_count=payload.get("observed_family_count"),
        observed_tag_count=payload.get("observed_tag_count"),
        observed_merge_applied=bool(payload.get("observed_merge_applied")),
        repo_sync=dict(approved_registry.get("repo_sync") or {}),
    )


@router.get("/xml-schemas/families", response_model=XmlSchemaFamilyListResponse)
def list_xml_schema_families(registry_type: str = Query(default="observed")) -> XmlSchemaFamilyListResponse:
    if registry_type not in {"observed", "approved"}:
        raise HTTPException(status_code=400, detail="registry_type must be `observed` or `approved`.")
    try:
        registry = (
            xml_schema_registry_service.load_approved_registry()
            if registry_type == "approved"
            else xml_schema_registry_service.load_observed_registry()
        )
        approved_registry = xml_schema_registry_service.load_approved_registry()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load XML schema registry: {exc}") from exc
    return XmlSchemaFamilyListResponse(
        registry_type=registry_type,
        registry_version=registry.get("registry_version"),
        generated_at=registry.get("generated_at"),
        scanned_file_count=registry.get("scanned_file_count"),
        family_count=registry.get("family_count"),
        families=list(registry.get("families") or []),
        scan_errors=list(registry.get("scan_errors") or []),
        repo_sync=dict(approved_registry.get("repo_sync") or {}),
    )


@router.get("/xml-schemas/tags", response_model=XmlSchemaTagListResponse)
def list_xml_schema_tags(registry_type: str = Query(default="observed")) -> XmlSchemaTagListResponse:
    if registry_type not in {"observed", "approved"}:
        raise HTTPException(status_code=400, detail="registry_type must be `observed` or `approved`.")
    try:
        registry = (
            xml_schema_registry_service.load_approved_tag_registry()
            if registry_type == "approved"
            else xml_schema_registry_service.load_observed_registry()
        )
        approved_registry = xml_schema_registry_service.load_approved_tag_registry()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load XML schema tag registry: {exc}") from exc
    return XmlSchemaTagListResponse(
        registry_type=registry_type,
        registry_version=registry.get("registry_version"),
        generated_at=registry.get("generated_at"),
        scanned_file_count=registry.get("scanned_file_count"),
        tag_count=registry.get("tag_count"),
        tags=list(registry.get("tags") or []),
        scan_errors=list(registry.get("scan_errors") or []),
        repo_sync=dict(approved_registry.get("repo_sync") or {}),
    )


@router.get("/xml-schemas/families/{family_key}", response_model=XmlSchemaFamilyDetailResponse)
def get_xml_schema_family_detail(
    family_key: str,
    registry_type: str = Query(default="observed"),
) -> XmlSchemaFamilyDetailResponse:
    if registry_type not in {"observed", "approved"}:
        raise HTTPException(status_code=400, detail="registry_type must be `observed` or `approved`.")
    try:
        payload = xml_schema_registry_service.get_schema_family_detail(registry_type, family_key)
        approved_registry = xml_schema_registry_service.load_approved_registry()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load schema family detail: {exc}") from exc
    return XmlSchemaFamilyDetailResponse(
        registry_type=str(payload.get("registry_type") or registry_type),
        registry_version=payload.get("registry_version"),
        family=dict(payload.get("family") or {}),
        repo_sync=dict(approved_registry.get("repo_sync") or {}),
    )


@router.get("/xml-schemas/tags/{tag_key}", response_model=XmlSchemaTagDetailResponse)
def get_xml_schema_tag_detail(
    tag_key: str,
    registry_type: str = Query(default="observed"),
) -> XmlSchemaTagDetailResponse:
    if registry_type not in {"observed", "approved"}:
        raise HTTPException(status_code=400, detail="registry_type must be `observed` or `approved`.")
    try:
        payload = xml_schema_registry_service.get_schema_tag_detail(registry_type, tag_key)
        approved_registry = xml_schema_registry_service.load_approved_tag_registry()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load schema tag detail: {exc}") from exc
    return XmlSchemaTagDetailResponse(
        registry_type=str(payload.get("registry_type") or registry_type),
        registry_version=payload.get("registry_version"),
        tag=dict(payload.get("tag") or {}),
        repo_sync=dict(approved_registry.get("repo_sync") or {}),
    )


@router.post("/xml-schemas/approve", response_model=XmlSchemaApprovalResponse)
def approve_xml_schema_family(payload: XmlSchemaApprovalRequest) -> XmlSchemaApprovalResponse:
    try:
        result = xml_schema_registry_service.approve_observed_family(
            fingerprint_hash=payload.fingerprint_hash,
            schema_family_id=payload.schema_family_id,
            parser_profile=payload.parser_profile,
            registry_type=payload.registry_type,
            batch_job_id=payload.batch_job_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to approve schema family: {exc}") from exc
    return XmlSchemaApprovalResponse(
        registry_version=str(result.get("registry_version") or ""),
        fingerprint_hash=str(result.get("fingerprint_hash") or payload.fingerprint_hash),
        approved_family=dict(result.get("approved_family") or {}),
        repo_sync=dict(result.get("repo_sync") or {}),
    )


@router.post("/xml-schemas/tags/approve", response_model=XmlSchemaTagApprovalResponse)
def approve_xml_schema_tag(payload: XmlSchemaTagApprovalRequest) -> XmlSchemaTagApprovalResponse:
    try:
        result = xml_schema_registry_service.approve_observed_tag(
            tag_fingerprint_hash=payload.tag_fingerprint_hash,
            schema_tag_id=payload.schema_tag_id,
            parser_profile=payload.parser_profile,
            registry_type=payload.registry_type,
            batch_job_id=payload.batch_job_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to approve schema tag: {exc}") from exc
    return XmlSchemaTagApprovalResponse(
        registry_version=str(result.get("registry_version") or ""),
        tag_fingerprint_hash=str(result.get("tag_fingerprint_hash") or payload.tag_fingerprint_hash),
        approved_tag=dict(result.get("approved_tag") or {}),
        repo_sync=dict(result.get("repo_sync") or {}),
    )


@router.post("/ingestions/validate", response_model=IngestionResponse)
async def validate_ingestion(
    pdf: UploadFile = File(...),
    xml: UploadFile = File(...),
    document_class: str | None = Query(default=None),
    extraction_profile: str | None = Query(default=None),
    evaluation_profile: str | None = Query(default=None),
    extractor_strategy: str | None = Query(default=None),
) -> IngestionResponse:
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="A PDF file is required.")
    if not xml.filename or not xml.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="An XML file is required.")

    pdf_bytes = await pdf.read()
    xml_bytes = await xml.read()
    if not pdf_bytes or not xml_bytes:
        raise HTTPException(status_code=400, detail="Uploaded files cannot be empty.")

    try:
        payload = service.process(
            pdf_bytes=pdf_bytes,
            pdf_name=pdf.filename,
            xml_bytes=xml_bytes,
            xml_name=xml.filename,
            document_class=document_class,
            extraction_profile=extraction_profile,
            evaluation_profile=evaluation_profile,
            extractor_strategy=extractor_strategy,
        )
        with session_scope() as session:
            payload = retention_service.persist_ingestion(
                session,
                payload=payload,
                pdf_name=pdf.filename,
                pdf_bytes=pdf_bytes,
                xml_name=xml.filename,
                xml_bytes=xml_bytes,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    return IngestionResponse.model_validate(payload)


@router.get("/ingestions/runs", response_model=IngestionRunListResponse)
def list_ingestion_runs() -> IngestionRunListResponse:
    try:
        with session_scope() as session:
            runs = retention_service.list_runs(session)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to list ingestion runs: {exc}") from exc
    return IngestionRunListResponse(runs=runs)


@router.get("/ingestions/runs/{run_id}", response_model=IngestionResponse)
def load_ingestion_run(run_id: str) -> IngestionResponse:
    try:
        with session_scope() as session:
            payload = retention_service.load_run_payload(session, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load ingestion run: {exc}") from exc
    return IngestionResponse.model_validate(payload)


@router.get("/ingestions/runs/{run_id}/pdf")
def load_ingestion_run_pdf(run_id: str) -> FileResponse:
    try:
        with session_scope() as session:
            pdf_path, media_type, file_name = retention_service.resolve_run_pdf(session, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load retained PDF: {exc}") from exc
    return FileResponse(path=pdf_path, media_type=media_type, filename=file_name)


@router.post("/ingestions/runs/{run_id}/invalidate", response_model=InvalidationResponse)
def invalidate_ingestion_run(run_id: str) -> InvalidationResponse:
    try:
        with session_scope() as session:
            payload = retention_service.invalidate_run(
                session,
                run_id=run_id,
                reason="Marked invalid by operator review.",
                requested_by="api_user",
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to invalidate run: {exc}") from exc
    return InvalidationResponse.model_validate(payload)


@router.get("/ingestions/runs/{run_id}/review-decisions", response_model=ReviewDecisionListResponse)
def list_review_decisions(run_id: str) -> ReviewDecisionListResponse:
    try:
        with session_scope() as session:
            decisions = retention_service.list_review_decisions(session, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load review decisions: {exc}") from exc
    return ReviewDecisionListResponse(decisions=decisions)


@router.post("/ingestions/runs/{run_id}/review-decisions", response_model=ReviewDecisionRecord)
def save_review_decision(run_id: str, payload: ReviewDecisionRequest) -> ReviewDecisionRecord:
    try:
        with session_scope() as session:
            record = retention_service.save_review_decision(
                session,
                run_id=run_id,
                candidate_id=payload.candidate_id,
                fragment_id=payload.fragment_id,
                node_id=payload.node_id,
                decision_status=payload.decision_status,
                note=payload.note,
                requested_by="api_user",
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to save review decision: {exc}") from exc
    return ReviewDecisionRecord.model_validate(record)


@router.get("/purge/runs/{run_id}/dry-run", response_model=PurgeSummaryResponse)
def dry_run_purge_run(run_id: str) -> PurgeSummaryResponse:
    try:
        with session_scope() as session:
            payload = retention_service.dry_run_purge_run(session, run_id=run_id, requested_by="api_user")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to build purge preview: {exc}") from exc
    return PurgeSummaryResponse.model_validate(payload)


@router.post("/purge/runs/{run_id}", response_model=PurgeSummaryResponse)
def purge_run(run_id: str) -> PurgeSummaryResponse:
    try:
        with session_scope() as session:
            payload = retention_service.purge_run(session, run_id=run_id, requested_by="api_user")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to purge run: {exc}") from exc
    return PurgeSummaryResponse.model_validate(payload)


@router.get("/purge/source-documents/{source_document_id}/dry-run", response_model=PurgeSummaryResponse)
def dry_run_purge_source_document(source_document_id: str) -> PurgeSummaryResponse:
    try:
        with session_scope() as session:
            payload = retention_service.dry_run_purge_source_document(
                session,
                source_document_id=source_document_id,
                requested_by="api_user",
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to build source purge preview: {exc}") from exc
    return PurgeSummaryResponse.model_validate(payload)


@router.post("/purge/source-documents/{source_document_id}", response_model=PurgeSummaryResponse)
def purge_source_document(source_document_id: str) -> PurgeSummaryResponse:
    try:
        with session_scope() as session:
            payload = retention_service.purge_source_document(
                session,
                source_document_id=source_document_id,
                requested_by="api_user",
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to purge source document family: {exc}") from exc
    return PurgeSummaryResponse.model_validate(payload)
