"""Product-selected snapshot revision input to existing Plugin composition.

Captured bytes never come from the diagnostic root. Existing currentness,
installed Source and distribution owners retain every read and IO operation.
This module neither approves nor executes a Plugin Definition.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    BinaryIO,
    ClassVar,
    Generic,
    Literal,
    Protocol,
    TypeVar,
)

from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductPluginDesiredSelectionV1,
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
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    admits_single_data_resource,
)
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
from loushang.harness.resources.plugins.selection import PluginSourceTrustSnapshotV1
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginManifest,
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)

if TYPE_CHECKING:
    from loushang.harness.capabilities.consumer_requirements import (
        ProductCompositionCompilation,
    )
    from loushang.harness.capabilities.provider_binding import (
        CapabilityBundleProviderBinding,
    )
    from loushang.harness.resources.plugins.selection import (
        PluginSelection,
        PluginSelectionPlanV2,
    )
    from loushang.harness.session.capability_composition_inputs import (
        SessionCapabilityCompositionInputs,
    )
    from loushang.harness.session.product_composition_assembly import (
        ProductPluginCompositionAssembly,
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
                capture_external_data_declaration(
                    selected,
                    trust_classes=policy.external_trust_classes,
                    resource_owners=policy.external_resource_owners,
                    permits_owner=policy.permits_external_owner,
                    invalid=f"{policy.product_label} external data selection is not admissible",
                    expected_selection=(policy.product_id, plugin_id),
                )
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


def capture_external_data_declaration(
    selected: PackageProductSelectedPluginManifestV1,
    *,
    trust_classes: frozenset[str],
    resource_owners: frozenset[str],
    permits_owner: Callable[[str, str], bool],
    invalid: str,
    expected_selection: tuple[str, str] | None = None,
    standalone: bool = False,
) -> tuple[PluginContributionReservation, PluginDeclaration]:
    """Read the single declaration allowed by the Product's data Source policy."""
    manifest = selected.verified_manifest() if expected_selection is not None else None
    trust = selected.source_trust_snapshot
    pairs = selected.verified_data_only_declarations()
    if (
        (
            expected_selection is not None
            and (
                selected.snapshot.installation_key.product_id != expected_selection[0]
                or manifest is None
                or manifest.name != expected_selection[1]
            )
        )
        or trust is None
        or (standalone and not isinstance(trust, PluginSourceTrustSnapshotV1))
        or not trust.trusted
        or (expected_selection is not None and trust.plugin_id != expected_selection[1])
        or not admits_single_data_resource(
            pairs,
            trust.source_trust_class,
            trust_classes=trust_classes,
            resource_owners=resource_owners,
            permits_owner=permits_owner,
        )
        or (
            standalone
            and (
                selected.snapshot.installation_key.plugin_id != selected.manifest.name
                or selected.snapshot.instance_revision_ref.plugin_id != selected.manifest.name
            )
        )
    ):
        raise ValueError(invalid)
    (declaration,) = pairs
    return declaration


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


def validate_preparation_lineage(
    runtime: PluginRuntimeResolution,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    label: str,
) -> None:
    if len(runtime.packages) != len(selected):
        raise ValueError(f"{label} selection is incomplete")
    for package, binding, item in zip(
        runtime.packages, runtime.bindings, selected, strict=True
    ):
        verified = item.verified_manifest()
        if (
            package.manifest.name != verified.name
            or package.manifest.version != verified.version
            or package.manifest.metadata != verified.metadata
            or (package.manifest_digest != verified.manifest_digest)
            or (package.contribution_index != verified.contribution_index)
            or (not package.manifest.enabled)
            or (not package.source.enabled)
            or (package.content_digest != item.snapshot.root_ref.artifact_digest)
            or (
                binding.source_identity
                != item.snapshot.package_revision.package_source_identity
            )
            or (item.source_trust_snapshot is None)
        ):
            raise ValueError(f"{label} revision changed")
        package.revision_handle.verify()


