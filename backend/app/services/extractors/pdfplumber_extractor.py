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
                blocks.extend(self._page_blocks(words, page_index, decision.extractor_strategy))

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

    def _page_blocks(self, words: list[dict], page_number: int, source_strategy: str) -> list[StructuredBlock]:
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
                    metadata={"word_count": len(ordered), "line_index": index},
                )
            )
        return blocks

    def _classify_block(self, text: str) -> tuple[str, int | None, str | None]:
        lower = text.lower()
        if re.match(r"^(part|section|schedule)\s+[a-z0-9]+", lower):
            return "heading", 1, text.split(":")[0][:80]
        if re.match(r"^\d+[a-z]?\b", lower):
            return "clause", 2, text.split(" ")[0]
        if text.isupper() and len(text.split()) <= 12:
            return "heading", 2, text[:80]
        return "paragraph", None, None
