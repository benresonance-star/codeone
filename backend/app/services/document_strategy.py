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
        requested_document_class: str | None = None,
        requested_extraction_profile: str | None = None,
        requested_evaluation_profile: str | None = None,
        requested_extractor_strategy: str | None = None,
    ) -> DocumentStrategyDecision:
        document_class = requested_document_class or self._classify_document(pdf_name=pdf_name, xml_name=xml_name)
        if document_class not in DEFAULTS_BY_CLASS:
            raise ValueError(f"Unknown document class: {document_class}")

        defaults = DEFAULTS_BY_CLASS[document_class]
        extraction_profile = get_extraction_profile(requested_extraction_profile or defaults["extraction_profile"])
        evaluation_profile = get_evaluation_profile(requested_evaluation_profile or defaults["evaluation_profile"])
        extractor_strategy = requested_extractor_strategy or defaults["extractor_strategy"]
        if extractor_strategy not in {"pdfplumber", "docling"}:
            raise ValueError(f"Unknown extractor strategy: {extractor_strategy}")

        notes = [
            f"classified_as:{document_class}",
            f"extraction_profile:{extraction_profile.profile_id}",
            f"evaluation_profile:{evaluation_profile.profile_id}",
            f"extractor_strategy:{extractor_strategy}",
        ]
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
            notes=notes,
        )

    def _classify_document(self, *, pdf_name: str, xml_name: str) -> str:
        combined = f"{pdf_name} {xml_name}".lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", combined)

        if any(token in normalized for token in ("schedule", "glossary", "definition", "defined term")):
            return "definitions_glossary"
        if any(token in normalized for token in ("interpret", "governance", "application", "a1", "part a")):
            return "governance_interpretation"
        if any(token in normalized for token in ("contents", "cover", "preface", "front matter", "about this")):
            return "front_matter_non_parity"
        return "clause_parity"
