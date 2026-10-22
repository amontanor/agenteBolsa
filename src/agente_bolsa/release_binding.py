"""Pure preparation and validation for a Raspberry release image binding.

The helper in this module prepares files for a later operator controlled cutover.
It never calls Docker or systemd.  In particular, an image tag is not treated as
proof that the tag currently points at the intended image: callers must provide
the output of ``docker image inspect`` and the expected Docker Image ID.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

SCHEMA_VERSION = "p-l-release-binding.v1"
CORE_SERVICES = ("scheduler", "web", "auxiliary")
DEFAULT_ROLLBACK_VERSION = "0.4.369"
IMAGE_REPOSITORY = "agente-bolsa"
_VERSION_RE = re.compile(r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class ReleaseBindingError(ValueError):
    """Raised when a release binding cannot be prepared safely."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ImageIdentityError(ReleaseBindingError):
    """Raised when supplied Docker identity evidence is absent or stale."""


@dataclass(frozen=True)
class ImageIdentity:
    """Identity extracted from one Docker image inspect record."""

    image_ref: str
    image_id: str
    architecture: str
    operating_system: str
    repo_digests: tuple[str, ...]
    labels: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        """Return redacted, serializable identity evidence."""

        return {
            "image_ref": self.image_ref,
            "image_id": self.image_id,
            "architecture": self.architecture,
            "os": self.operating_system,
            "registry_repo_digests": list(self.repo_digests),
            "labels": dict(self.labels),
        }


@dataclass(frozen=True)
class ReleaseBindingPlan:
    """Validated files and metadata for a later release cutover."""

    version: str
    image_ref: str
    image_identity: ImageIdentity
    release_dir: str
    env_file: str
    compose_filename: str
    override_filename: str
    override_compose: str
    systemd_dropin: str
    rollback_version: str
    rollback_image_ref: str
    rollback_identity: ImageIdentity
    rollback_override_compose: str
    rollback_systemd_dropin: str

    def manifest(self) -> dict[str, Any]:
        """Return a deterministic manifest suitable for an audit receipt."""

        return {
            "schema_version": SCHEMA_VERSION,
            "status": "prepared",
            "release_version": self.version,
            "image_ref": self.image_ref,
            "image_id": self.image_identity.image_id,
            "registry_repo_digests": list(self.image_identity.repo_digests),
            "architecture": self.image_identity.architecture,
            "os": self.image_identity.operating_system,
            "services": list(CORE_SERVICES),
            "release_dir": self.release_dir,
            "env_file": self.env_file,
            "artifacts": {
                "base_compose": self.compose_filename,
                "raspberry_override_compose": "docker-compose.raspberry.override.yml",
                "release_binding_compose": self.override_filename,
                "systemd_dropin": "systemd/agente-bolsa.service.d/10-release-binding.conf",
                "host_verifier": "verify_release_binding.py",
            },
            "rollback": {
                "release_version": self.rollback_version,
                "image_ref": self.rollback_image_ref,
                "image_id": self.rollback_identity.image_id,
                "registry_repo_digests": list(self.rollback_identity.repo_digests),
                "release_binding_compose": "rollback/docker-compose.release-binding.yml",
                "systemd_dropin": "rollback/systemd/agente-bolsa.service.d/10-release-binding.conf",
                "host_verifier": "rollback/verify_release_binding.py",
                "verification_required": True,
                "reason": (
                    "Approved 0.4.369 reference. Current 0.4.321 has a confirmed "
                    "kernel violation and is not a safe rollback reference."
                ),
            },
            "preparation_effects": {
                "docker": False,
                "systemd": False,
                "services_mutated": False,
                "env_modified": False,
                "kernel_resigned": False,
            },
        }


def _require_version(value: str, field: str = "version") -> str:
    if not isinstance(value, str) or _VERSION_RE.fullmatch(value) is None:
        raise ReleaseBindingError("malformed_version", f"{field} must be strict SemVer")
    return value


def image_tag(version: str) -> str:
    """Build canonical release tag; reject shell, digest, and mutable refs."""

    version = _require_version(version)
    return f"{IMAGE_REPOSITORY}:{version}-arm64"


def _require_image_ref(image_ref: str, version: str) -> str:
    expected = image_tag(version)
    if not isinstance(image_ref, str) or image_ref != expected:
        raise ReleaseBindingError(
            "malformed_image_ref",
            f"image reference must be exactly {expected!r}",
        )
    return image_ref


