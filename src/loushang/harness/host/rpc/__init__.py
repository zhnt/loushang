"""Product-neutral JSONL RPC host."""

from .projections import (
    STANDARD_AGENT_RPC_EVENT_PROJECTION,
    STANDARD_RPC_DIAGNOSTICS_PROJECTION,
    RpcDiagnosticsProjection,
    RpcEventProjection,
)
from .remote_ui import RpcExtensionUIContext
from .runtime import (
    RpcHost,
    run_rpc_host,
)
from .testing import (
    RpcWirePlayback,
    RpcWirePlaybackResult,
    play_rpc_lines,
    play_rpc_lines_async,
    play_rpc_wire,
    play_rpc_wire_async,
)
from .types import RpcModel, RpcModelCost, RpcSessionState

__all__ = [
    "RpcDiagnosticsProjection",
    "RpcEventProjection",
    "RpcExtensionUIContext",
    "RpcHost",
    "RpcModel",
    "RpcModelCost",
    "RpcSessionState",
    "RpcWirePlayback",
    "RpcWirePlaybackResult",
    "STANDARD_AGENT_RPC_EVENT_PROJECTION",
    "STANDARD_RPC_DIAGNOSTICS_PROJECTION",
    "play_rpc_lines",
    "play_rpc_lines_async",
    "play_rpc_wire",
    "play_rpc_wire_async",
    "run_rpc_host",
]
