from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.models.document_strategy import ExtractedPdf, ExtractedTable, StructuredBlock
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
        self.assertEqual(decision.extractor_options["docling_mode"], "text")

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

    def test_router_enables_docling_tables_for_energy_efficiency_parts(self) -> None:
        decision = DocumentStrategyRouter().route(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="ncc-volume-1-section-j.xml",
        )

        self.assertEqual(decision.document_class, "clause_parity")
        self.assertEqual(decision.extractor_strategy, "docling")
        self.assertEqual(decision.extractor_options["docling_mode"], "tables")


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

    def test_validate_pdf_omits_unmapped_table_link_fields(self) -> None:
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=3,
            blocks=[
                StructuredBlock(
                    block_id="docling_1_1",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="Sample clause text",
                    source_strategy="docling",
                )
            ],
            tables=[
                ExtractedTable(
                    table_id="docling_tbl_1",
                    rows=[["A", "B"]],
                    headers_present=True,
                    related_block_id=None,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    metadata={"num_rows": 1, "num_cols": 2},
                )
            ],
            strategy_name="docling",
            runtime_mode="native_tables_text",
        )
        xml_context = {
            "result": {
                "gate_decision": {"can_progress_to_alignment_layer": False},
                "document": {"doc_id": "benchmark_xml"},
            },
            "xml_nodes": [],
        }
        self.service._extract_pdf = lambda pdf_bytes, strategy: extracted  # type: ignore[method-assign]

        result = self.service._validate_pdf(b"pdf", "benchmark.pdf", xml_context, self.strategy)

        table_entry = result["result"]["table_validation"][0]
        self.assertNotIn("node_id", table_entry)
        self.assertNotIn("related_xml_node", table_entry)

    def test_document_family_id_is_bounded_for_long_file_names(self) -> None:
        family_id = self.service._build_document_family_id(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="table-J3D11a-maximum-conductance-to-solar-heat-gain-ratio.xml",
        )

        self.assertLessEqual(len(family_id), 80)
        self.assertTrue(family_id.startswith("ncc_2022_vol_1_parts_j2_and_j3_energy_efficiency"))

    def test_document_family_id_bounding_is_deterministic(self) -> None:
        pdf_name = "NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf"
        xml_name = "table-J3D11a-maximum-conductance-to-solar-heat-gain-ratio.xml"

        first = self.service._build_document_family_id(pdf_name=pdf_name, xml_name=xml_name)
        second = self.service._build_document_family_id(pdf_name=pdf_name, xml_name=xml_name)

        self.assertEqual(first, second)


class DoclingExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = DoclingExtractor()

    def _decision(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "document_class": "clause_parity",
            "extractor_options": {},
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

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

    def test_rows_from_table_cells_reconstructs_grid(self) -> None:
        data = SimpleNamespace(
            num_rows=3,
            num_cols=2,
            table_cells=[
                SimpleNamespace(
                    text="Abbreviation",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                    column_header=True,
                    row_header=False,
                ),
                SimpleNamespace(
                    text="Definitions",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                    column_header=True,
                    row_header=False,
                ),
                SimpleNamespace(
                    text="ABCB",
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                    column_header=False,
                    row_header=False,
                ),
                SimpleNamespace(
                    text="Australian Building Codes Board",
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                    column_header=False,
                    row_header=False,
                ),
                SimpleNamespace(
                    text="AC",
                    start_row_offset_idx=2,
                    end_row_offset_idx=3,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                    column_header=False,
                    row_header=False,
                ),
                SimpleNamespace(
                    text="Alternating Current",
                    start_row_offset_idx=2,
                    end_row_offset_idx=3,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                    column_header=False,
                    row_header=False,
                ),
            ],
        )

        rows, meta = self.extractor._rows_from_table_cells(data)

        self.assertEqual(
            rows,
            [
                ["Abbreviation", "Definitions"],
                ["ABCB", "Australian Building Codes Board"],
                ["AC", "Alternating Current"],
            ],
        )
        self.assertEqual(meta["header_row_count"], 1)
        self.assertEqual(meta["source_cell_count"], 6)

    def test_normalize_header_rows_merges_multirow_header(self) -> None:
        rows, meta = self.extractor._normalize_header_rows(
            [
                ["Schedule 1", "Definitions"],
                ["Abbreviations", "Glossary"],
                ["ABCB", "Australian Building Codes Board"],
            ],
            {"header_row_count": 2},
        )

        self.assertEqual(meta["header_row_count"], 1)
        self.assertEqual(rows[0], ["Schedule 1 Abbreviations", "Definitions Glossary"])
        self.assertEqual(rows[1], ["ABCB", "Australian Building Codes Board"])

    def test_glossary_repair_merges_continuation_rows(self) -> None:
        rows, meta = self.extractor._repair_glossary_rows(
            [
                ["Abbreviation", "Definitions"],
                ["ABCB", "Australian Building Codes Board"],
                ["", "and related guidance"],
            ],
            {"header_row_count": 1, "normalization_strategy": "table_cells_grid"},
        )

        self.assertTrue(meta["repaired"])
        self.assertEqual(rows[1], ["ABCB", "Australian Building Codes Board and related guidance"])

    def test_glossary_single_cell_repair_splits_abbreviation_table(self) -> None:
        rows, meta = self.extractor._repair_glossary_rows(
            [[
                "Abbreviation Definitions ABCB Australian Building Codes Board AC Alternating Current"
            ]],
            {"header_row_count": 0, "normalization_strategy": "dataframe_or_text_fallback"},
        )

        self.assertTrue(meta["repaired"])
        self.assertEqual(rows[0], ["Abbreviation", "Definitions"])
        self.assertEqual(rows[1], ["ABCB", "Australian Building Codes Board"])
        self.assertEqual(rows[2], ["AC", "Alternating Current"])

    def test_table_rows_falls_back_to_text_when_no_dataframe_or_cells(self) -> None:
        class PlainTextItem:
            text = "A\nB"

        rows = self.extractor._table_rows(PlainTextItem(), document=object())

        self.assertEqual(rows, [["A"], ["B"]])

    def test_empty_wrapper_table_is_detected(self) -> None:
        data = SimpleNamespace(
            num_rows=1,
            num_cols=1,
            table_cells=[
                SimpleNamespace(
                    text="",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                )
            ],
        )

        self.assertTrue(self.extractor._is_empty_wrapper_table(data, []))

    def test_empty_wrapper_table_ignores_fallback_rows(self) -> None:
        data = SimpleNamespace(
            num_rows=1,
            num_cols=1,
            table_cells=[
                SimpleNamespace(
                    text="",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                )
            ],
        )

        self.assertTrue(
            self.extractor._is_empty_wrapper_table(
                data,
                [["## Schedule 1 Definitions Abbreviations Symbols Glossary"]],
            )
        )

    def test_contextual_glossary_rows_rebuild_wrapper_table(self) -> None:
        strategy = DocumentStrategyRouter().route(
            pdf_name="schedule-1-definitions.pdf",
            xml_name="schedule-1-definitions.xml",
        )
        items = [
            (SimpleNamespace(label="table", text=""), 1),
            (SimpleNamespace(label="section_header", text="Abbreviations"), 1),
            (SimpleNamespace(label="text", text="Abbreviation"), 3),
            (SimpleNamespace(label="text", text="Definitions"), 3),
            (SimpleNamespace(label="text", text="ABCB"), 3),
            (SimpleNamespace(label="text", text="Australian Building Codes Board"), 3),
            (SimpleNamespace(label="text", text="AC"), 3),
            (SimpleNamespace(label="text", text="Alternating Current"), 3),
            (SimpleNamespace(label="table", text=""), 1),
        ]

        rows = self.extractor._contextual_table_rows(items, 0, strategy)

        self.assertEqual(
            rows,
            [
                ["Abbreviation", "Definitions"],
                ["ABCB", "Australian Building Codes Board"],
                ["AC", "Alternating Current"],
            ],
        )

    def test_contextual_glossary_rows_skip_schedule_title_wrapper(self) -> None:
        strategy = DocumentStrategyRouter().route(
            pdf_name="schedule-1-definitions.pdf",
            xml_name="schedule-1-definitions.xml",
        )
        items = [
            (SimpleNamespace(label="table", text=""), 1),
            (SimpleNamespace(label="section_header", text="Schedule 1"), 1),
            (SimpleNamespace(label="text", text="Definitions"), 3),
            (SimpleNamespace(label="text", text="Abbreviations Symbols"), 3),
            (SimpleNamespace(label="text", text="Glossary"), 3),
            (SimpleNamespace(label="section_header", text="Abbreviations"), 1),
            (SimpleNamespace(label="table", text=""), 1),
        ]

        rows = self.extractor._contextual_table_rows(items, 0, strategy)

        self.assertEqual(rows, [])

    def test_collect_tables_skips_empty_tables(self) -> None:
        strategy = DocumentStrategyRouter().route(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="benchmark.xml",
            requested_document_class="clause_parity",
            requested_extraction_profile="baseline_clause_parity",
            requested_evaluation_profile="baseline_clause_parity",
            requested_extractor_strategy="docling",
        )
        empty_table = SimpleNamespace(
            label="table",
            text="",
            data=SimpleNamespace(num_rows=0, num_cols=0, table_cells=[]),
            prov=[],
        )
        document = SimpleNamespace(iterate_items=lambda: [(empty_table, 1)])
        result = SimpleNamespace(document=document)

        tables = self.extractor._collect_tables(result, strategy)

        self.assertEqual(tables, [])

    def test_runtime_flags_honor_strategy_requested_tables_mode(self) -> None:
        decision = self._decision(extractor_options={"docling_mode": "tables"})

        flags = self.extractor._runtime_flags(decision)

        self.assertEqual(flags, (False, True, True))

    def test_runtime_flags_default_to_text_mode_when_requested(self) -> None:
        decision = self._decision(extractor_options={"docling_mode": "text"})

        flags = self.extractor._runtime_flags(decision)

        self.assertEqual(flags, (False, False, True))


if __name__ == "__main__":
    unittest.main()
