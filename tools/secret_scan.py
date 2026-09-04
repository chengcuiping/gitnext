#!/usr/bin/env python3
"""Scan repository source files for credentials and local-path leakage."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "__pycache__",
}
FORBIDDEN_FILENAMES = {".env", "id_dsa", "id_ecdsa", "id_ed25519", "id_rsa"}
PATTERNS = {
    "GitHub token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "AWS access key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "workspace path": re.compile(rb"/mnt/" + rb"si0260014qra"),
}


def main() -> int:
    findings: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if IGNORED_PARTS.intersection(relative.parts):
            continue
        if path.name in FORBIDDEN_FILENAMES or path.suffix.lower() in {".key", ".p12", ".pfx", ".pem"}:
            findings.append(f"forbidden credential file: {relative.as_posix()}")
            continue
        payload = path.read_bytes()
        for label, pattern in PATTERNS.items():
            if pattern.search(payload):
                findings.append(f"{label} pattern: {relative.as_posix()}")
    if findings:
        for finding in findings:
            print(finding)
        return 1
    print("secret scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
