from __future__ import annotations

from typing import Any
import re

try:
    import fitz
except ImportError:  # pragma: no cover - optional runtime dependency
    fitz = None


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


class PyMuPdfStyleExtractor:
    @classmethod
    def is_available(cls) -> bool:
        return fitz is not None

    def extract(self, pdf_bytes: bytes) -> list[dict[str, Any]]:
        if fitz is None:
            raise RuntimeError("PyMuPDF is not installed in this runtime.")

        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        spans: list[dict[str, Any]] = []
        try:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                page_payload = page.get_text("dict")
                for block in page_payload.get("blocks", []):
                    if int(block.get("type", -1)) != 0:
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = clean_text(str(span.get("text") or ""))
                            if not text:
                                continue
                            bbox = self._normalize_bbox(span.get("bbox"))
                            flags = int(span.get("flags") or 0)
                            font_name = self._normalize_font_name(span.get("font"))
                            font_size = self._normalize_font_size(span.get("size"))
                            text_color_rgb = self._rgb_from_color(span.get("color"))
                            spans.append(
                                {
                                    "page": page_index + 1,
                                    "text": text,
                                    "bbox": bbox,
                                    "font_name": font_name,
                                    "font_size_pt": font_size,
                                    "text_color_rgb": text_color_rgb,
                                    "text_color_hex": self._hex_from_rgb(text_color_rgb),
                                    "is_bold": self._is_bold(flags, font_name),
                                    "is_italic": self._is_italic(flags, font_name),
                                }
                            )
        finally:
            document.close()

        return spans

    def _normalize_bbox(self, bbox: Any) -> list[float]:
        if not bbox or len(bbox) != 4:
            return [0.0, 0.0, 0.0, 0.0]
        return [round(float(value), 2) for value in bbox]

    def _normalize_font_name(self, value: Any) -> str | None:
        font_name = str(value or "").strip()
        if not font_name:
            return None
        return re.sub(r"^[A-Z]{6}\+", "", font_name)

    def _normalize_font_size(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    def _rgb_from_color(self, value: Any) -> list[int] | None:
        if value is None:
            return None
        try:
            color_value = int(value)
        except (TypeError, ValueError):
            return None
        return [
            (color_value >> 16) & 255,
            (color_value >> 8) & 255,
            color_value & 255,
        ]

    def _hex_from_rgb(self, rgb: list[int] | None) -> str | None:
        if not rgb or len(rgb) != 3:
            return None
        return "#{:02X}{:02X}{:02X}".format(*rgb)

    def _is_bold(self, flags: int, font_name: str | None) -> bool:
        normalized_font = (font_name or "").lower()
        return bool(flags & 16) or any(token in normalized_font for token in ("bold", "black", "heavy", "semibold", "demi"))

    def _is_italic(self, flags: int, font_name: str | None) -> bool:
        normalized_font = (font_name or "").lower()
        return bool(flags & 2) or any(token in normalized_font for token in ("italic", "oblique"))
