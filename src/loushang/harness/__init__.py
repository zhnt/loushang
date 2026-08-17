"""Public Harness entrypoints without eager optional runtime imports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "AgentEventSink": "loushang.harness.types",
    "AgentRunMode": "loushang.harness.types",
    "AgentRunResult": "loushang.harness.types",
    "AgentRunSpec": "loushang.harness.types",
    "AgentRunStatus": "loushang.harness.types",
    "run_agent": "loushang.harness.runner",
    "ResourceBootstrapPorts": "loushang.harness.bootstrap",
    "ResourceBootstrapResult": "loushang.harness.bootstrap",
    "ResourceBootstrapRuntime": "loushang.harness.bootstrap",
    "BootstrapActivationPlan": "loushang.harness.bootstrap",
    "BootstrapActivationResult": "loushang.harness.bootstrap",
    "BootstrapActivationRuntime": "loushang.harness.bootstrap",
}


def __getattr__(name: str) -> Any:
    """Resolve public symbols without loading the Agent runtime by default."""

    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORT_MODULES})


__all__ = list(_EXPORT_MODULES)
