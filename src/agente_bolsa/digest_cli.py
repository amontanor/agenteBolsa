"""Shared read-only continuous-improvement digest command.

The normal CLI keeps its historical command and output contract.  The Docker
supervisor can invoke this module directly so a digest process does not import
the full ``agente_bolsa.main`` scheduler, broker, and resident-lab graph.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))


def _close_read_connection(store: Any) -> None:
    close_read_connection = getattr(store, "close_read_connection", None)
    if callable(close_read_connection):
        close_read_connection()


def execute_digest_command(
    args: argparse.Namespace,
    *,
    settings: Any,
    store: Any,
    build_digest: Callable[..., dict[str, Any]] | None = None,
    format_digest: Callable[[dict[str, Any]], str] | None = None,
    safety_summary: Callable[[Any], dict[str, Any] | None] | None = None,
    emit_json: Callable[[dict[str, Any]], None] = _print_json,
    close_store: bool = True,
) -> None:
    """Execute existing digest business logic against an already-open Store.

    ``build_digest`` and related arguments exist only for focused contract
    tests.  Production callers use the existing implementation imported lazily
    below; no alternate digest calculation is introduced.
    """

    try:
        if build_digest is None or format_digest is None or safety_summary is None:
            from .continuous_improvement.digest import build_lab_digest, format_lab_digest_text
            from .tools.config_audit import digest_safety_summary

            build_digest = build_digest or build_lab_digest
            format_digest = format_digest or format_lab_digest_text
            safety_summary = safety_summary or digest_safety_summary

        digest = build_digest(
            store,
            days=args.days,
            safety=safety_summary(settings),
        )
        if args.out:
            target = Path(args.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(format_digest(digest), encoding="utf-8")
            result = {"ok": True, "path": str(target), "digest": digest}
            if args.json:
                emit_json(result)
            else:
                print(f"Digest escrito: {result['path']}")
            return
        if args.json:
            emit_json({"ok": True, "digest": digest})
        else:
            print(format_digest(digest))
    finally:
        if close_store:
            _close_read_connection(store)


def run_digest_command(args: argparse.Namespace) -> None:
    """Run digest command from a lightweight module entrypoint."""

    from .config import get_settings
    from .logging_utils import configure_logging
    from .storage import Store

    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    store = Store(settings.database_path, settings.agent_logs_dir)
    try:
        store.ensure_schema()
        execute_digest_command(args, settings=settings, store=store, close_store=False)
    finally:
        _close_read_connection(store)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only continuous-improvement digest.")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--out", help="Ruta markdown opcional para escribir el digest.")
    parser.add_argument("--json", action="store_true", help="Devuelve JSON.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_digest_command(args)


if __name__ == "__main__":
    main()
