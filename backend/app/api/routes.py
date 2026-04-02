from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.core.database import session_scope
from app.models.validation import (
    IngestionResponse,
    IngestionRunListResponse,
    InvalidationResponse,
    PurgeSummaryResponse,
)
from app.services.ingestion import IngestionService
from app.services.retention import RetentionService

router = APIRouter()
service = IngestionService()
retention_service = RetentionService()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


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
