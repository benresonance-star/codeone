from __future__ import annotations

import unittest

from app.models.document_strategy import ExtractedPdf, StructuredBlock
from app.services.ingestion import IngestionService


class PdfOnlyCandidateWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IngestionService()

    def test_build_pdf_candidate_units_prefers_clauses_and_falls_back_to_uncovered_blocks(self) -> None:
        structured_blocks = [
            {
                "block_id": "clause_1",
                "page": 1,
                "bbox": [0.0, 0.0, 1.0, 1.0],
                "block_type": "paragraph",
                "text": "A1 This is the primary clause.",
            },
            {
                "block_id": "tail_1",
                "page": 1,
                "bbox": [0.0, 1.0, 1.0, 2.0],
                "block_type": "paragraph",
                "text": "Supplementary uncovered paragraph.",
            },
        ]
        assembled_clauses = [
            {
                "anchor": {"block_id": "clause_1", "block_type": "paragraph"},
                "source_block_ids": ["clause_1"],
                "rendered_blocks": [{"text": "A1 This is the primary clause."}],
                "title_or_lead": "A1 This is the primary clause.",
                "pages": [1],
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        ]

        units = self.service._build_pdf_candidate_units(
            structured_blocks=structured_blocks,
            assembled_clauses=assembled_clauses,
        )

        unit_ids = {unit["unit_id"] for unit in units}
        self.assertIn("pdf_clause:clause_1", unit_ids)
        self.assertIn("pdf_block:tail_1", unit_ids)

    def test_process_pdf_only_returns_pdf_workspace_without_xml(self) -> None:
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=10,
            blocks=[
                StructuredBlock(
                    block_id="clause_1",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="A1 A building must provide safe egress.",
                    source_strategy="docling",
                ),
                StructuredBlock(
                    block_id="clause_2",
                    page=1,
                    bbox=[0.0, 1.0, 1.0, 2.0],
                    block_type="list_item",
                    text="(a) exits must remain unobstructed.",
                    source_strategy="docling",
                ),
            ],
            tables=[],
            strategy_name="docling",
            runtime_mode="native_text",
        )
        self.service._extract_pdf = lambda pdf_bytes, strategy: extracted  # type: ignore[method-assign]

        payload = self.service.process_pdf_only(
            pdf_bytes=b"%PDF-1.4\n%",
            pdf_name="pdf-only-review.pdf",
        )

        self.assertEqual(payload["review_workspace"]["mode"], "pdf_only")
        self.assertEqual(payload["results"]["xml_validation"]["overall_status"], "NOT_PROVIDED")
        self.assertGreaterEqual(payload["review_workspace"]["candidate_total"], 1)
        self.assertTrue(all(candidate.get("candidate_origin") == "pdf" for candidate in payload["lineage"]["candidate_objects"]))
        self.assertTrue(all(candidate.get("xml_node_id") is None for candidate in payload["lineage"]["candidate_objects"]))

    def test_process_pdf_only_keeps_xml_as_secondary_reference(self) -> None:
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=7,
            blocks=[
                StructuredBlock(
                    block_id="clause_1",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="A1 A building must provide safe egress.",
                    source_strategy="docling",
                )
            ],
            tables=[],
            strategy_name="docling",
            runtime_mode="native_text",
        )
        self.service._extract_pdf = lambda pdf_bytes, strategy: extracted  # type: ignore[method-assign]
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_a" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="A">
  <num>A</num>
  <title>Governing requirements</title>
  <clause id="A1G1"><p>A building must provide safe egress.</p></clause>
