"""Deterministic Product Wheel for the installed, data-only ``coding.base``."""

from __future__ import annotations

import csv
import io
import json
import os
import stat
import zipfile
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
)

CODING_BASE_PRODUCT_WHEEL_FILENAME = "coding_base-1-py3-none-any.whl"
_PACKAGE_NAME = "coding_base"
_DIST_INFO = "coding_base-1.dist-info"
_MAX_MEMBER_BYTES = 256 * 1024
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MEMBERS = (
    "__init__.py",
    "declarations/plugin.json",
    "plugin.json",
    "prompts/standard.md",
    "skills/standard/SKILL.md",
)


@dataclass(frozen=True, slots=True)
class CodingBaseProductWheelArtifactV1:
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


def prepare_posix_coding_base_product_wheel(
    source_root: Path,
) -> CodingBaseProductWheelArtifactV1:
    """Publish exact installed bytes in a private Product Source root once."""

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
        raise ValueError("POSIX Coding base Product Source root is required")
    body = build_coding_base_product_wheel()
    if len(body) > _MAX_WHEEL_BYTES:
        raise ValueError("Installed Coding base Product Wheel exceeds budget")
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
            raise ValueError("Coding base Product Source root is not private")
        name = CODING_BASE_PRODUCT_WHEEL_FILENAME
        try:
            member = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor
            )
        except FileNotFoundError:
            member = os.open(
                name,
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
                        raise OSError("Coding base Product Wheel write made no progress")
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
                    raise ValueError("Coding base Product Wheel changed on disk")
            finally:
                os.close(member)
    finally:
        os.close(descriptor)
    return CodingBaseProductWheelArtifactV1(
        source_root / CODING_BASE_PRODUCT_WHEEL_FILENAME,
        sha256(body).hexdigest(),
        len(body),
    )


def build_coding_base_product_wheel() -> bytes:
    """Freeze only the installed Product-owned files into a repeatable Wheel."""

    root = (Path(__file__).resolve().parent / "_plugins" / "coding_base").resolve(
        strict=True
    )
    files = {
        f"{_PACKAGE_NAME}/{relative}": _read_member(root, relative)
        for relative in _MEMBERS
    }
    manifest = json.loads(files[f"{_PACKAGE_NAME}/plugin.json"])
    if not isinstance(manifest, dict) or (
        manifest.get("name"), manifest.get("version")
    ) != ("coding.base", "1"):
        raise ValueError("Installed Coding base Product manifest changed")
    files[f"{_DIST_INFO}/METADATA"] = (
        b"Metadata-Version: 2.1\nName: coding-base\nVersion: 1\n\n"
    )
    files[f"{_DIST_INFO}/WHEEL"] = (
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
    record_name = f"{_DIST_INFO}/RECORD"
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
    "build_coding_base_product_wheel",
    "coding_base_product_local_wheel_policy",
    "prepare_posix_coding_base_product_wheel",
]
