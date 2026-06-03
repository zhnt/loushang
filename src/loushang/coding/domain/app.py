from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from loushang.coding.domain.types import (
    CodingDomainPreparedTurn,
    CodingDomainRequest,
    MethodPolicy,
)
from loushang.method import (
    MethodCompiler,
    MethodContext,
    MethodLoader,
    MethodProjector,
    MethodSelector,
)
from loushang.method.types import (
    MethodDescriptor,
    MethodPlan,
    MethodProjection,
    MethodStep,
)

DEFAULT_GUIDANCE_TEMPLATE = "{guidance}\n\nUser request:\n\n{user_input}"


class CodingDomainApp:
    def __init__(
        self,
        *,
        cwd: Path | None = None,
        method_loader: MethodLoader | None = None,
        method_compiler: MethodCompiler | None = None,
        method_projector: MethodProjector | None = None,
    ) -> None:
        self._cwd = cwd
        self._method_loader = method_loader or MethodLoader()
        self._method_compiler = method_compiler or MethodCompiler()
        self._method_projector = method_projector or MethodProjector()

    def prepare_turn(self, request: CodingDomainRequest) -> CodingDomainPreparedTurn:
        return self.prepare_turns(request)[0]

    def prepare_turns(self, request: CodingDomainRequest) -> tuple[CodingDomainPreparedTurn, ...]:
        policy = request.method_policy or MethodPolicy.explicit(request.method)
        if policy.mode == "off":
            return (CodingDomainPreparedTurn(prepared_prompt=request.user_input),)
        if policy.mode != "explicit":
            raise ValueError(f"unsupported method policy mode: {policy.mode}")

        method_name = policy.selected_method.strip() if policy.selected_method is not None else None
        if not method_name:
            return (CodingDomainPreparedTurn(prepared_prompt=request.user_input),)

        cwd = request.cwd or self._cwd or Path.cwd()
        methods = self._method_loader.discover_methods(cwd)
        descriptor = MethodSelector(methods).select(method_name)
        if descriptor is None:
            raise ValueError(f"method not found: {method_name}")

        context = MethodContext(domain="coding", metadata=request.metadata)
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
        request: CodingDomainRequest,
        descriptor: MethodDescriptor,
        plan: MethodPlan,
        step: MethodStep,
        step_index: int,
        context: MethodContext,
    ) -> CodingDomainPreparedTurn:
        projection = self._method_projector.project(plan, step, context=context)
        metadata = {
            "meta_role": projection.meta_role,
            "role_variant": projection.role_variant,
            "temperature": projection.temperature,
            "plan_mode": plan.mode,
            "step_index": step_index,
        }
        if not _has_meaningful_guidance(descriptor, projection):
            return CodingDomainPreparedTurn(
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
        return CodingDomainPreparedTurn(
            prepared_prompt=DEFAULT_GUIDANCE_TEMPLATE.format(
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


def _has_meaningful_guidance(descriptor: MethodDescriptor, projection: MethodProjection) -> bool:
    source_projection = projection.metadata.get("source_projection")
    if isinstance(source_projection, Mapping):
        content = source_projection.get("content")
        if isinstance(content, str):
            return bool(content.strip() and projection.system_guidance.strip())
    return bool(descriptor.content.strip() and projection.system_guidance.strip())


__all__ = [
    "CodingDomainApp",
    "DEFAULT_GUIDANCE_TEMPLATE",
]
