"""Standard Agent session configuration over shared resource services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from loushang.harness.bootstrap import (
    StandardExtensionRuntime,
    create_standard_resource_bootstrap_runtime,
)
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.diagnostics.service import (
    DiagnosticsService,
    run_standard_startup_checks,
)
from loushang.harness.diagnostics.types import StartupCheckResult
from loushang.harness.model_catalog import ModelCatalog
from loushang.harness.resources.activation import SkillActivationRuntime
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.catalog_diagnostics import (
    record_package_lockfile_diagnostics,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.roots import (
    configure_resource_loader_roots,
)
from loushang.harness.resources.packages.source_resolver import (
    PackageSourceResolver,
)
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.session.bootstrap_activation import (
    StandardAgentSessionActivationEffects,
    activate_standard_agent_session_configuration,
)
from loushang.harness.session.cwd_audit import (
    CwdBoundServicesAudit,
    audit_cwd_bound_services,
    project_root_from_settings_base,
    record_cwd_bound_services_audit,
)

StandardExtensionT = TypeVar("StandardExtensionT", bound=StandardExtensionRuntime)

ExtensionFlagValues = Mapping[str, bool | str]
SourceIdentityCheck = Callable[[str], StartupCheckResult]


@dataclass(frozen=True, slots=True)
class StandardAgentSessionConfigurationRequest(Generic[StandardExtensionT]):
    """Concrete shared services for one standard Agent session activation."""

    settings: ControlConfig
    settings_manager: SettingsManager
    model_registry: ModelCatalog
    resource_loader: ResourceLoader
    diagnostics_service: DiagnosticsService
    package_materializer: PackageMaterializer
    skill_activation_runtime: SkillActivationRuntime
    session_id: str
    cwd: str
    create_extension_runtime: Callable[[ResourceBundle], StandardExtensionT]
    source_identity_check: SourceIdentityCheck
    extension_flag_values: ExtensionFlagValues | None = None


@dataclass(frozen=True, slots=True)
class StandardAgentSessionConfigurationResult(Generic[StandardExtensionT]):
    resource_bundle: ResourceBundle
    extension_runtime: StandardExtensionT
    cwd_bound_services_audit: CwdBoundServicesAudit


@dataclass
class _StandardAgentSessionConfigurationContext(Generic[StandardExtensionT]):
    request: StandardAgentSessionConfigurationRequest[StandardExtensionT]
    resource_bundle: ResourceBundle | None = None
    extension_runtime: StandardExtensionT | None = None
    cwd_bound_services_audit: CwdBoundServicesAudit | None = None


class StandardAgentSessionConfigurationRuntime(Generic[StandardExtensionT]):
    """Bind standard Harness resource services to the activation graph."""

    def configure(
        self,
        request: StandardAgentSessionConfigurationRequest[StandardExtensionT],
    ) -> StandardAgentSessionConfigurationResult[StandardExtensionT]:
        context = _StandardAgentSessionConfigurationContext[StandardExtensionT](
            request=request
        )
        activate_standard_agent_session_configuration(
            request.settings,
            context,
            effects=StandardAgentSessionActivationEffects(
                startup_checks=self._startup_checks,
                package_sources=self._package_sources,
                resource_roots=self._resource_roots,
                resources=self._resources,
                extensions=self._extensions,
                cwd_audit=self._cwd_audit,
                model_registry=self._model_registry,
            ),
        )
        if context.resource_bundle is None:
            raise RuntimeError("Session resources have not been configured.")
        if context.extension_runtime is None:
            raise RuntimeError("Session extensions have not been configured.")
        if context.cwd_bound_services_audit is None:
            raise RuntimeError("Session cwd-bound services have not been audited.")
        return StandardAgentSessionConfigurationResult(
            resource_bundle=context.resource_bundle,
            extension_runtime=context.extension_runtime,
            cwd_bound_services_audit=context.cwd_bound_services_audit,
        )

    def _startup_checks(
        self,
        selection: object,
        context: _StandardAgentSessionConfigurationContext[StandardExtensionT],
    ) -> None:
        del selection
        request = context.request
        record_package_lockfile_diagnostics(
            request.package_materializer.get_lockfile_diagnostics(),
            diagnostics_service=request.diagnostics_service,
            session_id=request.session_id,
        )
        run_standard_startup_checks(
            request.diagnostics_service,
            cwd=request.cwd,
            package_roots=request.settings.package_roots,
            additional_checks=(lambda: request.source_identity_check(request.cwd),),
            session_id=request.session_id,
        )

    def _package_sources(
        self,
        selection: object,
        context: _StandardAgentSessionConfigurationContext[StandardExtensionT],
    ) -> None:
        del selection
        request = context.request
        PackageSourceResolver(
            settings_manager=request.settings_manager,
            materializer=request.package_materializer,
            diagnostics_service=request.diagnostics_service,
            session_id=request.session_id,
        ).resolve_configured_sources_sync(
            missing_source_action="install",
            phase="startup",
        )

    def _resource_roots(
        self,
        selection: object,
        context: _StandardAgentSessionConfigurationContext[StandardExtensionT],
    ) -> None:
        del selection
        request = context.request
        configure_resource_loader_roots(
            resource_loader=request.resource_loader,
            settings_manager=request.settings_manager,
            materializer=request.package_materializer,
            diagnostics_service=request.diagnostics_service,
            session_id=request.session_id,
        )

    def _resources(
        self,
        selection: object,
        context: _StandardAgentSessionConfigurationContext[StandardExtensionT],
    ) -> None:
        del selection
        request = context.request
        result = create_standard_resource_bootstrap_runtime(
            create_extension_runtime=request.create_extension_runtime,
            diagnostics_service=request.diagnostics_service,
            session_id=request.session_id,
        ).discover(
            loader=request.resource_loader,
            cwd=request.cwd,
            transform_bundle=lambda bundle: request.skill_activation_runtime.apply(
                bundle,
                request.settings.disabled_skills,
            ),
        )
        request.diagnostics_service.record_many(result.diagnostics)
        context.resource_bundle = result.resource_bundle

    def _extensions(
        self,
        selection: object,
        context: _StandardAgentSessionConfigurationContext[StandardExtensionT],
    ) -> None:
        del selection
        request = context.request
        if context.resource_bundle is None:
            raise RuntimeError("Session resources have not been configured.")
        result = create_standard_resource_bootstrap_runtime(
            create_extension_runtime=request.create_extension_runtime,
            diagnostics_service=request.diagnostics_service,
            session_id=request.session_id,
        ).activate_extensions(
            resource_bundle=context.resource_bundle,
            extension_flags=request.extension_flag_values,
            transform_bundle=lambda bundle: request.skill_activation_runtime.apply(
                bundle,
                request.settings.disabled_skills,
            ),
        )
        request.diagnostics_service.record_many(result.flag_diagnostics)
        request.diagnostics_service.record_many(result.extension_diagnostics)
        context.resource_bundle = result.resource_bundle
        context.extension_runtime = result.extension_runtime

    def _cwd_audit(
        self,
        selection: object,
        context: _StandardAgentSessionConfigurationContext[StandardExtensionT],
    ) -> None:
        del selection
        request = context.request
        if context.resource_bundle is None:
            raise RuntimeError("Session resources have not been configured.")
        audit = audit_cwd_bound_services(
            session_cwd=request.cwd,
            project_root=project_root_from_settings_base(
                request.settings_manager.project_base_dir
            ),
            resource_cwd=context.resource_bundle.cwd,
        )
        record_cwd_bound_services_audit(
            audit,
            diagnostics_service=request.diagnostics_service,
            session_id=request.session_id,
        )
        context.cwd_bound_services_audit = audit

    def _model_registry(
        self,
        selection: object,
        context: _StandardAgentSessionConfigurationContext[StandardExtensionT],
    ) -> None:
        del selection
        request = context.request
        if context.resource_bundle is None:
            raise RuntimeError("Session resources have not been configured.")
        project_root = (
            context.resource_bundle.agents_path.parent
            if context.resource_bundle.agents_path is not None
            else Path(request.cwd)
        )
        request.model_registry.reload_if_project_layer(
            user_dir=Path.home() / ".loushang" / "models",
            project_dir=project_root / ".loushang" / "models",
        )


__all__ = [
    "StandardAgentSessionConfigurationRequest",
    "StandardAgentSessionConfigurationResult",
    "StandardAgentSessionConfigurationRuntime",
]
