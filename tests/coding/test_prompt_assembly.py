from __future__ import annotations

import asyncio
from datetime import date

from loushang.harness.tools.execution import direct_execution


def _runtime_footer(cwd: str) -> str:
    return f"Current date: {date.today().isoformat()}\nCurrent working directory: {cwd}"


def test_default_system_prompt_includes_exploration_progress_guidelines() -> None:
    from loushang.coding.prompt import assemble_prompt

    system_prompt = assemble_prompt().system_prompt

    assert (
        "首次探索工具调用前，必须先用一句话说明本轮要验证什么；不要直接开始扫描。"
        in system_prompt
    )
    assert (
        "连续执行 3 次探索工具调用后，必须先汇总已确认信息，再决定是否继续。"
        in system_prompt
    )
    assert (
        "避免无明确目标地批量列目录、搜索和读取文件；证据足够时停止探索并回答。"
        in system_prompt
    )
    assert (
        "进度说明只在目标变化、关键证据、阶段切换或需用户决策时发送，保持简短。"
        in system_prompt
    )
    assert "多步骤任务阶段结束时说明结果、验证和下一步或阻塞。" in system_prompt


def test_assemble_prompt_returns_prompt_assembly() -> None:
    from pathlib import Path

    from loushang.coding.prompt import assemble_prompt
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    registry = ToolRegistry()
    register_builtin_tools(registry)

    assembly = assemble_prompt(
        base_prompt="Base",
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            prompt_fragments=["Repo rules", " ", "\n", "More rules"],
        ),
        tool_definitions=registry.list_enabled_definitions(),
    )

    expected_tool_prompt = (
        "Available tools:\n"
        "- bash: Execute shell commands. Prefer a single command string; use cwd for the working directory.\n"
        "- Use bash for shell pipelines, redirects, and commands that are easier to express through the user's shell.\n"
        "- Prefer read, grep, find, ls, write, and edit for file operations when those tools are more precise.\n"
        "- read: Read text files and images from the coding workspace.\n"
        "- ls: List directory entries in the coding workspace.\n"
        "- find: Find file paths by glob pattern in the coding workspace.\n"
        "- Use find to locate files by path pattern instead of shelling out to find/fd.\n"
        "- Patterns with glob metacharacters are matched as globs; plain patterns match path substrings.\n"
        "- grep: Search file contents for patterns in the coding workspace.\n"
        "- Use grep to search file contents instead of shelling out to grep or rg.\n"
        "- Use literal=true for exact text searches and glob to narrow file types.\n"
        "- write: Write a text file in the coding workspace.\n"
        "- edit: Apply exact text replacements to a file in the coding workspace."
    )
    assert (
        assembly.system_prompt
        == f"Base\n\nRepo rules\n\nMore rules\n\n{expected_tool_prompt}\n\n{_runtime_footer('/tmp/project')}"
    )
    assert assembly.tool_prompt == expected_tool_prompt
    assert assembly.resource_fragments == ("Repo rules", "More rules")


def test_assemble_system_prompt_keeps_legacy_string_only_contract() -> None:
    from pathlib import Path

    from loushang.coding.prompt import assemble_system_prompt
    from loushang.harness.resources.types import ResourceBundle

    system_prompt = assemble_system_prompt(
        base_prompt="Base",
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"), prompt_fragments=[" Repo rules ", "", "   "]
        ),
    )

    assert system_prompt == f"Base\n\nRepo rules\n\n{_runtime_footer('/tmp/project')}"


