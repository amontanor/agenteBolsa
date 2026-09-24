"""Helpers for managed runtime paths inside the repo workspace."""

from __future__ import annotations

import os
import sys
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
    if python_path.exists():
        return python_path
    container_mode = os.getenv("AGENTE_BOLSA_CONTAINER", "").strip().lower()
    if container_mode in {"1", "true", "yes"}:
        return Path(sys.executable)
    raise FileNotFoundError(f"No existe el interprete gestionado del proyecto: {python_path}")
