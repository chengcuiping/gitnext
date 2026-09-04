#!/usr/bin/env python3
"""Strictly audit built GitNext wheel and source distributions."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

BANNED_NAMES = {"package.json", "package-lock.json", "tsconfig.json", "tsconfig.build.json"}
BANNED_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}
BANNED_PARTS = {".git", ".venv", "artifacts", "build", "dist", "node_modules", "tests", "tools"}


def safe_names(names: list[str], label: str) -> list[str]:
    errors: list[str] = []
    normalized: list[str] = []
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            errors.append(f"{label}: unsafe member path: {name}")
            continue
        if path.name in BANNED_NAMES or path.suffix.lower() in BANNED_SUFFIXES:
            errors.append(f"{label}: forbidden member: {name}")
        if BANNED_PARTS.intersection(path.parts):
            errors.append(f"{label}: forbidden member path: {name}")
        normalized.append(name)
    if errors:
        raise ValueError("\n".join(errors))
    return normalized


def audit_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = safe_names(archive.namelist(), path.name)
    roots = {PurePosixPath(name).parts[0] for name in names}
    unexpected = {root for root in roots if root != "gitnext" and not root.startswith("gitnext-0.1.0.dist-info")}
    if unexpected:
        raise ValueError(f"{path.name}: unexpected wheel roots: {sorted(unexpected)}")
    required = {"gitnext/__init__.py", "gitnext/py.typed"}
    missing = required - set(names)
    if missing:
        raise ValueError(f"{path.name}: missing wheel files: {sorted(missing)}")


def audit_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = safe_names([member.name for member in archive.getmembers() if member.isfile()], path.name)
    prefix = "gitnext-0.1.0/"
    if not names or any(not name.startswith(prefix) for name in names):
        raise ValueError(f"{path.name}: unexpected source distribution root")
    relative_names = {name.removeprefix(prefix) for name in names}
    required = {"LICENSE", "README.md", "pyproject.toml", "src/gitnext/__init__.py", "src/gitnext/py.typed"}
    missing = required - relative_names
    if missing:
        raise ValueError(f"{path.name}: missing source distribution files: {sorted(missing)}")
    allowed_roots = {"LICENSE", "MANIFEST.in", "PKG-INFO", "README.md", "pyproject.toml", "setup.cfg", "src"}
    unexpected = {PurePosixPath(name).parts[0] for name in relative_names} - allowed_roots
    if unexpected:
        raise ValueError(f"{path.name}: unexpected source distribution roots: {sorted(unexpected)}")


def main() -> int:
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"expected exactly one wheel and one sdist in {directory}")
        return 1
    try:
        audit_wheel(wheels[0])
        audit_sdist(sdists[0])
    except ValueError as error:
        print(error)
        return 1
    print(f"distribution audit passed: {wheels[0].name}, {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
