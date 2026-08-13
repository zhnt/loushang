from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, runtime_checkable

from loushang.ai.context import NormalizedContext
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.model import Model
from loushang.ai.options import CallOptions

ProviderContext = NormalizedContext
ProviderOptions = CallOptions | None
ProviderInvocationMode = Literal["complete", "stream"]


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: Model
    context: ProviderContext
    options: ProviderOptions
    base_url: str
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    mode: ProviderInvocationMode = "stream"
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    reasoning_enabled: bool | None = None
    temperature: float | int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        if not isinstance(self.model, Model):
            raise TypeError("ProviderRequest.model must be Model")
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise ValueError(
                "ProviderRequest.base_url must be a resolved non-empty string"
            )
        if "{" in self.base_url or "}" in self.base_url:
            raise ValueError("ProviderRequest.base_url contains an unresolved template")
        if self.reasoning_enabled is not None and not isinstance(
            self.reasoning_enabled, bool
        ):
            raise TypeError(
                "ProviderRequest.reasoning_enabled must be a boolean or None"
            )
        if self.reasoning_enabled is False and self.reasoning_effort is not None:
            raise ValueError(
                "ProviderRequest.reasoning_effort must be None when reasoning is disabled"
            )
        if not isinstance(self.context, NormalizedContext):
            raise TypeError("ProviderRequest.context must be NormalizedContext")
        if (
            not self.model.provider_id
            or not self.model.endpoint_id
            or not self.model.api
        ):
            raise ValueError(
                f"Model {self.model.id!r} is not bound to a concrete provider endpoint"
            )


@runtime_checkable
class APIAdapter(Protocol):
    api: str

    def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[RawPart]: ...


@runtime_checkable
class ProviderRequestValidator(Protocol):
    def validate_request(self, request: ProviderRequest) -> None: ...
