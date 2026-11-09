"""Product-selected snapshot revision input to existing Plugin composition.

Captured bytes never come from the diagnostic root. Existing currentness,
installed Source and distribution owners retain every read and IO operation.
This module neither approves nor executes a Plugin Definition.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO, ClassVar, Literal, Protocol

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
from loushang.harness.resources.packages.plugin_lifecycle._exact_product_source import (
    ExactProductSourceFiles,
    InstalledProductWheelRecipe,
    InstalledProductWheelSpec,
    resolve_installed_product_root,
)
from loushang.harness.resources.plugins.authority import PluginRuntimeResolution
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
    PluginPythonDistributionLock,
)
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceError,
    InstalledPythonDistributionEvidenceResolver,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
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


class CapabilityRevisionSpec(Protocol):
    @property
    def provider_contribution_id(self) -> str: ...
    @property
    def tool_contribution_id(self) -> str: ...
    @property
    def requested_authorities(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class ProductSelectedRevisionPolicy:
    product_id: str
    product_label: str
    base_plugin_id: str
    base_root_relative: str
    plugin_version: str
    source_trust_class: str
    definition_entrypoint: Callable[[], str]
    capability_spec: Callable[[str], CapabilityRevisionSpec]
    capability_location: Callable[[str], tuple[str, tuple[str, ...]]]
    source_files: Callable[[], ExactProductSourceFiles]
    wheel_recipe: Callable[[], InstalledProductWheelRecipe]
    wheel_spec: Callable[[str], InstalledProductWheelSpec]
    distribution_resolver: Callable[[], InstalledPythonDistributionEvidenceResolver]
    distribution_name: str
    maximum_files: Callable[[], int]
    maximum_bytes: Callable[[], int]
    handle_type: Callable[..., ProductSelectedRevisionHandle]
    external_trust_classes: frozenset[str]
    permits_external_owner: Callable[[str, str], bool]
    external_resource_owners: frozenset[str]


def _build_expected_wheel(
    policy: ProductSelectedRevisionPolicy, plugin_id: str
) -> bytes:
    return policy.source_files().build_installed_wheel(
        policy.wheel_spec(plugin_id), recipe=policy.wheel_recipe()
    )


def _capability_root(policy: ProductSelectedRevisionPolicy, plugin_id: str) -> Path:
    module_file, parts = policy.capability_location(plugin_id)
    return resolve_installed_product_root(module_file, parts)


class ProductSelectedRevisionHandle(VerifiedRevisionHandle):
    """Read one immutable capture only while its live Product selection agrees.

    The root is a diagnostic name, never a filesystem source. Every read
    rechecks the Product selection; bytes come from the pinned, verified
    capture, so neither a legacy root nor a stale Desired selection can
    supply executable bytes.
    """

    _handle_type: ClassVar[Callable[..., ProductSelectedRevisionHandle]]

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

    def _snapshot_verify(self) -> None:
        self._require_open()
        try:
            self._runtime.assert_selected_plugin_manifest_current(self._selected)
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

    def _snapshot_open_file(self, relative_path: str | PurePosixPath) -> BinaryIO:
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
        return (sha256(body).hexdigest(), len(body))

    def acquire(self) -> ProductSelectedRevisionHandle:
        self.verify()
        return self._handle_type(self._runtime, self._selected)

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> ProductSelectedRevisionHandle:
        self.verify()
        return self

    def _invalid_path(self, key: str) -> PluginRevisionError:
        return PluginRevisionError(
            "Product-selected Plugin file is unavailable",
            code="invalid_plugin_revision_path",
            path=self.root / key,
        )

    verify: Callable[..., None] = _snapshot_verify
    open_file: Callable[..., BinaryIO] = _snapshot_open_file


ProductSelectedRevisionHandle._handle_type = ProductSelectedRevisionHandle


def open_selected_resolution(
    policy: ProductSelectedRevisionPolicy,
    runtime: PackageProductRuntimeBindingV1,
    plugin_ids: tuple[str, ...],
    *,
    external_data_plugin_ids: frozenset[str] = frozenset(),
) -> PluginRuntimeResolution:
    if not isinstance(runtime, PackageProductRuntimeBindingV1):
        raise TypeError(
            f"{policy.product_label} Product Plugin requires a Product runtime"
        )
    packages: list[PublishedPluginPackage] = []
    bindings: list[PluginSourceBinding] = []
    plugins: list[InstalledPlugin] = []
    try:
        for plugin_id in plugin_ids:
            selected = runtime.capture_selected_plugin_manifest_for(
                plugin_id,
                max_files=policy.maximum_files(),
                max_total_bytes=policy.maximum_bytes(),
            )
            if plugin_id in external_data_plugin_ids:
                _validate_external_data_selection(policy, selected, plugin_id)
            else:
                _validate_builtin_selection(policy, selected, plugin_id)
            handle = policy.handle_type(runtime, selected)
            try:
                lock = (
                    PluginDependencyClosureLock(
                        package_content_digest=selected.snapshot.root_ref.artifact_digest,
                        python_distributions=(),
                    )
                    if plugin_id in external_data_plugin_ids
                    else _host_distribution_lock(
                        policy, plugin_id, selected.snapshot.root_ref.artifact_digest
                    )
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
                        enabled=True,
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
                    source_identity=selected.snapshot.package_revision.package_source_identity,
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
                        enabled=True,
                        resolved_package=package,
                    )
                )
            except BaseException:
                handle.close()
                raise
        return PluginRuntimeResolution(
            packages=tuple(packages), plugins=tuple(plugins), bindings=tuple(bindings)
        )
    except BaseException:
        for package in packages:
            package.revision_handle.close()
        raise


def _validate_builtin_selection(
    policy: ProductSelectedRevisionPolicy,
    selected: PackageProductSelectedPluginManifestV1,
    plugin_id: str,
) -> None:
    manifest = selected.verified_manifest()
    trust = selected.source_trust_snapshot
    if plugin_id == policy.base_plugin_id:
        if (
            selected.snapshot.installation_key.product_id != policy.product_id
            or manifest.name != plugin_id
            or manifest.version != policy.plugin_version
            or (not manifest.enabled)
            or (manifest.root_relative_path.as_posix() != policy.base_root_relative)
            or (manifest.package_root_relative_path != PurePosixPath("."))
            or (trust is None)
            or (trust.source_trust_class != policy.source_trust_class)
            or (
                sha256(_build_expected_wheel(policy, policy.base_plugin_id)).hexdigest()
                != selected.snapshot.root_ref.artifact_digest
            )
        ):
            raise ValueError(
                f"{policy.product_label} Product base selection is not first-party"
            )
        selected.verified_data_only_declarations()
        return
    spec = policy.capability_spec(plugin_id)
    reservations = {
        item.contribution_id: item for item in manifest.contribution_index.items
    }
    provider = reservations.get(spec.provider_contribution_id)
    tool = reservations.get(spec.tool_contribution_id)
    if (
        selected.snapshot.installation_key.product_id != policy.product_id
        or manifest.name != plugin_id
        or manifest.version != policy.plugin_version
        or (not manifest.enabled)
        or (
            manifest.root_relative_path.as_posix()
            != _capability_root(policy, plugin_id).name
        )
        or (manifest.package_root_relative_path != PurePosixPath("."))
        or (trust is None)
        or (trust.source_trust_class != policy.source_trust_class)
        or (
            set(reservations)
            != {spec.provider_contribution_id, spec.tool_contribution_id}
        )
        or (provider is None)
        or (provider.kind != "capability_provider")
        or (provider.declaration_source.kind != "in_process")
        or (provider.declaration_source.entrypoint != policy.definition_entrypoint())
        or (provider.requested_authorities != spec.requested_authorities)
        or (tool is None)
        or (tool.kind != "tool_pack")
        or (tool.declaration_source.kind != "document")
        or (
            sha256(_build_expected_wheel(policy, plugin_id)).hexdigest()
            != selected.snapshot.root_ref.artifact_digest
        )
    ):
        raise ValueError(
            f"{policy.product_label} Product Capability selection is not first-party"
        )


def _validate_external_data_selection(
    policy: ProductSelectedRevisionPolicy,
    selected: PackageProductSelectedPluginManifestV1,
    plugin_id: str,
) -> None:
    manifest = selected.verified_manifest()
    trust = selected.source_trust_snapshot
    pairs = selected.verified_data_only_declarations()
    if (
        selected.snapshot.installation_key.product_id != policy.product_id
        or manifest.name != plugin_id
        or trust is None
        or (not trust.trusted)
        or (trust.plugin_id != plugin_id)
        or (trust.source_trust_class not in policy.external_trust_classes)
        or (len(pairs) != 1)
        or (
            not policy.permits_external_owner(
                trust.source_trust_class, pairs[0][0].owner
            )
        )
        or (pairs[0][0].kind != "resource_item")
        or (pairs[0][0].owner not in policy.external_resource_owners)
    ):
        raise ValueError(
            f"{policy.product_label} external data selection is not admissible"
        )


def _host_distribution_lock(
    policy: ProductSelectedRevisionPolicy, plugin_id: str, content_digest: str
) -> PluginDependencyClosureLock:
    if plugin_id == policy.base_plugin_id:
        return PluginDependencyClosureLock(
            package_content_digest=content_digest, python_distributions=()
        )
    _spec = policy.capability_spec(plugin_id)
    try:
        evidence = policy.distribution_resolver().resolve(
            policy.distribution_name,
            required_paths=(_capability_root(policy, plugin_id) / "definition.py",),
        )
    except InstalledPythonDistributionEvidenceError as exc:
        raise ValueError(
            f"{policy.product_label} Product Capability host distribution is unavailable"
        ) from exc
    return PluginDependencyClosureLock(
        package_content_digest=content_digest,
        python_distributions=(
            PluginPythonDistributionLock(
                name=evidence.distribution.name, version=evidence.distribution.version
            ),
        ),
    )
