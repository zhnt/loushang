"""Deterministic Product Wheels for Coding's installed first-party Plugins."""

from __future__ import annotations

import csv
import io
import json
import os
import stat
import zipfile
from base64 import urlsafe_b64encode
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
)

CODING_BASE_PRODUCT_WHEEL_FILENAME = "coding_base-1-py3-none-any.whl"
_PACKAGE_NAME = "coding_base"
_MAX_MEMBER_BYTES = 256 * 1024
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MEMBERS = (
    "__init__.py",
    "declarations/plugin.json",
    "plugin.json",
    "prompts/standard.md",
    "skills/standard/SKILL.md",
)
_CAPABILITY_MEMBERS = (
    "__init__.py",
    "declarations/tools.json",
    "definition.py",
    "plugin.json",
)


@dataclass(frozen=True, slots=True)
class _BuiltinWheelSpec:
    plugin_id: str
    package_name: str
    members: tuple[str, ...]

    @property
    def filename(self) -> str:
        return f"{self.package_name}-1-py3-none-any.whl"

    @property
    def dist_info(self) -> str:
        return f"{self.package_name}-1.dist-info"

    @property
    def distribution_name(self) -> str:
        return self.package_name.replace("_", "-")


_BASE_SPEC = _BuiltinWheelSpec("coding.base", _PACKAGE_NAME, _MEMBERS)
_CAPABILITY_SPECS = {
    "coding.arch.default": _BuiltinWheelSpec(
        "coding.arch.default", "coding_arch_default", _CAPABILITY_MEMBERS
    ),
    "coding.lsp.default": _BuiltinWheelSpec(
        "coding.lsp.default", "coding_lsp_default", _CAPABILITY_MEMBERS
    ),
}


@dataclass(frozen=True, slots=True)
class CodingBaseProductWheelArtifactV1:
    path: Path
    artifact_digest: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class CodingCapabilityProductWheelArtifactV1:
    plugin_id: str
    path: Path
    artifact_digest: str
    byte_count: int


def coding_base_product_local_wheel_policy(
    artifact: CodingBaseProductWheelArtifactV1,
    *,
    project_scope_id: str,
    resolution_environment_fingerprint: str,
    policy_revision: str,
    quota_profile_revision: str,
    authority_id: str,
) -> PackageProductLocalWheelPolicy:
    """Pin the installed base artifact to the Product's explicit Source policy."""

    if (
        not isinstance(artifact, CodingBaseProductWheelArtifactV1)
        or artifact.path.name != CODING_BASE_PRODUCT_WHEEL_FILENAME
        or artifact.byte_count <= 0
        or artifact.byte_count > _MAX_WHEEL_BYTES
    ):
        raise ValueError("Coding base Product Wheel evidence is invalid")
    return PackageProductLocalWheelPolicy(
        product_id="coding",
        project_scope_id=project_scope_id,
        source_root=artifact.path.parent,
        bindings=(
            PackageProductLocalWheelBindingV1(
                source_identity=str(artifact.path),
                requested_package="coding-base==1",
                plugin_id="coding.base",
                artifact_digest=artifact.artifact_digest,
                plugin_manifest_path="coding_base/plugin.json",
                source_trust_class="host-equivalent-local",
            ),
        ),
        policy_revision=policy_revision,
        quota_profile_revision=quota_profile_revision,
        resolution_environment_fingerprint=resolution_environment_fingerprint,
        authority_id=authority_id,
    )


def coding_builtin_product_local_wheel_policy(
    base: CodingBaseProductWheelArtifactV1,
    capabilities: tuple[CodingCapabilityProductWheelArtifactV1, ...],
    *,
    project_scope_id: str,
    resolution_environment_fingerprint: str,
    policy_revision: str,
    quota_profile_revision: str,
    authority_id: str,
) -> PackageProductLocalWheelPolicy:
    """Pin all three inventoried first-party Coding Plugin Sources together."""

    base_policy = coding_base_product_local_wheel_policy(
        base,
        project_scope_id=project_scope_id,
        resolution_environment_fingerprint=resolution_environment_fingerprint,
        policy_revision=policy_revision,
        quota_profile_revision=quota_profile_revision,
        authority_id=authority_id,
    )
    if (
        not isinstance(capabilities, tuple)
        or any(
            not isinstance(item, CodingCapabilityProductWheelArtifactV1)
            for item in capabilities
        )
        or tuple(item.plugin_id for item in capabilities)
        != tuple(_CAPABILITY_SPECS)
    ):
        raise ValueError("Coding Capability Product Wheel set is incomplete")
    bindings = list(base_policy.bindings)
    for artifact in capabilities:
        spec = _CAPABILITY_SPECS[artifact.plugin_id]
        if (
            artifact.path.parent != base_policy.source_root
            or artifact.path.name != spec.filename
            or artifact.byte_count <= 0
            or artifact.byte_count > _MAX_WHEEL_BYTES
        ):
            raise ValueError("Coding Capability Product Wheel evidence is invalid")
        bindings.append(
            PackageProductLocalWheelBindingV1(
                source_identity=str(artifact.path),
                requested_package=f"{spec.distribution_name}==1",
                plugin_id=artifact.plugin_id,
                artifact_digest=artifact.artifact_digest,
                plugin_manifest_path=f"{spec.package_name}/plugin.json",
                source_trust_class="host-equivalent-local",
            )
        )
    return replace(
        base_policy,
        bindings=tuple(sorted(bindings, key=lambda item: item.source_identity)),
    )


