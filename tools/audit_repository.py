#!/usr/bin/env python3
"""Fail when the repository is not a clean standalone Python project."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    ".github/workflows/python-ci.yml",
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "contracts/v1/golden-corpus/manifest.json",
    "docs/provenance.md",
    "pyproject.toml",
    "src/gitnext/py.typed",
}
ALLOWED_ROOT_FILES = {
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
}
ALLOWED_ROOT_DIRECTORIES = {".github", "contracts", "docs", "src", "tests", "tools"}
BANNED_NAMES = {
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "tsconfig.build.json",
    "eslint.config.js",
}
BANNED_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}
BANNED_PARTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "artifacts",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
}
COMMAND_SCOPE = {".github", "src", "tests"}
COMMAND_PATTERN = re.compile(r"(?im)(?:^\s*(?:-\s+run:\s*)?|[\[(,]\s*[\"'])(?:no" r"de|npm|npx)(?:\s|[\"'])")
WORKSPACE_PREFIX = b"/mnt/" + b"si0260014qra"


def repository_files() -> list[Path]:
    return sorted(path for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.relative_to(ROOT).parts)


def dependency_name(specification: str) -> str:
    match = re.match(r"[A-Za-z0-9_.-]+", specification)
    if match is None:
        raise ValueError(f"Invalid dependency: {specification}")
    return match.group(0).lower().replace("_", "-")


def project_dependencies(path: Path) -> list[str]:
    payload = path.read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*$\n(?P<body>.*?)(?=^\[|\Z)", payload)
    if project is None:
        raise ValueError("pyproject.toml has no [project] section")
    dependencies = re.search(r"(?ms)^dependencies\s*=\s*\[(?P<body>.*?)^\]", project.group("body"))
    if dependencies is None:
        raise ValueError("pyproject.toml has no project dependencies")
    specifications = re.findall(r'^\s*"([^"\n]+)"\s*,?\s*$', dependencies.group("body"), flags=re.MULTILINE)
    if not specifications:
        raise ValueError("pyproject.toml project dependencies are empty or malformed")
    return specifications


def main() -> int:
    violations: list[str] = []
    files = repository_files()
    relative_files = {path.relative_to(ROOT).as_posix() for path in files}

    for missing in sorted(REQUIRED - relative_files):
        violations.append(f"missing required file: {missing}")

    for path in files:
        relative = path.relative_to(ROOT)
        display = relative.as_posix()
        if len(relative.parts) == 1:
            if display not in ALLOWED_ROOT_FILES:
                violations.append(f"unexpected root file: {display}")
        elif relative.parts[0] not in ALLOWED_ROOT_DIRECTORIES:
            violations.append(f"unexpected root directory: {relative.parts[0]}")
        if path.name in BANNED_NAMES or path.suffix.lower() in BANNED_SUFFIXES:
            violations.append(f"forbidden non-Python project file: {display}")
        if BANNED_PARTS.intersection(relative.parts):
            violations.append(f"generated or forbidden path: {display}")
        payload = path.read_bytes()
        if WORKSPACE_PREFIX in payload:
            violations.append(f"workspace path embedded in: {display}")
        if relative.parts[0] in COMMAND_SCOPE and COMMAND_PATTERN.search(payload.decode("utf-8", errors="ignore")):
            violations.append(f"non-Python tool invocation in: {display}")

    dependencies = {dependency_name(item) for item in project_dependencies(ROOT / "pyproject.toml")}
    if dependencies != {"httpx", "pydantic"}:
        violations.append(f"runtime dependencies must be exactly httpx and pydantic, got: {sorted(dependencies)}")

    if violations:
        for violation in violations:
            print(violation)
        return 1
    print(f"repository audit passed: {len(files)} files, Python-only runtime")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
