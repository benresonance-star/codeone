from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from difflib import SequenceMatcher
import hashlib
from typing import Any
import re
import xml.etree.ElementTree as ET

from app.core.contracts import load_contracts, validate_payload
from app.models.document_strategy import (
    DocumentStrategyDecision,
    ExtractedPdf,
    ExtractedTable,
    ReviewPolicy,
    StructuredBlock,
)
from app.models.validation import (
    CandidateValidationIssueRecord,
    CandidateValidationRecord,
    CandidateValidationSummaryRecord,
)
from app.services.document_strategy import DocumentStrategyRouter
from app.services.extractors import DoclingExtractor, PdfPlumberExtractor
from app.services.xml_schema_registry import XmlSchemaRegistryService


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def normalize_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[midpoint], 3)
    return round((ordered[midpoint - 1] + ordered[midpoint]) / 2, 3)


MAX_DOCUMENT_FAMILY_ID_LENGTH = 80
REVIEW_WORKSPACE_MAX_ALIGNMENTS_PER_NODE = 3
REVIEW_WORKSPACE_NARROW_XML_NODE_LIMIT = 12
REVIEW_WORKSPACE_LARGE_FRAGMENT_LIMIT = 100
TABLE_ROW_FRAGMENT_MIN_TEXT_LENGTH = 12
_GLOSSARY_ENTRY_ROOT_TAGS = frozenset({"abcb-glossentry", "glossentry"})
_GLOSSARY_CHILD_TAGS = frozenset({"glossterm", "glossdef"})
_XML_SCHEMA_FAMILY_REGISTRY = (
    {
        "schema_family_id": "ncc_document",
        "root_tags": frozenset({"ncc", "NCC"}),
        "required_children": frozenset(),
        "recommended_children": frozenset({"part", "clause", "table-reference", "image-reference"}),
        "parser_profile": "ncc_document",
    },
    {
        "schema_family_id": "ncc_part",
        "root_tags": frozenset({"part"}),
        "required_children": frozenset(),
        "recommended_children": frozenset({"num", "title"}),
        "parser_profile": "ncc_part",
    },
    {
        "schema_family_id": "ncc_clause",
        "root_tags": frozenset({"clause"}),
        "required_children": frozenset(),
        "recommended_children": frozenset({"title", "sptc", "p", "subclause"}),
        "parser_profile": "ncc_clause",
    },
    {
        "schema_family_id": "table_reference",
        "root_tags": frozenset({"table-reference"}),
        "required_children": frozenset({"table"}),
        "recommended_children": frozenset({"num", "title"}),
        "parser_profile": "table_reference",
    },
    {
        "schema_family_id": "image_reference",
        "root_tags": frozenset({"image-reference"}),
        "required_children": frozenset(),
        "recommended_children": frozenset({"title", "image", "caption"}),
        "parser_profile": "image_reference",
    },
    {
        "schema_family_id": "abcb_glossentry",
        "root_tags": _GLOSSARY_ENTRY_ROOT_TAGS,
        "required_children": frozenset({"glossterm", "glossdef"}),
        "recommended_children": frozenset(),
        "parser_profile": "abcb_glossentry",
    },
)

# Foundational baseline corpus: low-risk, inspectable categories for a deterministic slice
_BASELINE_SEMANTIC_CLASSES = frozenset({"definition", "title", "context_key", "note"})
_BASELINE_PATH_MARKERS = ("intro-part", "/intro", "subtitle", "/note[", "/title[")
_MAX_BASELINE_CORPUS_ITEMS = 500
_CLAUSE_LABEL_PAREN_PATTERN = re.compile(r"^\(([^)]+)\)\s*")
_CLAUSE_CODE_PATTERN = re.compile(r"^([A-Z]\d[A-Z]\d+[A-Z]?)\b")
_ROMAN_TOKEN_PATTERN = re.compile(r"^(?=[ivxlcdm]+$)(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv)$", re.IGNORECASE)
_NON_CLAUSE_LEAD_PATTERN = re.compile(r"^(?:notes?|table|figure|source)\b[:\s]", re.IGNORECASE)
_BRACKETED_MARGINALIA_PATTERN = re.compile(r"^\[[^\]]{1,80}\]$")
_EDITORIAL_MARGINALIA_PATTERN = re.compile(
    r"^(?:new\s+for\s+\d{4}|amend(?:ed|ment)?(?:\s+no\.?\s*\d+)?|deleted|inserted|repealed)\b",
    re.IGNORECASE,
)
_DOCUMENT_HEADING_PATTERN = re.compile(r"^(Part|Section|Schedule)\s+([A-Za-z0-9.-]+)\b[\s:,-]*(.*)$", re.IGNORECASE)
_NCC_VOLUME_PATTERN = re.compile(r"(?i)\bvolume\s+(one|two|three|\d+)\b")
_NCC_PAGE_PATTERN = re.compile(r"(?i)\bpage\s+(\d{1,4})\b")

# Deterministic applicability / implicit-relation patterns (conservative, inspectable)
_CLIMATE_ZONE_PATTERN = re.compile(r"(?i)climate\s+zone\s*([0-9]{1,2}[a-z]?)")
_BUILDING_CLASS_PATTERN = re.compile(r"(?i)\bclass\s+([0-9]{1,2}[a-z]?)\b")
_JURISDICTION_PATTERN = re.compile(
    r"(?i)\b(NSW|VIC|QLD|SA|WA|TAS|ACT|NT|Australian\s+Capital\s+Territory|New\s+South\s+Wales)\b"
)
_CONDITIONAL_PHRASE_PATTERN = re.compile(
    r"(?i)\b(where|if|unless|provided\s+that)\b[^.\n]{0,160}"
)
_IMPLICIT_SEE_PATTERN = re.compile(
    r"(?i)\b(?:see|refer\s+to)\s+([A-Za-z0-9][^.;\n]{2,120})"
)
_CLAUSE_LABEL_PATTERN = re.compile(r"\b([A-Z]\d[A-Z]\d+[A-Z]?)\b")


@dataclass
class XmlNode:
    node_id: str
    clause_id: str
    text: str
    path: str
    context_descriptor: XmlContextDescriptor | None = None


@dataclass
class XmlContextDescriptor:
    node_id: str
    full_path: str
    context_path_signature: str
    parent_node_id: str | None
    root_node_id: str | None
    ancestor_node_ids: list[str]
    ancestor_tags: list[str]
    nearest_structural_parent_id: str | None
    nearest_structural_parent_tag: str | None
    context_titles: list[str]
    depth: int
    sibling_index: int


@dataclass
class PdfFragment:
    fragment_id: str
    page: int
    text: str
    bbox: list[float]


