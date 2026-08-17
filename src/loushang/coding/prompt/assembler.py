"""Coding compatibility adapter over standard Harness prompt assembly."""

from __future__ import annotations

from typing import Any

from loushang.agent.types import AgentTool
from loushang.coding.prompt.defaults import DEFAULT_CODING_SYSTEM_PROMPT
from loushang.harness.capabilities.prompt import PromptSectionComposer
from loushang.harness.capabilities.prompt_assembly import (
    PromptAssembly,
)
from loushang.harness.capabilities.prompt_assembly import (
    assemble_prompt as assemble_harness_prompt,
)
from loushang.harness.resources.activation import ResourceActivation
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.tools.core import ToolDefinition


def assemble_prompt(
    *,
    base_prompt: str | None = None,
    resource_bundle: ResourceBundle | None = None,
    tool_definitions: list[ToolDefinition] | None = None,
    tools: list[AgentTool[Any]] | None = None,
    tool_prompt: str | None = None,
    resource_activation: ResourceActivation | None = None,
    prompt_section_composer: PromptSectionComposer | None = None,
) -> PromptAssembly:
    """Assemble a prompt while preserving Coding's historical default."""

    effective_base = (
        base_prompt
        if isinstance(base_prompt, str) and base_prompt.strip()
        else DEFAULT_CODING_SYSTEM_PROMPT
    )
    return assemble_harness_prompt(
        base_prompt=effective_base,
        resource_bundle=resource_bundle,
        tool_definitions=tool_definitions,
        tools=tools,
        tool_prompt=tool_prompt,
        resource_activation=resource_activation,
        prompt_section_composer=prompt_section_composer,
    )


def assemble_system_prompt(
    *,
    base_prompt: str | None = None,
    resource_bundle: ResourceBundle | None = None,
) -> str:
    return assemble_prompt(
        base_prompt=base_prompt,
        resource_bundle=resource_bundle,
    ).system_prompt


__all__ = [
    "DEFAULT_CODING_SYSTEM_PROMPT",
    "PromptAssembly",
    "assemble_prompt",
    "assemble_system_prompt",
]
