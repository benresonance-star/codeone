from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "backend").exists() and (parent / "frontend").exists():
            return parent
    raise RuntimeError("Could not locate project root.")


ROOT = project_root()
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
NPM = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
DOCKER = shutil.which("docker.exe") or shutil.which("docker") or "docker"

CommandSpec = tuple[Path, list[str], dict[str, str] | None]

LAYER_COMMANDS: dict[str, list[CommandSpec]] = {
    "static": [
        (BACKEND, [sys.executable, "-m", "unittest", "tests.test_xml_schema_registry"], None),
        (FRONTEND, [NPM, "run", "typecheck"], None),
    ],
    "backend": [
        (
            BACKEND,
            [sys.executable, "-m", "unittest", "tests.test_document_strategy", "tests.test_contract_conformance"],
            None,
        ),
    ],
    "payload": [
        (BACKEND, [sys.executable, "-m", "unittest", "tests.test_retention"], None),
    ],
    "frontend": [
        (FRONTEND, [NPM, "run", "lint"], None),
        (FRONTEND, [NPM, "run", "test"], None),
        (FRONTEND, [NPM, "run", "build"], None),
    ],
    "smoke": [
        (BACKEND, [sys.executable, "-m", "unittest", "tests.test_corpus_smoke"], None),
    ],
    "backend_image_light": [
        (
            ROOT,
            [
                DOCKER,
                "build",
                "-f",
                "backend/Dockerfile",
                "--build-arg",
                "BACKEND_REQUIREMENTS_FILE=requirements.txt",
                ".",
            ],
            None,
        ),
    ],
    "backend_image_full": [
        (
            ROOT,
            [
                DOCKER,
                "build",
                "-f",
                "backend/Dockerfile",
                "--build-arg",
                "BACKEND_REQUIREMENTS_FILE=requirements-docling.txt",
                ".",
            ],
            None,
        ),
    ],
}

ALL_LAYERS = ["static", "backend", "payload", "frontend", "smoke"]
OPTIONAL_LAYERS = ["backend_image_light", "backend_image_full"]


def run_layer(layer: str) -> None:
    print(f"\n== {layer} ==")
    for working_directory, command, extra_env in LAYER_COMMANDS[layer]:
        print(f"$ {' '.join(command)}")
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        subprocess.run(command, cwd=working_directory, check=True, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the layered ingestion test protocol.")
    parser.add_argument(
        "--layer",
        choices=[*ALL_LAYERS, *OPTIONAL_LAYERS, "all"],
        default="all",
        help="Run a single protocol layer or the default fast protocol.",
    )
    args = parser.parse_args()

    layers = ALL_LAYERS if args.layer == "all" else [args.layer]
    for layer in layers:
        run_layer(layer)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
