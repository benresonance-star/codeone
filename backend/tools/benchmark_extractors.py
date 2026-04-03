from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.document_strategy import DocumentStrategyRouter
from app.services.extractors import DoclingExtractor, PdfPlumberExtractor


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_pdf() -> Path:
    return repo_root() / "Spec" / "NCC 2022" / "PDF" / "PDF Sections" / "NCC 2022 - Vol 1 - Schedule 1 - Definitions.pdf"


def reports_dir() -> Path:
    return repo_root() / "backend" / "reports" / "benchmarks"


def default_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return reports_dir() / f"benchmark_{timestamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Docling against pdfplumber for NCC ingestion.")
    parser.add_argument("--pdf", type=Path, default=default_pdf(), help="Path to benchmark PDF.")
    parser.add_argument("--xml", type=Path, default=None, help="Optional paired XML for service-level comparison.")
    parser.add_argument("--document-class", default="definitions_glossary")
    parser.add_argument("--extraction-profile", default="definitions_glossary")
    parser.add_argument("--evaluation-profile", default="definitions_glossary")
    parser.add_argument("--output", type=Path, default=default_output_path(), help="JSON output file.")
    return parser.parse_args()


def run_once(
    extractor: DoclingExtractor | PdfPlumberExtractor,
    *,
    pdf_bytes: bytes,
    pdf_name: str,
    extractor_strategy: str,
    document_class: str,
    extraction_profile: str,
    evaluation_profile: str,
) -> dict:
    decision = DocumentStrategyRouter().route(
        pdf_name=pdf_name,
        xml_name="benchmark.xml",
        requested_document_class=document_class,
        requested_extraction_profile=extraction_profile,
        requested_evaluation_profile=evaluation_profile,
        requested_extractor_strategy=extractor_strategy,
    )
    started = perf_counter()
    extracted = extractor.extract(pdf_bytes, decision=decision)
    elapsed_ms = round((perf_counter() - started) * 1000, 2)

    return {
        "extractor_strategy": extractor_strategy,
        "runtime_mode": extracted.runtime_mode,
        "pages_processed": extracted.pages_processed,
        "blocks_extracted": len(extracted.blocks),
        "tables_extracted": len(extracted.tables),
        "heading_blocks": sum(1 for block in extracted.blocks if block.block_type == "heading"),
        "list_item_blocks": sum(1 for block in extracted.blocks if block.block_type == "list_item"),
        "block_type_counts": _block_type_counts(extracted.blocks),
        "avg_words_per_block": _avg_words_per_block(extracted.blocks),
        "table_shapes": [table.metadata.get("num_rows", len(table.rows)) for table in extracted.tables[:5]],
        "avg_table_cols": _avg_table_cols(extracted.tables),
        "avg_table_rows": _avg_table_rows(extracted.tables),
        "two_column_tables": sum(1 for table in extracted.tables if _table_col_count(table) == 2),
        "glossary_like_tables": sum(1 for table in extracted.tables if _looks_like_glossary_table(table.rows)),
        "tables_with_headers": sum(1 for table in extracted.tables if table.headers_present),
        "single_cell_table_ratio": _single_cell_table_ratio(extracted.tables),
        "repair_count": sum(1 for table in extracted.tables if table.metadata.get("repaired")),
        "normalization_strategy_counts": _normalization_strategy_counts(extracted.tables),
        "table_previews": [
            {
                "table_id": table.table_id,
                "shape": {
                    "rows": table.metadata.get("num_rows", len(table.rows)),
                    "cols": table.metadata.get("num_cols", max((len(row) for row in table.rows), default=0)),
                },
                "preview": table.rows[:3],
            }
            for table in extracted.tables[:3]
        ],
        "heading_samples": [block.text for block in extracted.blocks if block.block_type == "heading"][:5],
        "notes": extracted.notes,
        "elapsed_ms": elapsed_ms,
    }


def _block_type_counts(blocks: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.block_type] = counts.get(block.block_type, 0) + 1
    return counts


def _avg_words_per_block(blocks: list) -> float:
    if not blocks:
        return 0.0
    return round(sum(len(block.text.split()) for block in blocks) / len(blocks), 2)


def _quality_comparison(results: list[dict]) -> dict[str, object]:
    by_strategy = {result["extractor_strategy"]: result for result in results}
    docling = by_strategy.get("docling", {})
    pdfplumber = by_strategy.get("pdfplumber", {})
    return {
        "docling_heading_advantage": docling.get("heading_blocks", 0) - pdfplumber.get("heading_blocks", 0),
        "docling_list_item_advantage": docling.get("list_item_blocks", 0) - pdfplumber.get("list_item_blocks", 0),
        "table_count_delta": docling.get("tables_extracted", 0) - pdfplumber.get("tables_extracted", 0),
        "two_column_table_delta": docling.get("two_column_tables", 0) - pdfplumber.get("two_column_tables", 0),
        "single_cell_table_delta": round(
            float(docling.get("single_cell_table_ratio", 0.0)) - float(pdfplumber.get("single_cell_table_ratio", 0.0)),
            3,
        ),
        "glossary_repair_count": docling.get("repair_count", 0),
        "speed_delta_ms": round(docling.get("elapsed_ms", 0.0) - pdfplumber.get("elapsed_ms", 0.0), 2),
    }


def _table_col_count(table: Any) -> int:
    return int(table.metadata.get("num_cols", max((len(row) for row in table.rows), default=0)))


def _avg_table_cols(tables: list[Any]) -> float:
    if not tables:
        return 0.0
    return round(sum(_table_col_count(table) for table in tables) / len(tables), 2)


def _avg_table_rows(tables: list[Any]) -> float:
    if not tables:
        return 0.0
    return round(sum(int(table.metadata.get("num_rows", len(table.rows))) for table in tables) / len(tables), 2)


def _single_cell_table_ratio(tables: list[Any]) -> float:
    if not tables:
        return 0.0
    single_cell = sum(
        1
        for table in tables
        if int(table.metadata.get("num_rows", len(table.rows))) == 1 and _table_col_count(table) == 1
    )
    return round(single_cell / len(tables), 3)


def _normalization_strategy_counts(tables: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        strategy = str(table.metadata.get("normalization_strategy", "unknown"))
        counts[strategy] = counts.get(strategy, 0) + 1
    return counts


def _looks_like_glossary_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    sample = " ".join(cell for row in rows[:2] for cell in row if cell).lower()
    return any(token in sample for token in ("abbreviation", "definitions", "glossary", "symbols"))


def main() -> int:
    args = parse_args()
    pdf_bytes = args.pdf.read_bytes()
    extractors = {
        "docling": DoclingExtractor(),
        "pdfplumber": PdfPlumberExtractor(),
    }

    results = [
        run_once(
            extractor=extractors[strategy],
            pdf_bytes=pdf_bytes,
            pdf_name=args.pdf.name,
            extractor_strategy=strategy,
            document_class=args.document_class,
            extraction_profile=args.extraction_profile,
            evaluation_profile=args.evaluation_profile,
        )
        for strategy in ("docling", "pdfplumber")
    ]

    summary = {
        "pdf": str(args.pdf),
        "xml": str(args.xml) if args.xml else None,
        "note": "XML is optional here because extractor benchmarking focuses on PDF block extraction quality and speed.",
        "results": results,
        "comparison": _quality_comparison(results),
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
