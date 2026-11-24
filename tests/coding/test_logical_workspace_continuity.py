"""Exercise logical Workspace membership through real Coding and AppService owners."""

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
from secrets import token_hex

import pytest

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.types import ToolCall, ToolResultMessage
from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.managed_mux import ManagedMuxCreateV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionOpenSpecV1,
    SessionSnapshotRequestV1,
    WorkspaceRequestV1,
)
from loushang.appservice.execution_contract import ExecutionStatusV1
from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from loushang.coding.managed_bootstrap import (
    CodingManagedApplicationLaunchV1,
    create_coding_managed_attempt,
)
from loushang.coding.managed_local import (
    CodingManagedLocalCommandV1,
    CodingManagedLocalLaunchV1,
)
from loushang.harness.transcript import lifecycle

from .test_hosted_session import _model, _stream, synthetic_model_transport


def test_workspace_continuity_survives_directory_loss_and_rebinding(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    launch = CodingManagedApplicationLaunchV1(
        tmp_path, tmp_path / "application", "coding.logical-workspaces", tmp_path / "sessions",
    )
    old = tmp_path / "original"
    old.mkdir()
    replacement = tmp_path / "replacement"
    replacement.mkdir()

    backend = tmp_path / "other" / "backend"
    backend.mkdir(parents=True)
    denied = tmp_path / "outside"
    denied.mkdir()
    (denied / "notes.txt").write_text("private", encoding="utf-8")
    calls = {
        "exercise": [
            ("write", {"path": "notes.txt", "content": "frontend"}),
            ("write", {"path": str(backend / "notes.txt"), "content": "backend"}),
            ("read", {"path": "notes.txt"}),
            ("read", {"path": str(backend / "notes.txt")}),
            ("command", {"cwd": str(replacement), "command": "printf frontend > command.txt"}),
            ("command", {"cwd": str(backend), "command": "printf backend > command.txt"}),
        ],
        "partial": [
            ("read", {"path": "notes.txt"}),
            ("read", {"path": str(backend / "notes.txt")}),
        ],
        "no-default": [
            ("read", {"path": "notes.txt"}),
            ("read", {"path": str(replacement / "notes.txt")}),
        ],
    }
    results = {}
    active_script = None

    @synthetic_model_transport
    async def stream(model, context, options=None):
        ordinary = await _stream(model, context, options)
        label = active_script
        if label is None:
            return ordinary
        completed = [message for message in context.messages if isinstance(message, ToolResultMessage)
                     and message.tool_call_id.startswith(f"{label}-")]
        index = len(completed)
        if index == len(calls[label]):
            results[label] = completed
            return ordinary
        name, arguments = calls[label][index]
        if name == "command":
            name = next(tool.name for tool in context.tools if tool.name in {"bash", "shell"})
        tool_call = ToolCall(type="toolCall", id=f"{label}-{index}", name=name, arguments=arguments)
        message = replace(await ordinary.result(), content=[tool_call], stop_reason="toolUse")
        turn = AssistantMessageEventStream()
        turn.push({"type": "done", "reason": "toolUse", "message": message})
        return turn

    @asynccontextmanager
    async def host():
        attempt = create_coding_managed_attempt(launch, model=_model(), stream_fn=stream)
        app = await attempt.open()
        app.enable_client_scopes()
        client = app.open_client_scope()
        try:
            yield client
        finally:
            await client.close()
            await app.close()
            await attempt.close()

    async def member(client, info, continuity, *, title=None, existing_mux=False):
        assert info.workspace is not None
        mux_name = info.workspace["muxName"]
        assert isinstance(mux_name, str)
        selector = MuxSelectorV1(name=mux_name)
        if not existing_mux:
            await client.create_mux(MuxCreateV1(mux_name))
        await client.attach_mux(MuxAttachV1(selector))
        created = await client.open_member(MuxMemberOpenV1(
            selector, SessionOpenSpecV1("coding", continuity, info.scope, info.scope_fingerprint, title or continuity),
        ))
        return created.members[-1].session

    controls = {}
    approvals = {}

    async def control(client, mux_name, identity):
        key = (client, mux_name, identity)
        if key in controls:
            return controls[key]
        attachment = await client.attach_mux(MuxAttachV1(MuxSelectorV1(name=mux_name)))
        selected = next(item for item in attachment.mux_space.members if item.session == identity)
        request = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation, selected.member_id)
        controls[key] = request
        return request

    async def talk(client, mux, identity, text):
        request = await control(client, mux, identity)
        execution = client.execution_client
        instance = execution.service_instance_id
        record = await execution.submit_execution(request, instance, text, text)
        approvals[text] = 0
        async with asyncio.timeout(15):
            while not record.state.status.terminal:
                for envelope in await client.read_events(
                    attachment_id=request.attachment_id, controller_generation=request.controller_generation,
                ):
                    event = envelope.event
                    if event.kind is SessionEventKindV1.INTERACTION_REQUESTED:
                        approvals[text] += 1
                        await client.respond_interaction(InteractionRespondV1(
                            request.attachment_id, request.controller_generation, request.member_id,
                            event.interaction_id, InteractionOutcomeV1.APPROVE,
                        ))
                await asyncio.sleep(0.01)
                record = await execution.get_execution(request, instance, record.state.execution_id)
        assert record.state.status is ExecutionStatusV1.SUCCEEDED
        return await client.snapshot_session(request)

    async def scenario():
        nonlocal active_script
        async with host() as client:
            empty = (await client.workspace(WorkspaceRequestV1("create-workspace", name="Empty"))).workspaces[0]
            assert empty.workspace["paths"] == []
            await client.workspace(WorkspaceRequestV1("delete-workspace", workspace_id=empty.workspace["id"]))
            await client.workspace(WorkspaceRequestV1("register", str(old)))
            directory = (await client.workspace(WorkspaceRequestV1("workspaces"))).workspaces
            project, = (row for row in directory if row.workspace and not row.workspace["default"])
            default, = (row for row in directory if row.workspace and row.workspace["default"])
            legacy_default = (await client.workspace(WorkspaceRequestV1("allocate-temporary"))).workspaces[0]
            assert legacy_default.scope_fingerprint == default.scope_fingerprint
            workspace_id = project.workspace["id"]
            mux = project.workspace["muxName"]
            legacy = (await client.workspace(WorkspaceRequestV1("open", str(old)))).workspaces[0]
            original = await member(client, replace(legacy, workspace=project.workspace), "gui-draft-original", title="新会话")
            chat = await member(client, default, "gui-draft-chat", title="New Session")
            await talk(client, mux, original, "before")
            await talk(client, "gui-temporary", chat, "default-before")
            for name, identity in ((mux, original), ("gui-temporary", chat)):
                request = await control(client, name, identity)
                async with asyncio.timeout(5):
                    while (await client.snapshot_session(request)).title != "real Coding response":
                        await asyncio.sleep(0.01)

        shutil.rmtree(old)
        async with host() as client:
            directory = await client.list_muxes()
            titles = {entry.session: entry.title for space in directory.mux_spaces for entry in space.members}
            assert titles[original] == titles[chat] == "real Coding response"
            retained = (await client.workspace(WorkspaceRequestV1("open-workspace", workspace_id=workspace_id))).workspaces[0]
            link = retained.workspace["paths"][0]
            assert link["status"] == "missing"
            assert retained.scope_fingerprint == project.scope_fingerprint
            snapshot = await talk(client, mux, original, "missing")
            assert {"before", "missing"} <= {row.text for row in snapshot.records}
            await talk(client, "gui-temporary", chat, "default-after")
            fresh = await member(client, retained, "new-while-missing", existing_mux=True)
            assert fresh.scope_fingerprint == retained.scope_fingerprint
            assert fresh.scope_fingerprint != original.scope_fingerprint
            await client.workspace(WorkspaceRequestV1(
                "update-path", path=str(replacement), workspace_id=workspace_id, path_id=link["id"], alias="main",
            ))
            await client.workspace(WorkspaceRequestV1(
                "add-path", path=str(backend), workspace_id=workspace_id, alias="backend",
            ))

        async with host() as client:
            row = (await client.workspace(WorkspaceRequestV1("open-workspace", workspace_id=workspace_id))).workspaces[0]
            assert row.workspace["paths"][0]["path"] == str(replacement)
            assert row.workspace["muxName"] == mux
            assert row.scope_fingerprint == project.scope_fingerprint
            mux_view = await client.read_mux(MuxReadV1(MuxSelectorV1(name=mux)))
            assert {entry.session for entry in mux_view.members} == {original, fresh}
            snapshot = await talk(client, mux, original, "rebound")
            assert {"before", "missing", "rebound"} <= {item.text for item in snapshot.records}
            await control(client, "gui-temporary", chat)
            active_script = "exercise"
            await talk(client, mux, original, "exercise")
            assert all(not item.is_error for item in results["exercise"]), results["exercise"]
            assert approvals["exercise"] >= len(calls["exercise"])
            assert (replacement / "notes.txt").read_text(encoding="utf-8") == "frontend"
            assert (backend / "notes.txt").read_text(encoding="utf-8") == "backend"
            assert (replacement / "command.txt").read_text(encoding="utf-8") == "frontend"
            assert (backend / "command.txt").read_text(encoding="utf-8") == "backend"

            backend.rename(backend.with_name("offline"))
            backend.symlink_to(denied, target_is_directory=True)
            active_script = "partial"
            await talk(client, mux, original, "partial")
            assert [item.is_error for item in results["partial"]] == [False, True]
            assert (denied / "notes.txt").read_text(encoding="utf-8") == "private"
            await client.workspace(WorkspaceRequestV1("set-default-path", workspace_id=workspace_id))
            active_script = "no-default"
            await talk(client, mux, original, "no-default")
            assert [item.is_error for item in results["no-default"]] == [True, False]

            active_script = None
            replacement.rename(replacement.with_name("inactive-frontend"))
            snapshot = await talk(client, mux, original, "lost-while-open")
            assert "lost-while-open" in {item.text for item in snapshot.records}


    asyncio.run(scenario())


