from __future__ import annotations

import re

from app.models.document_strategy import DocumentStrategyDecision
from app.services.evaluation_profiles import get_evaluation_profile
from app.services.extraction_profiles import get_extraction_profile


DEFAULTS_BY_CLASS = {
    "clause_parity": {
        "extraction_profile": "baseline_clause_parity",
        "evaluation_profile": "baseline_clause_parity",
        "extractor_strategy": "docling",
    },
    "definitions_glossary": {
        "extraction_profile": "definitions_glossary",
        "evaluation_profile": "definitions_glossary",
        "extractor_strategy": "docling",
    },
    "governance_interpretation": {
        "extraction_profile": "governance_interpretation",
        "evaluation_profile": "governance_interpretation",
        "extractor_strategy": "docling",
    },
    "front_matter_non_parity": {
        "extraction_profile": "front_matter_non_parity",
        "evaluation_profile": "front_matter_non_parity",
        "extractor_strategy": "pdfplumber",
    },
}


class DocumentStrategyRouter:
    def route(
        self,
        *,
        pdf_name: str,
        xml_name: str,
        xml_schema_family_id: str | None = None,
        requested_document_class: str | None = None,
        requested_extraction_profile: str | None = None,
        requested_evaluation_profile: str | None = None,
        requested_extractor_strategy: str | None = None,
    ) -> DocumentStrategyDecision:
        document_class = requested_document_class or self._classify_document(
            pdf_name=pdf_name,
            xml_name=xml_name,
            xml_schema_family_id=xml_schema_family_id,
        )
        if document_class not in DEFAULTS_BY_CLASS:
            raise ValueError(f"Unknown document class: {document_class}")

        defaults = DEFAULTS_BY_CLASS[document_class]
        extraction_profile = get_extraction_profile(requested_extraction_profile or defaults["extraction_profile"])
        evaluation_profile = get_evaluation_profile(requested_evaluation_profile or defaults["evaluation_profile"])
        extractor_strategy = requested_extractor_strategy or defaults["extractor_strategy"]
        if extractor_strategy not in {"pdfplumber", "docling"}:
            raise ValueError(f"Unknown extractor strategy: {extractor_strategy}")
        extractor_options = self._extractor_options(
            extractor_strategy=extractor_strategy,
            document_class=document_class,
            pdf_name=pdf_name,
            xml_name=xml_name,
        )

        notes = [
            f"classified_as:{document_class}",
            f"extraction_profile:{extraction_profile.profile_id}",
            f"evaluation_profile:{evaluation_profile.profile_id}",
            f"extractor_strategy:{extractor_strategy}",
        ]
        if xml_schema_family_id:
            notes.append(f"xml_schema_family:{xml_schema_family_id}")
        if extractor_strategy == "docling":
            notes.append(f"docling_mode:{extractor_options.get('docling_mode', 'text')}")
        if extraction_profile.glossary_first:
            notes.append("glossary_first")
        if evaluation_profile.grouped_targets:
            notes.append("grouped_parity")

        return DocumentStrategyDecision(
            document_class=document_class,
            extraction_profile=extraction_profile,
            evaluation_profile=evaluation_profile,
            extractor_strategy=extractor_strategy,
            review_policy=extraction_profile.review_policy,
            extractor_options=extractor_options,
            notes=notes,
        )

    def _classify_document(
        self,
        *,
        pdf_name: str,
        xml_name: str,
        xml_schema_family_id: str | None = None,
    ) -> str:
        schema_class = self._document_class_from_schema_family(xml_schema_family_id)
        if schema_class:
            return schema_class
        combined = f"{pdf_name} {xml_name}".lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", combined)

        if any(token in normalized for token in ("schedule", "glossary", "definition", "defined term")):
            return "definitions_glossary"
        if any(token in normalized for token in ("interpret", "governance", "application", "a1", "part a")):
            return "governance_interpretation"
        if any(token in normalized for token in ("contents", "cover", "preface", "front matter", "about this")):
            return "front_matter_non_parity"
        return "clause_parity"

    def _document_class_from_schema_family(self, xml_schema_family_id: str | None) -> str | None:
        if xml_schema_family_id == "abcb_glossentry":
            return "definitions_glossary"
        if xml_schema_family_id in {"ncc_clause", "table_reference", "image_reference"}:
            return "clause_parity"
        return None

    def _extractor_options(
        self,
        *,
        extractor_strategy: str,
        document_class: str,
        pdf_name: str,
        xml_name: str,
    ) -> dict[str, str]:
        if extractor_strategy != "docling":
            return {}
        if self._should_enable_docling_tables(document_class=document_class, pdf_name=pdf_name, xml_name=xml_name):
            return {"docling_mode": "tables"}
        return {"docling_mode": "text"}

    def _should_enable_docling_tables(self, *, document_class: str, pdf_name: str, xml_name: str) -> bool:
        if document_class != "clause_parity":
            return False
        combined = f"{pdf_name} {xml_name}".lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", combined)
        return any(
            phrase in normalized
            for phrase in (
                "energy efficiency",
                "section j",
                "part j2",
                "part j3",
                "parts j2 and j3",
            )
        )
