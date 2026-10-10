"""One explicitly selected Coding turn Tool over the Product Worker query facet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart, ToolCall
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import DirectExecution, DirectToolContext

from .package_product_worker_query_consumer import validate_coding_worker_query_symbol

CODING_WORKER_QUERY_TOOL_NAME = "worker_query_symbol"


class _WorkerQuerySession(Protocol):
    async def query_worker_symbol(self, symbol: str) -> str: ...


@dataclass(slots=True)
class CodingWorkerTurnToolBinding:
    """Hold a Session-owned facet Consumer without granting ambient Host access."""

    plugin_id: str
    _session: _WorkerQuerySession | None = None

    def bind_session(self, session: _WorkerQuerySession) -> None:
        if self._session is not None:
            raise RuntimeError("Coding Worker turn Tool is already bound")
        self._session = session

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=CODING_WORKER_QUERY_TOOL_NAME,
            label="Worker symbol query",
            description=(
                "Query one symbol through the explicitly selected read-only "
                "Coding Worker Provider."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Symbol name to query (up to 128 characters).",
                    }
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
            execution=DirectExecution(self),
            execution_mode="sequential",
        )

    async def __call__(
        self, call: ToolCall, context: DirectToolContext
    ) -> AgentToolResult[Any]:
        del context
        if set(call.arguments) != {"symbol"}:
            raise ValueError("Coding Worker query requires exactly one symbol")
        symbol = validate_coding_worker_query_symbol(call.arguments["symbol"])
        session = self._session
        if session is None:
            raise RuntimeError("Coding Worker turn Tool has no Session owner")
        result = await session.query_worker_symbol(symbol)
        return AgentToolResult(
            content=[TextPart(type="text", text=result)],
            details={"pluginId": self.plugin_id, "symbol": symbol},
        )


__all__ = ["CODING_WORKER_QUERY_TOOL_NAME", "CodingWorkerTurnToolBinding"]
