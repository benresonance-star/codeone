from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
import re

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
        self._converters: dict[tuple[bool, bool, bool], DocumentConverter] = {}

    def extract(self, pdf_bytes: bytes, *, decision: DocumentStrategyDecision) -> ExtractedPdf:
        if DocumentConverter is None or InputFormat is None or PdfFormatOption is None or PdfPipelineOptions is None:
            return self._fallback_extract(pdf_bytes, decision, reason="Docling is not importable in this runtime.")

        try:
            runtime_flags = self._runtime_flags(decision)
            converter = self._get_converter(runtime_flags)
            result = self._convert_pdf_bytes(converter, pdf_bytes)
            blocks = self._collect_blocks(result)
            tables = self._collect_tables(result, decision)
            if not blocks:
                return self._fallback_extract(pdf_bytes, decision, reason="Docling returned no structured blocks.")

            return ExtractedPdf(
                pages_processed=len(result.pages),
                total_words=sum(len(block.text.split()) for block in blocks),
                blocks=blocks,
                tables=tables,
                strategy_name="docling",
                runtime_mode=self._runtime_mode(runtime_flags),
                notes=list(self._notes_for_runtime_mode(runtime_flags)),
            )
        except Exception as exc:  # noqa: BLE001
            return self._fallback_extract(pdf_bytes, decision, reason=f"Docling conversion failed: {exc}")

    def _get_converter(self, runtime_flags: tuple[bool, bool, bool]) -> DocumentConverter:
        if runtime_flags not in self._converters:
            enable_ocr, enable_table_structure, force_backend_text = runtime_flags
            options = PdfPipelineOptions(
                do_ocr=enable_ocr,
                do_table_structure=enable_table_structure,
                force_backend_text=force_backend_text,
            )
            self._converters[runtime_flags] = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                }
            )
        return self._converters[runtime_flags]

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

    def _collect_tables(self, result: Any, decision: DocumentStrategyDecision) -> list[ExtractedTable]:
        document = result.document
        items = list(document.iterate_items())
        tables: list[ExtractedTable] = []
        table_index = 0
        for item_index, (item, _) in enumerate(items):
            if self._label_name(item) != "table":
                continue

            rows, normalization_meta = self._normalize_table(item, document, decision, items, item_index)
            provenance = self._primary_provenance(item)
            page_number = int(getattr(provenance, "page_no", 1) or 1)
            data = getattr(item, "data", None)
            if not rows:
                continue
            table_index += 1
            tables.append(
                ExtractedTable(
                    table_id=f"docling_tbl_{table_index}",
                    rows=rows,
                    headers_present=self._headers_present(rows),
                    related_block_id=f"docling_{page_number}_{item_index + 1}",
                    bbox=self._bbox_from_provenance(provenance),
                    metadata={
                        "source": "docling",
                        "page": page_number,
                        "num_rows": getattr(data, "num_rows", len(rows)),
                        "num_cols": getattr(data, "num_cols", max((len(row) for row in rows), default=0)),
                        "caption_text": self._caption_text(item),
                        **normalization_meta,
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

    def _normalize_table(
        self,
        item: Any,
        document: Any,
        decision: DocumentStrategyDecision,
        items: list[tuple[Any, int]],
        item_index: int,
    ) -> tuple[list[list[str]], dict[str, Any]]:
        data = getattr(item, "data", None)
        rows: list[list[str]] = []
        metadata: dict[str, Any] = {
            "header_row_count": 0,
            "has_merged_headers": False,
            "empty_cell_ratio": 0.0,
            "source_cell_count": 0,
            "span_count": 0,
            "repaired": False,
            "normalization_strategy": "text_fallback",
            "discarded": False,
        }

        if data is not None and getattr(data, "table_cells", None):
            rows, cell_meta = self._rows_from_table_cells(data)
            metadata.update(cell_meta)
            metadata["normalization_strategy"] = "table_cells_grid"
        if not rows:
            rows = self._table_rows(item, document)
            metadata["normalization_strategy"] = "dataframe_or_text_fallback"

        if self._is_empty_wrapper_table(data, rows):
            contextual_rows = self._contextual_table_rows(items, item_index, decision)
            if contextual_rows:
                rows = contextual_rows
                metadata["normalization_strategy"] = "contextual_text_pairs"
            else:
                metadata["discarded"] = True
                metadata["normalization_strategy"] = "discarded_wrapper_table"
                return [], metadata

        rows, header_meta = self._normalize_header_rows(rows, metadata)
        metadata.update(header_meta)

        if decision.document_class == "definitions_glossary":
            rows, repair_meta = self._repair_glossary_rows(rows, metadata)
            metadata.update(repair_meta)

        metadata["num_rows"] = len(rows)
        metadata["num_cols"] = max((len(row) for row in rows), default=0)
        return rows, metadata

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

        raw_text = getattr(item, "text", None)
        if isinstance(raw_text, str) and raw_text.strip():
            return [[self._normalize_cell(cell)] for cell in raw_text.splitlines() if cell.strip()]

        text = self._item_text(item)
        return [[cell] for cell in text.splitlines() if cell.strip()]

    def _rows_from_table_cells(self, data: Any) -> tuple[list[list[str]], dict[str, Any]]:
        num_rows = max(int(getattr(data, "num_rows", 0) or 0), 1)
        num_cols = max(int(getattr(data, "num_cols", 0) or 0), 1)
        cells = list(getattr(data, "table_cells", []) or [])
        grid = [[{"text": "", "anchor": True, "header": False, "spanned": False} for _ in range(num_cols)] for _ in range(num_rows)]
        span_count = 0
        has_merged_headers = False

        for cell in cells:
            text = self._normalize_cell(getattr(cell, "text", ""))
            row_start = max(int(getattr(cell, "start_row_offset_idx", 0) or 0), 0)
            row_end = min(max(int(getattr(cell, "end_row_offset_idx", row_start + 1) or row_start + 1), row_start + 1), num_rows)
            col_start = max(int(getattr(cell, "start_col_offset_idx", 0) or 0), 0)
            col_end = min(max(int(getattr(cell, "end_col_offset_idx", col_start + 1) or col_start + 1), col_start + 1), num_cols)
            is_header = bool(getattr(cell, "column_header", False) or getattr(cell, "row_header", False))

            if row_end - row_start > 1 or col_end - col_start > 1:
                has_merged_headers = has_merged_headers or is_header

            for row_index in range(row_start, row_end):
                for col_index in range(col_start, col_end):
                    anchor = row_index == row_start and col_index == col_start
                    if not anchor:
                        span_count += 1
                    grid[row_index][col_index] = {
                        "text": text,
                        "anchor": anchor,
                        "header": is_header,
                        "spanned": not anchor,
                    }

        rows: list[list[str]] = []
        empty_cells = 0
        total_cells = 0
        header_row_count = 0
        for row in grid:
            normalized_row: list[str] = []
            row_is_header = False
            for cell in row:
                total_cells += 1
                if cell["spanned"] and not cell["anchor"]:
                    value = ""
                else:
                    value = cell["text"]
                if cell["header"]:
                    row_is_header = True
                if not value:
                    empty_cells += 1
                normalized_row.append(value)
            if any(normalized_row):
                rows.append(normalized_row)
                if row_is_header and header_row_count == len(rows) - 1:
                    header_row_count += 1

        return rows, {
            "header_row_count": header_row_count,
            "has_merged_headers": has_merged_headers,
            "empty_cell_ratio": round(empty_cells / max(total_cells, 1), 3),
            "source_cell_count": len(cells),
            "span_count": span_count,
        }

    def _is_empty_wrapper_table(self, data: Any, rows: list[list[str]]) -> bool:
        if data is None:
            return False
        num_rows = int(getattr(data, "num_rows", 0) or 0)
        num_cols = int(getattr(data, "num_cols", 0) or 0)
        cells = list(getattr(data, "table_cells", []) or [])
        if num_rows != 1 or num_cols != 1 or len(cells) != 1:
            return False
        cell_text = self._normalize_cell(getattr(cells[0], "text", ""))
        return not cell_text

    def _contextual_table_rows(
        self,
        items: list[tuple[Any, int]],
        item_index: int,
        decision: DocumentStrategyDecision,
    ) -> list[list[str]]:
        if decision.document_class != "definitions_glossary":
            return []

        collected: list[str] = []
        for next_item, _ in items[item_index + 1 :]:
            label = self._label_name(next_item)
            if label == "table":
                break
            if label == "section_header":
                if collected:
                    break
                continue
            if label not in {"text", "list_item", "caption"}:
                if collected:
                    break
                continue
            text = self._item_text(next_item)
            if not text:
                if collected:
                    break
                continue
            collected.append(text)

        if len(collected) < 4:
            return []

        header_left = collected[0]
        header_right = collected[1]
        if not self._looks_like_definition_header(header_left, header_right):
            return []

        rows = [[header_left, header_right]]
        body = collected[2:]
        for offset in range(0, len(body), 2):
            term = body[offset]
            definition = body[offset + 1] if offset + 1 < len(body) else ""
            if not definition:
                break
            rows.append([term, definition])
        return rows if len(rows) > 1 else []

    def _looks_like_definition_header(self, left: str, right: str) -> bool:
        pair = f"{left} {right}".lower()
        return "definition" in pair and any(token in pair for token in ("abbreviation", "symbol", "glossary"))

    def _normalize_header_rows(
        self,
        rows: list[list[str]],
        metadata: dict[str, Any],
    ) -> tuple[list[list[str]], dict[str, Any]]:
        if not rows:
            return rows, {"header_row_count": 0}

        normalized_rows = [[self._normalize_cell(cell) for cell in row] for row in rows]
        header_row_count = int(metadata.get("header_row_count", 0))
        if header_row_count == 0:
            header_row_count = self._infer_header_row_count(normalized_rows)

        if header_row_count > 1:
            merged_header = list(normalized_rows[0])
            for row_index in range(1, header_row_count):
                merged_header = self._merge_continuation_row_into_header(merged_header, normalized_rows[row_index])
            normalized_rows[0] = merged_header
            normalized_rows = [row for idx, row in enumerate(normalized_rows) if idx == 0 or idx >= header_row_count]
            header_row_count = 1 if normalized_rows else 0

        return normalized_rows, {"header_row_count": header_row_count}

    def _infer_header_row_count(self, rows: list[list[str]]) -> int:
        header_tokens = {"abbreviation", "abbreviations", "definitions", "symbols", "symbol", "glossary", "schedule"}
        count = 0
        for row in rows[:2]:
            joined = " ".join(cell for cell in row if cell).lower()
            if any(token in joined for token in header_tokens):
                count += 1
            else:
                break
        return count

    def _merge_continuation_row_into_header(self, base_row: list[str], continuation_row: list[str]) -> list[str]:
        width = max(len(base_row), len(continuation_row))
        merged: list[str] = []
        for index in range(width):
            left = base_row[index] if index < len(base_row) else ""
            right = continuation_row[index] if index < len(continuation_row) else ""
            merged.append(self._normalize_cell(" ".join(part for part in (left, right) if part)))
        return merged

    def _repair_glossary_rows(
        self,
        rows: list[list[str]],
        metadata: dict[str, Any],
    ) -> tuple[list[list[str]], dict[str, Any]]:
        repaired = False
        strategy = metadata.get("normalization_strategy", "unknown")
        repaired_rows = [list(row) for row in rows]

        if not repaired_rows:
            return repaired_rows, {"repaired": False, "normalization_strategy": strategy}

        repaired_rows, compressed = self._compress_glossary_columns(repaired_rows)
        repaired = repaired or compressed

        repaired_rows, merged = self._merge_glossary_continuations(repaired_rows, int(metadata.get("header_row_count", 0)))
        repaired = repaired or merged

        if self._is_single_cell_table(repaired_rows):
            split_rows = self._split_single_cell_glossary(repaired_rows[0][0])
            if split_rows:
                repaired_rows = split_rows
                repaired = True
                strategy = "repaired_glossary_pairs"

        if repaired and strategy == metadata.get("normalization_strategy"):
            strategy = f"{strategy}_repaired"

        return repaired_rows, {
            "repaired": repaired,
            "normalization_strategy": strategy,
        }

    def _compress_glossary_columns(self, rows: list[list[str]]) -> tuple[list[list[str]], bool]:
        if not rows:
            return rows, False
        max_cols = max(len(row) for row in rows)
        if max_cols <= 2:
            return rows, False

        repaired = False
        compressed_rows: list[list[str]] = []
        for row in rows:
            non_empty = [cell for cell in row if cell]
            if not non_empty:
                continue
            if len(non_empty) <= 2:
                compressed_rows.append((non_empty + [""])[:2])
                continue
            compressed_rows.append([non_empty[0], self._normalize_cell(" ".join(non_empty[1:]))])
            repaired = True
        return compressed_rows, repaired

    def _merge_glossary_continuations(self, rows: list[list[str]], header_row_count: int) -> tuple[list[list[str]], bool]:
        if not rows or max(len(row) for row in rows) < 2:
            return rows, False

        repaired = False
        merged_rows: list[list[str]] = []
        for index, row in enumerate(rows):
            padded = (row + ["", ""])[:2]
            if (
                index > header_row_count
                and not padded[0]
                and padded[1]
                and merged_rows
            ):
                merged_rows[-1][1] = self._normalize_cell(f"{merged_rows[-1][1]} {padded[1]}")
                repaired = True
                continue
            merged_rows.append(padded)
        return merged_rows, repaired

    def _is_single_cell_table(self, rows: list[list[str]]) -> bool:
        return len(rows) == 1 and len(rows[0]) == 1 and bool(rows[0][0])

    def _split_single_cell_glossary(self, text: str) -> list[list[str]]:
        normalized = self._normalize_cell(text)
        match = re.match(r"^(Abbreviation|Symbols?)\s+Definitions?\s+(.*)$", normalized)
        if not match:
            return []

        header_left = match.group(1)
        remainder = match.group(2)
        pattern = re.compile(r"\b([A-Z][A-Z0-9./%°()µ+-]{0,20})\b")
        matches = list(pattern.finditer(remainder))
        if len(matches) < 2:
            return []

        rows = [[header_left, "Definitions"]]
        for index, current in enumerate(matches):
            definition_start = current.end()
            definition_end = matches[index + 1].start() if index + 1 < len(matches) else len(remainder)
            definition = self._normalize_cell(remainder[definition_start:definition_end])
            term = current.group(1)
            if definition:
                rows.append([term, definition])
        return rows if len(rows) > 1 else []

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

    def _runtime_flags(self, decision: DocumentStrategyDecision) -> tuple[bool, bool, bool]:
        requested_mode = str(decision.extractor_options.get("docling_mode", "") or "").strip().lower()
        enable_ocr = self._env_flag("DOCLING_ENABLE_OCR", default=False)
        enable_table_structure = self._env_flag("DOCLING_ENABLE_TABLE_STRUCTURE", default=False)
        force_backend_text = self._env_flag("DOCLING_FORCE_BACKEND_TEXT", default=True)

        if requested_mode == "tables":
            enable_table_structure = True
        elif requested_mode == "ocr":
            enable_ocr = True
        elif requested_mode == "full":
            enable_ocr = True
            enable_table_structure = True
        elif requested_mode == "text":
            enable_ocr = False
            enable_table_structure = False
            force_backend_text = True

        return enable_ocr, enable_table_structure, force_backend_text

    def _runtime_mode(self, runtime_flags: tuple[bool, bool, bool]) -> str:
        enable_ocr, enable_table_structure, force_backend_text = runtime_flags
        flags: list[str] = []
        if enable_ocr:
            flags.append("ocr")
        if enable_table_structure:
            flags.append("tables")
        if force_backend_text:
            flags.append("text")
        return "native_" + "_".join(flags or ["default"])

    def _notes_for_runtime_mode(self, runtime_flags: tuple[bool, bool, bool]) -> tuple[str, str]:
        ocr_enabled, tables_enabled, _ = runtime_flags
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