@pytest.mark.parametrize("legacy", [False, True])
def test_delete_workspace_removes_attached_and_detached_history_only(tmp_path, monkeypatch, legacy):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    launch = CodingManagedApplicationLaunchV1(
        tmp_path, tmp_path / "application", "coding.delete-workspace", tmp_path / "sessions",
    )
    project = tmp_path / "project"
    project.mkdir()
    source = project / "keep.txt"
    source.write_bytes(b"project data")
    missing = tmp_path / "missing"
    missing.mkdir()
    if legacy:
        registry = tmp_path / "workspaces"
        registry.mkdir(mode=0o700)
        record = registry / "workspaces.json"
        record.write_text(json.dumps(sorted((str(project), str(missing)))), encoding="utf-8")
        record.chmod(0o600)

    @asynccontextmanager
    async def host():
        class Admission:
            async def acquire(self):
                pass

            def check_creation(self, previous):
                pass

            async def close(self):
                pass

        instance = token_hex(16)
        service = "a" * 64

        async def ensure_named(name, commit):
            await commit(ManagedMuxCreateV1(service, instance, sha256(name.encode()).hexdigest()[:32], name, "test"))

        binding = ManagedMuxServiceBindingV1(
            launch.application_id, service, instance, lambda _: Admission(), ensure_named=ensure_named,
        )
        local = CodingManagedLocalLaunchV1(
            launch, tmp_path / "connection", "workspace", instance_id=instance, managed_mux=binding,
        )
        command = CodingManagedLocalCommandV1(local, model=_model(), stream_fn=_stream)
        connection = LocalAppClientConnectionV1(
            LocalConnectionDirectoryV1(local.connection_root), local.endpoint,
        )
        try:
            await command.start()
            await connection.start()
            yield connection.client
        finally:
            await connection.close()
            await command.close()

    async def opened(client, info, mux, title):
        selector = MuxSelectorV1(name=mux)
        await client.attach_mux(MuxAttachV1(selector))
        space = await client.open_member(MuxMemberOpenV1(
            selector, SessionOpenSpecV1("coding", title, info.scope, info.scope_fingerprint, title),
        ))
        member = space.members[-1]
        attachment = await client.attach_mux(MuxAttachV1(selector))
        request = SessionSnapshotRequestV1(
            attachment.attachment_id, attachment.controller_generation, member.member_id,
        )
        execution = client.execution_client
        record = await execution.submit_execution(request, execution.service_instance_id, title, title)
        async with asyncio.timeout(10):
            while not record.state.status.terminal:
                await asyncio.sleep(0.01)
                record = await execution.get_execution(request, execution.service_instance_id, record.state.execution_id)
        assert record.state.status is ExecutionStatusV1.SUCCEEDED
        return member

    async def scenario():
        async with host() as client:
            if legacy:
                by_name = {
                    row.workspace["name"]: row
                    for row in (await client.workspace(WorkspaceRequestV1("workspaces"))).workspaces
                }
                workspace = by_name["project"]
                original, = (await client.workspace(WorkspaceRequestV1("open", str(project)))).workspaces
            else:
                workspace, = (await client.workspace(WorkspaceRequestV1(
                    "create-workspace", name="Project", path=str(project), alias="main",
                ))).workspaces
                original = workspace
            workspace_id = workspace.workspace["id"]
            mux = workspace.workspace["muxName"]
            await client.workspace(WorkspaceRequestV1(
                "add-path", path=str(missing), workspace_id=workspace_id, alias="missing",
            ))
            missing.rmdir()
            if legacy:
                await client.workspace(WorkspaceRequestV1(
                    "delete-workspace-with-history", workspace_id=by_name["missing"].workspace["id"],
                ))
            await client.workspace(WorkspaceRequestV1("open-workspace", workspace_id=workspace_id))
            detached = await opened(client, original, mux, "detached")
            await client.close_member(MuxMemberCloseV1(MuxSelectorV1(name=mux), detached.member_id))
            attached = await opened(client, workspace, mux, "attached")
            default, = (await client.workspace(WorkspaceRequestV1("allocate-temporary"))).workspaces
            other = await opened(client, default, "gui-temporary", "keep-other-chat")

            def history(member):
                path, = launch.session_root.rglob(f"hosted-{member.session.session_id}.jsonl")
                return path

            removed = (history(detached), history(attached))
            retained = history(other)
            with pytest.raises(AppServiceError) as old_client:
                await client.workspace(WorkspaceRequestV1("delete-workspace", workspace_id=workspace_id))
            assert old_client.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE

            deletion = WorkspaceRequestV1("delete-workspace-with-history", workspace_id=workspace_id)
            if legacy:
                delete_transcript = lifecycle.delete_agent_transcript_jsonl

                async def fail_on_detached(path, **options):
                    if path == removed[0]:
                        raise OSError("injected transcript deletion failure")
                    return await delete_transcript(path, **options)

                with monkeypatch.context() as fail:
                    fail.setattr(lifecycle, "delete_agent_transcript_jsonl", fail_on_detached)
                    with pytest.raises(AppServiceError) as incomplete:
                        await client.workspace(deletion)
                assert incomplete.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
                assert not removed[1].exists()
                assert removed[0].is_file()
                assert source.read_bytes() == b"project data"

            await client.workspace(deletion)
            assert (await client.workspace(deletion)).workspaces == ()
            assert all(not path.exists() for path in removed)
            assert retained.is_file()
            assert source.read_bytes() == b"project data"
            assert not missing.exists()

        async with host() as client:
            remaining, = (await client.workspace(WorkspaceRequestV1("workspaces"))).workspaces
            assert remaining.workspace["default"]
            muxes = await client.list_muxes()
            assert [member.session for space in muxes.mux_spaces for member in space.members] == [other.session]
            assert all(not path.exists() for path in removed)
            assert source.read_bytes() == b"project data"

    asyncio.run(scenario())
