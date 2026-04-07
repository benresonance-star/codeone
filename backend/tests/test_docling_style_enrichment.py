from __future__ import annotations

import unittest

from app.models.document_strategy import StructuredBlock
from app.services.extractors.docling_stub import DoclingExtractor


class _FakeStyleExtractor:
    def __init__(self, spans: list[dict], available: bool = True) -> None:
        self._spans = spans
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def extract(self, pdf_bytes: bytes) -> list[dict]:
        return list(self._spans)


class _FakeCoordOrigin:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeBBox:
    def __init__(self, l: float, t: float, r: float, b: float, coord_origin: str) -> None:
        self.l = l
        self.t = t
        self.r = r
        self.b = b
        self.coord_origin = _FakeCoordOrigin(coord_origin)


class _FakeProvenance:
    def __init__(self, page_no: int, bbox: _FakeBBox) -> None:
        self.page_no = page_no
        self.bbox = bbox


class DoclingStyleEnrichmentTests(unittest.TestCase):
    def test_apply_style_enrichment_attaches_summary_and_spans(self) -> None:
        extractor = DoclingExtractor()
        extractor._style_extractor = _FakeStyleExtractor(  # type: ignore[attr-defined]
            [
                {
                    "page": 1,
                    "text": "Red",
                    "bbox": [0.0, 0.0, 20.0, 10.0],
                    "font_name": "Helvetica-Bold",
                    "font_size_pt": 12.0,
                    "text_color_rgb": [255, 0, 0],
                    "text_color_hex": "#FF0000",
                    "is_bold": True,
                    "is_italic": False,
                },
                {
                    "page": 1,
                    "text": "Blue text",
                    "bbox": [22.0, 0.0, 90.0, 10.0],
                    "font_name": "Helvetica",
                    "font_size_pt": 10.0,
                    "text_color_rgb": [0, 0, 255],
                    "text_color_hex": "#0000FF",
                    "is_bold": False,
                    "is_italic": False,
                },
            ]
        )
        block = StructuredBlock(
            block_id="docling_1_1",
            page=1,
            bbox=[0.0, 0.0, 100.0, 12.0],
            block_type="paragraph",
            text="Red Blue text",
            source_strategy="docling",
            metadata={},
        )

        enriched_blocks, notes = extractor._apply_style_enrichment(b"pdf", [block])

        self.assertEqual(len(enriched_blocks), 1)
        metadata = enriched_blocks[0].metadata
        self.assertEqual(metadata["style_summary"]["source"], "pymupdf")
        self.assertEqual(metadata["style_summary"]["text_color_hex"], "#0000FF")
        self.assertEqual(metadata["style_summary"]["font_name"], "Helvetica")
        self.assertEqual(len(metadata["style_spans"]), 2)
        self.assertGreater(metadata["style_summary"]["confidence"], 0.8)
        self.assertIn("pymupdf_style:matched_blocks=1", notes)

    def test_apply_style_enrichment_gracefully_handles_missing_runtime(self) -> None:
        extractor = DoclingExtractor()
        extractor._style_extractor = _FakeStyleExtractor([], available=False)  # type: ignore[attr-defined]
        block = StructuredBlock(
            block_id="docling_1_1",
            page=1,
            bbox=[0.0, 0.0, 100.0, 12.0],
            block_type="paragraph",
            text="No styles here",
            source_strategy="docling",
            metadata={},
        )

        enriched_blocks, notes = extractor._apply_style_enrichment(b"pdf", [block])

        self.assertEqual(enriched_blocks[0].metadata, {})
        self.assertEqual(notes, ["pymupdf_style:unavailable"])

    def test_apply_style_enrichment_matches_reversed_docling_bbox_coordinates(self) -> None:
        extractor = DoclingExtractor()
        extractor._style_extractor = _FakeStyleExtractor(  # type: ignore[attr-defined]
            [
                {
                    "page": 1,
                    "text": "A1G1 Scope of NCC Volume One",
                    "bbox": [54.24, 535.47, 288.62, 546.32],
                    "font_name": "Helvetica-Bold",
                    "font_size_pt": 14.0,
                    "text_color_rgb": [0, 0, 0],
                    "text_color_hex": "#000000",
                    "is_bold": True,
                    "is_italic": False,
                }
            ]
        )
        block = StructuredBlock(
            block_id="docling_1_5",
            page=1,
            bbox=[54.24, 546.32, 288.62, 535.47],
            block_type="heading",
            text="A1G1 Scope of NCC Volume One",
            source_strategy="docling",
            metadata={},
        )

        enriched_blocks, notes = extractor._apply_style_enrichment(b"pdf", [block])

        metadata = enriched_blocks[0].metadata
        self.assertEqual(metadata["style_summary"]["font_name"], "Helvetica-Bold")
        self.assertTrue(metadata["style_summary"]["is_bold"])
        self.assertEqual(metadata["style_summary"]["font_size_pt"], 14.0)
        self.assertEqual(metadata["style_summary"]["text_color_hex"], "#000000")
        self.assertIn("pymupdf_style:matched_blocks=1", notes)

    def test_bbox_from_provenance_converts_bottom_left_origin_to_top_left(self) -> None:
        extractor = DoclingExtractor()
        provenance = _FakeProvenance(
            page_no=1,
            bbox=_FakeBBox(54.96, 702.97, 271.37, 716.15, "BOTTOMLEFT"),
        )

        bbox = extractor._bbox_from_provenance(provenance, page_height=842.0)

        self.assertEqual(bbox, [54.96, 125.85, 271.37, 139.03])


if __name__ == "__main__":
    unittest.main()
