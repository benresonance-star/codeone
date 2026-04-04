from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4
import xml.etree.ElementTree as ET

from app.core.contracts import project_root

SCHEMA_NORMALIZER_VERSION = "1"

DEFAULT_APPROVED_SCHEMA_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "schema_family_id": "ncc_document",
        "schema_family_version": "1",
        "schema_family_NCC_volume": None,
        "schema_family_NCC_version": "2022",
        "schema_family_NCC_ammendment": None,
        "parser_profile": "ncc_document",
        "match_rules": {
            "root_tags": ["ncc", "NCC"],
            "required_children": [],
            "recommended_children": ["part", "clause", "table-reference", "image-reference"],
            "outputclass_hints": [],
        },
        "approved_fingerprint_hashes": [],
    },
    {
        "schema_family_id": "ncc_part",
        "schema_family_version": "1",
        "schema_family_NCC_volume": None,
        "schema_family_NCC_version": "2022",
        "schema_family_NCC_ammendment": None,
        "parser_profile": "ncc_part",
        "match_rules": {
            "root_tags": ["part"],
            "required_children": [],
            "recommended_children": ["num", "title"],
            "outputclass_hints": ["ncc-part"],
        },
        "approved_fingerprint_hashes": [],
    },
    {
        "schema_family_id": "ncc_clause",
        "schema_family_version": "1",
        "schema_family_NCC_volume": None,
        "schema_family_NCC_version": "2022",
        "schema_family_NCC_ammendment": None,
        "parser_profile": "ncc_clause",
        "match_rules": {
            "root_tags": ["clause"],
            "required_children": [],
            "recommended_children": ["title", "sptc", "p", "subclause"],
            "outputclass_hints": ["ncc-clause"],
        },
        "approved_fingerprint_hashes": [],
    },
    {
        "schema_family_id": "table_reference",
        "schema_family_version": "1",
        "schema_family_NCC_volume": None,
        "schema_family_NCC_version": "2022",
        "schema_family_NCC_ammendment": None,
        "parser_profile": "table_reference",
        "match_rules": {
            "root_tags": ["table-reference"],
            "required_children": ["table"],
            "recommended_children": ["num", "title"],
            "outputclass_hints": [],
        },
        "approved_fingerprint_hashes": [],
    },
    {
        "schema_family_id": "image_reference",
        "schema_family_version": "1",
        "schema_family_NCC_volume": None,
        "schema_family_NCC_version": "2022",
        "schema_family_NCC_ammendment": None,
        "parser_profile": "image_reference",
        "match_rules": {
            "root_tags": ["image-reference"],
            "required_children": [],
            "recommended_children": ["title", "image", "caption"],
            "outputclass_hints": [],
        },
        "approved_fingerprint_hashes": [],
    },
    {
        "schema_family_id": "abcb_glossentry",
        "schema_family_version": "1",
        "schema_family_NCC_volume": None,
        "schema_family_NCC_version": "2022",
        "schema_family_NCC_ammendment": None,
        "parser_profile": "abcb_glossentry",
        "match_rules": {
            "root_tags": ["abcb-glossentry", "glossentry"],
            "required_children": ["glossterm", "glossdef"],
            "recommended_children": [],
            "outputclass_hints": ["abcb-glossentry"],
        },
        "approved_fingerprint_hashes": [],
    },
)

DEFAULT_APPROVED_SCHEMA_TAGS: tuple[dict[str, Any], ...] = ()


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


