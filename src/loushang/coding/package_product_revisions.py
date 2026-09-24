"""First-party Plugin revisions captured from the selected Product Store.

This module supplies verified bytes to the existing Plugin approval and
declaration machinery. It does not approve or execute a Definition itself.
"""

from __future__ import annotations

import io
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources.plugins.authority import PluginRuntimeResolution
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
    PluginPythonDistributionLock,
)
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceError,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginManifest,
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)

from ._capability_plugin_specs import (
    CODING_CAPABILITY_PLUGIN_SPEC_BY_ID,
    ordered_coding_capability_plugin_specs,
)
from .package_builtin_wheel import (
    build_coding_base_product_wheel,
    build_coding_capability_product_wheel,
)
from .plugin_dependency_grants import coding_plugin_distribution_evidence_resolver

_MAX_FILES = 64
_MAX_BYTES = 1024 * 1024
_DEFINITION_ENTRYPOINT = "definition.py:declare"


class _ProductSelectedRevisionHandle(VerifiedRevisionHandle):
    """Read one immutable capture only while its live Product selection agrees.

    The root is a diagnostic name, never a filesystem source. Every read
    recaptures through the Product Store, so neither a legacy package root nor
    a stale Desired selection can supply executable bytes.
    """

    def __init__(
        self,
        runtime: PackageProductRuntimeBindingV1,
        selected: PackageProductSelectedPluginManifestV1,
    ) -> None:
        selected.verified_manifest()
        snapshot = selected.snapshot
        self.root = (
            Path("/__loushang_product_snapshot__")
            / snapshot.root_ref.artifact_digest
            / snapshot.installation_key.plugin_id.replace(".", "_")
        )
        self.content_digest = snapshot.root_ref.artifact_digest
        self._runtime = runtime
        self._selected = selected
        root_relative = selected.manifest.root_relative_path.as_posix()
        prefix = "" if root_relative == "." else f"{root_relative}/"
        self._files = {
            name[len(prefix) :]: body
            for name, body in snapshot.files
            if name.startswith(prefix)
        }
        self._directories = {
            PurePosixPath(*parts[:index]).as_posix()
            for name in self._files
            for parts in (PurePosixPath(name).parts,)
            for index in range(1, len(parts))
        }
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def verify(self) -> None:
        self._require_open()
        try:
            current = self._runtime.capture_selected_plugin_manifest_for(
                self._selected.snapshot.installation_key.plugin_id,
                max_files=_MAX_FILES,
                max_total_bytes=_MAX_BYTES,
            )
            if current != self._selected:
                raise ValueError("Product selection changed")
        except (
            PackageProductRuntimeActivationError,
            PackageProductRuntimeReadError,
            ValueError,
        ) as exc:
            raise PluginRevisionError(
                "Product-selected Plugin revision changed",
                code="plugin_revision_changed",
                path=self.root,
            ) from exc

    def open_file(self, relative_path: str | PurePosixPath) -> BinaryIO:
        self.verify()
        key = canonical_plugin_relative_path(relative_path).as_posix()
        try:
            return io.BytesIO(self._files[key])
        except KeyError as exc:
            raise self._invalid_path(key) from exc

    def entry_kind(
        self, relative_path: str | PurePosixPath
    ) -> Literal["file", "directory"]:
        self.verify()
        key = canonical_plugin_relative_path(relative_path).as_posix()
        if key in self._files:
            return "file"
        if key in self._directories:
            return "directory"
        raise self._invalid_path(key)

    def file_identity(self, relative_path: str | PurePosixPath) -> tuple[str, int]:
        self.verify()
        key = canonical_plugin_relative_path(relative_path).as_posix()
        try:
            body = self._files[key]
        except KeyError as exc:
            raise self._invalid_path(key) from exc
        return sha256(body).hexdigest(), len(body)

    def acquire(self) -> _ProductSelectedRevisionHandle:
        self.verify()
        return _ProductSelectedRevisionHandle(self._runtime, self._selected)

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> _ProductSelectedRevisionHandle:
        self.verify()
        return self

    def _invalid_path(self, key: str) -> PluginRevisionError:
        return PluginRevisionError(
            "Product-selected Plugin file is unavailable",
            code="invalid_plugin_revision_path",
            path=self.root / key,
        )


def open_coding_product_capability_resolution(
    runtime: PackageProductRuntimeBindingV1,
    *,
    plugin_ids: tuple[str, ...],
) -> PluginRuntimeResolution:
    """Supply exact selected first-party revisions without a legacy materializer.

    This is a revision input to the existing approved Definition/Provider
    composer, not an execution grant. The host distribution grant is restricted
    to a Wheel identical to the installed first-party package.
    """

    if (
        not isinstance(plugin_ids, tuple)
        or not plugin_ids
        or len(plugin_ids) != len(set(plugin_ids))
    ):
        raise ValueError("Coding Product Capability selection is invalid")
    specs = ordered_coding_capability_plugin_specs(plugin_ids)
    if len(specs) != len(plugin_ids):
        raise ValueError("Coding Product Capability selection is invalid")
    return _open_selected_resolution(runtime, tuple(spec.plugin_id for spec in specs))


def open_coding_product_builtin_resolution(
    runtime: PackageProductRuntimeBindingV1,
) -> PluginRuntimeResolution:
    """Reopen the complete, sorted first-party set from one Product binding."""

    return _open_selected_resolution(
        runtime,
        ("coding.arch.default", "coding.base", "coding.lsp.default"),
    )


