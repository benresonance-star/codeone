from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import requests


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_pdf() -> Path:
    return repo_root() / "Spec" / "NCC 2022" / "PDF" / "PDF Sections" / "NCC 2022 - Vol 1 - Part A1 - Interpreting the NCC.pdf"


def default_xml() -> Path:
    return repo_root() / "Spec" / "NCC 2022" / "XMLs" / "A1-interpreting-the-ncc.xml"


def reports_dir() -> Path:
    return repo_root() / "backend" / "reports" / "smoke"


def default_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return reports_dir() / f"smoke_{timestamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a live API smoke test against the NCC ingestion backend.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL.")
    parser.add_argument("--pdf", type=Path, default=default_pdf(), help="Path to the sample PDF.")
    parser.add_argument("--xml", type=Path, default=default_xml(), help="Path to the paired XML.")
    parser.add_argument("--extractor-strategy", default="docling", choices=["docling", "pdfplumber"])
    parser.add_argument("--document-class", default=None)
    parser.add_argument("--output", type=Path, default=default_output_path(), help="JSON output file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    health = requests.get(f"{args.base_url}/api/health", timeout=30)
    health.raise_for_status()

    with args.pdf.open("rb") as pdf_handle, args.xml.open("rb") as xml_handle:
        response = requests.post(
            f"{args.base_url}/api/ingestions/validate",
            params={
                "extractor_strategy": args.extractor_strategy,
                "document_class": args.document_class,
            },
            files={
                "pdf": (args.pdf.name, pdf_handle, "application/pdf"),
                "xml": (args.xml.name, xml_handle, "application/xml"),
            },
            timeout=300,
        )
    response.raise_for_status()
    payload = response.json()

    summary = {
        "health": health.json(),
        "extractor_strategy": payload["summary"]["document_strategy"].get("extractor_strategy"),
        "runtime_mode": payload["summary"]["document_strategy"].get("runtime_mode"),
        "pdf_status": payload["summary"]["pdf_status"],
        "can_progress": payload["summary"]["can_progress"],
        "aligned": payload["raw_metrics"]["pdf"].get("aligned"),
        "unresolved": payload["raw_metrics"]["pdf"].get("unresolved"),
        "parity_summary": payload["summary"].get("parity_summary", {}),
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"summary": summary, "payload": payload}, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
