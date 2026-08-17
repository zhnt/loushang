from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace

import pytest

from loushang.harness.capabilities import (
    CapabilityGraphBindingError,
    CapabilityGraphPlanRequest,
    CapabilityPack,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphPlanner,
    RuntimeCapabilityGraphRuntime,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.prompt import PromptSection
from loushang.harness.capabilities.resources_consumers import (
    ResourceActivationCapabilityConsumer,
    ResourceCommandPackCapabilityConsumer,
    ResourcePromptCapabilityConsumer,
    ResourceToolPackCapabilityConsumer,
)
from loushang.harness.capabilities.resources_contracts import (
    RESOURCES_ACTIVATION_REQUIREMENT,
    RESOURCES_CAPABILITY_DEFINITION,
    RESOURCES_COMMAND_PACK_REQUIREMENT,
    RESOURCES_PROMPT_REQUIREMENT,
    RESOURCES_TOOL_PACK_REQUIREMENT,
)
from loushang.harness.capabilities.resources_provider import (
    resources_capability_provider_binding,
)
from loushang.harness.resources.activation import ResourceActivationRuntime
from loushang.harness.resources.types import ResourceBundle, SkillDescriptor
from loushang.harness.runtime import (
    COMMAND_PACKS_SLOT,
    PROMPT_SECTIONS_SLOT,
    RESOURCE_RUNTIME_SLOT,
    SIDE_QUESTION_PROVIDER_SLOT,
    RuntimeCapabilityImplementation,
    RuntimeProfileResolver,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _profile(*, separator: str = "\n"):
    return RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(
            product_id="research",
            prompt_separator=separator,
            strip_prompt_sections=False,
        )
    )


def _plan(binding):  # type: ignore[no-untyped-def]
    return RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="research",
            roots=(RESOURCES_CAPABILITY_DEFINITION.capability_id,),
            definitions=(RESOURCES_CAPABILITY_DEFINITION,),
            providers=(binding.provider,),
        )
    )


def _replace_selection(profile, slot: str, **changes):  # type: ignore[no-untyped-def]
    capabilities = []
    for capability in profile.capabilities:
        if capability.slot.key != slot:
            capabilities.append(capability)
            continue
        resolved = capability.selections[0]
        capabilities.append(
            replace(
                capability,
                selections=(
                    replace(
                        resolved,
                        selection=replace(resolved.selection, **changes),
                    ),
                ),
            )
        )
    return replace(profile, capabilities=tuple(capabilities))


def test_resources_seam_exposes_focused_consumers_without_live_registrations(
    tmp_path,
) -> None:
    async def scenario() -> None:
        profile = _profile()
        binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:research",
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="research",
            runtime_id="research-session",
            profile_fingerprint=_sha("profile"),
        )
        binder = RuntimeCapabilityGraphBinder()
        await binder.bind(runtime, _plan(binding), (binding,))

        activation = ResourceActivationCapabilityConsumer(
            runtime.capture(RESOURCES_ACTIVATION_REQUIREMENT)
        )
        prompt = ResourcePromptCapabilityConsumer(
            runtime.capture(RESOURCES_PROMPT_REQUIREMENT)
        )
        tools = ResourceToolPackCapabilityConsumer(
            runtime.capture(RESOURCES_TOOL_PACK_REQUIREMENT)
        )
        commands = ResourceCommandPackCapabilityConsumer(
            runtime.capture(RESOURCES_COMMAND_PACK_REQUIREMENT)
        )
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

        disabled = activation.apply_skill_activation(bundle, ["review"])
        assert activation.activate(disabled).active_skills() == ()
        assert (
            prompt.compose(
                (PromptSection("base", "Base"), PromptSection("tail", "Tail"))
            ).text
            == "Base\nTail"
        )
        assert tools.compose(
            (CapabilityPack("tools", "product", ("tool",)),)
        ).items == ("tool",)
        assert commands.compose(
            (CapabilityPack("commands", "product", ("command",)),)
        ).items == ("command",)
        assert runtime.snapshot is not None
        assert runtime.snapshot.nodes[0].scope == "session"
        assert runtime.snapshot.nodes[0].phase == "bootstrap"
        assert RESOURCES_CAPABILITY_DEFINITION.refresh_boundary == "sealed"
        private_resource_slot = profile.capability(RESOURCE_RUNTIME_SLOT.key).slot
        assert private_resource_slot.scope == "workspace"
        assert private_resource_slot.refresh_boundary == "sealed"
        assert runtime.registration_inventory is not None
        assert runtime.registration_inventory.entries == ()
        await binder.dispose(runtime)

    asyncio.run(scenario())


