#!/usr/bin/env python3
"""Bloquea archivos con bytes nulos o .py no parseables (T5.8).

Usado por la CI remota y por el hook pre-commit. Recorre src/ y tests/ (o los
archivos pasados como argumentos) y falla si encuentra un byte nulo o un .py que
no compila con ast.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _iter_targets(args: list[str]) -> list[Path]:
    if args:
        return [Path(a) for a in args if a.endswith(".py")]
    roots = [Path("src"), Path("tests"), Path("scripts")]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


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
            ast.parse(data.decode("utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
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
