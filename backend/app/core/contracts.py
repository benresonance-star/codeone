from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator


def project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "Spec").exists():
            return parent
    raise RuntimeError("Could not locate project root containing Spec directory.")


def spec_dir() -> Path:
    return project_root() / "Spec"


def load_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_contracts() -> dict[str, dict[str, Any]]:
    specs = spec_dir()
    return {
        "pdf_contract": load_json_file(specs / "pdf_ingestion_contract.json"),
        "xml_contract": load_json_file(specs / "xml_source_contract.json"),
        "pdf_result_schema": load_json_file(specs / "validation_result.schema.json"),
        "xml_result_schema": load_json_file(specs / "xml_validation_result.schema.json"),
    }


@lru_cache(maxsize=2)
def schema_validator(schema_name: str) -> Draft7Validator:
    contracts = load_contracts()
    schema = contracts[schema_name]
    return Draft7Validator(schema)


def validate_payload(schema_name: str, payload: dict[str, Any]) -> None:
    validator = schema_validator(schema_name)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if not errors:
        return

    messages = []
    for error in errors:
        path = ".".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{path}: {error.message}")
    raise ValueError("; ".join(messages))
