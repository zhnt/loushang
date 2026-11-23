from __future__ import annotations

import asyncio
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import UserMessage
from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.execution.model import (
    ExecutionErrorCodeV1,
    ExecutionServiceErrorV1,
    ExecutionStatusV1,
)
from loushang.appserver.execution.session_commands import SessionCommandInvocationV1
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    SessionModelSelectV1,
    SessionOpenSpecV1,
    SessionSnapshotRequestV1,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.remote_client import RemoteAppClientV1
from loushang.appservice.client_scope import ScopedAppServiceV1
from loushang.appservice.runtime import AppServiceV1
from loushang.coding.control import CompactionSettings, ControlConfig, SettingsManager
from loushang.coding.hosted.execution import (
    CodingHostedExecutionSessionV1,
    create_coding_execution_service_binding,
)
from loushang.coding.session.manager import SessionManager
from loushang.harness.model_catalog import ModelCatalog
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution
from loushang.harness.transcript import CompactionResult
from loushang.harnesstui.mux.shell import HostedMuxShellV1
from loushang.tui.core import RenderConstraints
from loushang.tui.input import InputEvent
from tests.appserver.test_connection import _pair

from .lsp.test_fake_launcher_vertical_slice import FakeLauncher
from .lsp.test_fake_launcher_vertical_slice import _binding as _lsp_binding
from .test_agent_session import _ai_model_registry
from .test_hosted_execution import _binding, _message
from .test_hosted_execution import _private_home as _private_home


@asynccontextmanager
async def _remote(scope) -> AsyncIterator[RemoteAppClientV1]:
    left, right = _pair()
    profile = AppConnectionProfileV1.LOCAL_EXECUTION
    server = AppServerConnectionV1(
        scope,
        AppFramedStreamV1(right),
        profile=profile,
        execution=scope.execution_client,
    )
    serving = asyncio.create_task(server.serve())
    remote = RemoteAppClientV1(
        AppFramedStreamV1(left), profile=profile, session_thinking=True
    )
    try:
        await remote.start()
        yield remote
    finally:
        await remote.close()
        await serving


@asynccontextmanager
async def _service(binding):
    hosted = CodingHostedExecutionSessionV1(binding)
    identity = binding.identity

    class Resolver:
        async def open_session(self, request):
            assert request.session_id == identity.session_id
            return hosted

    service = AppServiceV1(
        product_id="coding",
        resolver=Resolver(),
        execution=create_coding_execution_service_binding(
            "application", service_instance_id="instance"
        ),
    )
    owner = ScopedAppServiceV1(service)
    scope = owner.open_client_scope()
    try:
        mux = await scope.create_mux(MuxCreateV1("commands"))
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        await scope.attach_mux(MuxAttachV1(selector))
        mux = await scope.open_member(
            MuxMemberOpenV1(
                selector,
                SessionOpenSpecV1(
                    identity.product_id,
                    identity.continuity_id,
                    identity.scope,
                    identity.scope_fingerprint,
                    "commands",
                    identity.session_id,
                ),
            )
        )
        yield owner, scope, selector, mux.members[0].member_id
    finally:
        await service.close()


async def _submit(shell, text):
    shell.handle(InputEvent(kind="paste", text=text))
    shell.handle(InputEvent(kind="key", key="enter"))
    async with asyncio.timeout(3):
        while shell.pending_actions:
            await asyncio.sleep(0.01)


def _screen(shell) -> str:
    return "\n".join(
        line.text
        for line in shell.screen.render(
            RenderConstraints(width=120, max_height=64, visible_height=64),
        ).lines
    )


def _tool(name):
    async def invoke(_args, _ctx):
        pytest.fail("tool selection must never call a tool")

    return ToolDefinition(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object"},
        execution=direct_execution(invoke),
    )


