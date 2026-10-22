"""Prepare release image binding artifacts without touching Docker or systemd.

Usage example::

    python scripts/prepare_release_binding.py \
        --version 0.4.376 \
        --image-id sha256:<64-hex> \
        --inspect-json image-inspect.json \
        --rollback-image-id sha256:<64-hex> \
        --rollback-inspect-json rollback-image-inspect.json \
        --output-dir release-binding-0.4.376

The inspect payload must come from ``docker image inspect`` collected by an
operator or an offline QA fixture.  This command never invokes Docker,
systemd, SSH, Compose, or a network client.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Keep direct checkout invocation independent from an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agente_bolsa.release_binding import (  # noqa: E402
    ReleaseBindingError,
    load_inspect_json,
    prepare_release_binding,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="release SemVer, for example 0.4.376")
    parser.add_argument("--image-id", required=True, help="exact Docker ImageID sha256 digest")
    parser.add_argument(
        "--inspect-json",
        required=True,
        help="path to docker image inspect JSON, or '-' for stdin",
    )
    parser.add_argument(
        "--rollback-image-id",
        required=True,
        help="exact approved 0.4.369 Docker ImageID sha256 digest",
    )
    parser.add_argument(
        "--rollback-inspect-json",
        required=True,
        help="docker image inspect JSON for approved 0.4.369 image, or '-' for stdin",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--release-dir",
        default=None,
        help="absolute target release directory; default /opt/agente-bolsa/releases/<version>",
    )
    parser.add_argument("--env-file", default="/etc/agente-bolsa/runtime.env")
    parser.add_argument("--rollback-version", default="0.4.369")
    parser.add_argument("--json", action="store_true", help="print manifest JSON")
    return parser


def _read_inspect(path: str) -> Any:
    if path == "-":
        return load_inspect_json(sys.stdin.read())
    try:
        return load_inspect_json(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReleaseBindingError("missing_image_identity", f"cannot read inspect JSON: {path}") from exc


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ReleaseBindingError("output_exists", f"refusing to overwrite {path}") from exc


def _write_plan(output_dir: Path, plan: Any) -> None:
    # Validate identity and all text before this point. Writes are local audit
    # artifacts only; no production path is ever opened by this helper.
    destinations = (
        (output_dir / plan.override_filename, plan.override_compose),
        (
            output_dir / "systemd" / "agente-bolsa.service.d" / "10-release-binding.conf",
            plan.systemd_dropin,
        ),
        (output_dir / "rollback" / plan.override_filename, plan.rollback_override_compose),
        (
            output_dir / "rollback" / "systemd" / "agente-bolsa.service.d" / "10-release-binding.conf",
            plan.rollback_systemd_dropin,
        ),
        (
            output_dir / "verify_release_binding.py",
            (Path(__file__).with_name("verify_release_binding.py")).read_text(encoding="utf-8"),
        ),
        (
            output_dir / "rollback" / "verify_release_binding.py",
            (Path(__file__).with_name("verify_release_binding.py")).read_text(encoding="utf-8"),
        ),
    )
    manifest_path = output_dir / "release-binding.json"
    import json

    destinations += ((manifest_path, json.dumps(plan.manifest(), indent=2, sort_keys=True) + "\n"),)
    existing = next((path for path, _ in destinations if path.exists()), None)
    if existing is not None:
        raise ReleaseBindingError("output_exists", f"refusing to overwrite {existing}")
    for path, content in destinations:
        _write_new(path, content)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inspect_payload = _read_inspect(args.inspect_json)
        plan = prepare_release_binding(
            version=args.version,
            image_id=args.image_id,
            inspect_payload=inspect_payload,
            rollback_image_id=args.rollback_image_id,
            rollback_inspect_payload=_read_inspect(args.rollback_inspect_json),
            release_dir=args.release_dir,
            env_file=args.env_file,
            rollback_version=args.rollback_version,
        )
        _write_plan(args.output_dir, plan)
    except (OSError, ReleaseBindingError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        import json

        print(json.dumps(plan.manifest(), indent=2, sort_keys=True))
    else:
        print(f"prepared release binding {plan.version}: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
