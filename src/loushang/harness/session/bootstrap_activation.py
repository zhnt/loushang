"""Standard Agent session activation order and effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harness.bootstrap import (
    BootstrapActivationPlan,
    BootstrapActivationRuntime,
)
from loushang.harness.config.activation import ConfigActivationStep
from loushang.harness.config.agent import ControlConfig

ActivationContextT = TypeVar("ActivationContextT")


@dataclass(frozen=True)
class StandardAgentSessionActivationEffects(Generic[ActivationContextT]):
    """Product effects bound to the standard Agent session activation order."""

    startup_checks: Callable[[object, ActivationContextT], object]
    package_sources: Callable[[object, ActivationContextT], object]
    resource_roots: Callable[[object, ActivationContextT], object]
    resources: Callable[[object, ActivationContextT], object]
    extensions: Callable[[object, ActivationContextT], object]
    cwd_audit: Callable[[object, ActivationContextT], object]
    model_registry: Callable[[object, ActivationContextT], object]


def standard_agent_session_activation_plan(
    effects: StandardAgentSessionActivationEffects[ActivationContextT],
) -> BootstrapActivationPlan[ControlConfig, ActivationContextT]:
    """Compose standard Agent startup capabilities over the shared graph runtime."""

    return BootstrapActivationPlan(
        steps=(
            ConfigActivationStep(
                "startup_checks",
                select=lambda config: config.package_roots,
                apply=effects.startup_checks,
            ),
            ConfigActivationStep(
                "package_sources",
                select=lambda config: config.package_sources,
                apply=effects.package_sources,
                depends_on=("startup_checks",),
            ),
            ConfigActivationStep(
                "resource_roots",
                select=lambda config: (
                    config.package_roots,
                    config.package_sources,
                    config.plugin_sources,
                    config.disabled_plugins,
                    config.resource_roots,
                ),
                apply=effects.resource_roots,
                depends_on=("package_sources",),
            ),
            ConfigActivationStep(
                "resources",
                select=lambda config: config.disabled_skills,
                apply=effects.resources,
                depends_on=("resource_roots",),
            ),
            ConfigActivationStep(
                "extensions",
                select=lambda config: (
                    config.disabled_skills,
                    config.disabled_plugins,
                ),
                apply=effects.extensions,
                depends_on=("resources",),
            ),
            ConfigActivationStep(
                "cwd_audit",
                select=lambda config: config.resource_roots,
                apply=effects.cwd_audit,
                depends_on=("extensions",),
            ),
            ConfigActivationStep(
                "model_registry",
                select=lambda config: config.enabled_models,
                apply=effects.model_registry,
                depends_on=("cwd_audit",),
            ),
        )
    )


def activate_standard_agent_session_configuration(
    config: ControlConfig,
    context: ActivationContextT,
    *,
    effects: StandardAgentSessionActivationEffects[ActivationContextT],
) -> ActivationContextT:
    """Execute the standard activation plan and propagate its first failure."""

    result = BootstrapActivationRuntime(
        standard_agent_session_activation_plan(effects)
    ).activate(config, context)
    if result.report.failures:
        raise result.report.failures[0].error
    return result.context


__all__ = [
    "StandardAgentSessionActivationEffects",
    "activate_standard_agent_session_configuration",
    "standard_agent_session_activation_plan",
]
