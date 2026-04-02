from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_pdf() -> Path:
    return repo_root() / "Spec" / "NCC 2022" / "PDF" / "PDF Sections" / "NCC 2022 - Vol 1 - Part A1 - Interpreting the NCC.pdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Docling runtime modes against a sample PDF.")
    parser.add_argument("--pdf", type=Path, default=default_pdf(), help="Path to the sample PDF.")
    parser.add_argument(
        "--modes",
        nargs="*",
        default=["text", "ocr", "tables", "full"],
        choices=["text", "ocr", "tables", "full"],
        help="Runtime modes to probe.",
    )
    return parser.parse_args()


def mode_env(mode: str) -> dict[str, str]:
    mapping = {
        "text": {
            "DOCLING_ENABLE_OCR": "false",
            "DOCLING_ENABLE_TABLE_STRUCTURE": "false",
            "DOCLING_FORCE_BACKEND_TEXT": "true",
        },
        "ocr": {
            "DOCLING_ENABLE_OCR": "true",
            "DOCLING_ENABLE_TABLE_STRUCTURE": "false",
            "DOCLING_FORCE_BACKEND_TEXT": "true",
        },
        "tables": {
            "DOCLING_ENABLE_OCR": "false",
            "DOCLING_ENABLE_TABLE_STRUCTURE": "true",
            "DOCLING_FORCE_BACKEND_TEXT": "true",
        },
        "full": {
            "DOCLING_ENABLE_OCR": "true",
            "DOCLING_ENABLE_TABLE_STRUCTURE": "true",
            "DOCLING_FORCE_BACKEND_TEXT": "true",
        },
    }
    return mapping[mode]


def run_mode(pdf_path: Path, mode: str) -> dict[str, object]:
    env = os.environ.copy()
    env.update(mode_env(mode))
    command = [
        sys.executable,
        "-c",
        (
            "from app.services.document_strategy import DocumentStrategyRouter;"
            "from app.services.extractors.docling_stub import DoclingExtractor;"
            f"pdf_path=r'''{pdf_path}''';"
            "decision=DocumentStrategyRouter().route("
            "pdf_name='probe.pdf', xml_name='probe.xml', requested_extractor_strategy='docling');"
            "extractor=DoclingExtractor();"
            "result=extractor.extract(open(pdf_path,'rb').read(), decision=decision);"
            "import json;"
            "print(json.dumps({"
            "'runtime_mode': result.runtime_mode,"
            "'blocks': len(result.blocks),"
            "'tables': len(result.tables),"
            "'notes': result.notes"
            "}))"
        ),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    payload = {
        "mode": mode,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
    return payload


def main() -> int:
    args = parse_args()
    results = [run_mode(args.pdf, mode) for mode in args.modes]
    print(json.dumps({"pdf": str(args.pdf), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
