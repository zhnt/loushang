"""Shared resource toggle mutation over an injected settings manager."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from loushang.harness.cli.agent_args import AgentCliArgs


class ResourceToggleError(RuntimeError):
    """Raised after a resource toggle operation reports an actionable error."""

    def __init__(self, message: str, *, messages: tuple[str, ...] = ()) -> None:
        super().__init__(message)
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
    settings_manager: object,
    request: ResourceToggleRequest,
    *,
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
            _call(settings_manager, "disable_plugin", name, scope="project")
            messages.append(f"disabled plugin\t{name}")
        for name in request.enable_plugins:
            _call(settings_manager, "enable_plugin", name, scope="project")
            messages.append(f"enabled plugin\t{name}")
    except ResourceToggleError:
        raise
    except Exception as error:
        raise ResourceToggleError(str(error), messages=tuple(messages)) from error
    return ResourceToggleResult(tuple(messages))


def _call(settings_manager: object, name: str, *args: object, **kwargs: object) -> object:
    method = getattr(settings_manager, name, None)
    if not callable(method):
        raise ResourceToggleError(f"settings operation is not available: {name}")
    return method(*args, **kwargs)


__all__ = [
    "ResourceToggleError",
    "ResourceToggleRequest",
    "ResourceToggleResult",
    "agent_resource_toggle_request",
    "apply_resource_toggles",
    "report_agent_resource_settings_errors",
]
