"""Offline contract tests for release image binding preparation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agente_bolsa.release_binding import (
    ImageIdentityError,
    ReleaseBindingError,
    image_tag,
    prepare_release_binding,
    render_override_compose,
    render_systemd_dropin,
    validate_image_identity,
)

IMAGE_ID = "sha256:" + "a" * 64
IMAGE_REF = "agente-bolsa:0.4.376-arm64"


def _inspect(**overrides):
    record = {
        "Id": IMAGE_ID,
        "RepoTags": [IMAGE_REF],
        "RepoDigests": ["agente-bolsa@sha256:" + "b" * 64],
        "Architecture": "arm64",
        "Os": "linux",
        "Config": {"Labels": {"org.opencontainers.image.version": "0.4.376"}},
    }
    record.update(overrides)
    return [record]


def test_exact_image_identity_keeps_registry_digest_separate():
    identity = validate_image_identity(
        _inspect(), image_ref=IMAGE_REF, expected_image_id=IMAGE_ID, version="0.4.376"
    )

    assert identity.image_id == IMAGE_ID
    assert identity.repo_digests == ("agente-bolsa@sha256:" + "b" * 64,)
    assert identity.as_dict()["image_id"] != identity.as_dict()["registry_repo_digests"][0]


@pytest.mark.parametrize(
    ("record", "code"),
    [
        ({"RepoTags": [IMAGE_REF], "Architecture": "arm64", "Os": "linux"}, "missing_image_id"),
        ({"Id": IMAGE_ID, "RepoTags": ["agente-bolsa:0.4.321-arm64"], "Architecture": "arm64", "Os": "linux"}, "image_tag_missing"),
        ({"Id": "sha256:" + "c" * 64, "RepoTags": [IMAGE_REF], "Architecture": "arm64", "Os": "linux"}, "stale_image"),
        ({"Id": IMAGE_ID, "RepoTags": [IMAGE_REF], "Architecture": "amd64", "Os": "linux"}, "wrong_architecture"),
        ({"Id": IMAGE_ID, "RepoTags": [IMAGE_REF], "Architecture": "arm64", "Os": "windows"}, "wrong_os"),
    ],
)
def test_identity_gate_rejects_missing_stale_or_wrong_image(record, code):
    with pytest.raises(ImageIdentityError, match=code):
        validate_image_identity(
            [record], image_ref=IMAGE_REF, expected_image_id=IMAGE_ID, version="0.4.376"
        )


@pytest.mark.parametrize(
    "value",
    [
        "0.4.376;rm -rf /",
        "0.4.376\nExecStart=/bin/sh",
        "0.4.376@sha256:" + "a" * 64,
    ],
)
def test_release_and_image_injection_rejected(value):
    with pytest.raises(ReleaseBindingError):
        image_tag(value)
    with pytest.raises(ReleaseBindingError):
        render_override_compose("agente-bolsa:" + value + "-arm64")


def test_rendered_override_binds_all_started_services_to_exact_tag():
    compose = render_override_compose(IMAGE_REF)

    assert compose.count(f"image: {IMAGE_REF}") == 3
    for service in ("scheduler", "web", "auxiliary"):
        assert f"  {service}:\n    image: {IMAGE_REF}" in compose
    assert "${AGENTE_BOLSA_IMAGE}" in compose


def test_systemd_dropin_has_explicit_files_and_no_deps_up():
    dropin = render_systemd_dropin(
        image_ref=IMAGE_REF,
        release_dir="/opt/agente-bolsa/releases/0.4.376",
    )

    assert "ExecStart=" in dropin
    assert "--project-directory /opt/agente-bolsa/releases/0.4.376/deploy" in dropin
    assert "-f /opt/agente-bolsa/releases/0.4.376/deploy/docker-compose.yml" in dropin
    assert "-f /opt/agente-bolsa/releases/0.4.376/deploy/docker-compose.raspberry.override.yml" in dropin
    assert "up -d --no-deps scheduler web auxiliary" in dropin
    assert "stop scheduler web auxiliary" in dropin
    assert "AGENTE_BOLSA_IMAGE=" not in dropin


def test_preparation_generates_final_and_approved_rollback_without_runtime_effects(tmp_path: Path):
    plan = prepare_release_binding(
        version="0.4.376",
        image_id=IMAGE_ID,
        inspect_payload=_inspect(),
    )

    assert plan.image_ref == IMAGE_REF
    assert "agente-bolsa:0.4.376-arm64" in plan.override_compose
    assert "agente-bolsa:0.4.369-arm64" in plan.rollback_override_compose
    manifest = plan.manifest()
    assert manifest["rollback"]["release_version"] == "0.4.369"
    assert manifest["rollback"]["verification_required"] is True
    assert manifest["preparation_effects"] == {
        "docker": False,
        "systemd": False,
        "services_mutated": False,
        "env_modified": False,
        "kernel_resigned": False,
    }
    assert list(tmp_path.iterdir()) == []


def test_unapproved_or_injected_rollback_rejected():
    with pytest.raises(ReleaseBindingError, match="rollback_reference_not_approved"):
        prepare_release_binding(
            version="0.4.376",
            image_id=IMAGE_ID,
            inspect_payload=_inspect(),
            rollback_version="0.4.321",
        )


def test_cli_fixture_shape_is_json_serializable():
    plan = prepare_release_binding(
        version="0.4.376",
        image_id=IMAGE_ID,
        inspect_payload=_inspect(),
    )
    assert json.loads(json.dumps(plan.manifest()))["image_id"] == IMAGE_ID
