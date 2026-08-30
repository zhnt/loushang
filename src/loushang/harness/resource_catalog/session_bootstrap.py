"""Private initial-Session bridge into the RCP4 joint Resource generation."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from loushang.harness.capabilities.composition_runtime import (
    StagedResourceCompositionCandidate,
)
from loushang.harness.extensions.context import ExtensionRuntimeBindings
from loushang.harness.extensions.declarations import (
    ExtensionCapabilityDeclarationSnapshot,
)
from loushang.harness.resource_catalog.generation import (
    prepare_first_party_resource_owner_generation,
)
from loushang.harness.resource_catalog.inputs import AdmittedPackageResource
from loushang.harness.resource_catalog.joint_generation import (
    ExtensionGenerationRetirementPort,
    JointResourcePublication,
    PreparedExtensionGenerationPort,
    PreparedExtensionResourceJointGeneration,
    prepare_extension_resource_joint_generation,
)
from loushang.harness.resources._catalog_embedded_source import (
    EmbeddedResourceCollectionHandle,
    EmbeddedResourceDiscoveryBudget,
)
from loushang.harness.resources._catalog_native_source import (
    NativeResourceDiscoveryBudget,
    NativeResourceRootHandle,
)
from loushang.harness.resources._catalog_package_source import (
    PackageResourceDiscoveryBudget,
)
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._catalog_records import (
    ResourceActivationPolicySnapshot,
    ResourceCatalogSnapshot,
    ResourceMergePolicySnapshot,
)
from loushang.harness.resources._catalog_source_contracts import (
    BorrowedResourceSourceGenerationLease,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)
from loushang.harness.resources.types import ExtensionDescriptor, ResourceBundle

InitialSessionResourceCatalogBootstrapState = Literal[
    "unprepared",
    "prepared",
    "published",
    "disposed",
]


class InitialExtensionGenerationHost(Protocol):
    """Narrow Extension owner seam required by initial joint bootstrap."""

    def prepare_generation(
        self,
        extensions: Sequence[ExtensionDescriptor],
    ) -> PreparedExtensionGenerationPort: ...


@dataclass(frozen=True, slots=True)
class InitialSessionResourceCatalogInputs:
    """Owner-prepared exact inputs for one initial Session generation.

    The Product adapter must produce ``base_resource_bundle`` and the opaque
    source handles from the same admitted initial selection.  The Bundle is
    only the defensive input for Extension discovery; Catalog sources remain
    the final selection authority.
    """

    product_id: str
    scope_id: str
    resource_runtime_id: str
    product_policy_revision: str
    root_handles: tuple[NativeResourceRootHandle, ...]
    issued_at: int
    expires_at: int
    now: int
    base_resource_bundle: ResourceBundle
    catalog_generation: int = 1
    package_resources: tuple[AdmittedPackageResource, ...] = ()
    embedded_collections: tuple[EmbeddedResourceCollectionHandle, ...] = ()
    discovery_budget: NativeResourceDiscoveryBudget | None = None
    discovery_deadline_monotonic_ns: int | None = None
    discovery_cancellation_probe: Callable[[], bool] | None = None
    package_discovery_budget: PackageResourceDiscoveryBudget | None = None
    embedded_discovery_budget: EmbeddedResourceDiscoveryBudget | None = None
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES
    merge_policy: ResourceMergePolicySnapshot | None = None
    activation_policy: ResourceActivationPolicySnapshot | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("Resource runtime id", self.resource_runtime_id),
            ("Product policy revision", self.product_policy_revision),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not isinstance(self.base_resource_bundle, ResourceBundle):
            raise TypeError("initial Resource Catalog requires a base ResourceBundle")
        if (
            isinstance(self.catalog_generation, bool)
            or not isinstance(self.catalog_generation, int)
            or self.catalog_generation < 1
        ):
            raise ValueError("Session Resource Catalog generation must be positive")
        if any(
            not isinstance(item, NativeResourceRootHandle) for item in self.root_handles
        ):
            raise TypeError("initial Resource Catalog root handles are invalid")
        if any(
            not isinstance(item, AdmittedPackageResource)
            for item in self.package_resources
        ):
            raise TypeError("initial Resource Catalog package inputs are invalid")
        if any(
            not isinstance(item, EmbeddedResourceCollectionHandle)
            for item in self.embedded_collections
        ):
            raise TypeError("initial Resource Catalog embedded inputs are invalid")


@dataclass(frozen=True, slots=True)
class InitialSessionResourcePublication:
    """Session-visible callback set kept free of private Catalog value types."""

    capture: Callable[[], object]
    commit: Callable[[object, object, ResourceBundle], object]
    restore: Callable[[object], object]

    def __post_init__(self) -> None:
        if not all(
            callable(item) for item in (self.capture, self.commit, self.restore)
        ):
            raise TypeError(
                "initial Session Resource publication callbacks are invalid"
            )


class InitialSessionResourceCatalogBootstrap:
    """Own exact inputs until one joint candidate publishes or rolls back."""

    def __init__(self, inputs: InitialSessionResourceCatalogInputs) -> None:
        if not isinstance(inputs, InitialSessionResourceCatalogInputs):
            raise TypeError("initial Resource Catalog bootstrap inputs are invalid")
        self._inputs = inputs
        self._base_resource_bundle = _defensive_bundle(inputs.base_resource_bundle)
        self._joint: PreparedExtensionResourceJointGeneration | None = None
        self._preflight_candidate: PreparedExtensionGenerationPort | None = None
        self._state: InitialSessionResourceCatalogBootstrapState = "unprepared"
        self._source_inputs_owned = True

    @property
    def product_id(self) -> str:
        return self._inputs.product_id

    @property
    def scope_id(self) -> str:
        return self._inputs.scope_id

    @property
    def catalog_generation(self) -> int:
        return self._inputs.catalog_generation

    @property
    def state(self) -> InitialSessionResourceCatalogBootstrapState:
        return self._state

    async def prepare(
        self,
        *,
        extension_host: InitialExtensionGenerationHost,
        staged_resource_candidate: StagedResourceCompositionCandidate,
        bindings: ExtensionRuntimeBindings,
        extension_declaration_preflight: (
            Callable[[ExtensionCapabilityDeclarationSnapshot], None] | None
        ) = None,
    ) -> None:
        """Prepare one exact root-private Extension/Resource candidate."""

        if self._state != "unprepared":
            raise RuntimeError("initial Resource Catalog bootstrap is already used")
        if not isinstance(
            staged_resource_candidate, StagedResourceCompositionCandidate
        ):
            raise TypeError("initial Resource Catalog requires its staged candidate")
        prepare_generation = getattr(extension_host, "prepare_generation", None)
        if not callable(prepare_generation):
            raise TypeError(
                "initial Resource Catalog requires an Extension generation host"
            )
        try:
            extension_candidate = prepare_generation(
                tuple(self._base_resource_bundle.extensions)
            )
            self._preflight_candidate = extension_candidate
            if extension_declaration_preflight is not None:
                declarations = getattr(
                    extension_candidate,
                    "capability_declarations",
                    None,
                )
                if not isinstance(
                    declarations,
                    ExtensionCapabilityDeclarationSnapshot,
                ):
                    raise TypeError(
                        "staged Extension generation does not expose capability "
                        "declarations"
                    )
                preflight_result = extension_declaration_preflight(declarations)
                if inspect.isawaitable(preflight_result):
                    if inspect.iscoroutine(preflight_result):
                        preflight_result.close()
                    raise TypeError(
                        "Extension declaration preflight must be synchronous"
                    )
                if preflight_result is not None:
                    raise TypeError(
                        "Extension declaration preflight must return None"
                    )
            async def prepare_resource(
                source_lease: BorrowedResourceSourceGenerationLease,
            ) -> None:
                inputs = self._inputs
                await prepare_first_party_resource_owner_generation(
                    staged_candidate=staged_resource_candidate,
                    product_id=inputs.product_id,
                    scope_id=inputs.scope_id,
                    runtime_id=inputs.resource_runtime_id,
                    product_policy_revision=inputs.product_policy_revision,
                    catalog_generation=inputs.catalog_generation,
                    root_handles=inputs.root_handles,
                    package_resources=inputs.package_resources,
                    embedded_collections=inputs.embedded_collections,
                    issued_at=inputs.issued_at,
                    expires_at=inputs.expires_at,
                    now=inputs.now,
                    discovery_budget=inputs.discovery_budget,
                    discovery_deadline_monotonic_ns=(
                        inputs.discovery_deadline_monotonic_ns
                    ),
                    discovery_cancellation_probe=(inputs.discovery_cancellation_probe),
                    package_discovery_budget=inputs.package_discovery_budget,
                    embedded_discovery_budget=inputs.embedded_discovery_budget,
                    context_file_names=inputs.context_file_names,
                    merge_policy=inputs.merge_policy,
                    activation_policy=inputs.activation_policy,
                    extension_source_lease=source_lease,
                    projection_cwd=Path(self._base_resource_bundle.cwd),
                )

            self._joint = await prepare_extension_resource_joint_generation(
                extension_candidate=extension_candidate,
                staged_resource_candidate=staged_resource_candidate,
                base_resource_bundle=self._base_resource_bundle,
                bindings=bindings,
                product_id=self._inputs.product_id,
                prepare_resource_generation=prepare_resource,
            )
            # The joint now owns rollback custody.  Keep the preflight handle
            # until every await needed to create that joint has succeeded so a
            # failed Extension Resource freeze remains retryable by abort().
            self._preflight_candidate = None
        except BaseException as preparation_error:
            preflight_candidate = self._preflight_candidate
            if preflight_candidate is not None:
                try:
                    await _rollback_preflight_candidate(preflight_candidate)
                except BaseException as cleanup_error:
                    preparation_error.add_note(
                        "Extension declaration preflight rollback also failed: "
                        f"{cleanup_error!r}"
                    )
                else:
                    self._preflight_candidate = None
            try:
                self._close_source_inputs()
            except BaseException as cleanup_error:
                preparation_error.add_note(
                    "Initial Resource source-input cleanup also failed: "
                    f"{cleanup_error!r}"
                )
            else:
                if self._preflight_candidate is not None:
                    raise
                self._state = "disposed"
            raise
        self._source_inputs_owned = False
        self._state = "prepared"

    def publish(
        self,
        publication: InitialSessionResourcePublication,
    ) -> ExtensionGenerationRetirementPort:
        """Publish the joint generation through one synchronous callback."""

        if self._state != "prepared" or self._joint is None:
            raise RuntimeError("initial Resource Catalog bootstrap is not prepared")
        if not isinstance(publication, InitialSessionResourcePublication):
            raise TypeError("initial Resource Catalog publication port is invalid")

        def commit(
            catalog: object,
            projection: ResourceCatalogProjection,
        ) -> object:
            if not isinstance(catalog, ResourceCatalogSnapshot):
                raise TypeError("initial Resource Catalog snapshot is invalid")
            bundle = projection.to_compatibility_bundle()
            if not isinstance(bundle, ResourceBundle):
                raise TypeError(
                    "initial Resource Catalog projection returned no Bundle"
                )
            return publication.commit(catalog, projection, bundle)

        retirement = self._joint.publish(
            JointResourcePublication(
                capture=publication.capture,
                commit=commit,
                restore=publication.restore,
            )
        )
        self._state = "published"
        return retirement

    async def abort(
        self,
        *,
        dispose_graph: Callable[[], Awaitable[tuple[str, ...]]] | None = None,
    ) -> None:
        """Release an unpublished root/Graph candidate or unused source inputs."""

        if self._state == "published":
            return
        if self._state == "disposed":
            return
        joint = self._joint
        if joint is not None:
            await joint.rollback(dispose_graph=dispose_graph)
            self._state = "disposed"
            return
        preflight_candidate = self._preflight_candidate
        if preflight_candidate is not None:
            await _rollback_preflight_candidate(preflight_candidate)
            self._preflight_candidate = None
        self.close_unprepared()

    def close_unprepared(self) -> None:
        """Synchronously release inputs before Session construction transfers them."""

        if self._state == "disposed":
            return
        if self._state != "unprepared":
            raise RuntimeError(
                "initial Resource Catalog bootstrap is already prepared"
            )
        if self._preflight_candidate is not None:
            raise RuntimeError(
                "initial Resource Catalog Extension candidate cleanup is pending"
            )
        self._close_source_inputs()
        self._state = "disposed"

    def _close_source_inputs(self) -> None:
        if not self._source_inputs_owned:
            return
        errors: list[BaseException] = []
        for resource in self._inputs.package_resources:
            try:
                resource.close()
            except BaseException as exc:
                errors.append(exc)
        for collection in self._inputs.embedded_collections:
            try:
                collection.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            primary = errors[0]
            for error in errors[1:]:
                primary.add_note(
                    f"Additional initial Resource input cleanup failure: {error!r}"
                )
            raise primary
        self._source_inputs_owned = False


def _defensive_bundle(bundle: ResourceBundle) -> ResourceBundle:
    return ResourceBundle(
        cwd=Path(bundle.cwd),
        agents_path=bundle.agents_path,
        agents_md=bundle.agents_md,
        prompt_fragments=list(bundle.prompt_fragments),
        prompt_descriptors=list(bundle.prompt_descriptors),
        skills=list(bundle.skills),
        extensions=list(bundle.extensions),
        prompts=list(bundle.prompts),
        themes=list(bundle.themes),
        diagnostics=list(bundle.diagnostics),
    )


async def _rollback_preflight_candidate(
    candidate: PreparedExtensionGenerationPort,
) -> None:
    task = asyncio.create_task(candidate.rollback())
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                reports = task.result()
                break
            cancellation = exc
    else:
        reports = task.result()
    if any(report.has_failures for report in reports):
        raise RuntimeError(
            "Extension declaration preflight retirement remains pending"
        )
    if cancellation is not None:
        raise cancellation


__all__ = [
    "ExtensionGenerationRetirementPort",
    "InitialExtensionGenerationHost",
    "InitialSessionResourceCatalogBootstrap",
    "InitialSessionResourceCatalogBootstrapState",
    "InitialSessionResourceCatalogInputs",
    "InitialSessionResourcePublication",
    "ResourceCatalogProjection",
]
