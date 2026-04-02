from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.document_strategy import DocumentStrategyRouter
from app.services.ingestion import IngestionService, PdfFragment, XmlNode
from app.services.extractors.docling_stub import DoclingExtractor


class DocumentStrategyRouterTests(unittest.TestCase):
    def test_router_classifies_interpreting_documents(self) -> None:
        decision = DocumentStrategyRouter().route(
            pdf_name="NCC 2022 - Vol 1 - Part A1 - Interpreting the NCC.pdf",
            xml_name="ncc-volume-1-part-a1.xml",
        )

        self.assertEqual(decision.document_class, "governance_interpretation")
        self.assertEqual(decision.extractor_strategy, "docling")
        self.assertEqual(decision.extraction_profile.profile_id, "governance_interpretation")

    def test_router_allows_explicit_profile_override(self) -> None:
        decision = DocumentStrategyRouter().route(
            pdf_name="schedule-1-definitions.pdf",
            xml_name="schedule-1-definitions.xml",
            requested_document_class="definitions_glossary",
            requested_extraction_profile="baseline_clause_parity",
            requested_evaluation_profile="baseline_clause_parity",
            requested_extractor_strategy="pdfplumber",
        )

        self.assertEqual(decision.document_class, "definitions_glossary")
        self.assertEqual(decision.extractor_strategy, "pdfplumber")
        self.assertEqual(decision.extraction_profile.profile_id, "baseline_clause_parity")
        self.assertEqual(decision.evaluation_profile.profile_id, "baseline_clause_parity")


class ParityScaffoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IngestionService()
        self.strategy = DocumentStrategyRouter().route(
            pdf_name="schedule-1-definitions.pdf",
            xml_name="schedule-1-definitions.xml",
        )

    def test_grouped_parity_scaffold_tracks_unmapped_definition_groups(self) -> None:
        fragments = [
            PdfFragment(fragment_id="frag_1_1", page=1, text="Accessible means suitable for use.", bbox=[0.0, 0.0, 1.0, 1.0]),
        ]
        alignments = [
            {
                "fragment_id": "frag_1_1",
                "node_id": "def_accessible",
                "confidence": 0.97,
                "matched": True,
                "page": 1,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        ]
        xml_nodes = [
            XmlNode(
                node_id="def_accessible",
                clause_id="def_accessible",
                text="Accessible means suitable for use by a person.",
                path="/definition[@id='def_accessible']",
            ),
            XmlNode(
                node_id="def_building",
                clause_id="def_building",
                text="Building means a structure with a roof.",
                path="/definition[@id='def_building']",
            ),
        ]

        scaffold = self.service._build_parity_scaffold(self.strategy, fragments, alignments, xml_nodes)

        self.assertEqual(scaffold["summary"]["group_count"], 2)
        self.assertEqual(scaffold["summary"]["matched_groups"], 1)
        self.assertEqual(scaffold["summary"]["review_required_groups"], 1)
        self.assertEqual(scaffold["summary"]["unmapped_targets"], 1)

    def test_grouped_parity_requires_review_when_targets_remain_unmapped(self) -> None:
        scaffold = {
            "summary": {
                "group_count": 2,
                "matched_groups": 1,
                "review_required_groups": 1,
                "unmapped_targets": 1,
            }
        }

        self.assertTrue(
            self.service._should_require_review(
                self.strategy.review_policy,
                self.strategy,
                unresolved=[],
                low_confidence=[],
                parity_scaffold=scaffold,
                alignment_avg=0.97,
            )
        )


class DoclingExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = DoclingExtractor()

    def test_label_mapping_matches_structured_block_expectations(self) -> None:
        self.assertEqual(self.extractor._map_block_type("section_header"), "heading")
        self.assertEqual(self.extractor._map_block_type("list_item"), "list_item")
        self.assertEqual(self.extractor._map_block_type("text"), "paragraph")

    def test_bbox_extraction_uses_docling_provenance(self) -> None:
        provenance = SimpleNamespace(
            page_no=2,
            bbox=SimpleNamespace(l=10.126, t=20.25, r=30.375, b=40.499),
        )

        bbox = self.extractor._bbox_from_provenance(provenance)

        self.assertEqual(bbox, [10.13, 20.25, 30.38, 40.5])

    def test_table_rows_use_dataframe_when_available(self) -> None:
        class FakeDataFrame:
            def __init__(self) -> None:
                self.values = SimpleNamespace(tolist=lambda: [["Header", "Value"], ["A", "1"], ["", ""]])

            def fillna(self, value: str) -> "FakeDataFrame":
                return self

        class FakeItem:
            text = ""

            def export_to_dataframe(self, doc=None) -> FakeDataFrame:  # noqa: ANN001
                return FakeDataFrame()

        rows = self.extractor._table_rows(FakeItem(), document=object())

        self.assertEqual(rows, [["Header", "Value"], ["A", "1"]])
        self.assertTrue(self.extractor._headers_present(rows))


if __name__ == "__main__":
    unittest.main()