class IngestionService:
    def __init__(self) -> None:
        self.contracts = load_contracts()
        self.router = DocumentStrategyRouter()
        self.schema_registry = XmlSchemaRegistryService()
        self.extractors = {
            "pdfplumber": PdfPlumberExtractor(),
            "docling": DoclingExtractor(),
        }

    def process(
        self,
        pdf_bytes: bytes,
        pdf_name: str,
        xml_bytes: bytes,
        xml_name: str,
        *,
        document_class: str | None = None,
        extraction_profile: str | None = None,
        evaluation_profile: str | None = None,
        extractor_strategy: str | None = None,
    ) -> dict[str, Any]:
        xml_context = self._validate_xml(xml_bytes, xml_name)
        strategy = self.router.route(
            pdf_name=pdf_name,
            xml_name=xml_name,
            xml_schema_family_id=xml_context["metrics"].get("schema_family_id"),
            requested_document_class=document_class,
            requested_extraction_profile=extraction_profile,
            requested_evaluation_profile=evaluation_profile,
            requested_extractor_strategy=extractor_strategy,
        )
        strategy = self._resolve_runtime_strategy(strategy)
        pdf_context = self._validate_pdf(pdf_bytes, pdf_name, xml_context, strategy)
        document_family_id = self._build_document_family_id(pdf_name=pdf_name, xml_name=xml_name)
        semantic_units = xml_context["semantic_units"]
        pdf_evidence_packets = self._build_pdf_evidence_packets(
            semantic_units=semantic_units,
            fragments=pdf_context["fragments"],
            structured_blocks=pdf_context["structured_blocks"],
            alignments=pdf_context["alignments"],
            xml_validation=xml_context["result"],
            pdf_validation=pdf_context["result"],
        )
        candidate_objects = self._build_candidate_objects(
            semantic_units=semantic_units,
            pdf_evidence_packets=pdf_evidence_packets,
            assembled_clauses=pdf_context["assembled_clauses"],
            structured_blocks=pdf_context["structured_blocks"],
        )
        (
            candidate_objects,
            candidate_relations,
            reconciliation_records,
            graph_edges,
            enrichment_summary,
            candidate_validation_results,
            candidate_validation_summary,
            canonical_snippets,
        ) = self._run_candidate_runtime(
            xml_bytes=xml_bytes,
            xml_metrics=xml_context["metrics"],
            semantic_units=semantic_units,
            pdf_evidence_packets=pdf_evidence_packets,
            candidate_objects=candidate_objects,
            can_progress_to_semantic_layer=self._can_progress_to_candidate_promotion(pdf_context["result"]),
            review_decisions=None,
        )
        candidate_objects = self._attach_clause_projections_to_candidates(
            candidates=candidate_objects,
            assembled_clauses=pdf_context["assembled_clauses"],
            structured_blocks=pdf_context["structured_blocks"],
        )
        review_workspace = self._build_review_workspace(
            pdf_name=pdf_name,
            xml_name=xml_name,
            xml_nodes=xml_context["xml_nodes"],
            semantic_units=semantic_units,
            fragments=pdf_context["fragments"],
            structured_blocks=pdf_context["structured_blocks"],
            assembled_clauses=pdf_context["assembled_clauses"],
            alignments=pdf_context["alignments"],
            candidates=candidate_objects,
            canonical_snippets=canonical_snippets,
            xml_validation=xml_context["result"],
            pdf_validation=pdf_context["result"],
            xml_bytes=xml_bytes,
            xml_metrics=xml_context["metrics"],
            candidate_relations=candidate_relations,
            reconciliation_records=reconciliation_records,
            graph_edges=graph_edges,
            enrichment_summary=enrichment_summary,
            candidate_validation_results=candidate_validation_results,
            candidate_validation_summary=candidate_validation_summary,
            review_decisions=[],
        )

        foundational_baseline_corpus = self._build_foundational_baseline_corpus_slice(
            semantic_units=semantic_units,
            candidate_objects=candidate_objects,
        )
        candidate_quality = self._build_candidate_quality_metrics(
            semantic_units=semantic_units,
            pdf_evidence_packets=pdf_evidence_packets,
            candidate_objects=candidate_objects,
            review_units=review_workspace["review_units"],
            canonical_snippets=canonical_snippets,
            foundational_baseline_corpus=foundational_baseline_corpus,
            candidate_validation_results=candidate_validation_results,
        )
        graph_readiness = self._build_graph_readiness_summary(
            enrichment_summary=enrichment_summary,
            xml_validation=xml_context["result"],
            pdf_validation=pdf_context["result"],
            candidate_quality=candidate_quality,
            candidate_validation_summary=candidate_validation_summary,
        )
        review_workspace = {
            **review_workspace,
            "candidate_quality": candidate_quality,
            "graph_readiness": graph_readiness,
            "foundational_baseline_corpus": foundational_baseline_corpus,
        }
        docling_view = self._build_docling_view(
            structured_blocks=pdf_context["structured_blocks"],
            tables=pdf_context["tables"],
            assembled_clauses=pdf_context["assembled_clauses"],
            strategy=pdf_context["strategy"],
        )

        return {
            "summary": {
                "ingestion_run_status": "active",
                "xml_status": xml_context["result"]["overall_status"],
                "pdf_status": pdf_context["result"]["overall_status"],
                "can_progress": bool(pdf_context["result"]["gate_decision"]["can_progress_to_semantic_layer"]),
                "paired_document_id": pdf_context["result"]["document"].get("paired_xml_doc_id")
                or xml_context["result"]["document"].get("paired_pdf_doc_id"),
                "schema_family_id": xml_context["metrics"].get("schema_family_id"),
                "schema_family_version": xml_context["metrics"].get("schema_family_version"),
                "schema_registry_version": xml_context["metrics"].get("schema_registry_version"),
                "schema_normalizer_version": xml_context["metrics"].get("schema_normalizer_version"),
                "schema_recheck_status": xml_context["metrics"].get("schema_recheck_status"),
                "document_strategy": pdf_context["strategy"],
                "parity_summary": pdf_context["parity_scaffold"]["summary"],
            },
            "results": {
                "xml_validation": xml_context["result"],
                "pdf_validation": pdf_context["result"],
            },
            "raw_metrics": {
                "xml": xml_context["metrics"],
                "pdf": pdf_context["metrics"],
            },
            "lineage": {
                "document_family_id": document_family_id,
                "xml_nodes": xml_context["xml_nodes"],
                "xml_semantic_units": semantic_units,
                "pdf_fragments": pdf_context["fragments"],
                "structured_blocks": pdf_context["structured_blocks"],
                "pdf_clause_candidates": pdf_context["assembled_clauses"],
                "docling_tables": pdf_context["tables"],
                "alignments": pdf_context["alignments"],
                "parity_scaffold": pdf_context["parity_scaffold"],
                "pdf_evidence_packets": pdf_evidence_packets,
                "candidate_objects": candidate_objects,
                "candidate_relations": candidate_relations,
                "reconciliation_records": reconciliation_records,
                "candidate_validation_results": candidate_validation_results,
                "candidate_validation_summary": candidate_validation_summary,
                "graph_edges": graph_edges,
                "enrichment_summary": enrichment_summary,
                "canonical_snippets": canonical_snippets,
                "pdf_tables": pdf_context["result"].get("table_validation", []),
                "xml_tables": xml_context["result"].get("table_validation", []),
                "candidate_quality": candidate_quality,
                "graph_readiness": graph_readiness,
                "foundational_baseline_corpus": foundational_baseline_corpus,
                "schema_runtime": xml_context["metrics"].get("schema_runtime", {}),
            },
            "review_workspace": review_workspace,
            "docling_view": docling_view,
        }

    def process_pdf_only(
        self,
        *,
        pdf_bytes: bytes,
        pdf_name: str,
        xml_bytes: bytes | None = None,
        xml_name: str | None = None,
        document_class: str | None = None,
        extraction_profile: str | None = None,
        evaluation_profile: str | None = None,
        extractor_strategy: str | None = None,
    ) -> dict[str, Any]:
        xml_context = self._reference_xml_context(xml_bytes=xml_bytes, xml_name=xml_name)
        strategy = self.router.route(
            pdf_name=pdf_name,
            xml_name="",
            requested_document_class=document_class,
            requested_extraction_profile=extraction_profile,
            requested_evaluation_profile=evaluation_profile,
            requested_extractor_strategy=extractor_strategy,
        )
        strategy = self._resolve_runtime_strategy(strategy)
        extracted = self._extract_pdf(pdf_bytes, strategy)
        fragments = self._fragments_from_blocks(extracted.blocks, extracted.tables)
        structured_blocks = self._codify_block_styles([self._serialize_block(block) for block in extracted.blocks])
        tables = [self._serialize_extracted_table(table) for table in extracted.tables]
        assembled_clauses = self._build_assembled_clauses(structured_blocks)
        pdf_context = self._build_pdf_only_context(
            pdf_name=pdf_name,
            extracted=extracted,
            strategy=strategy,
            fragments=fragments,
            structured_blocks=structured_blocks,
            tables=tables,
            assembled_clauses=assembled_clauses,
        )
        pdf_units = self._build_pdf_candidate_units(
            structured_blocks=structured_blocks,
            assembled_clauses=assembled_clauses,
        )
        pdf_evidence_packets = self._build_pdf_native_evidence_packets(
            units=pdf_units,
            fragments=fragments,
            structured_blocks=structured_blocks,
            pdf_validation=pdf_context["result"],
        )
        candidate_objects = self._build_candidate_objects(
            semantic_units=pdf_units,
            pdf_evidence_packets=pdf_evidence_packets,
            assembled_clauses=assembled_clauses,
            structured_blocks=structured_blocks,
        )
        (
            candidate_objects,
            candidate_relations,
            reconciliation_records,
            graph_edges,
            enrichment_summary,
            candidate_validation_results,
            candidate_validation_summary,
            canonical_snippets,
        ) = self._run_candidate_runtime(
            xml_bytes=None,
            xml_metrics={},
            semantic_units=pdf_units,
            pdf_evidence_packets=pdf_evidence_packets,
            candidate_objects=candidate_objects,
            can_progress_to_semantic_layer=False,
            review_decisions=None,
        )
        candidate_objects = self._attach_clause_projections_to_candidates(
            candidates=candidate_objects,
            assembled_clauses=assembled_clauses,
            structured_blocks=structured_blocks,
        )
        review_workspace = self._build_review_workspace(
            pdf_name=pdf_name,
            xml_name=xml_name or "",
            xml_nodes=xml_context["xml_nodes"],
            semantic_units=pdf_units,
            fragments=fragments,
            structured_blocks=structured_blocks,
            assembled_clauses=assembled_clauses,
            alignments=[],
            candidates=candidate_objects,
            canonical_snippets=canonical_snippets,
            xml_validation=xml_context["result"],
            pdf_validation=pdf_context["result"],
            candidate_relations=candidate_relations,
            reconciliation_records=reconciliation_records,
            graph_edges=graph_edges,
            enrichment_summary=enrichment_summary,
            candidate_validation_results=candidate_validation_results,
            candidate_validation_summary=candidate_validation_summary,
            review_decisions=[],
            pdf_evidence_packets=pdf_evidence_packets,
        )
        foundational_baseline_corpus = self._build_foundational_baseline_corpus_slice(
            semantic_units=pdf_units,
            candidate_objects=candidate_objects,
        )
        candidate_quality = self._build_candidate_quality_metrics(
            semantic_units=pdf_units,
            pdf_evidence_packets=pdf_evidence_packets,
            candidate_objects=candidate_objects,
            review_units=review_workspace["review_units"],
            canonical_snippets=canonical_snippets,
            foundational_baseline_corpus=foundational_baseline_corpus,
            candidate_validation_results=candidate_validation_results,
        )
        graph_readiness = self._build_graph_readiness_summary(
            enrichment_summary=enrichment_summary,
            xml_validation=xml_context["result"],
            pdf_validation=pdf_context["result"],
            candidate_quality=candidate_quality,
            candidate_validation_summary=candidate_validation_summary,
        )
        review_workspace = {
            **review_workspace,
            "candidate_quality": candidate_quality,
            "graph_readiness": graph_readiness,
            "foundational_baseline_corpus": foundational_baseline_corpus,
            "xml_reference_available": bool(xml_bytes),
        }
        docling_view = self._build_docling_view(
            structured_blocks=structured_blocks,
            tables=tables,
            assembled_clauses=assembled_clauses,
            strategy=pdf_context["strategy"],
        )
        return {
            "summary": {
                "ingestion_run_status": "transient_pdf_only",
                "xml_status": xml_context["result"].get("overall_status") or "NOT_PROVIDED",
                "pdf_status": pdf_context["result"]["overall_status"],
                "can_progress": False,
                "paired_document_id": None,
                "schema_family_id": None,
                "schema_family_version": None,
                "schema_registry_version": None,
                "schema_normalizer_version": None,
                "schema_recheck_status": "not_applicable",
                "document_strategy": pdf_context["strategy"],
                "parity_summary": pdf_context["parity_scaffold"]["summary"],
                "created_at": utc_now_iso(),
                "ingestion_run_id": None,
                "xml_source_document_id": self._slugify(xml_name or "xml_not_provided") if xml_name else None,
                "pdf_source_document_id": self._slugify(pdf_name),
            },
            "results": {
                "xml_validation": xml_context["result"],
                "pdf_validation": pdf_context["result"],
            },
            "raw_metrics": {
                "xml": xml_context["metrics"],
                "pdf": pdf_context["metrics"],
            },
            "lineage": {
                "document_family_id": self._build_document_family_id(
                    pdf_name=pdf_name,
                    xml_name=xml_name or "pdf_only_reference",
                ),
                "workspace_mode": "pdf_only",
                "xml_nodes": xml_context["xml_nodes"],
                "xml_semantic_units": [],
                "reference_xml_semantic_units": xml_context["semantic_units"],
                "pdf_semantic_units": pdf_units,
                "pdf_fragments": fragments,
                "structured_blocks": structured_blocks,
                "pdf_clause_candidates": assembled_clauses,
                "docling_tables": tables,
                "alignments": [],
                "parity_scaffold": pdf_context["parity_scaffold"],
                "pdf_evidence_packets": pdf_evidence_packets,
                "candidate_objects": candidate_objects,
                "candidate_relations": candidate_relations,
                "reconciliation_records": reconciliation_records,
                "candidate_validation_results": candidate_validation_results,
                "candidate_validation_summary": candidate_validation_summary,
                "graph_edges": graph_edges,
                "enrichment_summary": enrichment_summary,
                "canonical_snippets": canonical_snippets,
                "pdf_tables": pdf_context["result"].get("table_validation", []),
                "xml_tables": xml_context["result"].get("table_validation", []),
                "candidate_quality": candidate_quality,
                "graph_readiness": graph_readiness,
                "foundational_baseline_corpus": foundational_baseline_corpus,
                "schema_runtime": {},
            },
            "review_workspace": review_workspace,
            "docling_view": docling_view,
        }

    def preview_docling(
        self,
        *,
        pdf_bytes: bytes,
        pdf_name: str,
        document_class: str | None = None,
        extraction_profile: str | None = None,
        evaluation_profile: str | None = None,
        extractor_strategy: str | None = None,
    ) -> dict[str, Any]:
        strategy = self.router.route(
            pdf_name=pdf_name,
            xml_name="",
            requested_document_class=document_class,
            requested_extraction_profile=extraction_profile,
            requested_evaluation_profile=evaluation_profile,
            requested_extractor_strategy=extractor_strategy or "docling",
        )
        strategy = self._resolve_runtime_strategy(strategy)
        extracted = self._extract_pdf(pdf_bytes, strategy)
        structured_blocks = self._codify_block_styles([self._serialize_block(block) for block in extracted.blocks])
        tables = [self._serialize_extracted_table(table) for table in extracted.tables]
        strategy_payload = self._serialize_strategy(strategy, extracted)
        assembled_clauses = self._build_assembled_clauses(structured_blocks)
        return {
            "docling_view": self._build_docling_view(
                structured_blocks=structured_blocks,
                tables=tables,
                assembled_clauses=assembled_clauses,
                strategy=strategy_payload,
            ),
            "raw_metrics": {
                "structured_block_count": len(structured_blocks),
                "assembled_clause_count": len(assembled_clauses),
                "table_count": len(tables),
                "runtime_mode": extracted.runtime_mode,
                "runtime_strategy": extracted.strategy_name,
            },
        }

    def _reference_xml_context(self, *, xml_bytes: bytes | None, xml_name: str | None) -> dict[str, Any]:
        if not xml_bytes or not xml_name:
            return {
                "result": {
                    "validation_id": "xml_reference_not_provided",
                    "document": {
                        "doc_id": "xml_reference_not_provided",
                        "schema_family_id": None,
                    },
                    "overall_status": "NOT_PROVIDED",
                    "gate_decision": {
                        "can_progress_to_alignment_layer": False,
                        "blocked": False,
                        "reason": "XML was not supplied for PDF-only review.",
                    },
                    "warnings": [],
                    "errors": [],
                    "table_validation": [],
                    "rule_results": [],
                },
                "metrics": {
                    "schema_family_id": None,
                    "metadata": {},
                    "warnings": [],
                    "errors": [],
                    "reference_mode": "not_provided",
                },
                "xml_nodes": [],
                "semantic_units": [],
            }
        context = self._validate_xml(xml_bytes, xml_name)
        metrics = dict(context.get("metrics") or {})
        metrics["reference_mode"] = "secondary_reference"
        return {
            "result": context["result"],
            "metrics": metrics,
            "xml_nodes": context["xml_nodes"],
            "semantic_units": context["semantic_units"],
        }

    def _build_pdf_only_context(
        self,
        *,
        pdf_name: str,
        extracted: ExtractedPdf,
        strategy: DocumentStrategyDecision,
        fragments: list[PdfFragment],
        structured_blocks: list[dict[str, Any]],
        tables: list[dict[str, Any]],
        assembled_clauses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        table_validation = [
            {
                "table_id": table.get("table_id"),
                "status": "PASS" if table.get("rows") else "FAIL",
                "rows_expected": len(table.get("rows") or []),
                "rows_extracted": len(table.get("rows") or []),
                "confidence": 0.99 if table.get("rows") else 0.0,
            }
            for table in tables
        ]
        overall_confidence = round(
            average(
                [
                    1.0 if fragments else 0.0,
                    1.0 if structured_blocks else 0.0,
                    1.0 if not tables or all(table.get("rows") for table in tables) else 0.6,
                ]
            ),
            3,
        )
        warnings = [
            {
                "code": "PDF_ONLY_REVIEW_MODE",
                "severity": "warning",
                "message": "Candidate inventory is derived from the PDF parsing engine only; XML remains secondary reference data.",
                "rule_id": "PDF_ONLY_REVIEW",
            }
        ]
        result = {
            "validation_id": f"pdf_only_{self._slugify(pdf_name)}",
            "contract": {
                "contract_id": self.contracts["pdf_contract"]["contract_id"],
                "contract_version": self.contracts["pdf_contract"]["contract_version"],
            },
            "document": {
                "doc_id": self._slugify(pdf_name),
                "paired_document_id": None,
                "paired_xml_doc_id": None,
                "pages_processed": extracted.pages_processed,
                "fragments_extracted": len(fragments),
                "tables_extracted": len(tables),
            },
            "overall_status": "PASS_WITH_WARNINGS" if fragments else "FAIL",
            "gate_decision": {
                "can_progress_to_semantic_layer": False,
                "blocked": False,
                "reason": "PDF-only workspace is review-only and does not promote canonical snippets.",
            },
            "confidence": {
                "overall": overall_confidence,
                "sources": {
                    "block_structure": 1.0 if structured_blocks else 0.0,
                    "table_structure": 1.0 if not tables or all(table.get("rows") for table in tables) else 0.6,
                    "xml_alignment": 0.0,
                    "metadata": 1.0 if structured_blocks else 0.0,
                },
            },
            "alignment_summary": {
                "aligned": 0,
                "unresolved": len(fragments),
                "average_confidence": 0.0,
            },
            "warnings": warnings,
            "errors": [] if fragments else [{"code": "NO_PDF_FRAGMENTS", "severity": "error", "message": "No PDF fragments were extracted."}],
            "rule_results": [
                {
                    "rule_id": "PDF_ONLY_REVIEW",
                    "status": "PASS_WITH_WARNINGS" if fragments else "FAIL",
                    "details": {
                        "structured_block_count": len(structured_blocks),
                        "assembled_clause_count": len(assembled_clauses),
                        "fragment_count": len(fragments),
                    },
                }
            ],
            "table_validation": table_validation,
            "trace_sample": [
                {
                    "fragment_id": fragment.fragment_id,
                    "page": fragment.page,
                    "bbox": fragment.bbox,
                }
                for fragment in fragments[:10]
            ],
        }
        return {
            "result": result,
            "metrics": {
                "pages_processed": extracted.pages_processed,
                "total_words": extracted.total_words,
                "structured_block_count": len(structured_blocks),
                "assembled_clause_count": len(assembled_clauses),
                "table_count": len(tables),
                "quality_score": overall_confidence,
                "runtime_mode": extracted.runtime_mode,
            },
            "fragments": fragments,
            "structured_blocks": structured_blocks,
            "assembled_clauses": assembled_clauses,
            "tables": tables,
            "alignments": [],
            "strategy": self._serialize_strategy(strategy, extracted),
            "parity_scaffold": {
                "mode": "pdf_only",
                "summary": {
                    "parity_mode": "pdf_only_review",
                    "alignment_count": 0,
                    "fragment_count": len(fragments),
                },
            },
        }

    def _validate_xml(self, xml_bytes: bytes, xml_name: str) -> dict[str, Any]:
        contract = self.contracts["xml_contract"]
        metrics: dict[str, Any] = {
            "is_well_formed": False,
            "encoding_valid": True,
            "root_element": None,
            "schema_family_id": None,
            "schema_family_confidence": 0.0,
            "schema_match_reasons": [],
            "schema_approved": False,
            "schema_variant_detected": False,
            "unknown_schema_family": False,
            "schema_required_structure_missing": False,
            "schema_parser_profile": None,
            "schema_family_version": None,
            "schema_registry_version": None,
            "schema_normalizer_version": None,
            "schema_recheck_status": "fresh",
            "schema_runtime": {},
            "metadata": {"edition": None, "amendment": None, "volume": None, "section": None, "part": None},
            "context_not_applicable": False,
            "invalid_parent_child_links": 0,
            "impossible_nesting_count": 0,
            "orphaned_structural_nodes": 0,
            "duplicate_ids": 0,
            "empty_required_nodes": 0,
            "unresolved_references": 0,
            "definition_link_failures": 0,
            "table_structure_issues": 0,
            "snippet_readiness": False,
            "traceability_metadata_complete": False,
            "quality_score": 0.0,
            "nodes_processed": 0,
            "table_count": 0,
            "warnings": [],
            "errors": [],
        }

        xml_nodes: list[XmlNode] = []
        semantic_units: list[dict[str, Any]] = []
        trace_sample: list[dict[str, Any]] = []

        try:
            root = ET.fromstring(xml_bytes)
            metrics["is_well_formed"] = True
            metrics["root_element"] = root.tag.split("}")[-1]
        except ET.ParseError as exc:
            result = self._build_xml_result(
                contract=contract,
                xml_name=xml_name,
                metrics=metrics,
                rule_results=[
                    {
                        "rule_id": "X1_XML_WELL_FORMED",
                        "status": "FAIL",
                        "details": {"error": str(exc)},
                    }
                ],
                warnings=[],
                errors=[
                    {
                        "code": "SCHEMA_ERROR",
                        "severity": "error",
                        "message": f"XML parse failure: {exc}",
                        "rule_id": "X1_XML_WELL_FORMED",
                    }
                ],
                validation_trace=[
                    {"step": "xml_loaded", "status": "FAIL"},
                ],
                xml_nodes=[],
                overall_status="BLOCKED",
                can_progress=False,
                blocked=True,
                reason="XML is not well formed.",
            )
            validate_payload("xml_result_schema", result)
            return {"result": result, "metrics": metrics, "xml_nodes": xml_nodes, "semantic_units": semantic_units}

        parent_map = self._xml_parent_map(root)
        schema_match = self._detect_xml_schema_family(root)
        metrics["schema_family_id"] = schema_match["schema_family_id"]
        metrics["schema_family_confidence"] = schema_match["schema_match_confidence"]
        metrics["schema_match_reasons"] = schema_match["schema_match_reasons"]
        metrics["schema_approved"] = schema_match["schema_approved"]
        metrics["schema_variant_detected"] = schema_match["schema_variant_detected"]
        metrics["unknown_schema_family"] = schema_match["unknown_schema_family"]
        metrics["schema_required_structure_missing"] = schema_match["required_structure_missing"]
        metrics["schema_parser_profile"] = schema_match["parser_profile"]
        metrics["schema_family_version"] = schema_match.get("schema_family_version")
        metrics["schema_registry_version"] = schema_match.get("registry_version")
        metrics["schema_normalizer_version"] = schema_match.get("normalizer_version")
        metrics["schema_runtime"] = dict(schema_match)

        all_elements = list(root.iter())
        metrics["nodes_processed"] = len(all_elements)

        ids: list[str] = []
        id_counts: dict[str, int] = defaultdict(int)
        references: list[str] = []
        empty_required_nodes = 0
        table_issues = 0
        table_count = 0

        for element in all_elements:
            element_id = element.attrib.get("id") or element.attrib.get("{http://www.w3.org/XML/1998/namespace}id")
            if element_id:
                ids.append(element_id)
                id_counts[element_id] += 1

            tag_name = self._element_tag_name(element)
            text_value = self._inventory_text_for_element(element)

            if tag_name in {"table", "tbody", "thead"}:
                table_count += 1 if tag_name == "table" else 0
                if tag_name == "table" and not text_value:
                    table_issues += 1

            if tag_name in {"heading", "title", "clause", "section", "part", "table"} and not text_value:
                empty_required_nodes += 1

            for key in ("ref", "href", "target", "rid"):
                value = element.attrib.get(key)
                if value:
                    target = self._extract_local_reference_target(key, value)
                    if target:
                        references.append(target)

            node_path = self._element_path(element)

            emit_inventory = not self._should_skip_inventory_for_element(element, parent_map)
            semantic_node_id = self._semantic_node_id(
                element=element,
                fallback_path=node_path,
                text=text_value,
            )
            context_descriptor = (
                self._build_xml_context_descriptor(
                    node_id=semantic_node_id,
                    element=element,
                    parent_map=parent_map,
                )
                if semantic_node_id
                else None
            )
            if emit_inventory and semantic_node_id:
                semantic_unit = self._semantic_unit_from_element(
                    element=element,
                    node_id=semantic_node_id,
                    path=node_path,
                    text=text_value,
                    context_descriptor=context_descriptor,
                )
                if semantic_unit is not None:
                    semantic_units.append(semantic_unit)

            should_emit_xml_node = emit_inventory and (
                len(text_value) >= 20 or self._is_glossary_entry_element(element)
            )
            if element_id and should_emit_xml_node:
                xml_nodes.append(
                    XmlNode(
                        node_id=element_id,
                        clause_id=element_id,
                        text=text_value,
                        path=node_path,
                        context_descriptor=context_descriptor,
                    )
                )
                if len(trace_sample) < 5:
                    trace_sample.append(
                        {
                            "node_id": element_id,
                            "clause_id": element_id,
                            "status": "PASS",
                            "xml_path": node_path,
                            "notes": text_value[:120],
                        }
                    )

        xml_nodes.extend(self._table_row_xml_nodes(root, parent_map))
        semantic_units.extend(self._semantic_units_from_xml_nodes(xml_nodes))
        semantic_units = self._dedupe_semantic_units(semantic_units)

        metrics["duplicate_ids"] = sum(count - 1 for count in id_counts.values() if count > 1)
        metrics.update(self._hierarchy_metrics(root, parent_map))
        metrics["empty_required_nodes"] = empty_required_nodes
        metrics["unresolved_references"] = sum(1 for ref in references if ref not in id_counts)
        metrics["definition_link_failures"] = self._definition_link_failures(root, parent_map, set(id_counts))
        metrics["table_structure_issues"] = table_issues
        metrics["table_count"] = table_count

        metadata = self._extract_xml_metadata(root, xml_name)
        metrics["metadata"] = metadata
        metrics["snippet_readiness"] = bool(xml_nodes) and metrics["duplicate_ids"] == 0
        metrics["traceability_metadata_complete"] = all(node.node_id and node.clause_id for node in xml_nodes[:25])

        metadata_ok = all([metadata["edition"], metadata["amendment"], metadata["volume"]]) and (
            metadata["section"] is not None or metadata["part"] is not None or metrics["context_not_applicable"]
        )
        hierarchy_ok = (
            metrics["invalid_parent_child_links"] == 0
            and metrics["impossible_nesting_count"] == 0
            and metrics["orphaned_structural_nodes"] == 0
        )
        references_score = 1.0 if metrics["unresolved_references"] == 0 else max(0.0, 1.0 - (metrics["unresolved_references"] / 10))
        tables_score = 1.0 if metrics["table_structure_issues"] == 0 else max(0.0, 1.0 - (metrics["table_structure_issues"] / 5))
        metrics["quality_score"] = round(
            average(
                [
                    1.0 if metrics["is_well_formed"] else 0.0,
                    1.0 if metadata_ok else 0.0,
                    1.0 if hierarchy_ok else 0.0,
                    references_score,
                    tables_score,
                    1.0 if metrics["snippet_readiness"] else 0.0,
                ]
            ),
            3,
        )

        rule_results: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        validation_trace = [{"step": "xml_loaded", "status": "PASS"}]
        schema_rule_status = "PASS"
        if metrics["schema_required_structure_missing"]:
            schema_rule_status = "FAIL"
            errors.append(
                {
                    "code": "XML_SCHEMA_REQUIRED_STRUCTURE",
                    "severity": "error",
                    "message": "XML matched a known schema family but is missing required structural elements.",
                    "rule_id": "X0_SCHEMA_FAMILY_MATCH",
                }
            )
            validation_trace.append({"step": "schema_family_detected", "status": "FAIL"})
        elif metrics["unknown_schema_family"]:
            schema_rule_status = "PASS_WITH_WARNINGS"
            warnings.append(
                {
                    "code": "XML_SCHEMA_UNKNOWN",
                    "severity": "warning",
                    "message": "XML did not match an approved schema family and requires review before parser dispatch.",
                    "rule_id": "X0_SCHEMA_FAMILY_MATCH",
                }
            )
            validation_trace.append({"step": "schema_family_detected", "status": "PASS_WITH_WARNINGS"})
        elif metrics["schema_variant_detected"]:
            schema_rule_status = "PASS_WITH_WARNINGS"
            warnings.append(
                {
                    "code": "XML_SCHEMA_VARIANT",
                    "severity": "warning",
                    "message": "XML matched an approved schema family but drifted from the preferred structural shape.",
                    "rule_id": "X0_SCHEMA_FAMILY_MATCH",
                }
            )
            validation_trace.append({"step": "schema_family_detected", "status": "PASS_WITH_WARNINGS"})
        else:
            validation_trace.append({"step": "schema_family_detected", "status": "PASS"})

        thresholds = contract["thresholds"]

        def add_rule(rule_id: str, status: str, details: dict[str, Any], warning: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
            rule_results.append({"rule_id": rule_id, "status": status, "details": details})
            if warning:
                warnings.append(warning)
            if error:
                errors.append(error)

        rule_results.append(
            {
                "rule_id": "X0_SCHEMA_FAMILY_MATCH",
                "status": schema_rule_status,
                "details": {
                    "schema_family_id": metrics["schema_family_id"],
                    "schema_approved": metrics["schema_approved"],
                    "schema_variant_detected": metrics["schema_variant_detected"],
                    "unknown_schema_family": metrics["unknown_schema_family"],
                    "required_structure_missing": metrics["schema_required_structure_missing"],
                    "parser_profile": metrics["schema_parser_profile"],
                    "match_confidence": metrics["schema_family_confidence"],
                    "match_reasons": metrics["schema_match_reasons"],
                },
            }
        )

        add_rule(
            "X1_XML_WELL_FORMED",
            "PASS" if metrics["is_well_formed"] and metrics["root_element"] in thresholds["expected_root_elements"] else "FAIL",
            {
                "root_element": metrics["root_element"],
                "encoding_valid": metrics["encoding_valid"],
                "well_formed": metrics["is_well_formed"],
            },
            error=None
            if metrics["is_well_formed"] and metrics["root_element"] in thresholds["expected_root_elements"]
            else {
                "code": "SCHEMA_ERROR",
                "severity": "error",
                "message": "XML is not well formed or uses an unexpected root element.",
                "rule_id": "X1_XML_WELL_FORMED",
            },
        )
        add_rule(
            "X2_REQUIRED_METADATA",
            "PASS" if metadata_ok else "FAIL",
            metadata,
            error=None
            if metadata_ok
            else {
                "code": "SOURCE_MISMATCH",
                "severity": "error",
                "message": "Required XML metadata is incomplete.",
                "rule_id": "X2_REQUIRED_METADATA",
            },
        )
        add_rule(
            "X3_HIERARCHY_INTEGRITY",
            "PASS" if hierarchy_ok else "FAIL",
            {
                "invalid_parent_child_links": metrics["invalid_parent_child_links"],
                "impossible_nesting_count": metrics["impossible_nesting_count"],
                "orphaned_structural_nodes": metrics["orphaned_structural_nodes"],
            },
            error=None
            if hierarchy_ok
            else {
                "code": "SCHEMA_ERROR",
                "severity": "error",
                "message": "Hierarchy integrity checks failed.",
                "rule_id": "X3_HIERARCHY_INTEGRITY",
            },
        )
        add_rule(
            "X4_UNIQUE_IDS",
            "PASS" if metrics["duplicate_ids"] == 0 else "FAIL",
            {"duplicate_ids": metrics["duplicate_ids"]},
            error=None
            if metrics["duplicate_ids"] == 0
            else {
                "code": "SCHEMA_ERROR",
                "severity": "error",
                "message": "Duplicate XML ids were found.",
                "rule_id": "X4_UNIQUE_IDS",
            },
        )

        if metrics["empty_required_nodes"] == 0:
            x5_status = "PASS"
        elif metrics["empty_required_nodes"] <= thresholds["max_empty_required_nodes_for_review"]:
            x5_status = "PASS_WITH_WARNINGS"
            warnings.append(
                {
                    "code": "EMPTY_REQUIRED_NODES",
                    "severity": "warning",
                    "message": f"{metrics['empty_required_nodes']} required nodes are empty.",
                    "rule_id": "X5_CONTENT_PRESENCE",
                }
            )
        else:
            x5_status = "FAIL"
            errors.append(
                {
                    "code": "SOURCE_MISMATCH",
                    "severity": "error",
                    "message": "Empty required XML nodes exceed the configured review threshold.",
                    "rule_id": "X5_CONTENT_PRESENCE",
                }
            )
        rule_results.append(
            {
                "rule_id": "X5_CONTENT_PRESENCE",
                "status": x5_status,
                "details": {"empty_required_nodes": metrics["empty_required_nodes"]},
            }
        )

        if metrics["unresolved_references"] == 0:
            x6_status = "PASS"
        elif metrics["unresolved_references"] <= thresholds["max_unresolved_references_for_warning"]:
            x6_status = "PASS_WITH_WARNINGS"
            warnings.append(
                {
                    "code": "UNRESOLVED_REFERENCE",
                    "severity": "warning",
                    "message": f"{metrics['unresolved_references']} XML references could not be resolved.",
                    "rule_id": "X6_REFERENCE_RESOLUTION",
                }
            )
        else:
            x6_status = "FAIL"
            errors.append(
                {
                    "code": "UNRESOLVED_REFERENCE",
                    "severity": "error",
                    "message": "Unresolved XML references exceed the configured threshold.",
                    "rule_id": "X6_REFERENCE_RESOLUTION",
                }
            )
        rule_results.append(
            {
                "rule_id": "X6_REFERENCE_RESOLUTION",
                "status": x6_status,
                "details": {"unresolved_references": metrics["unresolved_references"]},
            }
        )

        if metrics["definition_link_failures"] == 0:
            x7_status = "PASS"
        elif metrics["definition_link_failures"] <= thresholds["max_definition_link_failures_for_warning"]:
            x7_status = "PASS_WITH_WARNINGS"
            warnings.append(
                {
                    "code": "DEFINITION_LINK_WARNING",
                    "severity": "warning",
                    "message": f"{metrics['definition_link_failures']} definition links could not be resolved.",
                    "rule_id": "X7_DEFINITION_STRUCTURE",
                }
            )
        else:
            x7_status = "FAIL"
            errors.append(
                {
                    "code": "UNRESOLVED_REFERENCE",
                    "severity": "error",
                    "message": "Definition link failures exceed the configured threshold.",
                    "rule_id": "X7_DEFINITION_STRUCTURE",
                }
            )
        rule_results.append(
            {
                "rule_id": "X7_DEFINITION_STRUCTURE",
                "status": x7_status,
                "details": {"definition_link_failures": metrics["definition_link_failures"]},
            }
        )

        if metrics["table_structure_issues"] == 0:
            x8_status = "PASS"
        elif metrics["table_structure_issues"] <= thresholds["max_table_structure_issues_for_review"]:
            x8_status = "PASS_WITH_WARNINGS"
            warnings.append(
                {
                    "code": "TABLE_INCONSISTENCY",
                    "severity": "warning",
                    "message": f"{metrics['table_structure_issues']} XML table structure issues were found.",
                    "rule_id": "X8_TABLE_STRUCTURE",
                }
            )
        else:
            x8_status = "FAIL"
            errors.append(
                {
                    "code": "TABLE_INCONSISTENCY",
                    "severity": "error",
                    "message": "XML table structure issues exceed the configured review threshold.",
                    "rule_id": "X8_TABLE_STRUCTURE",
                }
            )
        rule_results.append(
            {
                "rule_id": "X8_TABLE_STRUCTURE",
                "status": x8_status,
                "details": {"table_structure_issues": metrics["table_structure_issues"]},
            }
        )

        add_rule(
            "X9_SNIPPET_READINESS",
            "PASS" if metrics["snippet_readiness"] and metrics["traceability_metadata_complete"] else "FAIL",
            {
                "snippet_readiness": metrics["snippet_readiness"],
                "traceability_metadata_complete": metrics["traceability_metadata_complete"],
            },
            error=None
            if metrics["snippet_readiness"] and metrics["traceability_metadata_complete"]
            else {
                "code": "EXECUTION_BLOCKED",
                "severity": "error",
                "message": "XML is not ready for canonical snippet generation.",
                "rule_id": "X9_SNIPPET_READINESS",
            },
        )
        add_rule(
            "X10_QUALITY_SCORE",
            "PASS" if metrics["quality_score"] >= thresholds["min_quality_score"] else "FAIL",
            {
                "score": metrics["quality_score"],
                "threshold": thresholds["min_quality_score"],
            },
            error=None
            if metrics["quality_score"] >= thresholds["min_quality_score"]
            else {
                "code": "EXECUTION_BLOCKED",
                "severity": "error",
                "message": "XML quality score is below threshold.",
                "rule_id": "X10_QUALITY_SCORE",
            },
        )

        overall_status, can_progress, blocked, reason = self._derive_status(
            errors=errors,
            warnings=warnings,
            quality_score=metrics["quality_score"],
            min_quality=thresholds["min_quality_score"],
            review_required=(
                bool(metrics["unknown_schema_family"])
                or bool(metrics["schema_variant_detected"])
                or 0 < metrics["empty_required_nodes"] <= thresholds["max_empty_required_nodes_for_review"]
                or 0 < metrics["table_structure_issues"] <= thresholds["max_table_structure_issues_for_review"]
            ),
            progression_target="alignment",
        )

        validation_trace.extend(
            [
                {"step": "metadata_validated", "status": "PASS" if metadata_ok else "FAIL"},
                {"step": "hierarchy_validated", "status": "PASS" if hierarchy_ok else "FAIL"},
                {
                    "step": "reference_validation",
                    "status": "PASS" if x6_status == "PASS" else ("PASS_WITH_WARNINGS" if x6_status == "PASS_WITH_WARNINGS" else "FAIL"),
                },
                {
                    "step": "snippet_readiness_validated",
                    "status": "PASS" if metrics["snippet_readiness"] and metrics["traceability_metadata_complete"] else "FAIL",
                },
            ]
        )

        result = self._build_xml_result(
            contract=contract,
            xml_name=xml_name,
            metrics=metrics,
            rule_results=rule_results,
            warnings=warnings,
            errors=errors,
            validation_trace=validation_trace,
            xml_nodes=xml_nodes,
            overall_status=overall_status,
            can_progress=can_progress,
            blocked=blocked,
            reason=reason,
            trace_sample=trace_sample,
        )
        validate_payload("xml_result_schema", result)
        return {
            "result": result,
            "metrics": metrics,
            "xml_nodes": xml_nodes,
            "semantic_units": semantic_units,
        }

    def _validate_pdf(
        self,
        pdf_bytes: bytes,
        pdf_name: str,
        xml_context: dict[str, Any],
        strategy: DocumentStrategyDecision,
    ) -> dict[str, Any]:
        contract = self.contracts["pdf_contract"]
        thresholds = contract["thresholds"]
        xml_result = xml_context["result"]
        xml_nodes: list[XmlNode] = xml_context["xml_nodes"]
        xml_metrics = xml_context.get("metrics", {})

        extracted = self._extract_pdf(pdf_bytes, strategy)
        scoped_blocks, scoped_tables = self._scope_extracted_pdf_for_xml(
            extracted.blocks,
            extracted.tables,
            xml_nodes,
            xml_metrics,
        )
        fragments = self._fragments_from_blocks(scoped_blocks, scoped_tables)
        page_count = extracted.pages_processed
        total_words = extracted.total_words
        text_based_ratio = 1.0 if page_count and total_words > 0 else 0.0
        line_texts = [fragment.text for fragment in fragments if fragment.text]
        split_scope = strategy.extraction_profile.expected_split_scope
        is_split = bool(page_count)

        alignments = [self._align_fragment(fragment, xml_nodes) for fragment in fragments]
        aligned = [item for item in alignments if item["matched"]]
        unresolved = [item for item in alignments if not item["matched"]]
        low_confidence = [item for item in aligned if item["confidence"] < thresholds["preferred_alignment_confidence"]]

        missing_fragment_id = len([fragment for fragment in fragments if not fragment.fragment_id])
        missing_clause_metadata = missing_fragment_id
        missing_traceability_metadata = len(
            [
                block
                for block in scoped_blocks
                if not block.block_id or not block.source_strategy or len(block.bbox) != 4
            ]
        )
        invalid_tables = len([table for table in scoped_tables if not table.rows or not any(row for row in table.rows if any(row))])
        missing_headers = len(
            [
                table
                for table in scoped_tables
                if strategy.extraction_profile.require_table_headers and table.rows and not table.headers_present
            ]
        )
        empty_row_sets = invalid_tables
        table_validation = []
        for table in scoped_tables:
            rows_extracted = len(table.rows or [])
            table_confidence = 0.99 if rows_extracted > 0 else 0.0
            related_node = table.related_block_id
            validation_entry = {
                "table_id": table.table_id,
                "status": "PASS" if rows_extracted > 0 else "FAIL",
                "rows_expected": rows_extracted,
                "rows_extracted": rows_extracted,
                "confidence": round(table_confidence, 3),
            }
            if related_node:
                validation_entry["node_id"] = related_node
                validation_entry["related_xml_node"] = related_node
            table_validation.append(validation_entry)

        alignment_avg = average([item["confidence"] for item in aligned]) if aligned else 0.0
        missing_bbox = len([block for block in scoped_blocks if len(block.bbox) != 4])
        untyped_fragments = len([block for block in scoped_blocks if not block.block_type])
        missing_page_reference = len([block for block in scoped_blocks if block.page <= 0])
        block_structure_score = 1.0 if fragments and missing_bbox == 0 and untyped_fragments == 0 and missing_page_reference == 0 else 0.0
        table_score = 1.0 if invalid_tables == 0 else max(0.0, 1.0 - invalid_tables / max(len(scoped_tables), 1))
        alignment_score = alignment_avg
        metadata_score = 1.0 if missing_clause_metadata == 0 and missing_traceability_metadata == 0 else max(
            0.0, 1.0 - ((missing_clause_metadata + missing_traceability_metadata) / max(len(fragments), 1))
        )
        overall_confidence = round(average([block_structure_score, table_score, alignment_score, metadata_score]), 3)
        parity_scaffold = self._build_parity_scaffold(strategy, fragments, alignments, xml_nodes)
        serialized_blocks = self._codify_block_styles([self._serialize_block(block) for block in scoped_blocks])
        serialized_tables = [self._serialize_extracted_table(table) for table in scoped_tables]
        assembled_clauses = self._build_assembled_clauses(serialized_blocks, alignments=alignments)

        rule_results: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        c1_pass = text_based_ratio >= thresholds["min_text_based_ratio"]
        rule_results.append(
            {
                "rule_id": "C1_PDF_QUALITY",
                "status": "PASS" if c1_pass else "FAIL",
                "details": {
                    "text_based_pdf_confirmed": c1_pass,
                    "text_based_ratio": round(text_based_ratio, 3),
                },
            }
        )
        if not c1_pass:
            errors.append(
                {
                    "code": "PDF_QUALITY_FAILURE",
                    "severity": "error",
                    "message": "PDF is not text-based enough for deterministic extraction.",
                    "rule_id": "C1_PDF_QUALITY",
                }
            )

        c2_pass = is_split and split_scope == "section"
        rule_results.append(
            {
                "rule_id": "C2_SPLITTING",
                "status": "PASS" if c2_pass else "FAIL",
                "details": {"is_split": is_split, "split_scope": split_scope},
            }
        )
        if not c2_pass:
            errors.append(
                {
                    "code": "SPLIT_FAILURE",
                    "severity": "error",
                    "message": "PDF is not split to section scope.",
                    "rule_id": "C2_SPLITTING",
                }
            )

        c3_pass = (
            bool(fragments)
            and missing_bbox == 0
            and untyped_fragments == 0
            and missing_page_reference == 0
            and missing_fragment_id == 0
        )
        rule_results.append(
            {
                "rule_id": "C3_BLOCK_STRUCTURE",
                "status": "PASS" if c3_pass else "FAIL",
                "details": {
                    "fragments_checked": len(fragments),
                    "missing_bbox": missing_bbox,
                    "untyped_fragments": untyped_fragments,
                    "missing_page_reference": missing_page_reference,
                    "missing_fragment_id": missing_fragment_id,
                    "block_types": sorted({block.block_type for block in scoped_blocks}),
                },
            }
        )
        if not c3_pass:
            errors.append(
                {
                    "code": "BLOCK_STRUCTURE_FAILURE",
                    "severity": "error",
                    "message": "PDF structured blocks are incomplete or unusable.",
                    "rule_id": "C3_BLOCK_STRUCTURE",
                }
            )

        c4_pass = invalid_tables == 0 and missing_headers == 0
        rule_results.append(
            {
                "rule_id": "C4_TABLE_STRUCTURE",
                "status": "PASS" if c4_pass else "FAIL",
                "details": {
                    "tables_checked": len(scoped_tables),
                    "invalid_tables": invalid_tables,
                    "missing_headers_where_expected": missing_headers,
                },
            }
        )
        if not c4_pass:
            errors.append(
                {
                    "code": "TABLE_INCONSISTENCY",
                    "severity": "error",
                    "message": "Extracted PDF tables are not structurally usable.",
                    "rule_id": "C4_TABLE_STRUCTURE",
                }
            )

        xml_gate_open = xml_result["gate_decision"]["can_progress_to_alignment_layer"]
        if (
            xml_gate_open
            and alignment_avg >= thresholds["preferred_alignment_confidence"]
            and len(unresolved) == 0
            and len(low_confidence) == 0
        ):
            c5_status = "PASS"
        elif (
            xml_gate_open
            and alignment_avg >= thresholds["min_alignment_confidence_for_warning"]
            and len(unresolved) <= thresholds["max_unresolved_alignments_for_warning"]
            and len(low_confidence) <= thresholds["max_low_confidence_alignments_for_warning"]
        ):
            c5_status = "PASS_WITH_WARNINGS"
            for item in low_confidence[:10]:
                warnings.append(
                    {
                        "code": "LOW_ALIGNMENT_CONFIDENCE",
                        "severity": "warning",
                        "rule_id": "C5_XML_ALIGNMENT",
                        "fragment_id": item["fragment_id"],
                        "node_id": item["node_id"],
                        "xml_node": item["node_id"],
                        "message": "Alignment confidence below preferred threshold.",
                        "confidence": round(item["confidence"], 3),
                    }
                )
        else:
            c5_status = "FAIL"
            errors.append(
                {
                    "code": "ALIGNMENT_FAILURE",
                    "severity": "error",
                    "message": "PDF to XML alignment did not meet the required thresholds.",
                    "rule_id": "C5_XML_ALIGNMENT",
                }
            )
        rule_results.append(
            {
                "rule_id": "C5_XML_ALIGNMENT",
                "status": c5_status,
                "details": {
                    "aligned_fragments": len(aligned),
                    "low_confidence": len(low_confidence),
                    "unresolved": len(unresolved),
                    "average_confidence": alignment_avg,
                    "xml_gate_open": xml_gate_open,
                },
            }
        )

        c6_pass = missing_clause_metadata == 0 and missing_traceability_metadata == 0
        rule_results.append(
            {
                "rule_id": "C6_METADATA",
                "status": "PASS" if c6_pass else "FAIL",
                "details": {
                    "missing_clause_metadata": missing_clause_metadata,
                    "missing_traceability_metadata": missing_traceability_metadata,
                },
            }
        )
        if not c6_pass:
            errors.append(
                {
                    "code": "METADATA_FAILURE",
                    "severity": "error",
                    "message": "Extracted fragments are missing traceability metadata.",
                    "rule_id": "C6_METADATA",
                }
            )

        c7_pass = overall_confidence >= thresholds["min_quality_score"]
        rule_results.append(
            {
                "rule_id": "C7_QUALITY_SCORE",
                "status": "PASS" if c7_pass else "FAIL",
                "details": {
                    "score": overall_confidence,
                    "threshold": thresholds["min_quality_score"],
                },
            }
        )
        if not c7_pass:
            errors.append(
                {
                    "code": "EXECUTION_BLOCKED",
                    "severity": "error",
                    "message": "Overall PDF quality score is below threshold.",
                    "rule_id": "C7_QUALITY_SCORE",
                }
            )

        overall_status, can_progress, blocked, reason = self._derive_status(
            errors=errors,
            warnings=warnings,
            quality_score=overall_confidence,
            min_quality=thresholds["min_quality_score"],
            review_required=self._should_require_review(
                strategy.review_policy,
                strategy,
                unresolved=unresolved,
                low_confidence=low_confidence,
                parity_scaffold=parity_scaffold,
                alignment_avg=alignment_avg,
            ),
            progression_target="semantic",
        )

        trace_sample = [
            {
                "fragment_id": item["fragment_id"],
                "node_id": item["node_id"],
                "xml_node": item["node_id"],
                "page": item["page"],
                "bbox": item["bbox"],
                "confidence": round(item["confidence"], 3),
            }
            for item in aligned[:10]
        ]

        result = {
            "validation_id": f"val_{self._slugify(pdf_name)}",
            "contract": {
                "contract_id": contract["contract_id"],
                "contract_version": contract["contract_version"],
            },
            "document": {
                "doc_id": self._slugify(pdf_name),
                "paired_document_id": xml_result["document"]["doc_id"],
                "paired_xml_doc_id": xml_result["document"]["doc_id"],
                "pages_processed": page_count,
                "fragments_extracted": len(fragments),
                "tables_extracted": len(scoped_tables),
            },
            "overall_status": overall_status,
            "gate_decision": {
                "can_progress_to_semantic_layer": can_progress,
                "blocked": blocked,
                "reason": reason,
            },
            "confidence": {
                "overall": overall_confidence,
                "sources": {
                    "block_structure": round(block_structure_score, 3),
                    "table_structure": round(table_score, 3),
                    "xml_alignment": round(alignment_score, 3),
                    "metadata": round(metadata_score, 3),
                },
            },
            "rule_results": rule_results,
            "table_validation": table_validation,
            "alignment_summary": {
                "total_fragments": len(fragments),
                "aligned": len(aligned),
                "unresolved": len(unresolved),
                "low_confidence": len(low_confidence),
                "average_confidence": alignment_avg,
            },
            "warnings": warnings,
            "errors": errors,
            "validation_trace": [
                {"step": "pdf_loaded", "status": "PASS" if page_count else "FAIL"},
                {"step": "block_extraction_validated", "status": "PASS" if c3_pass else "FAIL"},
                {"step": "table_structure_validated", "status": "PASS" if c4_pass else "FAIL"},
                {
                    "step": "xml_alignment_validated",
                    "status": "PASS" if c5_status == "PASS" else ("PASS_WITH_WARNINGS" if c5_status == "PASS_WITH_WARNINGS" else "FAIL"),
                },
            ],
            "trace_sample": trace_sample,
            "approval": {
                "approved": can_progress,
                "approved_by_type": "system",
                "approved_by_id": "validation_engine",
                "approved_at": utc_now_iso(),
            },
        }
        validate_payload("pdf_result_schema", result)
        return {
            "result": result,
            "metrics": {
                "text_based_ratio": round(text_based_ratio, 3),
                "total_words": total_words,
                "line_count": len(line_texts),
                "aligned": len(aligned),
                "unresolved": len(unresolved),
                "quality_score": overall_confidence,
                "runtime_mode": extracted.runtime_mode,
            },
            "fragments": fragments,
            "structured_blocks": serialized_blocks,
            "assembled_clauses": assembled_clauses,
            "tables": serialized_tables,
            "alignments": alignments,
            "strategy": self._serialize_strategy(strategy, extracted),
            "parity_scaffold": parity_scaffold,
        }

    def _extract_pdf(self, pdf_bytes: bytes, strategy: DocumentStrategyDecision) -> ExtractedPdf:
        extractor = self.extractors.get(strategy.extractor_strategy)
        if extractor is None:
            raise ValueError(f"Unsupported extractor strategy: {strategy.extractor_strategy}")
        return extractor.extract(pdf_bytes, decision=strategy)

    def _resolve_runtime_strategy(self, strategy: DocumentStrategyDecision) -> DocumentStrategyDecision:
        if strategy.extractor_strategy != "docling":
            return strategy

        extractor = self.extractors.get("docling")
        if isinstance(extractor, DoclingExtractor) and extractor.is_available():
            return strategy

        resolved_notes = [
            *strategy.notes,
            "docling_unavailable:fallback_to_pdfplumber",
            "runtime_extractor:pdfplumber",
        ]
        return replace(
            strategy,
            extractor_strategy="pdfplumber",
            extractor_options={},
            notes=resolved_notes,
        )

    def _fragments_from_blocks(
        self,
        blocks: list[StructuredBlock],
        tables: list[Any] | None = None,
    ) -> list[PdfFragment]:
        fragments = [
            PdfFragment(
                fragment_id=block.block_id,
                page=block.page,
                text=block.text,
                bbox=block.bbox,
            )
            for block in blocks
        ]
        if tables:
            fragments.extend(self._fragments_from_tables(tables))
        return fragments

    def _scope_extracted_pdf_for_xml(
        self,
        blocks: list[StructuredBlock],
        tables: list[Any],
        xml_nodes: list[XmlNode],
        xml_metrics: dict[str, Any],
    ) -> tuple[list[StructuredBlock], list[Any]]:
        if not self._should_scope_to_part_wrapper(blocks, xml_nodes, xml_metrics):
            return blocks, tables

        part_token = clean_text(str((xml_metrics.get("metadata") or {}).get("part") or ""))
        if not part_token:
            return blocks, tables

        start_index = self._part_heading_index(blocks, part_token)
        if start_index is None:
            return blocks, tables
        end_index = self._part_intro_end_index(blocks, part_token, start_index)
        scoped_blocks = blocks[start_index:end_index]
        if not scoped_blocks:
            return blocks, tables
        scoped_pages = {block.page for block in scoped_blocks}
        scoped_tables = [table for table in tables if int((table.metadata or {}).get("page") or 0) in scoped_pages]
        return scoped_blocks, scoped_tables

    def _should_scope_to_part_wrapper(
        self,
        blocks: list[StructuredBlock],
        xml_nodes: list[XmlNode],
        xml_metrics: dict[str, Any],
    ) -> bool:
        if not blocks or not xml_nodes:
            return False
        if (xml_metrics.get("root_element") or "").lower() != "part":
            return False
        wrapper_paths = {"/part[", "/title[", "/intro-part[", "/callout[", "/li[", "/xref["}
        if not all(any(path in node.path for path in wrapper_paths) for node in xml_nodes):
            return False
        return True

    def _part_heading_index(self, blocks: list[StructuredBlock], part_token: str) -> int | None:
        normalized_part = normalize_text(part_token)
        for index, block in enumerate(blocks):
            text = normalize_text(block.text)
            if f"part {normalized_part}" in text and (
                block.block_type == "heading" or self._looks_like_structural_document_heading(block.text)
            ):
                return index
        return None

    def _part_intro_end_index(self, blocks: list[StructuredBlock], part_token: str, start_index: int) -> int:
        clause_pattern = re.compile(rf"\b(?:[a-z]{{2,4}}\s+)?{re.escape(normalize_text(part_token))}[a-z0-9]+", re.IGNORECASE)
        for index in range(start_index + 1, len(blocks)):
            block = blocks[index]
            if block.block_type != "heading":
                continue
            normalized_text = normalize_text(block.text)
            if clause_pattern.search(normalized_text) and f"part {normalize_text(part_token)}" not in normalized_text:
                return index
        return len(blocks)

    def _fragments_from_tables(self, tables: list[Any]) -> list[PdfFragment]:
        fragments: list[PdfFragment] = []
        for table in tables:
            row_groups = self._table_row_groups(table.rows, table.headers_present)
            if not row_groups:
                continue
            page = max(int((table.metadata or {}).get("page") or 1), 1)
            for row_index, row_group in enumerate(row_groups, start=1):
                row_text = self._table_row_fragment_text(table, row_group["headers"], row_group["values"])
                if len(row_text) < TABLE_ROW_FRAGMENT_MIN_TEXT_LENGTH:
                    continue
                fragments.append(
                    PdfFragment(
                        fragment_id=f"{table.table_id}__row_{row_index}",
                        page=page,
                        text=row_text,
                        bbox=self._table_row_fragment_bbox(
                            table.bbox,
                            row_index=row_index,
                            row_count=len(row_groups),
                            has_header=bool(row_group["headers"]),
                        ),
                    )
                )
        return fragments

    def _table_row_groups(
        self,
        rows: list[list[str]],
        headers_present: bool,
    ) -> list[dict[str, list[str]]]:
        normalized_rows = [
            [clean_text(cell) for cell in row]
            for row in rows
            if any(clean_text(cell) for cell in row)
        ]
        if not normalized_rows:
            return []

        if headers_present and len(normalized_rows) >= 2:
            headers = normalized_rows[0]
            body_rows = normalized_rows[1:]
        else:
            headers = []
            body_rows = normalized_rows

        grouped_rows: list[dict[str, list[str]]] = []
        for row in body_rows:
            values = row[:]
            if not any(values):
                continue
            grouped_rows.append({"headers": headers, "values": values})
        return grouped_rows

    def _table_row_fragment_text(
        self,
        table: Any,
        headers: list[str],
        values: list[str],
    ) -> str:
        metadata = table.metadata or {}
        prefix_parts = [clean_text(str(metadata.get("caption_text") or ""))]
        labeled_values: list[str] = []
        for index, value in enumerate(values):
            if not value:
                continue
            header = headers[index] if index < len(headers) and headers[index] else ""
            if header:
                labeled_values.append(f"{header}: {value}")
            elif len(values) == 2 and index == 1 and values[0]:
                labeled_values.append(f"{values[0]}: {value}")
            else:
                labeled_values.append(value)
        prefix_parts.extend(labeled_values)
        return clean_text(" ".join(part for part in prefix_parts if part))

    def _table_row_fragment_bbox(
        self,
        bbox: list[float] | None,
        *,
        row_index: int,
        row_count: int,
        has_header: bool,
    ) -> list[float]:
        if not bbox or len(bbox) != 4 or row_count <= 0:
            return [0.0, 0.0, 0.0, 0.0]
        x0, top, x1, bottom = bbox
        total_visual_rows = row_count + (1 if has_header else 0)
        visual_row_index = row_index + (1 if has_header else 0)
        row_height = (bottom - top) / max(total_visual_rows, 1)
        row_top = top + ((visual_row_index - 1) * row_height)
        row_bottom = min(bottom, row_top + row_height)
        return [
            round(float(x0), 2),
            round(float(row_top), 2),
            round(float(x1), 2),
            round(float(row_bottom), 2),
        ]

    def _serialize_block(self, block: StructuredBlock) -> dict[str, Any]:
        return {
            "block_id": block.block_id,
            "page": block.page,
            "bbox": block.bbox,
            "block_type": block.block_type,
            "text": block.text,
            "table_id": block.table_id,
            "section_hint": block.section_hint,
            "heading_level": block.heading_level,
            "source_strategy": block.source_strategy,
            "metadata": block.metadata,
        }

    def _serialize_extracted_table(self, table: ExtractedTable) -> dict[str, Any]:
        return {
            "table_id": table.table_id,
            "rows": table.rows,
            "headers_present": table.headers_present,
            "related_block_id": table.related_block_id,
            "bbox": table.bbox or [],
            "metadata": table.metadata,
        }

    def _codify_block_styles(self, structured_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not structured_blocks:
            return []

        page_body_font_sizes: dict[int, list[float]] = defaultdict(list)
        page_all_font_sizes: dict[int, list[float]] = defaultdict(list)
        page_frame_repetitions: dict[tuple[str, str], int] = defaultdict(int)

        for block in structured_blocks:
            if not isinstance(block, dict):
                continue
            metadata = block.get("metadata", {}) if isinstance(block.get("metadata"), dict) else {}
            style_summary = metadata.get("style_summary") if isinstance(metadata.get("style_summary"), dict) else {}
            try:
                font_size = float(style_summary.get("font_size_pt") or 0.0)
            except (TypeError, ValueError):
                font_size = 0.0
            page = int(block.get("page") or 0)
            if font_size > 0 and page > 0:
                page_all_font_sizes[page].append(font_size)
                if str(metadata.get("page_band") or "body") == "body":
                    page_body_font_sizes[page].append(font_size)
            page_band = str(metadata.get("page_band") or "body")
            normalized_text = clean_text(str(metadata.get("page_frame_normalized_text") or ""))
            if page_band in {"header", "footer"} and normalized_text:
                page_frame_repetitions[(page_band, normalized_text)] += 1

        codified_blocks: list[dict[str, Any]] = []
        for block in structured_blocks:
            next_block = dict(block)
            metadata = dict(next_block.get("metadata") or {})
            style_summary = metadata.get("style_summary") if isinstance(metadata.get("style_summary"), dict) else {}
            text = clean_text(str(next_block.get("text") or ""))
            page = int(next_block.get("page") or 0)
            page_band = str(metadata.get("page_band") or "body")
            normalized_text = clean_text(str(metadata.get("page_frame_normalized_text") or ""))
            body_median = median(page_body_font_sizes.get(page) or page_all_font_sizes.get(page) or [])
            try:
                font_size = float(style_summary.get("font_size_pt") or 0.0)
            except (TypeError, ValueError):
                font_size = 0.0
            relative_font_size = round(font_size / body_median, 3) if font_size > 0 and body_median > 0 else None
            emphasized = bool(style_summary.get("is_bold") or style_summary.get("is_italic"))
            structural_match = _DOCUMENT_HEADING_PATTERN.match(text)
            structural_heading_kind = structural_match.group(1).lower() if structural_match else None
            title_case_words = re.findall(r"[A-Z][A-Za-z0-9'-]*", text)
            heading_like = bool(
                structural_heading_kind
                or emphasized
                or (relative_font_size is not None and relative_font_size >= 1.08)
                or (len(title_case_words) >= 2 and len(text) <= 120 and not text.endswith((".", ";")))
            )
            repeated_band_count = (
                page_frame_repetitions.get((page_band, normalized_text), 0)
                if page_band in {"header", "footer"} and normalized_text
                else 0
            )
            likely_running_chrome = bool(
                page_band in {"header", "footer"}
                and repeated_band_count >= 2
                and not structural_heading_kind
                and not emphasized
                and (relative_font_size is None or relative_font_size <= 1.08)
            )
            page_frame_exempt = bool(
                structural_heading_kind
                and not likely_running_chrome
                and (
                    heading_like
                    or page_band == "body"
                    or (relative_font_size is not None and relative_font_size >= 1.12)
                )
            )
            _, structural_heading_text, structural_heading_title = self._split_document_heading(text)
            metadata["style_codification"] = {
                "font_size_pt": round(font_size, 3) if font_size > 0 else None,
                "body_median_font_size_pt": body_median or None,
                "relative_font_size": relative_font_size,
                "is_emphasized": emphasized,
                "heading_like": heading_like,
                "page_band": page_band,
                "repeated_page_frame_count": repeated_band_count or None,
                "likely_running_chrome": likely_running_chrome,
                "page_frame_exempt": page_frame_exempt,
                "structural_heading_kind": structural_heading_kind,
                "structural_heading_text": structural_heading_text,
                "structural_heading_title": structural_heading_title,
            }
            next_block["metadata"] = metadata
            codified_blocks.append(next_block)
        return codified_blocks

    def _build_docling_view(
        self,
        *,
        structured_blocks: list[dict[str, Any]],
        tables: list[dict[str, Any]],
        assembled_clauses: list[dict[str, Any]],
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        page_index: dict[int, dict[str, Any]] = {}

        for block in structured_blocks:
            page = int(block.get("page") or 0)
            if page <= 0:
                continue
            page_entry = page_index.setdefault(
                page,
                {
                    "page": page,
                    "block_ids": [],
                    "table_ids": [],
                    "block_types": [],
                },
            )
            block_id = str(block.get("block_id") or "")
            if block_id:
                page_entry["block_ids"].append(block_id)
            block_type = str(block.get("block_type") or "")
            if block_type and block_type not in page_entry["block_types"]:
                page_entry["block_types"].append(block_type)

        for table in tables:
            metadata = table.get("metadata", {}) if isinstance(table.get("metadata"), dict) else {}
            page = int(metadata.get("page") or 0)
            if page <= 0:
                continue
            page_entry = page_index.setdefault(
                page,
                {
                    "page": page,
                    "block_ids": [],
                    "table_ids": [],
                    "block_types": [],
                },
            )
            table_id = str(table.get("table_id") or "")
            if table_id:
                page_entry["table_ids"].append(table_id)

        pages = [
            {
                "page": page,
                "block_count": len(entry["block_ids"]),
                "table_count": len(entry["table_ids"]),
                "block_types": entry["block_types"],
                "block_ids": entry["block_ids"],
                "table_ids": entry["table_ids"],
            }
            for page, entry in sorted(page_index.items())
        ]

        return {
            "blocks": structured_blocks,
            "tables": tables,
            "assembled_clauses": assembled_clauses,
            "strategy": strategy,
            "page_index": pages,
        }

    def _build_assembled_clauses(
        self,
        structured_blocks: list[dict[str, Any]],
        *,
        alignments: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        structured_blocks = self._codify_block_styles([dict(block) for block in structured_blocks])
        ordered_blocks = [
            dict(block)
            for block in sorted(structured_blocks, key=self._structured_block_sort_key)
            if str(block.get("block_type") or "") in {"heading", "paragraph", "list_item"}
            and clean_text(str(block.get("text") or ""))
            and not self._is_page_frame_block(block)
        ]
        if not ordered_blocks:
            return []

        anchor_entries: list[dict[str, Any]] = []
        anchor_by_position: dict[int, dict[str, Any]] = {}
        clause_path_stack: list[str] = []
        active_heading_anchor_block_id: str | None = None
        active_structural_heading_anchor_block_id: str | None = None
        active_structural_path: list[dict[str, Any]] = []
        active_heading_context_path: list[dict[str, Any]] = []
        previous_block_type: str | None = None

        for index, block in enumerate(ordered_blocks):
            anchor = self._classify_clause_anchor(block, previous_block_type=previous_block_type)
            previous_block_type = str(block.get("block_type") or "")
            if not anchor.get("is_anchor"):
                continue
            block_type = str(block.get("block_type") or "")
            is_structural_heading = self._looks_like_structural_document_heading(str(block.get("text") or ""), block)
            is_clause_heading = block_type == "heading" and str(anchor.get("label_type") or "") == "clause_code"
            is_context_heading = block_type == "heading" and not is_structural_heading and not is_clause_heading
            if is_structural_heading:
                clause_path_stack = []
                clause_path: list[str] = []
                parent_heading_anchor_block_id = None
                active_heading_anchor_block_id = str(block.get("block_id") or "") or None
                active_structural_path = self._next_structural_path(
                    active_structural_path,
                    self._structural_heading_path_entry(block),
                )
                active_structural_heading_anchor_block_id = active_heading_anchor_block_id
                active_heading_context_path = list(active_structural_path)
                structural_path = list(active_heading_context_path)
            elif is_context_heading:
                clause_path_stack = []
                clause_path = []
                parent_heading_anchor_block_id = active_structural_heading_anchor_block_id
                active_heading_anchor_block_id = str(block.get("block_id") or "") or None
                active_heading_context_path = [
                    *list(active_structural_path),
                    self._heading_context_path_entry(block),
                ]
                structural_path = list(active_heading_context_path)
            elif anchor.get("label_key") and anchor.get("depth"):
                depth = int(anchor["depth"])
                clause_path_stack = clause_path_stack[: max(depth - 1, 0)]
                clause_path_stack.append(str(anchor["label_key"]))
                clause_path = list(clause_path_stack)
                parent_heading_anchor_block_id = active_structural_heading_anchor_block_id or active_heading_anchor_block_id
                if active_heading_anchor_block_id and active_heading_anchor_block_id != active_structural_heading_anchor_block_id:
                    parent_heading_anchor_block_id = active_heading_anchor_block_id
                structural_path = list(active_heading_context_path or active_structural_path)
            else:
                clause_path = []
                parent_heading_anchor_block_id = active_structural_heading_anchor_block_id or active_heading_anchor_block_id
                if active_heading_anchor_block_id and active_heading_anchor_block_id != active_structural_heading_anchor_block_id:
                    parent_heading_anchor_block_id = active_heading_anchor_block_id
                structural_path = list(active_heading_context_path or active_structural_path)
            entry = {
                "position": index,
                "block": block,
                "block_type": block_type,
                "label": anchor.get("label"),
                "label_key": anchor.get("label_key"),
                "label_type": anchor.get("label_type"),
                "depth": anchor.get("depth"),
                "title_or_lead": anchor.get("content_text") or clean_text(str(block.get("text") or "")),
                "clause_path": clause_path,
                "parent_heading_anchor_block_id": parent_heading_anchor_block_id,
                "structural_path": structural_path,
            }
            anchor_entries.append(entry)
            anchor_by_position[index] = entry

        if not anchor_entries:
            return []

        alignments_by_fragment: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for alignment in alignments or []:
            fragment_id = str(alignment.get("fragment_id") or "")
            if fragment_id:
                alignments_by_fragment[fragment_id].append(alignment)

        clauses: list[dict[str, Any]] = []
        for entry in anchor_entries:
            start_position = int(entry["position"])
            current_depth = entry.get("depth")
            rendered_blocks: list[dict[str, Any]] = []
            child_items: list[dict[str, Any]] = []
            source_block_ids: list[str] = []
            pages: list[int] = []
            bboxes: list[list[float]] = []
            active_relative_depth = 0

            for position in range(start_position, len(ordered_blocks)):
                block = ordered_blocks[position]
                nested_anchor = anchor_by_position.get(position)
                if position > start_position and nested_anchor and self._should_end_assembled_clause(
                    current_anchor=entry,
                    next_anchor=nested_anchor,
                ):
                    break

                page = int(block.get("page") or 0)
                bbox = self._normalized_bbox(block.get("bbox"))
                block_id = str(block.get("block_id") or "")
                if block_id:
                    source_block_ids.append(block_id)
                if page > 0:
                    pages.append(page)
                if bbox:
                    bboxes.append(bbox)

                if position == start_position:
                    label = entry.get("label")
                    relative_depth = 0
                    render_role = "anchor"
                    active_relative_depth = 0
                elif nested_anchor and nested_anchor.get("depth") and current_depth and int(nested_anchor["depth"]) > int(current_depth):
                    label = nested_anchor.get("label")
                    relative_depth = max(1, int(nested_anchor["depth"]) - int(current_depth))
                    render_role = "child_item"
                    active_relative_depth = relative_depth
                else:
                    label = None
                    relative_depth = active_relative_depth
                    render_role = "continuation"

                render_block = self._build_clause_render_block(
                    block=block,
                    label=label,
                    render_role=render_role,
                    relative_depth=relative_depth,
                )
                rendered_blocks.append(render_block)
                if render_role == "child_item":
                    child_items.append(
                        {
                            "block_id": render_block["block_id"],
                            "label": render_block.get("label"),
                            "text": render_block["text"],
                            "content_text": render_block["content_text"],
                            "page": render_block["page"],
                            "bbox": render_block["bbox"],
                            "relative_depth": render_block["relative_depth"],
                        }
                    )

            alignment_summary = self._assembled_clause_alignment_summary(
                source_block_ids=source_block_ids,
                alignments_by_fragment=alignments_by_fragment,
            )
            header_summary = self._assembled_clause_header_summary(
                entry=entry,
                rendered_blocks=rendered_blocks,
            )
            style_evidence = self._assembled_clause_style_evidence(header_summary["rendered_blocks"])
            candidate_title = self._assembled_clause_candidate_title(
                clause_code=header_summary["clause_code"],
                heading_text=header_summary["heading_text"],
                title_or_lead=header_summary["title_or_lead"],
                fallback_text=str(entry["block"].get("text") or ""),
                fallback_id=str(entry["block"].get("block_id") or ""),
            )
            confidence = self._assembled_clause_confidence(
                anchor=entry,
                rendered_blocks=header_summary["rendered_blocks"],
                alignment_confidence=alignment_summary["alignment_confidence"],
            )
            clause_pages = sorted({page for page in pages if page > 0})
            clauses.append(
                {
                    "clause_candidate_id": f"assembled_clause:{entry['block'].get('block_id')}",
                    "anchor": {
                        "block_id": entry["block"].get("block_id"),
                        "page": entry["block"].get("page"),
                        "bbox": self._normalized_bbox(entry["block"].get("bbox")),
                        "block_type": entry["block"].get("block_type"),
                        "label": entry.get("label"),
                        "title_or_lead": header_summary["title_or_lead"],
                    },
                    "clause_path": list(entry.get("clause_path") or []),
                    "structural_path": [dict(item) for item in (entry.get("structural_path") or [])],
                    "label": entry.get("label"),
                    "label_type": entry.get("label_type"),
                    "parent_heading_anchor_block_id": entry.get("parent_heading_anchor_block_id"),
                    "clause_code": header_summary["clause_code"],
                    "heading_text": header_summary["heading_text"],
                    "title_or_lead": header_summary["title_or_lead"],
                    "candidate_title": candidate_title,
                    "header_blocks": header_summary["header_blocks"],
                    "body_blocks": header_summary["body_blocks"],
                    "marginalia_blocks": header_summary["marginalia_blocks"],
                    "rendered_blocks": header_summary["rendered_blocks"],
                    "child_items": child_items,
                    "bbox": self._merge_bboxes(bboxes),
                    "start_page": clause_pages[0] if clause_pages else None,
                    "end_page": clause_pages[-1] if clause_pages else None,
                    "pages": clause_pages,
                    "style_evidence": style_evidence,
                    "confidence": confidence,
                    "source_block_ids": source_block_ids,
                    "matched_xml_node_id": alignment_summary["matched_xml_node_id"],
                    "alignment_confidence": alignment_summary["alignment_confidence"],
                }
            )
        clause_by_anchor_block_id = {
            str(clause.get("anchor", {}).get("block_id") or ""): clause
            for clause in clauses
            if str(clause.get("anchor", {}).get("block_id") or "")
        }
        enriched_clauses: list[dict[str, Any]] = []
        for clause in clauses:
            parent_anchor_block_id = str(clause.get("parent_heading_anchor_block_id") or "")
            parent_clause = clause_by_anchor_block_id.get(parent_anchor_block_id) if parent_anchor_block_id else None
            parent_context = self._parent_heading_context(parent_clause)
            next_clause = dict(clause)
            next_clause.update(parent_context)
            next_clause["structural_path"] = self._resolve_structural_path_candidate_ids(
                list(next_clause.get("structural_path") or []),
                clause_by_anchor_block_id=clause_by_anchor_block_id,
            )
            enriched_clauses.append(next_clause)
        return enriched_clauses

    def _structured_block_sort_key(self, block: dict[str, Any]) -> tuple[int, float, float, str]:
        bbox = self._normalized_bbox(block.get("bbox"))
        return (
            int(block.get("page") or 0),
            float(bbox[1] if len(bbox) == 4 else 0.0),
            float(bbox[0] if len(bbox) == 4 else 0.0),
            str(block.get("block_id") or ""),
        )

    def _normalized_bbox(self, bbox: Any) -> list[float]:
        if not isinstance(bbox, list) or len(bbox) != 4:
            return []
        try:
            x0, y0, x1, y1 = [round(float(value), 2) for value in bbox]
        except (TypeError, ValueError):
            return []
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]

    def _is_page_frame_block(self, block: dict[str, Any]) -> bool:
        metadata = block.get("metadata", {}) if isinstance(block.get("metadata"), dict) else {}
        codification = metadata.get("style_codification") if isinstance(metadata.get("style_codification"), dict) else {}
        if codification.get("page_frame_exempt"):
            return False
        return str(metadata.get("page_region") or "") in {"header", "footer"}

    def _is_editorial_marginalia_text(self, text: str) -> bool:
        cleaned = clean_text(text)
        if not cleaned:
            return False
        if _BRACKETED_MARGINALIA_PATTERN.match(cleaned):
            return True
        return bool(_EDITORIAL_MARGINALIA_PATTERN.match(cleaned.strip("()[] ")))

    def _looks_like_heading_text(self, text: str, block: dict[str, Any]) -> bool:
        cleaned = clean_text(text)
        if not cleaned or len(cleaned) > 120:
            return False
        if self._is_editorial_marginalia_text(cleaned):
            return False
        if cleaned.endswith((".", ";", ":", "-", "\u2014")):
            return False
        words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", cleaned)
        if not words:
            return False
        title_like = sum(1 for word in words if word[:1].isupper())
        metadata = block.get("metadata", {}) if isinstance(block.get("metadata"), dict) else {}
        codification = metadata.get("style_codification") if isinstance(metadata.get("style_codification"), dict) else {}
        if codification.get("heading_like"):
            return True
        style_summary = metadata.get("style_summary") if isinstance(metadata.get("style_summary"), dict) else {}
        emphasized = bool(style_summary.get("is_bold") or style_summary.get("is_italic"))
        return emphasized or title_like >= max(2, int(len(words) * 0.6))

    def _should_promote_post_heading_anchor(self, block: dict[str, Any], *, previous_block_type: str | None) -> bool:
        if previous_block_type != "heading":
            return False
        text = clean_text(str(block.get("text") or ""))
        if not text or self._is_editorial_marginalia_text(text) or _NON_CLAUSE_LEAD_PATTERN.match(text):
            return False
        return self._looks_like_heading_text(text, block)

    def _extract_clause_code_and_heading(self, text: str) -> tuple[str | None, str]:
        cleaned = clean_text(text)
        code_match = _CLAUSE_CODE_PATTERN.match(cleaned)
        if not code_match:
            return None, cleaned
        clause_code = clean_text(code_match.group(1))
        remainder = clean_text(cleaned[len(code_match.group(0)) :])
        return clause_code, remainder

    def _blocks_share_header_band(self, left_block: dict[str, Any], right_block: dict[str, Any]) -> bool:
        left_bbox = self._normalized_bbox(left_block.get("bbox"))
        right_bbox = self._normalized_bbox(right_block.get("bbox"))
        if len(left_bbox) != 4 or len(right_bbox) != 4:
            return False
        if int(left_block.get("page") or 0) != int(right_block.get("page") or 0):
            return False
        same_row = abs(left_bbox[1] - right_bbox[1]) <= 14 or abs(left_bbox[3] - right_bbox[3]) <= 14
        near_row = 0 <= right_bbox[1] - left_bbox[3] <= 18
        return same_row or near_row

    def _assembled_clause_header_summary(
        self,
        *,
        entry: dict[str, Any],
        rendered_blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        projected_blocks = [dict(block) for block in rendered_blocks]
        if not projected_blocks:
            return {
                "clause_code": None,
                "heading_text": None,
                "title_or_lead": entry.get("title_or_lead"),
                "header_blocks": [],
                "body_blocks": [],
                "marginalia_blocks": [],
                "rendered_blocks": [],
            }

        marginalia_ids = {
            str(block.get("block_id") or "")
            for block in projected_blocks
            if self._is_editorial_marginalia_text(str(block.get("text") or ""))
        }
        clause_code: str | None = None
        heading_text: str | None = None
        header_block_ids: set[str] = set()

        anchor_block = projected_blocks[0]
        anchor_code, anchor_remainder = self._extract_clause_code_and_heading(str(anchor_block.get("text") or ""))
        if anchor_code:
            clause_code = anchor_code
            header_block_ids.add(str(anchor_block.get("block_id") or ""))
            if anchor_remainder and self._looks_like_heading_text(anchor_remainder, anchor_block):
                heading_text = anchor_remainder
        elif str(entry.get("label_type") or "") == "clause_code":
            clause_code = str(entry.get("label") or "") or None
            header_block_ids.add(str(anchor_block.get("block_id") or ""))

        non_marginal_blocks = [
            block
            for block in projected_blocks
            if str(block.get("block_id") or "") not in marginalia_ids and str(block.get("render_role") or "") != "child_item"
        ]
        if clause_code:
            for block in non_marginal_blocks[1:4]:
                if not self._blocks_share_header_band(anchor_block, block):
                    break
                if self._extract_clause_code_and_heading(str(block.get("text") or ""))[0]:
                    continue
                if self._looks_like_heading_text(str(block.get("text") or ""), block):
                    heading_text = clean_text(str(block.get("text") or ""))
                    header_block_ids.add(str(block.get("block_id") or ""))
                    break
        elif str(anchor_block.get("block_type") or "") == "heading":
            header_block_ids.add(str(anchor_block.get("block_id") or ""))
            if self._looks_like_heading_text(str(anchor_block.get("text") or ""), anchor_block):
                heading_text = clean_text(str(anchor_block.get("text") or ""))

        title_or_lead = clean_text(str(entry.get("title_or_lead") or ""))
        if clause_code and heading_text:
            title_or_lead = clean_text(f"{clause_code} {heading_text}")
        elif heading_text:
            title_or_lead = heading_text

        header_blocks: list[dict[str, Any]] = []
        body_blocks: list[dict[str, Any]] = []
        marginalia_blocks: list[dict[str, Any]] = []
        for block in projected_blocks:
            block_id = str(block.get("block_id") or "")
            next_block = dict(block)
            if block_id in marginalia_ids:
                next_block["render_role"] = "annotation"
                next_block["relative_depth"] = 0
                marginalia_blocks.append(next_block)
            elif block_id in header_block_ids:
                next_block["render_role"] = "header"
                next_block["relative_depth"] = 0
                header_blocks.append(next_block)
            else:
                body_blocks.append(next_block)

        return {
            "clause_code": clause_code,
            "heading_text": heading_text,
            "title_or_lead": title_or_lead,
            "header_blocks": header_blocks,
            "body_blocks": body_blocks,
            "marginalia_blocks": marginalia_blocks,
            "rendered_blocks": [*header_blocks, *marginalia_blocks, *body_blocks],
        }

    def _classify_clause_anchor(
        self,
        block: dict[str, Any],
        *,
        previous_block_type: str | None,
    ) -> dict[str, Any]:
        block_type = str(block.get("block_type") or "")
        text = clean_text(str(block.get("text") or ""))
        label_info = self._extract_clause_label(text)
        content_text = self._strip_leading_clause_label(text, label_info["label"]) if label_info["label"] else text
        metadata = block.get("metadata", {}) if isinstance(block.get("metadata"), dict) else {}
        codification = metadata.get("style_codification") if isinstance(metadata.get("style_codification"), dict) else {}
        is_structural_heading = bool(
            self._looks_like_structural_document_heading(text, block)
            and not codification.get("likely_running_chrome")
            and (
                codification.get("heading_like")
                or codification.get("page_frame_exempt")
                or block_type == "heading"
            )
        )
        if block_type == "heading" and label_info["label"]:
            return {
                "is_anchor": True,
                "label": label_info["label"],
                "label_key": label_info["label_key"],
                "label_type": label_info["label_type"],
                "depth": label_info["depth"],
                "content_text": content_text,
            }
        if block_type == "heading" or is_structural_heading:
            return {
                "is_anchor": True,
                "label": label_info["label"],
                "label_key": label_info["label_key"],
                "label_type": "heading",
                "depth": 0,
                "content_text": text,
            }
        if label_info["label"]:
            return {
                "is_anchor": True,
                "label": label_info["label"],
                "label_key": label_info["label_key"],
                "label_type": label_info["label_type"],
                "depth": label_info["depth"],
                "content_text": content_text,
            }
        if _NON_CLAUSE_LEAD_PATTERN.match(text) or self._is_editorial_marginalia_text(text):
            return {
                "is_anchor": False,
                "label": None,
                "label_key": None,
                "label_type": None,
                "depth": None,
                "content_text": text,
            }
        return {
            "is_anchor": self._should_promote_post_heading_anchor(block, previous_block_type=previous_block_type),
            "label": None,
            "label_key": None,
            "label_type": None,
            "depth": None,
            "content_text": text,
        }

    def _extract_clause_label(self, text: str) -> dict[str, Any]:
        match = _CLAUSE_LABEL_PAREN_PATTERN.match(text)
        if match:
            token = clean_text(match.group(1))
            if not token or self._is_editorial_marginalia_text(token):
                return {"label": None, "label_key": None, "label_type": None, "depth": None}
            normalized = normalize_text(token).replace(" ", "")
            if token.isdigit():
                return {"label": f"({token})", "label_key": normalized, "label_type": "numeric", "depth": 1}
            if _ROMAN_TOKEN_PATTERN.match(token):
                return {"label": f"({token})", "label_key": normalized, "label_type": "roman", "depth": 3}
            if len(token) == 1 and token.isalpha():
                return {"label": f"({token})", "label_key": normalized, "label_type": "alpha", "depth": 2}
            if " " in token or len(normalized) > 4:
                return {"label": None, "label_key": None, "label_type": None, "depth": None}
            return {"label": f"({token})", "label_key": normalized, "label_type": "alphanumeric", "depth": 2}
        code_match = _CLAUSE_CODE_PATTERN.match(text)
        if code_match:
            token = clean_text(code_match.group(1))
            return {"label": token, "label_key": normalize_text(token).replace(" ", ""), "label_type": "clause_code", "depth": 1}
        return {"label": None, "label_key": None, "label_type": None, "depth": None}

    def _strip_leading_clause_label(self, text: str, label: str | None) -> str:
        cleaned = clean_text(text)
        if not label:
            return cleaned
        if cleaned.startswith(label):
            return clean_text(cleaned[len(label) :])
        return cleaned

    def _should_end_assembled_clause(
        self,
        *,
        current_anchor: dict[str, Any],
        next_anchor: dict[str, Any],
    ) -> bool:
        current_block_type = str(current_anchor.get("block_type") or "")
        next_block_type = str(next_anchor.get("block_type") or "")
        if next_block_type == "heading":
            return True
        if current_block_type == "heading":
            return True
        current_depth = current_anchor.get("depth")
        next_depth = next_anchor.get("depth")
        if current_depth is None or next_depth is None:
            return True
        return int(next_depth) <= int(current_depth)

    def _build_clause_render_block(
        self,
        *,
        block: dict[str, Any],
        label: str | None,
        render_role: str,
        relative_depth: int,
    ) -> dict[str, Any]:
        metadata = block.get("metadata", {}) if isinstance(block.get("metadata"), dict) else {}
        text = clean_text(str(block.get("text") or ""))
        content_text = self._strip_leading_clause_label(text, label)
        return {
            "block_id": str(block.get("block_id") or ""),
            "page": int(block.get("page") or 0),
            "bbox": self._normalized_bbox(block.get("bbox")),
            "block_type": str(block.get("block_type") or ""),
            "text": text,
            "label": label,
            "content_text": content_text,
            "render_role": render_role,
            "relative_depth": relative_depth,
            "style_summary": metadata.get("style_summary") if isinstance(metadata.get("style_summary"), dict) else None,
            "style_codification": (
                metadata.get("style_codification") if isinstance(metadata.get("style_codification"), dict) else None
            ),
            "style_spans": self._project_clause_style_spans(
                text=text,
                content_text=content_text,
                label=label,
                style_spans=metadata.get("style_spans") if isinstance(metadata.get("style_spans"), list) else [],
            ),
        }

    def _project_clause_style_spans(
        self,
        *,
        text: str,
        content_text: str,
        label: str | None,
        style_spans: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not style_spans:
            return []
        label_offset = 0
        if label and text.startswith(label):
            label_offset = len(label)
            while label_offset < len(text) and text[label_offset].isspace():
                label_offset += 1

        projected: list[dict[str, Any]] = []
        for span in style_spans:
            if not isinstance(span, dict):
                continue
            try:
                start = int(span.get("start", 0)) - label_offset
                end = int(span.get("end", 0)) - label_offset
            except (TypeError, ValueError):
                continue
            start = max(0, start)
            end = min(len(content_text), max(start, end))
            if end <= start:
                continue
            projected.append(
                {
                    **span,
                    "start": start,
                    "end": end,
                }
            )
        return projected

    def _merge_bboxes(self, bboxes: list[list[float]]) -> list[float]:
        normalized = [bbox for bbox in bboxes if len(bbox) == 4]
        if not normalized:
            return []
        return [
            round(min(bbox[0] for bbox in normalized), 2),
            round(min(bbox[1] for bbox in normalized), 2),
            round(max(bbox[2] for bbox in normalized), 2),
            round(max(bbox[3] for bbox in normalized), 2),
        ]

    def _assembled_clause_alignment_summary(
        self,
        *,
        source_block_ids: list[str],
        alignments_by_fragment: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        matched_alignments: list[dict[str, Any]] = []
        for block_id in source_block_ids:
            matched_alignments.extend(
                alignment
                for alignment in alignments_by_fragment.get(block_id, [])
                if alignment.get("matched") and alignment.get("node_id")
            )
        if not matched_alignments:
            return {"matched_xml_node_id": None, "alignment_confidence": 0.0}

        grouped: dict[str, list[float]] = defaultdict(list)
        for alignment in matched_alignments:
            grouped[str(alignment["node_id"])].append(float(alignment.get("confidence", 0.0)))
        node_id, scores = max(grouped.items(), key=lambda item: (sum(item[1]), len(item[1]), average(item[1])))
        return {
            "matched_xml_node_id": node_id,
            "alignment_confidence": round(average(scores), 3),
        }

    def _assembled_clause_style_evidence(self, rendered_blocks: list[dict[str, Any]]) -> dict[str, Any]:
        styled_blocks = [block for block in rendered_blocks if block.get("style_summary") or block.get("style_spans")]
        span_count = sum(len(block.get("style_spans") or []) for block in styled_blocks)
        primary_font = next(
            (
                block.get("style_summary", {}).get("font_name")
                for block in styled_blocks
                if isinstance(block.get("style_summary"), dict) and block.get("style_summary", {}).get("font_name")
            ),
            None,
        )
        return {
            "styled_block_count": len(styled_blocks),
            "style_span_count": span_count,
            "primary_font_name": primary_font,
            "has_emphasis": any(
                isinstance(block.get("style_summary"), dict)
                and (block["style_summary"].get("is_bold") or block["style_summary"].get("is_italic"))
                for block in styled_blocks
            ),
        }

    def _assembled_clause_confidence(
        self,
        *,
        anchor: dict[str, Any],
        rendered_blocks: list[dict[str, Any]],
        alignment_confidence: float,
    ) -> float:
        base = 0.7
        if anchor.get("label"):
            base += 0.12
        if str(anchor.get("block_type") or "") == "heading":
            base += 0.08
        if len(rendered_blocks) > 1:
            base += min(0.1, 0.02 * (len(rendered_blocks) - 1))
        if alignment_confidence > 0:
            base += min(0.07, alignment_confidence * 0.07)
        return round(min(base, 0.99), 3)

    def _looks_like_structural_document_heading(self, text: str | None, block: dict[str, Any] | None = None) -> bool:
        if isinstance(block, dict):
            metadata = block.get("metadata", {}) if isinstance(block.get("metadata"), dict) else {}
            codification = (
                metadata.get("style_codification") if isinstance(metadata.get("style_codification"), dict) else {}
            )
            if codification.get("structural_heading_kind"):
                return True
        cleaned = clean_text(text)
        if not cleaned:
            return False
        return bool(_DOCUMENT_HEADING_PATTERN.match(cleaned))

    def _assembled_clause_candidate_title(
        self,
        *,
        clause_code: str | None,
        heading_text: str | None,
        title_or_lead: str | None,
        fallback_text: str | None,
        fallback_id: str | None,
    ) -> str:
        cleaned_code = clean_text(clause_code)
        cleaned_heading = clean_text(heading_text)
        cleaned_title_or_lead = clean_text(title_or_lead)
        cleaned_fallback = clean_text(fallback_text)
        if cleaned_code and cleaned_heading:
            return clean_text(f"{cleaned_code} {cleaned_heading}")[:160]
        if cleaned_heading:
            return cleaned_heading[:160]
        if cleaned_title_or_lead:
            return cleaned_title_or_lead[:160]
        if cleaned_fallback:
            return cleaned_fallback[:160]
        return str(fallback_id or "")[:160]

    def _structural_heading_rank(self, kind: str | None) -> int:
        normalized = clean_text(kind).lower()
        if normalized == "part":
            return 1
        if normalized == "section":
            return 2
        if normalized == "schedule":
            return 3
        return 99

    def _structural_heading_path_entry(self, block: dict[str, Any]) -> dict[str, Any]:
        metadata = block.get("metadata", {}) if isinstance(block.get("metadata"), dict) else {}
        codification = metadata.get("style_codification") if isinstance(metadata.get("style_codification"), dict) else {}
        label, heading_text, heading_title = self._split_document_heading(str(block.get("text") or ""))
        block_id = str(block.get("block_id") or "")
        return {
            "kind": clean_text(str(codification.get("structural_heading_kind") or "")) or (label or "").split(" ", 1)[0].lower() or None,
            "label": label,
            "text": heading_text,
            "title": heading_title or clean_text(str(block.get("text") or "")),
            "block_id": block_id or None,
            "candidate_id": f"candidate:pdf_clause:{block_id}" if block_id else None,
        }

    def _heading_context_path_entry(self, block: dict[str, Any]) -> dict[str, Any]:
        text = clean_text(str(block.get("text") or ""))
        block_id = str(block.get("block_id") or "")
        return {
            "kind": "heading",
            "label": None,
            "text": text or None,
            "title": text or None,
            "block_id": block_id or None,
            "candidate_id": f"candidate:pdf_clause:{block_id}" if block_id else None,
        }

    def _next_structural_path(
        self,
        active_path: list[dict[str, Any]],
        entry: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not entry:
            return list(active_path)
        rank = self._structural_heading_rank(str(entry.get("kind") or ""))
        trimmed = [
            dict(item)
            for item in active_path
            if self._structural_heading_rank(str(item.get("kind") or "")) < rank
        ]
        trimmed.append(dict(entry))
        return trimmed

    def _resolve_structural_path_candidate_ids(
        self,
        structural_path: list[dict[str, Any]],
        *,
        clause_by_anchor_block_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for entry in structural_path:
            if not isinstance(entry, dict):
                continue
            block_id = str(entry.get("block_id") or "")
            related_clause = clause_by_anchor_block_id.get(block_id) if block_id else None
            next_entry = dict(entry)
            if related_clause and not next_entry.get("candidate_id"):
                next_entry["candidate_id"] = f"candidate:pdf_clause:{block_id}"
            resolved.append(next_entry)
        return resolved

    def _split_document_heading(self, title: str | None) -> tuple[str | None, str | None, str | None]:
        cleaned = clean_text(title)
        if not cleaned:
            return None, None, None
        match = _DOCUMENT_HEADING_PATTERN.match(cleaned)
        if not match:
            return None, cleaned, cleaned
        heading_label = clean_text(f"{match.group(1).title()} {match.group(2)}")
        heading_text = clean_text(match.group(3)) or None
        heading_title = clean_text(f"{heading_label} {heading_text or ''}")
        return heading_label, heading_text, heading_title

    def _parent_heading_context(self, parent_clause: dict[str, Any] | None) -> dict[str, Any]:
        if not parent_clause:
            return {
                "parent_heading_clause_id": None,
                "parent_heading_block_id": None,
                "parent_heading_label": None,
                "parent_heading_text": None,
                "parent_heading_title": None,
            }
        heading_label, heading_text, heading_title = self._split_document_heading(parent_clause.get("title_or_lead"))
        return {
            "parent_heading_clause_id": parent_clause.get("clause_candidate_id"),
            "parent_heading_block_id": parent_clause.get("anchor", {}).get("block_id"),
            "parent_heading_label": heading_label,
            "parent_heading_text": heading_text,
            "parent_heading_title": heading_title,
        }

    def _build_page_context_index(self, structured_blocks: list[dict[str, Any]] | None) -> dict[int, dict[str, Any]]:
        context_by_page: dict[int, dict[str, Any]] = {}
        for block in structured_blocks or []:
            if not self._is_page_frame_block(block):
                continue
            page = int(block.get("page") or 0)
            if page <= 0:
                continue
            metadata = block.get("metadata", {}) if isinstance(block.get("metadata"), dict) else {}
            region = str(metadata.get("page_region") or "")
            if region not in {"header", "footer"}:
                continue
            entry = context_by_page.setdefault(
                page,
                {
                    "pages": [page],
                    "header_blocks": [],
                    "footer_blocks": [],
                    "running_header_texts": [],
                    "running_footer_texts": [],
                    "volume_labels": [],
                    "ncc_page_numbers": [],
                },
            )
            projected_block = self._build_clause_render_block(
                block=block,
                label=None,
                render_role="page_context",
                relative_depth=0,
            )
            target_key = "header_blocks" if region == "header" else "footer_blocks"
            entry[target_key].append(projected_block)
            text = clean_text(str(block.get("text") or ""))
            if text:
                text_key = "running_header_texts" if region == "header" else "running_footer_texts"
                entry[text_key].append(text)
                volume_match = _NCC_VOLUME_PATTERN.search(text)
                if volume_match:
                    volume_label = f"Volume {volume_match.group(1).title()}"
                    if volume_label not in entry["volume_labels"]:
                        entry["volume_labels"].append(volume_label)
                page_match = _NCC_PAGE_PATTERN.search(text)
                if page_match:
                    page_number = int(page_match.group(1))
                    if page_number not in entry["ncc_page_numbers"]:
                        entry["ncc_page_numbers"].append(page_number)

        for entry in context_by_page.values():
            entry["start_page"] = entry["pages"][0] if entry["pages"] else None
            entry["end_page"] = entry["pages"][-1] if entry["pages"] else None
            entry["primary_volume_label"] = entry["volume_labels"][0] if entry["volume_labels"] else None
            entry["primary_ncc_page_number"] = entry["ncc_page_numbers"][0] if entry["ncc_page_numbers"] else None
        return context_by_page

    def _candidate_page_context(
        self,
        *,
        candidate: dict[str, Any],
        clause: dict[str, Any] | None,
        page_context_index: dict[int, dict[str, Any]],
    ) -> dict[str, Any] | None:
        page_numbers: list[int] = []
        if clause:
            page_numbers.extend(int(page) for page in (clause.get("pages") or []) if int(page or 0) > 0)
        if not page_numbers:
            page_numbers.extend(
                int(item.get("page") or 0)
                for item in (candidate.get("evidence") or [])
                if isinstance(item, dict) and int(item.get("page") or 0) > 0
            )
        unique_pages = sorted({page for page in page_numbers if page > 0})
        if not unique_pages:
            return None

        merged = {
            "start_page": unique_pages[0] if unique_pages else None,
            "end_page": unique_pages[-1] if unique_pages else None,
            "pages": unique_pages,
            "header_blocks": [],
            "footer_blocks": [],
            "running_header_texts": [],
            "running_footer_texts": [],
            "volume_labels": [],
            "ncc_page_numbers": [],
            "primary_volume_label": None,
            "primary_ncc_page_number": None,
        }
        for page in unique_pages:
            entry = page_context_index.get(page)
            if not entry:
                continue
            merged["header_blocks"].extend(list(entry.get("header_blocks") or []))
            merged["footer_blocks"].extend(list(entry.get("footer_blocks") or []))
            for key in ("running_header_texts", "running_footer_texts", "volume_labels", "ncc_page_numbers"):
                for value in entry.get(key) or []:
                    if value not in merged[key]:
                        merged[key].append(value)
        merged["primary_volume_label"] = merged["volume_labels"][0] if merged["volume_labels"] else None
        merged["primary_ncc_page_number"] = merged["ncc_page_numbers"][0] if merged["ncc_page_numbers"] else None
        return merged

    def _attach_clause_projections_to_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        assembled_clauses: list[dict[str, Any]],
        structured_blocks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        clause_by_anchor_block_id = {
            str(clause.get("anchor", {}).get("block_id")): clause
            for clause in assembled_clauses
            if str(clause.get("anchor", {}).get("block_id") or "")
        }
        clauses_by_source_block_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for clause in assembled_clauses:
            for block_id in clause.get("source_block_ids") or []:
                clauses_by_source_block_id[str(block_id)].append(clause)
        page_context_index = self._build_page_context_index(structured_blocks)

        enriched: list[dict[str, Any]] = []
        for candidate in candidates:
            matched_clause = self._match_clause_to_candidate(
                candidate=candidate,
                clause_by_anchor_block_id=clause_by_anchor_block_id,
                clauses_by_source_block_id=clauses_by_source_block_id,
            )
            next_candidate = dict(candidate)
            next_candidate["assembled_clause"] = matched_clause
            next_candidate["page_context"] = self._candidate_page_context(
                candidate=next_candidate,
                clause=matched_clause,
                page_context_index=page_context_index,
            )
            next_candidate["page"] = (
                matched_clause.get("start_page")
                if matched_clause and matched_clause.get("start_page") is not None
                else next_candidate.get("page")
                or (next_candidate.get("page_context") or {}).get("start_page")
                or next(
                    (
                        int(item.get("page") or 0)
                        for item in (next_candidate.get("evidence") or [])
                        if isinstance(item, dict) and int(item.get("page") or 0) > 0
                    ),
                    None,
                )
            )
            next_candidate["display_projection"] = self._build_candidate_display_projection(
                candidate=next_candidate,
                clause=matched_clause,
            )
            enriched.append(next_candidate)
        return enriched

    def _match_clause_to_candidate(
        self,
        *,
        candidate: dict[str, Any],
        clause_by_anchor_block_id: dict[str, dict[str, Any]],
        clauses_by_source_block_id: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any] | None:
        source = candidate.get("source", {}) if isinstance(candidate.get("source"), dict) else {}
        primary_fragment_id = str(
            source.get("pdf_fragment_id")
            or next((item.get("fragment_id") for item in (candidate.get("evidence") or []) if item.get("fragment_id")), "")
            or ""
        )
        evidence_ids = {
            str(item.get("fragment_id"))
            for item in (candidate.get("evidence") or [])
            if isinstance(item, dict) and item.get("fragment_id")
        }
        if primary_fragment_id:
            evidence_ids.add(primary_fragment_id)
        if primary_fragment_id and primary_fragment_id in clause_by_anchor_block_id:
            return dict(clause_by_anchor_block_id[primary_fragment_id])

        best_clause: dict[str, Any] | None = None
        best_score = -1.0
        candidate_node_id = str(candidate.get("xml_node_id") or "")
        considered = {
            id(clause): clause
            for block_id in evidence_ids
            for clause in clauses_by_source_block_id.get(block_id, [])
        }.values()
        for clause in considered:
            score = 0.0
            source_block_ids = {str(block_id) for block_id in (clause.get("source_block_ids") or [])}
            overlap = len(source_block_ids.intersection(evidence_ids))
            score += overlap * 3.0
            if primary_fragment_id and primary_fragment_id in source_block_ids:
                score += 5.0
            if candidate_node_id and candidate_node_id == str(clause.get("matched_xml_node_id") or ""):
                score += 2.5
            score += float(clause.get("alignment_confidence") or 0.0)
            if score > best_score:
                best_score = score
                best_clause = clause
        return dict(best_clause) if best_clause else None

    def _build_candidate_display_projection(
        self,
        *,
        candidate: dict[str, Any],
        clause: dict[str, Any] | None,
    ) -> dict[str, Any]:
        evidence = candidate.get("evidence") or []
        primary_evidence = evidence[0] if evidence else {}
        page_context = candidate.get("page_context") if isinstance(candidate.get("page_context"), dict) else None
        review = candidate.get("review", {}) if isinstance(candidate.get("review"), dict) else {}
        relation_count = len(candidate.get("candidate_relations") or [])
        reconciliation_count = len(candidate.get("reconciliation_records") or [])
        if clause:
            rendered_blocks = list(clause.get("rendered_blocks") or [])
            title = self._assembled_clause_candidate_title(
                clause_code=clause.get("clause_code"),
                heading_text=clause.get("heading_text"),
                title_or_lead=clause.get("title_or_lead"),
                fallback_text=str(primary_evidence.get("text") or ""),
                fallback_id=str(candidate.get("candidate_id") or ""),
            )
            source_provenance = {
                "start_page": clause.get("start_page"),
                "end_page": clause.get("end_page"),
                "pages": list(clause.get("pages") or []),
                "bbox": list(clause.get("bbox") or []),
                "source_block_ids": list(clause.get("source_block_ids") or []),
                "matched_xml_node_id": clause.get("matched_xml_node_id") or candidate.get("xml_node_id"),
                "alignment_confidence": clause.get("alignment_confidence"),
                "marginalia_count": len(clause.get("marginalia_blocks") or []),
                "parent_heading_clause_id": clause.get("parent_heading_clause_id"),
                "parent_heading_block_id": clause.get("parent_heading_block_id"),
                "structural_path": list(clause.get("structural_path") or []),
            }
        else:
            fallback_text = clean_text(str(primary_evidence.get("text") or candidate.get("proposed", {}).get("content") or ""))
            title = candidate.get("title") or candidate.get("candidate_id")
            rendered_blocks = [
                {
                    "block_id": str(primary_evidence.get("fragment_id") or ""),
                    "page": int(primary_evidence.get("page") or 0),
                    "bbox": list(primary_evidence.get("bbox") or []),
                    "block_type": str(primary_evidence.get("pdf_evidence_class") or "paragraph"),
                    "text": fallback_text,
                    "label": None,
                    "content_text": fallback_text,
                    "render_role": "anchor",
                    "relative_depth": 0,
                    "style_summary": None,
                    "style_spans": [],
                }
            ]
            source_provenance = {
                "start_page": candidate.get("page") or (candidate.get("page_context") or {}).get("start_page"),
                "end_page": candidate.get("page") or (candidate.get("page_context") or {}).get("end_page"),
                "pages": [int(primary_evidence.get("page") or 0)] if primary_evidence.get("page") else [],
                "bbox": list(primary_evidence.get("bbox") or []),
                "source_block_ids": [str(primary_evidence.get("fragment_id") or "")] if primary_evidence.get("fragment_id") else [],
                "matched_xml_node_id": candidate.get("xml_node_id"),
                "alignment_confidence": candidate.get("confidence", {}).get("overall"),
                "marginalia_count": 0,
                "structural_path": [],
            }

        return {
            "title": title,
            "clause_label": clause.get("label") if clause else None,
            "clause_path": list(clause.get("clause_path") or []) if clause else [],
            "clause_code": clause.get("clause_code") if clause else candidate.get("pdf_clause_code"),
            "heading_text": clause.get("heading_text") if clause else candidate.get("pdf_heading_text"),
            "parent_heading_clause_id": clause.get("parent_heading_clause_id") if clause else None,
            "parent_heading_block_id": clause.get("parent_heading_block_id") if clause else None,
            "parent_heading_label": clause.get("parent_heading_label") if clause else None,
            "parent_heading_text": clause.get("parent_heading_text") if clause else None,
            "parent_heading_title": clause.get("parent_heading_title") if clause else None,
            "structural_path": list(clause.get("structural_path") or []) if clause else [],
            "header_blocks": list(clause.get("header_blocks") or []) if clause else [],
            "marginalia_blocks": list(clause.get("marginalia_blocks") or []) if clause else [],
            "rendered_blocks": rendered_blocks,
            "page_context": page_context,
            "source_provenance": source_provenance,
            "added_fields": {
                "candidate_id": candidate.get("candidate_id"),
                "semantic_unit_id": candidate.get("semantic_unit_id"),
                "xml_node_id": candidate.get("xml_node_id"),
                "candidate_type": candidate.get("candidate_type"),
                "candidate_semantic_class": candidate.get("candidate_semantic_class"),
                "confidence": candidate.get("confidence", {}).get("overall"),
                "depends_on": list(candidate.get("depends_on") or []),
                "xml_path": candidate.get("xml_path"),
                "start_page": source_provenance.get("start_page"),
                "end_page": source_provenance.get("end_page"),
                "clause_code": clause.get("clause_code") if clause else candidate.get("pdf_clause_code"),
                "heading_text": clause.get("heading_text") if clause else candidate.get("pdf_heading_text"),
                "parent_heading_label": clause.get("parent_heading_label") if clause else None,
                "parent_heading_text": clause.get("parent_heading_text") if clause else None,
                "parent_heading_title": clause.get("parent_heading_title") if clause else None,
                "structural_path": list(clause.get("structural_path") or []) if clause else [],
                "page_context_volume": page_context.get("primary_volume_label") if page_context else None,
                "page_context_ncc_page": page_context.get("primary_ncc_page_number") if page_context else None,
            },
            "review_signals": {
                "base_status": review.get("base_status"),
                "needs_human_review": review.get("needs_human_review"),
                "issue_class": review.get("issue_class"),
                "source_emphasis": review.get("source_emphasis"),
                "issues": list(review.get("issues") or []),
                "xml_only_terms": list(review.get("xml_only_terms") or []),
                "pdf_only_terms": list(review.get("pdf_only_terms") or []),
                "relation_count": relation_count,
                "reconciliation_count": reconciliation_count,
            },
        }

    def _serialize_strategy(self, strategy: DocumentStrategyDecision, extracted: ExtractedPdf) -> dict[str, Any]:
        return {
            "document_class": strategy.document_class,
            "extractor_strategy": strategy.extractor_strategy,
            "extractor_options": strategy.extractor_options,
            "runtime_strategy": extracted.strategy_name,
            "runtime_mode": extracted.runtime_mode,
            "extraction_profile": strategy.extraction_profile.profile_id,
            "evaluation_profile": strategy.evaluation_profile.profile_id,
            "parity_mode": strategy.evaluation_profile.parity_mode,
            "notes": [*strategy.notes, *extracted.notes],
        }

    def _should_require_review(
        self,
        review_policy: ReviewPolicy,
        strategy: DocumentStrategyDecision,
        *,
        unresolved: list[dict[str, Any]],
        low_confidence: list[dict[str, Any]],
        parity_scaffold: dict[str, Any],
        alignment_avg: float,
    ) -> bool:
        if alignment_avg < review_policy.min_alignment_confidence_for_review:
            return False
        if 0 < len(unresolved) <= review_policy.max_unresolved_for_review:
            return True
        if 0 < len(low_confidence) <= review_policy.max_low_confidence_for_review:
            return True
        if review_policy.require_review_for_grouped_parity and parity_scaffold["summary"]["review_required_groups"] > 0:
            return True
        if review_policy.require_review_for_interpretive_content and strategy.document_class in {
            "definitions_glossary",
            "governance_interpretation",
        }:
            return bool(unresolved or low_confidence or parity_scaffold["summary"]["unmapped_targets"] > 0)
        return False

    def _build_parity_scaffold(
        self,
        strategy: DocumentStrategyDecision,
        fragments: list[PdfFragment],
        alignments: list[dict[str, Any]],
        xml_nodes: list[XmlNode],
    ) -> dict[str, Any]:
        if not strategy.evaluation_profile.grouped_targets:
            return {
                "state": "scaffolded",
                "parity_mode": strategy.evaluation_profile.parity_mode,
                "groups": [],
                "summary": {
                    "group_count": 0,
                    "matched_groups": 0,
                    "review_required_groups": 0,
                    "unmapped_targets": 0,
                },
            }

        target_groups: dict[str, dict[str, Any]] = {}
        for node in xml_nodes:
            group_key = self._group_key_for_node(node, strategy.document_class)
            group = target_groups.setdefault(
                group_key,
                {"group_id": group_key, "target_node_ids": [], "fragment_ids": [], "confidences": []},
            )
            group["target_node_ids"].append(node.node_id)

        for alignment in alignments:
            if not alignment["matched"] or not alignment["node_id"]:
                continue
            node = next((item for item in xml_nodes if item.node_id == alignment["node_id"]), None)
            if node is None:
                continue
            group_key = self._group_key_for_node(node, strategy.document_class)
            group = target_groups.setdefault(
                group_key,
                {"group_id": group_key, "target_node_ids": [], "fragment_ids": [], "confidences": []},
            )
            group["fragment_ids"].append(alignment["fragment_id"])
            group["confidences"].append(float(alignment["confidence"]))

        groups: list[dict[str, Any]] = []
        review_required_groups = 0
        matched_groups = 0
        unmapped_targets = 0
        for group in target_groups.values():
            confidence = average(group["confidences"]) if group["confidences"] else 0.0
            coverage = ratio(len(set(group["fragment_ids"])), max(len(set(group["target_node_ids"])), 1))
            review_required = bool(group["target_node_ids"] and not group["fragment_ids"])
            if review_required:
                review_required_groups += 1
                unmapped_targets += len(group["target_node_ids"])
            if group["fragment_ids"]:
                matched_groups += 1
            groups.append(
                {
                    "group_id": group["group_id"],
                    "target_node_ids": sorted(set(group["target_node_ids"])),
                    "source_fragment_ids": sorted(set(group["fragment_ids"])),
                    "average_confidence": confidence,
                    "coverage": coverage,
                    "review_required": review_required,
                }
            )

        return {
            "state": "scaffolded",
            "parity_mode": strategy.evaluation_profile.parity_mode,
            "glossary_semantics": strategy.evaluation_profile.glossary_semantics,
            "groups": groups,
            "summary": {
                "group_count": len(groups),
                "matched_groups": matched_groups,
                "review_required_groups": review_required_groups,
                "unmapped_targets": unmapped_targets,
            },
        }

    def _group_key_for_node(self, node: XmlNode, document_class: str) -> str:
        normalized = normalize_text(node.text)
        if document_class == "definitions_glossary":
            for marker in ("means", "refers to", "includes"):
                token = f" {marker} "
                if token in f" {normalized} ":
                    return normalized.split(token, 1)[0][:80] or node.node_id
        tokens = normalized.split()
        if not tokens:
            return node.node_id
        return "_".join(tokens[:4])

    def _build_xml_result(
        self,
        *,
        contract: dict[str, Any],
        xml_name: str,
        metrics: dict[str, Any],
        rule_results: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        validation_trace: list[dict[str, Any]],
        xml_nodes: list[XmlNode],
        overall_status: str,
        can_progress: bool,
        blocked: bool,
        reason: str | None,
        trace_sample: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        metadata = metrics["metadata"]
        return {
            "validation_id": f"val_{self._slugify(xml_name)}",
            "contract": {
                "contract_id": contract["contract_id"],
                "contract_version": contract["contract_version"],
            },
            "document": {
                "doc_id": self._slugify(xml_name),
                "paired_document_id": self._slugify(xml_name).replace("xml", "pdf"),
                "root_element": metrics["root_element"],
                "schema_family_id": metrics["schema_family_id"],
                "schema_family_version": metrics.get("schema_family_version"),
                "schema_approved": metrics["schema_approved"],
                "schema_variant_detected": metrics["schema_variant_detected"],
                "unknown_schema_family": metrics["unknown_schema_family"],
                "schema_match_confidence": metrics["schema_family_confidence"],
                "schema_match_reasons": metrics["schema_match_reasons"],
                "schema_parser_profile": metrics["schema_parser_profile"],
                "schema_registry_version": metrics.get("schema_registry_version"),
                "schema_normalizer_version": metrics.get("schema_normalizer_version"),
                "edition": metadata["edition"] or "unknown",
                "amendment": metadata["amendment"],
                "volume": metadata["volume"] or "unknown",
                "section": metadata["section"],
                "part": metadata["part"],
                "paired_pdf_doc_id": self._slugify(xml_name).replace("xml", "pdf"),
                "nodes_processed": metrics["nodes_processed"],
            },
            "overall_status": overall_status,
            "gate_decision": {
                "can_progress_to_alignment_layer": can_progress,
                "blocked": blocked,
                "reason": reason,
            },
            "confidence": {
                "overall": metrics["quality_score"],
                "sources": {
                    "well_formedness": 1.0 if metrics["is_well_formed"] else 0.0,
                    "metadata": 1.0 if metadata["edition"] and metadata["volume"] else 0.0,
                    "references": max(0.0, 1.0 - metrics["unresolved_references"] / max(metrics["nodes_processed"], 1)),
                    "table_structure": max(0.0, 1.0 - metrics["table_structure_issues"] / max(metrics["table_count"] or 1, 1)),
                },
            },
            "rule_results": rule_results,
            "table_validation": [
                {
                    "table_id": f"xml_tbl_{index}",
                    "status": "PASS",
                    "confidence": 1.0,
                    "rows_expected": 0,
                    "rows_extracted": 0,
                }
                for index in range(1, metrics["table_count"] + 1)
            ],
            "warnings": warnings,
            "errors": errors,
            "validation_trace": validation_trace,
            "trace_sample": trace_sample
            if trace_sample is not None
            else [
                {
                    "node_id": node.node_id,
                    "clause_id": node.clause_id,
                    "status": "PASS",
                    "xml_path": node.path,
                    "notes": node.text[:120],
                }
                for node in xml_nodes[:10]
            ],
            "approval": {
                "approved": can_progress,
                "approved_by_type": "system",
                "approved_by_id": "validation_engine",
                "approved_at": utc_now_iso(),
            },
        }

    def _derive_status(
        self,
        *,
        errors: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        quality_score: float,
        min_quality: float,
        review_required: bool,
        progression_target: str,
    ) -> tuple[str, bool, bool, str | None]:
        if errors or quality_score < min_quality:
            return "BLOCKED", False, True, f"Validation failed for {progression_target} progression."
        if review_required:
            return "REVIEW_REQUIRED", False, False, f"Manual review is required before {progression_target} progression."
        if warnings:
            return "PASS_WITH_WARNINGS", True, False, None
        return "PASS", True, False, None

    def _slugify(self, value: str) -> str:
        stem = clean_text(value).lower().replace(".", "_")
        return re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "document"

    def _extract_xml_metadata(self, root: ET.Element, xml_name: str) -> dict[str, Any]:
        attrs = {key.lower(): value for key, value in root.attrib.items()}
        root_tag = root.tag.split("}")[-1].lower()
        root_num = self._first_child_text(root, "num")
        root_title = self._first_child_text(root, "title")
        root_sptc = self._first_child_text(root, "sptc")
        text_sample = clean_text(" ".join(text for text in root.itertext()))[:4000]
        metadata = {
            "edition": attrs.get("edition"),
            "amendment": attrs.get("amendment") or attrs.get("version"),
            "volume": attrs.get("volume"),
            "section": attrs.get("section"),
            "part": attrs.get("part"),
        }

        if root_tag == "part" and not metadata["part"]:
            metadata["part"] = root_num or root_title
        if root_tag == "clause" and not metadata["section"]:
            metadata["section"] = root_sptc or root_num or root_title

        if not metadata["edition"]:
            matches = re.findall(r"\bncc\s+(20\d{2})\b", text_sample, flags=re.IGNORECASE)
            if matches:
                metadata["edition"] = str(max(int(match) for match in matches))
            else:
                match = re.search(r"(20\d{2})", xml_name)
                if match:
                    metadata["edition"] = match.group(1)
        if not metadata["volume"]:
            match = re.search(r"vol(?:ume)?[_\s-]?([0-9a-z]+)", xml_name.lower())
            if match:
                metadata["volume"] = match.group(1)
            else:
                metadata["volume"] = self._infer_volume_from_context(root_num or root_sptc or xml_name)
        if not metadata["edition"] and (attrs.get("outputclass", "").startswith("ncc") or root_tag in {"part", "clause"}):
            metadata["edition"] = "2022"
        if not metadata["amendment"] and metadata["edition"]:
            metadata["amendment"] = "base"
        return metadata

    def _infer_volume_from_context(self, value: str) -> str | None:
        normalized = clean_text(value)
        if not normalized:
            return None
        if re.match(r"^[a-z]", normalized, flags=re.IGNORECASE):
            return "1"
        if re.match(r"^\d", normalized):
            return "2"
        return None

    def _extract_local_reference_target(self, key: str, value: str) -> str | None:
        candidate = clean_text(value)
        if not candidate:
            return None
        if key == "href":
            if candidate.startswith("#"):
                return candidate[1:]
            return None
        if "://" in candidate or "/" in candidate:
            return None
        return candidate.lstrip("#")

    def _hierarchy_metrics(self, root: ET.Element, parent_map: dict[ET.Element, ET.Element]) -> dict[str, int]:
        structural_tags = {
            "ncc",
            "part",
            "section",
            "clause",
            "subclause",
            "intro-part",
            "table-reference",
            "image-reference",
        }
        allowed_parents: dict[str, set[str | None]] = {
            "part": {None, "ncc"},
            "section": {None, "ncc"},
            "clause": {None, "ncc", "part", "section"},
            "subclause": {"clause", "subclause"},
            "intro-part": {"part", "section", "clause"},
            "table-reference": {None, "ncc", "part", "section", "clause", "subclause", "intro-part"},
            "image-reference": {None, "ncc", "part", "section", "clause", "subclause", "intro-part"},
        }
        root_eligible_tags = {"ncc", "part", "section", "clause", "table-reference", "image-reference"}
        invalid_parent_child_links = 0
        impossible_nesting_count = 0
        orphaned_structural_nodes = 0

        for element in root.iter():
            if element is root:
                continue
            tag_name = self._element_tag_name(element)
            if tag_name not in structural_tags:
                continue

            structural_parent: ET.Element | None = None
            structural_ancestor_tags: list[str] = []
            current = parent_map.get(element)
            while current is not None:
                current_tag = self._element_tag_name(current)
                if current_tag in structural_tags:
                    structural_ancestor_tags.append(current_tag)
                    if structural_parent is None:
                        structural_parent = current
                current = parent_map.get(current)

            parent_tag = self._element_tag_name(structural_parent) if structural_parent is not None else None
            if structural_parent is None and tag_name not in root_eligible_tags:
                orphaned_structural_nodes += 1
                continue

            if parent_tag not in allowed_parents.get(tag_name, {None}):
                invalid_parent_child_links += 1

            if tag_name in {"part", "section"} and structural_parent is not None:
                impossible_nesting_count += 1
            elif tag_name == "subclause" and parent_tag not in {"clause", "subclause"}:
                impossible_nesting_count += 1
            elif tag_name == "clause" and "subclause" in structural_ancestor_tags:
                impossible_nesting_count += 1

        return {
            "invalid_parent_child_links": invalid_parent_child_links,
            "impossible_nesting_count": impossible_nesting_count,
            "orphaned_structural_nodes": orphaned_structural_nodes,
        }

    def _definition_link_failures(
        self,
        root: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
        known_ids: set[str],
    ) -> int:
        definition_target_ids: set[str] = set()
        for element in root.iter():
            if not (self._element_tag_name(element) == "definition" or self._is_glossary_entry_element(element)):
                continue
            element_id = element.attrib.get("id") or element.attrib.get("{http://www.w3.org/XML/1998/namespace}id")
            if element_id:
                definition_target_ids.add(element_id)

        if not definition_target_ids:
            return 0

        failures = 0
        for element in root.iter():
            tag_name = self._element_tag_name(element)
            if tag_name not in {"termref", "glossref", "glossseealso", "xref"}:
                continue

            target: str | None = None
            for key in ("ref", "href", "target", "rid"):
                value = element.attrib.get(key)
                if not value:
                    continue
                target = self._extract_local_reference_target(key, value)
                if target:
                    break
            if not target:
                continue

            parent = parent_map.get(element)
            parent_tag = self._element_tag_name(parent) if parent is not None else ""
            source_text = self._inventory_text_for_element(element).lower()
            is_definition_link = (
                tag_name in {"termref", "glossref", "glossseealso"}
                or "definition" in source_text
                or "defined term" in source_text
                or parent_tag in {"termref", "glossref", "glossseealso"}
            )
            if not is_definition_link:
                continue

            if target not in known_ids or target not in definition_target_ids:
                failures += 1

        return failures

    def _table_row_xml_nodes(self, root: ET.Element, parent_map: dict[ET.Element, ET.Element]) -> list[XmlNode]:
        nodes: list[XmlNode] = []
        for element in root.iter():
            if element.tag.split("}")[-1].lower() != "table-reference":
                continue

            table_ref_id = element.attrib.get("id") or self._slugify(clean_text(" ".join(element.itertext()))[:40])
            table_num = self._first_child_text(element, "num")
            table_title = self._first_child_text(element, "title")
            table_element = next(
                (child for child in element.iter() if child.tag.split("}")[-1].lower() == "table"),
                None,
            )
            if table_element is None:
                continue

            header_rows = self._table_section_rows(table_element, "thead")
            body_rows = self._table_section_rows(table_element, "tbody")
            headers = header_rows[0] if header_rows else []

            for index, row in enumerate(body_rows, start=1):
                values = [clean_text(value) for value in row]
                if not any(values):
                    continue
                row_text = self._table_row_text(table_num, table_title, headers, values)
                if len(row_text) < 20:
                    continue
                row_node_id = f"{table_ref_id}__row_{index}"
                context_descriptor = self._build_synthetic_context_descriptor(
                    node_id=row_node_id,
                    parent_element=element,
                    parent_map=parent_map,
                    suffix_segments=["tbody", f"row[{index}]"],
                    context_title=table_title,
                )
                nodes.append(
                    XmlNode(
                        node_id=row_node_id,
                        clause_id=row_node_id,
                        text=row_text,
                        path=f"{self._element_path(element)}/tbody/row[{index}]",
                        context_descriptor=context_descriptor,
                    )
                )
        return nodes

    def _table_section_rows(self, table_element: ET.Element, section_tag: str) -> list[list[str]]:
        rows: list[list[str]] = []
        sections = [element for element in table_element.iter() if element.tag.split("}")[-1].lower() == section_tag]
        for section in sections:
            for row in section:
                if row.tag.split("}")[-1].lower() != "row":
                    continue
                rows.append(
                    [
                        clean_text(" ".join(entry.itertext()))
                        for entry in row
                        if entry.tag.split("}")[-1].lower() == "entry"
                    ]
                )
        return rows

    def _table_row_text(
        self,
        table_num: str,
        table_title: str,
        headers: list[str],
        values: list[str],
    ) -> str:
        parts = [part for part in (table_num, table_title) if part]
        labeled_values: list[str] = []
        for index, value in enumerate(values):
            if not value:
                continue
            header = headers[index] if index < len(headers) and headers[index] else f"column_{index + 1}"
            labeled_values.append(f"{header}: {value}")
        if labeled_values:
            parts.append("; ".join(labeled_values))
        else:
            parts.extend(values)
        return clean_text(" ".join(parts))

    def _first_child_text(self, element: ET.Element, tag_name: str) -> str:
        for child in element:
            if child.tag.split("}")[-1].lower() == tag_name:
                return clean_text(" ".join(child.itertext()))
        return ""

    def _element_tag_name(self, element: ET.Element) -> str:
        return element.tag.split("}")[-1].lower()

    def _is_glossary_entry_element(self, element: ET.Element) -> bool:
        tag_name = self._element_tag_name(element)
        outputclass = clean_text(element.attrib.get("outputclass", "")).lower()
        return tag_name in _GLOSSARY_ENTRY_ROOT_TAGS or outputclass == "abcb-glossentry"

    def _glossary_term_text(self, element: ET.Element) -> str:
        if self._element_tag_name(element) == "glossterm":
            return clean_text(" ".join(element.itertext()))
        for child in element:
            if self._element_tag_name(child) == "glossterm":
                return clean_text(" ".join(child.itertext()))
        return ""

    def _glossary_definition_text(self, element: ET.Element) -> str:
        if self._element_tag_name(element) == "glossdef":
            return clean_text(" ".join(element.itertext()))
        for child in element:
            if self._element_tag_name(child) == "glossdef":
                return clean_text(" ".join(child.itertext()))
        return ""

    def _inventory_text_for_element(self, element: ET.Element) -> str:
        tag_name = self._element_tag_name(element)
        if self._is_glossary_entry_element(element):
            term = self._glossary_term_text(element)
            definition = self._glossary_definition_text(element)
            if term and definition:
                return clean_text(f"{term} means {definition}")
        if tag_name == "glossterm":
            return self._glossary_term_text(element)
        if tag_name == "glossdef":
            return self._glossary_definition_text(element)
        return clean_text(" ".join(part for part in element.itertext()))

    def _should_skip_inventory_for_element(
        self,
        element: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
    ) -> bool:
        tag_name = self._element_tag_name(element)
        if tag_name not in _GLOSSARY_CHILD_TAGS:
            return False
        current = parent_map.get(element)
        while current is not None:
            if self._is_glossary_entry_element(current):
                return True
            current = parent_map.get(current)
        return False

    def _semantic_unit_from_element(
        self,
        *,
        element: ET.Element,
        node_id: str,
        path: str,
        text: str,
        context_descriptor: XmlContextDescriptor | None = None,
    ) -> dict[str, Any] | None:
        if self._is_glossary_entry_element(element):
            term = self._glossary_term_text(element)
            definition = self._glossary_definition_text(element)
            return {
                "unit_id": f"unit:{node_id}",
                "node_id": node_id,
                "semantic_class": "definition",
                "title": term or self._review_title(text, "", node_id),
                "text": text,
                "path": path,
                "full_path": context_descriptor.full_path if context_descriptor is not None else path,
                "context_descriptor": asdict(context_descriptor) if context_descriptor is not None else None,
                "glossary_term": term,
                "glossary_definition": definition,
                "schema_family_id": "abcb_glossentry",
            }
        return self._semantic_unit_from_parts(
            node_id=node_id,
            path=path,
            text=text,
            context_descriptor=context_descriptor,
        )

    def _dedupe_semantic_units(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for unit in units:
            unit_id = str(unit.get("unit_id") or "")
            if not unit_id or unit_id in deduped:
                continue
            deduped[unit_id] = unit
        return list(deduped.values())

    def _detect_xml_schema_family(self, root: ET.Element) -> dict[str, Any]:
        return self.schema_registry.match_against_approved_registry(root)

    def _build_document_family_id(self, *, pdf_name: str, xml_name: str) -> str:
        pdf_stem = re.sub(r"\.pdf$", "", pdf_name, flags=re.IGNORECASE)
        xml_stem = re.sub(r"\.xml$", "", xml_name, flags=re.IGNORECASE)
        pdf_slug = self._slugify(pdf_stem)
        xml_slug = self._slugify(xml_stem)
        common_tokens = [
            token
            for token in pdf_slug.split("_")
            if token and token in xml_slug.split("_")
        ]
        if common_tokens:
            candidate = "_".join(common_tokens[:8])
        else:
            candidate = f"{pdf_slug}__{xml_slug}"
        return self._bounded_document_family_id(candidate)

    def _bounded_document_family_id(self, candidate: str) -> str:
        if len(candidate) <= MAX_DOCUMENT_FAMILY_ID_LENGTH:
            return candidate
        digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:12]
        prefix_length = MAX_DOCUMENT_FAMILY_ID_LENGTH - len(digest) - 1
        prefix = candidate[:prefix_length].rstrip("_") or "document_family"
        return f"{prefix}_{digest}"

    def _baseline_semantic_unit_eligible(self, unit: dict[str, Any]) -> bool:
        """Deterministic inclusion predicate for foundational baseline slice (inspectable, low-risk)."""
        cls = str(unit.get("semantic_class") or "").lower()
        if cls in _BASELINE_SEMANTIC_CLASSES:
            return True
        path = str(unit.get("path") or "").lower()
        return any(marker in path for marker in _BASELINE_PATH_MARKERS)

    def _baseline_category_for_unit(self, unit: dict[str, Any]) -> str:
        cls = str(unit.get("semantic_class") or "").lower()
        path = str(unit.get("path") or "").lower()
        if cls == "definition" or "/definition" in path:
            return "glossary_definition"
        if cls in {"title", "context_key"} or "/title" in path or "/num" in path:
            return "title_or_context"
        if cls == "note" or any(m in path for m in ("intro-part", "intro", "subtitle")):
            return "interpretive_structure"
        return "interpretive_structure"

    def _build_foundational_baseline_corpus_slice(
        self,
        *,
        semantic_units: list[dict[str, Any]],
        candidate_objects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cand_by_node = {str(c.get("xml_node_id")): c for c in candidate_objects if c.get("xml_node_id")}
        eligible_units = [u for u in semantic_units if self._baseline_semantic_unit_eligible(u)]
        eligible_ids = {str(u.get("node_id")) for u in eligible_units}

        items: list[dict[str, Any]] = []
        for unit in sorted(eligible_units, key=lambda u: str(u.get("node_id") or "")):
            nid = str(unit.get("node_id") or "")
            cand = cand_by_node.get(nid, {})
            evidence = list(cand.get("evidence") or [])
            primary = evidence[0] if evidence else {}
            items.append(
                {
                    "candidate_id": cand.get("candidate_id"),
                    "node_id": nid,
                    "semantic_unit_id": unit.get("unit_id"),
                    "baseline_category": self._baseline_category_for_unit(unit),
                    "title": unit.get("title") or cand.get("title"),
                    "semantic_class": unit.get("semantic_class"),
                    "validation_state": cand.get("validation_state"),
                    "status": cand.get("status"),
                    "text_preview": clean_text(str(unit.get("text") or ""))[:400],
                    "evidence": {
                        "primary_fragment_id": primary.get("fragment_id"),
                        "primary_page": cand.get("page") or primary.get("page"),
                        "has_pdf_evidence": bool(primary.get("fragment_id")),
                        "evidence_packet_count": len(evidence),
                    },
                }
            )
            if len(items) >= _MAX_BASELINE_CORPUS_ITEMS:
                break

        eligible_count = len(eligible_ids)
        included = len(items)
        coverage = ratio(included, max(eligible_count, 1))

        return {
            "schema_version": "1",
            "generated_at": utc_now_iso(),
            "summary": {
                "eligible_semantic_unit_count": eligible_count,
                "included_item_count": included,
                "truncated": eligible_count > included,
                "coverage_ratio": round(coverage, 4),
            },
            "items": items,
        }

    def _build_candidate_quality_metrics(
        self,
        *,
        semantic_units: list[dict[str, Any]],
        pdf_evidence_packets: list[dict[str, Any]],
        candidate_objects: list[dict[str, Any]],
        review_units: list[dict[str, Any]],
        canonical_snippets: list[dict[str, Any]],
        foundational_baseline_corpus: dict[str, Any],
        candidate_validation_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        baseline_summary = foundational_baseline_corpus.get("summary") if isinstance(foundational_baseline_corpus, dict) else {}
        validation_results = list(candidate_validation_results or [])
        return {
            "schema_version": "1",
            "generated_at": utc_now_iso(),
            "semantic_unit_count": len(semantic_units),
            "pdf_evidence_packet_count": len(pdf_evidence_packets),
            "candidate_object_count": len(candidate_objects),
            "review_unit_count": len(review_units),
            "promoted_snippet_count": len(canonical_snippets),
            "candidate_validation_result_count": len(validation_results),
            "candidate_validation_pass_count": sum(1 for item in validation_results if item.get("validation_state") == "pass"),
            "candidate_validation_requires_review_count": sum(
                1 for item in validation_results if item.get("validation_state") == "requires_review"
            ),
            "candidate_validation_fail_count": sum(1 for item in validation_results if item.get("validation_state") == "fail"),
            "promotion_eligible_candidate_count": sum(1 for item in validation_results if item.get("promotion_eligible")),
            "foundational_baseline_eligible_count": int(baseline_summary.get("eligible_semantic_unit_count") or 0),
            "foundational_baseline_included_count": int(baseline_summary.get("included_item_count") or 0),
            "foundational_baseline_coverage_ratio": float(baseline_summary.get("coverage_ratio") or 0.0),
        }

    def _validation_status_allows_graph_inspection(self, validation: dict[str, Any]) -> bool:
        status = str(validation.get("overall_status") or "")
        if not status:
            return True
        return status in {"PASS", "PASS_WITH_WARNINGS", "NOT_PROVIDED", "REFERENCE_ONLY"}

    def _semantic_inventory_mode(self, semantic_units: list[dict[str, Any]]) -> str:
        if semantic_units and all(str(unit.get("source_kind") or "") == "pdf" for unit in semantic_units):
            return "pdf_only"
        return "xml"

    def _build_graph_readiness_summary(
        self,
        *,
        enrichment_summary: dict[str, Any],
        xml_validation: dict[str, Any],
        pdf_validation: dict[str, Any],
        candidate_quality: dict[str, Any],
        candidate_validation_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        unresolved_blocking = int(enrichment_summary.get("unresolved_blocking_count") or 0)
        unresolved_text_relations = int(enrichment_summary.get("text_unresolved_relation_count") or 0)
        reconciliation_review_required = int(enrichment_summary.get("reconciliation_review_required_count") or 0)
        su_count = int(candidate_quality.get("semantic_unit_count") or 0)
        cand_count = int(candidate_quality.get("candidate_object_count") or 0)
        promoted_count = int(candidate_quality.get("promoted_snippet_count") or 0)
        promotable_count = int(candidate_quality.get("promotion_eligible_candidate_count") or 0)
        baseline_eligible = int(candidate_quality.get("foundational_baseline_eligible_count") or 0)
        baseline_included = int(candidate_quality.get("foundational_baseline_included_count") or 0)
        validation_summary = candidate_validation_summary or {}
        validation_blocking = int(validation_summary.get("requires_review_count") or 0) + int(
            validation_summary.get("fail_count") or 0
        )

        gates: list[dict[str, Any]] = [
            {
                "gate_id": "explicit_relations_non_blocking",
                "passed": unresolved_blocking == 0,
                "detail": f"unresolved_blocking_count={unresolved_blocking}",
            },
            {
                "gate_id": "query_relations_resolved_or_reviewed",
                "passed": unresolved_text_relations == 0,
                "detail": f"text_unresolved_relation_count={unresolved_text_relations}",
            },
            {
                "gate_id": "reconciliation_pressure_clear",
                "passed": reconciliation_review_required == 0,
                "detail": f"reconciliation_review_required_count={reconciliation_review_required}",
            },
            {
                "gate_id": "semantic_inventory_present",
                "passed": su_count > 0,
                "detail": f"semantic_unit_count={su_count}",
            },
            {
                "gate_id": "candidate_layer_present",
                "passed": cand_count > 0,
                "detail": f"candidate_object_count={cand_count}",
            },
            {
                "gate_id": "candidate_validation_non_blocking",
                "passed": validation_blocking == 0,
                "detail": f"candidate_validation_blocking_count={validation_blocking}",
            },
            {
                "gate_id": "xml_validation_allows_inspection",
                "passed": self._validation_status_allows_graph_inspection(xml_validation),
                "detail": f"overall_status={xml_validation.get('overall_status')!r}",
            },
            {
                "gate_id": "pdf_validation_allows_inspection",
                "passed": self._validation_status_allows_graph_inspection(pdf_validation),
                "detail": f"overall_status={pdf_validation.get('overall_status')!r}",
            },
            {
                "gate_id": "foundational_baseline_slice_present_or_empty_doc",
                "passed": baseline_eligible == 0 or baseline_included > 0,
                "detail": f"eligible={baseline_eligible} included={baseline_included}",
            },
            {
                "gate_id": "snippet_promotion_consistent",
                "passed": promoted_count <= promotable_count,
                "detail": f"promoted={promoted_count} promotable={promotable_count}",
            },
        ]
        passed_all = all(bool(g.get("passed")) for g in gates)
        return {
            "schema_version": "1",
            "generated_at": utc_now_iso(),
            "ready_for_graph_handoff": passed_all,
            "gates": gates,
            "metrics_echo": {
                "unresolved_blocking_count": unresolved_blocking,
                "text_unresolved_relation_count": unresolved_text_relations,
                "reconciliation_review_required_count": reconciliation_review_required,
                "semantic_unit_count": su_count,
                "candidate_object_count": cand_count,
                "candidate_validation_blocking_count": validation_blocking,
                "promoted_snippet_count": promoted_count,
                "promotable_candidate_count": promotable_count,
                "foundational_baseline_eligible_count": baseline_eligible,
                "foundational_baseline_included_count": baseline_included,
            },
        }

    def _semantic_enrichment_field_authority(self) -> dict[str, str]:
        """Static provenance map: XML-backed vs heuristic enrichment (additive; top-level fields unchanged)."""
        return {
            "explicit_relations": "xml_authoritative",
            "glossary_links": "heuristic_glossary_match",
            "applicability_conditions": "heuristic_pattern",
            "implicit_relation_candidates": "heuristic_text",
            "defined_terms_used": "derived_from_heuristic_glossary_match",
            "unresolved_terms": "heuristic_glossary_match",
        }

    def _build_review_workspace(
        self,
        *,
        pdf_name: str,
        xml_name: str,
        xml_nodes: list[XmlNode],
        semantic_units: list[dict[str, Any]] | None = None,
        fragments: list[PdfFragment],
        structured_blocks: list[dict[str, Any]] | None = None,
        assembled_clauses: list[dict[str, Any]] | None = None,
        alignments: list[dict[str, Any]],
        candidates: list[dict[str, Any]] | None = None,
        canonical_snippets: list[dict[str, Any]],
        xml_validation: dict[str, Any],
        pdf_validation: dict[str, Any],
        xml_bytes: bytes | None = None,
        xml_metrics: dict[str, Any] | None = None,
        candidate_relations: list[dict[str, Any]] | None = None,
        reconciliation_records: list[dict[str, Any]] | None = None,
        candidate_validation_results: list[dict[str, Any]] | None = None,
        candidate_validation_summary: dict[str, Any] | None = None,
        graph_edges: list[dict[str, Any]] | None = None,
        enrichment_summary: dict[str, Any] | None = None,
        review_decisions: list[dict[str, Any]] | None = None,
        pdf_evidence_packets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        workspace_mode = "full"
        workspace_reason = "default_full_lineage_review"
        review_alignments = list(alignments)
        semantic_units = semantic_units or self._semantic_units_from_xml_nodes(xml_nodes)
        inventory_mode = self._semantic_inventory_mode(semantic_units)

        if inventory_mode == "pdf_only":
            workspace_mode = "pdf_only"
            workspace_reason = "pdf_native_candidate_inventory"
            review_fragment_ids = {fragment.fragment_id for fragment in fragments}
            review_node_ids: set[str] = set()
            review_xml_nodes = list(xml_nodes)
            review_fragments = list(fragments)
            review_snippets = list(canonical_snippets)
        else:
            if self._should_focus_review_workspace(xml_name=xml_name, xml_nodes=xml_nodes, fragments=fragments):
                workspace_mode = "focused"
                workspace_reason = "narrow_xml_artifact_focus"
                review_alignments = self._focused_review_alignments(alignments, xml_nodes)

            review_fragment_ids = {item["fragment_id"] for item in review_alignments}
            review_node_ids = {item["node_id"] for item in review_alignments if item.get("node_id")}
            review_xml_nodes = [node for node in xml_nodes if node.node_id in review_node_ids] if review_node_ids else []
            review_fragments = [fragment for fragment in fragments if fragment.fragment_id in review_fragment_ids]
            review_snippets = [
                snippet
                for snippet in canonical_snippets
                if snippet.get("fragment_id") in review_fragment_ids
            ]

        if pdf_evidence_packets is None:
            pdf_packets = self._build_pdf_evidence_packets(
                semantic_units=semantic_units,
                fragments=fragments,
                structured_blocks=structured_blocks,
                alignments=alignments,
                xml_validation=xml_validation,
                pdf_validation=pdf_validation,
            )
        else:
            pdf_packets = list(pdf_evidence_packets)
        if candidates is None:
            candidate_objects = self._build_candidate_objects(
                semantic_units=semantic_units,
                pdf_evidence_packets=pdf_packets,
                assembled_clauses=assembled_clauses or [],
                structured_blocks=structured_blocks,
            )
            rels: list[dict[str, Any]] = list(candidate_relations or [])
            reconciliations: list[dict[str, Any]] = list(reconciliation_records or [])
            validation_results: list[dict[str, Any]] = list(candidate_validation_results or [])
            validation_summary: dict[str, Any] = dict(candidate_validation_summary or {})
            edges: list[dict[str, Any]] = list(graph_edges or [])
            summary: dict[str, Any] = dict(enrichment_summary or {})
            if xml_bytes is not None and xml_metrics is not None:
                candidate_objects, rels, reconciliations, edges, summary = self._apply_semantic_enrichment(
                    xml_bytes=xml_bytes,
                    xml_metrics=xml_metrics,
                    semantic_units=semantic_units,
                    pdf_evidence_packets=pdf_packets,
                    candidate_objects=candidate_objects,
                )
                edges = self._append_snippet_promotion_edges(
                    graph_edges=edges,
                    candidates=candidate_objects,
                    canonical_snippets=canonical_snippets,
                )
                summary = {**summary, "graph_edge_count": len(edges)}
        else:
            candidate_objects = candidates
            rels = list(candidate_relations or [])
            reconciliations = list(reconciliation_records or [])
            validation_results = list(candidate_validation_results or [])
            validation_summary = dict(candidate_validation_summary or {})
            edges = list(graph_edges or [])
            summary = dict(enrichment_summary or {})
        candidate_objects = self._attach_clause_projections_to_candidates(
            candidates=candidate_objects,
            assembled_clauses=assembled_clauses or [],
            structured_blocks=structured_blocks,
        )
        if workspace_mode == "focused":
            review_candidates = [
                candidate
                for candidate in candidate_objects
                if candidate.get("xml_node_id") in review_node_ids
                or any(
                    evidence.get("fragment_id") in review_fragment_ids
                    for evidence in (candidate.get("evidence") or [])
                )
            ]
        else:
            review_candidates = candidate_objects
        review_units = self._build_review_units(
            candidates=review_candidates,
            canonical_snippets=review_snippets,
        )
        candidate_total = len(candidate_objects)
        candidate_surfaced = len(review_units)
        candidate_needs_review = len(
            [unit for unit in review_units if unit.get("needs_human_review")]
        )
        blocking_relation_candidates = sum(
            1
            for cand in review_candidates
            if any(rel.get("blocking") for rel in (cand.get("explicit_relations") or []))
        )
        review_required_reconciliations = sum(
            1 for record in reconciliations if record.get("review_required")
        )

        return {
            "mode": workspace_mode,
            "reason": workspace_reason,
            "xml_nodes": review_xml_nodes,
            "xml_semantic_units": semantic_units,
            "pdf_fragments": review_fragments,
            "pdf_evidence_packets": pdf_packets,
            "pdf_clause_candidates": list(assembled_clauses or []),
            "alignments": review_alignments,
            "candidates": review_candidates,
            "canonical_snippets": review_snippets,
            "review_units": review_units,
            "alignment_total": len(alignments),
            "alignment_displayed": len(review_alignments),
            "candidate_total": candidate_total,
            "candidate_surfaced": candidate_surfaced,
            "candidate_needs_review": candidate_needs_review,
            "candidate_relations": rels,
            "reconciliation_records": reconciliations,
            "candidate_validation_results": validation_results,
            "candidate_validation_summary": validation_summary,
            "review_decisions": list(review_decisions or []),
            "graph_edges": edges,
            "enrichment_summary": summary,
            "enrichment_counts": {
                "candidates_with_blocking_relations": blocking_relation_candidates,
                "review_required_reconciliations": review_required_reconciliations,
                "graph_edge_count": len(edges),
            },
        }

    def _should_focus_review_workspace(
        self,
        *,
        xml_name: str,
        xml_nodes: list[XmlNode],
        fragments: list[PdfFragment],
    ) -> bool:
        normalized_xml_name = self._slugify(xml_name)
        narrow_artifact_prefixes = ("table_", "image_", "figure_", "diagram_", "map_")
        if not normalized_xml_name.startswith(narrow_artifact_prefixes):
            return False
        return (
            len(xml_nodes) <= REVIEW_WORKSPACE_NARROW_XML_NODE_LIMIT
            and len(fragments) >= REVIEW_WORKSPACE_LARGE_FRAGMENT_LIMIT
        )

    def _focused_review_alignments(
        self,
        alignments: list[dict[str, Any]],
        xml_nodes: list[XmlNode],
    ) -> list[dict[str, Any]]:
        node_lookup = {node.node_id: node for node in xml_nodes}
        by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for alignment in alignments:
            node_id = alignment.get("node_id")
            if not alignment.get("matched") or not node_id:
                continue
            by_node[str(node_id)].append(alignment)

        selected: list[dict[str, Any]] = []
        ranked_groups = sorted(
            by_node.items(),
            key=lambda item: self._review_group_priority(item[0], item[1], node_lookup),
            reverse=True,
        )
        for node_id, node_alignments in ranked_groups:
            ranked = sorted(
                node_alignments,
                key=lambda item: self._review_alignment_priority(item, node_lookup.get(node_id)),
                reverse=True,
            )
            selected.extend(ranked[:REVIEW_WORKSPACE_MAX_ALIGNMENTS_PER_NODE])
        row_selected = [alignment for alignment in selected if self._is_row_node_id(str(alignment.get("node_id") or ""))]
        if row_selected:
            return row_selected
        return selected

    def _build_review_units(
        self,
        *,
        candidates: list[dict[str, Any]],
        canonical_snippets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        approved_candidate_ids = {
            str(snippet.get("candidate_id"))
            for snippet in canonical_snippets
            if snippet.get("candidate_id")
        }

        review_units: list[dict[str, Any]] = []
        for candidate in candidates:
            evidence = candidate.get("evidence") or []
            primary_evidence = evidence[0] if evidence else {}
            approved = candidate.get("candidate_id") in approved_candidate_ids
            review_decision_status = str(candidate.get("review", {}).get("human_decision_status") or "")
            base_status = (
                "approved"
                if approved
                else review_decision_status or str(candidate.get("review", {}).get("base_status") or "review required")
            )
            review_units.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "title": candidate.get("title"),
                    "candidate_type": candidate.get("candidate_type"),
                    "xml_structural_class": candidate.get("xml_structural_class"),
                    "pdf_evidence_class": primary_evidence.get("pdf_evidence_class", "unknown"),
                    "candidate_semantic_class": candidate.get("candidate_semantic_class"),
                    "confidence": float(candidate.get("confidence", {}).get("overall", 0.0)),
                    "base_status": base_status,
                    "needs_human_review": bool(candidate.get("review", {}).get("needs_human_review", False)) and not approved,
                    "review_issue_class": candidate.get("review", {}).get("issue_class", "clean_match"),
                    "review_source_emphasis": candidate.get("review", {}).get("source_emphasis", "balanced"),
                    "matched": bool(evidence),
                    "page": primary_evidence.get("page"),
                    "fragment_id": primary_evidence.get("fragment_id") or f"xml_only:{candidate.get('xml_node_id')}",
                    "node_id": candidate.get("xml_node_id"),
                    "xml_path": candidate.get("xml_path") or "No XML node linked yet",
                    "xml_text": candidate.get("xml_text") or "",
                    "pdf_text": primary_evidence.get("text", ""),
                    "bbox": primary_evidence.get("bbox", []),
                    "issues": candidate.get("review", {}).get("issues", []),
                    "xml_only_terms": candidate.get("review", {}).get("xml_only_terms", []),
                    "pdf_only_terms": candidate.get("review", {}).get("pdf_only_terms", []),
                    "raw_xml_only_terms": candidate.get("review", {}).get("raw_xml_only_terms", []),
                    "raw_pdf_only_terms": candidate.get("review", {}).get("raw_pdf_only_terms", []),
                    "ignored_structural_terms": candidate.get("review", {}).get("ignored_structural_terms", []),
                    "validation_state": candidate.get("validation_state"),
                    "classification": candidate.get("classification"),
                    "promotion_eligible": bool(candidate.get("promotion_eligible", False)),
                    "review_decision_status": review_decision_status or None,
                    "explicit_relations_count": len(candidate.get("explicit_relations") or []),
                    "glossary_links_count": len(candidate.get("glossary_links") or []),
                    "enrichment_summary": candidate.get("review", {}).get("enrichment_summary"),
                    "enrichment_issue_class": candidate.get("review", {}).get("enrichment_issue_class"),
                }
            )
        return review_units

    def _review_issue_class(
        self,
        *,
        alignment: dict[str, Any],
        linked_issue: bool,
        xml_only_terms: list[str],
        pdf_only_terms: list[str],
    ) -> str:
        if not alignment.get("matched") or not alignment.get("node_id"):
            return "unmatched"
        if linked_issue:
            return "validation"
        if float(alignment.get("confidence", 0.0)) < 0.9:
            return "low_confidence"
        if xml_only_terms and pdf_only_terms:
            return "mixed_mismatch"
        if xml_only_terms:
            return "xml_mismatch"
        if pdf_only_terms:
            return "pdf_mismatch"
        return "clean_match"

    def _review_source_emphasis(
        self,
        *,
        xml_only_terms: list[str],
        pdf_only_terms: list[str],
    ) -> str:
        if xml_only_terms and pdf_only_terms:
            return "mixed"
        if xml_only_terms:
            return "xml"
        if pdf_only_terms:
            return "pdf"
        return "balanced"

    def _linked_review_issue_keys(
        self,
        xml_validation: dict[str, Any],
        pdf_validation: dict[str, Any],
    ) -> set[str]:
        linked_issues: set[str] = set()
        for item in [
            *(xml_validation.get("warnings") or []),
            *(xml_validation.get("errors") or []),
            *(pdf_validation.get("warnings") or []),
            *(pdf_validation.get("errors") or []),
        ]:
            if not isinstance(item, dict):
                continue
            fragment_id = item.get("fragment_id")
            node_id = item.get("node_id") or item.get("xml_node")
            if fragment_id:
                linked_issues.add(f"fragment:{fragment_id}")
            if node_id:
                linked_issues.add(f"node:{node_id}")
        return linked_issues

    def _semantic_unit_from_parts(
        self,
        *,
        node_id: str,
        path: str,
        text: str,
        context_descriptor: XmlContextDescriptor | None = None,
    ) -> dict[str, Any] | None:
        semantic_class = self._xml_structural_class(path, text)
        min_text_length = 1 if semantic_class in {"title", "context_key"} else 5
        if semantic_class == "ambiguous" or len(clean_text(text)) < min_text_length:
            return None
        return {
            "unit_id": f"unit:{node_id}",
            "node_id": node_id,
            "semantic_class": semantic_class,
            "title": self._review_title(text, "", node_id),
            "text": text,
            "path": path,
            "full_path": context_descriptor.full_path if context_descriptor is not None else path,
            "context_descriptor": asdict(context_descriptor) if context_descriptor is not None else None,
        }

    def _semantic_node_id(
        self,
        *,
        element: ET.Element,
        fallback_path: str,
        text: str,
    ) -> str | None:
        explicit_id = element.attrib.get("id") or element.attrib.get("{http://www.w3.org/XML/1998/namespace}id")
        if explicit_id:
            return explicit_id

        tag_name = element.tag.split("}")[-1].lower()
        semantic_class = self._xml_structural_class(fallback_path, text)
        if semantic_class not in {"title", "context_key", "note"}:
            return None

        digest = hashlib.sha1(fallback_path.encode("utf-8")).hexdigest()[:10]
        return f"{tag_name}_{digest}"

    def _semantic_units_from_xml_nodes(self, xml_nodes: list[XmlNode]) -> list[dict[str, Any]]:
        units = [
            unit
            for unit in (
                self._semantic_unit_from_parts(
                    node_id=node.node_id,
                    path=node.path,
                    text=node.text,
                    context_descriptor=node.context_descriptor,
                )
                for node in xml_nodes
            )
            if unit is not None
        ]
        return self._dedupe_semantic_units(units)

    def _build_pdf_candidate_units(
        self,
        *,
        structured_blocks: list[dict[str, Any]],
        assembled_clauses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        units: list[dict[str, Any]] = []
        covered_block_ids: set[str] = set()

        for clause in assembled_clauses:
            anchor = clause.get("anchor", {}) if isinstance(clause.get("anchor"), dict) else {}
            anchor_block_id = str(anchor.get("block_id") or "")
            source_block_ids = [str(block_id) for block_id in (clause.get("source_block_ids") or []) if block_id]
            covered_block_ids.update(source_block_ids)
            text = clean_text(" ".join(str(block.get("text") or "") for block in (clause.get("body_blocks") or clause.get("rendered_blocks") or [])))
            semantic_class = (
                "title"
                if str(anchor.get("block_type") or "") == "heading" or self._looks_like_structural_document_heading(str(clause.get("title_or_lead") or ""))
                else "rule"
            )
            clause_code = clean_text(str(clause.get("clause_code") or "")) or None
            heading_text = clean_text(str(clause.get("heading_text") or "")) or None
            title = self._assembled_clause_candidate_title(
                clause_code=clause_code,
                heading_text=heading_text,
                title_or_lead=str(clause.get("candidate_title") or clause.get("title_or_lead") or ""),
                fallback_text=text,
                fallback_id=anchor_block_id,
            )
            units.append(
                {
                    "unit_id": f"pdf_clause:{anchor_block_id}",
                    "node_id": None,
                    "semantic_class": semantic_class,
                    "title": title,
                    "text": text or title,
                    "path": f"/pdf/clause[{anchor_block_id}]",
                    "full_path": f"/pdf/clause[{anchor_block_id}]",
                    "context_descriptor": None,
                    "source_kind": "pdf",
                    "anchor_block_id": anchor_block_id,
                    "source_block_ids": source_block_ids or ([anchor_block_id] if anchor_block_id else []),
                    "pages": list(clause.get("pages") or []),
                    "bbox": list(clause.get("bbox") or []),
                    "pdf_evidence_class": str(anchor.get("block_type") or "paragraph"),
                    "clause_code": clause_code,
                    "heading_text": heading_text,
                    "structural_path": list(clause.get("structural_path") or []),
                }
            )

        if units:
            uncovered_blocks = [
                block
                for block in structured_blocks
                if str(block.get("block_id") or "") not in covered_block_ids
                and str(block.get("block_type") or "") in {"heading", "paragraph", "list_item"}
                and clean_text(str(block.get("text") or ""))
                and not self._is_editorial_marginalia_text(str(block.get("text") or ""))
                and not self._is_page_frame_block(block)
            ]
        else:
            uncovered_blocks = [
                block
                for block in structured_blocks
                if str(block.get("block_type") or "") in {"heading", "paragraph", "list_item"}
                and clean_text(str(block.get("text") or ""))
                and not self._is_editorial_marginalia_text(str(block.get("text") or ""))
                and not self._is_page_frame_block(block)
            ]

        for block in uncovered_blocks:
            block_id = str(block.get("block_id") or "")
            text = clean_text(str(block.get("text") or ""))
            semantic_class = "title" if str(block.get("block_type") or "") == "heading" else "rule"
            units.append(
                {
                    "unit_id": f"pdf_block:{block_id}",
                    "node_id": None,
                    "semantic_class": semantic_class,
                    "title": text[:160] or block_id,
                    "text": text,
                    "path": f"/pdf/block[{block_id}]",
                    "full_path": f"/pdf/block[{block_id}]",
                    "context_descriptor": None,
                    "source_kind": "pdf",
                    "anchor_block_id": block_id,
                    "source_block_ids": [block_id],
                    "pages": [int(block.get("page") or 0)] if block.get("page") else [],
                    "bbox": list(block.get("bbox") or []),
                    "pdf_evidence_class": str(block.get("block_type") or "paragraph"),
                    "structural_path": [],
                }
            )

        return units

    def _build_pdf_native_evidence_packets(
        self,
        *,
        units: list[dict[str, Any]],
        fragments: list[PdfFragment],
        structured_blocks: list[dict[str, Any]] | None,
        pdf_validation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        fragment_by_id = {fragment.fragment_id: fragment for fragment in fragments}
        block_by_id = {
            str(block.get("block_id")): block
            for block in (structured_blocks or [])
            if isinstance(block, dict) and block.get("block_id")
        }
        linked_issues = self._linked_review_issue_keys({}, pdf_validation)
        packets: list[dict[str, Any]] = []
        for unit in units:
            evidence_fragments: list[dict[str, Any]] = []
            source_block_ids = [str(block_id) for block_id in (unit.get("source_block_ids") or []) if block_id]
            unit_confidence = float(unit.get("confidence") or 0.95)
            for block_id in source_block_ids:
                fragment = fragment_by_id.get(block_id)
                if fragment is None:
                    continue
                evidence_fragments.append(
                    {
                        "fragment_id": fragment.fragment_id,
                        "page": fragment.page,
                        "bbox": fragment.bbox,
                        "text": fragment.text,
                        "confidence": unit_confidence,
                        "pdf_evidence_class": self._pdf_evidence_class(fragment, block_by_id.get(fragment.fragment_id)),
                        "matched": True,
                    }
                )
            packets.append(
                {
                    "unit_id": unit["unit_id"],
                    "node_id": None,
                    "linked_issue": any(f"fragment:{evidence['fragment_id']}" in linked_issues for evidence in evidence_fragments),
                    "evidence_fragments": evidence_fragments,
                }
            )
        return packets

    def _build_pdf_evidence_packets(
        self,
        *,
        semantic_units: list[dict[str, Any]],
        fragments: list[PdfFragment],
        structured_blocks: list[dict[str, Any]] | None,
        alignments: list[dict[str, Any]],
        xml_validation: dict[str, Any],
        pdf_validation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        fragment_by_id = {fragment.fragment_id: fragment for fragment in fragments}
        block_by_id = {
            str(block.get("block_id")): block
            for block in (structured_blocks or [])
            if isinstance(block, dict) and block.get("block_id")
        }
        linked_issues = self._linked_review_issue_keys(xml_validation, pdf_validation)
        by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for alignment in alignments:
            node_id = alignment.get("node_id")
            if alignment.get("matched") and node_id:
                by_node[str(node_id)].append(alignment)

        packets: list[dict[str, Any]] = []
        for unit in semantic_units:
            node_id = str(unit["node_id"])
            aligned_items = sorted(
                by_node.get(node_id, []),
                key=lambda item: (float(item.get("confidence", 0.0)), str(item.get("fragment_id", ""))),
                reverse=True,
            )
            evidence_fragments: list[dict[str, Any]] = []
            for item in aligned_items:
                fragment = fragment_by_id.get(str(item.get("fragment_id") or ""))
                if fragment is None:
                    continue
                evidence_fragments.append(
                    {
                        "fragment_id": fragment.fragment_id,
                        "page": item.get("page", fragment.page),
                        "bbox": item.get("bbox", fragment.bbox),
                        "text": fragment.text,
                        "confidence": float(item.get("confidence", 0.0)),
                        "pdf_evidence_class": self._pdf_evidence_class(fragment, block_by_id.get(fragment.fragment_id)),
                        "matched": bool(item.get("matched")),
                    }
                )
            linked_issue = f"node:{node_id}" in linked_issues or any(
                f"fragment:{evidence['fragment_id']}" in linked_issues for evidence in evidence_fragments
            )
            packets.append(
                {
                    "unit_id": unit["unit_id"],
                    "node_id": node_id,
                    "linked_issue": linked_issue,
                    "evidence_fragments": evidence_fragments,
                }
            )
        return packets

    def _build_candidate_objects(
        self,
        *,
        semantic_units: list[dict[str, Any]],
        pdf_evidence_packets: list[dict[str, Any]],
        assembled_clauses: list[dict[str, Any]] | None = None,
        structured_blocks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        packet_by_unit_id = {packet["unit_id"]: packet for packet in pdf_evidence_packets}
        candidates: list[dict[str, Any]] = []
        for unit in semantic_units:
            packet = packet_by_unit_id.get(unit["unit_id"], {"evidence_fragments": [], "linked_issue": False})
            evidence = list(packet.get("evidence_fragments") or [])
            primary_evidence = evidence[0] if evidence else {}
            context_descriptor = dict(unit.get("context_descriptor") or {})
            pdf_text = str(primary_evidence.get("text") or "")
            inventory_mode = str(unit.get("source_kind") or "xml")
            if inventory_mode == "pdf":
                raw_xml_only_terms: list[str] = []
                raw_pdf_only_terms: list[str] = []
                xml_only_terms = []
                pdf_only_terms = []
                ignored_structural_terms = []
                alignment_like = {
                    "matched": bool(primary_evidence),
                    "node_id": primary_evidence.get("fragment_id") if primary_evidence else None,
                    "confidence": float(primary_evidence.get("confidence", 0.0) or 0.95),
                }
                issues = []
                if not primary_evidence:
                    issues.append("No PDF evidence fragment was linked to this PDF-native candidate.")
                if bool(packet.get("linked_issue")):
                    issues.append("PDF validation warnings or errors reference this candidate.")
                review_issue_class = "clean_match" if primary_evidence else "unmatched"
                review_source_emphasis = "pdf"
                base_status = "match" if primary_evidence else "review required"
            else:
                raw_xml_only_terms, raw_pdf_only_terms = self._review_term_deltas(unit["text"], pdf_text)
                xml_only_terms, pdf_only_terms, ignored_structural_terms = self._effective_review_term_deltas(
                    xml_only_terms=raw_xml_only_terms,
                    pdf_only_terms=raw_pdf_only_terms,
                    candidate_semantic_class=unit["semantic_class"],
                )
                alignment_like = {
                    "matched": bool(primary_evidence),
                    "node_id": unit["node_id"] if primary_evidence else None,
                    "confidence": float(primary_evidence.get("confidence", 0.0)),
                }
                issues = self._build_review_issues(
                    alignment=alignment_like,
                    xml_only_terms=xml_only_terms,
                    pdf_only_terms=pdf_only_terms,
                    linked_issue=bool(packet.get("linked_issue")),
                )
                review_issue_class = self._review_issue_class(
                    alignment=alignment_like,
                    linked_issue=bool(packet.get("linked_issue")),
                    xml_only_terms=xml_only_terms,
                    pdf_only_terms=pdf_only_terms,
                )
                review_source_emphasis = self._review_source_emphasis(
                    xml_only_terms=xml_only_terms,
                    pdf_only_terms=pdf_only_terms,
                )
                base_status = self._derive_review_base_status(
                    alignment=alignment_like,
                    issues=issues,
                    approved=False,
                    candidate_semantic_class=unit["semantic_class"],
                )
            validation_state = "pass" if base_status == "match" else "requires_review"
            overall_confidence = float(primary_evidence.get("confidence", 0.0) or (0.95 if inventory_mode == "pdf" else 0.0))
            candidates.append(
                {
                    "candidate_id": f"candidate:{unit['unit_id']}",
                    "semantic_unit_id": unit["unit_id"],
                    "xml_node_id": unit["node_id"],
                    "candidate_origin": inventory_mode,
                    "schema_family_id": unit.get("schema_family_id"),
                    "glossary_term": unit.get("glossary_term"),
                    "glossary_definition": unit.get("glossary_definition"),
                    "title": unit["title"],
                    "candidate_type": unit["semantic_class"],
                    "xml_structural_class": unit["semantic_class"],
                    "candidate_semantic_class": unit["semantic_class"],
                    "xml_path": unit["path"] if inventory_mode != "pdf" else None,
                    "xml_full_path": unit.get("full_path") if inventory_mode != "pdf" else None,
                    "xml_parent_node_id": context_descriptor.get("parent_node_id"),
                    "xml_root_node_id": context_descriptor.get("root_node_id"),
                    "xml_ancestor_node_ids": list(context_descriptor.get("ancestor_node_ids") or []),
                    "xml_ancestor_tags": list(context_descriptor.get("ancestor_tags") or []),
                    "xml_context_path_signature": context_descriptor.get("context_path_signature"),
                    "xml_context_descriptor": context_descriptor or None,
                    "xml_text": unit["text"] if inventory_mode != "pdf" else "",
                    "pdf_unit_text": unit["text"],
                    "pdf_anchor_block_id": unit.get("anchor_block_id"),
                    "pdf_clause_code": unit.get("clause_code"),
                    "pdf_heading_text": unit.get("heading_text"),
                    "pdf_structural_path": list(unit.get("structural_path") or []),
                    "source_block_ids": list(unit.get("source_block_ids") or []),
                    "status": "validated" if validation_state == "pass" else "draft",
                    "validation_state": validation_state,
                    "confidence": {
                        "overall": overall_confidence,
                        "sources": {
                            "alignment": overall_confidence if inventory_mode != "pdf" else 0.0,
                            "structure": 1.0 if unit["semantic_class"] != "ambiguous" else 0.0,
                        },
                    },
                    "source": {
                        "xml_node_id": unit["node_id"],
                        "pdf_fragment_id": primary_evidence.get("fragment_id"),
                        "alignment_confidence": overall_confidence,
                    },
                    "page": int(primary_evidence.get("page") or 0) or None,
                    "proposed": {
                        "snippet_id": f"snippet:{unit['unit_id']}",
                        "display_name": unit["title"],
                        "description": unit["text"][:160],
                        "content": pdf_text or unit["text"],
                    },
                    "evidence": evidence,
                    "review": {
                        "base_status": base_status,
                        "needs_human_review": base_status in {"review required", "mismatch", "paused", "ambiguous"},
                        "issue_class": review_issue_class,
                        "source_emphasis": review_source_emphasis,
                        "issues": issues,
                        "xml_only_terms": xml_only_terms,
                        "pdf_only_terms": pdf_only_terms,
                        "raw_xml_only_terms": raw_xml_only_terms,
                        "raw_pdf_only_terms": raw_pdf_only_terms,
                        "ignored_structural_terms": ignored_structural_terms,
                    },
                    "depends_on": [],
                }
            )
        return self._attach_clause_projections_to_candidates(
            candidates=candidates,
            assembled_clauses=assembled_clauses or [],
            structured_blocks=structured_blocks,
        )

    def _can_progress_to_candidate_promotion(self, pdf_validation: dict[str, Any]) -> bool:
        gate_decision = pdf_validation.get("gate_decision") if isinstance(pdf_validation, dict) else {}
        return bool((gate_decision or {}).get("can_progress_to_semantic_layer"))

    def _run_candidate_runtime(
        self,
        *,
        xml_bytes: bytes | None,
        xml_metrics: dict[str, Any],
        semantic_units: list[dict[str, Any]],
        pdf_evidence_packets: list[dict[str, Any]],
        candidate_objects: list[dict[str, Any]],
        can_progress_to_semantic_layer: bool,
        review_decisions: list[dict[str, Any]] | None,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any],
        list[dict[str, Any]],
        dict[str, Any],
        list[dict[str, Any]],
    ]:
        (
            candidate_objects,
            candidate_relations,
            reconciliation_records,
            graph_edges,
            enrichment_summary,
        ) = self._apply_semantic_enrichment(
            xml_bytes=xml_bytes,
            xml_metrics=xml_metrics,
            semantic_units=semantic_units,
            pdf_evidence_packets=pdf_evidence_packets,
            candidate_objects=candidate_objects,
        )
        (
            candidate_objects,
            candidate_relations,
            reconciliation_records,
            candidate_validation_results,
            candidate_validation_summary,
        ) = self._apply_candidate_validation_stage(
            candidate_objects=candidate_objects,
            candidate_relations=candidate_relations,
            reconciliation_records=reconciliation_records,
            review_decisions=review_decisions,
        )
        canonical_snippets = self._build_canonical_snippets(
            can_progress=can_progress_to_semantic_layer,
            candidates=candidate_objects,
            candidate_validation_results=candidate_validation_results,
        )
        graph_edges = self._append_snippet_promotion_edges(
            graph_edges=graph_edges,
            candidates=candidate_objects,
            canonical_snippets=canonical_snippets,
        )
        enrichment_summary = {
            **enrichment_summary,
            "graph_edge_count": len(graph_edges),
            "candidate_validation_blocking_count": int(candidate_validation_summary.get("requires_review_count") or 0)
            + int(candidate_validation_summary.get("fail_count") or 0),
            "promotion_eligible_count": int(candidate_validation_summary.get("promotion_eligible_count") or 0),
        }
        return (
            candidate_objects,
            candidate_relations,
            reconciliation_records,
            graph_edges,
            enrichment_summary,
            candidate_validation_results,
            candidate_validation_summary,
            canonical_snippets,
        )

    def _apply_candidate_validation_stage(
        self,
        *,
        candidate_objects: list[dict[str, Any]],
        candidate_relations: list[dict[str, Any]],
        reconciliation_records: list[dict[str, Any]],
        review_decisions: list[dict[str, Any]] | None = None,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any],
    ]:
        review_decision_by_candidate = {
            str(item.get("candidate_id") or ""): item
            for item in (review_decisions or [])
            if item.get("candidate_id")
        }
        relations_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for relation in candidate_relations:
            source_candidate_id = str(relation.get("source_candidate_id") or "")
            if source_candidate_id:
                relations_by_candidate[source_candidate_id].append(relation)
        reconciliations_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in reconciliation_records:
            for candidate_id in (record.get("source_candidate_ids") or []):
                cid = str(candidate_id or "")
                if cid:
                    reconciliations_by_candidate[cid].append(record)

        validation_results: list[dict[str, Any]] = []
        for candidate in candidate_objects:
            candidate_id = str(candidate.get("candidate_id") or "")
            source = candidate.get("source") or {}
            review = dict(candidate.get("review") or {})
            issues: list[CandidateValidationIssueRecord] = []
            candidate_origin = str(candidate.get("candidate_origin") or "xml")

            if candidate_origin != "pdf" and not candidate.get("xml_node_id"):
                issues.append(
                    CandidateValidationIssueRecord(
                        code="missing_xml_node",
                        severity="high",
                        message="Candidate is missing an XML node reference.",
                        blocking=True,
                    )
                )
            if not source.get("pdf_fragment_id"):
                issues.append(
                    CandidateValidationIssueRecord(
                        code="missing_pdf_fragment",
                        severity="medium",
                        message="Candidate has no linked PDF evidence fragment for promotion.",
                        blocking=False,
                    )
                )
            if candidate.get("validation_state") != "pass":
                issues.append(
                    CandidateValidationIssueRecord(
                        code="candidate_requires_review",
                        severity="medium",
                        message="Candidate remains in a review-required state before promotion.",
                        blocking=True,
                    )
                )
            if any(rel.get("blocking") for rel in relations_by_candidate.get(candidate_id, [])):
                issues.append(
                    CandidateValidationIssueRecord(
                        code="blocking_relation",
                        severity="high",
                        message="Candidate has one or more blocking explicit relations.",
                        blocking=True,
                    )
                )
            if any(record.get("review_required") for record in reconciliations_by_candidate.get(candidate_id, [])):
                issues.append(
                    CandidateValidationIssueRecord(
                        code="reconciliation_review_required",
                        severity="medium",
                        message="Candidate reconciliation still requires review.",
                        blocking=False,
                    )
                )

            decision = review_decision_by_candidate.get(candidate_id)
            review_override_applied = False
            review_decision_status = str((decision or {}).get("decision_status") or "") or None

            blocking_issue_count = sum(1 for issue in issues if issue.blocking)
            advisory_issue_count = len(issues) - blocking_issue_count
            final_validation_state = "pass" if blocking_issue_count == 0 else "requires_review"
            lifecycle_status = "validated" if final_validation_state == "pass" else "draft"

            if review_decision_status == "approved":
                final_validation_state = "pass"
                lifecycle_status = "validated"
                review_override_applied = blocking_issue_count > 0
            elif review_decision_status == "rejected":
                final_validation_state = "fail"
                lifecycle_status = "rejected"
                issues.append(
                    CandidateValidationIssueRecord(
                        code="review_rejected",
                        severity="high",
                        message="Candidate was rejected by human review.",
                        blocking=True,
                    )
                )
                blocking_issue_count = sum(1 for issue in issues if issue.blocking)
                advisory_issue_count = len(issues) - blocking_issue_count

            promotion_eligible = bool(
                candidate_origin != "pdf"
                and final_validation_state == "pass"
                and source.get("pdf_fragment_id")
                and candidate.get("xml_node_id")
            )

            review["needs_human_review"] = final_validation_state == "requires_review"
            if review_decision_status:
                review["human_decision_status"] = review_decision_status
                review["human_decision_note"] = (decision or {}).get("note")
                review["human_decision_updated_at"] = (decision or {}).get("updated_at")
            candidate["review"] = review
            candidate["validation_state"] = final_validation_state
            candidate["status"] = lifecycle_status
            candidate["promotion_eligible"] = promotion_eligible
            candidate["candidate_validation"] = {
                "schema_version": "1",
                "validation_state": final_validation_state,
                "lifecycle_status": lifecycle_status,
                "promotion_eligible": promotion_eligible,
                "review_override_applied": review_override_applied,
                "review_decision_status": review_decision_status,
                "issues": [issue.model_dump() for issue in issues],
            }

            for relation in relations_by_candidate.get(candidate_id, []):
                if review_decision_status:
                    relation["review_decision_status"] = review_decision_status
                    relation["review_decision_note"] = (decision or {}).get("note")
            for record in reconciliations_by_candidate.get(candidate_id, []):
                if review_decision_status:
                    record["review_decision_status"] = review_decision_status
                    record["review_decision_note"] = (decision or {}).get("note")

            validation_results.append(
                CandidateValidationRecord(
                    candidate_id=candidate_id,
                    validation_state=final_validation_state,
                    lifecycle_status=lifecycle_status,
                    promotion_eligible=promotion_eligible,
                    review_override_applied=review_override_applied,
                    review_decision_status=review_decision_status,
                    issue_count=len(issues),
                    blocking_issue_count=blocking_issue_count,
                    advisory_issue_count=advisory_issue_count,
                    issues=issues,
                ).model_dump()
            )

        summary = CandidateValidationSummaryRecord(
            candidate_count=len(validation_results),
            pass_count=sum(1 for item in validation_results if item.get("validation_state") == "pass"),
            requires_review_count=sum(
                1 for item in validation_results if item.get("validation_state") == "requires_review"
            ),
            fail_count=sum(1 for item in validation_results if item.get("validation_state") == "fail"),
            promotion_eligible_count=sum(1 for item in validation_results if item.get("promotion_eligible")),
            review_override_count=sum(1 for item in validation_results if item.get("review_override_applied")),
        ).model_dump()
        return candidate_objects, candidate_relations, reconciliation_records, validation_results, summary

    def _xml_parent_map(self, root: ET.Element) -> dict[ET.Element, ET.Element]:
        parent: dict[ET.Element, ET.Element] = {}
        for ancestor in root.iter():
            for child in ancestor:
                parent[child] = ancestor
        return parent

    def _element_identifier(self, element: ET.Element | None) -> str | None:
        if element is None:
            return None
        return element.attrib.get("id") or element.attrib.get("{http://www.w3.org/XML/1998/namespace}id")

    def _xml_ancestor_chain(
        self,
        element: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
    ) -> list[ET.Element]:
        chain: list[ET.Element] = []
        current: ET.Element | None = element
        while current is not None:
            chain.append(current)
            current = parent_map.get(current)
        return list(reversed(chain))

    def _xml_sibling_index(
        self,
        element: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
    ) -> int:
        parent = parent_map.get(element)
        if parent is None:
            return 1
        tag_name = self._element_tag_name(element)
        same_tag_siblings = [child for child in parent if self._element_tag_name(child) == tag_name]
        for index, sibling in enumerate(same_tag_siblings, start=1):
            if sibling is element:
                return index
        return 1

    def _element_full_path(
        self,
        element: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
    ) -> str:
        segments: list[str] = []
        for current in self._xml_ancestor_chain(element, parent_map):
            tag_name = self._element_tag_name(current)
            identifier = self._element_identifier(current)
            if identifier:
                safe_identifier = str(identifier).replace("'", "\\'")
                segments.append(f"{tag_name}[@id='{safe_identifier}']")
            else:
                segments.append(f"{tag_name}[{self._xml_sibling_index(current, parent_map)}]")
        return "/" + "/".join(segments)

    def _context_titles_for_chain(self, chain: list[ET.Element]) -> list[str]:
        labels: list[str] = []
        for element in chain:
            for tag_name in ("title", "num", "sptc"):
                label = self._first_child_text(element, tag_name)
                if label and label not in labels:
                    labels.append(label)
                    break
        return labels

    def _nearest_structural_ancestor(
        self,
        element: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
    ) -> ET.Element | None:
        structural_tags = {"clause", "part", "section", "definition", "table-reference", "intro-part", "table", "page"}
        current = parent_map.get(element)
        while current is not None:
            if self._element_tag_name(current) in structural_tags:
                return current
            current = parent_map.get(current)
        return None

    def _build_xml_context_descriptor(
        self,
        *,
        node_id: str,
        element: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
    ) -> XmlContextDescriptor:
        chain = self._xml_ancestor_chain(element, parent_map)
        parent = parent_map.get(element)
        ancestor_elements = chain[:-1]
        ancestor_node_ids = [
            str(identifier)
            for identifier in (self._element_identifier(ancestor) for ancestor in ancestor_elements)
            if identifier
        ]
        nearest_structural_parent = self._nearest_structural_ancestor(element, parent_map)
        return XmlContextDescriptor(
            node_id=node_id,
            full_path=self._element_full_path(element, parent_map),
            context_path_signature="/".join(self._element_tag_name(item) for item in chain),
            parent_node_id=self._element_identifier(parent),
            root_node_id=ancestor_node_ids[0] if ancestor_node_ids else self._element_identifier(element),
            ancestor_node_ids=ancestor_node_ids,
            ancestor_tags=[self._element_tag_name(item) for item in ancestor_elements],
            nearest_structural_parent_id=self._element_identifier(nearest_structural_parent),
            nearest_structural_parent_tag=self._element_tag_name(nearest_structural_parent) if nearest_structural_parent is not None else None,
            context_titles=self._context_titles_for_chain(ancestor_elements),
            depth=max(0, len(chain) - 1),
            sibling_index=self._xml_sibling_index(element, parent_map),
        )

    def _build_synthetic_context_descriptor(
        self,
        *,
        node_id: str,
        parent_element: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
        suffix_segments: list[str],
        context_title: str | None = None,
    ) -> XmlContextDescriptor:
        parent_chain = self._xml_ancestor_chain(parent_element, parent_map)
        parent_descriptor = self._build_xml_context_descriptor(node_id=node_id, element=parent_element, parent_map=parent_map)
        parent_identifier = self._element_identifier(parent_element)
        context_titles = list(parent_descriptor.context_titles)
        if context_title:
            normalized_title = clean_text(context_title)
            if normalized_title and normalized_title not in context_titles:
                context_titles.append(normalized_title)
        return XmlContextDescriptor(
            node_id=node_id,
            full_path=f"{parent_descriptor.full_path}/{'/'.join(suffix_segments)}",
            context_path_signature="/".join([*(self._element_tag_name(item) for item in parent_chain), *suffix_segments]),
            parent_node_id=parent_identifier,
            root_node_id=parent_descriptor.root_node_id,
            ancestor_node_ids=[*parent_descriptor.ancestor_node_ids, *([str(parent_identifier)] if parent_identifier else [])],
            ancestor_tags=[*(self._element_tag_name(item) for item in parent_chain)],
            nearest_structural_parent_id=parent_identifier or parent_descriptor.nearest_structural_parent_id,
            nearest_structural_parent_tag=self._element_tag_name(parent_element),
            context_titles=context_titles,
            depth=parent_descriptor.depth + len(suffix_segments),
            sibling_index=1,
        )

    def _nearest_xml_id(
        self,
        element: ET.Element | None,
        parent_map: dict[ET.Element, ET.Element],
    ) -> str | None:
        current: ET.Element | None = element
        while current is not None:
            eid = self._element_identifier(current)
            if eid:
                return str(eid)
            current = parent_map.get(current)
        return None

    def _collect_explicit_xml_relations(self, root: ET.Element) -> tuple[list[dict[str, Any]], set[str]]:
        """Derive explicit ref/href/target/rid edges and structural parent links where both ends have ids."""
        all_ids: set[str] = set()
        for element in root.iter():
            eid = element.attrib.get("id") or element.attrib.get("{http://www.w3.org/XML/1998/namespace}id")
            if eid:
                all_ids.add(str(eid))

        parent_map = self._xml_parent_map(root)
        relations: list[dict[str, Any]] = []

        for element in root.iter():
            tag_name = element.tag.split("}")[-1].lower()
            for key in ("ref", "href", "target", "rid"):
                raw = element.attrib.get(key)
                if not raw:
                    continue
                target = self._extract_local_reference_target(key, raw)
                if not target:
                    continue
                if tag_name in {"xref", "ref"}:
                    parent_el = parent_map.get(element)
                    source_id = (
                        self._nearest_xml_id(parent_el, parent_map)
                        if parent_el is not None
                        else self._nearest_xml_id(element, parent_map)
                    )
                else:
                    source_id = self._nearest_xml_id(element, parent_map)
                if not source_id:
                    continue
                resolved = target in all_ids
                relations.append(
                    {
                        "relation_id": f"xref:{source_id}:{key}:{target}",
                        "relation_kind": "xref_attribute",
                        "relation_authority": "xml_explicit",
                        "source_node_id": source_id,
                        "target_node_id": target,
                        "target_locator": target,
                        "resolution_status": "resolved" if resolved else "unresolved",
                        "attrib_key": key,
                        "raw_value": clean_text(raw)[:500],
                        "resolved": resolved,
                        "blocking": not resolved,
                        "confidence": 1.0 if resolved else 0.0,
                        "provenance": {
                            "source_authority": "xml_authoritative",
                            "source_fields": [key],
                            "evidence_fragment_ids": [],
                            "evidence_spans": [clean_text(raw)[:200]],
                        },
                    }
                )

        structural_tags = {"clause", "part", "section", "definition", "table-reference", "intro-part", "table"}
        for element in root.iter():
            eid = element.attrib.get("id") or element.attrib.get("{http://www.w3.org/XML/1998/namespace}id")
            if not eid:
                continue
            tag_name = element.tag.split("}")[-1].lower()
            parent = parent_map.get(element)
            if parent is None:
                continue
            parent_tag = parent.tag.split("}")[-1].lower()
            if tag_name not in structural_tags and parent_tag not in structural_tags:
                continue
            parent_id = self._nearest_xml_id(parent, parent_map)
            if not parent_id or parent_id == eid:
                continue
            relations.append(
                {
                    "relation_id": f"struct:child:{eid}",
                    "relation_kind": "structural_parent",
                    "relation_authority": "xml_explicit",
                    "source_node_id": eid,
                    "target_node_id": parent_id,
                    "target_locator": parent_id,
                    "resolution_status": "resolved" if parent_id in all_ids else "unresolved",
                    "attrib_key": "parent",
                    "raw_value": tag_name,
                    "resolved": parent_id in all_ids,
                    "blocking": False,
                    "confidence": 1.0,
                    "provenance": {
                        "source_authority": "xml_authoritative",
                        "source_fields": ["parent"],
                        "evidence_fragment_ids": [],
                        "evidence_spans": [tag_name],
                    },
                }
            )

        dedup: dict[str, dict[str, Any]] = {}
        for rel in relations:
            dedup[rel["relation_id"]] = rel
        return list(dedup.values()), all_ids

    def _build_glossary_index(self, semantic_units: list[dict[str, Any]]) -> dict[str, str]:
        """Map normalized term -> definition node_id for definition-class units."""
        index: dict[str, str] = {}
        for unit in semantic_units:
            if str(unit.get("semantic_class") or "") != "definition":
                continue
            text = clean_text(str(unit.get("text") or ""))
            term: str | None = None
            structured_term = clean_text(str(unit.get("glossary_term") or ""))
            if structured_term:
                term = structured_term
            for marker in (" means ", " refers to ", " includes "):
                idx = text.lower().find(marker)
                if idx > 0:
                    term = clean_text(text[:idx])
                    break
            if not term:
                term = clean_text(str(unit.get("title") or ""))
            if not term:
                continue
            key = normalize_text(term)
            if key and key not in index:
                index[key] = str(unit["node_id"])
        return dict(sorted(index.items(), key=lambda item: (-len(item[0]), item[0])))

    def _glossary_links_for_text(
        self,
        text: str,
        glossary_index: dict[str, str],
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        """Longest-first deterministic term matching against glossary keys."""
        normalized = normalize_text(text)
        if not normalized or not glossary_index:
            return [], [], []

        matched_keys: set[str] = set()
        links: list[dict[str, Any]] = []
        for key in sorted(glossary_index.keys(), key=lambda k: (-len(k), k)):
            if not key or key in matched_keys:
                continue
            boundary = rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])"
            if re.search(boundary, normalized):
                matched_keys.add(key)
                node_id = glossary_index[key]
                links.append(
                    {
                        "definition_node_id": node_id,
                        "term_normalized": key,
                        "match": "boundary_token",
                    }
                )

        defined_terms = sorted(matched_keys)
        candidate_tokens = {t for t in re.findall(r"[A-Za-z][a-z]+(?:\s+[a-z]+){0,4}", text) if len(t) >= 8}
        unresolved: list[str] = []
        for phrase in sorted(candidate_tokens):
            n = normalize_text(phrase)
            if n and n not in glossary_index and not any(n in k or k in n for k in matched_keys):
                if len(unresolved) < 8:
                    unresolved.append(phrase.strip()[:80])
        return links, defined_terms, unresolved

    def _extract_applicability_conditions(self, text: str) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = []
        for match in _CLIMATE_ZONE_PATTERN.finditer(text):
            conditions.append(
                {"dimension": "climate_zone", "value": match.group(1).strip(), "source_span": match.group(0)[:120]}
            )
        for match in _BUILDING_CLASS_PATTERN.finditer(text):
            conditions.append(
                {"dimension": "building_class", "value": match.group(1).strip(), "source_span": match.group(0)[:120]}
            )
        for match in _JURISDICTION_PATTERN.finditer(text):
            conditions.append(
                {"dimension": "jurisdiction", "value": match.group(1).strip(), "source_span": match.group(0)[:120]}
            )
        for match in _CONDITIONAL_PHRASE_PATTERN.finditer(text):
            conditions.append(
                {"dimension": "conditional_phrase", "value": clean_text(match.group(0))[:200], "source_span": match.group(0)[:120]}
            )
        dedup: dict[str, dict[str, Any]] = {}
        for item in conditions:
            dedup[f"{item['dimension']}:{item.get('value')}:{item.get('source_span')}"] = item
        return list(dedup.values())

    def _implicit_relation_candidates_for_text(self, text: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for match in _IMPLICIT_SEE_PATTERN.finditer(text):
            hint = clean_text(match.group(1))[:200]
            if len(hint) < 4:
                continue
            clause_labels = self._clause_labels_from_text(hint)
            out.append(
                {
                    "kind": "text_see_reference",
                    "hint": hint,
                    "target_locator": clause_labels[0] if clause_labels else hint,
                    "confidence": 0.35,
                    "note": "Heuristic; not XML-backed.",
                }
            )
        return out[:5]

    def _clause_labels_from_text(self, text: str) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for match in _CLAUSE_LABEL_PATTERN.finditer(clean_text(text).upper()):
            label = match.group(1)
            if label not in seen:
                seen.add(label)
                labels.append(label)
        return labels

    def _leading_clause_labels_from_text(self, text: str) -> list[str]:
        normalized = clean_text(text).upper()
        match = re.match(r"^([A-Z]\d[A-Z]\d+[A-Z]?)\b", normalized)
        return [match.group(1)] if match else []

    def _build_clause_reference_index(
        self,
        *,
        semantic_units: list[dict[str, Any]],
        node_to_candidate: dict[str, dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for unit in semantic_units:
            node_id = str(unit.get("node_id") or "")
            if not node_id:
                continue
            labels: set[str] = set()
            labels.update(self._clause_labels_from_text(node_id))
            labels.update(self._leading_clause_labels_from_text(str(unit.get("text") or "")))
            if not labels:
                continue
            candidate = node_to_candidate.get(node_id) or {}
            for label in sorted(labels):
                index[label].append(
                    {
                        "node_id": node_id,
                        "semantic_unit_id": unit.get("unit_id"),
                        "candidate_id": candidate.get("candidate_id"),
                        "candidate_semantic_class": candidate.get("candidate_semantic_class") or unit.get("semantic_class"),
                    }
                )
        return dict(index)

    def _text_relation_source_authority(self, candidate: dict[str, Any], hint: str) -> str:
        evidence_text = normalize_text(" ".join(str(item.get("text") or "") for item in (candidate.get("evidence") or [])))
        if evidence_text and normalize_text(hint) in evidence_text:
            return "pdf_grounded"
        return "heuristic"

    def _text_relations_for_candidate(
        self,
        *,
        candidate: dict[str, Any],
        clause_reference_index: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        source_node_id = str(candidate.get("xml_node_id") or "")
        source_candidate_id = str(candidate.get("candidate_id") or "")
        source_semantic_unit_id = str(candidate.get("semantic_unit_id") or "")
        evidence_fragment_ids = [
            str(item.get("fragment_id"))
            for item in (candidate.get("evidence") or [])
            if item.get("fragment_id")
        ]
        relations: list[dict[str, Any]] = []
        seen_relation_ids: set[str] = set()
        combined_text = f"{candidate.get('xml_text') or ''} {' '.join(str(item.get('text') or '') for item in (candidate.get('evidence') or []))}"
        for match in _IMPLICIT_SEE_PATTERN.finditer(combined_text):
            hint = clean_text(match.group(1))[:200]
            clause_labels = self._clause_labels_from_text(hint)
            if not clause_labels:
                continue
            for label in clause_labels:
                matches = [
                    item
                    for item in clause_reference_index.get(label, [])
                    if str(item.get("node_id") or "") != source_node_id
                ]
                preferred_matches = [
                    item
                    for item in matches
                    if str(item.get("candidate_semantic_class") or "") not in {"title", "context_key"}
                ]
                if len(preferred_matches) == 1:
                    matches = preferred_matches
                relation_id = f"textref:{source_node_id}:{label}"
                if relation_id in seen_relation_ids:
                    continue
                seen_relation_ids.add(relation_id)
                if len(matches) == 1:
                    target = matches[0]
                    relation = {
                        "relation_id": relation_id,
                        "relation_kind": "clause_reference",
                        "relation_authority": "text_resolved",
                        "source_node_id": source_node_id,
                        "source_candidate_id": source_candidate_id,
                        "source_semantic_unit_id": source_semantic_unit_id,
                        "target_node_id": str(target.get("node_id") or ""),
                        "target_candidate_id": target.get("candidate_id"),
                        "target_semantic_unit_id": target.get("semantic_unit_id"),
                        "target_locator": label,
                        "resolution_status": "resolved",
                        "resolved": True,
                        "blocking": False,
                        "confidence": 0.72,
                        "raw_value": hint,
                        "provenance": {
                            "source_authority": self._text_relation_source_authority(candidate, hint),
                            "source_fields": ["xml_text", "pdf_evidence_text"],
                            "evidence_fragment_ids": evidence_fragment_ids,
                            "evidence_spans": [hint],
                        },
                    }
                else:
                    ambiguous = len(matches) > 1
                    relation = {
                        "relation_id": relation_id,
                        "relation_kind": "clause_reference",
                        "relation_authority": "text_unresolved",
                        "source_node_id": source_node_id,
                        "source_candidate_id": source_candidate_id,
                        "source_semantic_unit_id": source_semantic_unit_id,
                        "target_node_id": None,
                        "target_candidate_id": None,
                        "target_semantic_unit_id": None,
                        "target_locator": label,
                        "resolution_status": "ambiguous" if ambiguous else "unresolved",
                        "resolved": False,
                        "blocking": False,
                        "confidence": 0.35 if ambiguous else 0.4,
                        "raw_value": hint,
                        "provenance": {
                            "source_authority": self._text_relation_source_authority(candidate, hint),
                            "source_fields": ["xml_text", "pdf_evidence_text"],
                            "evidence_fragment_ids": evidence_fragment_ids,
                            "evidence_spans": [hint],
                        },
                    }
                relations.append(relation)
        return relations

    def _reconciliation_records_for_candidate(
        self,
        *,
        candidate: dict[str, Any],
        relations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidate_id = str(candidate.get("candidate_id") or "")
        records: list[dict[str, Any]] = []
        for relation in relations:
            authority = str(relation.get("relation_authority") or "")
            resolution_status = str(relation.get("resolution_status") or "")
            classification = "match"
            promotion_effect = "none"
            review_required = False
            notes: str | None = None
            if relation.get("blocking"):
                classification = "gap"
                promotion_effect = "blocks_selected_relation_classes"
                review_required = True
                notes = "Explicit XML relation could not be resolved."
            elif authority == "text_unresolved":
                classification = "review_required" if resolution_status == "ambiguous" else "gap"
                promotion_effect = "advisory_only"
                review_required = True
                notes = "Text-derived clause reference needs review."
            elif authority == "text_resolved":
                classification = "match"
                promotion_effect = "advisory_only"
                notes = "Text-derived clause reference resolved to a known candidate."
            records.append(
                {
                    "reconciliation_id": f"reconcile:{candidate_id}:{relation.get('relation_id')}",
                    "source_candidate_ids": [candidate_id] if candidate_id else [],
                    "source_relation_ids": [relation.get("relation_id")],
                    "classification": classification,
                    "promotion_effect": promotion_effect,
                    "review_required": review_required,
                    "notes": notes,
                }
            )
        return records

    def _bind_relation_candidate_context(
        self,
        *,
        relation: dict[str, Any],
        source_candidate: dict[str, Any],
        node_to_candidate: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        bound = dict(relation)
        target_node_id = str(bound.get("target_node_id") or "")
        target_candidate = node_to_candidate.get(target_node_id) if target_node_id else None
        bound.setdefault("source_candidate_id", source_candidate.get("candidate_id"))
        bound.setdefault("source_semantic_unit_id", source_candidate.get("semantic_unit_id"))
        if target_candidate is not None:
            bound.setdefault("target_candidate_id", target_candidate.get("candidate_id"))
            bound.setdefault("target_semantic_unit_id", target_candidate.get("semantic_unit_id"))
        else:
            bound.setdefault("target_candidate_id", None)
            bound.setdefault("target_semantic_unit_id", None)
        return bound

    def _extract_candidate_relation_runtime(
        self,
        *,
        explicit_relations: list[dict[str, Any]],
        glossary_index: dict[str, str],
        clause_reference_index: dict[str, list[dict[str, Any]]],
        node_to_candidate: dict[str, dict[str, Any]],
        candidate_objects: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        all_candidate_relations: list[dict[str, Any]] = []
        for candidate in candidate_objects:
            nid = str(candidate.get("xml_node_id") or "")
            evidence = list(candidate.get("evidence") or [])
            primary = evidence[0] if evidence else {}
            xml_cls = str(candidate.get("xml_structural_class") or "")
            pdf_cls = str(primary.get("pdf_evidence_class") or "unknown")
            alignment_like = {
                "matched": bool(primary),
                "node_id": nid if primary else None,
                "confidence": float(primary.get("confidence", 0.0)),
            }
            sem_cls = self._candidate_semantic_class(
                xml_structural_class=xml_cls,
                pdf_evidence_class=pdf_cls,
                alignment=alignment_like,
            )
            candidate["classification"] = {
                "xml_structural_class": xml_cls,
                "pdf_evidence_class": pdf_cls,
                "candidate_semantic_class": sem_cls,
            }
            candidate["candidate_semantic_class"] = sem_cls

            combined_text = f"{candidate.get('xml_text') or ''} {primary.get('text') or ''}"
            g_links, defined_terms, unresolved_terms = self._glossary_links_for_text(combined_text, glossary_index)
            candidate["glossary_links"] = g_links
            candidate["defined_terms_used"] = defined_terms
            candidate["unresolved_terms"] = unresolved_terms[:12]
            candidate["applicability_conditions"] = self._extract_applicability_conditions(combined_text)
            candidate["implicit_relation_candidates"] = self._implicit_relation_candidates_for_text(combined_text)

            local_explicit_rels = [
                self._bind_relation_candidate_context(
                    relation=rel,
                    source_candidate=candidate,
                    node_to_candidate=node_to_candidate,
                )
                for rel in explicit_relations
                if str(rel.get("source_node_id") or "") == nid
            ]
            local_text_rels = self._text_relations_for_candidate(
                candidate=candidate,
                clause_reference_index=clause_reference_index,
            )
            local_rels = [*local_explicit_rels, *local_text_rels]
            candidate["explicit_relations"] = local_explicit_rels
            candidate["candidate_relations"] = local_rels
            all_candidate_relations.extend(local_rels)

            depends_on: list[str] = []
            for rel in local_rels:
                if rel.get("relation_kind") in {"xref_attribute", "structural_parent", "clause_reference"} and rel.get(
                    "resolved"
                ):
                    tgt = str(rel.get("target_node_id") or "")
                    if tgt and tgt in node_to_candidate:
                        depends_on.append(str(node_to_candidate[tgt].get("candidate_id")))
            candidate["depends_on"] = sorted(set(depends_on))

            candidate["semantic_enrichment"] = {
                "schema_version": "1",
                "field_authority": self._semantic_enrichment_field_authority(),
                "per_field_counts": {
                    "explicit_relations": len(local_explicit_rels),
                    "candidate_relations": len(local_rels),
                    "reconciliation_records": 0,
                    "glossary_links": len(g_links),
                    "applicability_conditions": len(candidate.get("applicability_conditions") or []),
                    "implicit_relation_candidates": len(candidate.get("implicit_relation_candidates") or []),
                },
            }
        return candidate_objects, all_candidate_relations

    def _reconcile_candidate_relation_runtime(
        self,
        *,
        candidate_objects: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        gated = 0
        all_reconciliation_records: list[dict[str, Any]] = []
        for candidate in candidate_objects:
            evidence = list(candidate.get("evidence") or [])
            primary = evidence[0] if evidence else {}
            alignment_like = {
                "matched": bool(primary),
                "node_id": str(candidate.get("xml_node_id") or "") if primary else None,
                "confidence": float(primary.get("confidence", 0.0)),
            }
            sem_cls = str(candidate.get("candidate_semantic_class") or "")
            original_validation_state = candidate.get("validation_state")
            original_status = candidate.get("status")
            local_explicit_rels = list(candidate.get("explicit_relations") or [])
            local_rels = list(candidate.get("candidate_relations") or [])

            reconciliation_records = self._reconciliation_records_for_candidate(
                candidate=candidate,
                relations=local_rels,
            )
            candidate["reconciliation_records"] = reconciliation_records
            all_reconciliation_records.extend(reconciliation_records)

            blocking = [rel for rel in local_explicit_rels if rel.get("blocking")]
            review_only_relations = [
                rel
                for rel in local_rels
                if rel.get("resolution_status") in {"unresolved", "ambiguous", "review_required"} and not rel.get("blocking")
            ]
            review = dict(candidate.get("review") or {})
            issues = list(review.get("issues") or [])
            if blocking:
                for rel in blocking:
                    issues.append(
                        f"Unresolved explicit XML relation ({rel.get('attrib_key')}) targets '{rel.get('target_node_id')}'."
                    )
                review["enrichment_issue_class"] = "unresolved_explicit_relation"
                review["enrichment_summary"] = f"{len(blocking)} unresolved explicit relation(s)."
            elif review_only_relations:
                for rel in review_only_relations:
                    issues.append(
                        f"Review relation candidate '{rel.get('target_locator')}' ({rel.get('resolution_status')})."
                    )
                review["enrichment_issue_class"] = "review_relation_candidate"
                review["enrichment_summary"] = f"{len(review_only_relations)} relation candidate(s) require review."
            else:
                review.setdefault("enrichment_issue_class", "clean")
                review.setdefault("enrichment_summary", "")

            if blocking:
                gated += 1
                candidate["validation_state"] = "requires_review"
                candidate["status"] = "draft"
                review["needs_human_review"] = True
                review["base_status"] = self._derive_review_base_status(
                    alignment=alignment_like,
                    issues=issues,
                    approved=False,
                    candidate_semantic_class=sem_cls,
                )
            else:
                candidate["validation_state"] = original_validation_state
                candidate["status"] = original_status
                if review_only_relations:
                    review["needs_human_review"] = True

            review["issues"] = issues
            candidate["review"] = review
            semantic_enrichment = dict(candidate.get("semantic_enrichment") or {})
            per_field_counts = dict(semantic_enrichment.get("per_field_counts") or {})
            per_field_counts["reconciliation_records"] = len(reconciliation_records)
            semantic_enrichment["per_field_counts"] = per_field_counts
            candidate["semantic_enrichment"] = semantic_enrichment
        return candidate_objects, all_reconciliation_records, gated

    def _apply_semantic_enrichment(
        self,
        *,
        xml_bytes: bytes | None,
        xml_metrics: dict[str, Any],
        semantic_units: list[dict[str, Any]],
        pdf_evidence_packets: list[dict[str, Any]],
        candidate_objects: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        _ = xml_metrics
        _ = pdf_evidence_packets
        explicit_relations: list[dict[str, Any]] = []
        id_set: set[str] = set()
        if xml_bytes:
            try:
                root = ET.fromstring(xml_bytes)
                explicit_relations, id_set = self._collect_explicit_xml_relations(root)
            except ET.ParseError:
                explicit_relations, id_set = [], set()

        glossary_index = self._build_glossary_index(semantic_units)
        node_to_candidate: dict[str, dict[str, Any]] = {}
        for c in candidate_objects:
            nid = str(c.get("xml_node_id") or "")
            if nid:
                node_to_candidate[nid] = c
        clause_reference_index = self._build_clause_reference_index(
            semantic_units=semantic_units,
            node_to_candidate=node_to_candidate,
        )
        candidate_objects, all_candidate_relations = self._extract_candidate_relation_runtime(
            explicit_relations=explicit_relations,
            glossary_index=glossary_index,
            clause_reference_index=clause_reference_index,
            node_to_candidate=node_to_candidate,
            candidate_objects=candidate_objects,
        )
        candidate_objects, all_reconciliation_records, gated = self._reconcile_candidate_relation_runtime(
            candidate_objects=candidate_objects,
        )

        enrichment_summary = {
            "generated_at": utc_now_iso(),
            "explicit_relation_count": len(explicit_relations),
            "candidate_relation_count": len(all_candidate_relations),
            "text_resolved_relation_count": sum(
                1 for rel in all_candidate_relations if rel.get("relation_authority") == "text_resolved"
            ),
            "text_unresolved_relation_count": sum(
                1 for rel in all_candidate_relations if rel.get("relation_authority") == "text_unresolved"
            ),
            "reconciliation_record_count": len(all_reconciliation_records),
            "reconciliation_review_required_count": sum(
                1 for record in all_reconciliation_records if record.get("review_required")
            ),
            "unresolved_blocking_count": sum(1 for r in explicit_relations if r.get("blocking")),
            "candidates_gated": gated,
            "glossary_term_count": len(glossary_index),
            "xml_id_count": len(id_set),
            "graph_edge_count": 0,
            "field_authority": self._semantic_enrichment_field_authority(),
        }

        graph_edges = self._build_semantic_graph_edges(
            candidate_objects=candidate_objects,
            semantic_units=semantic_units,
            candidate_relations=all_candidate_relations,
            enrichment_summary=enrichment_summary,
        )
        return candidate_objects, all_candidate_relations, all_reconciliation_records, graph_edges, enrichment_summary

    def _build_semantic_graph_edges(
        self,
        *,
        candidate_objects: list[dict[str, Any]],
        semantic_units: list[dict[str, Any]],
        candidate_relations: list[dict[str, Any]],
        enrichment_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        unit_by_node = {str(u.get("node_id")): u for u in semantic_units}

        for candidate in candidate_objects:
            cid = str(candidate.get("candidate_id") or "")
            suid = str(candidate.get("semantic_unit_id") or "")
            if suid:
                edges.append(
                    {
                        "edge_id": f"e:{cid}:unit:{suid}",
                        "edge_type": "candidate_to_semantic_unit",
                        "source": {"kind": "candidate", "id": cid},
                        "target": {"kind": "semantic_unit", "id": suid},
                    }
                )
            frag = (candidate.get("source") or {}).get("pdf_fragment_id")
            if frag:
                edges.append(
                    {
                        "edge_id": f"e:{cid}:frag:{frag}",
                        "edge_type": "candidate_to_pdf_fragment",
                        "source": {"kind": "candidate", "id": cid},
                        "target": {"kind": "pdf_fragment", "id": str(frag)},
                    }
                )
            for link in candidate.get("glossary_links") or []:
                dnode = str(link.get("definition_node_id") or "")
                if not dnode:
                    continue
                du = unit_by_node.get(dnode, {})
                edges.append(
                    {
                        "edge_id": f"e:{cid}:gloss:{dnode}",
                        "edge_type": "glossary_link",
                        "source": {"kind": "candidate", "id": cid},
                        "target": {"kind": "definition_node", "id": dnode},
                        "payload": {"semantic_unit_id": du.get("unit_id"), "term": link.get("term_normalized")},
                    }
                )
            for app_index, cond in enumerate(candidate.get("applicability_conditions") or []):
                dim = str(cond.get("dimension") or "unknown")
                val = str(cond.get("value") or "")[:40]
                edges.append(
                    {
                        "edge_id": f"e:{cid}:app:{dim}:{app_index}:{val}",
                        "edge_type": "applicability",
                        "source": {"kind": "candidate", "id": cid},
                        "target": {"kind": "applicability_dimension", "id": dim},
                        "payload": cond,
                    }
                )

        for rel in candidate_relations:
            sid = str(rel.get("source_node_id") or "")
            tid = str(rel.get("target_node_id") or "")
            src_c = next((c for c in candidate_objects if str(c.get("xml_node_id")) == sid), None)
            tgt_c = next((c for c in candidate_objects if str(c.get("xml_node_id")) == tid), None)
            edge_type = "relation_resolved" if rel.get("resolution_status") == "resolved" else "relation_unresolved"
            target_kind = "xml_node" if tid else "relation_locator"
            target_id = tid or str(rel.get("target_locator") or rel.get("relation_id"))
            source_kind = "candidate" if (src_c or {}).get("candidate_id") else "xml_node"
            source_id = str((src_c or {}).get("candidate_id") or sid)
            edges.append(
                {
                    "edge_id": f"e:rel:{rel.get('relation_id')}",
                    "edge_type": edge_type,
                    "source": {"kind": source_kind, "id": source_id},
                    "target": {"kind": target_kind, "id": target_id},
                    "payload": {
                        "relation_kind": rel.get("relation_kind"),
                        "relation_authority": rel.get("relation_authority"),
                        "resolution_status": rel.get("resolution_status"),
                        "attrib_key": rel.get("attrib_key"),
                        "source_candidate_id": (src_c or {}).get("candidate_id"),
                        "target_candidate_id": (tgt_c or {}).get("candidate_id"),
                        "target_locator": rel.get("target_locator"),
                    },
                }
            )

        enrichment_summary["graph_edge_count"] = len(edges)
        return edges

    def _append_snippet_promotion_edges(
        self,
        *,
        graph_edges: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        canonical_snippets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        edges = list(graph_edges)
        cand_set = {str(c.get("candidate_id")) for c in candidates}
        for snippet in canonical_snippets:
            cid = str(snippet.get("candidate_id") or "")
            if not cid or cid not in cand_set:
                continue
            sid = f"snippet:{cid}"
            edges.append(
                {
                    "edge_id": f"e:promote:{cid}",
                    "edge_type": "candidate_to_canonical_snippet",
                    "source": {"kind": "candidate", "id": cid},
                    "target": {"kind": "canonical_snippet", "id": sid},
                    "payload": {"clause_id": snippet.get("clause_id"), "fragment_id": snippet.get("fragment_id")},
                }
            )
        return edges

    def _review_term_deltas(self, xml_text: str, pdf_text: str) -> tuple[list[str], list[str]]:
        xml_terms = {token for token in normalize_text(xml_text).split() if token}
        pdf_terms = {token for token in normalize_text(pdf_text).split() if token}
        return sorted(xml_terms - pdf_terms)[:10], sorted(pdf_terms - xml_terms)[:10]

    def _xml_structural_class(self, xml_path: str, xml_text: str) -> str:
        normalized_path = xml_path.lower()
        normalized_text = xml_text.lower()
        if not normalized_path and not normalized_text:
            return "ambiguous"
        if any(marker in normalized_path for marker in ("glossentry", "glossdef")):
            return "definition"
        if "glossterm" in normalized_path:
            return "context_key"
        if "/title[" in normalized_path or normalized_path.endswith("/title"):
            return "title"
        if "/num[" in normalized_path or normalized_path.endswith("/num"):
            return "context_key"
        if any(marker in normalized_path for marker in ("/note[", "/intro-part[", "/intro[", "/subtitle[")) or normalized_path.endswith("/note"):
            return "note"
        if "table" in normalized_path:
            return "table"
        if "xref" in normalized_path or "reference" in normalized_path:
            return "reference"
        if "definition" in normalized_path or " means " in normalized_text:
            return "definition"
        return "rule"

    def _pdf_evidence_class(self, fragment: PdfFragment, block: dict[str, Any] | None) -> str:
        fragment_id = fragment.fragment_id.lower()
        if "__row_" in fragment_id:
            return "table_row"
        if "__cell_" in fragment_id:
            return "table_cell"
        if block and block.get("block_type"):
            return str(block["block_type"]).lower()
        return "unknown"

    def _candidate_semantic_class(
        self,
        *,
        xml_structural_class: str,
        pdf_evidence_class: str,
        alignment: dict[str, Any],
    ) -> str:
        if xml_structural_class != "ambiguous":
            return xml_structural_class
        if alignment.get("matched") and pdf_evidence_class in {"table_row", "table_cell"}:
            return "table"
        return "ambiguous"

    def _effective_review_term_deltas(
        self,
        *,
        xml_only_terms: list[str],
        pdf_only_terms: list[str],
        candidate_semantic_class: str,
    ) -> tuple[list[str], list[str], list[str]]:
        if candidate_semantic_class not in {"title", "context_key"}:
            return xml_only_terms, pdf_only_terms, []

        ignored = {
            term
            for term in [*xml_only_terms, *pdf_only_terms]
            if self._is_structural_title_token(term)
        }
        return (
            [term for term in xml_only_terms if term not in ignored],
            [term for term in pdf_only_terms if term not in ignored],
            sorted(ignored),
        )

    def _is_structural_title_token(self, term: str) -> bool:
        if term in {
            "part",
            "section",
            "volume",
            "schedule",
            "appendix",
            "chapter",
            "clause",
            "table",
            "figure",
            "diagram",
            "map",
        }:
            return True
        return bool(re.match(r"^[a-z]{1,4}\d[a-z0-9]*$", term))

    def _review_title(self, xml_text: str, pdf_text: str, fragment_id: str) -> str:
        source = clean_text(xml_text) or clean_text(pdf_text)
        return source[:96] if source else fragment_id

    def _build_review_issues(
        self,
        *,
        alignment: dict[str, Any],
        xml_only_terms: list[str],
        pdf_only_terms: list[str],
        linked_issue: bool,
    ) -> list[str]:
        issues: list[str] = []
        if not alignment.get("matched") or not alignment.get("node_id"):
            issues.append("No XML clause met the alignment threshold for this fragment.")
        if float(alignment.get("confidence", 0.0)) < 0.9:
            issues.append("Alignment confidence is below the temporary auto-pass threshold.")
        if linked_issue:
            issues.append("Validation warnings or errors reference this candidate.")
        if xml_only_terms:
            issues.append(f"XML-only terms detected: {', '.join(xml_only_terms[:4])}.")
        if pdf_only_terms:
            issues.append(f"PDF-only terms detected: {', '.join(pdf_only_terms[:4])}.")
        return issues

    def _derive_review_base_status(
        self,
        *,
        alignment: dict[str, Any],
        issues: list[str],
        approved: bool,
        candidate_semantic_class: str,
    ) -> str:
        if approved:
            return "approved"
        if (
            not alignment.get("matched")
            or not alignment.get("node_id")
            or float(alignment.get("confidence", 0.0)) < 0.85
        ):
            return "review required"
        if candidate_semantic_class in {"title", "context_key"} and not issues:
            return "match"
        if any("XML-only" in issue or "PDF-only" in issue for issue in issues):
            return "mismatch"
        return "match"

    def _build_canonical_snippets(
        self,
        *,
        can_progress: bool,
        candidates: list[dict[str, Any]],
        candidate_validation_results: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if not can_progress:
            return []

        promotable_ids = {
            str(item.get("candidate_id"))
            for item in (candidate_validation_results or [])
            if item.get("promotion_eligible")
        }
        snippets: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_id = str(candidate.get("candidate_id") or "")
            if promotable_ids:
                if candidate_id not in promotable_ids:
                    continue
            elif candidate.get("validation_state") != "pass":
                continue
            source = candidate.get("source") or {}
            fragment_id = source.get("pdf_fragment_id")
            if not fragment_id or not candidate.get("xml_node_id"):
                continue
            snippets.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "clause_id": candidate["xml_node_id"],
                    "fragment_id": fragment_id,
                    "content": candidate.get("proposed", {}).get("content", ""),
                    "confidence": float(candidate.get("confidence", {}).get("overall", 0.0)),
                }
            )
        return snippets

    def _page_fragments(self, words: list[dict[str, Any]], page_number: int) -> list[PdfFragment]:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for word in words:
            grouped[int(float(word["top"]) // 4)].append(word)

        fragments: list[PdfFragment] = []
        for index, (_, line_words) in enumerate(sorted(grouped.items()), start=1):
            ordered = sorted(line_words, key=lambda item: float(item["x0"]))
            text = clean_text(" ".join(item["text"] for item in ordered))
            if not text:
                continue
            bbox = [
                round(min(float(item["x0"]) for item in ordered), 2),
                round(min(float(item["top"]) for item in ordered), 2),
                round(max(float(item["x1"]) for item in ordered), 2),
                round(max(float(item["bottom"]) for item in ordered), 2),
            ]
            fragments.append(
                PdfFragment(
                    fragment_id=f"frag_{page_number}_{index}",
                    page=page_number,
                    text=text,
                    bbox=bbox,
                )
            )
        return fragments

    def _align_fragment(self, fragment: PdfFragment, xml_nodes: list[XmlNode]) -> dict[str, Any]:
        candidate_text = normalize_text(fragment.text)
        if not candidate_text or not xml_nodes:
            return {
                "fragment_id": fragment.fragment_id,
                "node_id": None,
                "confidence": 0.0,
                "matched": False,
                "page": fragment.page,
                "bbox": fragment.bbox,
            }

        best_score = 0.0
        best_node: XmlNode | None = None
        best_key = (-1.0, -1.0, 0.0)
        candidate_tokens = set(candidate_text.split())
        for node in xml_nodes:
            node_text = normalize_text(node.text)
            if not node_text:
                continue
            token_score = self._token_overlap_score(candidate_tokens, set(node_text.split()))
            if candidate_text in node_text or node_text in candidate_text:
                overlap_score = min(len(candidate_text), len(node_text)) / max(len(candidate_text), len(node_text))
                score = max(overlap_score, token_score, SequenceMatcher(None, candidate_text, node_text).ratio())
            else:
                score = max(token_score, SequenceMatcher(None, candidate_text, node_text).ratio())
            candidate_key = (
                round(score, 3),
                self._node_specificity_score(node),
                -float(len(node_text)),
            )
            if candidate_key > best_key:
                best_key = candidate_key
                best_score = score
                best_node = node

        return {
            "fragment_id": fragment.fragment_id,
            "node_id": best_node.node_id if best_node and best_score >= 0.75 else None,
            "confidence": round(best_score if best_node else 0.0, 3),
            "matched": bool(best_node and best_score >= 0.75),
            "page": fragment.page,
            "bbox": fragment.bbox,
        }

    def _token_overlap_score(self, candidate_tokens: set[str], node_tokens: set[str]) -> float:
        if not candidate_tokens or not node_tokens:
            return 0.0
        overlap = candidate_tokens & node_tokens
        if not overlap:
            return 0.0
        coverage = len(overlap) / len(candidate_tokens)
        specificity = len(overlap) / len(node_tokens)
        return round((0.75 * coverage) + (0.25 * specificity), 3)

    def _node_specificity_score(self, node: XmlNode) -> float:
        score = 0.0
        if self._is_row_node_id(node.node_id) or "/row[" in node.path:
            score += 2.0
        if "/tbody/" in node.path or "/thead/" in node.path:
            score += 0.5
        score += min(node.path.count("/"), 10) / 10
        return round(score, 3)

    def _is_row_node_id(self, node_id: str) -> bool:
        return "__row_" in node_id

    def _review_group_priority(
        self,
        node_id: str,
        node_alignments: list[dict[str, Any]],
        node_lookup: dict[str, XmlNode],
    ) -> tuple[float, float, float]:
        node = node_lookup.get(node_id)
        best_confidence = max((float(item.get("confidence", 0.0)) for item in node_alignments), default=0.0)
        return (
            self._node_specificity_score(node) if node else 0.0,
            best_confidence,
            -float(len(node.text)) if node else 0.0,
        )

    def _review_alignment_priority(
        self,
        alignment: dict[str, Any],
        node: XmlNode | None,
    ) -> tuple[float, float, float, float]:
        fragment_id = str(alignment.get("fragment_id") or "")
        return (
            float(alignment.get("confidence", 0.0)),
            self._node_specificity_score(node) if node else 0.0,
            1.0 if "__row_" in fragment_id else 0.0,
            -float(int(alignment.get("page") or 0)),
        )

    def _element_path(self, element: ET.Element) -> str:
        tag_name = element.tag.split("}")[-1]
        identifier = element.attrib.get("id")
        return f"/{tag_name}[@id='{identifier}']" if identifier else f"/{tag_name}"
