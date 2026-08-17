from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})
_EMPTY_TAGS: Mapping[str, tuple[str, ...]] = MappingProxyType({})


@dataclass(frozen=True)
class MethodApplicability:
    domains: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()
    contexts: tuple[str, ...] = ()
    artifact_types: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    toolchains: tuple[str, ...] = ()
    lifecycle: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    complexity: str | None = None
    risk: str | None = None
    tags: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _EMPTY_TAGS)


@dataclass(frozen=True)
class MethodDescriptor:
    id: str
    name: str
    description: str
    content: str
    kind: str
    element_type: str | None = None
    domain: str | None = None
    meta_role: str | None = None
    phase: str | None = None
    source_path: str | None = None
    version: str | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    applicability: MethodApplicability = field(default_factory=MethodApplicability)


@dataclass(frozen=True)
class MethodContext:
    domain: str | None = None
    task: str | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    applicability: MethodApplicability = field(default_factory=MethodApplicability)


@dataclass(frozen=True)
class MethodStep:
    id: str
    title: str
    executor: str
    role_variant: str | None = None
    projection: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    constraint: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    audit: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    applicability: MethodApplicability = field(default_factory=MethodApplicability)


@dataclass(frozen=True)
class MethodPlan:
    id: str
    method_id: str
    mode: str
    steps: tuple[MethodStep, ...]
    phase: str | None = None
    activity: str | None = None
    task: str | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    applicability: MethodApplicability = field(default_factory=MethodApplicability)


@dataclass(frozen=True)
class MethodProjection:
    method_id: str
    step_id: str
    system_guidance: str
    meta_role: str | None = None
    role_variant: str | None = None
    user_guidance: str | None = None
    allowed_skills: tuple[str, ...] = ()
    suggested_tools: tuple[str, ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    approval_gates: tuple[str, ...] = ()
    temperature: float | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)


__all__ = [
    "MethodApplicability",
    "MethodContext",
    "MethodDescriptor",
    "MethodPlan",
    "MethodProjection",
    "MethodStep",
]