def test_assemble_prompt_wraps_context_files_with_paths_before_runtime_footer() -> None:
    from pathlib import Path

    from loushang.coding.prompt import assemble_prompt
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
    )

    root_context = PromptFragmentDescriptor(
        name="AGENTS.md",
        source_path=Path("/tmp/workspace/AGENTS.md"),
        text="Workspace rules",
        canonical_name="AGENTS.md",
        prompt_kind="agents_md",
    )
    project_context = PromptFragmentDescriptor(
        name="CLAUDE.md",
        source_path=Path("/tmp/workspace/project/CLAUDE.md"),
        text="Project rules",
        canonical_name="CLAUDE.md",
        prompt_kind="claude_md",
    )
    prompt_asset = PromptFragmentDescriptor(
        name="repo",
        source_path=Path("/tmp/workspace/project/prompts/repo.md"),
        text="Prompt rules",
        canonical_name="repo.md",
        prompt_kind="prompt_asset",
    )

    assembly = assemble_prompt(
        base_prompt="Base",
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/workspace/project"),
            prompt_descriptors=[root_context, project_context, prompt_asset],
            prompt_fragments=["Workspace rules", "Project rules", "Prompt rules"],
            prompts=[prompt_asset],
        ),
    )

    expected_context = (
        "# Project Context\n\n"
        "Project-specific instructions and guidelines:\n\n"
        "## /tmp/workspace/AGENTS.md\n\n"
        "Workspace rules\n\n"
        "## /tmp/workspace/project/CLAUDE.md\n\n"
        "Project rules"
    )
    assert assembly.system_prompt == (
        f"Base\n\n{expected_context}\n\nPrompt rules\n\n{_runtime_footer('/tmp/workspace/project')}"
    )
    assert assembly.resource_fragments == (expected_context, "Prompt rules")


def test_assemble_prompt_includes_visible_skill_summaries_and_hides_explicit_only_skills() -> (
    None
):
    from pathlib import Path

    from loushang.coding.prompt import assemble_prompt
    from loushang.harness.resources.types import (
        ResourceBundle,
        SkillDescriptor,
    )

    assembly = assemble_prompt(
        base_prompt="Base",
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            skills=[
                SkillDescriptor(
                    name="debugging",
                    description="Debug failures by tracing the narrowest failing path.",
                    source_path=Path("/tmp/project/skills/debugging/SKILL.md"),
                ),
                SkillDescriptor(
                    name="deploy",
                    description="Deployment-only workflow.",
                    source_path=Path("/tmp/project/skills/deploy/SKILL.md"),
                    disable_model_invocation=True,
                ),
            ],
        ),
    )

    assert "<available_skills>" in assembly.system_prompt
    assert "<name>debugging</name>" in assembly.system_prompt
    assert (
        "<description>Debug failures by tracing the narrowest failing path.</description>"
        in assembly.system_prompt
    )
    assert "/tmp/project/skills/debugging/SKILL.md" in assembly.system_prompt
    assert "deploy" not in assembly.system_prompt


def test_assemble_prompt_keeps_legacy_tool_prompt_argument() -> None:
    from loushang.coding.prompt import assemble_prompt

    assembly = assemble_prompt(
        base_prompt="Base",
        tool_prompt="Available tools:\n- legacy: preserved",
    )

    assert assembly.system_prompt == "Base\n\nAvailable tools:\n- legacy: preserved"
    assert assembly.tool_prompt == "Available tools:\n- legacy: preserved"


def test_assemble_prompt_prefers_explicit_tool_prompt_over_tools() -> None:
    from loushang.coding.prompt import assemble_prompt
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    registry = ToolRegistry()
    register_builtin_tools(registry)

    assembly = assemble_prompt(
        base_prompt="Base",
        tool_definitions=registry.list_enabled_definitions(),
        tool_prompt="Available tools:\n- legacy: preserved",
    )

    assert assembly.system_prompt == "Base\n\nAvailable tools:\n- legacy: preserved"
    assert assembly.tool_prompt == "Available tools:\n- legacy: preserved"


