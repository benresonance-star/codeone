from __future__ import annotations

from typing import Protocol

from app.models.document_strategy import DocumentStrategyDecision, ExtractedPdf


class PdfExtractor(Protocol):
    def extract(self, pdf_bytes: bytes, *, decision: DocumentStrategyDecision) -> ExtractedPdf:
        ...
