from __future__ import annotations

import unittest

from app.models.document_strategy import ExtractedPdf, ExtractedTable, StructuredBlock
from app.services.ingestion import IngestionService


class CorpusSliceSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IngestionService()

    def _process_fixture(
        self,
        *,
        pdf_name: str,
        xml_name: str,
        xml_bytes: bytes,
        blocks: list[StructuredBlock] | None = None,
        tables: list[ExtractedTable] | None = None,
    ) -> dict[str, object]:
        blocks = blocks or []
        tables = tables or []
        total_words = sum(len((block.text or "").split()) for block in blocks)
        if not total_words:
            total_words = sum(len(" ".join(" ".join(row) for row in table.rows).split()) for table in tables)

        extracted = ExtractedPdf(
            pages_processed=1,
            total_words=max(total_words, 1),
            blocks=blocks,
            tables=tables,
            strategy_name="docling",
            runtime_mode="native_tables_text" if tables else "native_text",
        )
        self.service._extract_pdf = lambda pdf_bytes, strategy: extracted  # type: ignore[method-assign]
        return self.service.process(
            b"%PDF-1.4\n%",
            pdf_name=pdf_name,
            xml_bytes=xml_bytes,
            xml_name=xml_name,
        )

    def test_front_matter_slice_keeps_inventory_bounded_and_promotable(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_a" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="A">
  <num>A</num>
  <title>Governing requirements</title>
  <intro-part id="intro_1"><p>This Part forms part of NCC 2022 Volume One.</p></intro-part>
  <clause id="A1G1"><p>Buildings must comply with the governing requirements in this Part.</p></clause>
</part>
"""
        payload = self._process_fixture(
            pdf_name="NCC 2022 - Vol 1 - Part A.pdf",
            xml_name="part-a.xml",
            xml_bytes=xml_bytes,
            blocks=[
                StructuredBlock(
                    block_id="frag_a1",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="Buildings must comply with the governing requirements in this Part.",
                    source_strategy="docling",
                )
            ],
        )

        self.assertGreaterEqual(payload["review_workspace"]["candidate_total"], 1)
        self.assertGreaterEqual(len(payload["lineage"]["candidate_objects"]), 3)
        self.assertEqual(
            0,
            len([record for record in payload["lineage"]["reconciliation_records"] if record.get("review_required")]),
        )
        self.assertGreaterEqual(payload["review_workspace"]["candidate_quality"]["candidate_object_count"], 3)

    def test_glossary_slice_emits_definition_candidate_without_dependency_noise(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<abcb-glossentry id="entry_1" outputclass="abcb-glossentry" edition="2022" volume="1" amendment="base" part="Schedule 1">
  <glossterm id="term_1">Accessible</glossterm>
  <glossdef outputclass="glossdef">
    <p>Having features to enable use by people with a disability.</p>
  </glossdef>
</abcb-glossentry>
"""
        payload = self._process_fixture(
            pdf_name="schedule-1-definitions.pdf",
            xml_name="glossary-accessible.xml",
            xml_bytes=xml_bytes,
            blocks=[
                StructuredBlock(
                    block_id="frag_g1",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="Accessible means having features to enable use by people with a disability.",
                    source_strategy="docling",
                )
            ],
        )

        candidate = payload["lineage"]["candidate_objects"][0]
        self.assertEqual(candidate["candidate_semantic_class"], "definition")
        self.assertEqual(
            0,
            len([record for record in payload["lineage"]["reconciliation_records"] if record.get("review_required")]),
        )
        self.assertEqual(len(payload["lineage"]["reconciliation_records"]), 0)
        self.assertEqual(payload["review_workspace"]["candidate_total"], 1)

    def test_narrow_table_slice_surfaces_synthesized_row_candidates(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<table-reference id="tbl_ref_1" edition="2022" volume="1" amendment="base" section="J">
  <num>J3D11a</num>
  <title>Maximum conductance to solar heat gain ratio</title>
  <table id="tbl_data_1">
    <tgroup cols="2">
      <thead>
        <row><entry>Climate zone</entry><entry>Maximum ratio</entry></row>
      </thead>
      <tbody>
        <row><entry>2</entry><entry>16.95</entry></row>
      </tbody>
    </tgroup>
  </table>
</table-reference>
"""
        payload = self._process_fixture(
            pdf_name="NCC 2022 - Vol 1 - Parts J2 and J3 - Energy Efficiency.pdf",
            xml_name="table-J3D11a.xml",
            xml_bytes=xml_bytes,
            tables=[
                ExtractedTable(
                    table_id="tbl_ref_1",
                    rows=[["Climate zone", "Maximum ratio"], ["2", "16.95"]],
                    headers_present=True,
                    related_block_id="tbl_ref_1",
                    bbox=[0.0, 0.0, 1.0, 1.0],
                )
            ],
        )

        row_candidates = [
            candidate
            for candidate in payload["lineage"]["candidate_objects"]
            if candidate.get("xml_node_id", "").endswith("__row_1")
        ]
        self.assertEqual(len(row_candidates), 1)
        self.assertGreaterEqual(payload["review_workspace"]["candidate_total"], 2)
        self.assertEqual(
            0,
            len([record for record in payload["lineage"]["reconciliation_records"] if record.get("review_required")]),
        )

    def test_mixed_reference_slice_tracks_resolved_and_unresolved_dependencies(self) -> None:
        xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<part id="part_c" outputclass="ncc-part" edition="2022" volume="1" amendment="base" section="C">
  <num>C</num>
  <title>Test part</title>
  <clause id="C3D15"><p>Division of public corridors greater than 40 m in length.</p></clause>
  <clause id="clause_ref_source">
    <p>Refer to <xref href="#C3D15" id="xref_1">C3D15</xref> and C3D99 for further detail.</p>
  </clause>
</part>
"""
        payload = self._process_fixture(
            pdf_name="mixed-reference.pdf",
            xml_name="mixed-reference.xml",
            xml_bytes=xml_bytes,
            blocks=[
                StructuredBlock(
                    block_id="frag_ref",
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    block_type="paragraph",
                    text="Refer to C3D15 and C3D99 for further detail.",
                    source_strategy="docling",
                )
            ],
        )

        relation_authorities = {relation.get("relation_authority") for relation in payload["lineage"]["candidate_relations"]}
        self.assertIn("xml_explicit", relation_authorities)
        self.assertIn("text_unresolved", relation_authorities)
        self.assertGreaterEqual(len(payload["lineage"]["reconciliation_records"]), 1)

        source_candidate = next(
            candidate for candidate in payload["lineage"]["candidate_objects"] if candidate.get("xml_node_id") == "clause_ref_source"
        )
        self.assertTrue(
            any(relation.get("resolution_status") == "unresolved" for relation in source_candidate.get("candidate_relations") or [])
        )


if __name__ == "__main__":
    unittest.main()
