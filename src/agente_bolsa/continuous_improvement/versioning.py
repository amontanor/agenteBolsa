"""Deterministic version bump helpers for review-only code changes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

VERSION_FILE = "src/agente_bolsa/__init__.py"
VERSION_RE = re.compile(r'(__version__\s*=\s*")(\d+)\.(\d+)\.(\d+)(")')
PRODUCT_CHANGE_PREFIXES = ("src/agente_bolsa/", "tests/")
PRODUCT_CHANGE_FILES = {"pyproject.toml"}


def requires_version_bump(target_paths: list[str]) -> bool:
    normalized = [_normalize_path(path) for path in target_paths]
    return any(
        path == VERSION_FILE or path in PRODUCT_CHANGE_FILES or path.startswith(PRODUCT_CHANGE_PREFIXES)
        for path in normalized
    )


def bump_version_in_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    bumped = bump_version_text(text)
    if bumped["changed"]:
        path.write_text(str(bumped["text"]), encoding="utf-8")
    return bumped


def bump_version_text(text: str) -> dict[str, Any]:
    match = VERSION_RE.search(text)
    if match is None:
        raise ValueError(f"No se encontro __version__ en {VERSION_FILE}.")
    major, minor, patch = (int(match.group(2)), int(match.group(3)), int(match.group(4)))
    old_version = f"{major}.{minor}.{patch}"
    new_version = f"{major}.{minor}.{patch + 1}"
    new_text = VERSION_RE.sub(rf'\g<1>{major}.{minor}.{patch + 1}\g<5>', text, count=1)
    return {
        "changed": new_text != text,
        "old_version": old_version,
        "new_version": new_version,
        "text": new_text,
    }


def strip_version_file_from_file_edits(file_edits: Any) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(file_edits, list):
        return [], False
    kept: list[dict[str, Any]] = []
    touched = False
    for item in file_edits:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        path = _normalize_path(str(item.get("path") or ""))
        if path == VERSION_FILE:
            touched = True
            continue
        kept.append(item)
    return kept, touched


def strip_version_file_from_diff(diff_text: str) -> tuple[str, bool]:
    if not str(diff_text or "").strip():
        return "", False
    lines = diff_text.splitlines()
    sections: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git "):
            if current:
                sections.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        sections.append(current)
    kept: list[str] = []
    touched = False
    for section in sections:
        header = section[0]
        match = re.match(r"diff --git a/(.+?) b/(.+)$", header)
        if match:
            left = _normalize_path(match.group(1))
            right = _normalize_path(match.group(2))
            if left == VERSION_FILE or right == VERSION_FILE:
                touched = True
                continue
        kept.extend(section)
    return ("\n".join(kept) + ("\n" if kept else "")), touched


def version_file_in_diff(diff_text: str) -> bool:
    _, touched = strip_version_file_from_diff(diff_text)
    return touched


def _normalize_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("/")
