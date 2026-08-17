from __future__ import annotations

import asyncio

import pytest

from loushang.coding.session.agent_session import AgentSession
from loushang.harness.session.agent_product import AgentProductSession


def test_coding_disposal_preserves_product_failure_after_host_sandbox_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def dispose_product(_self: object) -> None:
        events.append("product")
        raise RuntimeError("product disposal failed")

    class _SandboxRuntime:
        async def close(self) -> None:
            events.append("host-sandbox")
            raise ValueError("cleanup failed")

    monkeypatch.setattr(
        AgentProductSession,
        "_dispose_session_runtime_profile",
        dispose_product,
    )
    session = object.__new__(AgentSession)
    session._sandbox_runtime = _SandboxRuntime()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="product disposal failed") as captured:
        asyncio.run(session._dispose_session_runtime_profile())

    assert events == ["product", "host-sandbox"]
    assert captured.value.__notes__ == [
        "process host or sandbox cleanup also failed: cleanup failed"
    ]


def test_coding_disposal_propagates_cleanup_failure_without_product_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def dispose_product(_self: object) -> None:
        events.append("product")

    class _SandboxRuntime:
        async def close(self) -> None:
            events.append("host-sandbox")
            raise ValueError("cleanup failed")

    monkeypatch.setattr(
        AgentProductSession,
        "_dispose_session_runtime_profile",
        dispose_product,
    )
    session = object.__new__(AgentSession)
    session._sandbox_runtime = _SandboxRuntime()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="cleanup failed"):
        asyncio.run(session._dispose_session_runtime_profile())

    assert events == ["product", "host-sandbox"]


def test_coding_disposes_lsp_before_process_host_and_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def dispose_product(_self: object) -> None:
        events.append("product")

    class _LspRuntime:
        async def close(self) -> None:
            events.append("lsp")

    class _SandboxRuntime:
        async def close(self) -> None:
            events.append("host-sandbox")

    monkeypatch.setattr(
        AgentProductSession,
        "_dispose_session_runtime_profile",
        dispose_product,
    )
    session = object.__new__(AgentSession)
    session._lsp_runtime = _LspRuntime()  # type: ignore[assignment]
    session._sandbox_runtime = _SandboxRuntime()  # type: ignore[assignment]

    asyncio.run(session._dispose_session_runtime_profile())

    assert events == ["product", "lsp", "host-sandbox"]
