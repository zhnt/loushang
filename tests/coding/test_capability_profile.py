from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import loushang.coding.session.agent_session as agent_session_module
import loushang.harness.session.agent_product as agent_product_module
from loushang.agent import Agent
from loushang.coding.product_plan import (
    CODING_CAPABILITY_PLAN,
    CODING_CAPABILITY_PROFILE,
    CODING_CAPABILITY_PROFILE_METADATA_KEY,
    CODING_PRODUCT_ID,
)
from loushang.coding.runtime_capability_admission import (
    SIDE_QUESTION_RUNTIME_PERMISSION,
    resolve_coding_capability_profile,
)
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.capabilities import (
    CapabilityPack,
    bind_capability_composition_runtime,
    standard_capability_composition_implementations,
)
from loushang.harness.capabilities.prompt import PromptSection
from loushang.harness.conversation import ConversationHeader
from loushang.harness.extensions.agent import (
    ExtensionAPI,
    ExtensionManifest,
    ExtensionPermissionDeclaration,
    ExtensionPolicyDecision,
    ExtensionRunner,
)
from loushang.harness.extensions.types import (
    LoadedExtension,
    RegisteredRuntimeCapabilityReplacement,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    ResourceBundle,
    SkillDescriptor,
)
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    RuntimeCapabilityBindingError,
    RuntimeProfileResolutionError,
    RuntimeProfileSnapshot,
    SideQuestionAnswer,
)
from loushang.harness.session.legacy_side_question import bind_legacy_side_question


class _SideQuestionProviderFactory:
    def __init__(self, name: str) -> None:
        self.name = name

    def bind(self, context: object) -> object:
        return (self.name, context)


def _extension(
    extension_id: str,
    *replacements: RegisteredRuntimeCapabilityReplacement,
    permissions: tuple[str, ...] = (SIDE_QUESTION_RUNTIME_PERMISSION,),
) -> LoadedExtension:
    return LoadedExtension(
        name=extension_id,
        source_path=Path(f"/tmp/{extension_id}.py"),
        manifest=ExtensionManifest(
            id=extension_id,
            name=extension_id,
            permissions=ExtensionPermissionDeclaration(
                capabilities=permissions,
            ),
        ),
        policy=ExtensionPolicyDecision(capabilities=permissions),
        runtime_capability_replacements=list(replacements),
    )


def test_coding_capability_profile_binds_all_default_capabilities(tmp_path) -> None:
    profile = CODING_CAPABILITY_PROFILE
    binding = bind_capability_composition_runtime(profile)
    bundle = ResourceBundle(
        cwd=tmp_path,
        skills=[
            SkillDescriptor(
                name="review",
                source_path=tmp_path / "skills" / "review" / "SKILL.md",
                description="Review changes.",
            )
        ],
    )

    activated = binding.apply_skill_activation(bundle, ("review",))
    assert activated.skills[0].enabled is False
    assert binding.activate_resources(activated).active_skills() == ()
    assert (
        binding.compose_prompt_sections()
        .compose((PromptSection("base", "Base"), PromptSection("tail", "Tail")))
        .text
        == "Base\n\nTail"
    )
    assert binding.compose_tool_packs(
        (
            CapabilityPack("extension", "extension", ("extension",), priority=1),
            CapabilityPack("product", "product", ("product",), priority=2),
        )
    ).items == ("product", "extension")
    assert binding.compose_command_packs(
        (CapabilityPack("commands", "product", ("command",)),)
    ).items == ("command",)
    binding.dispose()


def test_coding_capability_snapshot_is_separate_from_other_header_metadata() -> None:
    profile = CODING_CAPABILITY_PROFILE
    header = ConversationHeader(
        conversation_id="session",
        version=1,
        created_at="2026-07-17T00:00:00Z",
        metadata={
            "cwd": "/workspace",
            CODING_CAPABILITY_PROFILE_METADATA_KEY: profile.snapshot().to_json(),
        },
    )

    snapshot = RuntimeProfileSnapshot.from_json(
        header.metadata[CODING_CAPABILITY_PROFILE_METADATA_KEY]
    )

    assert snapshot.product_id == CODING_PRODUCT_ID
    assert (
        header.metadata[CODING_CAPABILITY_PROFILE_METADATA_KEY]
        == profile.snapshot().to_json()
    )
    assert snapshot.to_json() == profile.snapshot().to_json()
    assert set(slot.key for slot in CODING_CAPABILITY_PLAN.slots) == {
        "resource.runtime",
        "prompt.sections",
        "skill.activation",
        "tool.packs",
        "command.packs",
        "interaction.side_question",
        "continuity.provider_packs",
    }
    assert all(
        slot.allowed_sources == frozenset({"product"})
        for slot in CODING_CAPABILITY_PLAN.slots
        if slot.key != SIDE_QUESTION_PROVIDER_SLOT.key
    )
    assert CODING_CAPABILITY_PLAN.slot(
        SIDE_QUESTION_PROVIDER_SLOT.key
    ).allowed_sources == frozenset({"product", "oem", "extension"})


