"""Shared service preparation and bootstrap result contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from loushang.agent.types import ThinkingLevel
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.ai.model.selection import ModelSelection
from loushang.harness.bootstrap import ResourceBootstrapRuntime
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticRecord
from loushang.harness.model_catalog import ModelCatalog
from loushang.harness.session.bootstrap_configuration import ExtensionFlagValues
from loushang.harness.workspace.exec import ExecService

SettingsT = TypeVar("SettingsT")
ModelRegistryT = TypeVar("ModelRegistryT")
ResourceLoaderT = TypeVar("ResourceLoaderT")
DiagnosticsT = TypeVar("DiagnosticsT")
ExecServiceT = TypeVar("ExecServiceT")
ServicesT = TypeVar("ServicesT")
BundleT = TypeVar("BundleT")
ExtensionT = TypeVar("ExtensionT")
DiagnosticRecordT = TypeVar("DiagnosticRecordT")
DiagnosticDraftT = TypeVar("DiagnosticDraftT")
SessionT = TypeVar("SessionT")
AuditT = TypeVar("AuditT")
SessionManagerT = TypeVar("SessionManagerT")
RuntimeT = TypeVar("RuntimeT")


@dataclass(frozen=True)
class BootstrapServices(
    Generic[SettingsT, ModelRegistryT, ResourceLoaderT, DiagnosticsT, ExecServiceT]
):
    """Product service handles shared by a session bootstrap."""

    settings_manager: SettingsT
    model_registry: ModelRegistryT
    resource_loader: ResourceLoaderT
    diagnostics_service: DiagnosticsT
    exec_service: ExecServiceT | None = None


def create_standard_agent_bootstrap_services(
    *,
    resource_loader_factory: Callable[[], ResourceLoaderT],
    ai_model_registry: AiModelRegistry | None = None,
    resource_loader: ResourceLoaderT | None = None,
    settings_manager: SettingsManager | None = None,
    diagnostics_service: DiagnosticsService | None = None,
    exec_service: ExecService | None = None,
    default_model: ModelSelection | None = None,
    thinking_level: ThinkingLevel = "off",
    system_prompt: str = "",
) -> BootstrapServices[
    SettingsManager,
    ModelCatalog,
    ResourceLoaderT,
    DiagnosticsService,
    ExecService,
]:
    """Construct standard Agent services with Product resource loading injected."""

    resolved_settings_manager = settings_manager or SettingsManager(
        ControlConfig(
            default_model=default_model,
            thinking_level=thinking_level,
            system_prompt=system_prompt,
        )
    )
    return BootstrapServices(
        settings_manager=resolved_settings_manager,
        model_registry=ModelCatalog(ai_registry=ai_model_registry),
        resource_loader=resource_loader or resource_loader_factory(),
        diagnostics_service=diagnostics_service or DiagnosticsService(),
        exec_service=exec_service or ExecService(),
    )


@dataclass(frozen=True)
class AgentSessionServices(Generic[ServicesT, BundleT, ExtensionT, DiagnosticRecordT]):
    """Cwd-bound services and results of the shared resource bootstrap."""

    cwd: str
    services: ServicesT
    resource_bundle: BundleT | None = None
    extension_runner: ExtensionT | None = None
    diagnostics: tuple[DiagnosticRecordT, ...] = ()

    @property
    def settings_manager(self) -> object:
        return getattr(self.services, "settings_manager")

    @property
    def model_registry(self) -> object:
        return getattr(self.services, "model_registry")

    @property
    def resource_loader(self) -> object:
        return getattr(self.services, "resource_loader")

    @property
    def diagnostics_service(self) -> object:
        return getattr(self.services, "diagnostics_service")

    @property
    def exec_service(self) -> object:
        return getattr(self.services, "exec_service")


def prepare_agent_session_services(
    *,
    cwd: str | Path,
    create_services: Callable[[Path], ServicesT],
    build_resource_bootstrap: Callable[
        [ServicesT],
        ResourceBootstrapRuntime[
            ResourceLoaderT,
            BundleT,
            ExtensionT,
            DiagnosticDraftT,
            DiagnosticRecordT,
        ],
    ],
    get_resource_loader: Callable[[ServicesT], ResourceLoaderT],
    services: ServicesT | None = None,
    service_overrides: Mapping[str, object | None] | None = None,
    resource_loader_options: Mapping[str, object] | None = None,
    configure_resource_loader: (
        Callable[[ResourceLoaderT, Mapping[str, object]], None] | None
    ) = None,
    extension_flag_values: ExtensionFlagValues | None = None,
) -> AgentSessionServices[ServicesT, BundleT, ExtensionT, DiagnosticRecordT]:
    """Prepare cwd-bound session services with the existing resource runtime."""

    resolved_cwd = Path(cwd).expanduser().resolve(strict=False)
    if services is None:
        resolved_services = create_services(resolved_cwd)
    else:
        overrides = service_overrides or {}
        if any(value is not None for value in overrides.values()):
            raise ValueError(
                "service components cannot be overridden when services is provided"
            )
        resolved_services = services

    loader = get_resource_loader(resolved_services)
    if resource_loader_options:
        if configure_resource_loader is None:
            raise ValueError(
                "resource loader options require a configure_resource_loader port"
            )
        configure_resource_loader(loader, resource_loader_options)

    prepared = build_resource_bootstrap(resolved_services).prepare(
        loader=loader,
        cwd=resolved_cwd,
        extension_flags=extension_flag_values,
    )
    return AgentSessionServices(
        cwd=str(resolved_cwd),
        services=resolved_services,
        resource_bundle=prepared.resource_bundle,
        extension_runner=prepared.extension_runtime,
        diagnostics=prepared.diagnostics,
    )


def build_agent_product_session_runtime(
    *,
    session_dir: str | Path,
    runtime_factory: Callable[..., RuntimeT],
    fixed_services: ServicesT,
    build_session: Callable[
        [SessionManagerT, ServicesT, object | None],
        SessionT,
    ],
    session_cwd: Callable[[SessionManagerT], str],
    services_factory: Callable[[str], ServicesT] | None = None,
    persist: bool = True,
    diagnostics_service: object | None = None,
    on_non_persistent_session: Callable[[SessionT], None] | None = None,
) -> RuntimeT:
    """Bind cwd-aware services and a Product session builder to one runtime."""

    def session_factory(
        session_manager: SessionManagerT,
        *,
        session_start_event: object | None = None,
    ) -> SessionT:
        session_services = (
            services_factory(session_cwd(session_manager))
            if services_factory is not None
            else fixed_services
        )
        session = build_session(
            session_manager,
            session_services,
            session_start_event,
        )
        if not persist and on_non_persistent_session is not None:
            on_non_persistent_session(session)
        return session

    return runtime_factory(
        session_dir=Path(session_dir),
        session_factory=session_factory,
        persist=persist,
        diagnostics_service=diagnostics_service,
    )


@dataclass(frozen=True)
class CreateAgentSessionResult(Generic[SessionT, BundleT, DiagnosticRecordT, AuditT]):
    """Product session plus the shared bootstrap outputs."""

    session: SessionT
    resource_bundle: BundleT | None
    diagnostics: tuple[DiagnosticRecordT, ...]
    cwd_bound_services_audit: AuditT | None = None


def build_standard_agent_session_result(
    session: SessionT,
    *,
    resource_bundle: BundleT | None,
    diagnostics_service: DiagnosticsService,
    session_id: str,
    cwd_bound_services_audit: AuditT | None = None,
) -> CreateAgentSessionResult[SessionT, BundleT, DiagnosticRecord, AuditT]:
    """Collect standard bootstrap outputs for a Product-created session."""

    return CreateAgentSessionResult(
        session=session,
        resource_bundle=resource_bundle,
        diagnostics=tuple(diagnostics_service.get_diagnostics(session_id=session_id)),
        cwd_bound_services_audit=cwd_bound_services_audit,
    )


__all__ = [
    "AgentSessionServices",
    "BootstrapServices",
    "CreateAgentSessionResult",
    "build_agent_product_session_runtime",
    "build_standard_agent_session_result",
    "create_standard_agent_bootstrap_services",
    "prepare_agent_session_services",
]
