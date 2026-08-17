"""Stable JSON-compatible wire types for the RPC host."""

from __future__ import annotations

from typing import Any, NotRequired, Required, TypedDict


class RpcModelCost(TypedDict):
    input: float | int
    output: float | int
    cacheRead: float | int
    cacheWrite: float | int


class RpcModel(TypedDict, total=False):
    provider: Required[str]
    id: Required[str]
    name: NotRequired[str]
    endpointId: NotRequired[str]
    api: NotRequired[str]
    baseUrl: NotRequired[str]
    input: NotRequired[list[str]]
    contextWindow: NotRequired[int]
    maxTokens: NotRequired[int]
    reasoning: NotRequired[bool]
    cost: NotRequired[RpcModelCost]
    compat: NotRequired[dict[str, Any]]


class RpcSessionState(TypedDict, total=False):
    sessionId: Required[str]
    sessionName: NotRequired[str]
    sessionFile: NotRequired[str]
    model: Required[RpcModel | None]
    thinkingLevel: Required[str]
    isStreaming: Required[bool]
    isCompacting: Required[bool]
    steeringMode: Required[str | None]
    followUpMode: Required[str | None]
    autoCompactionEnabled: Required[bool | None]
    messageCount: Required[int]
    pendingMessageCount: Required[int]


__all__ = ["RpcModel", "RpcModelCost", "RpcSessionState"]
