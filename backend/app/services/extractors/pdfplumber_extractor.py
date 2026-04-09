from __future__ import annotations

from collections import defaultdict
from io import BytesIO
import re

import pdfplumber

from app.models.document_strategy import DocumentStrategyDecision, ExtractedPdf, ExtractedTable, StructuredBlock


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


class PdfPlumberExtractor:
    def extract(self, pdf_bytes: bytes, *, decision: DocumentStrategyDecision) -> ExtractedPdf:
        blocks: list[StructuredBlock] = []
        tables: list[ExtractedTable] = []
        page_count = 0
        total_words = 0

        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            for page_index, page in enumerate(pdf.pages, start=1):
                words = page.extract_words() or []
                total_words += len(words)
                blocks.extend(
                    self._page_blocks(
                        words,
                        page_index,
                        decision.extractor_strategy,
                        page_height=float(getattr(page, "height", 0.0) or 0.0),
                    )
                )

                for table_index, table in enumerate(page.extract_tables() or [], start=1):
                    rows = [[clean_text(cell) for cell in row] for row in table if row]
                    headers_present = bool(rows and any(rows[0]))
                    tables.append(
                        ExtractedTable(
                            table_id=f"tbl_{page_index}_{table_index}",
                            rows=rows,
                            headers_present=headers_present,
                            metadata={"page": page_index},
                        )
                    )

        return ExtractedPdf(
            pages_processed=page_count,
            total_words=total_words,
            blocks=blocks,
            tables=tables,
            strategy_name="pdfplumber",
        )

    def _page_blocks(self, words: list[dict], page_number: int, source_strategy: str, *, page_height: float) -> list[StructuredBlock]:
        grouped: dict[int, list[dict]] = defaultdict(list)
        for word in words:
            grouped[int(float(word["top"]) // 4)].append(word)

        blocks: list[StructuredBlock] = []
        for index, (_, line_words) in enumerate(sorted(grouped.items()), start=1):
            ordered = sorted(line_words, key=lambda item: float(item["x0"]))
            text = clean_text(" ".join(item["text"] for item in ordered))
            if not text:
                continue

            block_type, heading_level, section_hint = self._classify_block(text)
            bbox = [
                round(min(float(item["x0"]) for item in ordered), 2),
                round(min(float(item["top"]) for item in ordered), 2),
                round(max(float(item["x1"]) for item in ordered), 2),
                round(max(float(item["bottom"]) for item in ordered), 2),
            ]
            blocks.append(
                StructuredBlock(
                    block_id=f"frag_{page_number}_{index}",
                    page=page_number,
                    bbox=bbox,
                    block_type=block_type,
                    text=text,
                    section_hint=section_hint,
                    heading_level=heading_level,
                    source_strategy=source_strategy,
                    metadata={
                        "word_count": len(ordered),
                        "line_index": index,
                    },
                )
            )
        return self._tag_page_frame_blocks(blocks, page_height=page_height)

    def _classify_block(self, text: str) -> tuple[str, int | None, str | None]:
        lower = text.lower()
        if re.match(r"^(part|section|schedule)\s+[a-z0-9]+", lower):
            return "heading", 1, text.split(":")[0][:80]
        if re.match(r"^\d+[a-z]?\b", lower):
            return "clause", 2, text.split(" ")[0]
        if text.isupper() and len(text.split()) <= 12:
            return "heading", 2, text[:80]
        return "paragraph", None, None

    def _tag_page_frame_blocks(self, blocks: list[StructuredBlock], *, page_height: float) -> list[StructuredBlock]:
        if not blocks:
            return []
        grouped: dict[tuple[str, str], list[str]] = {}
        for block in blocks:
            page_region = self._candidate_page_band(block.bbox, page_height)
            if page_region == "body":
                continue
            normalized = self._normalize_page_frame_text(block.text)
            if not normalized:
                continue
            grouped.setdefault((page_region, normalized), []).append(block.block_id)

        repeated_keys = {
            key
            for key, block_ids in grouped.items()
            if len(block_ids) >= 2
        }
        tagged_blocks: list[StructuredBlock] = []
        for block in blocks:
            page_region = self._candidate_page_band(block.bbox, page_height)
            normalized = self._normalize_page_frame_text(block.text)
            looks_like_page_number = self._looks_like_page_number(block.text)
            is_page_frame = (
                page_region != "body"
                and not self._looks_like_structural_heading(block.text)
                and (looks_like_page_number or bool(normalized and (page_region, normalized) in repeated_keys))
            )
            metadata = dict(block.metadata)
            metadata["page_band"] = page_region
            metadata["page_height"] = round(page_height, 2) if page_height else None
            if is_page_frame:
                metadata["page_region"] = page_region
                metadata["page_frame_confidence"] = 0.98 if normalized and (page_region, normalized) in repeated_keys else 0.9
                metadata["page_frame_role"] = self._page_frame_role(block.text, page_region=page_region)
                metadata["page_frame_normalized_text"] = normalized
            tagged_blocks.append(StructuredBlock(**{**block.__dict__, "metadata": metadata}))
        return tagged_blocks

    def _candidate_page_band(self, bbox: list[float], page_height: float) -> str:
        if not bbox or len(bbox) != 4 or page_height <= 0:
            return "body"
        _, top, _, bottom = bbox
        if top <= page_height * 0.12:
            return "header"
        if bottom >= page_height * 0.9:
            return "footer"
        return "body"

    def _normalize_page_frame_text(self, text: str) -> str:
        normalized = re.sub(r"(?i)\bpage\s+\d+\b", "page", text or "")
        normalized = re.sub(r"\b\d+\b", "#", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized

    def _looks_like_page_number(self, text: str) -> bool:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        return bool(re.search(r"(?i)\bpage\s+\d+\b", cleaned) or re.fullmatch(r"\d{1,4}", cleaned))

    def _page_frame_role(self, text: str, *, page_region: str) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if self._looks_like_page_number(cleaned):
            return "page_number"
        if page_region == "header":
            return "running_header"
        return "running_footer"

    def _looks_like_structural_heading(self, text: str) -> bool:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        return bool(re.match(r"(?i)^(part|section|schedule)\s+[a-z0-9.-]+\b", cleaned))
