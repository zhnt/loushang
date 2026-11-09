from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.agent import synthetic_model_transport
from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, ThinkingPart, ToolCall, Usage
from loushang.apphost import (
    SessionBindingKeyV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
)
from loushang.appserver.protocol import (
    InteractionOutcomeV1,
    SessionEventKindV1,
    SessionScopeV1,
)
from loushang.appservice.execution_contract import ExecutionRequestV1, ExecutionStatusV1
from loushang.coding.appservice_adapter import CodingHostedSessionV1
from loushang.coding.bootstrap import create_services
from loushang.coding.hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.hosted_execution import CodingHostedExecutionSessionV1
from loushang.coding.hosted_session import (
    CodingHostedHistoryBindingV1,
    CodingRealHostedSessionFactoryV1,
)
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.session.agent_session import AgentSession
from loushang.harness.approval import ApprovalRequest
from loushang.harness.config.agent import SettingsManager


@pytest.fixture(autouse=True)
def _private_session_home(tmp_path, monkeypatch):
    home = tmp_path / "user-home"
    home.mkdir()
    for key, path in {
        "HOME": home,
        "USERPROFILE": home,
        "LOUSHANG_HOME": tmp_path / "platform",
        "LOUSHANG_RUNTIME_DIR": tmp_path / "runtime",
        "LOUSHANG_TMPDIR": tmp_path / "scratch",
    }.items():
        monkeypatch.setenv(key, str(path))


def test_hosted_session_fixture_admits_only_private_user_resources(tmp_path):
    from loushang.harness.resources.layout import resolve_user_resource_roots

    assert Path.home().resolve() == (tmp_path / "user-home").resolve()
    roots, explicit = resolve_user_resource_roots()
    assert roots == ((tmp_path / "platform").resolve(),)
    assert not explicit


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            input=("text",), context_window=128000, max_tokens=4096
        ),
    )


@synthetic_model_transport
async def _stream(model, context, options=None):
    message = AssistantMessage(
        endpoint="anthropic-messages",
        role="assistant",
        content=[TextPart(type="text", text="real Coding response")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    stream.push(
        {
            "type": "text_delta",
            "content_index": 0,
            "delta": "real Coding response",
            "partial": message,
        }
    )
    stream.push({"type": "done", "reason": "stop", "message": message})
    return stream


async def _construction(tmp_path: Path, model: Model | None = None, *,
                        continuity_id: str = "continuity-1", stream_fn=_stream):
    scope = CodingHostedScopeV1(SessionScopeV1.CWD, tmp_path / "sessions", tmp_path)
    catalog = CodingHostedSessionCatalogV1((scope,))
    candidate = await catalog.create_candidate(
        SessionCreateIntentV1(
            SessionCreateRequestV1(
                "coding",
                scope.fingerprint,
                "a" * 32,
                requested_continuity_id=continuity_id,
                requested_scope=scope.discovery_scope,
            ),
            CODING_HOSTED_COMPATIBILITY_ID,
        )
    )
    claimed = await candidate.claim()
    identity = claimed.opaque_binding.record.identity
    factory = CodingRealHostedSessionFactoryV1(
        services_factory=lambda cwd: create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "settings.json",
                project_settings_path=cwd / ".loushang" / "settings.json",
            )
        ),
        model=model or _model(),
        stream_fn=stream_fn,
        tools=[],
    )
    return candidate, claimed, identity, factory


async def _binding(tmp_path: Path, model: Model | None = None, **kwargs):
    candidate, claimed, identity, factory = await _construction(tmp_path, model, **kwargs)
    binding = await factory.create_session(
        binding_key=SessionBindingKeyV1(
            identity.product_id, identity.continuity_id, identity.session_id
        ),
        opaque_session_binding=claimed.opaque_binding,
    )
    await claimed.close()
    await candidate.close()
    return binding


