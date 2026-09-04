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
DIST_NAME = "gitnext"
VERSION = "0.1.0"
DIST_INFO = f"{DIST_NAME}-{VERSION}.dist-info"
EGG_INFO = f"src/{DIST_NAME}.egg-info"
WHEEL_METADATA = {
    f"{DIST_INFO}/METADATA",
    f"{DIST_INFO}/RECORD",
    f"{DIST_INFO}/WHEEL",
    f"{DIST_INFO}/entry_points.txt",
    f"{DIST_INFO}/licenses/LICENSE",
    f"{DIST_INFO}/top_level.txt",
}
SDIST_METADATA = {
    f"{EGG_INFO}/PKG-INFO",
    f"{EGG_INFO}/SOURCES.txt",
    f"{EGG_INFO}/dependency_links.txt",
    f"{EGG_INFO}/entry_points.txt",
    f"{EGG_INFO}/requires.txt",
    f"{EGG_INFO}/top_level.txt",
}
SDIST_ROOT_FILES = {"LICENSE", "MANIFEST.in", "PKG-INFO", "README.md", "pyproject.toml", "setup.cfg"}


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
    expected_name = f"{DIST_NAME}-{VERSION}-py3-none-any.whl"
    if path.name != expected_name:
        raise ValueError(f"unexpected wheel filename or compatibility tag: {path.name}")
    required = {f"{DIST_NAME}/__init__.py", f"{DIST_NAME}/py.typed"} | WHEEL_METADATA
    with zipfile.ZipFile(path) as archive:
        names = safe_names(archive.namelist(), path.name)
        missing = required - set(names)
        if missing:
            raise ValueError(f"{path.name}: missing wheel files: {sorted(missing)}")
        wheel_metadata = archive.read(f"{DIST_INFO}/WHEEL").decode("utf-8")
    unexpected: set[str] = set()
    for name in names:
        member = PurePosixPath(name)
        if member.parts[0] == DIST_NAME:
            if member.name != "py.typed" and member.suffix != ".py":
                unexpected.add(name)
        elif name not in WHEEL_METADATA:
            unexpected.add(name)
    if unexpected:
        raise ValueError(f"{path.name}: unexpected non-Python or non-metadata files: {sorted(unexpected)}")
    if "Root-Is-Purelib: true" not in wheel_metadata or "Tag: py3-none-any" not in wheel_metadata:
        raise ValueError(f"{path.name}: WHEEL metadata does not describe a py3-none-any pure-Python wheel")


def audit_sdist(path: Path) -> None:
    expected_name = f"{DIST_NAME}-{VERSION}.tar.gz"
    if path.name != expected_name:
        raise ValueError(f"unexpected source distribution filename: {path.name}")
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        unsupported = [member.name for member in members if not member.isfile() and not member.isdir()]
        if unsupported:
            raise ValueError(f"{path.name}: links or special files are not allowed: {sorted(unsupported)}")
        names = safe_names([member.name for member in members if member.isfile()], path.name)
    prefix = f"{DIST_NAME}-{VERSION}/"
    if not names or any(not name.startswith(prefix) for name in names):
        raise ValueError(f"{path.name}: unexpected source distribution root")
    relative_names = {name.removeprefix(prefix) for name in names}
    required = {
        "LICENSE",
        "PKG-INFO",
        "README.md",
        "pyproject.toml",
        f"src/{DIST_NAME}/__init__.py",
        f"src/{DIST_NAME}/py.typed",
    } | SDIST_METADATA
    missing = required - relative_names
    if missing:
        raise ValueError(f"{path.name}: missing source distribution files: {sorted(missing)}")
    unexpected: set[str] = set()
    package_prefix = f"src/{DIST_NAME}/"
    for name in relative_names:
        member = PurePosixPath(name)
        if name in SDIST_ROOT_FILES or name in SDIST_METADATA:
            continue
        if name.startswith(package_prefix) and (member.name == "py.typed" or member.suffix == ".py"):
            continue
        unexpected.add(name)
    if unexpected:
        raise ValueError(f"{path.name}: unexpected non-Python or non-metadata files: {sorted(unexpected)}")


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
