"""Immutable Product selection for the local hosted Method slice."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from loushang.appserver.method_work import method_identifier
from loushang.harnesswork.integrations.session import (
    PreparedSessionWorkTurn,
    SessionWorkTurn,
    project_prepared_session_work_turns,
)
from loushang.method import MethodDomainRequest, MethodLoader, MethodPolicy
from loushang.method.types import MethodApplicability, MethodDescriptor

from .domain.app import CodingDomainApp


def _freeze(value: Any) -> Any:
    if type(value) in (MethodDescriptor, MethodApplicability):
        return replace(value, **{f.name: _freeze(getattr(value, f.name)) for f in fields(value)})
    if is_dataclass(value):
        raise ValueError("unsupported Method data class")
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value):
            raise ValueError("Method mappings require string keys")
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if value is None or type(value) in (str, int, bool, float):
        return value
    raise ValueError("Method configuration must be data")


def _data(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _data(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: _data(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_data(v) for v in value]
    return value


class _FrozenLoader(MethodLoader):
    def __init__(self, descriptor: MethodDescriptor) -> None:
        self._descriptor = descriptor

    def discover_methods(self, cwd: str | Path) -> list[MethodDescriptor]:
        return [self._descriptor]


@dataclass(frozen=True)
class CodingHostedMethodV1:
    """Trusted fixed selection, detached from mutable files and caller mappings."""

    descriptor: MethodDescriptor
    max_steps: int = 16

    def __post_init__(self) -> None:
        if type(self.descriptor) is not MethodDescriptor:
            raise TypeError("hosted Method requires a descriptor")
        if type(self.max_steps) is not int or not 1 <= self.max_steps <= 64:
            raise ValueError("invalid hosted Method step limit")
        object.__setattr__(self, "descriptor", _freeze(self.descriptor))
        metadata = self.descriptor.metadata
        frontmatter = metadata.get("frontmatter", {})
        if metadata.get("approval_gates") or (isinstance(frontmatter, Mapping) and frontmatter.get("approval_gates")):
            raise ValueError("hosted Method does not implement approval gates")
        method_identifier(self.descriptor.id)
        self.prepare("validate fixed Method", Path.cwd())
        self.digest  # Validate the complete frozen input, including finite JSON numbers.

    @property
    def digest(self) -> str:
        body = json.dumps(_data(self.descriptor), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(body.encode()).hexdigest()

    def prepare(self, text: str, cwd: Path) -> tuple[SessionWorkTurn, ...]:
        prepared = CodingDomainApp(method_loader=_FrozenLoader(self.descriptor)).prepare_turns(
            MethodDomainRequest(text, cwd, method_policy=MethodPolicy.explicit(self.descriptor.id)),
        )
        turns = project_prepared_session_work_turns(cast(Sequence[PreparedSessionWorkTurn], prepared), images=None, follow_up_messages=())
        if not turns or len(turns) > self.max_steps:
            raise ValueError("unsupported Method step count")
        seen: set[str] = set()
        for turn in turns:
            for identifier in (turn.method_id, turn.plan_id, turn.step_id):
                method_identifier(identifier)  # type: ignore[arg-type]
            assert turn.step_id is not None
            if turn.step_id in seen or turn.planned_constraint or turn.audit_policy:
                raise ValueError("unsupported Method contract")
            seen.add(turn.step_id)
        return turns
