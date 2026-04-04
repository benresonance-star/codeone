from __future__ import annotations

import unittest

from app.core.contracts import load_contracts
from app.models.document_strategy import ExtractedPdf, StructuredBlock
from app.services.ingestion import IngestionService


class ContractConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IngestionService()
        self.contracts = load_contracts()

    def _valid_xml_bytes(self) -> bytes:
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_j3" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="J">
  <num>J3</num>
  <title>Elemental provisions</title>
  <clause id="J3D1"><p>Simple clause text for contract conformance.</p></clause>
</part>
"""

    def _valid_xml_context(self) -> dict[str, object]:
        return self.service._validate_xml(self._valid_xml_bytes(), "J3-elemental-provisions.xml")

    def test_xml_rule_results_cover_schema_rule_plus_declared_contract_rules(self) -> None:
        result = self._valid_xml_context()["result"]

        declared_rule_ids = [rule["rule_id"] for rule in self.contracts["xml_contract"]["rules"]]
        observed_rule_ids = [rule["rule_id"] for rule in result["rule_results"]]

        self.assertEqual(observed_rule_ids, ["X0_SCHEMA_FAMILY_MATCH", *declared_rule_ids])

    def test_pdf_rule_results_cover_declared_contract_rules(self) -> None:
        xml_context = self._valid_xml_context()
        strategy = self.service.router.route(
            pdf_name="NCC 2022 - Vol 1 - Part J3.pdf",
            xml_name="J3-elemental-provisions.xml",
        )
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=6,
            blocks=[
                StructuredBlock(
                    block_id="frag_1",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="Simple clause text for contract conformance.",
                    source_strategy="docling",
                )
            ],
            tables=[],
            strategy_name="docling",
            runtime_mode="native_text",
        )
        self.service._extract_pdf = lambda pdf_bytes, decision: extracted  # type: ignore[method-assign]

        result = self.service._validate_pdf(b"pdf", "part-j3.pdf", xml_context, strategy)["result"]

        declared_rule_ids = [rule["rule_id"] for rule in self.contracts["pdf_contract"]["rules"]]
        observed_rule_ids = [rule["rule_id"] for rule in result["rule_results"]]

        self.assertEqual(observed_rule_ids, declared_rule_ids)

    def test_xml_content_presence_uses_warning_threshold_before_blocking(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_j3" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="J">
  <num>J3</num>
  <title></title>
  <clause id="J3D1"><p>Usable clause body remains present.</p></clause>
</part>
"""

        result = self.service._validate_xml(xml_bytes, "J3-elemental-provisions.xml")
        x5_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "X5_CONTENT_PRESENCE")

        self.assertEqual(result["metrics"]["empty_required_nodes"], 1)
        self.assertEqual(x5_rule["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["result"]["overall_status"], "REVIEW_REQUIRED")

    def test_xml_table_structure_uses_warning_threshold_before_blocking(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<table-reference id="tbl_ref_1" edition="2022" volume="1" amendment="base" section="J">
  <num>J3D11a</num>
  <title>Maximum conductance to solar heat gain ratio</title>
  <table id="tbl_data_1"></table>
</table-reference>
"""

        result = self.service._validate_xml(xml_bytes, "table-J3D11a.xml")
        x8_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "X8_TABLE_STRUCTURE")

        self.assertEqual(result["metrics"]["table_structure_issues"], 1)
        self.assertEqual(x8_rule["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["result"]["overall_status"], "REVIEW_REQUIRED")

    def test_xml_hierarchy_integrity_blocks_impossible_nesting(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_j3" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="J">
  <num>J3</num>
  <title>Elemental provisions</title>
  <subclause id="J3D1_a"><p>Subclauses cannot hang directly off a part.</p></subclause>
</part>
"""

        result = self.service._validate_xml(xml_bytes, "J3-elemental-provisions.xml")
        x3_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "X3_HIERARCHY_INTEGRITY")

        self.assertGreater(result["metrics"]["invalid_parent_child_links"], 0)
        self.assertGreater(result["metrics"]["impossible_nesting_count"], 0)
        self.assertEqual(x3_rule["status"], "FAIL")

    def test_xml_definition_structure_warns_when_term_reference_target_is_missing(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_g" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="G">
  <num>G</num>
  <title>Glossary test</title>
  <definition id="def_accessible"><p>Accessible means suitable for use.</p></definition>
  <clause id="clause_use">
    <p>Use <termref ref="#missing_definition">Accessible</termref> where required.</p>
  </clause>
</part>
"""

        result = self.service._validate_xml(xml_bytes, "glossary-bench.xml")
        x7_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "X7_DEFINITION_STRUCTURE")

        self.assertEqual(result["metrics"]["definition_link_failures"], 1)
        self.assertEqual(x7_rule["status"], "PASS_WITH_WARNINGS")

    def test_pdf_block_structure_fails_when_fragment_identity_and_metadata_are_missing(self) -> None:
        xml_context = self._valid_xml_context()
        strategy = self.service.router.route(
            pdf_name="NCC 2022 - Vol 1 - Part J3.pdf",
            xml_name="J3-elemental-provisions.xml",
        )
        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=3,
            blocks=[
                StructuredBlock(
                    block_id="",
                    page=0,
                    bbox=[],
                    block_type="",
                    text="Broken block structure",
                    source_strategy="docling",
                )
            ],
            tables=[],
            strategy_name="docling",
            runtime_mode="native_text",
        )
        self.service._extract_pdf = lambda pdf_bytes, decision: extracted  # type: ignore[method-assign]

        result = self.service._validate_pdf(b"pdf", "broken.pdf", xml_context, strategy)
        c3_rule = next(rule for rule in result["result"]["rule_results"] if rule["rule_id"] == "C3_BLOCK_STRUCTURE")

        self.assertEqual(c3_rule["status"], "FAIL")
        self.assertEqual(c3_rule["details"]["missing_fragment_id"], 1)
        self.assertEqual(c3_rule["details"]["missing_page_reference"], 1)
        self.assertEqual(c3_rule["details"]["missing_bbox"], 1)
        self.assertEqual(c3_rule["details"]["untyped_fragments"], 1)


if __name__ == "__main__":
    unittest.main()
