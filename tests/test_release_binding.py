"""Offline contract tests for release image binding preparation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from agente_bolsa.release_binding import (
    ImageIdentityError,
    ReleaseBindingError,
    image_tag,
    prepare_release_binding,
    render_override_compose,
    render_systemd_dropin,
    validate_compose_parity,
    validate_image_identity,
)
from scripts import verify_release_binding
from scripts.prepare_release_binding import _write_plan

IMAGE_ID = "sha256:" + "a" * 64
IMAGE_REF = "agente-bolsa:0.4.376-arm64"
ROLLBACK_IMAGE_ID = "sha256:" + "c" * 64
ROLLBACK_REF = "agente-bolsa:0.4.369-arm64"


def _inspect(*, version="0.4.376", image_id=IMAGE_ID, **overrides):
    record = {
        "Id": image_id,
        "RepoTags": [f"agente-bolsa:{version}-arm64"],
        "RepoDigests": ["agente-bolsa@sha256:" + "b" * 64],
        "Architecture": "arm64",
        "Os": "linux",
        "Config": {"Labels": {"org.opencontainers.image.version": version}},
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
    assert "${AGENTE_BOLSA_IMAGE}" not in compose


def test_systemd_dropin_has_explicit_files_and_no_deps_up():
    dropin = render_systemd_dropin(
        image_ref=IMAGE_REF,
        image_id=IMAGE_ID,
        release_dir="/opt/agente-bolsa/releases/0.4.376",
    )

    assert "ExecStart=" in dropin
    assert "--project-directory /opt/agente-bolsa/releases/0.4.376/deploy" in dropin
    assert "-f /opt/agente-bolsa/releases/0.4.376/deploy/docker-compose.yml" in dropin
    assert dropin.count(" -f ") == 6
    assert dropin.count("docker-compose.release-binding.yml") == 2
    assert "-f /opt/agente-bolsa/releases/0.4.376/deploy/docker-compose.raspberry.override.yml" in dropin
    assert "-f /opt/agente-bolsa/releases/0.4.376/deploy/docker-compose.release-binding.yml" in dropin
    assert "up -d --no-deps scheduler web auxiliary" in dropin
    assert "stop scheduler web auxiliary" in dropin
    assert "ExecStartPre=/usr/bin/python3 /opt/agente-bolsa/releases/0.4.376/deploy/verify_release_binding.py" in dropin
    assert f"--expected-image-id {IMAGE_ID}" in dropin
    assert "AGENTE_BOLSA_IMAGE=" not in dropin


def test_preparation_generates_final_and_approved_rollback_without_runtime_effects(tmp_path: Path):
    plan = prepare_release_binding(
        version="0.4.376",
        image_id=IMAGE_ID,
        inspect_payload=_inspect(),
        rollback_image_id=ROLLBACK_IMAGE_ID,
        rollback_inspect_payload=_inspect(version="0.4.369", image_id=ROLLBACK_IMAGE_ID),
    )

    assert plan.image_ref == IMAGE_REF
    assert "agente-bolsa:0.4.376-arm64" in plan.override_compose
    assert "agente-bolsa:0.4.369-arm64" in plan.rollback_override_compose
    assert plan.rollback_identity.image_id == ROLLBACK_IMAGE_ID
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
        rollback_image_id=ROLLBACK_IMAGE_ID,
        rollback_inspect_payload=_inspect(version="0.4.369", image_id=ROLLBACK_IMAGE_ID),
    )
    assert json.loads(json.dumps(plan.manifest()))["image_id"] == IMAGE_ID


def test_output_preserves_original_compose_layers_and_adds_binding_last(tmp_path: Path):
    plan = prepare_release_binding(
        version="0.4.376",
        image_id=IMAGE_ID,
        inspect_payload=_inspect(),
        rollback_image_id=ROLLBACK_IMAGE_ID,
        rollback_inspect_payload=_inspect(version="0.4.369", image_id=ROLLBACK_IMAGE_ID),
    )
    _write_plan(tmp_path, plan)

    assert (tmp_path / "docker-compose.release-binding.yml").is_file()
    assert not (tmp_path / "docker-compose.raspberry.override.yml").exists()
    assert (tmp_path / "verify_release_binding.py").is_file()
    manifest = json.loads((tmp_path / "release-binding.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["base_compose"] == "docker-compose.yml"
    assert manifest["artifacts"]["raspberry_override_compose"] == "docker-compose.raspberry.override.yml"
    assert manifest["artifacts"]["release_binding_compose"] == "docker-compose.release-binding.yml"
    dropin = (tmp_path / "systemd/agente-bolsa.service.d/10-release-binding.conf").read_text(
        encoding="utf-8"
    )
    start = next(line for line in dropin.splitlines() if line.startswith("ExecStart=/usr/bin/docker"))
    assert start.count(" -f ") == 3
    assert start.endswith("up -d --no-deps scheduler web auxiliary")


def test_host_verifier_uses_inspect_argument_list_and_timeout(monkeypatch):
    calls = []

    class Completed:
        returncode = 0
        stdout = json.dumps(_inspect())

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(verify_release_binding.subprocess, "run", fake_run)
    result = verify_release_binding.verify(image_ref=IMAGE_REF, expected_image_id=IMAGE_ID)

    assert result["image_id"] == IMAGE_ID
    assert calls == [
        (
            ["/usr/bin/docker", "image", "inspect", IMAGE_REF],
            {
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": 20.0,
            },
        )
    ]


def test_host_verifier_rejects_stale_image_without_starting_anything(monkeypatch):
    class Completed:
        returncode = 0
        stdout = json.dumps(_inspect())

    monkeypatch.setattr(verify_release_binding.subprocess, "run", lambda *args, **kwargs: Completed())
    with pytest.raises(ValueError, match="ImageID mismatch"):
        verify_release_binding.verify(
            image_ref=IMAGE_REF,
            expected_image_id=ROLLBACK_IMAGE_ID,
        )


def test_compose_parity_preserves_resources_ports_mounts_and_other_services():
    source = {
        "services": {
            name: {"image": ROLLBACK_REF, "ports": ["8081:8501"],
                   "volumes": ["/var/lib/agente-bolsa:/data"],
                   "mem_limit": "2g", "environment": {"PAPER": "true"}}
            for name in ("scheduler", "web", "auxiliary")
        },
        "networks": {"default": {"name": "agente-bolsa"}},
    }
    source["services"]["init-db"] = {"image": ROLLBACK_REF}
    before = deepcopy(source)
    rendered = deepcopy(source)
    for name in ("scheduler", "web", "auxiliary"):
        rendered["services"][name]["image"] = IMAGE_REF
    validate_compose_parity(source, rendered, image_ref=IMAGE_REF)
    assert source == before
    for field in ("ports", "volumes", "mem_limit", "environment"):
        broken = deepcopy(rendered)
        broken["services"]["scheduler"].pop(field)
        with pytest.raises(ReleaseBindingError, match="compose_parity_mismatch"):
            validate_compose_parity(source, broken, image_ref=IMAGE_REF)
    broken = deepcopy(rendered)
    broken["services"]["init-db"]["image"] = IMAGE_REF
    with pytest.raises(ReleaseBindingError, match="compose_parity_mismatch"):
        validate_compose_parity(source, broken, image_ref=IMAGE_REF)


@pytest.mark.parametrize("path", ["/opt/release%h", "/opt/my release", "/opt/release\tname"])
def test_systemd_paths_reject_specifiers_and_whitespace(path):
    with pytest.raises(ReleaseBindingError, match="malformed_path"):
        render_systemd_dropin(image_ref=IMAGE_REF, image_id=IMAGE_ID, release_dir=path)


def test_rollback_requires_independent_image_evidence():
    with pytest.raises(ImageIdentityError, match="rollback_identity_required"):
        prepare_release_binding(version="0.4.376", image_id=IMAGE_ID,
                                inspect_payload=_inspect())
    with pytest.raises(ImageIdentityError, match="stale_image"):
        prepare_release_binding(version="0.4.376", image_id=IMAGE_ID,
                                inspect_payload=_inspect(), rollback_image_id=IMAGE_ID,
                                rollback_inspect_payload=_inspect(version="0.4.369",
                                                                  image_id=ROLLBACK_IMAGE_ID))
