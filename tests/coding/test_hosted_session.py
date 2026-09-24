from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from loushang.agent import synthetic_model_transport
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage
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
from loushang.coding.appservice_adapter import CodingHostedSessionV1
from loushang.coding.bootstrap import create_services
from loushang.coding.hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.hosted_session import CodingRealHostedSessionFactoryV1
from loushang.coding.session.agent_session import AgentSession
from loushang.harness.approval import ApprovalRequest
from loushang.harness.config.agent import SettingsManager


@pytest.fixture(autouse=True)
def _private_session_home(tmp_path, monkeypatch):
    home = tmp_path / "user-home"
    home.mkdir()
    for key, path in {
        "HOME": home, "USERPROFILE": home, "LOUSHANG_HOME": tmp_path / "platform",
        "LOUSHANG_RUNTIME_DIR": tmp_path / "runtime", "LOUSHANG_TMPDIR": tmp_path / "scratch",
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


async def _construction(tmp_path: Path):
    scope = CodingHostedScopeV1(SessionScopeV1.CWD, tmp_path / "sessions", tmp_path)
    catalog = CodingHostedSessionCatalogV1((scope,))
    candidate = await catalog.create_candidate(
        SessionCreateIntentV1(
            SessionCreateRequestV1(
                "coding",
                scope.fingerprint,
                "a" * 32,
                requested_continuity_id="continuity-1",
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
        model=_model(),
        stream_fn=_stream,
        tools=[],
    )
    return candidate, claimed, identity, factory


async def _binding(tmp_path: Path):
    candidate, claimed, identity, factory = await _construction(tmp_path)
    binding = await factory.create_session(
        binding_key=SessionBindingKeyV1(
            identity.product_id, identity.continuity_id, identity.session_id
        ),
        opaque_session_binding=claimed.opaque_binding,
    )
    await claimed.close()
    await candidate.close()
    return binding


def test_G14_PRODUCT_real_agent_session_streams_and_persists_messages(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        binding = await _binding(tmp_path)
        hosted = CodingHostedSessionV1(binding)
        events = []
        hosted.subscribe(events.append)
        try:
            await hosted.start_turn("hello actual Session")
            snapshot = await hosted.snapshot()
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
        finally:
            await hosted.close()
        assert len(tuple((tmp_path / "sessions").glob("*.jsonl"))) == 1

    asyncio.run(asyncio.wait_for(scenario(), 20))


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

        monkeypatch.setattr(coding_bootstrap, "_default_package_materializer", reject_legacy)
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
        with pytest.raises(TypeError, match="Package Product runtime factory is required"):
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
    import loushang.coding.hosted_session as hosted_session
    from loushang.coding._plugin_lifecycle import (
        resolve_coding_plugin_lifecycle_state_layout,
    )
    from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout

    layout = resolve_coding_plugin_lifecycle_state_layout(tmp_path)
    epoch = resolve_coding_package_epoch_layout(layout)
    epoch.control_root.mkdir(parents=True, mode=0o700)
    (epoch.control_root / "epoch.jsonl").write_text("invalid B fence\n")
    selected: list[str] = []

    def refuse_product(*_args: object, **_kwargs: object) -> None:
        selected.append("product")
        raise ValueError("invalid B fence")

    def reject_legacy(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fenced Hosted startup reached legacy materializer")

    monkeypatch.setattr(
        hosted_session, "open_coding_fenced_product_application_owner", refuse_product
    )
    monkeypatch.setattr(coding_bootstrap, "_default_package_materializer", reject_legacy)

    async def scenario() -> None:
        candidate, claimed, identity, factory = await _construction(tmp_path)
        with pytest.raises(ValueError, match="invalid B fence"):
            await factory.create_session(
                binding_key=SessionBindingKeyV1(
                    identity.product_id, identity.continuity_id, identity.session_id
                ),
                opaque_session_binding=claimed.opaque_binding,
            )
        assert selected == ["product"]
        await claimed.close()
        await candidate.close()
        await factory.close()

    asyncio.run(asyncio.wait_for(scenario(), 20))


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

    monkeypatch.setattr(coding_bootstrap, "_default_package_materializer", reject_legacy)
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
            package_product_runtime_factory_for_session=lambda _manager: ProductFactory(),
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
) -> None:
    import loushang.coding.hosted_session as module

    began = time.perf_counter()
    phases = []

    def phase(name):
        phases.append((name, round(time.perf_counter() - began, 3)))

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