def test_tool_only_rounds_stay_in_history_without_empty_hosted_messages(tmp_path: Path) -> None:
    progress = "Checking available sources."
    tool_only = [
        ThinkingPart(type="thinking", thinking="Inspect the next source"),
        ToolCall(type="toolCall", id="lookup-2", name="unused_tool", arguments={}),
    ]
    content = iter((
        [
            TextPart(type="text", text=progress),
            ToolCall(type="toolCall", id="lookup-1", name="unused_tool", arguments={}),
        ],
        tool_only,
    ))

    @synthetic_model_transport
    async def stream(model, context, options=None):
        result = await _stream(model, context, options)
        parts = next(content, None)
        if parts is None:
            return result
        message = replace(await result.result(), content=parts, stop_reason="toolUse")
        tool_turn = AssistantMessageEventStream()
        tool_turn.push({"type": "done", "reason": "toolUse", "message": message})
        return tool_turn

    async def scenario():
        binding = await _binding(tmp_path, stream_fn=stream)
        hosted = CodingHostedExecutionSessionV1(binding)
        events = []
        hosted.subscribe(events.append)
        try:
            hosted.start_execution(ExecutionRequestV1("lookup", "Check the sources."))
            outcome = await asyncio.wait_for(hosted.wait_execution("lookup"), timeout=5)
            assert outcome.status is ExecutionStatusV1.SUCCEEDED
            expected = ["Check the sources.", progress, "real Coding response"]
            snapshot = (await hosted.snapshot_execution()).source
            assert [row.text for row in snapshot.records] == expected
            assert [event.text for event in events if event.kind is SessionEventKindV1.ASSISTANT_MESSAGE] == expected[1:]
            path = binding.control.session_manager.session_file
            assert path is not None
        finally:
            await hosted.close()

        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        assert any(
            isinstance(entry.payload, AssistantMessage) and entry.payload.content == tool_only
            for entry in history.records
        )
        restored = CodingHostedHistoryBindingV1(binding.identity, history)
        assert [row.text for row in restored.project_snapshot().records[:-1]] == expected

    asyncio.run(scenario())


@pytest.mark.parametrize("first_title", ["工作区连接诊断", "标题" * 40])
def test_gui_title_runs_in_background_and_retries_from_original_prompt(tmp_path, first_title):
    expected = "工作区连接诊断"
    question = "能帮我检查为什么 AppHost 连不上我的工作区吗？"
    title_contexts = []
    title_started = asyncio.Event()
    finish_title = asyncio.Event()

    @synthetic_model_transport
    async def stream(model, context, options=None):
        if "Write a short session title" not in (context.system_prompt or ""):
            return await _stream(model, context, options)
        title_contexts.append(context)
        title_started.set()
        await finish_title.wait()
        primary = await _stream(model, context, options)
        message = replace(
            await primary.result(),
            content=[TextPart(type="text", text=first_title if len(title_contexts) == 1 else expected)],
        )
        result = AssistantMessageEventStream()
        result.push({"type": "done", "reason": "stop", "message": message})
        return result

    async def scenario():
        binding = await _binding(tmp_path, continuity_id="gui-new-title-test", stream_fn=stream)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            assert (await hosted.snapshot_execution()).source.title == "New Session"
            hosted.start_execution(ExecutionRequestV1("first", question))
            await asyncio.wait_for(title_started.wait(), timeout=5)
            outcome = await asyncio.wait_for(hosted.wait_execution("first"), timeout=5)
            assert outcome.status is ExecutionStatusV1.SUCCEEDED
            snapshot = (await hosted.snapshot_execution()).source
            assert snapshot.title == question
            assert [row.text for row in snapshot.records] == [question, "real Coding response"]
            path = binding.control.session_manager.session_file
            assert path is not None
            history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
            restored = CodingHostedHistoryBindingV1(binding.identity, history)
            assert restored.project_snapshot().title == question

            hosted.start_execution(ExecutionRequestV1("second", "还有其他原因吗？"))
            finish_title.set()
            assert (await asyncio.wait_for(hosted.wait_execution("second"), timeout=5)).status is ExecutionStatusV1.SUCCEEDED
            await asyncio.wait_for(binding.wait_for_title(), timeout=5)
            assert (await hosted.snapshot_execution()).source.title == expected
            assert len(title_contexts) == (1 if first_title == expected else 2)
            for context in title_contexts:
                assert not context.tools
                assert len(context.messages) == 1
                content = context.messages[0].content
                assert isinstance(content, list) and len(content) == 1
                assert isinstance(content[0], TextPart) and content[0].text == question
        finally:
            finish_title.set()
            await hosted.close()

        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        restored = CodingHostedHistoryBindingV1(binding.identity, history)
        assert restored.project_snapshot().title == expected

    asyncio.run(scenario())


