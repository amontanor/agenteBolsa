#!/usr/bin/env python3
"""Bloquea archivos activos con bytes nulos, UTF-8 invalido o sintaxis rota.

Usado por la CI remota y por el hook pre-commit. Recorre codigo, documentacion
activa y JSON de gobierno. Asi la proteccion cubre tambien la fuente unica de
verdad del proyecto, no solo Python.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ACTIVE_DOCUMENTS = (
    Path("README.md"),
    Path("docs/architecture.md"),
    Path("docs/operating_model.md"),
    Path("docs/plan_mejoras_y_tareas.md"),
    Path("docs/startup_runbook.md"),
    Path("docs/promotion_checklist.md"),
    Path("docs/estudio_semanal.md"),
    Path("docs/tutorial_arranque_diario.md"),
    Path("docs/versioning.md"),
    Path("docs/RELEVO_DIRECCION_TECNICA.md"),
)
SUPPORTED_SUFFIXES = {".py", ".md", ".json"}


def _iter_targets(args: list[str]) -> list[Path]:
    if args:
        return [Path(a) for a in args if Path(a).suffix.lower() in SUPPORTED_SUFFIXES]
    roots = [Path("src"), Path("tests"), Path("scripts")]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    files.extend(path for path in ACTIVE_DOCUMENTS if path.exists())
    config_dir = Path("data/config")
    if config_dir.exists():
        files.extend(config_dir.glob("*.json"))
    return sorted(set(files))


def main(argv: list[str]) -> int:
    errors: list[str] = []
    for path in _iter_targets(argv):
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(f"{path}: no se pudo leer ({exc})")
            continue
        if b"\x00" in data:
            errors.append(f"{path}: contiene bytes nulos")
            continue
        try:
            # PowerShell 5.1 escribe UTF-8 con BOM en varios JSON gobernados.
            # Es UTF-8 valido y debe normalizarse antes de parsear.
            text = data.decode("utf-8-sig")
            if path.suffix.lower() == ".py":
                ast.parse(text)
            elif path.suffix.lower() == ".json":
                json.loads(text)
        except (SyntaxError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: no parsea ({exc})")
    if errors:
        print("ARCHIVOS CORRUPTOS DETECTADOS (T5.8):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"check_no_nulls: OK ({len(_iter_targets(argv))} archivos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
