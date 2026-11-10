"""Model selection through real AppHost owners and the scoped client."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager

import pytest

from loushang.ai.model import ModelSelection
from loushang.ai.model.selection import model_selection_ref
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionModelSelectV1,
    SessionOpenSpecV1,
    SessionSnapshotRequestV1,
)
from loushang.appservice.execution_contract import ExecutionStatusV1
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.hosted_bootstrap import create_coding_hosted_attempt
from loushang.coding.hosted_resume import CodingDeferredHostedSessionV1
from loushang.coding.managed_bootstrap import (
    CodingManagedApplicationLaunchV1,
    create_coding_managed_attempt,
)
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.harness.config.agent import SettingsManager
from loushang.harness.transcript.kinds import MODEL_SELECTION_KIND

from .test_hosted_bootstrap import _launch
from .test_hosted_session import _stream

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="owned hosted transcript Writer")


@pytest.mark.parametrize("managed", [True, False], ids=["managed", "deferred"])
def test_apphost_models_restore_before_input_and_reject_without_consuming_submission(
    tmp_path, monkeypatch, managed,
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    home = tmp_path / "user-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    project_path = default_project_settings_path(tmp_path)
    global_path = default_global_settings_path()
    selection_a = ModelSelection("faux", "anthropic-messages", "first")
    selection_b = ModelSelection("faux", "anthropic-messages", "faux-model")
    first_id, second_id = model_selection_ref(selection_a), model_selection_ref(selection_b)
    available = {first_id, second_id}
    catalog_path = project_path.parent / "models" / "faux.json"
    catalog_path.parent.mkdir(parents=True)
    models = {
        model_id: {"displayName": model_id, "capabilities": {"input": ["text"], "stream": True}}
        for model_id in (selection_a.model_id, selection_b.model_id)
    }

    def write_catalog():
        catalog_path.write_text(json.dumps({"providers": {"faux": {"endpoints": {
            "anthropic-messages": {
                "api": "anthropic-messages", "baseUrl": "https://models.example.invalid", "models": models,
            },
        }}}}), encoding="utf-8")

    write_catalog()

    def settings():
        return SettingsManager(global_settings_path=global_path, project_settings_path=project_path)

    launch = (
        CodingManagedApplicationLaunchV1(tmp_path, tmp_path / "application", "coding.models", tmp_path / "sessions")
        if managed else _launch(tmp_path)
    )
    scope = launch.scopes[0]
    scope.session_dir.mkdir(mode=0o700)

    @asynccontextmanager
    async def host():
        if managed:
            attempt = create_coding_managed_attempt(launch, stream_fn=_stream, tools=[])
        else:
            attempt = create_coding_hosted_attempt(launch, stream_fn=_stream, tools=[], owned_transcripts=True)
        app = await attempt.open()
        app.enable_client_scopes()
        client = app.open_client_scope()
        try:
            yield client
        finally:
            await client.close()
            await app.close()
            await attempt.close()

    async def open_session(client, continuity, *, create=False, session_id=None):
        selector = MuxSelectorV1(name="models")
        if create:
            await client.create_mux(MuxCreateV1("models"))
        attachment = await client.attach_mux(MuxAttachV1(selector))
        member = next((m for m in attachment.mux_space.members if m.session.continuity_id == continuity), None)
        if member is None:
            mux = await client.open_member(MuxMemberOpenV1(
                selector,
                SessionOpenSpecV1("coding", continuity, scope.scope, scope.fingerprint, continuity, session_id),
            ))
            member = next(m for m in mux.members if m.session.continuity_id == continuity)
            attachment = await client.attach_mux(MuxAttachV1(selector))
        return SessionSnapshotRequestV1(
            attachment.attachment_id, attachment.controller_generation, member.member_id,
        ), member.session.session_id

    async def select(client, control, model_id):
        return await client.select_session_model(SessionModelSelectV1(
            control.attachment_id, control.controller_generation, control.member_id, model_id,
        ))

    async def require_current(client, control, current):
        result = await client.list_session_models(control)
        assert {model.id for model in result.models if model.provider == "faux"} == available
        assert all(model.provider != "unknown" for model in result.models)
        assert result.current_id == current

    async def require_submission_rejected(client, control):
        execution = client.execution_client
        instance = execution.service_instance_id
        before = await client.snapshot_session(control)
        with pytest.raises(AppServiceError) as rejected:
            await execution.submit_execution(control, instance, "retry", "Keep this input")
        assert rejected.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        assert await execution.find_execution_by_submission(control, instance, "retry") is None
        assert await client.snapshot_session(control) == before

    def transcript(session_id):
        return read_coding_resume_snapshot(
            scope.session_dir / f"hosted-{session_id}.jsonl", max_bytes=1024 * 1024,
        )

    async def scenario():
        async with host() as client:
            first, session_a = await open_session(client, "first", create=True)
            await require_current(client, first, None)
            await require_submission_rejected(client, first)
            assert (await select(client, first, first_id)).current_id == first_id
            assert settings().get_settings().default_model == selection_a

            second, session_b = await open_session(client, "second")
            await require_current(client, second, first_id)
            assert sum(record.kind == MODEL_SELECTION_KIND for record in transcript(session_b).records) == 1
            assert (await select(client, second, second_id)).current_id == second_id
            assert settings().get_settings().default_model == selection_b
            first, _ = await open_session(client, "first")
            await require_current(client, first, first_id)

            settings().set_default_model(selection_a, scope="project")
            third, session_c = await open_session(client, "project-default")
            await require_current(client, third, first_id)
            settings().set_default_model(ModelSelection("missing", "endpoint", "model"), scope="project")
            invalid, _ = await open_session(client, "invalid-default")
            await require_current(client, invalid, None)

        # Existing selections outrank project and global settings on reopen.
        async with host() as client:
            first, _ = await open_session(client, "first", session_id=session_a)
            await require_current(client, first, first_id)
            second, _ = await open_session(client, "second", session_id=session_b)
            await require_current(client, second, second_id)
            third, _ = await open_session(client, "project-default", session_id=session_c)
            await require_current(client, third, first_id)

        available.remove(first_id)
        del models[selection_a.model_id]
        write_catalog()
        async with host() as client:
            first, _ = await open_session(client, "first", session_id=session_a)
            await require_current(client, first, None)
            await require_submission_rejected(client, first)
            before = transcript(session_a)
            if not managed:
                entered, release = asyncio.Event(), asyncio.Event()
                current_plan = CodingDeferredHostedSessionV1._current_plan

                async def pause_plan(binding):
                    entered.set()
                    await release.wait()
                    return await current_plan(binding)

                with monkeypatch.context() as patch:
                    patch.setattr(CodingDeferredHostedSessionV1, "_current_plan", pause_plan)
                    selecting = asyncio.create_task(select(client, first, second_id))
                    try:
                        await asyncio.wait_for(entered.wait(), 10)
                        first, _ = await open_session(client, "first", session_id=session_a)
                    finally:
                        release.set()
                    with pytest.raises(AppServiceError) as stale:
                        await selecting
                    assert stale.value.code is AppErrorCodeV1.STALE_ATTACHMENT
                assert transcript(session_a).records == before.records
            assert (await select(client, first, second_id)).current_id == second_id
            after = transcript(session_a)
            assert after.records[:-1] == before.records
            assert after.records[-1].kind == MODEL_SELECTION_KIND
            if not managed:
                assert "Sending a message resumes" in (await client.snapshot_session(first)).records[-1].text

        # Selection survives an additional Host restart before the first send.
        async with host() as client:
            first, _ = await open_session(client, "first", session_id=session_a)
            await require_current(client, first, second_id)
            execution = client.execution_client
            instance = execution.service_instance_id
            submitted = await execution.submit_execution(first, instance, "retry", "Keep this input")
            while True:
                for envelope in await client.read_events(
                    attachment_id=first.attachment_id, controller_generation=first.controller_generation,
                ):
                    if envelope.event.kind is SessionEventKindV1.INTERACTION_REQUESTED:
                        await client.respond_interaction(InteractionRespondV1(
                            first.attachment_id, first.controller_generation, first.member_id,
                            envelope.event.interaction_id, InteractionOutcomeV1.APPROVE,
                        ))
                record = await execution.get_execution(first, instance, submitted.state.execution_id)
                if record.state.status.terminal:
                    break
                await asyncio.sleep(0.01)
            assert record.state.status is ExecutionStatusV1.SUCCEEDED
            duplicate = await execution.submit_execution(first, instance, "retry", "Keep this input")
            assert duplicate.state.execution_id == record.state.execution_id
            snapshot = await client.snapshot_session(first)
            assert [item.text for item in snapshot.records].count("Keep this input") == 1

    asyncio.run(asyncio.wait_for(scenario(), 60))