class XmlSchemaRegistryService:
    def __init__(self) -> None:
        self._storage_root = self._resolve_storage_root()
        self._registry_root = self._storage_root / "schema-registry"
        self._registry_root.mkdir(parents=True, exist_ok=True)
        self._batch_root = self._registry_root / "batches"
        self._batch_root.mkdir(parents=True, exist_ok=True)
        self._approved_registry_path = self._registry_root / "approved_schema_registry.json"
        self._approved_tag_registry_path = self._registry_root / "approved_tag_schema_registry.json"
        self._observed_registry_path = self._registry_root / "observed_schema_registry.json"
        self._repo_registry_root = project_root() / "data" / "schema-registry"
        self._repo_registry_root.mkdir(parents=True, exist_ok=True)
        self._repo_approved_registry_path = self._repo_registry_root / "approved_schema_registry.json"
        self._repo_approved_tag_registry_path = self._repo_registry_root / "approved_tag_schema_registry.json"

    def load_approved_registry(self) -> dict[str, Any]:
        registry = self._load_runtime_approved_registry()
        return self._attach_repo_sync(
            registry,
            repo_path=self._repo_approved_registry_path,
        )

    def load_approved_tag_registry(self) -> dict[str, Any]:
        registry = self._load_runtime_approved_tag_registry()
        return self._attach_repo_sync(
            registry,
            repo_path=self._repo_approved_tag_registry_path,
        )

    def load_observed_registry(self) -> dict[str, Any]:
        if not self._observed_registry_path.exists():
            return self._empty_observed_registry()
        return self._read_json(self._observed_registry_path)

    def list_schema_families(self, registry_type: str) -> list[dict[str, Any]]:
        registry = self.load_approved_registry() if registry_type == "approved" else self.load_observed_registry()
        return list(registry.get("families") or [])

    def list_schema_tags(self, registry_type: str) -> list[dict[str, Any]]:
        registry = self.load_approved_tag_registry() if registry_type == "approved" else self.load_observed_registry()
        return list(registry.get("tags") or [])

    def get_schema_family_detail(self, registry_type: str, family_key: str) -> dict[str, Any]:
        families = self.list_schema_families(registry_type)
        key_name = "schema_family_id" if registry_type == "approved" else "fingerprint_hash"
        family = next((item for item in families if str(item.get(key_name)) == family_key), None)
        if family is None:
            raise LookupError("Schema family not found.")
        registry = self.load_approved_registry() if registry_type == "approved" else self.load_observed_registry()
        return {
            "registry_type": registry_type,
            "registry_version": registry.get("registry_version"),
            "family": family,
        }

    def get_schema_tag_detail(self, registry_type: str, tag_key: str) -> dict[str, Any]:
        tags = self.list_schema_tags(registry_type)
        key_name = "schema_tag_id" if registry_type == "approved" else "tag_fingerprint_hash"
        tag = next((item for item in tags if str(item.get(key_name)) == tag_key), None)
        if tag is None:
            raise LookupError("Schema tag not found.")
        registry = self.load_approved_tag_registry() if registry_type == "approved" else self.load_observed_registry()
        return {
            "registry_type": registry_type,
            "registry_version": registry.get("registry_version"),
            "tag": tag,
        }

    def scan_repo_xml_corpus(self) -> dict[str, Any]:
        corpus_root = project_root() / "Spec"
        xml_files = sorted(path for path in corpus_root.rglob("*.xml") if path.is_file())
        sources = [
            {
                "file_name": path.name,
                "source_path": str(path.relative_to(project_root())).replace("\\", "/"),
                "content": path.read_bytes(),
            }
            for path in xml_files
        ]
        registry = self._build_family_registry(sources=sources, registry_prefix="observed")
        self._write_json(self._observed_registry_path, registry)
        return registry

    def scan_uploaded_xml_batch(self, files: list[tuple[str, bytes]]) -> dict[str, Any]:
        sources = [
            {
                "file_name": file_name,
                "source_path": file_name,
                "content": content,
            }
            for file_name, content in files
        ]
        batch_job_id = f"batch_{uuid4().hex[:12]}"
        registry_payload = self._build_family_registry(sources=sources, registry_prefix="uploaded_batch")
        merged_observed_registry = self._merge_uploaded_registry_into_observed(registry_payload)
        batch_payload = {
            "batch_job_id": batch_job_id,
            **registry_payload,
            "observed_registry_version": merged_observed_registry.get("registry_version"),
            "observed_family_count": merged_observed_registry.get("family_count"),
            "observed_tag_count": merged_observed_registry.get("tag_count"),
            "observed_merge_applied": True,
        }
        self._write_json(self._batch_root / f"{batch_job_id}.json", batch_payload)
        return batch_payload

    def load_batch_job(self, batch_job_id: str) -> dict[str, Any]:
        batch_path = self._batch_root / f"{batch_job_id}.json"
        if not batch_path.exists():
            raise LookupError("Schema batch job not found.")
        return self._read_json(batch_path)

    def approve_observed_family(
        self,
        *,
        fingerprint_hash: str,
        schema_family_id: str | None = None,
        parser_profile: str | None = None,
        registry_type: str | None = None,
        batch_job_id: str | None = None,
    ) -> dict[str, Any]:
        approved_registry = self._load_runtime_approved_registry()
        observed = self._load_family_for_approval(
            fingerprint_hash=fingerprint_hash,
            registry_type=registry_type,
            batch_job_id=batch_job_id,
        )
        if observed is None:
            raise LookupError("Observed schema family not found.")

        target_family_id = schema_family_id or str(observed.get("suggested_schema_family_id") or self._suggest_schema_family_id(observed))
        target_parser_profile = parser_profile or str(observed.get("suggested_parser_profile") or target_family_id)

        families = list(approved_registry.get("families") or [])
        family = next((item for item in families if str(item.get("schema_family_id")) == target_family_id), None)
        if family is None:
            family = {
                "schema_family_id": target_family_id,
                "schema_family_version": "1",
                "schema_family_NCC_volume": None,
                "schema_family_NCC_version": "2022",
                "schema_family_NCC_ammendment": None,
                "parser_profile": target_parser_profile,
                "match_rules": {
                    "root_tags": [observed.get("root_tag")],
                    "required_children": list(observed.get("direct_child_tags") or []),
                    "recommended_children": [],
                    "outputclass_hints": [observed.get("outputclass")] if observed.get("outputclass") else [],
                },
                "approved_fingerprint_hashes": [],
            }
            families.append(family)
        approved_hashes = {str(item) for item in (family.get("approved_fingerprint_hashes") or [])}
        approved_hashes.add(fingerprint_hash)
        family["approved_fingerprint_hashes"] = sorted(approved_hashes)
        family["last_updated"] = utc_now_iso()
        family["parser_profile"] = target_parser_profile
        approved_registry["families"] = families
        approved_registry["registry_version"] = f"approved_{utc_now_iso().replace(':', '').replace('-', '')}"
        approved_registry["generated_at"] = utc_now_iso()
        self._write_json(self._approved_registry_path, approved_registry)
        repo_sync = self._sync_approved_registry_to_repo(approved_registry)
        return {
            "registry_version": approved_registry["registry_version"],
            "approved_family": family,
            "fingerprint_hash": fingerprint_hash,
            "repo_sync": repo_sync,
        }

    def approve_observed_tag(
        self,
        *,
        tag_fingerprint_hash: str,
        schema_tag_id: str | None = None,
        parser_profile: str | None = None,
        registry_type: str | None = None,
        batch_job_id: str | None = None,
    ) -> dict[str, Any]:
        approved_registry = self._load_runtime_approved_tag_registry()
        observed = self._load_tag_for_approval(
            tag_fingerprint_hash=tag_fingerprint_hash,
            registry_type=registry_type,
            batch_job_id=batch_job_id,
        )
        if observed is None:
            raise LookupError("Observed schema tag not found.")

        target_tag_id = schema_tag_id or str(observed.get("suggested_schema_tag_id") or self._suggest_schema_tag_id(observed))
        target_parser_profile = parser_profile or str(
            observed.get("suggested_parser_profile") or f"{target_tag_id}_tag"
        )

        tags = list(approved_registry.get("tags") or [])
        tag = next((item for item in tags if str(item.get("schema_tag_id")) == target_tag_id), None)
        if tag is None:
            tag = {
                "schema_tag_id": target_tag_id,
                "schema_tag_version": "1",
                "tag_name": observed.get("tag_name"),
                "parser_profile": target_parser_profile,
                "match_rules": {
                    "tag_names": [observed.get("tag_name")],
                    "required_children": list(observed.get("direct_child_tags") or []),
                    "outputclass_hints": [observed.get("outputclass")] if observed.get("outputclass") else [],
                    "attribute_names": list(observed.get("attribute_names") or []),
                    "text_required": bool(observed.get("text_present")),
                    "parent_tag_hints": [item["tag"] for item in (observed.get("common_parent_tags") or [])[:8]],
                    "context_path_hints": [item["path"] for item in (observed.get("common_paths") or [])[:8]],
                },
                "approved_tag_fingerprint_hashes": [],
            }
            tags.append(tag)
        approved_hashes = {str(item) for item in (tag.get("approved_tag_fingerprint_hashes") or [])}
        approved_hashes.add(tag_fingerprint_hash)
        tag["approved_tag_fingerprint_hashes"] = sorted(approved_hashes)
        tag["tag_name"] = observed.get("tag_name")
        tag["parser_profile"] = target_parser_profile
        self._merge_tag_summary(tag, observed)
        tag["last_updated"] = utc_now_iso()

        approved_registry["tags"] = sorted(tags, key=lambda item: str(item.get("schema_tag_id", "")))
        approved_registry["tag_count"] = len(approved_registry["tags"])
        approved_registry["registry_version"] = f"approved_tags_{utc_now_iso().replace(':', '').replace('-', '')}"
        approved_registry["generated_at"] = utc_now_iso()
        self._write_json(self._approved_tag_registry_path, approved_registry)
        repo_sync = self._sync_approved_tag_registry_to_repo(approved_registry)
        return {
            "registry_version": approved_registry["registry_version"],
            "approved_tag": tag,
            "tag_fingerprint_hash": tag_fingerprint_hash,
            "repo_sync": repo_sync,
        }

    def build_structural_fingerprint(self, root: ET.Element, *, source_path: str | None = None) -> dict[str, Any]:
        root_tag = self._element_tag_name(root)
        direct_child_tags = sorted({self._element_tag_name(child) for child in root})
        namespace_hints = sorted({self._namespace_uri(root.tag), *(self._namespace_uri(child.tag) for child in root)} - {""})
        outputclass = clean_text(root.attrib.get("outputclass"))
        path_signature = f"{root_tag}>{'|'.join(direct_child_tags[:12])}"
        fingerprint_payload = {
            "root_tag": root_tag,
            "outputclass": outputclass or None,
            "namespace_hints": namespace_hints,
            "direct_child_tags": direct_child_tags,
            "path_signature": path_signature,
        }
        fingerprint_hash = hashlib.sha1(json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")).hexdigest()
        return {
            **fingerprint_payload,
            "fingerprint_hash": fingerprint_hash,
            "child_tag_signature": ", ".join(direct_child_tags),
            "source_path": source_path,
        }

    def match_against_approved_registry(
        self,
        root: ET.Element,
        *,
        approved_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        registry = approved_registry or self.load_approved_registry()
        fingerprint = self.build_structural_fingerprint(root)
        root_tag = fingerprint["root_tag"]
        direct_child_tags = set(fingerprint["direct_child_tags"])
        outputclass = clean_text(root.attrib.get("outputclass")).lower()

        best_match: dict[str, Any] | None = None
        best_score = -1.0

        for family in registry.get("families") or []:
            match_rules = family.get("match_rules") or {}
            root_tags = {str(tag) for tag in (match_rules.get("root_tags") or [])}
            if root_tag not in root_tags:
                continue
            required_children = {str(tag) for tag in (match_rules.get("required_children") or [])}
            recommended_children = {str(tag) for tag in (match_rules.get("recommended_children") or [])}
            outputclass_hints = {clean_text(str(tag)).lower() for tag in (match_rules.get("outputclass_hints") or []) if clean_text(str(tag))}
            missing_required = sorted(required_children - direct_child_tags)
            missing_recommended = sorted(recommended_children - direct_child_tags)
            required_score = 1.0 if not required_children else ratio(len(required_children) - len(missing_required), len(required_children))
            recommended_score = 1.0 if not recommended_children else ratio(len(recommended_children) - len(missing_recommended), len(recommended_children))
            outputclass_score = 1.0 if not outputclass_hints or outputclass in outputclass_hints else 0.0
            exact_fingerprint_match = fingerprint["fingerprint_hash"] in {str(item) for item in (family.get("approved_fingerprint_hashes") or [])}
            score = round((required_score * 0.6) + (recommended_score * 0.25) + (outputclass_score * 0.15), 3)
            if exact_fingerprint_match:
                score = max(score, 0.99)
            if score > best_score:
                best_score = score
                best_match = {
                    "schema_family_id": family.get("schema_family_id"),
                    "schema_family_version": family.get("schema_family_version"),
                    "schema_match_confidence": score,
                    "schema_match_reasons": [
                        f"root:{root_tag}",
                        f"required_children_present:{len(required_children) - len(missing_required)}/{len(required_children)}",
                        f"recommended_children_present:{len(recommended_children) - len(missing_recommended)}/{len(recommended_children)}",
                        f"outputclass_match:{outputclass_score == 1.0}",
                        f"exact_fingerprint_match:{exact_fingerprint_match}",
                    ],
                    "schema_approved": not missing_required,
                    "schema_variant_detected": bool(missing_recommended) and not missing_required,
                    "unknown_schema_family": False,
                    "required_structure_missing": bool(missing_required),
                    "parser_profile": family.get("parser_profile"),
                    "registry_version": registry.get("registry_version"),
                    "normalizer_version": registry.get("normalizer_version") or SCHEMA_NORMALIZER_VERSION,
                    "fingerprint_hash": fingerprint["fingerprint_hash"],
                }

        if best_match is not None:
            return best_match

        return {
            "schema_family_id": None,
            "schema_family_version": None,
            "schema_match_confidence": 0.0,
            "schema_match_reasons": [f"root:{root_tag}", "no_approved_schema_family_match"],
            "schema_approved": False,
            "schema_variant_detected": False,
            "unknown_schema_family": True,
            "required_structure_missing": False,
            "parser_profile": None,
            "registry_version": registry.get("registry_version"),
            "normalizer_version": registry.get("normalizer_version") or SCHEMA_NORMALIZER_VERSION,
            "fingerprint_hash": fingerprint["fingerprint_hash"],
        }

    def _seed_approved_registry(self) -> dict[str, Any]:
        return {
            "registry_version": "approved_seed_v1",
            "generated_at": utc_now_iso(),
            "normalizer_version": SCHEMA_NORMALIZER_VERSION,
            "families": [dict(item) for item in DEFAULT_APPROVED_SCHEMA_FAMILIES],
        }

    def _seed_approved_tag_registry(self) -> dict[str, Any]:
        return {
            "registry_version": "approved_tag_seed_v1",
            "generated_at": utc_now_iso(),
            "normalizer_version": SCHEMA_NORMALIZER_VERSION,
            "tag_count": len(DEFAULT_APPROVED_SCHEMA_TAGS),
            "tags": [dict(item) for item in DEFAULT_APPROVED_SCHEMA_TAGS],
        }

    def _load_runtime_approved_registry(self) -> dict[str, Any]:
        if not self._approved_registry_path.exists():
            registry = self._seed_approved_registry()
            self._write_json(self._approved_registry_path, registry)
            self._sync_approved_registry_to_repo(registry)
            return registry
        registry = self._read_json(self._approved_registry_path)
        normalized_registry, changed = self._normalize_approved_registry(registry)
        if changed:
            self._write_json(self._approved_registry_path, normalized_registry)
            self._sync_approved_registry_to_repo(normalized_registry)
        return normalized_registry

    def _load_runtime_approved_tag_registry(self) -> dict[str, Any]:
        if not self._approved_tag_registry_path.exists():
            registry = self._seed_approved_tag_registry()
            self._write_json(self._approved_tag_registry_path, registry)
            self._sync_approved_tag_registry_to_repo(registry)
            return registry
        registry = self._read_json(self._approved_tag_registry_path)
        normalized_registry, changed = self._normalize_approved_tag_registry(registry)
        if changed:
            self._write_json(self._approved_tag_registry_path, normalized_registry)
            self._sync_approved_tag_registry_to_repo(normalized_registry)
        return normalized_registry

    def _normalize_approved_registry(self, registry: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        changed = False
        families: list[dict[str, Any]] = []
        for family in list(registry.get("families") or []):
            normalized_family = dict(family)
            if "schema_family_NCC_volume" not in normalized_family:
                normalized_family["schema_family_NCC_volume"] = None
                changed = True
            if "schema_family_NCC_version" not in normalized_family:
                normalized_family["schema_family_NCC_version"] = "2022"
                changed = True
            if "schema_family_NCC_ammendment" not in normalized_family:
                normalized_family["schema_family_NCC_ammendment"] = None
                changed = True
            families.append(normalized_family)
        if not changed:
            return registry, False
        return {**registry, "families": families}, True

    def _normalize_approved_tag_registry(self, registry: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        changed = False
        tags: list[dict[str, Any]] = []
        for tag in list(registry.get("tags") or []):
            normalized_tag = dict(tag)
            if "schema_tag_version" not in normalized_tag:
                normalized_tag["schema_tag_version"] = "1"
                changed = True
            if "approved_tag_fingerprint_hashes" not in normalized_tag:
                normalized_tag["approved_tag_fingerprint_hashes"] = []
                changed = True
            if "match_rules" not in normalized_tag:
                normalized_tag["match_rules"] = {}
                changed = True
            tags.append(normalized_tag)
        normalized = {**registry, "tag_count": len(tags), "tags": tags}
        if not changed and int(registry.get("tag_count") or 0) == len(tags):
            return normalized, False
        return normalized, True

    def _sync_approved_registry_to_repo(self, registry: dict[str, Any]) -> dict[str, Any]:
        export_payload = {
            **self._registry_core_payload(registry),
            "export_mode": "runtime_exported_to_repo",
            "repo_export_path": self._repo_registry_relative_path(self._repo_approved_registry_path),
            "exported_from_runtime_at": utc_now_iso(),
        }
        self._write_json(self._repo_approved_registry_path, export_payload)
        return self._repo_sync_metadata(registry, repo_path=self._repo_approved_registry_path)

    def _sync_approved_tag_registry_to_repo(self, registry: dict[str, Any]) -> dict[str, Any]:
        export_payload = {
            **self._registry_core_payload(registry),
            "export_mode": "runtime_exported_to_repo",
            "repo_export_path": self._repo_registry_relative_path(self._repo_approved_tag_registry_path),
            "exported_from_runtime_at": utc_now_iso(),
        }
        self._write_json(self._repo_approved_tag_registry_path, export_payload)
        return self._repo_sync_metadata(registry, repo_path=self._repo_approved_tag_registry_path)

    def _attach_repo_sync(self, registry: dict[str, Any], *, repo_path: Path) -> dict[str, Any]:
        return {
            **registry,
            "repo_sync": self._repo_sync_metadata(registry, repo_path=repo_path),
        }

    def _repo_sync_metadata(self, registry: dict[str, Any], *, repo_path: Path) -> dict[str, Any]:
        runtime_checksum = self._registry_checksum(registry)
        repo_exists = repo_path.exists()
        if not repo_exists:
            return {
                "mode": "runtime_exported_to_repo",
                "repo_path": self._repo_registry_relative_path(repo_path),
                "repo_exists": False,
                "export_status": "missing",
                "synced": False,
                "drift_detected": False,
                "runtime_checksum": runtime_checksum,
                "repo_checksum": None,
                "last_exported_at": None,
                "repo_registry_version": None,
            }

        repo_payload = self._read_json(repo_path)
        repo_checksum = self._registry_checksum(repo_payload)
        synced = repo_checksum == runtime_checksum
        return {
            "mode": "runtime_exported_to_repo",
            "repo_path": self._repo_registry_relative_path(repo_path),
            "repo_exists": True,
            "export_status": "synced" if synced else "drifted",
            "synced": synced,
            "drift_detected": not synced,
            "runtime_checksum": runtime_checksum,
            "repo_checksum": repo_checksum,
            "last_exported_at": repo_payload.get("exported_from_runtime_at"),
            "repo_registry_version": repo_payload.get("registry_version"),
        }

    def _build_family_registry(self, *, sources: list[dict[str, Any]], registry_prefix: str) -> dict[str, Any]:
        approved_registry = self.load_approved_registry()
        approved_tag_registry = self.load_approved_tag_registry()
        families_by_hash: dict[str, dict[str, Any]] = {}
        tags_by_hash: dict[str, dict[str, Any]] = {}
        scan_errors: list[dict[str, Any]] = []
        scanned_file_count = 0

        for source in sources:
            file_name = str(source.get("file_name") or "")
            source_path = str(source.get("source_path") or file_name or "uploaded.xml")
            content = source.get("content")
            if not isinstance(content, (bytes, bytearray)) or not content:
                scan_errors.append({"file": source_path, "error": "Uploaded file was empty."})
                continue
            if not file_name.lower().endswith(".xml"):
                scan_errors.append({"file": source_path, "error": "Only XML files are accepted in uploaded schema batches."})
                continue
            try:
                root = ET.fromstring(content)
            except ET.ParseError as exc:
                scan_errors.append({"file": source_path, "error": str(exc)})
                continue

            scanned_file_count += 1
            fingerprint = self.build_structural_fingerprint(root, source_path=source_path)
            tree_summary = self._summarize_xml_tree(root)
            runtime_match = self.match_against_approved_registry(root, approved_registry=approved_registry)
            for tag_observation in self._summarize_tag_schemas(root, source_path=source_path, approved_registry=approved_tag_registry):
                observed_tag = tags_by_hash.setdefault(
                    tag_observation["tag_fingerprint_hash"],
                    {
                        **tag_observation,
                        "occurrence_count": 0,
                        "file_count": 0,
                        "files": [],
                        "example_files": [],
                        "example_paths": [],
                        "example_texts": [],
                        "parent_tag_counts": {},
                        "nearest_structural_parent_counts": {},
                        "context_path_counts": {},
                        "_file_set": [],
                    },
                )
                self._merge_tag_observation(observed_tag, tag_observation)
            observed = families_by_hash.setdefault(
                fingerprint["fingerprint_hash"],
                {
                    **fingerprint,
                    "file_count": 0,
                    "files": [],
                    "example_files": [],
                    "last_seen": None,
                    "status": (
                        "variant"
                        if runtime_match["schema_variant_detected"]
                        else "approved"
                        if runtime_match["schema_approved"]
                        else "unknown"
                    ),
                    "nearest_approved_schema_family_id": runtime_match["schema_family_id"],
                    "suggested_schema_family_id": runtime_match["schema_family_id"] or self._suggest_schema_family_id(fingerprint),
                    "suggested_parser_profile": runtime_match["parser_profile"] or self._suggest_schema_family_id(fingerprint),
                    "match_confidence": runtime_match["schema_match_confidence"],
                    "match_reasons": runtime_match["schema_match_reasons"],
                    "schema_variant_detected": runtime_match["schema_variant_detected"],
                    "schema_approved": runtime_match["schema_approved"],
                    "required_structure_missing": runtime_match["required_structure_missing"],
                },
            )
            self._merge_tree_summary(observed, tree_summary)
            observed["file_count"] += 1
            observed["files"].append(source_path)
            if len(observed["example_files"]) < 5:
                observed["example_files"].append(source_path)
            observed["last_seen"] = utc_now_iso()

        families = sorted(
            (self._finalize_tree_summary(family) for family in families_by_hash.values()),
            key=lambda item: (-int(item.get("file_count", 0)), str(item.get("fingerprint_hash", ""))),
        )
        tags = sorted(
            (self._finalize_tag_summary(tag) for tag in tags_by_hash.values()),
            key=lambda item: (-int(item.get("occurrence_count", 0)), str(item.get("tag_fingerprint_hash", ""))),
        )
        registry_version = self._registry_version_from_entries(
            registry_prefix=registry_prefix,
            families=families,
            tags=tags,
        )
        return {
            "registry_version": registry_version,
            "generated_at": utc_now_iso(),
            "uploaded_file_count": len(sources),
            "scanned_file_count": scanned_file_count,
            "family_count": len(families),
            "tag_count": len(tags),
            "families": families,
            "tags": tags,
            "scan_errors": scan_errors,
            "approved_registry_version": approved_registry.get("registry_version"),
            "approved_tag_registry_version": approved_tag_registry.get("registry_version"),
        }

    def _load_family_for_approval(
        self,
        *,
        fingerprint_hash: str,
        registry_type: str | None,
        batch_job_id: str | None,
    ) -> dict[str, Any] | None:
        normalized_type = str(registry_type or "observed").lower()
        if normalized_type == "batch":
            if not batch_job_id:
                return None
            batch_payload = self.load_batch_job(batch_job_id)
            families = batch_payload.get("families") or []
        else:
            observed_registry = self.load_observed_registry()
            families = observed_registry.get("families") or []
        return next((item for item in families if str(item.get("fingerprint_hash")) == fingerprint_hash), None)

    def _load_tag_for_approval(
        self,
        *,
        tag_fingerprint_hash: str,
        registry_type: str | None,
        batch_job_id: str | None,
    ) -> dict[str, Any] | None:
        normalized_type = str(registry_type or "observed").lower()
        if normalized_type == "batch":
            if not batch_job_id:
                return None
            batch_payload = self.load_batch_job(batch_job_id)
            tags = batch_payload.get("tags") or []
        else:
            observed_registry = self.load_observed_registry()
            tags = observed_registry.get("tags") or []
        return next((item for item in tags if str(item.get("tag_fingerprint_hash")) == tag_fingerprint_hash), None)

    def _empty_observed_registry(self) -> dict[str, Any]:
        return {
            "registry_version": "observed_empty",
            "generated_at": utc_now_iso(),
            "scanned_file_count": 0,
            "family_count": 0,
            "tag_count": 0,
            "families": [],
            "tags": [],
            "scan_errors": [],
        }

    def _merge_uploaded_registry_into_observed(self, uploaded_registry: dict[str, Any]) -> dict[str, Any]:
        observed_registry = self.load_observed_registry()
        merged_registry = self._merge_observed_registry_payloads(
            observed_registry=observed_registry,
            uploaded_registry=uploaded_registry,
        )
        self._write_json(self._observed_registry_path, merged_registry)
        return merged_registry

    def _merge_observed_registry_payloads(
        self,
        *,
        observed_registry: dict[str, Any],
        uploaded_registry: dict[str, Any],
    ) -> dict[str, Any]:
        families_by_hash = {
            str(family.get("fingerprint_hash")): self._hydrate_observed_family(family)
            for family in (observed_registry.get("families") or [])
            if family.get("fingerprint_hash")
        }
        tags_by_hash = {
            str(tag.get("tag_fingerprint_hash")): self._hydrate_observed_tag(tag)
            for tag in (observed_registry.get("tags") or [])
            if tag.get("tag_fingerprint_hash")
        }

        for family in uploaded_registry.get("families") or []:
            fingerprint_hash = str(family.get("fingerprint_hash") or "")
            if not fingerprint_hash:
                continue
            target_family = families_by_hash.get(fingerprint_hash)
            if target_family is None:
                families_by_hash[fingerprint_hash] = self._hydrate_observed_family(family)
                continue
            if self._file_sets_are_subset(target_family.get("files"), family.get("files")):
                continue
            incoming_family = self._hydrate_observed_family(family)
            self._merge_tree_summary(target_family, incoming_family)
            self._merge_family_metadata(target_family, incoming_family)

        for tag in uploaded_registry.get("tags") or []:
            tag_fingerprint_hash = str(tag.get("tag_fingerprint_hash") or "")
            if not tag_fingerprint_hash:
                continue
            target_tag = tags_by_hash.get(tag_fingerprint_hash)
            if target_tag is None:
                tags_by_hash[tag_fingerprint_hash] = self._hydrate_observed_tag(tag)
                continue
            if self._file_sets_are_subset(target_tag.get("files"), tag.get("files")):
                continue
            incoming_tag = self._hydrate_observed_tag(tag)
            self._merge_observed_tag_records(target_tag, incoming_tag)

        families = sorted(
            (self._finalize_tree_summary(family) for family in families_by_hash.values()),
            key=lambda item: (-int(item.get("file_count", 0)), str(item.get("fingerprint_hash", ""))),
        )
        tags = sorted(
            (self._finalize_tag_summary(tag) for tag in tags_by_hash.values()),
            key=lambda item: (-int(item.get("occurrence_count", 0)), str(item.get("tag_fingerprint_hash", ""))),
        )

        scan_errors = list(observed_registry.get("scan_errors") or [])
        existing_scan_error_keys = {
            (str(item.get("file") or ""), str(item.get("error") or ""))
            for item in scan_errors
            if isinstance(item, dict)
        }
        for item in uploaded_registry.get("scan_errors") or []:
            key = (str(item.get("file") or ""), str(item.get("error") or ""))
            if key not in existing_scan_error_keys:
                scan_errors.append(dict(item))
                existing_scan_error_keys.add(key)

        return {
            "registry_version": self._registry_version_from_entries(
                registry_prefix="observed",
                families=families,
                tags=tags,
            ),
            "generated_at": utc_now_iso(),
            "scanned_file_count": int(observed_registry.get("scanned_file_count") or 0)
            + int(uploaded_registry.get("scanned_file_count") or 0),
            "family_count": len(families),
            "tag_count": len(tags),
            "families": families,
            "tags": tags,
            "scan_errors": scan_errors,
            "approved_registry_version": uploaded_registry.get("approved_registry_version")
            or observed_registry.get("approved_registry_version"),
            "approved_tag_registry_version": uploaded_registry.get("approved_tag_registry_version")
            or observed_registry.get("approved_tag_registry_version"),
        }

    def _registry_core_payload(self, registry: dict[str, Any]) -> dict[str, Any]:
        return {
            "registry_version": registry.get("registry_version"),
            "generated_at": registry.get("generated_at"),
            "normalizer_version": registry.get("normalizer_version") or SCHEMA_NORMALIZER_VERSION,
            "families": list(registry.get("families") or []),
            "family_count": int(registry.get("family_count") or 0),
            "tags": list(registry.get("tags") or []),
            "tag_count": int(registry.get("tag_count") or 0),
        }

    def _registry_version_from_entries(
        self,
        *,
        registry_prefix: str,
        families: list[dict[str, Any]],
        tags: list[dict[str, Any]],
    ) -> str:
        return (
            f"{registry_prefix}_"
            f"{hashlib.sha1(json.dumps({'families': [f['fingerprint_hash'] for f in families], 'tags': [t['tag_fingerprint_hash'] for t in tags]}, sort_keys=True).encode('utf-8')).hexdigest()[:12]}"
        )

    def _registry_checksum(self, registry: dict[str, Any]) -> str:
        payload = self._registry_core_payload(registry)
        return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _repo_registry_relative_path(self, repo_path: Path) -> str:
        try:
            return str(repo_path.relative_to(project_root())).replace("\\", "/")
        except ValueError:
            return str(repo_path).replace("\\", "/")

    def _resolve_storage_root(self) -> Path:
        root = project_root() / "runtime-data"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _summarize_xml_tree(self, root: ET.Element) -> dict[str, Any]:
        element_tag_counts: dict[str, int] = defaultdict(int)
        attribute_name_counts: dict[str, int] = defaultdict(int)
        path_counts: dict[str, int] = defaultdict(int)
        leaf_tags: set[str] = set()
        highlighted_paths: dict[str, list[str]] = {
            "title": [],
            "xref": [],
            "section": [],
            "table": [],
            "note": [],
        }
        max_depth = 0
        tree_node_count = 0

        def walk(element: ET.Element, path_segments: list[str]) -> None:
            nonlocal max_depth, tree_node_count

            tag_name = self._element_tag_name(element)
            current_path = [*path_segments, tag_name]
            normalized_path = "/".join(current_path)

            element_tag_counts[tag_name] += 1
            path_counts[normalized_path] += 1
            tree_node_count += 1
            max_depth = max(max_depth, len(current_path) - 1)

            for attribute_name in element.attrib:
                normalized_attribute = attribute_name.split("}")[-1].lower()
                attribute_name_counts[normalized_attribute] += 1

            if tag_name in highlighted_paths and normalized_path not in highlighted_paths[tag_name] and len(highlighted_paths[tag_name]) < 5:
                highlighted_paths[tag_name].append(normalized_path)

            children = list(element)
            if not children:
                leaf_tags.add(tag_name)

            for child in children:
                walk(child, current_path)

        walk(root, [])

        return {
            "all_element_tags": sorted(element_tag_counts),
            "element_tag_counts": dict(sorted(element_tag_counts.items())),
            "attribute_name_counts": dict(sorted(attribute_name_counts.items())),
            "leaf_tags": sorted(leaf_tags),
            "tree_node_count": tree_node_count,
            "max_depth": max_depth,
            "highlighted_paths": {tag: paths for tag, paths in highlighted_paths.items() if paths},
            "_tree_path_counts": dict(path_counts),
        }

    def _merge_tree_summary(self, family: dict[str, Any], tree_summary: dict[str, Any]) -> None:
        family["all_element_tags"] = sorted(
            set(family.get("all_element_tags") or []).union(tree_summary.get("all_element_tags") or [])
        )

        existing_tag_counts = dict(family.get("element_tag_counts") or {})
        for tag_name, count in (tree_summary.get("element_tag_counts") or {}).items():
            existing_tag_counts[str(tag_name)] = int(existing_tag_counts.get(str(tag_name), 0)) + int(count)
        family["element_tag_counts"] = dict(sorted(existing_tag_counts.items()))

        existing_attribute_counts = dict(family.get("attribute_name_counts") or {})
        for attribute_name, count in (tree_summary.get("attribute_name_counts") or {}).items():
            existing_attribute_counts[str(attribute_name)] = int(existing_attribute_counts.get(str(attribute_name), 0)) + int(count)
        family["attribute_name_counts"] = dict(sorted(existing_attribute_counts.items()))

        family["leaf_tags"] = sorted(set(family.get("leaf_tags") or []).union(tree_summary.get("leaf_tags") or []))
        family["tree_node_count"] = int(family.get("tree_node_count") or 0) + int(tree_summary.get("tree_node_count") or 0)
        family["max_depth"] = max(int(family.get("max_depth") or 0), int(tree_summary.get("max_depth") or 0))

        highlighted_paths = {
            str(tag): list(paths)
            for tag, paths in (family.get("highlighted_paths") or {}).items()
            if isinstance(paths, list)
        }
        for tag_name, paths in (tree_summary.get("highlighted_paths") or {}).items():
            merged_paths = highlighted_paths.setdefault(str(tag_name), [])
            for path in paths:
                normalized_path = str(path)
                if normalized_path not in merged_paths and len(merged_paths) < 5:
                    merged_paths.append(normalized_path)
        family["highlighted_paths"] = dict(sorted(highlighted_paths.items()))

        path_counts = dict(family.get("_tree_path_counts") or {})
        for path, count in (tree_summary.get("_tree_path_counts") or {}).items():
            path_counts[str(path)] = int(path_counts.get(str(path), 0)) + int(count)
        family["_tree_path_counts"] = path_counts

    def _finalize_tree_summary(self, family: dict[str, Any]) -> dict[str, Any]:
        finalized = dict(family)
        path_counts = dict(finalized.pop("_tree_path_counts", {}) or {})
        finalized["common_paths"] = [
            {"path": path, "count": count}
            for path, count in sorted(path_counts.items(), key=lambda item: (-int(item[1]), item[0]))[:12]
        ]
        return finalized

    def _hydrate_observed_family(self, family: dict[str, Any]) -> dict[str, Any]:
        hydrated = dict(family)
        hydrated["_tree_path_counts"] = {
            str(item.get("path")): int(item.get("count") or 0)
            for item in (hydrated.get("common_paths") or [])
            if isinstance(item, dict) and item.get("path")
        }
        hydrated["files"] = list(hydrated.get("files") or hydrated.get("example_files") or [])
        hydrated["example_files"] = list(hydrated.get("example_files") or [])
        hydrated["file_count"] = int(hydrated.get("file_count") or len(hydrated["files"]))
        hydrated["all_element_tags"] = list(hydrated.get("all_element_tags") or [])
        hydrated["element_tag_counts"] = dict(hydrated.get("element_tag_counts") or {})
        hydrated["attribute_name_counts"] = dict(hydrated.get("attribute_name_counts") or {})
        hydrated["leaf_tags"] = list(hydrated.get("leaf_tags") or [])
        hydrated["highlighted_paths"] = {
            str(tag): list(paths)
            for tag, paths in (hydrated.get("highlighted_paths") or {}).items()
            if isinstance(paths, list)
        }
        return hydrated

    def _summarize_tag_schemas(
        self,
        root: ET.Element,
        *,
        source_path: str,
        approved_registry: dict[str, Any],
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []

        def walk(element: ET.Element, path_segments: list[str]) -> None:
            tag_name = self._element_tag_name(element)
            current_path = [*path_segments, tag_name]
            direct_child_tags = sorted({self._element_tag_name(child) for child in element})
            attribute_names = sorted({attribute_name.split("}")[-1].lower() for attribute_name in element.attrib})
            namespace_hints = sorted(
                {self._namespace_uri(element.tag), *(self._namespace_uri(child.tag) for child in element)} - {""}
            )
            outputclass = clean_text(element.attrib.get("outputclass")) or None
            text_present = bool(clean_text(" ".join(element.itertext())))
            tag_fingerprint_payload = {
                "tag_name": tag_name,
                "outputclass": outputclass,
                "namespace_hints": namespace_hints,
                "direct_child_tags": direct_child_tags,
                "attribute_names": attribute_names,
                "text_present": text_present,
            }
            tag_fingerprint_hash = hashlib.sha1(
                json.dumps(tag_fingerprint_payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            parent_tag = path_segments[-1] if path_segments else None
            context_path = "/".join(current_path)
            nearest_structural_parent_tag = self._nearest_structural_tag(path_segments)
            runtime_match = self._match_tag_against_approved_registry(
                tag_fingerprint_hash=tag_fingerprint_hash,
                tag_name=tag_name,
                approved_registry=approved_registry,
            )
            cleaned_text = clean_text(" ".join(element.itertext()))
            observations.append(
                {
                    **tag_fingerprint_payload,
                    "tag_fingerprint_hash": tag_fingerprint_hash,
                    "child_tag_signature": ", ".join(direct_child_tags),
                    "source_path": source_path,
                    "tag_name": tag_name,
                    "status": runtime_match["status"],
                    "nearest_approved_schema_tag_id": runtime_match["schema_tag_id"],
                    "suggested_schema_tag_id": runtime_match["schema_tag_id"] or self._suggest_schema_tag_id({"tag_name": tag_name}),
                    "suggested_parser_profile": runtime_match["parser_profile"] or f"{self._suggest_schema_tag_id({'tag_name': tag_name})}_tag",
                    "match_confidence": runtime_match["schema_match_confidence"],
                    "match_reasons": runtime_match["schema_match_reasons"],
                    "schema_approved": runtime_match["schema_approved"],
                    "schema_variant_detected": runtime_match["schema_variant_detected"],
                    "parent_tag": parent_tag,
                    "nearest_structural_parent_tag": nearest_structural_parent_tag,
                    "context_path": context_path,
                    "depth": len(current_path) - 1,
                    "leaf_occurrence_count": 0 if list(element) else 1,
                    "example_text": cleaned_text[:180] if cleaned_text else None,
                }
            )

            for child in element:
                walk(child, current_path)

        walk(root, [])
        return observations

    def _merge_tag_observation(self, target: dict[str, Any], observation: dict[str, Any]) -> None:
        target["occurrence_count"] = int(target.get("occurrence_count") or 0) + 1
        file_set = set(str(item) for item in (target.get("_file_set") or []))
        source_path = str(observation.get("source_path") or "")
        if source_path and source_path not in file_set:
            file_set.add(source_path)
            target["file_count"] = int(target.get("file_count") or 0) + 1
            target["files"] = sorted(file_set)
            if len(target["example_files"]) < 5:
                target["example_files"].append(source_path)
        target["_file_set"] = sorted(file_set)

        for field_name, key_name in (
            ("parent_tag_counts", "parent_tag"),
            ("nearest_structural_parent_counts", "nearest_structural_parent_tag"),
            ("context_path_counts", "context_path"),
        ):
            current_counts = dict(target.get(field_name) or {})
            key = observation.get(key_name)
            if key:
                current_counts[str(key)] = int(current_counts.get(str(key), 0)) + 1
            target[field_name] = current_counts

        example_path = str(observation.get("context_path") or "")
        if example_path and example_path not in target["example_paths"] and len(target["example_paths"]) < 8:
            target["example_paths"].append(example_path)
        example_text = observation.get("example_text")
        if example_text and example_text not in target["example_texts"] and len(target["example_texts"]) < 5:
            target["example_texts"].append(example_text)

        target["max_depth"] = max(int(target.get("max_depth") or 0), int(observation.get("depth") or 0))
        target["leaf_occurrence_count"] = int(target.get("leaf_occurrence_count") or 0) + int(
            observation.get("leaf_occurrence_count") or 0
        )
        target["last_seen"] = utc_now_iso()

    def _merge_tag_summary(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        target["attribute_names"] = sorted(set(target.get("attribute_names") or []).union(source.get("attribute_names") or []))
        target["direct_child_tags"] = sorted(
            set(target.get("direct_child_tags") or []).union(source.get("direct_child_tags") or [])
        )
        target["text_present"] = bool(target.get("text_present")) or bool(source.get("text_present"))

        for field_name in ("common_paths", "common_parent_tags", "common_structural_parents", "example_paths", "example_texts"):
            merged_items: list[Any] = list(target.get(field_name) or [])
            for item in source.get(field_name) or []:
                if item not in merged_items and len(merged_items) < 12:
                    merged_items.append(item)
            target[field_name] = merged_items

    def _finalize_tag_summary(self, tag: dict[str, Any]) -> dict[str, Any]:
        finalized = dict(tag)
        finalized.pop("_file_set", None)
        finalized["common_paths"] = [
            {"path": path, "count": count}
            for path, count in sorted(
                dict(finalized.pop("context_path_counts", {}) or {}).items(),
                key=lambda item: (-int(item[1]), item[0]),
            )[:12]
        ]
        finalized["common_parent_tags"] = [
            {"tag": tag_name, "count": count}
            for tag_name, count in sorted(
                dict(finalized.pop("parent_tag_counts", {}) or {}).items(),
                key=lambda item: (-int(item[1]), item[0]),
            )[:12]
        ]
        finalized["common_structural_parents"] = [
            {"tag": tag_name, "count": count}
            for tag_name, count in sorted(
                dict(finalized.pop("nearest_structural_parent_counts", {}) or {}).items(),
                key=lambda item: (-int(item[1]), item[0]),
            )[:12]
        ]
        return finalized

    def _hydrate_observed_tag(self, tag: dict[str, Any]) -> dict[str, Any]:
        hydrated = dict(tag)
        hydrated["context_path_counts"] = {
            str(item.get("path")): int(item.get("count") or 0)
            for item in (hydrated.get("common_paths") or [])
            if isinstance(item, dict) and item.get("path")
        }
        hydrated["parent_tag_counts"] = {
            str(item.get("tag")): int(item.get("count") or 0)
            for item in (hydrated.get("common_parent_tags") or [])
            if isinstance(item, dict) and item.get("tag")
        }
        hydrated["nearest_structural_parent_counts"] = {
            str(item.get("tag")): int(item.get("count") or 0)
            for item in (hydrated.get("common_structural_parents") or [])
            if isinstance(item, dict) and item.get("tag")
        }
        hydrated["files"] = list(hydrated.get("files") or hydrated.get("example_files") or [])
        hydrated["example_files"] = list(hydrated.get("example_files") or [])
        hydrated["_file_set"] = list(hydrated.get("files") or [])
        hydrated["attribute_names"] = list(hydrated.get("attribute_names") or [])
        hydrated["direct_child_tags"] = list(hydrated.get("direct_child_tags") or [])
        hydrated["example_paths"] = list(hydrated.get("example_paths") or [])
        hydrated["example_texts"] = list(hydrated.get("example_texts") or [])
        hydrated["occurrence_count"] = int(hydrated.get("occurrence_count") or 0)
        hydrated["file_count"] = int(hydrated.get("file_count") or len(hydrated["files"]))
        hydrated["leaf_occurrence_count"] = int(hydrated.get("leaf_occurrence_count") or 0)
        hydrated["max_depth"] = int(hydrated.get("max_depth") or 0)
        return hydrated

    def _merge_family_metadata(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        target["files"] = self._merge_sorted_unique_strings(target.get("files"), source.get("files"))
        target["file_count"] = len(target["files"])
        target["example_files"] = self._merge_limited_unique_strings(
            target.get("example_files"),
            source.get("example_files") or source.get("files"),
            limit=5,
        )
        target["last_seen"] = source.get("last_seen") or utc_now_iso()
        target["match_confidence"] = max(
            float(target.get("match_confidence") or 0.0),
            float(source.get("match_confidence") or 0.0),
        )
        target["match_reasons"] = self._merge_limited_unique_strings(
            target.get("match_reasons"),
            source.get("match_reasons"),
            limit=12,
        )
        target["schema_variant_detected"] = bool(target.get("schema_variant_detected")) or bool(
            source.get("schema_variant_detected")
        )
        target["schema_approved"] = bool(target.get("schema_approved")) or bool(source.get("schema_approved"))
        target["required_structure_missing"] = bool(target.get("required_structure_missing")) and bool(
            source.get("required_structure_missing")
        )
        target["status"] = self._merge_status(target.get("status"), source.get("status"))

    def _merge_observed_tag_records(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        target["files"] = self._merge_sorted_unique_strings(target.get("files"), source.get("files"))
        target["file_count"] = len(target["files"])
        target["_file_set"] = list(target["files"])
        target["example_files"] = self._merge_limited_unique_strings(
            target.get("example_files"),
            source.get("example_files") or source.get("files"),
            limit=5,
        )
        target["attribute_names"] = self._merge_sorted_unique_strings(
            target.get("attribute_names"),
            source.get("attribute_names"),
        )
        target["direct_child_tags"] = self._merge_sorted_unique_strings(
            target.get("direct_child_tags"),
            source.get("direct_child_tags"),
        )
        target["example_paths"] = self._merge_limited_unique_strings(
            target.get("example_paths"),
            source.get("example_paths"),
            limit=8,
        )
        target["example_texts"] = self._merge_limited_unique_strings(
            target.get("example_texts"),
            source.get("example_texts"),
            limit=5,
        )
        target["occurrence_count"] = int(target.get("occurrence_count") or 0) + int(source.get("occurrence_count") or 0)
        target["leaf_occurrence_count"] = int(target.get("leaf_occurrence_count") or 0) + int(
            source.get("leaf_occurrence_count") or 0
        )
        target["max_depth"] = max(int(target.get("max_depth") or 0), int(source.get("max_depth") or 0))
        target["text_present"] = bool(target.get("text_present")) or bool(source.get("text_present"))
        target["last_seen"] = source.get("last_seen") or utc_now_iso()
        target["match_confidence"] = max(
            float(target.get("match_confidence") or 0.0),
            float(source.get("match_confidence") or 0.0),
        )
        target["match_reasons"] = self._merge_limited_unique_strings(
            target.get("match_reasons"),
            source.get("match_reasons"),
            limit=12,
        )
        target["schema_variant_detected"] = bool(target.get("schema_variant_detected")) or bool(
            source.get("schema_variant_detected")
        )
        target["schema_approved"] = bool(target.get("schema_approved")) or bool(source.get("schema_approved"))
        target["status"] = self._merge_status(target.get("status"), source.get("status"))

        for field_name in ("context_path_counts", "parent_tag_counts", "nearest_structural_parent_counts"):
            current_counts = dict(target.get(field_name) or {})
            for key, count in (source.get(field_name) or {}).items():
                current_counts[str(key)] = int(current_counts.get(str(key), 0)) + int(count)
            target[field_name] = current_counts

    def _merge_sorted_unique_strings(self, existing: Any, incoming: Any) -> list[str]:
        return sorted({str(item) for item in (existing or []) if item} | {str(item) for item in (incoming or []) if item})

    def _merge_limited_unique_strings(self, existing: Any, incoming: Any, *, limit: int) -> list[str]:
        merged: list[str] = []
        for item in list(existing or []) + list(incoming or []):
            normalized = str(item)
            if normalized and normalized not in merged:
                merged.append(normalized)
            if len(merged) >= limit:
                break
        return merged

    def _file_sets_are_subset(self, existing_files: Any, incoming_files: Any) -> bool:
        existing = {str(item) for item in (existing_files or []) if item}
        incoming = {str(item) for item in (incoming_files or []) if item}
        return bool(incoming) and incoming.issubset(existing)

    def _merge_status(self, left: Any, right: Any) -> str:
        priority = {"approved": 3, "variant": 2, "unknown": 1}
        normalized_left = str(left or "unknown").lower()
        normalized_right = str(right or "unknown").lower()
        return normalized_left if priority.get(normalized_left, 0) >= priority.get(normalized_right, 0) else normalized_right

    def _element_tag_name(self, element: ET.Element) -> str:
        return element.tag.split("}")[-1].lower()

    def _namespace_uri(self, tag: str) -> str:
        if tag.startswith("{") and "}" in tag:
            return tag[1:].split("}", 1)[0]
        return ""

    def _suggest_schema_family_id(self, fingerprint: dict[str, Any]) -> str:
        root_tag = str(fingerprint.get("root_tag") or "custom").replace("-", "_")
        return f"{root_tag}_family"

    def _suggest_schema_tag_id(self, fingerprint: dict[str, Any]) -> str:
        tag_name = str(fingerprint.get("tag_name") or "custom_tag").replace("-", "_")
        return tag_name

    def _nearest_structural_tag(self, path_segments: list[str]) -> str | None:
        structural_tags = {
            "ncc",
            "page",
            "part",
            "section",
            "subsection",
            "clause",
            "subclause",
            "schedule",
            "table-reference",
            "table",
            "image-reference",
        }
        for tag_name in reversed(path_segments):
            if tag_name in structural_tags:
                return tag_name
        return None

    def _match_tag_against_approved_registry(
        self,
        *,
        tag_fingerprint_hash: str,
        tag_name: str,
        approved_registry: dict[str, Any],
    ) -> dict[str, Any]:
        for tag in approved_registry.get("tags") or []:
            approved_hashes = {str(item) for item in (tag.get("approved_tag_fingerprint_hashes") or [])}
            tag_names = {str(item) for item in ((tag.get("match_rules") or {}).get("tag_names") or [])}
            exact_match = tag_fingerprint_hash in approved_hashes
            name_match = tag_name in tag_names or str(tag.get("tag_name") or "") == tag_name
            if exact_match or name_match:
                return {
                    "schema_tag_id": tag.get("schema_tag_id"),
                    "parser_profile": tag.get("parser_profile"),
                    "schema_match_confidence": 0.99 if exact_match else 0.7,
                    "schema_match_reasons": [
                        f"tag:{tag_name}",
                        f"exact_fingerprint_match:{exact_match}",
                        f"name_match:{name_match}",
                    ],
                    "schema_approved": exact_match,
                    "schema_variant_detected": name_match and not exact_match,
                    "status": "approved" if exact_match else "variant",
                }
        return {
            "schema_tag_id": None,
            "parser_profile": None,
            "schema_match_confidence": 0.0,
            "schema_match_reasons": [f"tag:{tag_name}", "no_approved_schema_tag_match"],
            "schema_approved": False,
            "schema_variant_detected": False,
            "status": "unknown",
        }
