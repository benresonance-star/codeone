from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
import re

from app.models.document_strategy import DocumentStrategyDecision, ExtractedPdf, ExtractedTable, StructuredBlock
from app.services.extractors.pdfplumber_extractor import PdfPlumberExtractor
from app.services.extractors.pymupdf_style_extractor import PyMuPdfStyleExtractor

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
    @classmethod
    def is_available(cls) -> bool:
        return all(
            dependency is not None
            for dependency in (DocumentConverter, InputFormat, PdfFormatOption, PdfPipelineOptions)
        )

    def __init__(self) -> None:
        self._fallback = PdfPlumberExtractor()
        self._converters: dict[tuple[bool, bool, bool], DocumentConverter] = {}
        self._style_extractor = PyMuPdfStyleExtractor()

    def extract(self, pdf_bytes: bytes, *, decision: DocumentStrategyDecision) -> ExtractedPdf:
        if not self.is_available():
            return self._fallback_extract(pdf_bytes, decision, reason="Docling is not importable in this runtime.")

        try:
            runtime_flags = self._runtime_flags(decision)
            converter = self._get_converter(runtime_flags)
            result = self._convert_pdf_bytes(converter, pdf_bytes)
            blocks = self._collect_blocks(result)
            tables = self._collect_tables(result, decision)
            blocks, style_notes = self._apply_style_enrichment(pdf_bytes, blocks)
            if not blocks:
                return self._fallback_extract(pdf_bytes, decision, reason="Docling returned no structured blocks.")

            return ExtractedPdf(
                pages_processed=len(result.pages),
                total_words=sum(len(block.text.split()) for block in blocks),
                blocks=blocks,
                tables=tables,
                strategy_name="docling",
                runtime_mode=self._runtime_mode(runtime_flags),
                notes=[*self._notes_for_runtime_mode(runtime_flags), *style_notes],
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
        blocks, style_notes = self._apply_style_enrichment(pdf_bytes, extracted.blocks)
        notes = list(extracted.notes)
        notes.append(reason)
        notes.append("pdfplumber fallback used after Docling path was attempted.")
        notes.extend(style_notes)
        return ExtractedPdf(
            pages_processed=extracted.pages_processed,
            total_words=extracted.total_words,
            blocks=blocks,
            tables=extracted.tables,
            strategy_name="docling",
            runtime_mode="fallback_pdfplumber",
            notes=notes,
        )

    def _apply_style_enrichment(
        self,
        pdf_bytes: bytes,
        blocks: list[StructuredBlock],
    ) -> tuple[list[StructuredBlock], list[str]]:
        if not blocks:
            return blocks, []
        if not self._style_extractor.is_available():
            return blocks, ["pymupdf_style:unavailable"]

        try:
            style_spans = self._style_extractor.extract(pdf_bytes)
        except Exception as exc:  # noqa: BLE001
            return blocks, [f"pymupdf_style:failed:{exc}"]

        spans_by_page: dict[int, list[dict[str, Any]]] = {}
        for span in style_spans:
            page = int(span.get("page") or 0)
            if page <= 0:
                continue
            spans_by_page.setdefault(page, []).append(span)

        enriched_blocks: list[StructuredBlock] = []
        matched_blocks = 0
        for block in blocks:
            matched_spans = [
                span
                for span in spans_by_page.get(block.page, [])
                if self._span_matches_block(span_bbox=span.get("bbox"), block_bbox=block.bbox)
            ]
            style_payload = self._style_payload_for_block(block, matched_spans)
            if not style_payload:
                enriched_blocks.append(block)
                continue
            metadata = dict(block.metadata)
            metadata.update(style_payload)
            enriched_blocks.append(replace(block, metadata=metadata))
            matched_blocks += 1

        notes = [
            f"pymupdf_style:spans={len(style_spans)}",
            f"pymupdf_style:matched_blocks={matched_blocks}",
        ]
        if matched_blocks == 0:
            notes.append("pymupdf_style:no_block_matches")
        return enriched_blocks, notes

    def _style_payload_for_block(self, block: StructuredBlock, matched_spans: list[dict[str, Any]]) -> dict[str, Any]:
        if not matched_spans or not block.text:
            return {}

        sorted_spans = sorted(
            matched_spans,
            key=lambda span: (
                float((span.get("bbox") or [0.0, 0.0, 0.0, 0.0])[1]),
                float((span.get("bbox") or [0.0, 0.0, 0.0, 0.0])[0]),
            ),
        )

        style_spans: list[dict[str, Any]] = []
        cursor = 0
        matched_characters = 0
        weighted_styles: dict[tuple[Any, ...], int] = {}

        for span in sorted_spans:
            span_text = str(span.get("text") or "").strip()
            if not span_text:
                continue
            start = self._find_span_start(block.text, span_text, cursor)
            if start is None:
                continue
            end = start + len(span_text)
            cursor = end
            matched_characters += len(span_text)

            style_entry = {
                "start": start,
                "end": end,
                "bbox": span.get("bbox") or [0.0, 0.0, 0.0, 0.0],
                "font_name": span.get("font_name"),
                "font_size_pt": span.get("font_size_pt"),
                "text_color_rgb": span.get("text_color_rgb"),
                "text_color_hex": span.get("text_color_hex"),
                "is_bold": bool(span.get("is_bold")),
                "is_italic": bool(span.get("is_italic")),
            }
            style_spans.append(style_entry)

            style_key = (
                style_entry["font_name"],
                style_entry["font_size_pt"],
                tuple(style_entry["text_color_rgb"] or []),
                style_entry["text_color_hex"],
                style_entry["is_bold"],
                style_entry["is_italic"],
            )
            weighted_styles[style_key] = weighted_styles.get(style_key, 0) + len(span_text)

        merged_spans = self._merge_adjacent_style_spans(style_spans)
        if not merged_spans:
            return {}

        dominant_key = max(weighted_styles.items(), key=lambda item: item[1])[0]
        confidence = round(matched_characters / max(len(block.text), 1), 3)

        return {
            "style_summary": {
                "source": "pymupdf",
                "font_name": dominant_key[0],
                "font_size_pt": dominant_key[1],
                "text_color_rgb": list(dominant_key[2]) if dominant_key[2] else None,
                "text_color_hex": dominant_key[3],
                "is_bold": dominant_key[4],
                "is_italic": dominant_key[5],
                "confidence": confidence,
                "span_count": len(merged_spans),
            },
            "style_spans": merged_spans,
        }

    def _merge_adjacent_style_spans(self, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not spans:
            return []
        merged: list[dict[str, Any]] = [dict(spans[0])]
        for span in spans[1:]:
            current = merged[-1]
            if (
                current["end"] == span["start"]
                and current.get("font_name") == span.get("font_name")
                and current.get("font_size_pt") == span.get("font_size_pt")
                and current.get("text_color_hex") == span.get("text_color_hex")
                and current.get("is_bold") == span.get("is_bold")
                and current.get("is_italic") == span.get("is_italic")
            ):
                current["end"] = span["end"]
                current["bbox"] = self._merge_bbox(current.get("bbox"), span.get("bbox"))
                continue
            merged.append(dict(span))
        return merged

    def _merge_bbox(self, left: Any, right: Any) -> list[float]:
        left_bbox = left if isinstance(left, list) and len(left) == 4 else [0.0, 0.0, 0.0, 0.0]
        right_bbox = right if isinstance(right, list) and len(right) == 4 else [0.0, 0.0, 0.0, 0.0]
        return [
            round(min(float(left_bbox[0]), float(right_bbox[0])), 2),
            round(min(float(left_bbox[1]), float(right_bbox[1])), 2),
            round(max(float(left_bbox[2]), float(right_bbox[2])), 2),
            round(max(float(left_bbox[3]), float(right_bbox[3])), 2),
        ]

    def _find_span_start(self, block_text: str, span_text: str, cursor: int) -> int | None:
        direct_match = block_text.find(span_text, cursor)
        if direct_match >= 0:
            return direct_match
        fallback_match = block_text.find(span_text)
        if fallback_match >= 0 and fallback_match >= cursor:
            return fallback_match
        return None

    def _span_matches_block(self, span_bbox: Any, block_bbox: list[float]) -> bool:
        normalized_span_bbox = self._normalize_bbox(span_bbox)
        normalized_block_bbox = self._normalize_bbox(block_bbox)
        if normalized_span_bbox is None or normalized_block_bbox is None:
            return False
        span_x0, span_y0, span_x1, span_y1 = normalized_span_bbox
        block_x0, block_y0, block_x1, block_y1 = normalized_block_bbox

        center_x = (span_x0 + span_x1) / 2
        center_y = (span_y0 + span_y1) / 2
        if block_x0 <= center_x <= block_x1 and block_y0 <= center_y <= block_y1:
            return True

        overlap_width = max(0.0, min(span_x1, block_x1) - max(span_x0, block_x0))
        overlap_height = max(0.0, min(span_y1, block_y1) - max(span_y0, block_y0))
        intersection_area = overlap_width * overlap_height
        span_area = max((span_x1 - span_x0) * (span_y1 - span_y0), 0.0)
        if span_area <= 0:
            return False
        return (intersection_area / span_area) >= 0.5

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
        return self._normalize_bbox(
            [
                round(float(getattr(bbox, "l", 0.0)), 2),
                round(float(getattr(bbox, "t", 0.0)), 2),
                round(float(getattr(bbox, "r", 0.0)), 2),
                round(float(getattr(bbox, "b", 0.0)), 2),
            ]
        ) or [0.0, 0.0, 0.0, 0.0]

    def _normalize_bbox(self, bbox: Any) -> list[float] | None:
        if not isinstance(bbox, list) or len(bbox) != 4:
            return None
        try:
            x0, y0, x1, y1 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            return None
        return [
            round(min(x0, x1), 2),
            round(min(y0, y1), 2),
            round(max(x0, x1), 2),
            round(max(y0, y1), 2),
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
