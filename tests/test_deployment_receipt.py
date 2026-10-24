from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agente_bolsa.deployment_receipt import (
    RECEIPT_FILENAME,
    append_verified_deployment_receipt,
    format_verified_deployment_time,
    latest_verified_deployment_receipt,
)

IMAGE_ID = "sha256:" + "a" * 64
GIT_HEAD = "1" * 40
GIT_TREE = "2" * 40
VERSION = "0.4.377"


def test_append_and_read_verified_deployment_receipt_uses_one_instant(tmp_path):
    receipt = append_verified_deployment_receipt(
        tmp_path,
        current_version=VERSION,
        image_id=IMAGE_ID,
        source_head=GIT_HEAD,
        source_tree=GIT_TREE,
        verified_at=datetime(2026, 10, 24, 9, 30, 5, tzinfo=timezone.utc),
    )

    assert receipt["verified_at_utc"] == "2026-10-24T09:30:05Z"
    assert receipt["verified_at_local"] == "2026-10-24T11:30:05+02:00"
    assert receipt["image_id"] == IMAGE_ID
    assert latest_verified_deployment_receipt(tmp_path, current_version=VERSION) == receipt
    assert format_verified_deployment_time(receipt) == (
        "Despliegue verificado: 2026-10-24 11:30:05 Europe/Madrid · 2026-10-24 09:30:05 UTC"
    )


def test_missing_receipt_renders_unavailable(tmp_path):
    assert latest_verified_deployment_receipt(tmp_path, current_version=VERSION) is None
    assert format_verified_deployment_time(None) == "Fecha de despliegue no disponible"


def test_latest_receipt_must_match_active_version(tmp_path):
    append_verified_deployment_receipt(
        tmp_path,
        current_version="0.4.376",
        image_id=IMAGE_ID,
        source_head=GIT_HEAD,
        source_tree=GIT_TREE,
        verified_at=datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc),
    )

    assert latest_verified_deployment_receipt(tmp_path, current_version=VERSION) is None


def test_invalid_latest_line_does_not_fall_back_to_old_receipt(tmp_path):
    path = tmp_path / RECEIPT_FILENAME
    valid = append_verified_deployment_receipt(
        tmp_path,
        current_version=VERSION,
        image_id=IMAGE_ID,
        source_head=GIT_HEAD,
        source_tree=GIT_TREE,
        verified_at=datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc),
    )
    path.write_text(json.dumps(valid) + "\nnot-a-receipt\n", encoding="utf-8")

    assert latest_verified_deployment_receipt(tmp_path, current_version=VERSION) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image_id", "sha256:short"),
        ("source_head", "not-a-git-object"),
        ("source_tree", "not-a-git-object"),
    ],
)
def test_receipt_writer_rejects_incomplete_identity(tmp_path, field, value):
    identity = {
        "image_id": IMAGE_ID,
        "source_head": GIT_HEAD,
        "source_tree": GIT_TREE,
    }
    identity[field] = value

    with pytest.raises(ValueError):
        append_verified_deployment_receipt(
            tmp_path,
            current_version=VERSION,
            verified_at=datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc),
            **identity,
        )


def test_receipt_writer_rejects_naive_timestamp(tmp_path):
    with pytest.raises(ValueError, match="must include a timezone"):
        append_verified_deployment_receipt(
            tmp_path,
            current_version=VERSION,
            image_id=IMAGE_ID,
            source_head=GIT_HEAD,
            source_tree=GIT_TREE,
            verified_at=datetime(2026, 10, 24, 9, 30),
        )
