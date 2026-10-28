from __future__ import annotations

import asyncio
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Literal

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import UserMessage
from loushang.coding._capability_plugin_composition import (
    CodingCapabilityPluginCompositionError,
)
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.lsp import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
    LspServerDefinition,
)
from loushang.coding.lsp._deferred_generation import CodingDeferredLspGeneration
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.sandbox import SandboxSettings
from loushang.harness.session.agent_product import AgentProductSession

_FAKE_LSP_SERVER = Path(__file__).parent / "fixtures" / "fake_lsp_server.py"
_LSP_TOOL_NAMES = {DOCUMENT_OUTLINE_TOOL_NAME, INSPECT_SYMBOL_TOOL_NAME}


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
        session = create_agent_session(
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
        )
        registry = session._composition.tool_controller.tool_registry
        assert registry is not None
        if mode == "always":
            assert session.get_lsp_status().enabled is False
        else:
            assert session.get_lsp_status().enabled is True
            assert session._deferred_lsp_slot is not None
            assert session._deferred_lsp_slot.state == "dormant"
            assert session._coding_lsp_plugin_assembly is None
            dormant_status = await session.execute_command_async("lsp", "status")
            assert dormant_status is not None
            assert dormant_status.result["enabled"] is True
            assert session._deferred_lsp_slot.state == "dormant"

        try:
            await session.prepare_model_call_runtime()

            if mode == "always":
                assert _LSP_TOOL_NAMES <= {
                    definition.name for definition in session.get_all_tools()
                }
                assert _LSP_TOOL_NAMES <= set(session.get_active_tool_names())
            else:
                assert _LSP_TOOL_NAMES <= {
                    str(item["name"]) for item in session.get_all_tool_infos()
                }
                assert _LSP_TOOL_NAMES.isdisjoint(
                    definition.name for definition in session.get_all_tools()
                )
                assert _LSP_TOOL_NAMES.isdisjoint(session.get_active_tool_names())
                tools_result = await session.execute_command_async(
                    "tools", "on document_outline inspect_symbol"
                )
                assert tools_result is not None
                assert _LSP_TOOL_NAMES <= set(session.get_active_tool_names())
                assert _LSP_TOOL_NAMES <= {
                    definition.name for definition in session.get_all_tools()
                }

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


@pytest.mark.parametrize("failure_after_retirement", [False, True])
def test_session_close_preserves_parent_until_deferred_lsp_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_after_retirement: bool,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), persist=False
        )
        session = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={"coding.lsp": "on_demand"},
                        sandbox=SandboxSettings(enabled=False),
                    )
                )
            ),
        )
        attempts: list[CodingDeferredLspGeneration] = []
        order: list[str] = []
        original_child_dispose = CodingDeferredLspGeneration.dispose
        original_parent_dispose = AgentProductSession._dispose_session_runtime_profile

        async def dispose_child(candidate: CodingDeferredLspGeneration) -> None:
            attempts.append(candidate)
            order.append("child")
            if len(attempts) == 1:
                if failure_after_retirement:
                    await original_child_dispose(candidate)
                raise RuntimeError("injected child retirement failure")
            await original_child_dispose(candidate)

        async def dispose_parent(owner: AgentProductSession) -> None:
            order.append("parent")
            await original_parent_dispose(owner)

        try:
            await session.set_active_tools([INSPECT_SYMBOL_TOOL_NAME])
            slot = session._deferred_lsp_slot
            assert slot is not None and slot.active is not None
            candidate = slot.active
            parent = session._capability_graph_runtime
            assert not parent.is_closed
            with monkeypatch.context() as patch:
                patch.setattr(CodingDeferredLspGeneration, "dispose", dispose_child)
                patch.setattr(
                    AgentProductSession, "_dispose_session_runtime_profile", dispose_parent
                )
                with pytest.raises(RuntimeError, match="injected child retirement"):
                    await session.dispose()
                assert order == ["child"]
                assert not parent.is_closed
                assert slot.state == "closing"
                assert slot._candidate is candidate
                with pytest.raises(RuntimeError, match="closing"):
                    await slot.activate(retry=True)
                with pytest.raises(RuntimeError):
                    await session.set_active_tools([INSPECT_SYMBOL_TOOL_NAME])
                assert not parent.is_closed

                await session.dispose()
                assert order == ["child", "child", "parent"]
                assert attempts == [candidate, candidate]
                assert slot.state == "closed"
                assert slot._candidate is None
                assert parent.is_closed
                assert candidate.graph is not None and candidate.graph.is_closed
        finally:
            await session.dispose()

    asyncio.run(scenario())


def test_active_deferred_lsp_rejects_revoked_product_selection(tmp_path: Path) -> None:
    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(project), persist=False
        )
        session = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={"coding.lsp": "on_demand"},
                        sandbox=SandboxSettings(enabled=False),
                    )
                )
            ),
        )
        try:
            await session.set_active_tools([INSPECT_SYMBOL_TOOL_NAME])
            slot = session._deferred_lsp_slot
            assert slot is not None and slot.active is not None

            def revoked() -> None:
                raise PackageProductRuntimeReadError(
                    "selected LSP revision was revoked",
                    code="selection_changed",
                )

            slot.active.current_selection_check = revoked
            with pytest.raises(CodingCapabilityPluginCompositionError) as failed:
                await session.prepare_model_call_runtime()
            assert failed.value.code == "coding_capability_product_restart_required"
        finally:
            await session.dispose()

    asyncio.run(scenario())


