from __future__ import annotations

from dataclasses import replace

from app.models.document_strategy import DocumentStrategyDecision, ExtractedPdf
from app.services.extractors.pdfplumber_extractor import PdfPlumberExtractor


class DoclingStubExtractor:
    def __init__(self) -> None:
        self._fallback = PdfPlumberExtractor()

    def extract(self, pdf_bytes: bytes, *, decision: DocumentStrategyDecision) -> ExtractedPdf:
        extracted = self._fallback.extract(pdf_bytes, decision=decision)
        blocks = [
            replace(
                block,
                source_strategy="docling_stub",
                metadata={**block.metadata, "fallback_strategy": "pdfplumber"},
            )
            for block in extracted.blocks
        ]
        tables = [
            replace(table, metadata={**table.metadata, "fallback_strategy": "pdfplumber"})
            for table in extracted.tables
        ]
        notes = list(extracted.notes)
        notes.append("Docling runtime not active; pdfplumber fallback used through stub strategy.")
        return ExtractedPdf(
            pages_processed=extracted.pages_processed,
            total_words=extracted.total_words,
            blocks=blocks,
            tables=tables,
            strategy_name="docling",
            runtime_mode="stub_fallback",
            notes=notes,
        )