_SelectionItemT = TypeVar("_SelectionItemT")


@dataclass(slots=True)
class SelectedProductPreparationScope(Generic[_SelectionItemT]):
    """Retain the original runtime across second capture and domain preparation.

    Successful work transfers the runtime to its nominal result. Any failure
    after a completed open closes it, with the original close-error priority.
    A class context also preserves StopIteration from acquisition/validation.
    """

    product_runtime: PackageProductRuntimeBindingV1
    open_runtime: Callable[[], PluginRuntimeResolution]
    selection_items: Callable[[PluginRuntimeResolution], Iterable[_SelectionItemT]]
    selection_id: Callable[[_SelectionItemT], str]
    maximum_files: Callable[[], int]
    maximum_bytes: Callable[[], int]
    label: str
    _runtime: PluginRuntimeResolution = field(init=False, repr=False)

    def __enter__(
        self,
    ) -> tuple[
        PluginRuntimeResolution, tuple[PackageProductSelectedPluginManifestV1, ...]
    ]:
        self._runtime = self.open_runtime()
        try:
            selected = tuple(
                self.product_runtime.capture_selected_plugin_manifest_for(
                    self.selection_id(item),
                    max_files=self.maximum_files(),
                    max_total_bytes=self.maximum_bytes(),
                )
                for item in self.selection_items(self._runtime)
            )
            validate_preparation_lineage(self._runtime, selected, label=self.label)
        except BaseException:
            self._runtime.close()
            raise
        return self._runtime, selected

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if error_type is not None:
            self._runtime.close()


def selected_runtime_recheck(runtime: PluginRuntimeResolution) -> Callable[[], None]:
    """Keep only this runtime and read its current packages on every recheck."""

    def recheck_selected_revisions() -> None:
        for package in runtime.packages:
            package.revision_handle.verify()

    return recheck_selected_revisions


ProductAdmissionFailure = Callable[[tuple[str, ...]], Exception]


def observe_requested_plugins(
    runtime: PackageProductRuntimeBindingV1,
    requests: tuple[tuple[str, bool], ...],
    admission_failure: ProductAdmissionFailure,
) -> tuple[list[str], tuple[PackageProductPluginDesiredSelectionV1, ...]]:
    enabled: list[str] = []
    observed: list[PackageProductPluginDesiredSelectionV1] = []
    for plugin_id, requested in requests:
        if not requested:
            continue
        selection = runtime.capture_plugin_desired_selection_for(plugin_id)
        observed.append(selection)
        if selection.desired_state == "absent" and not selection.recorded:
            raise admission_failure(("product_requested_capability_not_installed",))
        if selection.desired_state == "installed_enabled":
            enabled.append(plugin_id)
    return enabled, tuple(observed)


def require_current_manifests(
    runtime: PackageProductRuntimeBindingV1,
    manifests: tuple[PackageProductSelectedPluginManifestV1, ...],
    reason: str = "",
    admission_failure: ProductAdmissionFailure | None = None,
) -> None:
    try:
        for manifest in manifests:
            runtime.assert_selected_plugin_manifest_current(manifest)
    except (
        PackageProductRuntimeActivationError,
        PackageProductRuntimeReadError,
    ) as exc:
        if admission_failure is None:
            raise
        raise admission_failure((reason,)) from exc


def capture_catalog_base_selection(
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    admission_failure: ProductAdmissionFailure,
) -> PackageProductPluginDesiredSelectionV1 | None:
    """Distinguish a recorded disabled base from a missing installation."""
    selection = runtime.capture_plugin_desired_selection_for(plugin_id)
    if selection.desired_state == "installed_disabled" or (
        selection.desired_state == "absent" and selection.recorded
    ):
        return selection
    if selection.desired_state != "installed_enabled":
        raise admission_failure(("product_requested_base_not_installed",))
    return None