def test_gui_title_and_primary_reply_keep_independent_durable_outcomes(tmp_path: Path) -> None:
    from .test_agent_session_model_input import _CodingPreparedAdapter
    from .test_agent_session_model_input import _model as prepared_model

    question = "介绍北京天气\n" + "气候" * 30
    preview = "介绍北京天气 " + "气候" * 20 + "…"
    primary_started = asyncio.Event()
    finish_primary = asyncio.Event()
    title_published = asyncio.Event()
    transport_order = []

    class Adapter(_CodingPreparedAdapter):
        async def invoke_prepared_raw(self, request, prepared):
            is_title = "Write a short session title" in (request.context.system_prompt or "")
            prepared.payload_for_transport()
            transport_order.append("title" if is_title else "main")
            if not is_title:
                primary_started.set()
                await finish_primary.wait()
            yield {"type": "response_start", "response_id": "title-test"}
            yield {"type": "text_delta", "text": "北京四季气候" if is_title else "Beijing has four seasons."}
            yield {"type": "stop_reason", "stop_reason": "stop"}
            yield {"type": "response_done"}

    async def scenario():
        adapter = Adapter()
        registry = get_default_api_registry()
        registry.register_api_adapter(adapter, source_id=adapter.api)
        try:
            binding = await _binding(
                tmp_path, prepared_model(api=adapter.api),
                continuity_id="gui-new-durable-title-test", stream_fn=None,
            )
            hosted = CodingHostedExecutionSessionV1(binding)
            hosted.subscribe(lambda event: title_published.set() if event.kind is SessionEventKindV1.STATUS else None)
            try:
                hosted.start_execution(ExecutionRequestV1("first", question))
                await asyncio.wait_for(primary_started.wait(), timeout=5)
                assert (await hosted.snapshot_execution()).source.title == preview
                assert binding._title_task is None
                assert transport_order == ["main"]
                finish_primary.set()
                outcome = await asyncio.wait_for(hosted.wait_execution("first"), timeout=5)
                assert outcome.status is ExecutionStatusV1.SUCCEEDED
                await asyncio.wait_for(title_published.wait(), timeout=5)
                snapshot = (await hosted.snapshot_execution()).source
                assert snapshot.title == "北京四季气候"
                assert [row.text for row in snapshot.records] == [question, "Beijing has four seasons."]
                entries = binding.control.session_manager.get_entries()
                assert [row.payload.purpose for row in entries if row.kind == "model.input.prepared"] == [
                    "main", "session_title",
                ]
                assert [row.payload.stop_reason for row in entries if row.kind == "model.call.outcome"] == [
                    "stop", "stop",
                ]
            finally:
                finish_primary.set()
                await hosted.close()
        finally:
            registry.unregister_api_adapters(source_id=adapter.api)

    asyncio.run(scenario())