def test_assemble_prompt_uses_tool_prompt_snippets_and_hides_tools_without_snippet() -> (
    None
):
    from loushang.coding.prompt import assemble_prompt
    from loushang.harness.tools.workspace import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        raise AssertionError("not used in this test")

    assembly = assemble_prompt(
        base_prompt="Base",
        tool_definitions=[
            ToolDefinition(
                name="visible_tool",
                label="Visible Tool",
                description="visible description should not be used",
                parameters={"type": "object"},
                execution=direct_execution(execute),
                prompt_snippet="Run visible behavior",
                prompt_guidelines=("Use visible_tool when asked.",),
            ),
            ToolDefinition(
                name="formatted_tool",
                label="Formatted Tool",
                description="formatted description should not be used",
                parameters={"type": "object"},
                execution=direct_execution(execute),
                prompt_snippet="- formatted_tool: Keep formatted snippet",
            ),
            ToolDefinition(
                name="hidden_tool",
                label="Hidden Tool",
                description="hidden description should not appear",
                parameters={"type": "object"},
                execution=direct_execution(execute),
            ),
        ],
    )

    expected_tool_prompt = (
        "Available tools:\n"
        "- visible_tool: Run visible behavior\n"
        "- Use visible_tool when asked.\n"
        "- formatted_tool: Keep formatted snippet"
    )
    assert assembly.tool_prompt == expected_tool_prompt
    assert assembly.system_prompt == f"Base\n\n{expected_tool_prompt}"


def test_tuple_backed_inputs_snapshot_mutable_constructors() -> None:
    from loushang.harness.capabilities.prompt_assembly import PromptAssembly
    from loushang.harness.tools.core import ToolDefinition
    from loushang.harness.workspace.exec import ExecRequest

    command = ["bash", "-lc", "echo hi"]
    env = [["A", "1"], ["B", "2"]]
    fragments = ["one", "two"]
    prompt_guidelines = ["keep edits narrow", "prefer explicit tool names"]

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        raise AssertionError("not used in this test")

    exec_request = ExecRequest(command=command, env=env)
    tool_definition = ToolDefinition(
        name="tool",
        label="Tool",
        description="Tool description",
        parameters={"type": "object"},
        execution=direct_execution(execute),
        prompt_guidelines=prompt_guidelines,
    )
    prompt_assembly = PromptAssembly(
        system_prompt="sys", tool_prompt="tool", resource_fragments=fragments
    )

    command.append("later")
    env.append(["C", "3"])
    fragments.append("later")
    prompt_guidelines.append("later")

    assert exec_request.command == ("bash", "-lc", "echo hi")
    assert exec_request.env == (("A", "1"), ("B", "2"))
    assert tool_definition.prompt_guidelines == (
        "keep edits narrow",
        "prefer explicit tool names",
    )
    assert prompt_assembly.resource_fragments == ("one", "two")


def test_tuple_backed_constructors_reject_bare_strings() -> None:
    from loushang.harness.capabilities.prompt_assembly import PromptAssembly
    from loushang.harness.tools.core import ToolDefinition
    from loushang.harness.workspace.exec import ExecRequest

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        raise AssertionError("not used in this test")

    try:
        ExecRequest(command="bash", env=[])
    except TypeError as exc:
        assert "command" in str(exc)
    else:
        raise AssertionError("ExecRequest.command should reject bare strings")

    try:
        ToolDefinition(
            name="tool",
            label="Tool",
            description="Tool description",
            parameters={"type": "object"},
            execution=direct_execution(execute),
            prompt_guidelines="keep edits narrow",
        )
    except TypeError as exc:
        assert "prompt_guidelines" in str(exc)
    else:
        raise AssertionError(
            "ToolDefinition.prompt_guidelines should reject bare strings"
        )

    try:
        PromptAssembly(
            system_prompt="sys", tool_prompt="tool", resource_fragments="one"
        )
    except TypeError as exc:
        assert "resource_fragments" in str(exc)
    else:
        raise AssertionError(
            "PromptAssembly.resource_fragments should reject bare strings"
        )


