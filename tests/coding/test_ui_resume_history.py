from __future__ import annotations

import asyncio
import sys
from contextlib import suppress
from datetime import UTC, datetime
from io import StringIO

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.types import UserMessage
from loushang.coding import bootstrap
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.interaction.resume_history import (
    build_coding_resume_history_screen,
)
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
)
from loushang.coding.resume_activation_attempt import CodingActivationAttemptV1
from loushang.coding.resume_activation_plan import build_session_activation_plan
from loushang.coding.resume_permission_confirmation import (
    CodingResumePermissionConfirmation,
    coding_resume_permission_request,
)
from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harness.approval import DenyApprovalResolver, InteractiveApprovalResolver
from loushang.harnesstui.conversation.application_host import (
    run_prepared_screen_conversation,
)
from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ErrorRecord,
    UserPromptRecord,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned Resume Writer")


class _TerminalSurface:
    """Terminal-only callbacks; no Session or permission authority."""

    async def handle_text(self, text):
        return None

    async def handle_surface_intent(self, intent):
        return None

    def is_local_command(self, text):
        return False

    def clear_approval_surfaces(self):
        pass


def test_unverified_tail_screen_is_read_only_and_never_prepares_writer(
    tmp_path,
):
    async def scenario():
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            defer_materialization=False,
        )
        await manager.append_message(
            UserMessage(role="user", content="recent only", timestamp=1.0)
        )
        path = manager.session_file
        await manager.dispose_runtime_profile()
        assert path is not None

        def forbidden_factory(*args, **kwargs):
            pytest.fail("read-only tail must not construct a Session")

        root = AgentSessionRuntime(
            session_dir=path.parent,
            session_factory=forbidden_factory,
        )
        try:
            page = await root.preview_resume_recent_page(path)
            app = ScreenCodingTuiApp(
                model_label=None,
                cwd=str(tmp_path),
                branch=None,
                session_label=manager.header.conversation_id,
            )
            prepared = build_coding_resume_history_screen(
                runtime=root,
                session_ref=path,
                history=page,
                app=app,
                prepare_input=None,
                surface=_TerminalSurface(),
                stderr=StringIO(),
            )
            assert any(
                isinstance(record, UserPromptRecord)
                and record.text == "recent only"
                for record in prepared.history_records
            )
            assert await prepared.action_host.submit(
                ConversationTextAction("continue")
            ) is None
            assert root.current_session is None
            assert await prepared.action_host.submit(
                ConversationTextAction("/quit")
            ) == 0
        finally:
            await root.dispose_session_runtime()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["history", "completed", "denied", "revoked", "cancelled", "closed_before_writer", "wrong_target", "rebind_failed", "unknown_transport", "cancel_recovery"])