def prepare_posix_coding_base_product_wheel(
    source_root: Path,
) -> CodingBaseProductWheelArtifactV1:
    """Publish exact installed bytes in a private Product Source root once."""

    path, digest, byte_count = _publish_posix_product_wheel(
        source_root,
        filename=CODING_BASE_PRODUCT_WHEEL_FILENAME,
        body=build_coding_base_product_wheel(),
        label="base",
    )
    return CodingBaseProductWheelArtifactV1(path, digest, byte_count)


def prepare_posix_coding_capability_product_wheels(
    source_root: Path,
) -> tuple[CodingCapabilityProductWheelArtifactV1, ...]:
    """Publish the exact checked-in LSP and Arch packages into Product Source."""

    artifacts = []
    for plugin_id, spec in _CAPABILITY_SPECS.items():
        path, digest, byte_count = _publish_posix_product_wheel(
            source_root,
            filename=spec.filename,
            body=build_coding_capability_product_wheel(plugin_id),
            label="Capability",
        )
        artifacts.append(
            CodingCapabilityProductWheelArtifactV1(
                plugin_id=plugin_id,
                path=path,
                artifact_digest=digest,
                byte_count=byte_count,
            )
        )
    return tuple(artifacts)


def _publish_posix_product_wheel(
    source_root: Path, *, filename: str, body: bytes, label: str
) -> tuple[Path, str, int]:
    if (
        os.name != "posix"
        or not isinstance(source_root, Path)
        or not source_root.is_absolute()
        or ".." in source_root.parts
        or not all(
            hasattr(os, name)
            for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
        )
    ):
        raise ValueError(f"POSIX Coding {label} Product Source root is required")
    if len(body) > _MAX_WHEEL_BYTES:
        raise ValueError(f"Installed Coding {label} Product Wheel exceeds budget")
    descriptor = os.open(
        source_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        directory = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or stat.S_IMODE(directory.st_mode) & 0o077
            or directory.st_uid != os.getuid()
        ):
            raise ValueError(f"Coding {label} Product Source root is not private")
        try:
            member = os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
        except FileNotFoundError:
            member = os.open(
                filename,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=descriptor,
            )
            try:
                os.fchmod(member, 0o600)
                remaining = memoryview(body)
                while remaining:
                    written = os.write(member, remaining)
                    if written <= 0:
                        raise OSError(
                            f"Coding {label} Product Wheel write made no progress"
                        )
                    remaining = remaining[written:]
                os.fsync(member)
            finally:
                os.close(member)
            os.fsync(descriptor)
        else:
            try:
                existing = os.fstat(member)
                if (
                    not stat.S_ISREG(existing.st_mode)
                    or existing.st_nlink != 1
                    or existing.st_uid != os.getuid()
                    or stat.S_IMODE(existing.st_mode) & 0o077
                    or existing.st_size != len(body)
                    or os.read(member, len(body) + 1) != body
                ):
                    raise ValueError(f"Coding {label} Product Wheel changed on disk")
            finally:
                os.close(member)
    finally:
        os.close(descriptor)
    return source_root / filename, sha256(body).hexdigest(), len(body)


def build_coding_base_product_wheel() -> bytes:
    """Freeze only the installed Product-owned files into a repeatable Wheel."""

    return _build_coding_product_wheel(_BASE_SPEC)


def build_coding_capability_product_wheel(plugin_id: str) -> bytes:
    """Freeze one exact first-party executable Capability package."""

    try:
        spec = _CAPABILITY_SPECS[plugin_id]
    except (KeyError, TypeError) as exc:
        raise ValueError("Unknown Coding Capability Product Plugin") from exc
    return _build_coding_product_wheel(spec)


def _build_coding_product_wheel(spec: _BuiltinWheelSpec) -> bytes:
    root = (Path(__file__).resolve().parent / "_plugins" / spec.package_name).resolve(
        strict=True
    )
    files = {
        f"{spec.package_name}/{relative}": _read_member(root, relative)
        for relative in spec.members
    }
    manifest = json.loads(files[f"{spec.package_name}/plugin.json"])
    if not isinstance(manifest, dict) or (
        manifest.get("name"), manifest.get("version")
    ) != (spec.plugin_id, "1"):
        raise ValueError(f"Installed {spec.plugin_id} Product manifest changed")
    files[f"{spec.dist_info}/METADATA"] = (
        "Metadata-Version: 2.1\n"
        f"Name: {spec.distribution_name}\n"
        "Version: 1\n\n"
    ).encode("utf-8")
    files[f"{spec.dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\n"
        b"Generator: loushang-coding-product\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n\n"
    )
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    record_name = f"{spec.dist_info}/RECORD"
    writer.writerow((record_name, "", ""))
    files[record_name] = record.getvalue().encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_STORED
            archive.writestr(member, body)
    return output.getvalue()


def _read_member(root: Path, relative: str) -> bytes:
    path = root / relative
    current = path.parent
    while current != root:
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise ValueError("Installed Coding base Product directory is unsafe")
        current = current.parent
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > _MAX_MEMBER_BYTES
    ):
        raise ValueError("Installed Coding base Product member is unsafe")
    body = path.read_bytes()
    after = path.lstat()
    if (
        len(body) > _MAX_MEMBER_BYTES
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ValueError("Installed Coding base Product member changed during read")
    return body


__all__ = [
    "CODING_BASE_PRODUCT_WHEEL_FILENAME",
    "CodingBaseProductWheelArtifactV1",
    "CodingCapabilityProductWheelArtifactV1",
    "build_coding_base_product_wheel",
    "build_coding_capability_product_wheel",
    "coding_base_product_local_wheel_policy",
    "coding_builtin_product_local_wheel_policy",
    "prepare_posix_coding_base_product_wheel",
    "prepare_posix_coding_capability_product_wheels",
]
