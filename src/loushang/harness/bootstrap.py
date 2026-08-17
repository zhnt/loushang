"""Product-neutral resource bootstrap orchestration.

Products provide resource loaders, extension runtimes, and diagnostic
normalizers.  Harness owns the ordering and the invariant that extension
resource discovery happens after flags have been applied.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from loushang.harness.capabilities.packs import (
    CapabilityPack,
    CapabilityPackComposer,
)
from loushang.harness.config.activation import (
    ConfigActivationReport,
    ConfigActivationRuntime,
    ConfigActivationStep,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import (
    DiagnosticDraft,
    DiagnosticPhase,
    DiagnosticRecord,
    DiagnosticSource,
)
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.tools.contribution import (
    ToolContribution,
    ToolResolutionResult,
    resolve_tool_contributions,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

LoaderT = TypeVar("LoaderT")
BundleT = TypeVar("BundleT")
ExtensionT = TypeVar("ExtensionT")
StandardExtensionT = TypeVar("StandardExtensionT", bound="StandardExtensionRuntime")
DiagnosticT = TypeVar("DiagnosticT")
DiagnosticInputT = TypeVar("DiagnosticInputT")
DiagnosticOutputT = TypeVar("DiagnosticOutputT")
ActivationConfigT = TypeVar("ActivationConfigT")
ActivationContextT = TypeVar("ActivationContextT")
FlagValues = Mapping[str, bool | str] | None
ExtensionToolDiagnosticFactory = Callable[[str, str], DiagnosticT]
BundleDiagnosticMerger = Callable[[BundleT, Sequence[DiagnosticT]], BundleT]
ExtensionToolResolver = Callable[..., ToolResolutionResult]
BundleTransform = Callable[[BundleT], BundleT]


class StandardResourceLoader(Protocol):
    def discover_resources(self, cwd: Path) -> ResourceBundle: ...


class StandardExtensionRuntime(Protocol):
    def apply_flag_values(
        self,
        values: FlagValues,
    ) -> Sequence[DiagnosticDraft]: ...

    def discover_resources(self, bundle: ResourceBundle) -> ResourceBundle: ...

    def get_diagnostics(self) -> Sequence[DiagnosticDraft]: ...


@dataclass(frozen=True)
class ResourceBootstrapPorts(
    Generic[LoaderT, BundleT, ExtensionT, DiagnosticInputT, DiagnosticOutputT]
):
    """Callbacks that bind Product resource and extension semantics."""

    discover_resources: Callable[[LoaderT, Path], BundleT]
    create_extension_runtime: Callable[[BundleT], ExtensionT]
    apply_extension_flags: Callable[
        [ExtensionT, FlagValues],
        Sequence[DiagnosticInputT],
    ]
    rediscover_resources: Callable[[ExtensionT, BundleT], BundleT]
    bundle_diagnostics: Callable[[BundleT], Sequence[DiagnosticInputT]]
    extension_diagnostics: Callable[[ExtensionT], Sequence[DiagnosticInputT]]
    normalize_diagnostic: Callable[
        [DiagnosticInputT, DiagnosticPhase, DiagnosticSource],
        DiagnosticOutputT,
    ]


@dataclass(frozen=True)
class ResourceBootstrapResult(Generic[BundleT, ExtensionT, DiagnosticOutputT]):
    """Resources, extensions, and normalized diagnostics for one cwd."""

    resource_bundle: BundleT
    extension_runtime: ExtensionT
    diagnostics: tuple[DiagnosticOutputT, ...]


@dataclass(frozen=True)
class ResourceDiscoveryResult(Generic[BundleT, DiagnosticOutputT]):
    """One resource discovery phase and its normalized diagnostics."""

    resource_bundle: BundleT
    diagnostics: tuple[DiagnosticOutputT, ...]


@dataclass(frozen=True)
class ExtensionResourceActivationResult(
    Generic[BundleT, ExtensionT, DiagnosticOutputT]
):
    """Extension activation over an already discovered resource bundle."""

    resource_bundle: BundleT
    extension_runtime: ExtensionT
    flag_diagnostics: tuple[DiagnosticOutputT, ...]
    extension_diagnostics: tuple[DiagnosticOutputT, ...]


class ResourceBootstrapRuntime(
    Generic[LoaderT, BundleT, ExtensionT, DiagnosticInputT, DiagnosticOutputT]
):
    """Run the shared resource/extension bootstrap transaction."""

    def __init__(
        self,
        ports: ResourceBootstrapPorts[
            LoaderT,
            BundleT,
            ExtensionT,
            DiagnosticInputT,
            DiagnosticOutputT,
        ],
    ) -> None:
        self._ports = ports

    def prepare(
        self,
        *,
        loader: LoaderT,
        cwd: str | Path,
        extension_flags: FlagValues = None,
        transform_bundle: BundleTransform[BundleT] | None = None,
    ) -> ResourceBootstrapResult[BundleT, ExtensionT, DiagnosticOutputT]:
        discovery = self.discover(
            loader=loader,
            cwd=cwd,
            transform_bundle=transform_bundle,
        )
        activation = self.activate_extensions(
            resource_bundle=discovery.resource_bundle,
            extension_flags=extension_flags,
            transform_bundle=transform_bundle,
        )
        return ResourceBootstrapResult(
            resource_bundle=activation.resource_bundle,
            extension_runtime=activation.extension_runtime,
            diagnostics=(
                *discovery.diagnostics,
                *activation.extension_diagnostics,
                *activation.flag_diagnostics,
            ),
        )

    def discover(
        self,
        *,
        loader: LoaderT,
        cwd: str | Path,
        transform_bundle: BundleTransform[BundleT] | None = None,
    ) -> ResourceDiscoveryResult[BundleT, DiagnosticOutputT]:
        """Discover Product resources without activating extensions."""

        resolved_cwd = Path(cwd).expanduser().resolve(strict=False)
        bundle = self._ports.discover_resources(loader, resolved_cwd)
        loader_diagnostics = tuple(self._ports.bundle_diagnostics(bundle))
        if transform_bundle is not None:
            bundle = transform_bundle(bundle)
        diagnostics = tuple(
            self._ports.normalize_diagnostic(
                diagnostic,
                "resource_loading",
                "loader",
            )
            for diagnostic in loader_diagnostics
        )
        return ResourceDiscoveryResult(
            resource_bundle=bundle,
            diagnostics=diagnostics,
        )

    def activate_extensions(
        self,
        *,
        resource_bundle: BundleT,
        extension_flags: FlagValues = None,
        transform_bundle: BundleTransform[BundleT] | None = None,
    ) -> ExtensionResourceActivationResult[BundleT, ExtensionT, DiagnosticOutputT]:
        """Activate extensions and rediscover their resource contributions."""

        extension_runtime = self._ports.create_extension_runtime(resource_bundle)
        flag_diagnostics = tuple(
            self._ports.apply_extension_flags(extension_runtime, extension_flags)
        )
        bundle = self._ports.rediscover_resources(
            extension_runtime,
            resource_bundle,
        )
        if transform_bundle is not None:
            bundle = transform_bundle(bundle)
        normalized_flags = tuple(
            self._ports.normalize_diagnostic(
                diagnostic,
                "resource_loading",
                "bootstrap",
            )
            for diagnostic in flag_diagnostics
        )
        normalized_extensions = tuple(
            self._ports.normalize_diagnostic(
                diagnostic,
                "resource_loading",
                "extensions",
            )
            for diagnostic in self._ports.extension_diagnostics(extension_runtime)
        )
        return ExtensionResourceActivationResult(
            resource_bundle=bundle,
            extension_runtime=extension_runtime,
            flag_diagnostics=normalized_flags,
            extension_diagnostics=normalized_extensions,
        )


def create_standard_resource_bootstrap_runtime(
    *,
    create_extension_runtime: Callable[[ResourceBundle], StandardExtensionT],
    diagnostics_service: DiagnosticsService,
    session_id: str | None = None,
) -> ResourceBootstrapRuntime[
    StandardResourceLoader,
    ResourceBundle,
    StandardExtensionT,
    DiagnosticDraft,
    DiagnosticRecord,
]:
    """Bind standard Harness resource, extension, and diagnostic components."""

    return ResourceBootstrapRuntime(
        ResourceBootstrapPorts(
            discover_resources=lambda loader, cwd: loader.discover_resources(cwd),
            create_extension_runtime=create_extension_runtime,
            apply_extension_flags=lambda runtime, values: runtime.apply_flag_values(
                values
            ),
            rediscover_resources=lambda runtime, bundle: runtime.discover_resources(
                bundle
            ),
            bundle_diagnostics=lambda bundle: tuple(bundle.diagnostics),
            extension_diagnostics=lambda runtime: runtime.get_diagnostics(),
            normalize_diagnostic=lambda diagnostic, phase, source: (
                diagnostics_service.normalize_diagnostic(
                    diagnostic,
                    phase=phase,
                    source=source,
                    session_id=session_id,
                )
            ),
        )
    )


@dataclass(frozen=True)
class BootstrapActivationPlan(Generic[ActivationConfigT, ActivationContextT]):
    """Product-provided steps for one ordered bootstrap transaction."""

    steps: tuple[ConfigActivationStep[ActivationConfigT, ActivationContextT], ...]
    rollback_on_start_failure: bool = True


@dataclass(frozen=True)
class BootstrapActivationResult(Generic[ActivationContextT]):
    """Activation context together with its structured execution report."""

    context: ActivationContextT
    report: ConfigActivationReport


class BootstrapActivationRuntime(Generic[ActivationConfigT, ActivationContextT]):
    """Run a product bootstrap plan as one ordered activation transaction."""

    def __init__(
        self,
        plan: BootstrapActivationPlan[ActivationConfigT, ActivationContextT],
    ) -> None:
        self._runtime = ConfigActivationRuntime(
            plan.steps,
            rollback_on_start_failure=plan.rollback_on_start_failure,
        )

    def activate(
        self,
        config: ActivationConfigT,
        context: ActivationContextT,
    ) -> BootstrapActivationResult[ActivationContextT]:
        report = self._runtime.start(config, context)
        return BootstrapActivationResult(context=context, report=report)

    @property
    def ordered_step_names(self) -> tuple[str, ...]:
        return self._runtime.ordered_names


def project_extension_tool_contributions(
    extension_runtime: ExtensionT,
    *,
    list_tool_definitions: Callable[[ExtensionT], Sequence[ToolDefinition]],
    get_tool_source_info: Callable[[ExtensionT, str], object | None],
) -> tuple[ToolContribution, ...]:
    """Project extension-provided tools into the shared contribution shape."""

    return tuple(
        ToolContribution(
            definition,
            source_info=get_tool_source_info(extension_runtime, definition.name),
            metadata={
                "kind": "extension_tool",
                "extension_tool": definition.name,
            },
        )
        for definition in list_tool_definitions(extension_runtime)
    )


def register_extension_tools(
    *,
    extension_runtime: ExtensionT,
    resource_bundle: BundleT,
    tool_registry: WorkspaceToolRegistry | None,
    list_tool_definitions: Callable[[ExtensionT], Sequence[ToolDefinition]],
    get_tool_source_info: Callable[[ExtensionT, str], object | None],
    merge_diagnostics: BundleDiagnosticMerger,
    make_conflict_diagnostic: ExtensionToolDiagnosticFactory,
    pack_composer: CapabilityPackComposer | None = None,
    resolve_contributions: ExtensionToolResolver = resolve_tool_contributions,
    product_pack_id: str = "product.tools",
    extension_pack_id: str = "extension.tools",
) -> tuple[BundleT, WorkspaceToolRegistry | None, list[DiagnosticT]]:
    """Merge extension tools into a Product registry without Product imports.

    The registry and extension runtime are Product bindings. Harness owns the
    deterministic contribution composition, conflict filtering, and source
    projection; the Product decides how diagnostics are represented and how a
    resource bundle stores them.
    """

    extension_tools = tuple(list_tool_definitions(extension_runtime))
    if not extension_tools:
        return resource_bundle, tool_registry, []

    resolved_registry = tool_registry or WorkspaceToolRegistry()
    extension_contributions = project_extension_tool_contributions(
        extension_runtime,
        list_tool_definitions=list_tool_definitions,
        get_tool_source_info=get_tool_source_info,
    )
    composer = pack_composer or CapabilityPackComposer()
    resolution = resolve_contributions(
        composer.compose(
            (
                CapabilityPack(
                    pack_id=product_pack_id,
                    source="product",
                    priority=100,
                    items=resolved_registry.list_contributions(),
                ),
                CapabilityPack(
                    pack_id=extension_pack_id,
                    source="extension",
                    items=extension_contributions,
                ),
            )
        ).items,
        fail_on_errors=False,
    )
    conflict_names = {
        name
        for diagnostic in resolution.diagnostics
        if diagnostic.code == "duplicate_tool"
        for name in (diagnostic.details.get("name"),)
        if isinstance(name, str)
    }
    diagnostics: list[DiagnosticT] = [
        make_conflict_diagnostic(
            name,
            f"Extension tool '{name}' conflicts with an existing registry tool.",
        )
        for name in sorted(conflict_names)
    ]
    for contribution in resolution.contributions:
        if contribution.metadata.get("kind") != "extension_tool":
            continue
        if contribution.definition.name in conflict_names:
            continue
        resolved_registry.register_tool(
            contribution.definition,
            source_info=contribution.source_info,
        )
    if diagnostics:
        resource_bundle = merge_diagnostics(resource_bundle, diagnostics)
    return resource_bundle, resolved_registry, diagnostics


def register_resource_extension_tools(
    *,
    extension_runtime: ExtensionT,
    resource_bundle: ResourceBundle,
    tool_registry: WorkspaceToolRegistry | None,
    list_tool_definitions: Callable[[ExtensionT], Sequence[ToolDefinition]],
    get_tool_source_info: Callable[[ExtensionT, str], object | None],
    pack_composer: CapabilityPackComposer | None = None,
    product_pack_id: str = "product.tools",
    extension_pack_id: str = "extension.tools",
    resolve_contributions: ExtensionToolResolver = resolve_tool_contributions,
) -> tuple[ResourceBundle, WorkspaceToolRegistry | None, list[DiagnosticDraft]]:
    """Bind the standard resource bundle and diagnostic types to tool registration."""

    return register_extension_tools(
        extension_runtime=extension_runtime,
        resource_bundle=resource_bundle,
        tool_registry=tool_registry,
        list_tool_definitions=list_tool_definitions,
        get_tool_source_info=get_tool_source_info,
        merge_diagnostics=lambda bundle, diagnostics: bundle.merge(
            diagnostics=diagnostics
        ),
        make_conflict_diagnostic=lambda name, message: resource_diagnostic(
            code="extension_tool_conflict",
            message=message,
        ),
        pack_composer=pack_composer,
        resolve_contributions=resolve_contributions,
        product_pack_id=product_pack_id,
        extension_pack_id=extension_pack_id,
    )


__all__ = [
    "ExtensionResourceActivationResult",
    "ResourceDiscoveryResult",
    "ResourceBootstrapPorts",
    "ResourceBootstrapResult",
    "ResourceBootstrapRuntime",
    "StandardExtensionRuntime",
    "StandardResourceLoader",
    "create_standard_resource_bootstrap_runtime",
    "BootstrapActivationPlan",
    "BootstrapActivationResult",
    "BootstrapActivationRuntime",
    "project_extension_tool_contributions",
    "register_extension_tools",
    "register_resource_extension_tools",
]