def test_hosted_session_sets_only_supported_thinking_levels(tmp_path: Path) -> None:
    async def scenario() -> None:
        model = Model(
            id="thinking-model", name="Thinking test", provider="faux",
            endpoint="anthropic-messages",
            capabilities=Capabilities(
                reasoning=True, reasoning_efforts=("low", "high"),
                input=("text",), context_window=128000, max_tokens=4096,
            ),
        )
        binding = await _binding(tmp_path, model)
        hosted = CodingHostedSessionV1(binding)
        try:
            before = await hosted.list_models()
            assert before.current_id is not None
            assert before.thinking is not None
            assert before.thinking.available_levels == ("off", "low", "high")
            with pytest.raises(ValueError, match="coding_thinking_level_unavailable"):
                await hosted.select_model(before.current_id, "medium")
            after = await hosted.select_model(before.current_id, "high")
            assert after.thinking is not None and after.thinking.current_level == "high"
            assert binding.control.thinking_level == "high"
        finally:
            await hosted.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", [
    "delivered", "source_changed", "factory_closed", "wrong_key",
    "unclaimed_closed", "claimed_closed", "source_changed_before_claim",
    pytest.param("catalog_fenced", marks=pytest.mark.skipif(
        sys.platform != "linux", reason="Linux owned transcript fence",
    )),
    pytest.param("catalog_fenced_before_claim", marks=pytest.mark.skipif(
        sys.platform != "linux", reason="Linux owned transcript fence",
    )),
])
def test_hosted_history_candidate_transfers_through_original_factory_without_runtime(
    tmp_path: Path, stage: str,
) -> None:
    from loushang.coding.hosted_application import (
        CodingForegroundProductFactoryV1,
        CodingHostedProfileFactoryV1,
    )
    from loushang.coding.hosted_catalog import (
        CodingHostedCandidateValidatorV1,
        CodingHostedCatalogError,
    )

    from .test_hosted_catalog import _intent, _scope

    async def scenario() -> None:
        scope = _scope(tmp_path)
        scope.session_dir.mkdir(mode=0o700, exist_ok=True)
        catalog = CodingHostedSessionCatalogV1(
            (scope,), owned_transcripts=stage.startswith("catalog_fenced"),
        )
        created = await catalog.create_candidate(_intent(scope))
        await created.close()
        rows = await catalog.list_identities((scope.discovery_scope,), limit=256)
        path = next(scope.session_dir.glob("*.jsonl"))
        original_bytes = path.read_bytes()

        def forbidden_services(cwd):
            raise AssertionError("history candidate constructed current services")

        def forbidden_product(manager):
            raise AssertionError("history candidate selected a Product factory")

        factory = CodingRealHostedSessionFactoryV1(
            services_factory=forbidden_services,
            package_product_runtime_factory_for_session=forbidden_product,
        )
        candidate = await catalog.open_history_candidate(
            rows[0].reference, max_bytes=1024 * 1024,
        )
        if stage in ("unclaimed_closed", "source_changed_before_claim", "catalog_fenced_before_claim"):
            if stage == "unclaimed_closed":
                await candidate.close()
            elif stage == "source_changed_before_claim":
                path.write_bytes(original_bytes + b"\n")
            else:
                catalog.fence()
            with pytest.raises(CodingHostedCatalogError):
                await candidate.claim()
            await candidate.close()
            await factory.close()
            await catalog.close()
            return
        claimed = await candidate.claim()
        opened = await CodingHostedCandidateValidatorV1().open_product_candidate(
            claimed, rows[0].envelope,
        )
        if stage == "source_changed":
            path.write_bytes(original_bytes + b"\n")
        elif stage == "catalog_fenced":
            catalog.fence()
        elif stage == "factory_closed":
            await factory.close()
        elif stage == "claimed_closed":
            await claimed.close()
        key = opened.binding_key
        if stage == "wrong_key":
            key = SessionBindingKeyV1(key.product_id, key.continuity_id, "wrong-session")
        hosted = None
        runtime = None
        profile = None
        try:
            if stage != "delivered":
                with pytest.raises(CodingHostedCatalogError):
                    await factory.create_session(
                        binding_key=key, opaque_session_binding=opened.opaque_binding,
                    )
            else:
                product_factory = CodingForegroundProductFactoryV1(factory)
                runtime = await product_factory.create_runtime(opened)
                profile = await CodingHostedProfileFactoryV1().bind_profile(
                    runtime.profile_binding,
                )
                binding = profile.profile_binding
                assert binding.control is None
                hosted = CodingHostedSessionV1(binding)
                snapshot = await hosted.snapshot()
                assert snapshot.identity.session_id == key.session_id
                assert snapshot.title == "New Session"
                assert snapshot.records[-1].text == "Historical session is read-only."
                await opened.close()
                await claimed.close()
                await candidate.close()
                assert await hosted.snapshot() == snapshot
                with pytest.raises(CodingHostedCatalogError):
                    await factory.create_session(
                        binding_key=key, opaque_session_binding=opened.opaque_binding,
                    )
                assert path.read_bytes() == original_bytes
        finally:
            if hosted is not None:
                await hosted.close()
            if profile is not None:
                await profile.close()
            if runtime is not None:
                await runtime.close()
            await opened.close()
            await claimed.close()
            await candidate.close()
            await factory.close()
            await catalog.close()

    asyncio.run(scenario())


def test_hosted_resume_lookup_uses_the_existing_canonical_binding(tmp_path: Path) -> None:
    from loushang.appservice.resume_ports import ResumeInputLookupQueryV1
    from loushang.coding.hosted_catalog import CodingHostedCatalogError
    from loushang.coding.resume_input_lookup import CodingResumeInputLookupQueryV1

    async def scenario():
        binding = await _binding(tmp_path)
        hosted = CodingHostedSessionV1(binding)
        try:
            original_control = binding.control
            query = CodingResumeInputLookupQueryV1("input-1", "a" * 64)
            result = await binding.lookup_resume_input(query)
            assert result.status == "unknown"
            assert result.record_id is None
            assert binding.control is original_control
            assert binding._close_task is None
            assert (await hosted.lookup_resume_input(ResumeInputLookupQueryV1(
                query.input_id, query.record_digest,
            ))).status == "unknown"
        finally:
            await hosted.close()
        with pytest.raises(CodingHostedCatalogError):
            await binding.lookup_resume_input(query)

    asyncio.run(scenario())