def test_tool_definition_prompt_guidelines_reject_non_strings() -> None:
    from loushang.harness.tools.core import ToolDefinition
    from loushang.harness.workspace.exec import ExecRequest

    bad_env_values = [["A=1"], ["A"], [("A",)], [("A", "1", "extra")]]
    bad_prompt_guideline_values = [[1], [("A",)], [["nested"]]]

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        raise AssertionError("not used in this test")

    for bad_env in bad_env_values:
        try:
            ExecRequest(command=["bash"], env=bad_env)
        except TypeError as exc:
            assert "env" in str(exc)
        else:
            raise AssertionError(f"ExecRequest.env should reject {bad_env!r}")

    for bad_prompt_guidelines in bad_prompt_guideline_values:
        try:
            ToolDefinition(
                name="tool",
                label="Tool",
                description="Tool description",
                parameters={"type": "object"},
                execution=direct_execution(execute),
                prompt_guidelines=bad_prompt_guidelines,
            )
        except TypeError as exc:
            assert "prompt_guidelines" in str(exc)
        else:
            raise AssertionError(
                f"ToolDefinition.prompt_guidelines should reject {bad_prompt_guidelines!r}"
            )


def test_exec_result_contract_defaults_and_shape() -> None:
    from loushang.harness.workspace.exec import ExecResult

    assert ExecResult(exit_code=7, stdout="out", stderr="err") == ExecResult(
        exit_code=7,
        stdout="out",
        stderr="err",
        timed_out=False,
    )
    assert ExecResult(exit_code=0, stdout="", stderr="").timed_out is False


def test_preflight_user_input_expands_prompt_templates_and_skill_references() -> None:
    from pathlib import Path

    from loushang.harness.capabilities.prompt_preflight import preflight_user_input
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
        SkillDescriptor,
    )

    resource_bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="plan",
                source_path=Path("/tmp/project/prompts/plan.md"),
                text="Use a planning workflow before editing.",
            )
        ],
        skills=[
            SkillDescriptor(
                name="debugging",
                source_path=Path("/tmp/project/skills/debugging/SKILL.md"),
                content="---\nname: debugging\n---\n\nCheck the failing path first.",
            )
        ],
    )

    prompt_result = preflight_user_input(
        "/plan focus on retries", resource_bundle=resource_bundle
    )
    skill_result = preflight_user_input(
        "/skill:debugging inspect the failing branch", resource_bundle=resource_bundle
    )

    assert (
        prompt_result.text
        == "Use a planning workflow before editing.\n\nfocus on retries"
    )
    assert prompt_result.diagnostics == ()
    assert skill_result.text == (
        '<skill name="debugging" location="/tmp/project/skills/debugging/SKILL.md">\n'
        "References are relative to /tmp/project/skills/debugging.\n\n"
        "Check the failing path first.\n"
        "</skill>\n\n"
        "inspect the failing branch"
    )
    assert skill_result.diagnostics == ()


def test_prompt_template_args_parse_quotes_and_substitute_pi_placeholders() -> None:
    from loushang.harness.capabilities.prompt import (
        parse_prompt_template_args,
        substitute_prompt_template_args,
    )

    args = parse_prompt_template_args('component "first feature" second\tthird')

    assert args == ["component", "first feature", "second", "third"]
    assert substitute_prompt_template_args(
        "Name: $1\nRest: ${@:2}\nPair: ${@:2:2}\nAll: $ARGUMENTS\nAgain: $@",
        args,
    ) == (
        "Name: component\n"
        "Rest: first feature second third\n"
        "Pair: first feature second\n"
        "All: component first feature second third\n"
        "Again: component first feature second third"
    )


def test_prompt_template_args_do_not_recursively_substitute_argument_values() -> None:
    from loushang.harness.capabilities.prompt import substitute_prompt_template_args

    assert (
        substitute_prompt_template_args("$ARGUMENTS", ["$1", "$ARGUMENTS", "${@:2}"])
        == "$1 $ARGUMENTS ${@:2}"
    )


def test_preflight_user_input_substitutes_prompt_template_args_when_placeholders_exist() -> (
    None
):
    from pathlib import Path

    from loushang.harness.capabilities.prompt_preflight import preflight_user_input
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
    )

    resource_bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="review",
                source_path=Path("/tmp/project/prompts/review.md"),
                text="Review $1 with notes: ${@:2}",
            )
        ],
    )

    result = preflight_user_input(
        '/review PR-123 "focus on tests"', resource_bundle=resource_bundle
    )

    assert result.text == "Review PR-123 with notes: focus on tests"
    assert result.diagnostics == ()


