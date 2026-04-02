from __future__ import annotations

from app.models.document_strategy import EvaluationProfile


EVALUATION_PROFILES: dict[str, EvaluationProfile] = {
    "baseline_clause_parity": EvaluationProfile(
        profile_id="baseline_clause_parity",
        description="Direct clause-to-clause parity when a stable XML counterpart exists.",
        parity_mode="one_to_one",
    ),
    "definitions_glossary": EvaluationProfile(
        profile_id="definitions_glossary",
        description="Grouped glossary parity across one-to-many definition targets.",
        parity_mode="one_to_many",
        grouped_targets=True,
        glossary_semantics=True,
    ),
    "governance_interpretation": EvaluationProfile(
        profile_id="governance_interpretation",
        description="Interpretive parity with grouped review for ambiguity-sensitive content.",
        parity_mode="one_to_many",
        grouped_targets=True,
    ),
    "front_matter_non_parity": EvaluationProfile(
        profile_id="front_matter_non_parity",
        description="Traceability-only handling for non-parity source material.",
        parity_mode="traceability_only",
    ),
}


def get_evaluation_profile(profile_id: str) -> EvaluationProfile:
    try:
        return EVALUATION_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown evaluation profile: {profile_id}") from exc
