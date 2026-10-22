#!/usr/bin/env python3
"""Verify one Docker image binding before systemd starts Compose.

Host-only standard-library verifier. It calls ``docker image inspect`` with an
argument list and bounded timeout. It never runs or starts an image.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REF_RE = re.compile(r"^agente-bolsa:[0-9]+\.[0-9]+\.[0-9]+-arm64$")


def _record(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return payload[0]
    if isinstance(payload, dict):
        return payload
    raise ValueError("docker inspect must return one image")


def verify(
    *,
    image_ref: str,
    expected_image_id: str,
    docker_bin: str = "/usr/bin/docker",
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Inspect and verify exact tag, ImageID, and linux/arm64 platform."""

    if IMAGE_REF_RE.fullmatch(image_ref) is None:
        raise ValueError("malformed image reference")
    if IMAGE_ID_RE.fullmatch(expected_image_id) is None:
        raise ValueError("malformed expected ImageID")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    completed = subprocess.run(
        [docker_bin, "image", "inspect", image_ref],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise ValueError(f"docker image inspect failed with rc={completed.returncode}")
    try:
        record = _record(json.loads(completed.stdout))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("docker image inspect returned malformed JSON") from exc
    actual_id = record.get("Id")
    if actual_id != expected_image_id:
        raise ValueError("stale image: ImageID mismatch")
    repo_tags = record.get("RepoTags")
    if not isinstance(repo_tags, list) or image_ref not in repo_tags:
        raise ValueError("image tag missing from inspected image")
    if record.get("Architecture") != "arm64" or record.get("Os") != "linux":
        raise ValueError("image platform must be linux/arm64")
    return {
        "image_ref": image_ref,
        "image_id": actual_id,
        "architecture": record["Architecture"],
        "os": record["Os"],
        "registry_repo_digests": record.get("RepoDigests", []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--docker-bin", default="/usr/bin/docker")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)
    try:
        result = verify(
            image_ref=args.image_ref,
            expected_image_id=args.expected_image_id,
            docker_bin=args.docker_bin,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"release binding verification failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