def test_preflight_user_input_keeps_legacy_arg_append_for_templates_without_placeholders() -> (
    None
):
    from pathlib import Path

    from loushang.harness.capabilities.prompt_preflight import preflight_user_input
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
    )

    resource_bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="plan",
                source_path=Path("/tmp/project/prompts/plan.md"),
                text="Use a planning workflow before editing.",
            )
        ],
    )

    result = preflight_user_input(
        "/plan focus on retries", resource_bundle=resource_bundle
    )

    assert result.text == "Use a planning workflow before editing.\n\nfocus on retries"
    assert result.diagnostics == ()


def test_preflight_user_input_rejects_disabled_skills_but_allows_explicit_only_skills() -> (
    None
):
    from pathlib import Path

    from loushang.coding.prompt import assemble_prompt
    from loushang.harness.capabilities.prompt_preflight import preflight_user_input
    from loushang.harness.resources.types import (
        ResourceBundle,
        SkillDescriptor,
    )

    resource_bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        skills=[
            SkillDescriptor(
                name="debugging",
                source_path=Path("/tmp/project/skills/debugging/SKILL.md"),
                content="Debug body",
                description="Debug failures.",
                enabled=False,
            ),
            SkillDescriptor(
                name="deploy",
                source_path=Path("/tmp/project/skills/deploy/SKILL.md"),
                content="Deploy body",
                description="Deployment-only workflow.",
                disable_model_invocation=True,
            ),
        ],
    )

    disabled_result = preflight_user_input(
        "/skill:debugging inspect", resource_bundle=resource_bundle
    )
    explicit_result = preflight_user_input(
        "/skill:deploy ship", resource_bundle=resource_bundle
    )
    assembly = assemble_prompt(base_prompt="Base", resource_bundle=resource_bundle)

    assert disabled_result.text == "/skill:debugging inspect"
    assert [diagnostic.code for diagnostic in disabled_result.diagnostics] == [
        "unresolved_skill_reference"
    ]
    assert explicit_result.text == (
        '<skill name="deploy" location="/tmp/project/skills/deploy/SKILL.md">\n'
        "References are relative to /tmp/project/skills/deploy.\n\n"
        "Deploy body\n"
        "</skill>\n\n"
        "ship"
    )
    assert explicit_result.diagnostics == ()
    assert "Deployment-only workflow" not in assembly.system_prompt


def test_preflight_user_input_reports_unresolved_references_without_rewriting_text() -> (
    None
):
    from pathlib import Path

    from loushang.harness.capabilities.prompt_preflight import preflight_user_input
    from loushang.harness.resources.types import ResourceBundle

    result = preflight_user_input(
        "/missing-template keep original",
        resource_bundle=ResourceBundle(cwd=Path("/tmp/project")),
    )

    assert result.text == "/missing-template keep original"
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unresolved_prompt_reference"
    ]


def test_preflight_user_input_async_can_await_command_execution() -> None:
    from loushang.harness.capabilities.prompt_preflight import (
        preflight_user_input_async,
    )

    calls: list[tuple[str, str]] = []

    async def _execute_command(name: str, args: str):
        calls.append((name, args))
        await asyncio.sleep(0)
        return type("Execution", (), {"result": f"{name}:{args}"})()

    async def scenario() -> None:
        result = await preflight_user_input_async(
            "/deploy now", execute_command=_execute_command
        )
        assert result.consumed is True
        assert result.text == "/deploy now"
        assert calls == [("deploy", "now")]

    asyncio.run(scenario())


def test_preflight_user_input_async_consumes_if_command_handler_returns_none() -> None:
    from loushang.harness.capabilities.prompt_preflight import (
        preflight_user_input_async,
    )

    calls: list[tuple[str, str]] = []

    async def _execute_command(name: str, args: str):
        calls.append((name, args))
        return None

    async def scenario() -> None:
        result = await preflight_user_input_async(
            "/deploy now", execute_command=_execute_command
        )
        assert result.consumed is True
        assert result.text == "/deploy now"
        assert calls == [("deploy", "now")]

    asyncio.run(scenario())
