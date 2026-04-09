from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_router_prefers_schema_family_for_glossary_entries(self) -> None:
        decision = DocumentStrategyRouter().route(
            pdf_name="unknown.pdf",
            xml_name="entry.xml",
            xml_schema_family_id="abcb_glossentry",
        )

        self.assertEqual(decision.document_class, "definitions_glossary")
        self.assertIn("xml_schema_family:abcb_glossentry", decision.notes)

    def test_runtime_strategy_falls_back_to_pdfplumber_when_docling_is_unavailable(self) -> None:
        service = IngestionService()
        strategy = DocumentStrategyRouter().route(
            pdf_name="schedule-1-definitions.pdf",
            xml_name="schedule-1-definitions.xml",
        )

        with patch.object(service.extractors["docling"], "is_available", return_value=False):
            resolved = service._resolve_runtime_strategy(strategy)

        self.assertEqual(strategy.extractor_strategy, "docling")
        self.assertEqual(resolved.extractor_strategy, "pdfplumber")
        self.assertEqual(resolved.extractor_options, {})
        self.assertIn("docling_unavailable:fallback_to_pdfplumber", resolved.notes)
        self.assertIn("runtime_extractor:pdfplumber", resolved.notes)


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

    def test_review_workspace_focuses_narrow_xml_artifacts(self) -> None:
        xml_nodes = [
            XmlNode(node_id="node_a", clause_id="node_a", text="Maximum conductance ratio climate zone 1", path="/table[@id='node_a']"),
            XmlNode(node_id="node_b", clause_id="node_b", text="Maximum conductance ratio climate zone 2", path="/table[@id='node_b']"),
        ]
        fragments = [
            PdfFragment(fragment_id=f"frag_{index}", page=1, text=f"Fragment {index}", bbox=[0.0, 0.0, 1.0, 1.0])
            for index in range(1, 121)
        ]
        alignments = []
        for index, fragment in enumerate(fragments, start=1):
            node_id = "node_a" if index % 2 else "node_b"
            alignments.append(
                {
                    "fragment_id": fragment.fragment_id,
                    "node_id": node_id,
                    "confidence": round(0.99 - (index * 0.001), 3),
                    "matched": True,
                    "page": fragment.page,
                    "bbox": fragment.bbox,
                }
            )

        workspace = self.service._build_review_workspace(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="table-J3D11a-maximum-conductance-to-solar-heat-gain-ratio.xml",
            xml_nodes=xml_nodes,
            fragments=fragments,
            alignments=alignments,
            canonical_snippets=[],
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )

        self.assertEqual(workspace["mode"], "focused")
        self.assertEqual(workspace["alignment_total"], 120)
        self.assertEqual(workspace["alignment_displayed"], 6)
        self.assertEqual(workspace["candidate_total"], 2)
        self.assertEqual(workspace["candidate_surfaced"], 2)
        self.assertEqual(len(workspace["pdf_fragments"]), 6)
        self.assertEqual(len(workspace["xml_nodes"]), 2)

    def test_review_workspace_emits_stable_review_units(self) -> None:
        xml_nodes = [
            XmlNode(
                node_id="node_a",
                clause_id="node_a",
                text="Accessible means suitable for use by a person.",
                path="/definition[@id='node_a']",
            )
        ]
        fragments = [
            PdfFragment(
                fragment_id="frag_1",
                page=1,
                text="Accessible means suitable for use.",
                bbox=[0.0, 0.0, 1.0, 1.0],
            )
        ]
        alignments = [
            {
                "fragment_id": "frag_1",
                "node_id": "node_a",
                "confidence": 0.91,
                "matched": True,
                "page": 1,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        ]

        workspace = self.service._build_review_workspace(
            pdf_name="schedule-1-definitions.pdf",
            xml_name="schedule-1-definitions.xml",
            xml_nodes=xml_nodes,
            fragments=fragments,
            alignments=alignments,
            canonical_snippets=[],
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )

        self.assertEqual(len(workspace["review_units"]), 1)
        self.assertEqual(workspace["candidate_total"], 1)
        self.assertEqual(workspace["candidate_surfaced"], 1)
        self.assertEqual(workspace["candidate_needs_review"], 1)
        review_unit = workspace["review_units"][0]
        self.assertEqual(review_unit["candidate_id"], "candidate:unit:node_a")
        self.assertEqual(review_unit["candidate_type"], "definition")
        self.assertEqual(review_unit["xml_structural_class"], "definition")
        self.assertEqual(review_unit["pdf_evidence_class"], "unknown")
        self.assertEqual(review_unit["candidate_semantic_class"], "definition")
        self.assertEqual(review_unit["base_status"], "mismatch")
        self.assertTrue(review_unit["needs_human_review"])
        self.assertEqual(review_unit["review_issue_class"], "xml_mismatch")
        self.assertEqual(review_unit["review_source_emphasis"], "xml")
        self.assertEqual(review_unit["fragment_id"], "frag_1")
        self.assertEqual(review_unit["node_id"], "node_a")
        self.assertIn("XML-only terms", review_unit["issues"][0])

    def test_review_workspace_classifies_table_reference_rows_as_table(self) -> None:
        xml_nodes = [
            XmlNode(
                node_id="table_ref_1__row_1",
                clause_id="table_ref_1__row_1",
                text="J3D11a Maximum conductance ratio Climate zone: 2 Maximum ratio: 16.95",
                path="/table-reference[@id='table_ref_1']/tbody/row[1]",
            )
        ]
        fragments = [
            PdfFragment(
                fragment_id="docling_tbl_30__row_1",
                page=12,
                text="Climate zone: 2 Maximum ratio: 16.95",
                bbox=[0.0, 0.0, 1.0, 1.0],
            )
        ]
        alignments = [
            {
                "fragment_id": "docling_tbl_30__row_1",
                "node_id": "table_ref_1__row_1",
                "confidence": 0.93,
                "matched": True,
                "page": 12,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        ]

        workspace = self.service._build_review_workspace(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="table-J3D11a-maximum-conductance-to-solar-heat-gain-ratio.xml",
            xml_nodes=xml_nodes,
            fragments=fragments,
            alignments=alignments,
            canonical_snippets=[],
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )

        self.assertEqual(workspace["review_units"][0]["candidate_type"], "table")
        self.assertEqual(workspace["review_units"][0]["pdf_evidence_class"], "table_row")

    def test_review_workspace_classifies_title_nodes_and_ignores_structural_title_tokens(self) -> None:
        xml_nodes = [
            XmlNode(
                node_id="title_j3",
                clause_id="title_j3",
                text="Elemental provisions",
                path="/part[@id='part_j3']/title[1]",
            )
        ]
        fragments = [
            PdfFragment(
                fragment_id="docling_3_1",
                page=3,
                text="Part J3 Elemental provisions",
                bbox=[0.0, 0.0, 1.0, 1.0],
            )
        ]
        alignments = [
            {
                "fragment_id": "docling_3_1",
                "node_id": "title_j3",
                "confidence": 0.96,
                "matched": True,
                "page": 3,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        ]
        structured_blocks = [
            {
                "block_id": "docling_3_1",
                "page": 3,
                "bbox": [0.0, 0.0, 1.0, 1.0],
                "block_type": "heading",
                "text": "Part J3 Elemental provisions",
                "source_strategy": "docling",
            }
        ]

        workspace = self.service._build_review_workspace(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="J3-elemental-provisions.xml",
            xml_nodes=xml_nodes,
            fragments=fragments,
            structured_blocks=structured_blocks,
            alignments=alignments,
            canonical_snippets=[],
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )

        review_unit = workspace["review_units"][0]
        self.assertEqual(review_unit["candidate_type"], "title")
        self.assertEqual(review_unit["xml_structural_class"], "title")
        self.assertEqual(review_unit["pdf_evidence_class"], "heading")
        self.assertEqual(review_unit["candidate_semantic_class"], "title")
        self.assertEqual(review_unit["raw_pdf_only_terms"], ["j3", "part"])
        self.assertEqual(review_unit["pdf_only_terms"], [])
        self.assertEqual(review_unit["ignored_structural_terms"], ["j3", "part"])
        self.assertEqual(review_unit["base_status"], "match")
        self.assertFalse(review_unit["needs_human_review"])
        self.assertEqual(review_unit["review_issue_class"], "clean_match")
        self.assertEqual(review_unit["review_source_emphasis"], "balanced")

    def test_validate_xml_emits_semantic_units_for_titles_and_rows(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<table-reference id="tbl_ref_1">
  <num>J3D11a</num>
  <title>Maximum conductance to solar heat gain ratio</title>
  <table id="tbl_data_1">
    <tgroup cols="2">
      <tbody>
        <row>
          <entry>2</entry>
          <entry>16.95</entry>
        </row>
      </tbody>
    </tgroup>
  </table>
</table-reference>
"""

        result = self.service._validate_xml(xml_bytes, "table-J3D11a-maximum-conductance-to-solar-heat-gain-ratio.xml")

        semantic_units = result["semantic_units"]
        unit_ids = {unit["unit_id"] for unit in semantic_units}
        semantic_classes = {unit["semantic_class"] for unit in semantic_units}
        self.assertIn("unit:tbl_ref_1", unit_ids)
        self.assertIn("unit:tbl_ref_1__row_1", unit_ids)
        self.assertIn("table", semantic_classes)
        self.assertIn("title", semantic_classes)

    def test_validate_xml_recognizes_glossentry_family_and_avoids_child_duplicate_inventory(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<abcb-glossentry id="entry_1" outputclass="abcb-glossentry" edition="2022" volume="1" amendment="base" part="Schedule 1">
  <glossterm id="term_1">Accessible</glossterm>
  <glossdef outputclass="glossdef">
    <p>Having features to enable use by people with a disability.</p>
  </glossdef>
</abcb-glossentry>
"""

        result = self.service._validate_xml(xml_bytes, "glossary-accessible.xml")

        self.assertEqual(result["metrics"]["schema_family_id"], "abcb_glossentry")
        self.assertTrue(result["metrics"]["schema_approved"])
        self.assertFalse(result["metrics"]["unknown_schema_family"])
        self.assertEqual(result["result"]["document"]["schema_family_id"], "abcb_glossentry")
        self.assertEqual({unit["node_id"] for unit in result["semantic_units"]}, {"entry_1"})
        unit = result["semantic_units"][0]
        self.assertEqual(unit["semantic_class"], "definition")
        self.assertEqual(unit["glossary_term"], "Accessible")
        self.assertEqual(
            unit["glossary_definition"],
            "Having features to enable use by people with a disability.",
        )

        packets = self.service._build_pdf_evidence_packets(
            semantic_units=result["semantic_units"],
            fragments=[],
            structured_blocks=[],
            alignments=[],
            xml_validation=result["result"],
            pdf_validation={"warnings": [], "errors": []},
        )
        candidates = self.service._build_candidate_objects(
            semantic_units=result["semantic_units"],
            pdf_evidence_packets=packets,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["glossary_term"], "Accessible")
        self.assertEqual(
            candidates[0]["glossary_definition"],
            "Having features to enable use by people with a disability.",
        )

    def test_validate_xml_blocks_when_known_schema_family_is_missing_required_structure(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<abcb-glossentry id="entry_1" outputclass="abcb-glossentry" edition="2022" volume="1" amendment="base" part="Schedule 1">
  <glossterm id="term_1">Accessible</glossterm>
</abcb-glossentry>
"""

        result = self.service._validate_xml(xml_bytes, "glossary-accessible.xml")

        schema_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "X0_SCHEMA_FAMILY_MATCH")
        self.assertEqual(schema_rule["status"], "FAIL")
        self.assertEqual(result["result"]["overall_status"], "BLOCKED")
        self.assertTrue(any(error["code"] == "XML_SCHEMA_REQUIRED_STRUCTURE" for error in result["result"]["errors"]))

    def test_canonical_snippets_promote_passed_candidates_only(self) -> None:
        candidates = [
            {
                "candidate_id": "candidate:unit:node_pass",
                "xml_node_id": "node_pass",
                "validation_state": "pass",
                "source": {"pdf_fragment_id": "frag_1"},
                "proposed": {"content": "Passed candidate content"},
                "confidence": {"overall": 0.97},
            },
            {
                "candidate_id": "candidate:unit:node_review",
                "xml_node_id": "node_review",
                "validation_state": "requires_review",
                "source": {"pdf_fragment_id": "frag_2"},
                "proposed": {"content": "Review candidate content"},
                "confidence": {"overall": 0.84},
            },
        ]

        snippets = self.service._build_canonical_snippets(
            can_progress=True,
            candidates=candidates,
        )

        self.assertEqual(len(snippets), 1)
        self.assertEqual(snippets[0]["candidate_id"], "candidate:unit:node_pass")
        self.assertEqual(snippets[0]["clause_id"], "node_pass")
        self.assertEqual(snippets[0]["fragment_id"], "frag_1")

    def test_validate_xml_adds_synthesized_table_row_nodes(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<table-reference id="tbl_ref_1">
  <num>J3D11a</num>
  <title>Maximum conductance to solar heat gain ratio</title>
  <table id="tbl_data_1">
    <tgroup cols="2">
      <thead>
        <row>
          <entry>Climate zone</entry>
          <entry>Maximum ratio</entry>
        </row>
      </thead>
      <tbody>
        <row>
          <entry>2</entry>
          <entry>16.95</entry>
        </row>
        <row>
          <entry>3</entry>
          <entry>19.88</entry>
        </row>
      </tbody>
    </tgroup>
  </table>
</table-reference>
"""

        result = self.service._validate_xml(xml_bytes, "table-J3D11a-maximum-conductance-to-solar-heat-gain-ratio.xml")

        row_nodes = [node for node in result["xml_nodes"] if "__row_" in node.node_id]
        self.assertEqual(len(row_nodes), 2)
        self.assertIn("Climate zone: 2", row_nodes[0].text)
        self.assertIn("Maximum ratio: 16.95", row_nodes[0].text)

    def test_validate_xml_accepts_part_root_and_infers_structural_metadata(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_j3" outputclass="ncc-part">
  <num>J3</num>
  <title>Elemental provisions</title>
  <intro-part id="intro_1">
    <p>This Part forms part of NCC 2022 Volume One.</p>
  </intro-part>
</part>
"""

        result = self.service._validate_xml(xml_bytes, "J3-elemental-provisions.xml")

        root_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "X1_XML_WELL_FORMED")
        metadata_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "X2_REQUIRED_METADATA")

        self.assertEqual(root_rule["status"], "PASS")
        self.assertEqual(metadata_rule["status"], "PASS")
        self.assertEqual(result["metrics"]["metadata"]["part"], "J3")
        self.assertEqual(result["metrics"]["metadata"]["volume"], "1")
        self.assertEqual(result["metrics"]["metadata"]["edition"], "2022")
        self.assertEqual(result["metrics"]["metadata"]["amendment"], "base")

    def test_validate_xml_ignores_external_href_targets_for_reference_resolution(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_j3" outputclass="ncc-part">
  <num>J3</num>
  <title>Elemental provisions</title>
  <intro-part id="intro_1">
    <p>See <xref href="/tmp/QppServer/example.xml#external_target" id="xref_1">other content</xref>.</p>
  </intro-part>
</part>
"""

        result = self.service._validate_xml(xml_bytes, "J3-elemental-provisions.xml")

        reference_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "X6_REFERENCE_RESOLUTION")
        self.assertEqual(reference_rule["status"], "PASS")
        self.assertEqual(result["metrics"]["unresolved_references"], 0)

    def test_validate_pdf_adds_row_fragments_from_tables(self) -> None:
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=3,
            blocks=[
                StructuredBlock(
                    block_id="docling_1_1",
                    page=1,
                    bbox=[0.0, 0.0, 10.0, 10.0],
                    block_type="paragraph",
                    text="Sample clause text",
                    source_strategy="docling",
                )
            ],
            tables=[
                ExtractedTable(
                    table_id="docling_tbl_1",
                    rows=[
                        ["Climate zone", "Maximum ratio"],
                        ["2", "16.95"],
                        ["3", "19.88"],
                    ],
                    headers_present=True,
                    related_block_id="docling_1_2",
                    bbox=[0.0, 10.0, 50.0, 40.0],
                    metadata={"page": 2, "num_rows": 3, "num_cols": 2},
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

        row_fragments = [fragment for fragment in result["fragments"] if "__row_" in fragment.fragment_id]
        self.assertEqual(len(row_fragments), 2)
        self.assertEqual(row_fragments[0].page, 2)
        self.assertIn("Climate zone: 2", row_fragments[0].text)
        self.assertIn("Maximum ratio: 16.95", row_fragments[0].text)

    def test_align_fragment_prefers_specific_row_node_over_large_container(self) -> None:
        fragment = PdfFragment(
            fragment_id="frag_1",
            page=1,
            text="Climate zone: 2 Maximum ratio: 16.95",
            bbox=[0.0, 0.0, 1.0, 1.0],
        )
        xml_nodes = [
            XmlNode(
                node_id="table_root",
                clause_id="table_root",
                text="J3D11a Maximum conductance ratio Climate zone Maximum ratio 2 16.95 3 19.88 4 13.34 5 11.83 6 6.27 7 12.90 8 12.90",
                path="/table-reference[@id='table_root']",
            ),
            XmlNode(
                node_id="table_root__row_1",
                clause_id="table_root__row_1",
                text="J3D11a Maximum conductance ratio Climate zone: 2 Maximum ratio: 16.95",
                path="/table-reference[@id='table_root']/tbody/row[1]",
            ),
        ]

        alignment = self.service._align_fragment(fragment, xml_nodes)

        self.assertTrue(alignment["matched"])
        self.assertEqual(alignment["node_id"], "table_root__row_1")

    def test_review_workspace_prefers_row_nodes_when_specific_matches_exist(self) -> None:
        xml_nodes = [
            XmlNode(
                node_id="table_root",
                clause_id="table_root",
                text="J3D11a Maximum conductance ratio Climate zone Maximum ratio 2 16.95 3 19.88",
                path="/table-reference[@id='table_root']",
            ),
            XmlNode(
                node_id="table_root__row_1",
                clause_id="table_root__row_1",
                text="J3D11a Maximum conductance ratio Climate zone: 2 Maximum ratio: 16.95",
                path="/table-reference[@id='table_root']/tbody/row[1]",
            ),
            XmlNode(
                node_id="table_root__row_2",
                clause_id="table_root__row_2",
                text="J3D11a Maximum conductance ratio Climate zone: 3 Maximum ratio: 19.88",
                path="/table-reference[@id='table_root']/tbody/row[2]",
            ),
        ]
        fragments = [
            PdfFragment(fragment_id=f"frag_{index}", page=1, text=f"Fragment {index}", bbox=[0.0, 0.0, 1.0, 1.0])
            for index in range(1, 121)
        ]
        alignments = [
            {
                "fragment_id": "docling_tbl_1__row_1",
                "node_id": "table_root__row_1",
                "confidence": 0.95,
                "matched": True,
                "page": 2,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            },
            {
                "fragment_id": "docling_tbl_1__row_2",
                "node_id": "table_root__row_2",
                "confidence": 0.94,
                "matched": True,
                "page": 2,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            },
            {
                "fragment_id": "frag_parent",
                "node_id": "table_root",
                "confidence": 0.95,
                "matched": True,
                "page": 1,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            },
        ]
        fragments.extend(
            [
                PdfFragment(fragment_id="docling_tbl_1__row_1", page=2, text="Climate zone: 2 Maximum ratio: 16.95", bbox=[0.0, 10.0, 10.0, 20.0]),
                PdfFragment(fragment_id="docling_tbl_1__row_2", page=2, text="Climate zone: 3 Maximum ratio: 19.88", bbox=[0.0, 20.0, 10.0, 30.0]),
                PdfFragment(fragment_id="frag_parent", page=1, text="J3D11a Maximum conductance ratio", bbox=[0.0, 0.0, 10.0, 10.0]),
            ]
        )

        workspace = self.service._build_review_workspace(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="table-J3D11a-maximum-conductance-to-solar-heat-gain-ratio.xml",
            xml_nodes=xml_nodes,
            fragments=fragments,
            alignments=alignments,
            canonical_snippets=[],
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )

        self.assertEqual(workspace["mode"], "focused")
        self.assertEqual(workspace["alignments"][0]["node_id"], "table_root__row_1")
        self.assertEqual([node.node_id for node in workspace["xml_nodes"]], ["table_root__row_1", "table_root__row_2"])

    def test_scope_extracted_pdf_for_part_wrapper_limits_to_intro_band(self) -> None:
        blocks = [
            StructuredBlock(
                block_id="docling_1_1",
                page=1,
                bbox=[0.0, 0.0, 1.0, 1.0],
                block_type="heading",
                text="Part J2 Energy efficiency",
                source_strategy="docling",
            ),
            StructuredBlock(
                block_id="docling_3_1",
                page=3,
                bbox=[0.0, 0.0, 1.0, 1.0],
                block_type="heading",
                text="Part J3 Elemental provisions",
                source_strategy="docling",
            ),
            StructuredBlock(
                block_id="docling_3_2",
                page=3,
                bbox=[0.0, 0.0, 1.0, 1.0],
                block_type="paragraph",
                text="This Part contains Deemed-to-Satisfy Provisions.",
                source_strategy="docling",
            ),
            StructuredBlock(
                block_id="docling_3_3",
                page=3,
                bbox=[0.0, 0.0, 1.0, 1.0],
                block_type="heading",
                text="J3D1",
                source_strategy="docling",
            ),
            StructuredBlock(
                block_id="docling_3_4",
                page=3,
                bbox=[0.0, 0.0, 1.0, 1.0],
                block_type="paragraph",
                text="Clause body text",
                source_strategy="docling",
            ),
        ]
        xml_nodes = [
            XmlNode(node_id="part_j3", clause_id="part_j3", text="J3 Elemental provisions", path="/part[@id='part_j3']"),
            XmlNode(node_id="intro_1", clause_id="intro_1", text="This Part contains Deemed-to-Satisfy Provisions.", path="/intro-part[@id='intro_1']"),
        ]
        metrics = {"root_element": "part", "metadata": {"part": "J3"}}

        scoped_blocks, scoped_tables = self.service._scope_extracted_pdf_for_xml(blocks, [], xml_nodes, metrics)

        self.assertEqual([block.block_id for block in scoped_blocks], ["docling_3_1", "docling_3_2"])
        self.assertEqual(scoped_tables, [])

    def test_validate_pdf_metadata_rule_does_not_fail_for_bounded_unresolved_alignments(self) -> None:
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=6,
            blocks=[
                StructuredBlock(
                    block_id="docling_1_1",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="Matched fragment text",
                    source_strategy="docling",
                ),
                StructuredBlock(
                    block_id="docling_1_2",
                    page=1,
                    bbox=[0.0, 1.0, 1.0, 2.0],
                    block_type="paragraph",
                    text="Unresolved fragment text",
                    source_strategy="docling",
                ),
            ],
            tables=[],
            strategy_name="docling",
            runtime_mode="native_text",
        )
        xml_context = {
            "result": {
                "gate_decision": {"can_progress_to_alignment_layer": True},
                "document": {"doc_id": "benchmark_xml"},
            },
            "metrics": {
                "root_element": "clause",
                "metadata": {"part": None, "section": "J2D2"},
            },
            "xml_nodes": [
                XmlNode(
                    node_id="node_1",
                    clause_id="node_1",
                    text="Matched fragment text",
                    path="/clause[@id='node_1']",
                )
            ],
        }
        self.service._extract_pdf = lambda pdf_bytes, strategy: extracted  # type: ignore[method-assign]

        result = self.service._validate_pdf(b"pdf", "benchmark.pdf", xml_context, self.strategy)

        metadata_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "C6_METADATA")
        alignment_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "C5_XML_ALIGNMENT")

        self.assertEqual(alignment_rule["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(metadata_rule["status"], "PASS")


class SemanticEnrichmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IngestionService()

    def test_unresolved_xref_gates_candidate_and_blocks_snippet_promotion(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_x" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="X">
  <num>X</num>
  <title>Test part</title>
  <clause id="clause_with_bad_ref">
    <p>This clause references <xref href="#nonexistent_clause" id="xref_1">another clause</xref> for compliance and detail.</p>
  </clause>
</part>
"""
        xml_ctx = self.service._validate_xml(xml_bytes, "bench-clause.xml")
        semantic_units = xml_ctx["semantic_units"]
        fragments = [
            PdfFragment(
                fragment_id="frag_1",
                page=1,
                text="This clause references another clause for compliance and detail.",
                bbox=[0.0, 0.0, 1.0, 1.0],
            )
        ]
        alignments = [
            {
                "fragment_id": "frag_1",
                "node_id": "clause_with_bad_ref",
                "confidence": 0.95,
                "matched": True,
                "page": 1,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        ]
        packets = self.service._build_pdf_evidence_packets(
            semantic_units=semantic_units,
            fragments=fragments,
            structured_blocks=[{"block_id": "frag_1", "block_type": "paragraph"}],
            alignments=alignments,
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )
        candidates = self.service._build_candidate_objects(semantic_units=semantic_units, pdf_evidence_packets=packets)
        candidates, rels, reconciliations, edges, summary = self.service._apply_semantic_enrichment(
            xml_bytes=xml_bytes,
            xml_metrics=xml_ctx["metrics"],
            semantic_units=semantic_units,
            pdf_evidence_packets=packets,
            candidate_objects=candidates,
        )
        cand = next(c for c in candidates if c.get("xml_node_id") == "clause_with_bad_ref")
        self.assertTrue(any(r.get("blocking") for r in rels))
        self.assertTrue(any(r.get("blocking") for r in (cand.get("explicit_relations") or [])))
        self.assertEqual(cand.get("validation_state"), "requires_review")
        snippets = self.service._build_canonical_snippets(can_progress=True, candidates=candidates)
        self.assertEqual(snippets, [])
        edge_types = {e.get("edge_type") for e in edges}
        self.assertIn("relation_unresolved", edge_types)
        self.assertGreaterEqual(summary.get("candidates_gated", 0), 1)
        self.assertTrue(any(record.get("review_required") for record in reconciliations))

    def test_glossary_links_and_applicability_extraction(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_g" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="G">
  <num>G</num>
  <title>Glossary test</title>
  <definition id="def_alpha"><p>Alpha means the first letter symbol.</p></definition>
  <definition id="def_beta"><p>Beta means the second letter symbol.</p></definition>
  <clause id="clause_use">
    <p>Climate zone 3 applies where Class 2 buildings use Alpha and Beta together in NSW.</p>
  </clause>
</part>
"""
        xml_ctx = self.service._validate_xml(xml_bytes, "glossary-bench.xml")
        semantic_units = xml_ctx["semantic_units"]
        fragments = [
            PdfFragment(
                fragment_id="f_clause",
                page=1,
                text="Climate zone 3 applies where Class 2 buildings use Alpha and Beta together in NSW.",
                bbox=[0.0, 0.0, 1.0, 1.0],
            )
        ]
        alignments = [
            {
                "fragment_id": "f_clause",
                "node_id": "clause_use",
                "confidence": 0.94,
                "matched": True,
                "page": 1,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        ]
        packets = self.service._build_pdf_evidence_packets(
            semantic_units=semantic_units,
            fragments=fragments,
            structured_blocks=[],
            alignments=alignments,
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )
        candidates = self.service._build_candidate_objects(semantic_units=semantic_units, pdf_evidence_packets=packets)
        candidates, _rels, _reconciliations, edges, _summary = self.service._apply_semantic_enrichment(
            xml_bytes=xml_bytes,
            xml_metrics=xml_ctx["metrics"],
            semantic_units=semantic_units,
            pdf_evidence_packets=packets,
            candidate_objects=candidates,
        )
        clause_cand = next(c for c in candidates if c.get("xml_node_id") == "clause_use")
        se = clause_cand.get("semantic_enrichment") or {}
        self.assertEqual((se.get("field_authority") or {}).get("explicit_relations"), "xml_authoritative")
        self.assertEqual((se.get("field_authority") or {}).get("glossary_links"), "heuristic_glossary_match")
        links = clause_cand.get("glossary_links") or []
        self.assertGreaterEqual(len(links), 1)
        terms = {link.get("term_normalized") for link in links}
        self.assertTrue(terms & {"alpha", "beta"})
        dims = {c.get("dimension") for c in (clause_cand.get("applicability_conditions") or [])}
        self.assertTrue({"climate_zone", "building_class", "jurisdiction"} <= dims)
        self.assertTrue(any(c.get("dimension") == "conditional_phrase" for c in (clause_cand.get("applicability_conditions") or [])))
        self.assertTrue(any(e.get("edge_type") == "glossary_link" for e in edges))

    def test_classification_object_round_trips_core_classes(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_z" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="Z">
  <num>Z</num>
  <title>T</title>
  <clause id="c1"><p>Standalone clause text for testing enrichment only.</p></clause>
</part>
"""
        xml_ctx = self.service._validate_xml(xml_bytes, "cls-bench.xml")
        semantic_units = xml_ctx["semantic_units"]
        fragments = [
            PdfFragment(fragment_id="fx", page=1, text="Standalone clause text for testing enrichment only.", bbox=[0, 0, 1, 1])
        ]
        alignments = [
            {"fragment_id": "fx", "node_id": "c1", "confidence": 0.92, "matched": True, "page": 1, "bbox": [0, 0, 1, 1]}
        ]
        packets = self.service._build_pdf_evidence_packets(
            semantic_units=semantic_units,
            fragments=fragments,
            structured_blocks=[],
            alignments=alignments,
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )
        candidates = self.service._build_candidate_objects(semantic_units=semantic_units, pdf_evidence_packets=packets)
        candidates, _, _, _, _ = self.service._apply_semantic_enrichment(
            xml_bytes=xml_bytes,
            xml_metrics=xml_ctx["metrics"],
            semantic_units=semantic_units,
            pdf_evidence_packets=packets,
            candidate_objects=candidates,
        )
        c0 = candidates[0]
        cls_obj = c0.get("classification") or {}
        self.assertEqual(cls_obj.get("xml_structural_class"), c0.get("xml_structural_class"))
        self.assertEqual(cls_obj.get("candidate_semantic_class"), c0.get("candidate_semantic_class"))

    def test_text_clause_reference_resolves_to_candidate_and_emits_reconciliation(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_c" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="C">
  <num>C</num>
  <title>Test part</title>
  <clause id="C3D15"><p>Division of public corridors greater than 40 m in length.</p></clause>
  <clause id="clause_ref_source"><p>Refer to C3D15 for division of public corridors greater than 40 m in length.</p></clause>
</part>
"""
        xml_ctx = self.service._validate_xml(xml_bytes, "bench-clause.xml")
        semantic_units = xml_ctx["semantic_units"]
        fragments = [
            PdfFragment(
                fragment_id="frag_ref",
                page=1,
                text="Refer to C3D15 for division of public corridors greater than 40 m in length.",
                bbox=[0.0, 0.0, 1.0, 1.0],
            )
        ]
        alignments = [
            {
                "fragment_id": "frag_ref",
                "node_id": "clause_ref_source",
                "confidence": 0.96,
                "matched": True,
                "page": 1,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        ]
        packets = self.service._build_pdf_evidence_packets(
            semantic_units=semantic_units,
            fragments=fragments,
            structured_blocks=[],
            alignments=alignments,
            xml_validation={"warnings": [], "errors": []},
            pdf_validation={"warnings": [], "errors": []},
        )
        candidates = self.service._build_candidate_objects(semantic_units=semantic_units, pdf_evidence_packets=packets)
        candidates, rels, reconciliations, edges, summary = self.service._apply_semantic_enrichment(
            xml_bytes=xml_bytes,
            xml_metrics=xml_ctx["metrics"],
            semantic_units=semantic_units,
            pdf_evidence_packets=packets,
            candidate_objects=candidates,
        )

        source_candidate = next(c for c in candidates if c.get("xml_node_id") == "clause_ref_source")
        resolved_relation = next(
            rel
            for rel in rels
            if rel.get("source_node_id") == "clause_ref_source" and rel.get("relation_kind") == "clause_reference"
        )
        self.assertEqual(resolved_relation.get("relation_authority"), "text_resolved")
        self.assertEqual(resolved_relation.get("resolution_status"), "resolved")
        self.assertEqual(resolved_relation.get("target_locator"), "C3D15")
        self.assertEqual(resolved_relation.get("target_node_id"), "C3D15")
        self.assertIn("candidate:unit:C3D15", source_candidate.get("depends_on") or [])
        self.assertTrue(any(record.get("source_relation_ids") == [resolved_relation.get("relation_id")] for record in reconciliations))
        self.assertGreaterEqual(summary.get("text_resolved_relation_count"), 1)
        self.assertTrue(any(edge.get("payload", {}).get("relation_authority") == "text_resolved" for edge in edges))


class CandidateRobustnessPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IngestionService()

    def test_semantic_enrichment_provenance_marks_authoritative_vs_heuristic(self) -> None:
        fa = self.service._semantic_enrichment_field_authority()
        self.assertEqual(fa["explicit_relations"], "xml_authoritative")
        self.assertEqual(fa["glossary_links"], "heuristic_glossary_match")
        self.assertEqual(fa["implicit_relation_candidates"], "heuristic_text")

    def test_foundational_baseline_slice_is_deterministic_and_bounded(self) -> None:
        units = [
            {"unit_id": "unit:b", "node_id": "b", "semantic_class": "definition", "title": "B", "text": "B means two.", "path": "/definition[@id='b']"},
            {"unit_id": "unit:a", "node_id": "a", "semantic_class": "definition", "title": "A", "text": "A means one.", "path": "/definition[@id='a']"},
            {"unit_id": "unit:t", "node_id": "t", "semantic_class": "rule", "title": "R", "text": "Longer clause body for testing.", "path": "/clause[@id='t']"},
        ]
        candidates = [
            {
                "candidate_id": "candidate:unit:a",
                "xml_node_id": "a",
                "validation_state": "pass",
                "status": "validated",
                "evidence": [{"fragment_id": "f1", "page": 1}],
                "title": "A",
            },
            {
                "candidate_id": "candidate:unit:b",
                "xml_node_id": "b",
                "validation_state": "requires_review",
                "status": "draft",
                "evidence": [],
                "title": "B",
            },
        ]
        first = self.service._build_foundational_baseline_corpus_slice(semantic_units=units, candidate_objects=candidates)
        second = self.service._build_foundational_baseline_corpus_slice(semantic_units=units, candidate_objects=candidates)
        self.assertEqual(first["items"], second["items"])
        self.assertEqual(first["items"][0]["node_id"], "a")
        self.assertEqual(first["summary"]["eligible_semantic_unit_count"], 2)
        self.assertEqual(first["summary"]["included_item_count"], 2)
        self.assertEqual(first["items"][0]["baseline_category"], "glossary_definition")

    def test_candidate_quality_and_graph_readiness_echo_counts(self) -> None:
        baseline = {
            "summary": {
                "eligible_semantic_unit_count": 3,
                "included_item_count": 2,
                "truncated": True,
                "coverage_ratio": 0.6667,
            },
            "items": [],
        }
        cq = self.service._build_candidate_quality_metrics(
            semantic_units=[{}, {}, {}],
            pdf_evidence_packets=[{}],
            candidate_objects=[{}, {}],
            review_units=[{}],
            canonical_snippets=[{"x": 1}],
            foundational_baseline_corpus=baseline,
            candidate_validation_results=[
                {"candidate_id": "candidate:1", "validation_state": "pass", "promotion_eligible": True},
                {"candidate_id": "candidate:2", "validation_state": "requires_review", "promotion_eligible": False},
            ],
        )
        self.assertEqual(cq["semantic_unit_count"], 3)
        self.assertEqual(cq["pdf_evidence_packet_count"], 1)
        self.assertEqual(cq["candidate_object_count"], 2)
        self.assertEqual(cq["review_unit_count"], 1)
        self.assertEqual(cq["promoted_snippet_count"], 1)
        self.assertEqual(cq["foundational_baseline_eligible_count"], 3)
        self.assertEqual(cq["foundational_baseline_included_count"], 2)

        gr = self.service._build_graph_readiness_summary(
            enrichment_summary={
                "unresolved_blocking_count": 0,
                "text_unresolved_relation_count": 0,
                "reconciliation_review_required_count": 0,
            },
            xml_validation={"overall_status": "PASS"},
            pdf_validation={"overall_status": "PASS"},
            candidate_quality=cq,
            candidate_validation_summary={"requires_review_count": 0, "fail_count": 0},
        )
        self.assertTrue(gr["ready_for_graph_handoff"])
        self.assertEqual(len(gr["gates"]), 10)
        gate_ids = {g["gate_id"] for g in gr["gates"]}
        self.assertIn("explicit_relations_non_blocking", gate_ids)
        self.assertIn("candidate_validation_non_blocking", gate_ids)
        self.assertIn("snippet_promotion_consistent", gate_ids)

    def test_graph_readiness_fails_when_blocking_relations_remain(self) -> None:
        cq = self.service._build_candidate_quality_metrics(
            semantic_units=[{}],
            pdf_evidence_packets=[{}],
            candidate_objects=[{}],
            review_units=[{}],
            canonical_snippets=[],
            foundational_baseline_corpus={"summary": {"eligible_semantic_unit_count": 0, "included_item_count": 0, "coverage_ratio": 0.0}},
            candidate_validation_results=[{"candidate_id": "candidate:1", "validation_state": "pass", "promotion_eligible": True}],
        )
        gr = self.service._build_graph_readiness_summary(
            enrichment_summary={
                "unresolved_blocking_count": 2,
                "text_unresolved_relation_count": 0,
                "reconciliation_review_required_count": 0,
            },
            xml_validation={"overall_status": "PASS"},
            pdf_validation={"overall_status": "PASS"},
            candidate_quality=cq,
            candidate_validation_summary={"requires_review_count": 0, "fail_count": 0},
        )
        self.assertFalse(gr["ready_for_graph_handoff"])
        blocking_gate = next(g for g in gr["gates"] if g["gate_id"] == "explicit_relations_non_blocking")
        self.assertFalse(blocking_gate["passed"])

    def test_candidate_validation_stage_respects_human_review_override(self) -> None:
        candidate = {
            "candidate_id": "candidate:unit:C3D15",
            "xml_node_id": "C3D15",
            "source": {"pdf_fragment_id": None},
            "validation_state": "requires_review",
            "status": "draft",
            "review": {"needs_human_review": True, "issues": []},
            "explicit_relations": [],
            "candidate_relations": [],
            "reconciliation_records": [],
        }
        candidates, relations, reconciliations, validation_results, summary = self.service._apply_candidate_validation_stage(
            candidate_objects=[candidate],
            candidate_relations=[],
            reconciliation_records=[],
            review_decisions=[
                {
                    "candidate_id": "candidate:unit:C3D15",
                    "decision_status": "approved",
                    "note": "Operator approved candidate.",
                    "updated_at": "2026-04-04T00:00:00Z",
                }
            ],
        )
        self.assertEqual(relations, [])
        self.assertEqual(reconciliations, [])
        self.assertEqual(candidates[0]["validation_state"], "pass")
        self.assertEqual(candidates[0]["review"]["human_decision_status"], "approved")
        self.assertFalse(validation_results[0]["promotion_eligible"])
        self.assertEqual(summary["review_override_count"], 1)


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

    def test_tag_page_frame_blocks_marks_repeated_headers_and_page_footer(self) -> None:
        blocks = [
            StructuredBlock(
                block_id="docling_1_1",
                page=1,
                bbox=[40.0, 20.0, 250.0, 34.0],
                block_type="paragraph",
                text="Governing requirements",
                source_strategy="docling",
            ),
            StructuredBlock(
                block_id="docling_1_2",
                page=1,
                bbox=[40.0, 792.0, 340.0, 806.0],
                block_type="paragraph",
                text="NCC 2022 Volume Two Page 41",
                source_strategy="docling",
            ),
            StructuredBlock(
                block_id="docling_2_1",
                page=2,
                bbox=[40.0, 20.0, 250.0, 34.0],
                block_type="paragraph",
                text="Governing requirements",
                source_strategy="docling",
            ),
            StructuredBlock(
                block_id="docling_2_2",
                page=2,
                bbox=[40.0, 792.0, 340.0, 806.0],
                block_type="paragraph",
                text="NCC 2022 Volume Two Page 42",
                source_strategy="docling",
            ),
        ]

        tagged = self.extractor._tag_page_frame_blocks(blocks, page_heights={1: 820.0, 2: 820.0})

        self.assertEqual(tagged[0].metadata["page_region"], "header")
        self.assertEqual(tagged[0].metadata["page_frame_role"], "running_header")
        self.assertEqual(tagged[1].metadata["page_region"], "footer")
        self.assertEqual(tagged[1].metadata["page_frame_role"], "page_number")

    def test_tag_page_frame_blocks_keeps_structural_part_heading_as_content(self) -> None:
        blocks = [
            StructuredBlock(
                block_id="docling_1_1",
                page=1,
                bbox=[40.0, 20.0, 320.0, 38.0],
                block_type="heading",
                text="Part A1 Interpreting the NCC",
                source_strategy="docling",
            ),
            StructuredBlock(
                block_id="docling_2_1",
                page=2,
                bbox=[40.0, 20.0, 320.0, 38.0],
                block_type="heading",
                text="Part A1 Interpreting the NCC",
                source_strategy="docling",
            ),
        ]

        tagged = self.extractor._tag_page_frame_blocks(blocks, page_heights={1: 820.0, 2: 820.0})

        self.assertNotIn("page_region", tagged[0].metadata)
        self.assertNotIn("page_region", tagged[1].metadata)

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

    def test_collect_tables_preserves_page_metadata_and_related_block_id(self) -> None:
        strategy = DocumentStrategyRouter().route(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="benchmark.xml",
            requested_document_class="clause_parity",
            requested_extraction_profile="baseline_clause_parity",
            requested_evaluation_profile="baseline_clause_parity",
            requested_extractor_strategy="docling",
        )
        table_item = SimpleNamespace(
            label="table",
            text="",
            data=SimpleNamespace(num_rows=2, num_cols=2, table_cells=[]),
            prov=[SimpleNamespace(page_no=3, bbox=SimpleNamespace(l=0.0, t=0.0, r=10.0, b=20.0))],
            export_to_dataframe=lambda doc=None: SimpleNamespace(
                fillna=lambda value: SimpleNamespace(values=SimpleNamespace(tolist=lambda: [["Header", "Value"], ["A", "1"]]))
            ),
            caption_text="Example table",
        )
        document = SimpleNamespace(iterate_items=lambda: [(table_item, 1)])
        result = SimpleNamespace(document=document)

        tables = self.extractor._collect_tables(result, strategy)

        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].metadata["page"], 3)
        self.assertEqual(tables[0].related_block_id, "docling_3_1")

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