def _require_image_id(image_id: str, field: str = "image_id") -> str:
    if not isinstance(image_id, str) or _IMAGE_ID_RE.fullmatch(image_id) is None:
        raise ImageIdentityError(
            "malformed_image_id",
            f"{field} must be a Docker ImageID sha256 digest",
        )
    return image_id


def _require_token(value: str, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise ReleaseBindingError("malformed_token", f"{field} contains unsafe characters")
    return value


def _require_posix_path(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or any(ord(character) < 32 for character in value)
        or any(character in value for character in "% ;|&$`'\"\\")
    ):
        raise ReleaseBindingError("malformed_path", f"{field} must be an absolute POSIX path")
    path = PurePosixPath(value)
    if ".." in path.parts:
        raise ReleaseBindingError("malformed_path", f"{field} cannot contain '..'")
    return value.rstrip("/") or "/"


def _inspect_record(payload: Any) -> Mapping[str, Any]:
    """Normalize Docker inspect JSON while rejecting ambiguous input."""

    if isinstance(payload, Mapping):
        record = payload
    elif isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], Mapping):
        record = payload[0]
    else:
        raise ImageIdentityError("missing_image_identity", "inspect JSON must contain one image")
    return record


def _string_list(value: Any, field: str, *, allow_missing: bool = True) -> tuple[str, ...]:
    if value is None and allow_missing:
        return ()
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ImageIdentityError("malformed_image_identity", f"{field} must be a string list")
    return tuple(value)


def validate_image_identity(
    inspect_payload: Any,
    *,
    image_ref: str,
    expected_image_id: str,
    version: str,
) -> ImageIdentity:
    """Validate exact tag, real Docker ImageID, platform, and release version.

    ``RepoDigests`` are retained as registry provenance only. They are never
    compared with ``Id`` and never accepted in place of Docker ``Id``.
    """

    version = _require_version(version)
    image_ref = _require_image_ref(image_ref, version)
    expected_image_id = _require_image_id(expected_image_id, "expected_image_id")
    record = _inspect_record(inspect_payload)

    actual_id = record.get("Id")
    if actual_id is None:
        raise ImageIdentityError("missing_image_id", "Docker inspect record has no Id")
    actual_id = _require_image_id(actual_id)
    if actual_id != expected_image_id:
        raise ImageIdentityError(
            "stale_image",
            f"ImageID {actual_id} does not match expected {expected_image_id}",
        )

    repo_tags = _string_list(record.get("RepoTags"), "RepoTags", allow_missing=False)
    if image_ref not in repo_tags:
        raise ImageIdentityError("image_tag_missing", f"inspect record is not tagged {image_ref}")

    architecture = record.get("Architecture")
    if architecture != "arm64":
        raise ImageIdentityError("wrong_architecture", "release image must be linux/arm64")
    operating_system = record.get("Os")
    if operating_system != "linux":
        raise ImageIdentityError("wrong_os", "release image must target linux")

    config = record.get("Config", {})
    if config is None:
        config = {}
    if not isinstance(config, Mapping):
        raise ImageIdentityError("malformed_image_identity", "Config must be a map")
    labels_raw = config.get("Labels", {})
    if labels_raw is None:
        labels_raw = {}
    if not isinstance(labels_raw, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in labels_raw.items()
    ):
        raise ImageIdentityError("malformed_image_identity", "Config.Labels must be a string map")
    repo_digests = _string_list(record.get("RepoDigests"), "RepoDigests")
    return ImageIdentity(
        image_ref=image_ref,
        image_id=actual_id,
        architecture=architecture,
        operating_system=operating_system,
        repo_digests=repo_digests,
        labels=dict(labels_raw),
    )


def _compose_paths(
    release_dir: str,
    compose_filename: str,
    override_filename: str,
    binding_filename: str,
) -> tuple[str, str, str]:
    release_dir = _require_posix_path(release_dir, "release_dir")
    compose_filename = _require_token(compose_filename, "compose_filename")
    override_filename = _require_token(override_filename, "override_filename")
    binding_filename = _require_token(binding_filename, "binding_filename")
    deploy_dir = PurePosixPath(release_dir) / "deploy"
    return (
        str(deploy_dir / compose_filename),
        str(deploy_dir / override_filename),
        str(deploy_dir / binding_filename),
    )