def test_agent_extension_side_question_replacement_runs_full_profile_chain() -> None:
    created: list[str] = []
    disposed: list[str] = []
    api = ExtensionAPI(
        name="acme.review",
        source_path=Path("/tmp/acme-review.py"),
    )
    api.register_side_question_provider(
        "review",
        create=lambda: (
            created.append("review") or _SideQuestionProviderFactory("review")
        ),
        dispose=lambda value: disposed.append(str(getattr(value, "name"))),
        priority=20,
    )
    loaded = replace(
        api.build_loaded_extension(),
        manifest=ExtensionManifest(
            id="acme.review",
            name="Acme Review",
            permissions=ExtensionPermissionDeclaration(
                capabilities=(SIDE_QUESTION_RUNTIME_PERMISSION,),
            ),
        ),
        policy=ExtensionPolicyDecision(
            capabilities=(SIDE_QUESTION_RUNTIME_PERMISSION,),
        ),
    )
    extension_runtime = ExtensionRunner([loaded])

    resolution = resolve_coding_capability_profile(extension_runtime.active_extensions)
    runtime = resolution.bind()
    side_question = resolution.bind_side_question()

    selected = runtime.profile.capability(SIDE_QUESTION_PROVIDER_SLOT.key).selections
    assert len(selected) == 1
    assert selected[0].source == "extension"
    assert selected[0].layer_id == "extension:acme.review"
    assert selected[0].selection.implementation.endswith(
        ":interaction.side_question:review"
    )
    assert getattr(side_question.provider_factory, "name") == "review"
    assert created == ["review"]
    side_question.dispose()
    runtime.dispose()
    assert disposed == ["review"]


def test_legacy_side_question_binding_ignores_unrelated_implementations() -> None:
    unrelated = standard_capability_composition_implementations()[0]

    binding = bind_legacy_side_question(
        CODING_CAPABILITY_PROFILE,
        additional_implementations=(unrelated, unrelated),
    )

    assert binding.provider_factory is not None
    binding.dispose()


def test_discovered_extension_can_replace_side_question_runtime(tmp_path) -> None:
    extension_dir = tmp_path / "external-side-question"
    extension_dir.mkdir()
    entry_path = extension_dir / "extension.py"
    entry_path.write_text(
        """
class Provider:
    async def ask(self, question, *, on_update=None):
        return None

    def cancel(self):
        pass


class Factory:
    name = "discovered"

    def bind(self, context):
        return Provider()


def register(api):
    api.register_side_question_provider(
        "discovered",
        create=Factory,
        priority=30,
    )
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    (extension_dir / "loushang-extension.toml").write_text(
        """
[extension]
id = "acme.discovered-side-question"
name = "Discovered Side Question"

[permissions]
level = "safe"
capabilities = ["interaction.side_question"]
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    extension_runtime = ExtensionRunner(
        [
            ExtensionDescriptor(
                name="external-side-question",
                source_path=extension_dir,
                entry_path=entry_path,
            )
        ]
    )

    resolution = resolve_coding_capability_profile(extension_runtime.active_extensions)
    runtime = resolution.bind()
    side_question = resolution.bind_side_question()

    assert getattr(side_question.provider_factory, "name") == "discovered"
    assert (
        runtime.profile.capability(SIDE_QUESTION_PROVIDER_SLOT.key)
        .selections[0]
        .layer_id
        == "extension:acme.discovered-side-question"
    )
    assert extension_runtime.get_diagnostics() == []
    assert [
        (surface.type, surface.name)
        for surface in extension_runtime.active_extensions[0].surfaces
    ] == [("runtime_capability", "discovered")]
    side_question.dispose()
    runtime.dispose()


def test_multiple_external_replacements_select_only_the_highest_priority_factory() -> (
    None
):
    created: list[str] = []
    low = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="low",
        create=lambda: created.append("low") or _SideQuestionProviderFactory("low"),
        priority=10,
    )
    high = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="high",
        create=lambda: created.append("high") or _SideQuestionProviderFactory("high"),
        priority=20,
    )

    resolution = resolve_coding_capability_profile(
        (_extension("acme.low", low), _extension("acme.high", high))
    )
    selected = resolution.profile.capability(SIDE_QUESTION_PROVIDER_SLOT.key).selections
    assert len(selected) == 1
    assert selected[0].layer_id == "extension:acme.high"
    assert created == []

    side_question = resolution.bind_side_question()
    assert getattr(side_question.provider_factory, "name") == "high"
    assert created == ["high"]
    side_question.dispose()


