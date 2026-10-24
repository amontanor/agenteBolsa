"""Record an active release after the deployment runbook verifies service health."""

from __future__ import annotations

import argparse
import json

from agente_bolsa import __version__
from agente_bolsa.config import get_settings
from agente_bolsa.deployment_receipt import append_verified_deployment_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True, help="Full sha256 Docker image ID from the live container")
    parser.add_argument("--source-head", required=True, help="Full Git HEAD verified for this release")
    parser.add_argument("--source-tree", required=True, help="Full Git tree verified for this release")
    args = parser.parse_args()

    settings = get_settings()
    receipt = append_verified_deployment_receipt(
        settings.data_dir,
        current_version=__version__,
        image_id=args.image_id,
        source_head=args.source_head,
        source_tree=args.source_tree,
    )
    print(json.dumps({"status": "recorded", **receipt}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
