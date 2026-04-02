from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReviewPolicy:
    min_alignment_confidence_for_review: float = 0.9
    max_unresolved_for_review: int = 5
    max_low_confidence_for_review: int = 5
    require_review_for_grouped_parity: bool = False
    require_review_for_interpretive_content: bool = False


@dataclass(frozen=True)
class ExtractionProfile:
    profile_id: str
    description: str
    expected_split_scope: str = "section"
    require_table_headers: bool = False
    prefer_docling: bool = False
    glossary_first: bool = False
    review_policy: ReviewPolicy = field(default_factory=ReviewPolicy)


@dataclass(frozen=True)
class EvaluationProfile:
    profile_id: str
    description: str
    parity_mode: str
    grouped_targets: bool = False
    glossary_semantics: bool = False


@dataclass(frozen=True)
class DocumentStrategyDecision:
    document_class: str
    extraction_profile: ExtractionProfile
    evaluation_profile: EvaluationProfile
    extractor_strategy: str
    review_policy: ReviewPolicy
    extractor_options: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StructuredBlock:
    block_id: str
    page: int
    bbox: list[float]
    block_type: str
    text: str
    table_id: str | None = None
    section_hint: str | None = None
    heading_level: int | None = None
    source_strategy: str = "pdfplumber"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedTable:
    table_id: str
    rows: list[list[str]]
    headers_present: bool
    related_block_id: str | None = None
    bbox: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedPdf:
    pages_processed: int
    total_words: int
    blocks: list[StructuredBlock]
    tables: list[ExtractedTable]
    strategy_name: str
    runtime_mode: str = "native"
    notes: list[str] = field(default_factory=list)