def test_ungranted_external_replacement_is_rejected_before_factory_creation() -> None:
    created: list[str] = []
    replacement = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="ungranted",
        create=lambda: (
            created.append("ungranted") or _SideQuestionProviderFactory("ungranted")
        ),
    )

    with pytest.raises(RuntimeProfileResolutionError) as exc_info:
        resolve_coding_capability_profile(
            (_extension("acme.ungranted", replacement, permissions=()),)
        )

    assert [item.code for item in exc_info.value.diagnostics] == [
        "runtime_slot_permission_denied"
    ]
    assert created == []


def test_unknown_external_runtime_slot_is_not_silently_ignored() -> None:
    created: list[str] = []
    replacement = RegisteredRuntimeCapabilityReplacement(
        slot="interaction.future",
        name="future",
        create=lambda: created.append("future") or object(),
    )

    with pytest.raises(RuntimeProfileResolutionError) as exc_info:
        resolve_coding_capability_profile(
            (_extension("acme.future", replacement),)
        )

    assert [item.code for item in exc_info.value.diagnostics] == ["unknown_slot"]
    assert exc_info.value.diagnostics[0].slot == "interaction.future"
    assert created == []


def test_one_extension_cannot_select_a_single_runtime_slot_twice() -> None:
    created: list[str] = []
    first = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="first",
        create=lambda: (
            created.append("first") or _SideQuestionProviderFactory("first")
        ),
    )
    second = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="second",
        create=lambda: (
            created.append("second") or _SideQuestionProviderFactory("second")
        ),
    )

    with pytest.raises(RuntimeProfileResolutionError) as exc_info:
        resolve_coding_capability_profile(
            (_extension("acme.ambiguous", first, second),)
        )

    assert [item.code for item in exc_info.value.diagnostics] == [
        "ambiguous_single_selection"
    ]
    assert created == []


def test_equal_priority_external_candidates_do_not_depend_on_discovery_order() -> None:
    created: list[str] = []
    alpha = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="alpha",
        create=lambda: (
            created.append("alpha") or _SideQuestionProviderFactory("alpha")
        ),
        priority=20,
    )
    zeta = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="zeta",
        create=lambda: (
            created.append("zeta") or _SideQuestionProviderFactory("zeta")
        ),
        priority=20,
    )
    alpha_extension = _extension("acme.alpha", alpha)
    zeta_extension = _extension("acme.zeta", zeta)

    forward = resolve_coding_capability_profile(
        (alpha_extension, zeta_extension)
    )
    reverse = resolve_coding_capability_profile(
        (zeta_extension, alpha_extension)
    )

    forward_selection = forward.profile.capability(
        SIDE_QUESTION_PROVIDER_SLOT.key
    ).selections[0]
    reverse_selection = reverse.profile.capability(
        SIDE_QUESTION_PROVIDER_SLOT.key
    ).selections[0]
    assert forward_selection == reverse_selection
    assert forward_selection.layer_id == "extension:acme.zeta"
    assert created == []

    side_question = reverse.bind_side_question()
    assert getattr(side_question.provider_factory, "name") == "zeta"
    assert created == ["zeta"]
    side_question.dispose()


def test_selected_external_factory_failure_does_not_fallback_to_lower_candidate() -> (
    None
):
    created: list[str] = []
    low = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="low",
        create=lambda: created.append("low") or _SideQuestionProviderFactory("low"),
        priority=10,
    )

    def fail_selected() -> object:
        created.append("high")
        raise RuntimeError("selected Provider unavailable")

    high = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="high",
        create=fail_selected,
        priority=20,
    )
    resolution = resolve_coding_capability_profile(
        (_extension("acme.low", low), _extension("acme.high", high))
    )

    with pytest.raises(RuntimeCapabilityBindingError) as exc_info:
        resolution.bind_side_question()

    assert exc_info.value.implementation.endswith(":interaction.side_question:high")
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "selected Provider unavailable"
    assert created == ["high"]


