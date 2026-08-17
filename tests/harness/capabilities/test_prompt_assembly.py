from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from loushang.harness.capabilities.prompt_assembly import (
    DEFAULT_HARNESS_SYSTEM_PROMPT,
    PromptAssembly,
    assemble_prompt,
)
from loushang.harness.capabilities.prompt_preflight import (
    preflight_user_input,
    preflight_user_input_async,
)
from loushang.harness.resources.activation import ResourceActivation
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution


def _runtime_footer(cwd: str) -> str:
    return f"Current date: {date.today().isoformat()}\nCurrent working directory: {cwd}"


def test_standard_assembly_uses_harness_default_and_allows_an_empty_base() -> None:
    assert assemble_prompt().system_prompt == DEFAULT_HARNESS_SYSTEM_PROMPT.strip()
    assert assemble_prompt(base_prompt="").system_prompt == ""


def test_standard_assembly_projects_resources_skills_tools_and_runtime() -> None:
    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        raise AssertionError("not used in this test")

    context = PromptFragmentDescriptor(
        name="AGENTS.md",
        source_path=Path("/tmp/research/AGENTS.md"),
        text="Verify primary sources.",
        prompt_kind="agents_md",
    )
    resource = PromptFragmentDescriptor(
        name="citation-style",
        source_path=Path("/tmp/research/prompts/citation-style.md"),
        text="Cite claims inline.",
    )
    bundle = ResourceBundle(
        cwd=Path("/tmp/research"),
        prompt_descriptors=[context, resource],
        prompt_fragments=[context.text, resource.text],
        skills=[
            SkillDescriptor(
                name="source-review",
                source_path=Path("/tmp/research/skills/source-review/SKILL.md"),
                description="Check the strength of cited evidence.",
            )
        ],
    )
    tool = ToolDefinition(
        name="catalog_search",
        label="Catalog Search",
        description="Search a catalog.",
        parameters={"type": "object"},
        execution=direct_execution(execute),
        prompt_snippet="Search the research catalog",
        prompt_guidelines=("Prefer primary records.",),
    )

    assembly = assemble_prompt(
        base_prompt="You are a research assistant.",
        resource_activation=ResourceActivation(bundle),
        tool_definitions=[tool],
    )

    assert isinstance(assembly, PromptAssembly)
    assert assembly.system_prompt.startswith(
        "You are a research assistant.\n\n# Project Context"
    )
    assert "## /tmp/research/AGENTS.md\n\nVerify primary sources." in (
        assembly.system_prompt
    )
    assert "Cite claims inline." in assembly.system_prompt
    assert "<name>source-review</name>" in assembly.system_prompt
    assert "- catalog_search: Search the research catalog" in assembly.system_prompt
    assert "- Prefer primary records." in assembly.system_prompt
    assert assembly.system_prompt.endswith(_runtime_footer("/tmp/research"))
    assert assembly.tool_prompt == (
        "Available tools:\n"
        "- catalog_search: Search the research catalog\n"
        "- Prefer primary records."
    )
    assert assembly.resource_fragments[1] == "Cite claims inline."


def test_standard_preflight_expands_prompt_and_escapes_skill_attributes() -> None:
    bundle = ResourceBundle(
        cwd=Path("/tmp/research"),
        prompts=[
            PromptFragmentDescriptor(
                name="compare",
                source_path=Path("/tmp/research/prompts/compare.md"),
                text="Compare $1 with ${@:2}.",
            )
        ],
        skills=[
            SkillDescriptor(
                name='review"source',
                source_path=Path('/tmp/research/skills/review"source/SKILL.md'),
                content="---\nname: review-source\n---\n\nInspect the evidence.",
            )
        ],
    )

    prompt_result = preflight_user_input(
        "/compare option-a option-b option-c",
        resource_bundle=bundle,
    )
    skill_result = preflight_user_input(
        '/skill:review"source focus',
        resource_bundle=bundle,
    )

    assert prompt_result.text == "Compare option-a with option-b option-c."
    assert skill_result.text.startswith(
        '<skill name="review&quot;source" '
        'location="/tmp/research/skills/review&quot;source/SKILL.md">'
    )
    assert "Inspect the evidence." in skill_result.text
    assert skill_result.text.endswith("</skill>\n\nfocus")


def test_standard_async_preflight_can_delegate_a_command() -> None:
    calls: list[tuple[str, str]] = []

    async def execute_command(name: str, arguments: str) -> None:
        calls.append((name, arguments))

    result = asyncio.run(
        preflight_user_input_async(
            "/publish draft",
            execute_command=execute_command,
        )
    )

    assert result.consumed is True
    assert result.text == "/publish draft"
    assert calls == [("publish", "draft")]
