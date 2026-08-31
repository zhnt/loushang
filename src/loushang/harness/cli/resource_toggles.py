"""Shared resource toggle mutation over an injected settings manager."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from loushang.harness.cli.agent_args import AgentCliArgs
from loushang.harness.cli.plugin_management import PluginManagementCliBinding
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementApplicationCommandV1,
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)


class ResourceToggleError(RuntimeError):
    """Raised after a resource toggle operation reports an actionable error."""

    expose_cli_code = True

    def __init__(
        self,
        message: str,
        *,
        code: str = "resource_toggle_failed",
        messages: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.messages = messages


@dataclass(frozen=True, slots=True)
class ResourceToggleRequest:
    enable_skills: tuple[str, ...] = ()
    disable_skills: tuple[str, ...] = ()
    add_plugin_sources: tuple[str, ...] = ()
    remove_plugin_sources: tuple[str, ...] = ()
    enable_plugins: tuple[str, ...] = ()
    disable_plugins: tuple[str, ...] = ()

    @property
    def has_operations(self) -> bool:
        return any(
            (
                self.enable_skills,
                self.disable_skills,
                self.add_plugin_sources,
                self.remove_plugin_sources,
                self.enable_plugins,
                self.disable_plugins,
            )
        )

    @property
    def requires_settings(self) -> bool:
        return any(
            (
                self.enable_skills,
                self.disable_skills,
                self.add_plugin_sources,
                self.remove_plugin_sources,
            )
        )


@dataclass(frozen=True, slots=True)
class ResourceToggleResult:
    messages: tuple[str, ...] = ()


def agent_resource_toggle_request(args: AgentCliArgs) -> ResourceToggleRequest | None:
    """Project standard Agent CLI resource flags into one optional request."""

    request = ResourceToggleRequest(
        enable_skills=tuple(args.enable_skills),
        disable_skills=tuple(args.disable_skills),
        add_plugin_sources=tuple(args.add_plugin_sources),
        remove_plugin_sources=tuple(args.remove_plugin_sources),
        enable_plugins=tuple(args.enable_plugins),
        disable_plugins=tuple(args.disable_plugins),
    )
    return request if request.has_operations else None


def report_agent_resource_settings_errors(
    args: AgentCliArgs,
    settings_manager: object | None,
    *,
    stderr: TextIO,
) -> None:
    """Drain settings diagnostics for standard resource CLI operations."""

    if not (
        args.list_plugins
        or args.list_packages
        or args.enable_skills
        or args.disable_skills
        or args.add_plugin_sources
        or args.remove_plugin_sources
        or args.enable_plugins
        or args.disable_plugins
    ):
        return
    context = (
        "package command"
        if args.list_packages
        or args.list_plugins
        or args.add_plugin_sources
        or args.remove_plugin_sources
        else "settings command"
    )
    drain_errors = getattr(settings_manager, "drain_errors", None)
    if not callable(drain_errors):
        return
    try:
        errors = drain_errors()
    except Exception:
        return
    if not isinstance(errors, list):
        return
    for error in errors:
        scope = _safe_getattr(error, "scope", "unknown")
        message = _safe_getattr(error, "message", "")
        stderr.write(f"Warning ({context}, {scope} settings): {message}\n")


def _safe_getattr(target: object, name: str, default: object) -> object:
    try:
        return getattr(target, name, default)
    except Exception:
        return default


def apply_resource_toggles(
    settings_manager: object | None,
    request: ResourceToggleRequest,
    *,
    plugin_management: PluginManagementCliBinding | None = None,
    evaluate_plugin_source: Callable[[str], str | None] | None = None,
    is_remote_plugin_source: Callable[[str], bool] | None = None,
    on_policy_denied: Callable[[str, str | None], None] | None = None,
) -> ResourceToggleResult:
    """Apply toggles while keeping settings ownership in the Product port."""

    messages: list[str] = []
    try:
        for name in request.disable_skills:
            _call(settings_manager, "disable_skill", name, scope="project")
            messages.append(f"disabled skill\t{name}")
        for name in request.enable_skills:
            _call(settings_manager, "enable_skill", name, scope="project")
            messages.append(f"enabled skill\t{name}")
        for source in request.remove_plugin_sources:
            removed = _call(
                settings_manager,
                "remove_plugin_source",
                source,
                scope="project",
            )
            if removed is False:
                raise ResourceToggleError(
                    f"no matching plugin source found: {source}",
                    messages=tuple(messages),
                )
            messages.append(f"removed plugin source\t{source}")
        for source in request.add_plugin_sources:
            reason = (
                evaluate_plugin_source(source)
                if evaluate_plugin_source is not None
                else None
            )
            if reason is not None:
                if on_policy_denied is not None:
                    on_policy_denied(source, reason)
                raise ResourceToggleError(reason, messages=tuple(messages))
            added = _call(
                settings_manager,
                "add_plugin_source",
                source,
                scope="project",
            )
            if added is False:
                raise ResourceToggleError(
                    f"plugin source already exists: {source}",
                    messages=tuple(messages),
                )
            label = (
                "remote plugin source"
                if is_remote_plugin_source is not None
                and is_remote_plugin_source(source)
                else "plugin source"
            )
            messages.append(f"added {label}\t{source}")
        for name in request.disable_plugins:
            _apply_plugin_toggle(plugin_management, name=name, action="disable")
            messages.append(f"plugin desired state committed\tdisabled\t{name}")
        for name in request.enable_plugins:
            _apply_plugin_toggle(plugin_management, name=name, action="enable")
            messages.append(f"plugin desired state committed\tenabled\t{name}")
    except ResourceToggleError as error:
        if error.messages or not messages:
            raise
        raise ResourceToggleError(
            str(error),
            code=error.code,
            messages=tuple(messages),
        ) from error
    except Exception as error:
        raise ResourceToggleError(str(error), messages=tuple(messages)) from error
    return ResourceToggleResult(tuple(messages))


def _call(
    settings_manager: object | None,
    name: str,
    *args: object,
    **kwargs: object,
) -> object:
    method = getattr(settings_manager, name, None)
    if not callable(method):
        raise ResourceToggleError(f"settings operation is not available: {name}")
    return method(*args, **kwargs)


def _apply_plugin_toggle(
    management: PluginManagementCliBinding | None,
    *,
    name: str,
    action: str,
) -> None:
    if management is None:
        raise ResourceToggleError(
            "plugin management command is not available",
            code="plugin_management_unavailable",
        )
    for _attempt in range(32):
        projection = management.query(
            correlation_id=f"cli:{action}-plugin:{name}:query",
            plugin_ids=(name,),
        )
        if not projection.installations:
            raise ResourceToggleError(
                f"plugin Installation is not migrated: {name}",
                code="plugin_enablement_migration_required",
            )
        [view] = projection.installations
        migration_phase = view.enablement_migration_phase
        if migration_phase not in {"compatibility_window", "finalized"}:
            in_progress = migration_phase in {"accepted", "desired_committed"}
            raise ResourceToggleError(
                (
                    f"plugin enablement migration is in progress: {name}"
                    if in_progress
                    else f"plugin Installation is not migrated: {name}"
                ),
                code=(
                    "plugin_enablement_migration_in_progress"
                    if in_progress
                    else "plugin_enablement_migration_required"
                ),
            )
        current = view.desired_state
        target = {
            "disable": "installed_disabled",
            "enable": "installed_enabled",
        }[action]
        if current == target:
            _publish_compatibility(management, name=name)
            return
        if current not in {"installed_disabled", "installed_enabled"}:
            raise ResourceToggleError(
                f"plugin Installation is not installed: {name}",
                code="plugin_installation_not_installed",
            )
        revision = projection.owner_revisions.desired_state
        identity = hashlib.sha256(
            json.dumps(
                {
                    "action": action,
                    "installationScope": management.installation_scope,
                    "pluginId": name,
                    "productId": management.product_id,
                    "revision": revision,
                    "scopeId": management.scope_id,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        operation_id = f"cli-plugin-toggle:{identity}"
        result = management.ports.commands.submit(
            PluginManagementApplicationCommandV1(
                correlation_id=f"cli:{action}-plugin:{name}",
                command=PluginManagementCommandV1(
                    action=action,  # type: ignore[arg-type]
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=operation_id,
                        idempotency_key=operation_id,
                        expected_inventory_revision=revision,
                        installation_key=view.installation_key,
                        desired_state=target,  # type: ignore[arg-type]
                        package_revision=None,
                        actor_id=management.actor_id,
                        policy_revision=management.policy_revision,
                    ),
                ),
            )
        )
        operation = result.operation
        if not isinstance(operation, PluginManagementOperationEventV1):
            raise ResourceToggleError(
                "plugin toggle returned an incompatible operation record",
                code="plugin_management_operation_incompatible",
            )
        terminal = operation.result
        if terminal is not None and terminal.disposition == "succeeded":
            _publish_compatibility(management, name=name)
            return
        error_code = (
            "plugin_management_operation_incomplete"
            if terminal is None or terminal.error_code is None
            else terminal.error_code
        )
        if error_code == "plugin_inventory_revision_conflict":
            continue
        raise ResourceToggleError(
            f"plugin {action} failed: {name}: {error_code}",
            code=error_code,
        )
    raise ResourceToggleError(
        f"plugin {action} could not linearize: {name}",
        code="plugin_management_busy",
    )


def _publish_compatibility(
    management: PluginManagementCliBinding,
    *,
    name: str,
) -> None:
    try:
        management.publish_compatibility()
    except Exception as error:
        raise ResourceToggleError(
            "plugin desired state committed but compatibility projection failed: "
            f"{name}",
            code="plugin_enablement_compatibility_publish_failed",
        ) from error


__all__ = [
    "ResourceToggleError",
    "ResourceToggleRequest",
    "ResourceToggleResult",
    "agent_resource_toggle_request",
    "apply_resource_toggles",
    "report_agent_resource_settings_errors",
]
