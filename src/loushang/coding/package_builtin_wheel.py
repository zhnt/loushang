"""Deterministic Product Wheels for Coding's installed first-party Plugins."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from loushang.harness.resources.packages.plugin_lifecycle._exact_product_source import (
    ExactProductSourceFiles,
    InstalledProductWheelRecipe,
    _installed_member_is_reparse,
)
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
        or tuple(item.plugin_id for item in capabilities) != tuple(_CAPABILITY_SPECS)
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


def inspect_posix_coding_base_product_wheel(
    source_root: Path,
) -> CodingBaseProductWheelArtifactV1:
    """Verify an already published built-in Wheel without publishing it."""

    path, digest, byte_count = _inspect_posix_product_wheel(
        source_root,
        filename=CODING_BASE_PRODUCT_WHEEL_FILENAME,
        body=build_coding_base_product_wheel(),
        label="base",
    )
    return CodingBaseProductWheelArtifactV1(path, digest, byte_count)


def inspect_posix_coding_capability_product_wheels(
    source_root: Path,
) -> tuple[CodingCapabilityProductWheelArtifactV1, ...]:
    """Verify all first-party Capability Sources without creating files."""

    artifacts = []
    for plugin_id, spec in _CAPABILITY_SPECS.items():
        path, digest, byte_count = _inspect_posix_product_wheel(
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


def prepare_windows_coding_base_product_wheel(
    source_root: Path,
) -> CodingBaseProductWheelArtifactV1:
    """Publish exact installed base bytes under the private Windows Source."""

    path, digest, byte_count = _publish_windows_product_wheel(
        source_root,
        filename=CODING_BASE_PRODUCT_WHEEL_FILENAME,
        body=build_coding_base_product_wheel(),
        label="base",
    )
    return CodingBaseProductWheelArtifactV1(path, digest, byte_count)


def prepare_windows_coding_capability_product_wheels(
    source_root: Path,
) -> tuple[CodingCapabilityProductWheelArtifactV1, ...]:
    """Publish exact first-party Capability bytes under the Windows Source."""

    return tuple(
        CodingCapabilityProductWheelArtifactV1(
            plugin_id=plugin_id,
            path=path,
            artifact_digest=digest,
            byte_count=byte_count,
        )
        for plugin_id, spec in _CAPABILITY_SPECS.items()
        for path, digest, byte_count in (
            _publish_windows_product_wheel(
                source_root,
                filename=spec.filename,
                body=build_coding_capability_product_wheel(plugin_id),
                label="Capability",
            ),
        )
    )


def inspect_windows_coding_base_product_wheel(
    source_root: Path,
) -> CodingBaseProductWheelArtifactV1:
    path, digest, byte_count = _inspect_windows_product_wheel(
        source_root,
        filename=CODING_BASE_PRODUCT_WHEEL_FILENAME,
        body=build_coding_base_product_wheel(),
        label="base",
    )
    return CodingBaseProductWheelArtifactV1(path, digest, byte_count)


def inspect_windows_coding_capability_product_wheels(
    source_root: Path,
) -> tuple[CodingCapabilityProductWheelArtifactV1, ...]:
    return tuple(
        CodingCapabilityProductWheelArtifactV1(
            plugin_id=plugin_id,
            path=path,
            artifact_digest=digest,
            byte_count=byte_count,
        )
        for plugin_id, spec in _CAPABILITY_SPECS.items()
        for path, digest, byte_count in (
            _inspect_windows_product_wheel(
                source_root,
                filename=spec.filename,
                body=build_coding_capability_product_wheel(plugin_id),
                label="Capability",
            ),
        )
    )


_product_source_files = ExactProductSourceFiles("Coding", lambda: _MAX_WHEEL_BYTES)
_inspect_windows_product_wheel = _product_source_files.inspect_windows
_publish_windows_product_wheel = _product_source_files.publish_windows
_inspect_posix_product_wheel = _product_source_files.inspect_posix
_publish_posix_product_wheel = _product_source_files.publish_posix


_PRODUCT_WHEEL_RECIPE = InstalledProductWheelRecipe(
    module_file=lambda: __file__,
    package_directory="_plugins",
    version="1",
    metadata_version="2.1",
    wheel_metadata=(
        b"Wheel-Version: 1.0\n"
        b"Generator: loushang-coding-product\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n\n"
    ),
    maximum_member_bytes=lambda: _MAX_MEMBER_BYTES,
)


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
    return _product_source_files.build_installed_wheel(
        spec, recipe=_PRODUCT_WHEEL_RECIPE
    )


def _read_member(root: Path, relative: str) -> bytes:
    return _product_source_files.read_installed_member(
        root, relative, maximum_bytes=lambda: _MAX_MEMBER_BYTES
    )


def _is_windows_reparse(metadata: os.stat_result) -> bool:
    return _installed_member_is_reparse(metadata)


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
    "prepare_windows_coding_base_product_wheel",
    "prepare_windows_coding_capability_product_wheels",
    "inspect_posix_coding_base_product_wheel",
    "inspect_posix_coding_capability_product_wheels",
    "inspect_windows_coding_base_product_wheel",
    "inspect_windows_coding_capability_product_wheels",
]