@dataclass(frozen=True, slots=True)
class ProductCatalogSelection:
    """Exact Package Store evidence retained from Catalog preparation to refresh."""

    runtime: PackageProductRuntimeBindingV1 | None = None
    capability_selections: tuple[PackageProductPluginDesiredSelectionV1, ...] = ()
    disabled_base: PackageProductPluginDesiredSelectionV1 | None = None
    base: PackageProductSelectedPluginManifestV1 | None = None
    capabilities: tuple[PackageProductSelectedPluginManifestV1, ...] = ()
    external: tuple[PackageProductSelectedPluginManifestV1, ...] = ()

    @property
    def desired(self) -> tuple[PackageProductPluginDesiredSelectionV1, ...]:
        if self.disabled_base is None:
            return self.capability_selections
        return (self.disabled_base, *self.capability_selections)

    def capture_capabilities_without_base(
        self, *, max_files: int, max_total_bytes: int
    ) -> tuple[PackageProductSelectedPluginManifestV1, ...]:
        if self.base is not None or self.runtime is None:
            return ()
        return capture_selected_manifests(
            self.runtime.capture_selected_plugin_manifest_for,
            (
                selection.installation_key.plugin_id
                for selection in self.capability_selections
                if selection.desired_state == "installed_enabled"
            ),
            max_files=max_files,
            max_total_bytes=max_total_bytes,
        )

    def require_current(
        self,
        *,
        product_label: str,
        refresh_failure: ProductAdmissionFailure | None = None,
    ) -> None:
        """Recheck the pinned startup evidence and refresh-specific Store membership."""

        def require_runtime(role: str) -> PackageProductRuntimeBindingV1:
            if self.runtime is None:
                raise RuntimeError(
                    f"{product_label} Product {role} runtime is unavailable"
                )
            return self.runtime

        if self.capability_selections:
            owner = require_runtime("Capability")
            try:
                for selection in self.capability_selections:
                    owner.assert_plugin_desired_selection_current(selection)
            except (
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                if refresh_failure is None:
                    raise
                raise refresh_failure(
                    ("product_capability_selection_refresh_requires_restart",)
                ) from exc
        if self.disabled_base is not None:
            owner = require_runtime("disabled-base")
            try:
                owner.assert_plugin_desired_selection_current(self.disabled_base)
                if refresh_failure is not None:
                    current_ids = owner.selected_external_data_plugin_ids()
                    if current_ids != tuple(
                        item.manifest.name for item in self.external
                    ):
                        raise RuntimeError("Product external data selection changed")
                require_current_manifests(owner, self.external)
            except RuntimeError as exc:
                if refresh_failure is None:
                    raise
                raise refresh_failure(
                    ("product_disabled_base_refresh_requires_restart",)
                ) from exc
        if self.base is not None and refresh_failure is not None:
            owner = require_runtime("base")
            for manifests, reason in (
                ((self.base,), "product_selected_base_refresh_requires_restart"),
                (
                    self.capabilities,
                    "product_selected_capability_refresh_requires_restart",
                ),
                (self.external, "product_selected_resource_refresh_requires_restart"),
            ):
                require_current_manifests(owner, manifests, reason, refresh_failure)


SelectionPhase = Literal[
    "worker", "desired", "base", "capability", "selected", "deferred"
]
SelectionError = PackageProductRuntimeActivationError | PackageProductRuntimeReadError
SelectionFailure = Callable[
    [SelectionPhase, SelectionError, PackageProductSelectedPluginManifestV1 | None],
    BaseException,
]


@contextmanager
def translate_selection_failure(
    failure: SelectionFailure,
    phase: SelectionPhase,
    selected: PackageProductSelectedPluginManifestV1 | None = None,
) -> Iterator[None]:
    try:
        yield
    except (
        PackageProductRuntimeActivationError,
        PackageProductRuntimeReadError,
    ) as exc:
        raise failure(phase, exc, selected) from exc


class _PreparedBaseCompilation(Protocol):
    @property
    def plan(self) -> PluginSelectionPlanV2: ...
    @property
    def product_composition(self) -> ProductCompositionCompilation: ...
    @property
    def selected_manifest(self) -> PackageProductSelectedPluginManifestV1: ...
    @property
    def selected_capability_manifests(self) -> tuple[PackageProductSelectedPluginManifestV1, ...]: ...
    @property
    def selected_external_data_manifests(self) -> tuple[PackageProductSelectedPluginManifestV1, ...]: ...


class _PreparedBaseSession(Protocol):
    @property
    def compilation(self) -> _PreparedBaseCompilation: ...
    @property
    def workspace_binding(self) -> CapabilityBundleProviderBinding: ...
    @property
    def session_inputs(self) -> SessionCapabilityCompositionInputs: ...


class _PreparedCapabilitySession(Protocol):
    @property
    def runtime(self) -> PluginRuntimeResolution: ...
    @property
    def session_inputs(self) -> SessionCapabilityCompositionInputs: ...
    @property
    def selection(self) -> PluginSelection: ...
    @property
    def plugin_assembly(self) -> ProductPluginCompositionAssembly: ...


@dataclass(frozen=True, slots=True)
class ProductSessionSelection:
    """Package facts pinned by a Session across construction, execution and receipt creation."""

    runtime: PackageProductRuntimeBindingV1 | None
    desired: tuple[PackageProductPluginDesiredSelectionV1, ...]
    base: PackageProductSelectedPluginManifestV1 | None
    capabilities: tuple[PackageProductSelectedPluginManifestV1, ...]
    external: tuple[PackageProductSelectedPluginManifestV1, ...]
    worker: PackageProductSelectedPluginManifestV1 | None

    @classmethod
    def from_prepared(
        cls,
        *,
        base: _PreparedBaseSession | None,
        capabilities: _PreparedCapabilitySession | None,
        runtime: PackageProductRuntimeBindingV1 | None,
        selected_capabilities: tuple[PackageProductSelectedPluginManifestV1, ...],
        selected_external: tuple[PackageProductSelectedPluginManifestV1, ...],
        desired_selections: tuple[PackageProductPluginDesiredSelectionV1, ...],
        selected_worker: PackageProductSelectedPluginManifestV1 | None,
        workspace_binding: CapabilityBundleProviderBinding | None,
        has_peer_materializer: bool,
        has_catalog_bootstrap: bool,
        get_session_id: Callable[[], str],
        product_id: str,
        product_label: str,
    ) -> ProductSessionSelection:
        """Admit an exact prepared graph and pin its Package Product evidence."""
        if (
            base is not None
            and capabilities is not None
            and (
                capabilities.session_inputs is not base.session_inputs
                or capabilities.selection.plan != base.compilation.plan
                or capabilities.plugin_assembly.product_composition
                is not base.compilation.product_composition
            )
        ):
            raise ValueError(f"{product_label} Product Session composition changed")
        compilation = base.compilation if base is not None else None
        pinned = cls(
            runtime=runtime,
            desired=desired_selections,
            base=compilation.selected_manifest if compilation is not None else None,
            capabilities=(
                compilation.selected_capability_manifests
                if compilation is not None
                else selected_capabilities
            ),
            external=(
                compilation.selected_external_data_manifests
                if compilation is not None
                else selected_external
            ),
            worker=selected_worker,
        )
        if capabilities is not None and (
            base is not None or runtime is not None or selected_capabilities
        ):
            # Managed plugins have no Product Package pins.
            pinned.require_prepared_inventory(
                capabilities.runtime.packages, product_label=product_label
            )
        if base is not None:
            if has_peer_materializer:
                raise ValueError(
                    f"{product_label} base Product cannot use a peer materializer"
                )
            if not has_catalog_bootstrap:
                raise ValueError(f"{product_label} base Product requires Catalog bootstrap")
            if workspace_binding is not base.workspace_binding:
                raise ValueError(f"{product_label} base Product workspace binding changed")
            if runtime is None:
                raise ValueError(f"{product_label} base Product requires runtime binding")
            if (
                base.compilation.plan.context.scope_id
                != f"session:{get_session_id()}"
            ):
                raise ValueError(f"{product_label} base Product Session identity changed")
        if runtime is not None and (
            not isinstance(runtime, PackageProductRuntimeBindingV1)
            or runtime.product_id != product_id
        ):
            raise ValueError(f"{product_label} Product runtime binding is invalid")
        return pinned

    def manifests(
        self, *, include_worker: bool = True
    ) -> tuple[PackageProductSelectedPluginManifestV1, ...]:
        return (
            *((self.base,) if self.base is not None else ()),
            *self.capabilities,
            *self.external,
            *((self.worker,) if include_worker and self.worker is not None else ()),
        )

    def require_current(
        self, failure: SelectionFailure, *, check_desired: bool
    ) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        if self.worker is not None:
            with translate_selection_failure(failure, "worker"):
                runtime.assert_selected_plugin_manifest_current(self.worker)
        if check_desired:
            for selection in self.desired:
                with translate_selection_failure(failure, "desired"):
                    runtime.assert_plugin_desired_selection_current(selection)
        if self.base is not None:
            with translate_selection_failure(failure, "base"):
                runtime.assert_selected_plugin_manifest_current(self.base)
            for manifest in self.capabilities:
                with translate_selection_failure(failure, "capability", manifest):
                    runtime.assert_selected_plugin_manifest_current(manifest)
        else:
            for manifest in (*self.capabilities, *self.external):
                with translate_selection_failure(failure, "selected"):
                    runtime.assert_selected_plugin_manifest_current(manifest)

    def require_prepared_inventory(
        self, packages: tuple[PublishedPluginPackage, ...], *, product_label: str
    ) -> None:
        """Check the composition inventory before a Session can use it."""
        selected = (
            self.manifests(include_worker=False)
            if self.base is not None
            else self.capabilities
        )
        inventory_changed = (
            tuple(package.manifest.name for package in packages)
            != tuple(sorted(item.manifest.name for item in selected))
            if self.base is not None
            else len(packages) != len(selected)
        )
        if inventory_changed or {
            package.manifest.name: package.content_digest for package in packages
        } != {
            item.manifest.name: item.snapshot.root_ref.artifact_digest
            for item in selected
        }:
            raise ValueError(f"{product_label} Product Session packages changed")


def capture_selected_manifests(
    capture: Callable[..., PackageProductSelectedPluginManifestV1],
    plugin_ids: Iterable[str],
    *,
    max_files: int,
    max_total_bytes: int,
) -> tuple[PackageProductSelectedPluginManifestV1, ...]:
    return tuple(
        capture(plugin_id, max_files=max_files, max_total_bytes=max_total_bytes)
        for plugin_id in plugin_ids
    )


def capture_enabled_plugin_recheck(
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    *,
    max_files: int,
    max_total_bytes: int,
    admission_failure: ProductAdmissionFailure,
) -> Callable[[], None]:
    """Retain the exact enabled selection and immutable manifest for rebinding."""
    selection = runtime.capture_plugin_desired_selection_for(plugin_id)
    if selection.desired_state != "installed_enabled":
        raise admission_failure(("product_requested_capability_not_installed",))
    manifest = runtime.capture_selected_plugin_manifest_for(
        plugin_id, max_files=max_files, max_total_bytes=max_total_bytes
    )

    def require_current() -> None:
        runtime.assert_plugin_desired_selection_current(selection)
        runtime.assert_selected_plugin_manifest_current(manifest)

    return require_current