def test_G14_PRODUCT_real_agent_session_streams_and_persists_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_property,
) -> None:
    import loushang.coding.bootstrap as bootstrap_module
    import loushang.coding.hosted_session as hosted_module
    import loushang.coding.package_product_runtime as product_runtime_module
    from loushang.harness.capabilities.component_runtime import (
        CapabilityOwnerComponentBinder,
    )
    from loushang.harness.resource_catalog.session_bootstrap import (
        InitialSessionResourceCatalogBootstrap,
    )

    began = time.perf_counter()
    durations: list[tuple[str, float, float]] = []
    cpu_durations: list[tuple[str, float]] = []

    def observe(name: str, started: float) -> None:
        durations.append(
            (name, round(started - began, 3), round(time.perf_counter() - started, 3))
        )

    def timed_sync(name, original):
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            cpu_started = time.process_time()
            try:
                return original(*args, **kwargs)
            finally:
                observe(name, started)
                cpu_durations.append((name, round(time.process_time() - cpu_started, 3)))

        return wrapper

    def timed_async(name, original):
        async def wrapper(*args, **kwargs):
            started = time.perf_counter()
            cpu_started = time.process_time()
            try:
                return await original(*args, **kwargs)
            finally:
                observe(name, started)
                cpu_durations.append((name, round(time.process_time() - cpu_started, 3)))

        return wrapper

    monkeypatch.setattr(
        CodingRealHostedSessionFactoryV1,
        "_default_product_factory_for_session",
        timed_sync(
            "product-owner-selection",
            CodingRealHostedSessionFactoryV1._default_product_factory_for_session,
        ),
    )
    monkeypatch.setattr(
        product_runtime_module,
        "_initialize_fresh_coding_product_for_session",
        timed_sync(
            "fresh-product-cutover",
            product_runtime_module._initialize_fresh_coding_product_for_session,
        ),
    )
    monkeypatch.setattr(
        product_runtime_module,
        "_bootstrap_coding_builtin_plugin",
        timed_sync(
            "builtin-plugin-bootstrap",
            product_runtime_module._bootstrap_coding_builtin_plugin,
        ),
    )
    monkeypatch.setattr(
        hosted_module,
        "create_agent_session",
        timed_sync("agent-session-construction", hosted_module.create_agent_session),
    )
    monkeypatch.setattr(
        bootstrap_module,
        "_prepare_coding_catalog_projection",
        timed_sync(
            "product-catalog-projection",
            bootstrap_module._prepare_coding_catalog_projection,
        ),
    )
    monkeypatch.setattr(
        bootstrap_module,
        "prepare_coding_builtin_product_composition",
        timed_sync(
            "product-catalog-composition",
            bootstrap_module.prepare_coding_builtin_product_composition,
        ),
    )
    monkeypatch.setattr(
        AgentSession,
        "prepare_model_call_runtime",
        timed_async("model-call-preparation", AgentSession.prepare_model_call_runtime),
    )
    monkeypatch.setattr(
        InitialSessionResourceCatalogBootstrap,
        "prepare",
        timed_async(
            "initial-catalog-preparation", InitialSessionResourceCatalogBootstrap.prepare
        ),
    )
    monkeypatch.setattr(
        CapabilityOwnerComponentBinder,
        "bind",
        timed_async("component-binding", CapabilityOwnerComponentBinder.bind),
    )

    async def scenario() -> None:
        started = time.perf_counter()
        cpu_started = time.process_time()
        try:
            binding = await _binding(tmp_path)
        finally:
            observe("hosted-binding", started)
            cpu_durations.append(
                ("hosted-binding", round(time.process_time() - cpu_started, 3))
            )
        hosted = CodingHostedSessionV1(binding)
        events = []
        hosted.subscribe(events.append)
        try:
            assert (await hosted.snapshot()).title == "New Session"
            started = time.perf_counter()
            cpu_started = time.process_time()
            try:
                await hosted.start_turn("hello actual Session")
            finally:
                observe("first-start-turn", started)
                cpu_durations.append(
                    ("first-start-turn", round(time.process_time() - cpu_started, 3))
                )
            snapshot = await hosted.snapshot()
            assert snapshot.title == "hello actual Session"
            assert [record.text for record in snapshot.records] == [
                "hello actual Session",
                "real Coding response",
            ]
            kinds = {event.kind for event in events}
            assert {
                SessionEventKindV1.TURN_STARTED,
                SessionEventKindV1.USER_MESSAGE,
                SessionEventKindV1.ASSISTANT_MESSAGE,
                SessionEventKindV1.TURN_COMPLETED,
            } <= kinds
            assert not snapshot.running
            models = await hosted.list_models()
            assert models.current_id == "faux:anthropic-messages:faux-model"
            assert any(choice.id == models.current_id for choice in models.models)
        finally:
            started = time.perf_counter()
            cpu_started = time.process_time()
            try:
                await hosted.close()
            finally:
                observe("hosted-close", started)
                cpu_durations.append(
                    ("hosted-close", round(time.process_time() - cpu_started, 3))
                )
        assert len(tuple((tmp_path / "sessions").glob("*.jsonl"))) == 1

    try:
        asyncio.run(asyncio.wait_for(scenario(), 20))
    except TimeoutError as error:
        error.add_note(f"G14 safe phase durations: {durations!r}")
        raise
    finally:
        record_property("g14_phase_durations", json.dumps(durations))
        record_property("g14_phase_cpu_durations", json.dumps(cpu_durations))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native Product route")