def test_model_free_session_and_governed_tool_selection_in_hosted_tui(tmp_path):
    async def scenario():
        binding, session = await _binding(
            tmp_path,
            model_available=False,
            tools=(_tool("one"), _tool("two"), _tool("denied")),
            allowed_tool_names=["one", "two"],
        )
        async with _service(binding) as (_, scope, selector, member):
            async with _remote(scope) as remote:
                shell = HostedMuxShellV1(
                    remote,
                    selector=selector,
                    product_id="coding",
                    scopes=(
                        (binding.identity.scope, binding.identity.scope_fingerprint),
                    ),
                )
                try:
                    await shell.start()
                    state = shell.state
                    control = SessionSnapshotRequestV1(
                        state.attachment_id, state.controller_generation, member
                    )
                    client = remote.execution_client
                    catalog = await client.session_command_catalog(
                        control, "instance", "/tools on "
                    )
                    entries = {item.name: item for item in catalog.commands}
                    assert entries["compact"].unavailable_reason == "model_required"
                    assert entries["session"].read_only
                    assert entries["reload"].unavailable_reason
                    assert set(catalog.completions) == {"on one", "on two"}
                    with pytest.raises(AppServiceError) as denied:
                        await client.read_session_command(
                            control,
                            "instance",
                            SessionCommandInvocationV1("tools", "off one"),
                        )
                    assert denied.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE

                    await _submit(shell, "/session")
                    assert session.session_id in _screen(shell)
                    shell.handle(InputEvent(kind="key", key="esc"))
                    await _submit(shell, "/tools only two")
                    assert shell.notice == "Session command succeeded"
                    assert session.get_active_tool_names() == ["two"]
                    assert '"allowed": false' in _screen(shell)
                    shell.handle(InputEvent(kind="key", key="esc"))
                    tools = await client.read_session_command(
                        control, "instance", SessionCommandInvocationV1("tools")
                    )
                    assert tools.data["active_tools"] == ["two"]
                    assert {"name": "denied", "description": "denied",
                            "active": False, "allowed": False} in tools.data["available_tools"]
                    await _submit(shell, "/tools")
                    assert '"active_tools"' in _screen(shell)
                    shell.handle(InputEvent(kind="key", key="esc"))
                    await _submit(shell, "/tools on denied")
                    assert "command_invalid_arguments" in shell.notice
                    assert session.get_active_tool_names() == ["two"]
                    assert session.messages == []
                finally:
                    await shell.close()

    asyncio.run(scenario())