def render_override_compose(image_ref: str) -> str:
    """Render third Compose layer with fixed images for core services."""

    if not isinstance(image_ref, str) or not re.fullmatch(
        rf"{re.escape(IMAGE_REPOSITORY)}:[0-9]+\.[0-9]+\.[0-9]+-arm64", image_ref
    ):
        raise ReleaseBindingError("malformed_image_ref", "override image reference is unsafe")
    lines = [
        "# Generated by prepare_release_binding.py; exact release image binding.",
        "# Keep image literal; runtime environment is not image authority.",
        "services:",
    ]
    for service in CORE_SERVICES:
        lines.extend((f"  {service}:", f"    image: {image_ref}"))
    return "\n".join(lines) + "\n"


def validate_compose_parity(
    source_config: Mapping[str, Any],
    rendered_config: Mapping[str, Any],
    *,
    image_ref: str,
) -> None:
    """Check normalized Compose snapshots differ only in core image values.

    Compose rendering itself remains an operator/host gate. This pure check is
    useful for an offline receipt after the host has rendered all three files.
    """

    render_override_compose(image_ref)
    if not isinstance(source_config, Mapping) or not isinstance(rendered_config, Mapping):
        raise ReleaseBindingError("compose_parity_mismatch", "rendered Compose snapshots must be maps")
    source = deepcopy(dict(source_config))
    rendered = deepcopy(dict(rendered_config))
    source_services = source.get("services")
    rendered_services = rendered.get("services")
    if not isinstance(source_services, Mapping) or not isinstance(rendered_services, Mapping):
        raise ReleaseBindingError("compose_parity_mismatch", "Compose snapshots must contain services maps")
    for service in CORE_SERVICES:
        source_service = source_services.get(service)
        rendered_service = rendered_services.get(service)
        if not isinstance(source_service, Mapping) or not isinstance(rendered_service, Mapping):
            raise ReleaseBindingError("compose_parity_mismatch", f"missing service {service}")
        if rendered_service.get("image") != image_ref:
            raise ReleaseBindingError("compose_parity_mismatch", f"image mismatch for {service}")
        source_service = dict(source_service)
        rendered_service = dict(rendered_service)
        source_service.pop("image", None)
        rendered_service.pop("image", None)
        source_services[service] = source_service
        rendered_services[service] = rendered_service
    if source != rendered:
        raise ReleaseBindingError("compose_parity_mismatch", "rendered Compose changed non-image configuration")


def _compose_command(
    *,
    image_ref: str,
    release_dir: str,
    env_file: str,
    compose_filename: str,
    override_filename: str,
    binding_filename: str,
    action: str,
) -> str:
    compose_path, override_path, binding_path = _compose_paths(
        release_dir, compose_filename, override_filename, binding_filename
    )
    args = [
        "/usr/bin/docker",
        "compose",
        "--project-name",
        "agente-bolsa",
        "--project-directory",
        str(PurePosixPath(release_dir) / "deploy"),
        "--env-file",
        _require_posix_path(env_file, "env_file"),
        "-f",
        compose_path,
        "-f",
        override_path,
        "-f",
        binding_path,
        action,
    ]
    if action == "up":
        args.extend(("-d", "--no-deps"))
    args.extend(CORE_SERVICES)
    return shlex.join(args)