def test_resources_fingerprint_covers_construction_inputs_but_not_side_question() -> (
    None
):
    profile = _profile()
    baseline = resources_capability_provider_binding(
        profile=profile,
        scope_instance_id="session:one",
    ).binding_input_fingerprint

    assert (
        resources_capability_provider_binding(
            profile=_profile(separator="\n\n"),
            scope_instance_id="session:one",
        ).binding_input_fingerprint
        != baseline
    )
    assert (
        resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:two",
        ).binding_input_fingerprint
        != baseline
    )
    assert (
        resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:one",
            provider_id="research.resources.alternate",
        ).binding_input_fingerprint
        != baseline
    )

    for slot in (
        RESOURCE_RUNTIME_SLOT.key,
        PROMPT_SECTIONS_SLOT.key,
        "skill.activation",
        "tool.packs",
        "command.packs",
    ):
        changed = _replace_selection(
            profile,
            slot,
            implementation=f"research.changed.{slot}",
        )
        assert (
            resources_capability_provider_binding(
                profile=changed,
                scope_instance_id="session:one",
            ).binding_input_fingerprint
            != baseline
        )

    side_question_only = _replace_selection(
        profile,
        SIDE_QUESTION_PROVIDER_SLOT.key,
        implementation="research.changed.side-question",
    )
    assert (
        resources_capability_provider_binding(
            profile=side_question_only,
            scope_instance_id="session:one",
        ).binding_input_fingerprint
        == baseline
    )


def test_resources_content_only_use_does_not_publish_a_new_mount(tmp_path) -> None:
    async def scenario() -> None:
        binding = resources_capability_provider_binding(
            profile=_profile(),
            scope_instance_id="session:research",
        )
        plan = _plan(binding)
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="research",
            runtime_id="research-session",
            profile_fingerprint=_sha("profile"),
        )
        binder = RuntimeCapabilityGraphBinder()
        await binder.bind(runtime, plan, (binding,))
        generation = runtime.generation
        consumer = ResourceActivationCapabilityConsumer(
            runtime.capture(RESOURCES_ACTIVATION_REQUIREMENT)
        )

        consumer.activate(ResourceBundle(cwd=tmp_path))
        consumer.activate(ResourceBundle(cwd=tmp_path, prompt_fragments=["changed"]))
        reused = await binder.bind(runtime, plan, (binding,))

        assert reused.created_capability_ids == ()
        assert reused.reused_capability_ids == ("harness.resources",)
        assert runtime.generation == generation
        await binder.dispose(runtime)

    asyncio.run(scenario())


@pytest.mark.parametrize("termination", ["failure", "pending_cancel", "raised_cancel"])
def test_resources_provider_failure_or_cancellation_cleans_private_profile_values(
    termination: str,
) -> None:
    async def scenario() -> None:
        disposed: list[str] = []
        profile = _replace_selection(
            _profile(),
            RESOURCE_RUNTIME_SLOT.key,
            implementation="research.resource-runtime",
        )
        terminal_slot = (
            PROMPT_SECTIONS_SLOT.key
            if termination == "failure"
            else COMMAND_PACKS_SLOT.key
        )
        profile = _replace_selection(
            profile,
            terminal_slot,
            implementation="research.terminal",
        )

        def finish(_selection, _context):  # type: ignore[no-untyped-def]
            if termination == "pending_cancel":
                task = asyncio.current_task()
                assert task is not None
                task.cancel()
                from loushang.harness.capabilities.packs import CapabilityPackComposer

                return CapabilityPackComposer()
            if termination == "raised_cancel":
                raise asyncio.CancelledError
            raise RuntimeError("provider construction failed")

        binding = resources_capability_provider_binding(
            profile=profile,
            scope_instance_id="session:research",
            additional_implementations=(
                RuntimeCapabilityImplementation(
                    slot=RESOURCE_RUNTIME_SLOT.key,
                    implementation="research.resource-runtime",
                    implementation_version=1,
                    create=lambda _selection, _context: ResourceActivationRuntime(),
                    dispose=lambda _value, _context: disposed.append("resource"),
                ),
                RuntimeCapabilityImplementation(
                    slot=terminal_slot,
                    implementation="research.terminal",
                    implementation_version=1,
                    create=finish,
                ),
            ),
        )
        runtime = RuntimeCapabilityGraphRuntime(
            product_id="research",
            runtime_id="research-session",
            profile_fingerprint=_sha("profile"),
        )
        binder = RuntimeCapabilityGraphBinder()

        expected = (
            CapabilityGraphBindingError
            if termination == "failure"
            else asyncio.CancelledError
        )
        with pytest.raises(expected):
            await binder.bind(runtime, _plan(binding), (binding,))

        assert disposed == ["resource"]
        assert runtime.generation == 0
        assert runtime.snapshot is None
        assert runtime.registration_inventory is not None
        assert runtime.registration_inventory.entries == ()

    asyncio.run(scenario())
