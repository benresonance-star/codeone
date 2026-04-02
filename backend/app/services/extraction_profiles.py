from __future__ import annotations

from app.models.document_strategy import ExtractionProfile, ReviewPolicy


EXTRACTION_PROFILES: dict[str, ExtractionProfile] = {
    "baseline_clause_parity": ExtractionProfile(
        profile_id="baseline_clause_parity",
        description="Standard clause extraction for one-to-one parity validation.",
        prefer_docling=True,
        review_policy=ReviewPolicy(),
    ),
    "definitions_glossary": ExtractionProfile(
        profile_id="definitions_glossary",
        description="Glossary-first extraction tuned for defined terms and distributed references.",
        prefer_docling=True,
        glossary_first=True,
        review_policy=ReviewPolicy(
            require_review_for_grouped_parity=True,
            require_review_for_interpretive_content=True,
        ),
    ),
    "governance_interpretation": ExtractionProfile(
        profile_id="governance_interpretation",
        description="Interpretive and governance extraction with higher review sensitivity.",
        prefer_docling=True,
        review_policy=ReviewPolicy(
            max_unresolved_for_review=3,
            max_low_confidence_for_review=3,
            require_review_for_interpretive_content=True,
        ),
    ),
    "front_matter_non_parity": ExtractionProfile(
        profile_id="front_matter_non_parity",
        description="Front matter extraction where parity is secondary to traceability.",
        prefer_docling=False,
        review_policy=ReviewPolicy(
            max_unresolved_for_review=2,
            max_low_confidence_for_review=2,
        ),
    ),
}


def get_extraction_profile(profile_id: str) -> ExtractionProfile:
    try:
        return EXTRACTION_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown extraction profile: {profile_id}") from exc