def test_native_screen_history_then_one_original_resume_input(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        async def historical(text):
            manager = await SessionManager.new(
                session_dir=tmp_path / "sessions", cwd=str(tmp_path), defer_materialization=False,
            )
            await manager.append_message(UserMessage(role="user", content=text, timestamp=1.0))
            path = manager.session_file
            await manager.dispose_runtime_profile()
            assert path is not None
            return path

        path = await historical("old history")
        other_path = await historical("other history") if mode == "wrong_target" else path
        model = Model(
            id="ui-test", name="UI Test", provider="faux", endpoint="ui-resume",
            api="ui-resume-test", base_url="https://provider.test/v1", auth=Auth(kind="none"),
            capabilities=Capabilities(input=("text",), output=("text",), stream=True,
                                      context_window=128000, max_tokens=4096),
        )
        selection = CodingFencedProductApplicationSelection()
        # Original application startup selects the native owner before history;
        # the display and its epoch observations must not select one themselves.
        startup = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), persist=False,
        )
        try:
            factory = selection.factory_for_session(startup)
            assert factory is not None
            factory.runtime_lease.release()
        finally:
            await startup.dispose_runtime_profile()
        selected_owners = dict(selection._owners)

        def ordinary(manager, **kwargs):
            return bootstrap.create_agent_session(
                session_manager=manager, composition_set="coding-minimal", no_tools=True,
                model=model, package_product_runtime_factory=selection.factory_for_session(manager),
                **kwargs,
            )

        root = AgentSessionRuntime(
            session_dir=tmp_path / "sessions", session_factory=ordinary,
            owned_transcripts=True, product_owner_selection=selection,
        )
        issuer = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        registry = get_default_api_registry()
        requests = []
        preparations = []
        entered = asyncio.Event()
        task = None

        class Adapter:
            api = "ui-resume-test"

            def prepare_request(self, request):
                return PreparedModelRequest.from_provider_request(request, payload={"model": request.model.id})

            async def invoke_prepared_raw(self, request, prepared):
                prepared.payload_for_transport()
                requests.append(request)
                if mode == "unknown_transport":
                    raise ConnectionError("provider outcome unknown")
                yield {"type": "response_start", "response_id": "ui-response"}
                yield {"type": "text_delta", "text": "actual reply"}
                yield {"type": "stop_reason", "stop_reason": "stop"}
                yield {"type": "response_done"}

            async def invoke_raw(self, request):
                pytest.fail("native prepared transport was bypassed")
                yield {}

        registry.register_api_adapter(Adapter(), source_id="ui-resume-test")
        try:
            history = await root.preview_resume_history(path)
            target_history = await root.preview_resume_history(other_path) if mode == "wrong_target" else history
            plan = build_session_activation_plan(
                target_history, resolve_coding_composition_set("coding-minimal"), workspace_root=tmp_path,
            )
            attempt = CodingActivationAttemptV1(
                attempt_id="ui-attempt", request_id="ui-input", session_id=plan.session_id,
                original_leaf_id=plan.selected_leaf_id, ancestry_digest=plan.ancestry_digest,
                plan_fingerprint=plan.plan_id, epoch_fingerprint=selection.resume_epoch_fingerprint(tmp_path),
                subject_digest="b" * 64,
            )
            app = ScreenCodingTuiApp(model_label=None, cwd=str(tmp_path), branch=None, session_label=history.header_preview.header.conversation_id)
            before = path.read_bytes()
            other_before = other_path.read_bytes()

            async def confirm(payload):
                assert root.current_session is None
                assert not root._owned_transcript_factory.pending_preparations
                assert await issuer.handle_result(payload["action_id"], outcome="allow_once")

            issuer.set_request_presenter(confirm)

            async def prepare_input(action, observe_identity):
                preparations.append(action)
                assert action.text == "continue once"
                if mode == "denied":
                    raise PermissionError("continuation denied before Writer")
                fact = await issuer.confirm(coding_resume_permission_request(
                    attempt, actor_id="root", expansion_codes=("authority.unknown",),
                ))
                assert fact is not None
                permission = CodingResumePermissionConfirmation(attempt, "root", ("authority.unknown",), issuer, fact)
                if mode == "closed_before_writer":
                    entered.set()
                    # A broken preparer must not bypass the original Root guard.
                    with suppress(asyncio.CancelledError):
                        await asyncio.Event().wait()

                def epoch(observed, receipt):
                    # This fixture checks UI/lifecycle orchestration, not production effect settlement.
                    assert observed == attempt
                    assert receipt["setId"] == "coding-minimal"

                if mode == "cancelled":
                    native_graph = AgentSession._prepare_resume_runtime_graph

                    async def pause_graph(session, **kwargs):
                        result = await native_graph(session, **kwargs)
                        entered.set()
                        await asyncio.Event().wait()
                        return result

                    monkeypatch.setattr(AgentSession, "_prepare_resume_runtime_graph", pause_graph)
                prepared = await root.prepare_resume_continuation(
                    session_file=other_path, plan=plan, current_owner_inputs=(), attempt=attempt,
                    input_record_id="ui-input-record", text=action.text, model=model, no_tools=True,
                    created_at=datetime(2026, 10, 12, tzinfo=UTC),
                    require_current_admission=permission.require_current,
                    require_current_epoch_settlement=epoch, observe_input_identity=observe_identity,
                )
                if mode in {"revoked", "cancel_recovery"}:
                    issuer.release_confirmation(fact)
                if mode == "cancel_recovery":
                    native_read = root.preview_resume_history

                    async def pause_recovery(*args, **kwargs):
                        result = await native_read(*args, **kwargs)
                        entered.set()
                        await asyncio.Event().wait()
                        return result

                    monkeypatch.setattr(root, "preview_resume_history", pause_recovery)
                if mode == "rebind_failed":
                    def failed_subscribe(session, listener):
                        raise OSError("native event subscription failed")

                    monkeypatch.setattr(AgentSession, "subscribe", failed_subscribe)
                return prepared

            run = build_coding_resume_history_screen(
                runtime=root, session_ref=path, history=history, app=app,
                prepare_input=prepare_input, surface=_TerminalSurface(), stderr=StringIO(),
            )
            assert root.current_session is None
            assert selection._owners == selected_owners
            assert path.read_bytes() == before

            async def screen_runner(**kwargs):
                nonlocal task
                assert kwargs["app"] is app
                host = kwargs["action_host"]
                assert [record.text for record in app.state.records if isinstance(record, UserPromptRecord)] == ["old history"]
                assert not app.state.running
                assert not requests
                assert not preparations
                assert await host.submit(ConversationTextAction("/quit")) == 0
                assert not preparations
                if mode == "history":
                    return 0
                if mode in {"cancelled", "closed_before_writer", "cancel_recovery"}:
                    task = asyncio.create_task(host.submit(ConversationTextAction("continue once")))
                    waiter = asyncio.create_task(entered.wait())
                    try:
                        await asyncio.wait((task, waiter), return_when=asyncio.FIRST_COMPLETED)
                        if not entered.is_set():
                            await task
                        if mode == "closed_before_writer":
                            host.close()
                        else:
                            await host.abort()
                        with pytest.raises(asyncio.CancelledError):
                            await task
                    finally:
                        waiter.cancel()
                        await asyncio.gather(waiter, return_exceptions=True)
                else:
                    assert await host.submit(ConversationTextAction("continue once")) is None
                assert len(preparations) == 1
                assert not app.state.running
                if mode == "completed":
                    assert root.current_session is not None
                    assert len(requests) == 1
                    assert [record.text for record in app.state.records if isinstance(record, UserPromptRecord)] == ["old history", "continue once"]
                    assert [record.text for record in app.state.records if isinstance(record, AssistantMessageRecord)] == ["actual reply"]
                else:
                    assert len(requests) == int(mode == "unknown_transport")
                    assert root.current_session is None
                    if mode in {"revoked", "rebind_failed", "unknown_transport"}:
                        assert host._recovery is not None
                        assert host._recovery.input_record_id == "ui-input-record"
                        assert host._recovery.status == (
                            "observed_failed" if mode == "unknown_transport" else "unknown"
                        )
                        assert [record.text for record in app.state.records if isinstance(record, UserPromptRecord)] == ["old history", "continue once"]
                        assert any(
                            "Saved input found." in record.summary
                            for record in app.state.records if isinstance(record, ErrorRecord)
                        )
                    # Recovery never calls the preparer or normal prompt again.
                    saved = path.read_bytes()
                    await host.submit(ConversationTextAction("continue once"))
                    assert len(preparations) == 1
                    assert path.read_bytes() == saved
                    assert len(requests) == int(mode == "unknown_transport")
                return 0

            assert await run_prepared_screen_conversation(
                run, stdin=StringIO(), stdout=StringIO(), screen_runner=screen_runner,
            ) == 0
            if mode in {"history", "denied", "wrong_target", "closed_before_writer"}:
                assert path.read_bytes() == before
            if mode == "wrong_target":
                assert other_path.read_bytes() == other_before
                assert selection._owners == selected_owners
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await root.dispose_session_runtime()
            issuer.dispose()
            registry.unregister_api_adapters("ui-resume-test")

    asyncio.run(scenario())
