from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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
    ReviewPolicy,
    StructuredBlock,
)
from app.services.document_strategy import DocumentStrategyRouter
from app.services.extractors import DoclingExtractor, PdfPlumberExtractor


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


MAX_DOCUMENT_FAMILY_ID_LENGTH = 80
REVIEW_WORKSPACE_MAX_ALIGNMENTS_PER_NODE = 3
REVIEW_WORKSPACE_NARROW_XML_NODE_LIMIT = 12
REVIEW_WORKSPACE_LARGE_FRAGMENT_LIMIT = 100


@dataclass
class XmlNode:
    node_id: str
    clause_id: str
    text: str
    path: str


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
            requested_document_class=document_class,
            requested_extraction_profile=extraction_profile,
            requested_evaluation_profile=evaluation_profile,
            requested_extractor_strategy=extractor_strategy,
        )
        pdf_context = self._validate_pdf(pdf_bytes, pdf_name, xml_context, strategy)
        document_family_id = self._build_document_family_id(pdf_name=pdf_name, xml_name=xml_name)
        # Transitional shortcut: snippets are still built directly from aligned
        # fragments. The first-class Candidate layer spec requires replacing
        # this with candidate extraction, candidate validation, and promotion.
        canonical_snippets = self._build_canonical_snippets(
            can_progress=bool(pdf_context["result"]["gate_decision"]["can_progress_to_semantic_layer"]),
            fragments=pdf_context["fragments"],
            alignments=pdf_context["alignments"],
        )
        review_workspace = self._build_review_workspace(
            pdf_name=pdf_name,
            xml_name=xml_name,
            xml_nodes=xml_context["xml_nodes"],
            fragments=pdf_context["fragments"],
            alignments=pdf_context["alignments"],
            canonical_snippets=canonical_snippets,
        )

        return {
            "summary": {
                "ingestion_run_status": "active",
                "xml_status": xml_context["result"]["overall_status"],
                "pdf_status": pdf_context["result"]["overall_status"],
                "can_progress": bool(pdf_context["result"]["gate_decision"]["can_progress_to_semantic_layer"]),
                "paired_document_id": pdf_context["result"]["document"].get("paired_xml_doc_id")
                or xml_context["result"]["document"].get("paired_pdf_doc_id"),
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
                "pdf_fragments": pdf_context["fragments"],
                "structured_blocks": pdf_context["structured_blocks"],
                "alignments": pdf_context["alignments"],
                "parity_scaffold": pdf_context["parity_scaffold"],
                "canonical_snippets": canonical_snippets,
                "pdf_tables": pdf_context["result"].get("table_validation", []),
                "xml_tables": xml_context["result"].get("table_validation", []),
            },
            "review_workspace": review_workspace,
        }

    def _validate_xml(self, xml_bytes: bytes, xml_name: str) -> dict[str, Any]:
        contract = self.contracts["xml_contract"]
        metrics: dict[str, Any] = {
            "is_well_formed": False,
            "encoding_valid": True,
            "root_element": None,
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
            return {"result": result, "metrics": metrics, "xml_nodes": xml_nodes}

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

            tag_name = element.tag.split("}")[-1].lower()
            text_value = clean_text(" ".join(part for part in element.itertext()))

            if tag_name in {"table", "tbody", "thead"}:
                table_count += 1 if tag_name == "table" else 0
                if tag_name == "table" and not text_value:
                    table_issues += 1

            if tag_name in {"heading", "title", "clause", "section", "part", "table"} and not text_value:
                empty_required_nodes += 1

            for key in ("ref", "href", "target", "rid"):
                value = element.attrib.get(key)
                if value:
                    references.append(value.lstrip("#"))

            if element_id and len(text_value) >= 20:
                node_path = self._element_path(element)
                xml_nodes.append(
                    XmlNode(
                        node_id=element_id,
                        clause_id=element_id,
                        text=text_value,
                        path=node_path,
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

        metrics["duplicate_ids"] = sum(count - 1 for count in id_counts.values() if count > 1)
        metrics["empty_required_nodes"] = empty_required_nodes
        metrics["unresolved_references"] = sum(1 for ref in references if ref not in id_counts)
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

        thresholds = contract["thresholds"]

        def add_rule(rule_id: str, status: str, details: dict[str, Any], warning: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
            rule_results.append({"rule_id": rule_id, "status": status, "details": details})
            if warning:
                warnings.append(warning)
            if error:
                errors.append(error)

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
        else:
            x5_status = "FAIL"
            warnings.append(
                {
                    "code": "EMPTY_REQUIRED_NODES",
                    "severity": "warning",
                    "message": f"{metrics['empty_required_nodes']} required nodes are empty.",
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
        else:
            x8_status = "FAIL"
            warnings.append(
                {
                    "code": "TABLE_INCONSISTENCY",
                    "severity": "warning",
                    "message": f"{metrics['table_structure_issues']} XML table structure issues were found.",
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
                0 < metrics["empty_required_nodes"] <= thresholds["max_empty_required_nodes_for_review"]
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
        return {"result": result, "metrics": metrics, "xml_nodes": xml_nodes}

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

        extracted = self._extract_pdf(pdf_bytes, strategy)
        fragments = self._fragments_from_blocks(extracted.blocks)
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

        missing_clause_metadata = len(unresolved)
        missing_traceability_metadata = len(
            [
                block
                for block in extracted.blocks
                if not block.block_id or not block.source_strategy or len(block.bbox) != 4
            ]
        )
        invalid_tables = len([table for table in extracted.tables if not table.rows or not any(row for row in table.rows if any(row))])
        missing_headers = len(
            [
                table
                for table in extracted.tables
                if strategy.extraction_profile.require_table_headers and table.rows and not table.headers_present
            ]
        )
        empty_row_sets = invalid_tables
        table_validation = []
        for table in extracted.tables:
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
        missing_bbox = len([block for block in extracted.blocks if len(block.bbox) != 4])
        untyped_fragments = len([block for block in extracted.blocks if not block.block_type])
        missing_page_reference = len([block for block in extracted.blocks if block.page <= 0])
        block_structure_score = 1.0 if fragments and missing_bbox == 0 and untyped_fragments == 0 and missing_page_reference == 0 else 0.0
        table_score = 1.0 if invalid_tables == 0 else max(0.0, 1.0 - invalid_tables / max(len(extracted.tables), 1))
        alignment_score = alignment_avg
        metadata_score = 1.0 if missing_clause_metadata == 0 and missing_traceability_metadata == 0 else max(
            0.0, 1.0 - ((missing_clause_metadata + missing_traceability_metadata) / max(len(fragments), 1))
        )
        overall_confidence = round(average([block_structure_score, table_score, alignment_score, metadata_score]), 3)
        parity_scaffold = self._build_parity_scaffold(strategy, fragments, alignments, xml_nodes)

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

        c3_pass = bool(fragments)
        rule_results.append(
            {
                "rule_id": "C3_BLOCK_STRUCTURE",
                "status": "PASS" if c3_pass else "FAIL",
                "details": {
                    "fragments_checked": len(fragments),
                    "missing_bbox": missing_bbox,
                    "untyped_fragments": untyped_fragments,
                    "missing_page_reference": missing_page_reference,
                    "block_types": sorted({block.block_type for block in extracted.blocks}),
                },
            }
        )
        if not c3_pass or missing_bbox or untyped_fragments or missing_page_reference:
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
                    "tables_checked": len(extracted.tables),
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
                "tables_extracted": len(extracted.tables),
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
            "structured_blocks": [self._serialize_block(block) for block in extracted.blocks],
            "alignments": alignments,
            "strategy": self._serialize_strategy(strategy, extracted),
            "parity_scaffold": parity_scaffold,
        }

    def _extract_pdf(self, pdf_bytes: bytes, strategy: DocumentStrategyDecision) -> ExtractedPdf:
        extractor = self.extractors.get(strategy.extractor_strategy)
        if extractor is None:
            raise ValueError(f"Unsupported extractor strategy: {strategy.extractor_strategy}")
        return extractor.extract(pdf_bytes, decision=strategy)

    def _fragments_from_blocks(self, blocks: list[StructuredBlock]) -> list[PdfFragment]:
        return [
            PdfFragment(
                fragment_id=block.block_id,
                page=block.page,
                text=block.text,
                bbox=block.bbox,
            )
            for block in blocks
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
        metadata = {
            "edition": attrs.get("edition"),
            "amendment": attrs.get("amendment") or attrs.get("version"),
            "volume": attrs.get("volume"),
            "section": attrs.get("section"),
            "part": attrs.get("part"),
        }

        for element in root.iter():
            tag_name = element.tag.split("}")[-1].lower()
            text_value = clean_text(" ".join(element.itertext()))
            if tag_name in metadata and not metadata[tag_name] and text_value:
                metadata[tag_name] = text_value
            if tag_name in {"amendment", "version"} and not metadata["amendment"] and text_value:
                metadata["amendment"] = text_value

        if not metadata["edition"]:
            match = re.search(r"(20\d{2})", xml_name)
            if match:
                metadata["edition"] = match.group(1)
        if not metadata["volume"]:
            match = re.search(r"vol(?:ume)?[_\s-]?([0-9a-z]+)", xml_name.lower())
            if match:
                metadata["volume"] = match.group(1)
        return metadata

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

    def _build_review_workspace(
        self,
        *,
        pdf_name: str,
        xml_name: str,
        xml_nodes: list[XmlNode],
        fragments: list[PdfFragment],
        alignments: list[dict[str, Any]],
        canonical_snippets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        workspace_mode = "full"
        workspace_reason = "default_full_lineage_review"
        review_alignments = list(alignments)

        if self._should_focus_review_workspace(xml_name=xml_name, xml_nodes=xml_nodes, fragments=fragments):
            workspace_mode = "focused"
            workspace_reason = "narrow_xml_artifact_focus"
            review_alignments = self._focused_review_alignments(alignments)

        review_fragment_ids = {item["fragment_id"] for item in review_alignments}
        review_node_ids = {item["node_id"] for item in review_alignments if item.get("node_id")}

        return {
            "mode": workspace_mode,
            "reason": workspace_reason,
            "xml_nodes": [node for node in xml_nodes if node.node_id in review_node_ids] if review_node_ids else [],
            "pdf_fragments": [fragment for fragment in fragments if fragment.fragment_id in review_fragment_ids],
            "alignments": review_alignments,
            "canonical_snippets": [
                snippet
                for snippet in canonical_snippets
                if snippet.get("fragment_id") in review_fragment_ids
            ],
            "alignment_total": len(alignments),
            "alignment_displayed": len(review_alignments),
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

    def _focused_review_alignments(self, alignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for alignment in alignments:
            node_id = alignment.get("node_id")
            if not alignment.get("matched") or not node_id:
                continue
            by_node[str(node_id)].append(alignment)

        selected: list[dict[str, Any]] = []
        for node_alignments in by_node.values():
            ranked = sorted(
                node_alignments,
                key=lambda item: (float(item.get("confidence", 0.0)), -int(item.get("page") or 0)),
                reverse=True,
            )
            selected.extend(ranked[:REVIEW_WORKSPACE_MAX_ALIGNMENTS_PER_NODE])
        return selected

    def _build_canonical_snippets(
        self,
        *,
        can_progress: bool,
        fragments: list[PdfFragment],
        alignments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not can_progress:
            return []

        fragment_by_id = {fragment.fragment_id: fragment for fragment in fragments}
        snippets: list[dict[str, Any]] = []
        for alignment in alignments:
            if not alignment["matched"] or not alignment["node_id"]:
                continue
            fragment = fragment_by_id.get(alignment["fragment_id"])
            if not fragment:
                continue
            snippets.append(
                {
                    "clause_id": alignment["node_id"],
                    "fragment_id": fragment.fragment_id,
                    "content": fragment.text,
                    "confidence": alignment["confidence"],
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
        for node in xml_nodes:
            node_text = normalize_text(node.text)
            if not node_text:
                continue
            if candidate_text in node_text or node_text in candidate_text:
                score = max(len(candidate_text), len(node_text)) / max(len(candidate_text), len(node_text))
                score = max(score, SequenceMatcher(None, candidate_text, node_text[: len(candidate_text) + 80]).ratio())
            else:
                score = SequenceMatcher(None, candidate_text, node_text).ratio()
            if score > best_score:
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

    def _element_path(self, element: ET.Element) -> str:
        tag_name = element.tag.split("}")[-1]
        identifier = element.attrib.get("id")
        return f"/{tag_name}[@id='{identifier}']" if identifier else f"/{tag_name}"
