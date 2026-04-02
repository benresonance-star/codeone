from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app.models.document_strategy import DocumentStrategyDecision, ExtractedPdf, ExtractedTable, StructuredBlock
from app.services.extractors.pdfplumber_extractor import PdfPlumberExtractor

try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
except ImportError:  # pragma: no cover - covered indirectly through fallback behavior
    DocumentConverter = None
    InputFormat = None
    PdfFormatOption = None
    PdfPipelineOptions = None


class DoclingExtractor:
    def __init__(self) -> None:
        self._fallback = PdfPlumberExtractor()
        self._converter: DocumentConverter | None = None

    def extract(self, pdf_bytes: bytes, *, decision: DocumentStrategyDecision) -> ExtractedPdf:
        if DocumentConverter is None or InputFormat is None or PdfFormatOption is None or PdfPipelineOptions is None:
            return self._fallback_extract(pdf_bytes, decision, reason="Docling is not importable in this runtime.")

        try:
            converter = self._get_converter()
            result = self._convert_pdf_bytes(converter, pdf_bytes)
            blocks = self._collect_blocks(result)
            tables = self._collect_tables(result)
            if not blocks:
                return self._fallback_extract(pdf_bytes, decision, reason="Docling returned no structured blocks.")

            return ExtractedPdf(
                pages_processed=len(result.pages),
                total_words=sum(len(block.text.split()) for block in blocks),
                blocks=blocks,
                tables=tables,
                strategy_name="docling",
                runtime_mode=self._runtime_mode(),
                notes=list(self._notes_for_runtime_mode()),
            )
        except Exception as exc:  # noqa: BLE001
            return self._fallback_extract(pdf_bytes, decision, reason=f"Docling conversion failed: {exc}")

    def _get_converter(self) -> DocumentConverter:
        if self._converter is None:
            enable_ocr = self._env_flag("DOCLING_ENABLE_OCR", default=False)
            enable_table_structure = self._env_flag("DOCLING_ENABLE_TABLE_STRUCTURE", default=False)
            force_backend_text = self._env_flag("DOCLING_FORCE_BACKEND_TEXT", default=True)
            options = PdfPipelineOptions(
                do_ocr=enable_ocr,
                do_table_structure=enable_table_structure,
                force_backend_text=force_backend_text,
            )
            self._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                }
            )
        return self._converter

    def _convert_pdf_bytes(self, converter: DocumentConverter, pdf_bytes: bytes) -> Any:
        with NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(pdf_bytes)
            temp_path = Path(handle.name)
        try:
            return converter.convert(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _collect_blocks(self, result: Any) -> list[StructuredBlock]:
        document = result.document
        blocks: list[StructuredBlock] = []
        for index, (item, level) in enumerate(document.iterate_items(), start=1):
            text = self._item_text(item)
            if not text:
                continue

            provenance = self._primary_provenance(item)
            bbox = self._bbox_from_provenance(provenance)
            page_number = int(getattr(provenance, "page_no", 1) or 1)
            label = self._label_name(item)
            blocks.append(
                StructuredBlock(
                    block_id=f"docling_{page_number}_{index}",
                    page=page_number,
                    bbox=bbox,
                    block_type=self._map_block_type(label),
                    text=text,
                    section_hint=text[:80] if label in {"section_header", "title"} else None,
                    heading_level=level if label in {"section_header", "title"} else None,
                    source_strategy="docling",
                    metadata={
                        "docling_label": label,
                        "docling_level": level,
                    },
                )
            )
        return blocks

    def _collect_tables(self, result: Any) -> list[ExtractedTable]:
        document = result.document
        tables: list[ExtractedTable] = []
        for index, (item, _) in enumerate(document.iterate_items(), start=1):
            if self._label_name(item) != "table":
                continue

            rows = self._table_rows(item, document)
            provenance = self._primary_provenance(item)
            data = getattr(item, "data", None)
            tables.append(
                ExtractedTable(
                    table_id=f"docling_tbl_{index}",
                    rows=rows,
                    headers_present=self._headers_present(rows),
                    bbox=self._bbox_from_provenance(provenance),
                    metadata={
                        "source": "docling",
                        "num_rows": getattr(data, "num_rows", len(rows)),
                        "num_cols": getattr(data, "num_cols", max((len(row) for row in rows), default=0)),
                        "caption_text": self._caption_text(item),
                    },
                )
            )
        return tables

    def _fallback_extract(self, pdf_bytes: bytes, decision: DocumentStrategyDecision, *, reason: str) -> ExtractedPdf:
        extracted = self._fallback.extract(pdf_bytes, decision=decision)
        notes = list(extracted.notes)
        notes.append(reason)
        notes.append("pdfplumber fallback used after Docling path was attempted.")
        return ExtractedPdf(
            pages_processed=extracted.pages_processed,
            total_words=extracted.total_words,
            blocks=extracted.blocks,
            tables=extracted.tables,
            strategy_name="docling",
            runtime_mode="fallback_pdfplumber",
            notes=notes,
        )

    def _item_text(self, item: Any) -> str:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            return " ".join(text.split())
        export_to_text = getattr(item, "export_to_text", None)
        if callable(export_to_text):
            return " ".join(str(export_to_text()).split())
        return ""

    def _primary_provenance(self, item: Any) -> Any | None:
        provenance = getattr(item, "prov", None)
        if provenance:
            return provenance[0]
        return None

    def _bbox_from_provenance(self, provenance: Any | None) -> list[float]:
        bbox = getattr(provenance, "bbox", None)
        if bbox is None:
            return [0.0, 0.0, 0.0, 0.0]
        return [
            round(float(getattr(bbox, "l", 0.0)), 2),
            round(float(getattr(bbox, "t", 0.0)), 2),
            round(float(getattr(bbox, "r", 0.0)), 2),
            round(float(getattr(bbox, "b", 0.0)), 2),
        ]

    def _label_name(self, item: Any) -> str:
        label = getattr(item, "label", None)
        if label is None:
            return "text"
        value = getattr(label, "value", None)
        return str(value or label)

    def _map_block_type(self, label: str) -> str:
        return {
            "title": "heading",
            "section_header": "heading",
            "list_item": "list_item",
            "caption": "caption",
            "table": "table",
            "text": "paragraph",
        }.get(label, "paragraph")

    def _table_rows(self, item: Any, document: Any) -> list[list[str]]:
        export_to_dataframe = getattr(item, "export_to_dataframe", None)
        if callable(export_to_dataframe):
            try:
                dataframe = export_to_dataframe(doc=document)
            except TypeError:
                dataframe = export_to_dataframe()
            values = dataframe.fillna("").values.tolist()
            rows = [[self._normalize_cell(cell) for cell in row] for row in values]
            non_empty = [row for row in rows if any(cell for cell in row)]
            if non_empty:
                return non_empty

        text = self._item_text(item)
        return [[cell] for cell in text.splitlines() if cell.strip()]

    def _normalize_cell(self, cell: Any) -> str:
        return " ".join(str(cell or "").split())

    def _headers_present(self, rows: list[list[str]]) -> bool:
        return bool(rows and any(cell for cell in rows[0]))

    def _caption_text(self, item: Any) -> str | None:
        caption_text = getattr(item, "caption_text", None)
        if isinstance(caption_text, str) and caption_text.strip():
            return " ".join(caption_text.split())
        return None

    def _env_flag(self, name: str, *, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _runtime_mode(self) -> str:
        flags: list[str] = []
        if self._env_flag("DOCLING_ENABLE_OCR", default=False):
            flags.append("ocr")
        if self._env_flag("DOCLING_ENABLE_TABLE_STRUCTURE", default=False):
            flags.append("tables")
        if self._env_flag("DOCLING_FORCE_BACKEND_TEXT", default=True):
            flags.append("text")
        return "native_" + "_".join(flags or ["default"])

    def _notes_for_runtime_mode(self) -> tuple[str, str]:
        ocr_enabled = self._env_flag("DOCLING_ENABLE_OCR", default=False)
        tables_enabled = self._env_flag("DOCLING_ENABLE_TABLE_STRUCTURE", default=False)
        if ocr_enabled or tables_enabled:
            return (
                "Docling configurable pipeline active.",
                f"OCR enabled={ocr_enabled}; table_structure enabled={tables_enabled}.",
            )
        return (
            "Docling text-first pipeline active.",
            "OCR and table structure remain disabled until explicitly enabled.",
        )


DoclingStubExtractor = DoclingExtractor
