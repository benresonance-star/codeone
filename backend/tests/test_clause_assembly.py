from __future__ import annotations

import unittest

from app.services.ingestion import IngestionService


def _block(
    block_id: str,
    *,
    page: int,
    block_type: str,
    text: str,
    bbox: list[float],
    metadata: dict | None = None,
) -> dict:
    return {
        "block_id": block_id,
        "page": page,
        "bbox": bbox,
        "block_type": block_type,
        "text": text,
        "table_id": None,
        "section_hint": None,
        "heading_level": None,
        "source_strategy": "docling",
        "metadata": metadata or {},
    }


class ClauseAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IngestionService()

    def test_build_assembled_clauses_groups_nested_numbered_items(self) -> None:
        blocks = [
            _block("docling_3_58", page=3, block_type="heading", text="J1P2 Application of Section J", bbox=[50, 120, 300, 132]),
            _block(
                "docling_3_59",
                page=3,
                block_type="paragraph",
                text="(1) For a Class 2 to 9 building, compliance is achieved with-",
                bbox=[53.84, 187.47, 554.67, 219.61],
            ),
            _block(
                "docling_3_60",
                page=3,
                block_type="list_item",
                text="(a) Part J4, for the building fabric; and",
                bbox=[58.68, 240.16, 249.52, 256.47],
            ),
            _block(
                "docling_3_61",
                page=3,
                block_type="list_item",
                text="(b) Part J5, for building sealing; and",
                bbox=[58.68, 256.47, 249.52, 277.33],
            ),
            _block(
                "docling_3_62",
                page=3,
                block_type="paragraph",
                text="(2) For another building, compliance is achieved differently.",
                bbox=[53.84, 284.0, 554.67, 302.0],
            ),
        ]

        clauses = self.service._build_assembled_clauses(blocks)

        root_clause = next(clause for clause in clauses if clause["anchor"]["block_id"] == "docling_3_59")
        child_clause = next(clause for clause in clauses if clause["anchor"]["block_id"] == "docling_3_60")

        self.assertEqual(root_clause["label"], "(1)")
        self.assertEqual(root_clause["clause_path"], ["1"])
        self.assertEqual(root_clause["source_block_ids"], ["docling_3_59", "docling_3_60", "docling_3_61"])
        self.assertEqual([item["label"] for item in root_clause["child_items"]], ["(a)", "(b)"])
        self.assertEqual(child_clause["clause_path"], ["1", "a"])
        self.assertEqual(child_clause["title_or_lead"], "Part J4, for the building fabric; and")

    def test_build_assembled_clauses_keeps_page_break_continuation_with_parent_clause(self) -> None:
        blocks = [
            _block(
                "docling_3_10",
                page=3,
                block_type="paragraph",
                text="(1) Compliance is achieved when the following applies-",
                bbox=[50.0, 700.0, 540.0, 720.0],
            ),
            _block(
                "docling_4_11",
                page=4,
                block_type="paragraph",
                text="continued on the next page with the same requirement wording.",
                bbox=[50.0, 50.0, 540.0, 72.0],
            ),
            _block(
                "docling_4_12",
                page=4,
                block_type="paragraph",
                text="(2) A new numbered item begins here.",
                bbox=[50.0, 100.0, 540.0, 120.0],
            ),
        ]

        clauses = self.service._build_assembled_clauses(blocks)
        root_clause = next(clause for clause in clauses if clause["anchor"]["block_id"] == "docling_3_10")

        self.assertEqual(root_clause["pages"], [3, 4])
        self.assertEqual(root_clause["source_block_ids"], ["docling_3_10", "docling_4_11"])
        self.assertEqual(root_clause["rendered_blocks"][1]["render_role"], "continuation")

    def test_build_assembled_clauses_ignores_table_and_note_like_false_positives(self) -> None:
        blocks = [
            _block("docling_1_1", page=1, block_type="heading", text="Section J", bbox=[40, 40, 260, 58]),
            _block("docling_1_2", page=1, block_type="paragraph", text="Notes: New South Wales Section J Energy Efficiency", bbox=[50, 80, 500, 98]),
            _block("docling_1_3", page=1, block_type="table", text="Not a clause table", bbox=[50, 120, 500, 160]),
            _block("docling_1_4", page=1, block_type="caption", text="Table caption", bbox=[50, 165, 500, 180]),
            _block("docling_1_5", page=1, block_type="paragraph", text="(1) A real clause begins here.", bbox=[50, 200, 500, 220]),
        ]

        clauses = self.service._build_assembled_clauses(blocks)
        clause_ids = [clause["anchor"]["block_id"] for clause in clauses]

        self.assertIn("docling_1_1", clause_ids)
        self.assertIn("docling_1_5", clause_ids)
        self.assertNotIn("docling_1_2", clause_ids)
        self.assertNotIn("docling_1_3", clause_ids)
        self.assertNotIn("docling_1_4", clause_ids)

    def test_attach_clause_projections_to_candidates_prefers_primary_fragment_match(self) -> None:
        blocks = [
            _block(
                "docling_3_59",
                page=3,
                block_type="paragraph",
                text="(1) For a Class 2 to 9 building, compliance is achieved with-",
                bbox=[53.84, 187.47, 554.67, 219.61],
                metadata={
                    "style_spans": [
                        {"start": 0, "end": 3, "text_color_hex": "#AA5500", "is_bold": True},
                    ]
                },
            ),
            _block(
                "docling_3_60",
                page=3,
                block_type="list_item",
                text="(a) Part J4, for the building fabric; and",
                bbox=[58.68, 240.16, 249.52, 256.47],
            ),
        ]
        clauses = self.service._build_assembled_clauses(
            blocks,
            alignments=[
                {
                    "fragment_id": "docling_3_60",
                    "node_id": "j1p2_a",
                    "confidence": 0.96,
                    "matched": True,
                }
            ],
        )
        candidate = {
            "candidate_id": "candidate:unit_j1p2_a",
            "semantic_unit_id": "unit_j1p2_a",
            "xml_node_id": "j1p2_a",
            "title": "J1P2 paragraph (a)",
            "candidate_type": "rule",
            "candidate_semantic_class": "rule",
            "xml_path": "/clause[@id='j1p2']/subclause[@id='j1p2_a']",
            "confidence": {"overall": 0.96},
            "source": {"xml_node_id": "j1p2_a", "pdf_fragment_id": "docling_3_60", "alignment_confidence": 0.96},
            "proposed": {"content": "(a) Part J4, for the building fabric; and"},
            "evidence": [
                {
                    "fragment_id": "docling_3_60",
                    "page": 3,
                    "bbox": [58.68, 240.16, 249.52, 256.47],
                    "text": "(a) Part J4, for the building fabric; and",
                    "confidence": 0.96,
                    "pdf_evidence_class": "list_item",
                }
            ],
            "review": {
                "base_status": "match",
                "needs_human_review": False,
                "issue_class": "clean_match",
                "source_emphasis": "balanced",
                "issues": [],
                "xml_only_terms": [],
                "pdf_only_terms": [],
            },
            "candidate_relations": [],
            "reconciliation_records": [],
            "depends_on": [],
        }

        enriched = self.service._attach_clause_projections_to_candidates(
            candidates=[candidate],
            assembled_clauses=clauses,
        )[0]

        self.assertIsNotNone(enriched["assembled_clause"])
        self.assertEqual(enriched["assembled_clause"]["anchor"]["block_id"], "docling_3_60")
        self.assertEqual(enriched["display_projection"]["clause_label"], "(a)")
        self.assertEqual(enriched["display_projection"]["source_provenance"]["matched_xml_node_id"], "j1p2_a")
        self.assertEqual(enriched["display_projection"]["added_fields"]["candidate_id"], "candidate:unit_j1p2_a")

    def test_build_assembled_clauses_recovers_header_and_annotation_separately(self) -> None:
        blocks = [
            _block("docling_1_10", page=1, block_type="heading", text="Part A1", bbox=[50, 40, 200, 58]),
            _block("docling_1_11", page=1, block_type="paragraph", text="A1G2", bbox=[50, 110, 90, 124]),
            _block(
                "docling_1_12",
                page=1,
                block_type="paragraph",
                text="Scope of NCC Volume Two",
                bbox=[120, 110, 340, 124],
                metadata={"style_summary": {"is_bold": True}},
            ),
            _block("docling_1_13", page=1, block_type="paragraph", text="[New for 2022]", bbox=[420, 110, 520, 124]),
            _block(
                "docling_1_14",
                page=1,
                block_type="paragraph",
                text="NCC Volume Two contains the requirements for-",
                bbox=[50, 145, 520, 162],
            ),
            _block(
                "docling_1_15",
                page=1,
                block_type="list_item",
                text="(a) Class 1 and 10a buildings; and",
                bbox=[70, 175, 300, 193],
            ),
            _block(
                "docling_1_16",
                page=1,
                block_type="list_item",
                text="(b) certain Class 10b structures; and",
                bbox=[70, 196, 320, 214],
            ),
            _block(
                "docling_1_17",
                page=1,
                block_type="list_item",
                text="(c) Class 10c private bushfire shelters.",
                bbox=[70, 217, 330, 235],
            ),
        ]

        clauses = self.service._build_assembled_clauses(blocks)
        clause = next(clause for clause in clauses if clause["anchor"]["block_id"] == "docling_1_11")

        self.assertEqual(clause["clause_code"], "A1G2")
        self.assertEqual(clause["heading_text"], "Scope of NCC Volume Two")
        self.assertEqual(clause["title_or_lead"], "A1G2 Scope of NCC Volume Two")
        self.assertEqual([block["text"] for block in clause["header_blocks"]], ["A1G2", "Scope of NCC Volume Two"])
        self.assertEqual([block["text"] for block in clause["marginalia_blocks"]], ["[New for 2022]"])
        self.assertEqual(clause["body_blocks"][0]["text"], "NCC Volume Two contains the requirements for-")
        self.assertEqual([item["label"] for item in clause["child_items"]], ["(a)", "(b)", "(c)"])
        self.assertEqual(clause["rendered_blocks"][1]["render_role"], "header")
        self.assertEqual(clause["rendered_blocks"][2]["render_role"], "annotation")


if __name__ == "__main__":
    unittest.main()
