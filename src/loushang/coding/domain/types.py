from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})


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


@dataclass(frozen=True)
class CodingDomainRequest:
    user_input: str
    cwd: Path
    method: str | None = None
    method_policy: MethodPolicy | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)


@dataclass(frozen=True)
class CodingDomainPreparedTurn:
    prepared_prompt: str
    method_id: str | None = None
    plan_id: str | None = None
    plan_mode: str | None = None
    step_id: str | None = None
    step_index: int | None = None
    step_title: str | None = None
    method_guidance: str | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)


__all__ = [
    "CodingDomainPreparedTurn",
    "CodingDomainRequest",
    "MethodPolicy",
]