def test_deferred_lsp_session_reopens_with_dormant_receipt(tmp_path: Path) -> None:
    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / "pyproject.toml").touch()
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(project), persist=True
        )
        services = create_services(
            settings_manager=SettingsManager(
                ControlConfig(
                    capabilities={"coding.lsp": "on_demand"},
                    sandbox=SandboxSettings(enabled=False),
                )
            )
        )
        first = create_agent_session(
            session_manager=manager, model=_model(), services=services
        )
        try:
            assert first._deferred_lsp_slot is not None
            await first.set_active_tools([INSPECT_SYMBOL_TOOL_NAME])
            assert first._deferred_lsp_slot.state == "active"
            await manager.append_message(
                UserMessage(role="user", content="preserved", timestamp=1.0)
            )
        finally:
            await first.dispose()
        transcript = manager.get_session_file()
        assert transcript is not None

        reopened_manager = await SessionManager.load(transcript)
        reopened = create_agent_session(
            session_manager=reopened_manager, model=_model(), services=services
        )
        try:
            assert reopened._deferred_lsp_slot is not None
            assert reopened._deferred_lsp_slot.state == "dormant"
            await reopened.prepare_model_call_runtime()
            assert INSPECT_SYMBOL_TOOL_NAME not in {
                definition.name for definition in reopened.get_all_tools()
            }
            await reopened.set_active_tools([INSPECT_SYMBOL_TOOL_NAME])
            assert reopened._deferred_lsp_slot.state == "active"
        finally:
            await reopened.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Product pre-fence registration requires the admitted Linux route",
)
def test_product_selected_deferred_lsp_executes_and_reopens_dormant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    (project / "pyproject.toml").touch()
    (project / "main.py").write_text("target = 1\n", encoding="utf-8")
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    settings = SettingsManager(
        ControlConfig(sandbox=SandboxSettings(enabled=False)),
        global_settings_path=tmp_path / "settings.json",
        project_settings_path=project / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        resolve_coding_plugin_lifecycle_state_layout(project),
        settings,
        workspace=project,
        namespace_id="6" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    method_log = project / "lsp-methods.log"
    definition = LspServerDefinition(
        id="product-fake-python",
        command=(sys.executable, str(_FAKE_LSP_SERVER)),
        language_extensions={"python": (".py",)},
        root_markers=("pyproject.toml",),
        environment={"LOUSHANG_FAKE_LSP_LOG": str(method_log)},
        startup_timeout_seconds=3,
        request_timeout_seconds=3,
        shutdown_timeout_seconds=3,
    )

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(project), persist=True
        )
        transcript = None
        for reopen in (False, True):
            if reopen:
                assert transcript is not None
                manager = await SessionManager.load(transcript)
            session = create_agent_session(
                session_manager=manager,
                model=_model(),
                services=create_services(settings_manager=settings),
                lsp_definitions=(definition,),
            )
            slot = session._deferred_lsp_slot
            assert slot is not None and slot.state == "dormant"
            registry = session._composition.tool_controller.tool_registry
            assert registry is not None
            graph = None
            try:
                await session.prepare_model_call_runtime()
                parent_snapshot = session._capability_graph_runtime.snapshot
                assert slot.state == "dormant"
                status = await session.execute_command_async("lsp", "status")
                assert status is not None and status.result["enabled"] is True
                assert slot.state == "dormant"
                await session.set_active_tools([DOCUMENT_OUTLINE_TOOL_NAME])
                generation = slot.active
                assert generation is not None
                # The Product route must retain the real Desired State and
                # selected-manifest witnesses, rather than the private fallback.
                assert generation.current_selection_check is not None
                generation.assert_current()
                graph = generation.graph
                assert graph is not None
                assert session._capability_graph_runtime.snapshot is parent_snapshot
                await session.prepare_model_call_runtime()
                tool = next(
                    tool for tool in session.agent.tools
                    if tool.name == DOCUMENT_OUTLINE_TOOL_NAME
                )
                result = await tool.execute("product-outline", {"path": "main.py"})
                assert result.details["server_id"] == "product-fake-python"
                assert result.details["items"][0]["name"] == "target"
                assert session.get_lsp_status().ready_count == 1
                if not reopen:
                    await manager.append_message(
                        UserMessage(role="user", content="preserved", timestamp=1.0)
                    )
                    transcript = manager.get_session_file()
            finally:
                await session.dispose()
            assert slot.state == "closed"
            assert graph is not None and graph.is_closed
            assert _LSP_TOOL_NAMES.isdisjoint(
                definition.name for definition in registry.list_definitions()
            )
        assert method_log.read_text(encoding="utf-8").splitlines() == [
            "initialize", "initialized", "textDocument/didOpen",
            "textDocument/documentSymbol", "shutdown", "exit",
        ] * 2

    asyncio.run(scenario())


def test_historical_eager_lsp_receipt_stays_eager_on_resume(tmp_path: Path) -> None:
    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(project), persist=True
        )
        settings = SettingsManager(
            ControlConfig(
                capabilities={"coding.lsp": "always"},
                sandbox=SandboxSettings(enabled=False),
            )
        )
        first = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(settings_manager=settings),
        )
        try:
            await first.prepare_model_call_runtime()
            await manager.append_message(
                UserMessage(role="user", content="preserved", timestamp=1.0)
            )
        finally:
            await first.dispose()
        transcript = manager.get_session_file()
        assert transcript is not None

        reopened_manager = await SessionManager.load(transcript)
        reopened = create_agent_session(
            session_manager=reopened_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={"coding.lsp": "on_demand"},
                        sandbox=SandboxSettings(enabled=False),
                    )
                )
            ),
        )
        try:
            assert reopened._deferred_lsp_slot is None
            await reopened.prepare_model_call_runtime()
            assert INSPECT_SYMBOL_TOOL_NAME in {
                definition.name for definition in reopened.get_all_tools()
            }
        finally:
            await reopened.dispose()

    asyncio.run(scenario())