def test_external_side_question_replacement_binds_to_the_live_coding_session(
    tmp_path,
) -> None:
    bound_contexts: list[object] = []
    disposed: list[str] = []

    class Provider:
        async def ask(self, question: str, *, on_update=None) -> SideQuestionAnswer:
            del on_update
            return SideQuestionAnswer(text=f"external:{question}")

        def cancel(self) -> None:
            pass

    class Factory:
        name = "external"

        def bind(self, context: object) -> Provider:
            bound_contexts.append(context)
            return Provider()

    replacement = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="external",
        create=Factory,
        dispose=lambda value: disposed.append(str(getattr(value, "name"))),
        priority=50,
    )
    extension = _extension("acme.external", replacement)
    extension_runtime = ExtensionRunner([extension])
    capability_runtime = resolve_coding_capability_profile(
        extension_runtime.active_extensions
    ).bind()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(
            agent=Agent(initial_state={"system_prompt": "Coding"}),
            session_manager=manager,
            capability_runtime=capability_runtime,
            extension_runner=extension_runtime,
        )

        answer = await session.ask_side_question("status?")

        assert answer.text == "external:status?"
        assert bound_contexts == [session]
        assert (
            session.capability_profile.capability(SIDE_QUESTION_PROVIDER_SLOT.key)
            .selections[0]
            .source
            == "extension"
        )
        await session.dispose()

    asyncio.run(scenario())
    assert disposed == ["external"]


def test_direct_session_rolls_back_resource_runtime_if_side_question_binding_fails(
    tmp_path,
    monkeypatch,
) -> None:
    events: list[str] = []
    runtime = cast(
        Any,
        SimpleNamespace(dispose=lambda: events.append("dispose:resources")),
    )

    class Resolution:
        def bind(self):  # type: ignore[no-untyped-def]
            events.append("bind:resources")
            return runtime

        def bind_side_question(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("side-question binding failed")

    monkeypatch.setattr(
        agent_session_module,
        "resolve_coding_capability_profile",
        lambda _extensions: Resolution(),
    )

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        with pytest.raises(RuntimeError, match="side-question binding failed"):
            AgentSession(
                agent=Agent(initial_state={"system_prompt": "Coding"}),
                session_manager=manager,
                extension_runner=ExtensionRunner([]),
            )

    asyncio.run(scenario())
    assert events == ["bind:resources", "dispose:resources"]


def test_direct_session_rolls_back_side_question_after_late_construction_failure(
    tmp_path,
    monkeypatch,
) -> None:
    disposed: list[str] = []

    class Factory:
        name = "external"

        def bind(self, _context: object) -> object:
            return SimpleNamespace(cancel=lambda: None)

    replacement = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="external",
        create=Factory,
        dispose=lambda value: disposed.append(str(getattr(value, "name"))),
    )
    monkeypatch.setattr(
        agent_product_module,
        "compose_session_runtime",
        lambda _ports: (_ for _ in ()).throw(RuntimeError("composition failed")),
    )

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        with pytest.raises(RuntimeError, match="composition failed"):
            AgentSession(
                agent=Agent(initial_state={"system_prompt": "Coding"}),
                session_manager=manager,
                extension_runner=ExtensionRunner(
                    [_extension("acme.external", replacement)]
                ),
            )

    asyncio.run(scenario())
    assert disposed == ["external"]


def test_session_shutdown_cancels_external_side_question_before_factory_disposal(
    tmp_path,
) -> None:
    events: list[str] = []

    class Provider:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def ask(self, question: str, *, on_update=None) -> SideQuestionAnswer:
            del question, on_update
            self.started.set()
            await asyncio.Future()
            raise AssertionError("unreachable")

        def cancel(self) -> None:
            events.append("cancel")

    provider = Provider()

    class Factory:
        def bind(self, context: object) -> Provider:
            del context
            return provider

    replacement = RegisteredRuntimeCapabilityReplacement(
        slot=SIDE_QUESTION_PROVIDER_SLOT.key,
        name="blocking",
        create=Factory,
        dispose=lambda _value: events.append("dispose"),
    )

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(
            agent=Agent(initial_state={"system_prompt": "Coding"}),
            session_manager=manager,
            extension_runner=ExtensionRunner(
                [_extension("acme.blocking", replacement)]
            ),
        )
        task = asyncio.create_task(session.ask_side_question("wait"))
        await provider.started.wait()

        await session.dispose()

        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert events == ["cancel", "dispose"]