def _open_selected_resolution(
    runtime: PackageProductRuntimeBindingV1,
    plugin_ids: tuple[str, ...],
) -> PluginRuntimeResolution:
    if not isinstance(runtime, PackageProductRuntimeBindingV1):
        raise TypeError("Coding Product Plugin requires a Product runtime")
    packages: list[PublishedPluginPackage] = []
    bindings: list[PluginSourceBinding] = []
    plugins: list[InstalledPlugin] = []
    try:
        for plugin_id in plugin_ids:
            selected = runtime.capture_selected_plugin_manifest_for(
                plugin_id,
                max_files=_MAX_FILES,
                max_total_bytes=_MAX_BYTES,
            )
            _validate_builtin_selection(selected, plugin_id)
            handle = _ProductSelectedRevisionHandle(runtime, selected)
            try:
                lock = _host_distribution_lock(
                    plugin_id, selected.snapshot.root_ref.artifact_digest
                )
                manifest = selected.verified_manifest()
                root = handle.root
                source = PluginSource(path=root)
                package = PublishedPluginPackage(
                    root=root,
                    package_root=root,
                    manifest=PluginManifest(
                        name=manifest.name,
                        root=root,
                        version=manifest.version,
                        enabled=manifest.enabled,
                        package_root=root,
                        metadata=manifest.metadata,
                    ),
                    source=source,
                    manifest_path=root / "plugin.json",
                    manifest_digest=manifest.manifest_digest,
                    package_root_relative=Path("."),
                    contribution_index=manifest.contribution_index,
                    content_digest=handle.content_digest,
                    revision_handle=handle,
                    dependency_lock=lock,
                )
                binding = PluginSourceBinding(
                    source=str(root.resolve()),
                    source_identity=(
                        selected.snapshot.package_revision.package_source_identity
                    ),
                    source_kind="local",
                    plugin_id=plugin_id,
                    manifest_digest=manifest.manifest_digest,
                    content_digest=handle.content_digest,
                    revision=handle.content_digest,
                    revision_kind="content_sha256",
                    dependency_lock=lock,
                )
                packages.append(package)
                bindings.append(binding)
                plugins.append(
                    InstalledPlugin(
                        manifest=package.manifest,
                        source=source,
                        enabled=manifest.enabled,
                        resolved_package=package,
                    )
                )
            except BaseException:
                handle.close()
                raise
        return PluginRuntimeResolution(
            packages=tuple(packages),
            plugins=tuple(plugins),
            bindings=tuple(bindings),
        )
    except BaseException:
        for package in packages:
            package.revision_handle.close()
        raise


def _validate_builtin_selection(
    selected: PackageProductSelectedPluginManifestV1, plugin_id: str
) -> None:
    manifest = selected.verified_manifest()
    trust = selected.source_trust_snapshot
    if plugin_id == "coding.base":
        if (
            selected.snapshot.installation_key.product_id != "coding"
            or manifest.name != plugin_id
            or manifest.version != "1"
            or not manifest.enabled
            or manifest.root_relative_path.as_posix() != "coding_base"
            or manifest.package_root_relative_path != PurePosixPath(".")
            or trust is None
            or trust.source_trust_class != "host-equivalent-local"
            or sha256(build_coding_base_product_wheel()).hexdigest()
            != selected.snapshot.root_ref.artifact_digest
        ):
            raise ValueError("Coding Product base selection is not first-party")
        selected.verified_data_only_declarations()
        return
    spec = CODING_CAPABILITY_PLUGIN_SPEC_BY_ID[plugin_id]
    reservations = {
        item.contribution_id: item for item in manifest.contribution_index.items
    }
    provider = reservations.get(spec.provider_contribution_id)
    tool = reservations.get(spec.tool_contribution_id)
    if (
        selected.snapshot.installation_key.product_id != "coding"
        or manifest.name != plugin_id
        or manifest.version != "1"
        or not manifest.enabled
        or manifest.root_relative_path.as_posix() != spec.source_root().name
        or manifest.package_root_relative_path != PurePosixPath(".")
        or trust is None
        or trust.source_trust_class != "host-equivalent-local"
        or set(reservations)
        != {spec.provider_contribution_id, spec.tool_contribution_id}
        or provider is None
        or provider.kind != "capability_provider"
        or provider.declaration_source.kind != "in_process"
        or provider.declaration_source.entrypoint != _DEFINITION_ENTRYPOINT
        or provider.requested_authorities != spec.requested_authorities
        or tool is None
        or tool.kind != "tool_pack"
        or tool.declaration_source.kind != "document"
        or sha256(build_coding_capability_product_wheel(plugin_id)).hexdigest()
        != selected.snapshot.root_ref.artifact_digest
    ):
        raise ValueError("Coding Product Capability selection is not first-party")


def _host_distribution_lock(
    plugin_id: str, content_digest: str
) -> PluginDependencyClosureLock:
    if plugin_id == "coding.base":
        return PluginDependencyClosureLock(
            package_content_digest=content_digest,
            python_distributions=(),
        )
    spec = CODING_CAPABILITY_PLUGIN_SPEC_BY_ID[plugin_id]
    try:
        evidence = coding_plugin_distribution_evidence_resolver().resolve(
            "loushang",
            required_paths=(spec.source_root() / "definition.py",),
        )
    except InstalledPythonDistributionEvidenceError as exc:
        raise ValueError(
            "Coding Product Capability host distribution is unavailable"
        ) from exc
    return PluginDependencyClosureLock(
        package_content_digest=content_digest,
        python_distributions=(
            PluginPythonDistributionLock(
                name=evidence.distribution.name,
                version=evidence.distribution.version,
            ),
        ),
    )


__all__ = [
    "open_coding_product_builtin_resolution",
    "open_coding_product_capability_resolution",
]