</part>
"""

        payload = self.service.process_pdf_only(
            pdf_bytes=b"%PDF-1.4\n%",
            pdf_name="pdf-with-reference.pdf",
            xml_bytes=xml_bytes,
            xml_name="part-a.xml",
        )

        self.assertEqual(payload["review_workspace"]["mode"], "pdf_only")
        self.assertNotEqual(payload["results"]["xml_validation"]["overall_status"], "NOT_PROVIDED")
        self.assertGreaterEqual(len(payload["review_workspace"]["xml_nodes"]), 1)
        self.assertGreaterEqual(len(payload["lineage"]["reference_xml_semantic_units"]), 1)
        self.assertTrue(all(candidate.get("candidate_origin") == "pdf" for candidate in payload["lineage"]["candidate_objects"]))

    def test_process_pdf_only_uses_clause_header_for_candidate_title_and_keeps_marginalia_out(self) -> None:
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=28,
            blocks=[
                StructuredBlock(
                    block_id="docling_1_10",
                    page=1,
                    bbox=[50.0, 40.0, 320.0, 58.0],
                    block_type="heading",
                    text="Part A1 Interpreting the NCC",
                    source_strategy="docling",
                ),
                StructuredBlock(
                    block_id="docling_1_11",
                    page=1,
                    bbox=[50.0, 110.0, 90.0, 124.0],
                    block_type="paragraph",
                    text="A1G2",
                    source_strategy="docling",
                ),
                StructuredBlock(
                    block_id="docling_1_12",
                    page=1,
                    bbox=[120.0, 110.0, 340.0, 124.0],
                    block_type="paragraph",
                    text="Scope of NCC Volume Two",
                    source_strategy="docling",
                    metadata={"style_summary": {"is_bold": True}},
                ),
                StructuredBlock(
                    block_id="docling_1_13",
                    page=1,
                    bbox=[420.0, 110.0, 520.0, 124.0],
                    block_type="paragraph",
                    text="[New for 2022]",
                    source_strategy="docling",
                ),
                StructuredBlock(
                    block_id="docling_1_14",
                    page=1,
                    bbox=[50.0, 145.0, 520.0, 162.0],
                    block_type="paragraph",
                    text="NCC Volume Two contains the requirements for-",
                    source_strategy="docling",
                ),
            ],
            tables=[],
            strategy_name="docling",
            runtime_mode="native_text",
        )
        self.service._extract_pdf = lambda pdf_bytes, strategy: extracted  # type: ignore[method-assign]

        payload = self.service.process_pdf_only(
            pdf_bytes=b"%PDF-1.4\n%",
            pdf_name="part-a1.pdf",
        )

        clause_candidate = next(
            candidate
            for candidate in payload["lineage"]["candidate_objects"]
            if candidate.get("candidate_id") == "candidate:pdf_clause:docling_1_11"
        )

        self.assertEqual(clause_candidate["title"], "A1G2 Scope of NCC Volume Two")
        self.assertEqual(clause_candidate["display_projection"]["heading_text"], "Scope of NCC Volume Two")
        self.assertEqual(clause_candidate["display_projection"]["clause_code"], "A1G2")
        self.assertEqual(clause_candidate["display_projection"]["parent_heading_label"], "Part A1")
        self.assertEqual(clause_candidate["display_projection"]["parent_heading_text"], "Interpreting the NCC")
        self.assertEqual(clause_candidate["display_projection"]["parent_heading_title"], "Part A1 Interpreting the NCC")
        self.assertEqual(
            clause_candidate["display_projection"]["structural_path"],
            [
                {
                    "kind": "part",
                    "label": "Part A1",
                    "text": "Interpreting the NCC",
                    "title": "Part A1 Interpreting the NCC",
                    "block_id": "docling_1_10",
                    "candidate_id": "candidate:pdf_clause:docling_1_10",
                }
            ],
        )
        self.assertEqual(
            [block["text"] for block in clause_candidate["display_projection"]["marginalia_blocks"]],
            ["[New for 2022]"],
        )
        self.assertFalse(
            any(candidate.get("title") == "[New for 2022]" for candidate in payload["lineage"]["candidate_objects"])
        )

    def test_process_pdf_only_sets_start_page_and_page_span_for_multi_page_clause(self) -> None:
        extracted = ExtractedPdf(
            pages_processed=2,
            total_words=18,
            blocks=[
                StructuredBlock(
                    block_id="docling_3_10",
                    page=3,
                    bbox=[50.0, 700.0, 540.0, 720.0],
                    block_type="paragraph",
                    text="(1) Compliance is achieved when the following applies-",
                    source_strategy="docling",
                ),
                StructuredBlock(
                    block_id="docling_4_11",
                    page=4,
                    bbox=[50.0, 50.0, 540.0, 72.0],
                    block_type="paragraph",
                    text="continued on the next page with the same requirement wording.",
                    source_strategy="docling",
                ),
                StructuredBlock(
                    block_id="docling_4_12",
                    page=4,
                    bbox=[50.0, 100.0, 540.0, 120.0],
                    block_type="paragraph",
                    text="(2) A new numbered item begins here.",
                    source_strategy="docling",
                ),
            ],
            tables=[],
            strategy_name="docling",
            runtime_mode="native_text",
        )
        self.service._extract_pdf = lambda pdf_bytes, strategy: extracted  # type: ignore[method-assign]

        payload = self.service.process_pdf_only(
            pdf_bytes=b"%PDF-1.4\n%",
            pdf_name="multi-page.pdf",
        )

        clause_candidate = next(
            candidate
            for candidate in payload["lineage"]["candidate_objects"]
            if candidate.get("candidate_id") == "candidate:pdf_clause:docling_3_10"
        )

        self.assertEqual(clause_candidate["page"], 3)
        self.assertEqual(clause_candidate["assembled_clause"]["start_page"], 3)
        self.assertEqual(clause_candidate["assembled_clause"]["end_page"], 4)
        self.assertEqual(clause_candidate["display_projection"]["page_context"]["start_page"], 3)
        self.assertEqual(clause_candidate["display_projection"]["page_context"]["end_page"], 4)
        self.assertEqual(clause_candidate["display_projection"]["page_context"]["pages"], [3, 4])


if __name__ == "__main__":
    unittest.main()
