from __future__ import annotations

import pytest

from loushang.harness.capabilities import (
    CapabilityPack,
    bind_capability_composition_runtime,
    standard_capability_composition_implementations,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.composition_runtime import (
    DISABLED_SKILL_ACTIVATION_IMPLEMENTATION,
    ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
    PROMPT_SECTIONS_IMPLEMENTATION,
    RESOURCE_ACTIVATION_IMPLEMENTATION,
)
from loushang.harness.capabilities.prompt import PromptSection
from loushang.harness.resources.types import ResourceBundle, SkillDescriptor
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    ProductRuntimePlan,
    RuntimeCapabilityBindingError,
    RuntimeCapabilitySelection,
    RuntimeProfileResolver,
    standard_capability_composition_slots,
)
from loushang.harness.session.legacy_side_question import bind_legacy_side_question


def _profile(*, prompt_config: dict[str, object] | None = None):
    plan = ProductRuntimePlan(
        product_id="research",
        slots=standard_capability_composition_slots(),
        defaults=(
            RuntimeCapabilitySelection(
                slot="resource.runtime",
                implementation=RESOURCE_ACTIVATION_IMPLEMENTATION,
                implementation_version=1,
            ),
            RuntimeCapabilitySelection(
                slot="prompt.sections",
                implementation=PROMPT_SECTIONS_IMPLEMENTATION,
                implementation_version=1,
                config=prompt_config or {"separator": "\n", "stripSections": False},
            ),
            RuntimeCapabilitySelection(
                slot="skill.activation",
                implementation=DISABLED_SKILL_ACTIVATION_IMPLEMENTATION,
                implementation_version=1,
            ),
            RuntimeCapabilitySelection(
                slot="tool.packs",
                implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
                implementation_version=1,
            ),
            RuntimeCapabilitySelection(
                slot="command.packs",
                implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
                implementation_version=1,
            ),
        ),
    )
    return RuntimeProfileResolver().resolve(plan)


def test_standard_composition_runtime_binds_neutral_product_values(tmp_path) -> None:
    runtime = bind_capability_composition_runtime(_profile())
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

    activated = runtime.apply_skill_activation(bundle, ("review",))

    assert runtime.activate_resources(activated).active_skills() == ()
    assert (
        runtime.compose_prompt_sections()
        .compose((PromptSection("base", "Base"), PromptSection("tail", "Tail")))
        .text
        == "Base\nTail"
    )
    assert runtime.compose_tool_packs(
        (
            CapabilityPack("extension", "extension", ("extension",), priority=1),
            CapabilityPack("product", "product", ("product",), priority=2),
        )
    ).items == ("product", "extension")
    assert runtime.compose_command_packs(
        (CapabilityPack("commands", "product", ("command",)),)
    ).items == ("command",)
    runtime.dispose()


def test_standard_composition_plan_is_reusable_by_another_product() -> None:
    plan = standard_capability_composition_plan(
        product_id="design",
        allowed_sources=frozenset({"product", "oem"}),
        prompt_separator="\n",
        strip_prompt_sections=False,
    )
    profile = RuntimeProfileResolver().resolve(plan)
    runtime = bind_capability_composition_runtime(profile)

    assert profile.product_id == "design"
    assert (
        runtime.compose_prompt_sections()
        .compose((PromptSection("base", " Base "), PromptSection("tail", " Tail ")))
        .text
        == " Base \n Tail "
    )
    assert all(
        slot.allowed_sources == frozenset({"product", "oem"}) for slot in plan.slots
    )
    runtime.dispose()


def test_standard_composition_plan_supports_per_slot_source_boundaries() -> None:
    plan = standard_capability_composition_plan(
        product_id="coding",
        slot_allowed_sources={
            SIDE_QUESTION_PROVIDER_SLOT.key: frozenset(
                {"product", "oem", "extension"}
            )
        },
    )
    profile = RuntimeProfileResolver().resolve(plan)
    runtime = bind_capability_composition_runtime(profile)
    slots = {slot.key: slot for slot in plan.slots}

    assert slots["resource.runtime"].allowed_sources == frozenset({"product"})
    assert slots[SIDE_QUESTION_PROVIDER_SLOT.key].allowed_sources == frozenset(
        {"product", "oem", "extension"}
    )
    assert SIDE_QUESTION_PROVIDER_SLOT.key not in runtime.binding.values()
    assert SIDE_QUESTION_PROVIDER_SLOT.key in {
        implementation.slot
        for implementation in standard_capability_composition_implementations()
    }
    assert not hasattr(runtime, "side_question_provider_factory")
    side_question = bind_legacy_side_question(profile)
    assert side_question.provider_factory is not None
    side_question.dispose()
    runtime.dispose()


def test_standard_composition_runtime_rejects_unknown_configuration() -> None:
    profile = _profile(
        prompt_config={"separator": "\n\n", "stripSections": True, "extra": True}
    )

    with pytest.raises(RuntimeCapabilityBindingError) as exc_info:
        bind_capability_composition_runtime(profile)

    assert exc_info.value.slot == "prompt.sections"
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "configuration must contain" in str(exc_info.value.__cause__)