def test_hosted_compaction_survives_detach_and_same_id_never_replays(
    tmp_path, monkeypatch
):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def summarize(**kwargs):
            calls.append(kwargs["custom_instructions"])
            started.set()
            await release.wait()
            preparation = kwargs["preparation"]
            return CompactionResult(
                "summary", preparation.first_kept_entry_id, preparation.tokens_before
            )

        monkeypatch.setattr(
            "loushang.coding.session.agent_session._execute_coding_compaction",
            summarize,
        )
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), persist=False
        )
        for i in range(3):
            await manager.append_message(
                UserMessage(role="user", content=f"Previous context {i}", timestamp=i)
            )
            await manager.append_message(_message())
        settings = SettingsManager(
            ControlConfig(compaction=CompactionSettings(keep_recent_tokens=1))
        )
        binding, session = await _binding(
            tmp_path, manager=manager, settings_manager=settings
        )
        invocation = SessionCommandInvocationV1("compact", "preserve  design")
        async with _service(binding) as (owner, scope, selector, member):
            async with _remote(scope) as remote:
                shell = HostedMuxShellV1(
                    remote,
                    selector=selector,
                    product_id="coding",
                    scopes=(
                        (binding.identity.scope, binding.identity.scope_fingerprint),
                    ),
                )
                await shell.start()
                state = shell.state
                control = SessionSnapshotRequestV1(
                    state.attachment_id, state.controller_generation, member
                )
                client = remote.execution_client
                shell.handle(InputEvent(kind="paste", text="/compact preserve  design"))
                shell.handle(InputEvent(kind="key", key="enter"))
                await asyncio.wait_for(started.wait(), 2)
                submission_id = shell.notice.rsplit(" ", 1)[-1]
                first = await client.find_execution_by_submission(
                    control, "instance", submission_id
                )
                duplicate = await client.submit_session_command(
                    control, "instance", submission_id, invocation
                )
                assert duplicate.state.execution_id == first.state.execution_id
                with pytest.raises(ExecutionServiceErrorV1) as busy:
                    await client.submit_session_command(
                        control,
                        "instance",
                        "busy-tools",
                        SessionCommandInvocationV1("tools"),
                    )
                assert busy.value.code is ExecutionErrorCodeV1.BUSY
                view = await client.read_session_command(
                    control, "instance", SessionCommandInvocationV1("session")
                )
                assert view.data["session"]["is_compacting"] is True
                inventory = await client.read_session_command(
                    control, "instance", SessionCommandInvocationV1("tools")
                )
                assert isinstance(inventory.data["available_tools"], list)
                await shell.close()
            await scope.close()

            reconnect = owner.open_client_scope()
            async with _remote(reconnect) as remote:
                attach = await remote.attach_mux(MuxAttachV1(selector))
                current = SessionSnapshotRequestV1(
                    attach.attachment_id, attach.controller_generation, member
                )
                client = remote.execution_client
                with pytest.raises(AppServiceError):
                    await client.read_session_command(
                        control, "instance", SessionCommandInvocationV1("session")
                    )
                found = await client.find_execution_by_submission(
                    current, "instance", submission_id
                )
                assert found.state.execution_id == first.state.execution_id
                release.set()
                async with asyncio.timeout(3):
                    while not found.state.status.terminal:
                        await asyncio.sleep(0.01)
                        found = await client.get_execution(
                            current, "instance", found.state.execution_id
                        )
                assert found.state.status is ExecutionStatusV1.SUCCEEDED
                result = await client.session_command_result(
                    current, "instance", found.state.execution_id
                )
                assert result.data["result"]["summary"] == "summary"
                assert calls == ["preserve  design"]
                assert session.get_compaction_status().last_succeeded is True

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("terminal", ["failed", "interrupted"])
def test_hosted_tui_reports_compaction_failure_and_targeted_interrupt(
    tmp_path, monkeypatch, terminal
):
    async def scenario():
        started = asyncio.Event()

        async def summarize(**_kwargs):
            started.set()
            if terminal == "failed":
                raise RuntimeError("private provider failure")
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        monkeypatch.setattr(
            "loushang.coding.session.agent_session._execute_coding_compaction",
            summarize,
        )
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), persist=False
        )
        await manager.append_message(
            UserMessage(role="user", content="Old context", timestamp=0)
        )
        await manager.append_message(_message())
        settings = SettingsManager(
            ControlConfig(compaction=CompactionSettings(keep_recent_tokens=1))
        )
        binding, session = await _binding(
            tmp_path, manager=manager, settings_manager=settings
        )
        record_count = len(manager.get_entries())
        async with _service(binding) as (_, scope, selector, member):
            async with _remote(scope) as remote:
                shell = HostedMuxShellV1(
                    remote,
                    selector=selector,
                    product_id="coding",
                    scopes=(
                        (binding.identity.scope, binding.identity.scope_fingerprint),
                    ),
                )
                try:
                    await shell.start()
                    if terminal == "failed":
                        await _submit(shell, "/compact")
                    else:
                        shell.handle(InputEvent(kind="text", text="/compact"))
                        shell.handle(InputEvent(kind="key", key="enter"))
                        await asyncio.wait_for(started.wait(), 2)
                        # The receipt is published on this same connection.
                        submission_id = shell.notice.rsplit(" ", 1)[-1]
                        state = shell.state
                        control = SessionSnapshotRequestV1(
                            state.attachment_id, state.controller_generation, member
                        )
                        assert (
                            await remote.execution_client.find_execution_by_submission(
                                control, "instance", submission_id
                            )
                        )
                        await _submit(shell, "/interrupt")
                    assert shell.notice.startswith(f"Session command {terminal}")
                    assert "private provider failure" not in _screen(shell)
                    assert len(manager.get_entries()) == record_count
                    assert not session.get_compaction_status().is_compacting
                finally:
                    await shell.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_phase_two_model_rename_and_extension_commands(tmp_path):
    async def scenario():
        first = Model(
            id="faux",
            provider="faux",
            endpoint="anthropic-messages",
            name="Faux",
            capabilities=Capabilities(input=("text",), context_window=128000),
        )
        second = Model(
            id="reasoner",
            provider="example",
            endpoint="responses",
            api="openai-responses",
            name="Reasoner",
            capabilities=Capabilities(
                input=("text",),
                context_window=64000,
                reasoning=True,
                reasoning_efforts=("low", "high"),
                reasoning_required=False,
            ),
        )
        catalog = ModelCatalog(ai_registry=_ai_model_registry(first, second))

        async def extension_command(args, context):
            pytest.fail("Inspecting an extension must not invoke one of its commands")

        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), persist=True
        )
        await manager.append_message(
            UserMessage(role="user", content="Existing conversation", timestamp=0)
        )
        binding, session = await _binding(
            tmp_path,
            command=extension_command,
            model_registry=catalog,
            manager=manager,
        )
        async with _service(binding) as (owner, scope, selector, member):
            async with _remote(scope) as remote:
                shell = HostedMuxShellV1(
                    remote,
                    selector=selector,
                    product_id="coding",
                    scopes=(
                        (binding.identity.scope, binding.identity.scope_fingerprint),
                    ),
                )
                try:
                    await shell.start()
                    state = shell.state
                    control = SessionSnapshotRequestV1(
                        state.attachment_id, state.controller_generation, member
                    )

                    await _submit(shell, "/commands")
                    assert all(
                        f"/{name}" in _screen(shell)
                        for name in ("model", "models", "rename", "extensions", "lsp")
                    )
                    shell.handle(InputEvent(kind="key", key="esc"))
                    await _submit(shell, "/models")
                    assert "faux:anthropic-messages:faux" in _screen(shell)
                    assert "(current)" in _screen(shell)
                    assert "example:responses:reasoner" in _screen(shell)
                    shell.handle(InputEvent(kind="key", key="esc"))

                    await _submit(shell, "/model")
                    assert shell.screen._model_picker is not None
                    shell.handle(InputEvent(kind="text", text="reasoner"))
                    shell.handle(InputEvent(kind="key", key="enter"))
                    async with asyncio.timeout(3):
                        while shell.pending_actions:
                            await asyncio.sleep(0.01)
                    assert (
                        shell.state.active_window.model_label
                        == "example:responses:reasoner"
                    ), shell.notice
                    shell.handle(InputEvent(kind="key", key="esc"))
                    await _submit(shell, "/model --thinking high")
                    assert session.thinking_level == "high"
                    shell.handle(InputEvent(kind="key", key="esc"))
                    await _submit(shell, "/model --thinking medium")
                    assert session.thinking_level == "high"
                    shell.handle(InputEvent(kind="key", key="esc"))
                    await _submit(shell, "/model nonexistent")
                    assert "No models match" in _screen(shell)
                    assert session.agent.model.id == "reasoner"
                    shell.handle(InputEvent(kind="key", key="esc"))
                    with pytest.raises(AppServiceError):
                        await remote.select_session_model(
                            SessionModelSelectV1(
                                control.attachment_id,
                                control.controller_generation,
                                member,
                                "example:responses:reasoner",
                                "medium",
                            )
                        )
                    assert session.thinking_level == "high"

                    await _submit(shell, "/rename")
                    assert shell.screen.composer.value == "/rename "
                    await _submit(shell, "Saved title")
                    assert session.session_name == "Saved title"
                    await shell.poll()
                    assert shell.state.active_window.title == "Saved title"
                    assert (await remote.read_mux(MuxReadV1(selector))).members[
                        0
                    ].title == "Saved title"
                    assert (
                        await remote.snapshot_session(control)
                    ).title == "Saved title"
                    shell.handle(InputEvent(kind="key", key="esc"))

                    await _submit(shell, "/extensions execution-test")
                    assert "execution-test" in _screen(shell)
                    assert str(tmp_path) not in _screen(shell)
                    shell.handle(InputEvent(kind="key", key="esc"))
                    await _submit(shell, "/extensions missing")
                    assert "Unknown extension" in _screen(shell)
                finally:
                    await shell.close()
            await scope.close()
            reconnect = owner.open_client_scope()
            async with _remote(reconnect) as remote:
                attached = await remote.attach_mux(MuxAttachV1(selector))
                assert attached.sessions[0].member.title == "Saved title"
                with pytest.raises(AppServiceError):
                    await remote.select_session_model(
                        SessionModelSelectV1(
                            control.attachment_id,
                            control.controller_generation,
                            member,
                            "faux:anthropic-messages:faux",
                        )
                    )
        saved = await SessionManager.open(session.get_session_file(), persist=True)
        try:
            assert saved.get_session_record().metadata.name == "Saved title"
        finally:
            await saved.dispose_runtime_profile()

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_phase_two_lsp_stop_uses_guard_and_session_owned_runtime(tmp_path):
    async def scenario():
        release, entered = asyncio.Event(), asyncio.Event()

        async def work(args, context):
            entered.set()
            await release.wait()

        binding, session = await _binding(tmp_path, command=work)
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        launcher = FakeLauncher(definition_result=None)
        lsp = _lsp_binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})
        session._lsp_access = lsp
        await lsp.inspect_symbol(
            path="main.py", line=1, character=1, correlation_id="hosted-status"
        )
        try:
            async with _service(binding) as (_, scope, selector, member):
                async with _remote(scope) as remote:
                    shell = HostedMuxShellV1(
                        remote,
                        selector=selector,
                        product_id="coding",
                        scopes=(
                            (
                                binding.identity.scope,
                                binding.identity.scope_fingerprint,
                            ),
                        ),
                    )
                    try:
                        await shell.start()
                        state = shell.state
                        control = SessionSnapshotRequestV1(
                            state.attachment_id, state.controller_generation, member
                        )
                        client = remote.execution_client
                        await _submit(shell, "/lsp status")
                        assert '"ready_count": 1' in _screen(shell)
                        shell.handle(InputEvent(kind="key", key="esc"))
                        stop = f"stop fake-python {shlex.quote(str(tmp_path))}"
                        with pytest.raises(AppServiceError):
                            await client.read_session_command(
                                control,
                                "instance",
                                SessionCommandInvocationV1("lsp", stop),
                            )
                        running = await client.submit_execution(
                            control, "instance", "in-flight", "/work"
                        )
                        await asyncio.wait_for(entered.wait(), 3)
                        for command in (
                            SessionCommandInvocationV1("lsp", stop),
                            SessionCommandInvocationV1("rename", "Busy"),
                        ):
                            with pytest.raises(ExecutionServiceErrorV1) as busy:
                                await client.submit_session_command(
                                    control, "instance", command.name, command
                                )
                            assert busy.value.code is ExecutionErrorCodeV1.BUSY
                        with pytest.raises(AppServiceError) as busy_model:
                            await remote.select_session_model(
                                SessionModelSelectV1(
                                    control.attachment_id,
                                    control.controller_generation,
                                    member,
                                    "faux:anthropic-messages:faux",
                                )
                            )
                        assert (
                            busy_model.value.code
                            is AppErrorCodeV1.OPERATION_UNAVAILABLE
                        )
                        release.set()
                        async with asyncio.timeout(3):
                            while not (
                                await client.get_execution(
                                    control, "instance", running.state.execution_id
                                )
                            ).state.status.terminal:
                                await asyncio.sleep(0.01)
                        await _submit(
                            shell,
                            f"/lsp stop fake-python {shlex.quote(str(tmp_path.parent))}",
                        )
                        assert "must stay within" in _screen(shell)
                        assert lsp.status().ready_count == 1
                        shell.handle(InputEvent(kind="key", key="esc"))
                        await _submit(shell, f"/lsp {stop}")
                        assert '"stopped": true' in _screen(shell)
                        assert launcher.handles[0].server.methods()[-2:] == [
                            "shutdown",
                            "exit",
                        ]
                        shell.handle(InputEvent(kind="key", key="esc"))
                        await _submit(shell, "/lsp")
                        assert '"state": "stopped"' in _screen(shell)
                    finally:
                        release.set()
                        await shell.close()
        finally:
            await lsp.dispose()

    asyncio.run(asyncio.wait_for(scenario(), 15))
