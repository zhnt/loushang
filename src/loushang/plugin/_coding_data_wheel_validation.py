"""Inert, bounded author check for Coding's Skill and Prompt Wheel profiles."""

from __future__ import annotations

import io
import os
import re
import stat
import zipfile
from hashlib import sha256
from pathlib import Path

from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerificationError,
    inspect_package_wheel_bytes,
)
from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser

_WHEEL_NAME = re.compile(
    r"(?P<plugin>[a-z][a-z0-9]*)-(?P<version>[0-9]+(?:\.[0-9]+){0,2})-py3-none-any\.whl\Z"
)
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_BUDGET = PackageInspectionBudgetV1(
    max_entries=16,
    max_total_expanded_bytes=1024 * 1024,
    max_entry_expanded_bytes=1024 * 1024,
    max_path_length=512,
    max_path_components=32,
    max_metadata_bytes=128 * 1024,
    max_wall_time_ms=5000,
)


class _ProfileRefusal(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_coding_data_wheel(path: str | Path) -> dict[str, object]:
    """Check exact inert bytes; target Product admission remains separate."""

    source = Path(path).expanduser().absolute()
    base: dict[str, object] = {
        "artifactPath": str(source),
        "productAdmission": "not_checked",
        "productSelection": "not_checked",
        "productUse": "not_checked",
    }
    match = _WHEEL_NAME.fullmatch(source.name)
    if match is None or len(source.name) > 180:
        return _failure(base, "coding_data_wheel_filename_unsupported")
    try:
        body = _read_regular_wheel(source)
    except (OSError, _ProfileRefusal):
        return _failure(base, "coding_data_wheel_source_unsafe")
    digest = sha256(body).hexdigest()
    base.update(pluginId=match["plugin"], version=match["version"], sha256=digest)
    try:
        inspected = inspect_package_wheel_bytes(
            body,
            wheel_filename=source.name,
            budgets=_BUDGET,
            max_artifact_bytes=_MAX_WHEEL_BYTES,
        )
    except PackageWheelVerificationError as exc:
        return _failure(base, exc.code)
    if (
        inspected.distribution != match["plugin"]
        or inspected.version != match["version"]
        or inspected.requires_dist
        or inspected.provides_extra
    ):
        return _failure(base, "coding_data_wheel_profile_unsupported")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            files = {item.filename: archive.read(item) for item in archive.infolist()}
        kind, contribution_id = _check_data_profile(
            files, match["plugin"], match["version"]
        )
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile, UnicodeError):
        return _failure(base, "coding_data_wheel_profile_unsupported")
    return {
        **base,
        "contributionId": contribution_id,
        "diagnostics": [],
        "profile": f"coding-data-{kind}-v1",
        "resourceKind": kind,
        "valid": True,
    }


def _read_regular_wheel(path: Path) -> bytes:
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode) or not 0 < initial.st_size <= _MAX_WHEEL_BYTES:
        raise _ProfileRefusal("coding_data_wheel_source_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or _identity(initial) != _identity(opened):
            raise _ProfileRefusal("coding_data_wheel_source_unsafe")
        body = handle.read(_MAX_WHEEL_BYTES + 1)
        after = os.fstat(handle.fileno())
    visible = path.lstat()
    if (
        not body
        or len(body) > _MAX_WHEEL_BYTES
        or _identity(opened) != _identity(after)
        or _identity(opened) != _identity(visible)
    ):
        raise _ProfileRefusal("coding_data_wheel_source_unsafe")
    return body


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _check_data_profile(
    files: dict[str, bytes], plugin_id: str, version: str
) -> tuple[str, str]:
    root = plugin_id
    fixed = {f"{root}/plugin.json", f"{root}/declarations/resources.json"}
    metadata = {
        f"{root}-{version}.dist-info/{name}" for name in ("WHEEL", "METADATA", "RECORD")
    }
    if not fixed | metadata <= files.keys() or len(files) != 6:
        raise _ProfileRefusal("coding_data_wheel_profile_unsupported")
    manifest = PluginManifestParser().parse_file_set(
        files, manifest_logical_path=f"{root}/plugin.json"
    )
    if manifest.name != plugin_id or manifest.version != version:
        raise _ProfileRefusal("coding_data_wheel_profile_unsupported")
    reservations = manifest.contribution_index.items
    if len(reservations) != 1:
        raise _ProfileRefusal("coding_data_wheel_profile_unsupported")
    reservation = reservations[0]
    if (
        reservation.kind != "resource_item"
        or reservation.contribution_execution_model != "data_only"
        or reservation.declaration_source.kind != "document"
        or reservation.declaration_source.relative_path.as_posix()
        != "declarations/resources.json"
        or reservation.requested_authorities
        or reservation.configuration
        or reservation.worker_configuration is not None
    ):
        raise _ProfileRefusal("coding_data_wheel_profile_unsupported")
    document = PluginDeclarationDocumentCodec.decode_bytes(
        files[f"{root}/declarations/resources.json"]
    )
    if len(document.declarations) != 1:
        raise _ProfileRefusal("coding_data_wheel_profile_unsupported")
    declaration = document.declarations[0]
    if (
        declaration.plugin_id != plugin_id
        or declaration.contribution_id != reservation.contribution_id
        or declaration.kind != reservation.kind
        or declaration.owner != reservation.owner
        or declaration.reservation_fingerprint != reservation.fingerprint
        or declaration.source_descriptor_fingerprint
        != reservation.source_descriptor_fingerprint
        or declaration.source_kind != "document"
        or declaration.contribution_execution_model
        not in (None, reservation.contribution_execution_model)
        or declaration.worker_configuration != reservation.worker_configuration
    ):
        raise _ProfileRefusal("coding_data_wheel_profile_unsupported")
    payload = ResourceItemDeclarationPayload.from_dict(dict(declaration.payload))
    kind = payload.resource_kind
    if kind == "skill":
        expected_body = f"{root}/{payload.locator}/SKILL.md"
        valid_shape = (
            payload.locator_kind == "directory"
            and payload.schema_id == "loushang.resource.skill"
            and payload.media_type == "text/markdown"
            and payload.locator.startswith("skills/")
            and len(payload.locator.split("/")) == 2
        )
    elif kind == "prompt":
        expected_body = f"{root}/{payload.locator}"
        valid_shape = (
            payload.locator_kind == "file"
            and payload.schema_id == "loushang.resource.prompt"
            and payload.media_type == "text/markdown"
            and payload.locator.startswith("prompts/")
            and len(payload.locator.split("/")) == 2
            and payload.locator.endswith(".md")
        )
    else:
        raise _ProfileRefusal("coding_data_wheel_profile_unsupported")
    if (
        not valid_shape
        or payload.owner_namespace != f"resources.{kind}"
        or set(files) - fixed - metadata != {expected_body}
    ):
        raise _ProfileRefusal("coding_data_wheel_profile_unsupported")
    files[expected_body].decode("utf-8")
    return kind, reservation.contribution_id


def _failure(base: dict[str, object], code: str) -> dict[str, object]:
    return {
        **base,
        "diagnostics": [{"code": code}],
        "valid": False,
    }


__all__ = ["validate_coding_data_wheel"]
