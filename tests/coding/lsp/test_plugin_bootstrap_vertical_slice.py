from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from time import time_ns
from typing import Literal

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.coding.bootstrap import _create_agent_session, create_services
from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.lsp import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
    LspServerDefinition,
)
from loushang.coding.lsp._plugin_opt_in import CodingLspPluginOptInRequest
from loushang.coding.session_manager import SessionManager
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
)
from loushang.harness.sandbox import SandboxSettings

_FAKE_LSP_SERVER = Path(__file__).parent / "fixtures" / "fake_lsp_server.py"
_LSP_TOOL_NAMES = {DOCUMENT_OUTLINE_TOOL_NAME, INSPECT_SYMBOL_TOOL_NAME}


class _ApprovalOwner:
    def approve_definition(self, *, journal, subject):
        now = time_ns() // 1_000_000
        return journal.issue_execution_decision(
            subject,
            disposition="approved",
            authorization=PluginApprovalAuthorizationV1.direct(
                actor_id="operator:plugin-lsp-vertical-slice",
                source="coding-lsp-plugin-vertical-slice",
            ),
            revocation_epoch=0,
            issued_at_unix_ms=now - 1_000,
            expires_at_unix_ms=now + 60_000,
            expected_journal_revision=journal.snapshot().journal_revision,
        )

    def approve_activation(self, *, journal, subject):
        now = time_ns() // 1_000_000
        return journal.issue_activation_decision(
            subject,
            disposition="approved",
            authorization=PluginApprovalAuthorizationV1.direct(
                actor_id="operator:plugin-lsp-vertical-slice",
                source="coding-lsp-plugin-vertical-slice",
            ),
            issued_at_unix_ms=now - 1_000,
            expires_at_unix_ms=now + 60_000,
            expected_journal_revision=journal.snapshot().journal_revision,
        )


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128_000,
            max_tokens=4_096,
        ),
    )


@pytest.mark.parametrize("mode", ["always", "on_demand"])
def test_private_plugin_executes_real_lsp_tools_and_retires_exact_generation(
    tmp_path: Path,
    mode: Literal["always", "on_demand"],
) -> None:
    async def scenario() -> None:
        project = tmp_path / mode
        project.mkdir()
        (project / "pyproject.toml").touch()
        (project / "main.py").write_text(
            "target = 1\nprint(target)\n",
            encoding="utf-8",
        )
        method_log = project / "lsp-methods.log"
        manager = await SessionManager.new(
            session_dir=tmp_path / f"sessions-{mode}",
            cwd=str(project),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={"coding.lsp": mode},
                        sandbox=SandboxSettings(enabled=False),
                    )
                )
            ),
            lsp_definitions=(
                LspServerDefinition(
                    id="repository-fake-python",
                    command=(sys.executable, str(_FAKE_LSP_SERVER)),
                    language_extensions={"python": (".py",)},
                    root_markers=("pyproject.toml",),
                    environment={"LOUSHANG_FAKE_LSP_LOG": str(method_log)},
                    startup_timeout_seconds=3,
                    request_timeout_seconds=3,
                    shutdown_timeout_seconds=3,
                ),
            ),
            coding_lsp_plugin_opt_in=CodingLspPluginOptInRequest(
                approval_owner=_ApprovalOwner()
            ),
        )
        registry = session._composition.tool_controller.tool_registry
        assert registry is not None
        assert session.get_lsp_status().enabled is False

        try:
            await session.prepare_model_call_runtime()

            assert _LSP_TOOL_NAMES <= {
                definition.name for definition in session.get_all_tools()
            }
            if mode == "always":
                assert _LSP_TOOL_NAMES <= set(session.get_active_tool_names())
            else:
                assert _LSP_TOOL_NAMES.isdisjoint(session.get_active_tool_names())
                await session.set_active_tools(sorted(_LSP_TOOL_NAMES))
                assert set(session.get_active_tool_names()) == _LSP_TOOL_NAMES

            materialized = {tool.name: tool for tool in session.agent.tools}
            symbol = await materialized[INSPECT_SYMBOL_TOOL_NAME].execute(
                f"plugin-{mode}-inspect",
                {"path": "main.py", "line": 2, "character": 7},
            )
            outline = await materialized[DOCUMENT_OUTLINE_TOOL_NAME].execute(
                f"plugin-{mode}-outline",
                {"path": "main.py"},
            )

            assert symbol.details["server_id"] == "repository-fake-python"
            assert symbol.details["count"] == 1
            assert symbol.details["items"][0]["path"] == "main.py"
            assert outline.details["server_id"] == "repository-fake-python"
            assert outline.details["count"] == 1
            assert outline.details["items"][0]["name"] == "target"

            status = session.get_lsp_status()
            assert status.enabled is True
            assert status.ready_count == 1
            [server] = status.servers
            assert server.definition_id == "repository-fake-python"
            assert server.workspace_root == str(project.resolve())
            assert server.state == "ready"

            assert await session.stop_lsp_server(
                definition_id="repository-fake-python",
                workspace_root=str(project.resolve()),
            )
            [stopped] = session.get_lsp_status().servers
            assert stopped.state == "stopped"
            assert stopped.runtime_id is None
        finally:
            await session.dispose()

        assert session._capability_graph_runtime.is_closed is True
        assert _LSP_TOOL_NAMES.isdisjoint(
            definition.name for definition in registry.list_definitions()
        )
        assert method_log.read_text(encoding="utf-8").splitlines() == [
            "initialize",
            "initialized",
            "textDocument/didOpen",
            "textDocument/definition",
            "textDocument/documentSymbol",
            "shutdown",
            "exit",
        ]

    asyncio.run(scenario())