def test_windows_hosted_ordinary_session_enters_fresh_b_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.bootstrap as coding_bootstrap
    import loushang.coding.package_product_runtime as product_runtime
    from loushang.coding._plugin_lifecycle import (
        resolve_ephemeral_coding_plugin_lifecycle_state_layout,
    )

    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=tmp_path
    )
    monkeypatch.setattr(
        product_runtime,
        "resolve_coding_plugin_lifecycle_state_layout",
        lambda _workspace: lifecycle,
    )
    monkeypatch.setattr(
        product_runtime,
        "default_global_settings_path",
        lambda: tmp_path / "settings.json",
    )
    monkeypatch.setattr(product_runtime, "version", lambda _package: "2.0.0")

    def reject_legacy(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Hosted ordinary Session reached legacy startup")

    monkeypatch.setattr(
        coding_bootstrap, "prepare_managed_coding_base_plugin_assembly", reject_legacy
    )
    monkeypatch.setattr(coding_bootstrap, "_default_package_materializer", reject_legacy)

    async def scenario() -> None:
        candidate, claimed, identity, factory = await _construction(tmp_path)
        try:
            binding = await factory.create_session(
                binding_key=SessionBindingKeyV1(
                    identity.product_id, identity.continuity_id, identity.session_id
                ),
                opaque_session_binding=claimed.opaque_binding,
            )
            try:
                assert binding.control.package_product_lifecycle_mode == "enforced"
                assert binding.control.package_product_binding_id is not None
            finally:
                await binding.close()
        finally:
            await claimed.close()
            await candidate.close()
            await factory.close()

    asyncio.run(scenario())


def test_hosted_product_runtime_requires_a_session_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.bootstrap as coding_bootstrap

    async def scenario() -> None:
        candidate, claimed, identity, _ = await _construction(tmp_path)
        selected: list[str] = []

        def select(manager):
            selected.append(manager.get_header().conversation_id)
            return None

        def reject_legacy(*_args, **_kwargs):
            raise AssertionError("Hosted Product selection reached legacy startup")

        monkeypatch.setattr(
            coding_bootstrap, "_default_package_materializer", reject_legacy
        )
        factory = CodingRealHostedSessionFactoryV1(
            services_factory=lambda cwd: create_services(
                settings_manager=SettingsManager(
                    global_settings_path=tmp_path / "settings.json",
                    project_settings_path=cwd / ".loushang" / "settings.json",
                )
            ),
            model=_model(),
            stream_fn=_stream,
            tools=[],
            package_product_runtime_factory_for_session=select,
        )
        with pytest.raises(
            TypeError, match="Package Product runtime factory is required"
        ):
            await factory.create_session(
                binding_key=SessionBindingKeyV1(
                    identity.product_id, identity.continuity_id, identity.session_id
                ),
                opaque_session_binding=claimed.opaque_binding,
            )
        assert selected == [identity.session_id]
        await claimed.close()
        await candidate.close()

    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_hosted_fenced_default_refuses_invalid_product_without_legacy_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.bootstrap as coding_bootstrap
    import loushang.coding.package_product_runtime as product_runtime
    from loushang.coding._plugin_lifecycle import (
        resolve_coding_plugin_lifecycle_state_layout,
    )
    from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
    from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
        PackageEpochFenceError,
    )

    layout = resolve_coding_plugin_lifecycle_state_layout(tmp_path)
    epoch = resolve_coding_package_epoch_layout(layout)
    if sys.platform == "win32":
        from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
        from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
            open_windows_directory,
            open_windows_regular_file_at,
        )

        epoch.control_root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with WindowsPrivateDirectoryAcl() as acl:
            parent = open_windows_directory(epoch.control_root.parent)
            try:
                control = open_windows_directory(
                    epoch.control_root.name,
                    dir_fd=parent,
                    create_new=True,
                    security_descriptor=acl.security_descriptor,
                )
                try:
                    epoch_file = open_windows_regular_file_at(
                        control,
                        "epoch.jsonl",
                        create_new=True,
                        write=True,
                        security_descriptor=acl.security_descriptor,
                    )
                    try:
                        os.write(epoch_file, b"invalid B fence\n")
                    finally:
                        os.close(epoch_file)
                finally:
                    os.close(control)
            finally:
                os.close(parent)
    else:
        epoch.control_root.mkdir(parents=True, mode=0o700)
        (epoch.control_root / "epoch.jsonl").write_text("invalid B fence\n")
    selected: list[str] = []

    def refuse_product(*_args: object, **_kwargs: object) -> None:
        selected.append("product")
        raise ValueError("invalid B fence")

    def reject_legacy(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fenced Hosted startup reached legacy materializer")

    monkeypatch.setattr(
        product_runtime, "open_coding_fenced_product_application_owner", refuse_product
    )
    monkeypatch.setattr(
        coding_bootstrap, "_default_package_materializer", reject_legacy
    )

    async def scenario() -> None:
        candidate, claimed, identity, factory = await _construction(tmp_path)
        with pytest.raises(PackageEpochFenceError):
            await factory.create_session(
                binding_key=SessionBindingKeyV1(
                    identity.product_id, identity.continuity_id, identity.session_id
                ),
                opaque_session_binding=claimed.opaque_binding,
            )
        assert selected == []
        await claimed.close()
        await candidate.close()
        await factory.close()

    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_hosted_default_preserves_effective_old_settings_without_product_cutover(
    tmp_path: Path,
) -> None:
    from loushang.coding._plugin_lifecycle import (
        resolve_coding_plugin_lifecycle_state_layout,
    )
    from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout

    settings = tmp_path / "settings.json"
    old_bytes = b'{"disabled_plugins":["coding.base"]}'
    settings.write_bytes(old_bytes)
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(tmp_path)

    async def scenario() -> None:
        candidate, claimed, identity, factory = await _construction(tmp_path)
        try:
            binding = await factory.create_session(
                binding_key=SessionBindingKeyV1(
                    identity.product_id, identity.continuity_id, identity.session_id
                ),
                opaque_session_binding=claimed.opaque_binding,
            )
            await binding.close()
        finally:
            await claimed.close()
            await candidate.close()
            await factory.close()

    asyncio.run(asyncio.wait_for(scenario(), 20))
    assert settings.read_bytes() == old_bytes
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert not (epoch.control_root / "epoch.jsonl").exists()


def test_hosted_product_runtime_missing_selection_cannot_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.bootstrap as coding_bootstrap
    from loushang.coding.control import ControlConfig
    from loushang.harness.package_product.product_runtime import (
        PackageProductRuntimeActivationError,
        PackageProductRuntimeBindingV1,
    )

    events: list[str] = []

    class Lifecycle:
        binding_id = "owner:coding-package"
        active = False

        def activate(self) -> None:
            self.active = True

    class Inventory:
        binding_id = "owner:coding-package"

    class ProductFactory:
        def create(self, request):
            events.append(f"product:{request.session_id}")
            return PackageProductRuntimeBindingV1(
                product_id="coding",
                lifecycle=Lifecycle(),  # type: ignore[arg-type]
                inventory=Inventory(),  # type: ignore[arg-type]
                mode="enforced",
                on_dispose=lambda: events.append("product_dispose"),
            )

    def reject_legacy(*_args, **_kwargs):
        raise AssertionError("Hosted Product startup reached legacy Plugin path")

    monkeypatch.setattr(
        coding_bootstrap, "_default_package_materializer", reject_legacy
    )
    monkeypatch.setattr(
        coding_bootstrap, "prepare_managed_coding_base_plugin_assembly", reject_legacy
    )

    async def scenario() -> None:
        candidate, claimed, identity, _ = await _construction(tmp_path)
        factory = CodingRealHostedSessionFactoryV1(
            services_factory=lambda _cwd: create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
            model=_model(),
            stream_fn=_stream,
            tools=[],
            package_product_runtime_factory_for_session=lambda _manager: (
                ProductFactory()
            ),
        )
        with pytest.raises(PackageProductRuntimeActivationError) as failure:
            await factory.create_session(
                binding_key=SessionBindingKeyV1(
                    identity.product_id, identity.continuity_id, identity.session_id
                ),
                opaque_session_binding=claimed.opaque_binding,
            )
        assert failure.value.code == "package_product_manifest_reader_unavailable"
        assert events == [f"product:{identity.session_id}", "product_dispose"]
        await claimed.close()
        await candidate.close()

    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_G14_OWNERSHIP_failed_session_construction_retains_cleanup_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    import loushang.coding.bootstrap as bootstrap_module
    import loushang.coding.hosted_session as module
    import loushang.coding.package_product_runtime as product_runtime_module

    began = time.perf_counter()
    cpu_began = time.process_time()
    phases = []

    def phase(name):
        phases.append(
            (
                name,
                round(time.perf_counter() - began, 3),
                round(time.process_time() - cpu_began, 3),
            )
        )

    def timed_sync(name, original):
        def wrapper(*args, **kwargs):
            phase(name + "-enter")
            try:
                return original(*args, **kwargs)
            finally:
                phase(name + "-exit")

        return wrapper

    monkeypatch.setattr(
        CodingRealHostedSessionFactoryV1,
        "_default_product_factory_for_session",
        timed_sync(
            "product-owner-selection",
            CodingRealHostedSessionFactoryV1._default_product_factory_for_session,
        ),
    )
    monkeypatch.setattr(
        product_runtime_module,
        "_initialize_fresh_coding_product_for_session",
        timed_sync(
            "fresh-product-cutover",
            product_runtime_module._initialize_fresh_coding_product_for_session,
        ),
    )
    monkeypatch.setattr(
        product_runtime_module,
        "_bootstrap_coding_builtin_plugin",
        timed_sync(
            "builtin-plugin-bootstrap",
            product_runtime_module._bootstrap_coding_builtin_plugin,
        ),
    )
    monkeypatch.setattr(
        module,
        "create_agent_session",
        timed_sync("agent-session-construction", module.create_agent_session),
    )
    monkeypatch.setattr(
        bootstrap_module,
        "prepare_coding_builtin_product_composition",
        timed_sync(
            "product-catalog-composition",
            bootstrap_module.prepare_coding_builtin_product_composition,
        ),
    )

    async def scenario() -> None:
        candidate, claimed, identity, factory = await _construction(tmp_path)
        phase("candidate-ready")
        original_dispose = AgentSession.dispose
        attempts = 0

        async def failing_dispose(session: AgentSession) -> None:
            nonlocal attempts
            attempts += 1
            phase("dispose-enter")
            if attempts == 1:
                raise RuntimeError("temporary cleanup failure")
            await original_dispose(session)
            phase("dispose-done")

        def reject_binding(*args):
            raise RuntimeError("binding construction failed")

        monkeypatch.setattr(AgentSession, "dispose", failing_dispose)
        monkeypatch.setattr(module, "CodingRealHostedSessionV1", reject_binding)
        with pytest.raises(RuntimeError, match="temporary cleanup failure"):
            await factory.create_session(
                binding_key=SessionBindingKeyV1(
                    identity.product_id, identity.continuity_id, identity.session_id
                ),
                opaque_session_binding=claimed.opaque_binding,
            )
        assert attempts == 1
        phase("factory-failed")
        await claimed.close()
        phase("retry-closed")
        await claimed.close()
        await candidate.close()
        assert attempts == 2

    try:
        asyncio.run(asyncio.wait_for(scenario(), 20))
    except TimeoutError as error:
        # Fixed phase names and durations only; no paths, settings or raw task
        # representations. Keep the original watchdog and failure unchanged.
        error.add_note(f"Hosted construction/cleanup phase durations: {phases!r}")
        raise
    finally:
        record_property("g14_ownership_phases", json.dumps(phases))


def test_G14_PRODUCT_real_approval_broker_round_trip_and_close(tmp_path: Path) -> None:
    async def scenario() -> None:
        binding = await _binding(tmp_path)
        hosted = CodingHostedSessionV1(binding)
        presented = asyncio.Queue()
        hosted.subscribe(
            lambda event: (
                presented.put_nowait(event)
                if event.kind is SessionEventKindV1.INTERACTION_REQUESTED
                else None
            )
        )
        decision = asyncio.create_task(
            binding._approval.resolve(
                ApprovalRequest(
                    tool_name="safe-test",
                    arguments={"action": "preview"},
                    action_id="native-action-1",
                )
            )
        )
        try:
            event = await presented.get()
            assert event.interaction_id != "native-action-1"
            assert await hosted.respond_interaction(
                event.interaction_id, InteractionOutcomeV1.APPROVE
            )
            result = await decision
            assert result.disposition == "allow"
        finally:
            await hosted.close()
            await asyncio.gather(decision, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 20))
