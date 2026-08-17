"""Product-neutral Method discovery, planning, and prompt preparation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from loushang.method.compiler import MethodCompiler
from loushang.method.loader import MethodLoader
from loushang.method.projection import MethodProjector
from loushang.method.selector import MethodSelector
from loushang.method.types import (
    MethodContext,
    MethodDescriptor,
    MethodPlan,
    MethodProjection,
    MethodStep,
)

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True)
class MethodDomainProfile:
    """Product vocabulary used by the shared Method runtime."""

    domain: str
    guidance_template: str = "{guidance}\n\nUser request:\n\n{user_input}"

    def __post_init__(self) -> None:
        if not self.domain.strip():
            raise ValueError("method domain profile requires a non-empty domain")
        if "{guidance}" not in self.guidance_template:
            raise ValueError("method guidance template requires {guidance}")
        if "{user_input}" not in self.guidance_template:
            raise ValueError("method guidance template requires {user_input}")


@dataclass(frozen=True)
class MethodPolicy:
    mode: str = "explicit"
    selected_method: str | None = None

    @classmethod
    def off(cls) -> MethodPolicy:
        return cls(mode="off")

    @classmethod
    def explicit(cls, selected_method: str | None = None) -> MethodPolicy:
        return cls(mode="explicit", selected_method=selected_method)


def resolve_method_policy(
    *,
    explicit_method: str | None,
    disabled: bool,
    settings_manager: object | None = None,
) -> MethodPolicy:
    """Resolve CLI selection over an optional Product settings provider."""

    if disabled:
        return MethodPolicy.off()
    if explicit_method is not None:
        return MethodPolicy.explicit(explicit_method)
    get_method_settings = getattr(settings_manager, "get_method_settings", None)
    if callable(get_method_settings):
        settings = get_method_settings()
    else:
        get_settings = getattr(settings_manager, "get_settings", None)
        settings = (
            getattr(get_settings(), "method", None)
            if callable(get_settings)
            else None
        )
    if settings is None:
        return MethodPolicy.explicit()
    if getattr(settings, "mode", None) == "off":
        return MethodPolicy.off()
    return MethodPolicy(
        mode=getattr(settings, "mode", "explicit"),
        selected_method=getattr(settings, "selected_method", None),
    )


@dataclass(frozen=True)
class MethodDomainRequest:
    user_input: str
    cwd: Path
    method: str | None = None
    method_policy: MethodPolicy | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)


@dataclass(frozen=True)
class MethodDomainPreparedTurn:
    prepared_prompt: str
    method_id: str | None = None
    plan_id: str | None = None
    plan_mode: str | None = None
    step_id: str | None = None
    step_index: int | None = None
    step_title: str | None = None
    method_guidance: str | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)


class MethodDomainRuntime:
    """Compose existing Method components for one Product domain."""

    def __init__(
        self,
        *,
        profile: MethodDomainProfile,
        cwd: Path | None = None,
        method_loader: MethodLoader | None = None,
        method_compiler: MethodCompiler | None = None,
        method_projector: MethodProjector | None = None,
    ) -> None:
        self._profile = profile
        self._cwd = cwd
        self._method_loader = method_loader or MethodLoader()
        self._method_compiler = method_compiler or MethodCompiler()
        self._method_projector = method_projector or MethodProjector()

    def prepare_turn(
        self,
        request: MethodDomainRequest,
    ) -> MethodDomainPreparedTurn:
        return self.prepare_turns(request)[0]

    def prepare_turns(
        self,
        request: MethodDomainRequest,
    ) -> tuple[MethodDomainPreparedTurn, ...]:
        policy = request.method_policy or MethodPolicy.explicit(request.method)
        if policy.mode == "off":
            return (MethodDomainPreparedTurn(prepared_prompt=request.user_input),)
        if policy.mode != "explicit":
            raise ValueError(f"unsupported method policy mode: {policy.mode}")

        method_name = (
            policy.selected_method.strip()
            if policy.selected_method is not None
            else None
        )
        if not method_name:
            return (MethodDomainPreparedTurn(prepared_prompt=request.user_input),)

        cwd = request.cwd or self._cwd or Path.cwd()
        descriptor = MethodSelector(
            self._method_loader.discover_methods(cwd)
        ).select(method_name)
        if descriptor is None:
            raise ValueError(f"method not found: {method_name}")

        context = MethodContext(
            domain=self._profile.domain,
            metadata=request.metadata,
        )
        plan = self._method_compiler.compile(descriptor, context=context)
        return tuple(
            self._prepare_step_turn(
                request=request,
                descriptor=descriptor,
                plan=plan,
                step=step,
                step_index=step_index,
                context=context,
            )
            for step_index, step in enumerate(plan.steps)
        )

    def _prepare_step_turn(
        self,
        *,
        request: MethodDomainRequest,
        descriptor: MethodDescriptor,
        plan: MethodPlan,
        step: MethodStep,
        step_index: int,
        context: MethodContext,
    ) -> MethodDomainPreparedTurn:
        projection = self._method_projector.project(plan, step, context=context)
        metadata = _projection_metadata(
            projection=projection,
            plan=plan,
            step_index=step_index,
        )
        if not _has_meaningful_guidance(descriptor, projection):
            return MethodDomainPreparedTurn(
                prepared_prompt=request.user_input,
                method_id=descriptor.id,
                plan_id=plan.id,
                plan_mode=plan.mode,
                step_id=step.id,
                step_index=step_index,
                step_title=step.title,
                metadata=metadata,
            )

        guidance = projection.system_guidance
        return MethodDomainPreparedTurn(
            prepared_prompt=self._profile.guidance_template.format(
                guidance=guidance,
                user_input=request.user_input,
            ),
            method_id=projection.method_id,
            plan_id=plan.id,
            plan_mode=plan.mode,
            step_id=step.id,
            step_index=step_index,
            step_title=step.title,
            method_guidance=guidance,
            metadata=metadata,
        )


def _projection_metadata(
    *,
    projection: MethodProjection,
    plan: MethodPlan,
    step_index: int,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "meta_role": projection.meta_role,
        "role_variant": projection.role_variant,
        "temperature": projection.temperature,
        "plan_mode": plan.mode,
        "step_index": step_index,
    }
    for source_key, target_key in (
        ("source_constraint", "planned_constraint"),
        ("source_audit", "audit_policy"),
        ("plan_facts", "plan_facts"),
        ("step_facts", "step_facts"),
    ):
        value = projection.metadata.get(source_key)
        if isinstance(value, Mapping) and value:
            metadata[target_key] = dict(value)
    return metadata


def _has_meaningful_guidance(
    descriptor: MethodDescriptor,
    projection: MethodProjection,
) -> bool:
    source_projection = projection.metadata.get("source_projection")
    if isinstance(source_projection, Mapping):
        content = source_projection.get("content")
        if isinstance(content, str):
            return bool(content.strip() and projection.system_guidance.strip())
    return bool(descriptor.content.strip() and projection.system_guidance.strip())


__all__ = [
    "MethodDomainPreparedTurn",
    "MethodDomainProfile",
    "MethodDomainRequest",
    "MethodDomainRuntime",
    "MethodPolicy",
    "resolve_method_policy",
]
