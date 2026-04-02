from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.validation import IngestionResponse
from app.services.ingestion import IngestionService

router = APIRouter()
service = IngestionService()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ingestions/validate", response_model=IngestionResponse)
async def validate_ingestion(
    pdf: UploadFile = File(...),
    xml: UploadFile = File(...),
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
        payload = service.process(pdf_bytes=pdf_bytes, pdf_name=pdf.filename, xml_bytes=xml_bytes, xml_name=xml.filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    return IngestionResponse.model_validate(payload)
