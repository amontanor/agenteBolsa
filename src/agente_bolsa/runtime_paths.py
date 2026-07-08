"""Helpers for managed runtime paths inside the repo workspace."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def managed_python_path(root: Path | None = None) -> Path:
    base = root or repo_root()
    if os.name == "nt":
        return base / ".venv" / "Scripts" / "python.exe"
    return base / ".venv" / "bin" / "python"


def require_managed_python(root: Path | None = None) -> Path:
    python_path = managed_python_path(root)
    if not python_path.exists():
        raise FileNotFoundError(f"No existe el interprete gestionado del proyecto: {python_path}")
    return python_path