def render_systemd_dropin(
    *,
    image_ref: str,
    release_dir: str,
    env_file: str = "/etc/agente-bolsa/runtime.env",
    compose_filename: str = "docker-compose.yml",
    override_filename: str = "docker-compose.raspberry.override.yml",
    binding_filename: str = "docker-compose.release-binding.yml",
    image_id: str | None = None,
    verifier_filename: str = "verify_release_binding.py",
) -> str:
    """Render systemd command lines with explicit Compose files and services."""

    if not isinstance(image_ref, str) or not re.fullmatch(
        rf"{re.escape(IMAGE_REPOSITORY)}:[0-9]+\.[0-9]+\.[0-9]+-arm64", image_ref
    ):
        raise ReleaseBindingError("malformed_image_ref", "systemd image reference is unsafe")
    _compose_paths(release_dir, compose_filename, override_filename, binding_filename)
    release_dir = _require_posix_path(release_dir, "release_dir")
    _require_posix_path(env_file, "env_file")
    image_id = _require_image_id(image_id or "", "image_id")
    verifier_filename = _require_token(verifier_filename, "verifier_filename")
    start = _compose_command(
        image_ref=image_ref,
        release_dir=release_dir,
        env_file=env_file,
        compose_filename=compose_filename,
        override_filename=override_filename,
        binding_filename=binding_filename,
        action="up",
    )
    stop = _compose_command(
        image_ref=image_ref,
        release_dir=release_dir,
        env_file=env_file,
        compose_filename=compose_filename,
        override_filename=override_filename,
        binding_filename=binding_filename,
        action="stop",
    )
    deploy_dir = str(PurePosixPath(release_dir) / "deploy")
    verifier_path = str(PurePosixPath(deploy_dir) / verifier_filename)
    verifier = shlex.join(
        [
            "/usr/bin/python3",
            verifier_path,
            "--image-ref",
            image_ref,
            "--expected-image-id",
            image_id,
            "--timeout-seconds",
            "20",
        ]
    )
    return (
        "# Generated by prepare_release_binding.py; preparation only.\n"
        "[Service]\n"
        f"WorkingDirectory={deploy_dir}\n"
        f"EnvironmentFile={env_file}\n"
        f"ExecStartPre={verifier}\n"
        "ExecStart=\n"
        f"ExecStart={start}\n"
        "ExecStop=\n"
        f"ExecStop={stop}\n"
    )


def prepare_release_binding(
    *,
    version: str,
    image_id: str,
    inspect_payload: Any,
    rollback_image_id: str | None = None,
    rollback_inspect_payload: Any | None = None,
    release_dir: str | None = None,
    env_file: str = "/etc/agente-bolsa/runtime.env",
    rollback_version: str = DEFAULT_ROLLBACK_VERSION,
) -> ReleaseBindingPlan:
    """Validate identity and render final plus explicit approved rollback files."""

    version = _require_version(version)
    rollback_version = _require_version(rollback_version, "rollback_version")
    if rollback_version != DEFAULT_ROLLBACK_VERSION:
        raise ReleaseBindingError(
            "rollback_reference_not_approved",
            f"rollback must remain approved {DEFAULT_ROLLBACK_VERSION}",
        )
    image_ref = image_tag(version)
    identity = validate_image_identity(
        inspect_payload,
        image_ref=image_ref,
        expected_image_id=image_id,
        version=version,
    )
    if rollback_image_id is None or rollback_inspect_payload is None:
        raise ImageIdentityError(
            "rollback_identity_required",
            "approved rollback requires image ID and docker image inspect evidence",
        )
    rollback_image_ref = image_tag(rollback_version)
    rollback_identity = validate_image_identity(
        rollback_inspect_payload,
        image_ref=rollback_image_ref,
        expected_image_id=rollback_image_id,
        version=rollback_version,
    )
    release_dir = release_dir or f"/opt/agente-bolsa/releases/{version}"
    release_dir = _require_posix_path(release_dir, "release_dir")
    _require_posix_path(env_file, "env_file")
    return ReleaseBindingPlan(
        version=version,
        image_ref=image_ref,
        image_identity=identity,
        release_dir=release_dir,
        env_file=env_file,
        compose_filename="docker-compose.yml",
        override_filename="docker-compose.release-binding.yml",
        override_compose=render_override_compose(image_ref),
        systemd_dropin=render_systemd_dropin(
            image_ref=image_ref,
            release_dir=release_dir,
            env_file=env_file,
            image_id=identity.image_id,
        ),
        rollback_version=rollback_version,
        rollback_image_ref=rollback_image_ref,
        rollback_identity=rollback_identity,
        rollback_override_compose=render_override_compose(rollback_image_ref),
        rollback_systemd_dropin=render_systemd_dropin(
            image_ref=rollback_image_ref,
            release_dir=f"/opt/agente-bolsa/releases/{rollback_version}",
            env_file=env_file,
            image_id=rollback_identity.image_id,
        ),
    )


def load_inspect_json(raw: str) -> Any:
    """Decode inspect JSON with a stable error class for CLI callers."""

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImageIdentityError("malformed_image_identity", "inspect JSON is invalid") from exc
