from __future__ import annotations

import json


def _tool_context_provider(*, cwd: str, model=None):
    from loushang.harness.tools.workspace import ToolContext

    def _provider(*, tool_call_id: str) -> ToolContext:
        kwargs = {"model": model} if model is not None else {}
        return ToolContext(tool_call_id=tool_call_id, cwd=cwd, **kwargs)

    return _provider


def test_registry_register_tool_accepts_raw_runtime_agent_tool() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    class RuntimeTool:
        name = "runtime_tool"
        label = "Runtime Tool"
        description = "runtime tool"
        parameters = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        prepare_arguments = None
        execution_mode = "sequential"

        async def execute(
            self,
            tool_call_id: str,
            params: dict[str, object],
            signal=None,
            on_update=None,
        ):
            del tool_call_id, params, signal, on_update
            return AgentToolResult(content=[], details={})

    registry = ToolRegistry()
    registry.register_tool(RuntimeTool())

    assert registry.get_definition("runtime_tool").name == "runtime_tool"
    assert registry.get_definition("runtime_tool").execution_mode == "sequential"


def test_registry_register_tool_accepts_decorated_tool() -> None:
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    @tool()
    async def greet(name: str) -> str:
        return f"hi {name}"

    registry = WorkspaceToolRegistry()
    registry.register_tool(greet)

    assert registry.get_definition("greet").name == "greet"


def test_tool_registry_exposes_builtin_tool_family() -> None:
    from loushang.coding.tool_pack import register_coding_builtin_tools
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    registry = WorkspaceToolRegistry()
    register_coding_builtin_tools(registry)

    assert [definition.name for definition in registry.list_definitions()] == [
        "bash",
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    ]
    assert [definition.name for definition in registry.list_enabled_definitions()] == [
        "bash",
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    ]
    assert registry.get_definition("bash").label == "Bash"


def test_registry_resolves_harness_contributions_without_mutating_state() -> None:
    from loushang.coding.tool_pack import register_coding_builtin_tools
    from loushang.harness.tools.contribution import ToolPackDefinition
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    registry = WorkspaceToolRegistry()
    register_coding_builtin_tools(registry)
    registry.disable_tool("bash")

    result = registry.resolve_contributions(
        packs=(
            ToolPackDefinition(
                name="read_only", tools=("read", "ls", "find", "grep", "bash")
            ),
        ),
        include_packs=("read_only",),
    )

    assert [definition.name for definition in result.definitions] == [
        "read",
        "ls",
        "find",
        "grep",
    ]
    assert result.diagnostics == ()
    assert [definition.name for definition in registry.list_enabled_definitions()] == [
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    ]


def test_workspace_factory_and_coding_pack_have_distinct_owners() -> None:
    from loushang.coding.tool_pack import (
        create_coding_tool_definitions,
        create_coding_tools,
    )
    from loushang.harness.tools.workspace.factory import (
        ALL_TOOL_NAMES,
        ToolName,
        create_all_tool_definitions,
        create_all_tools,
        create_core_workspace_tool_definitions,
        create_core_workspace_tools,
        create_read_only_tool_definitions,
        create_read_only_tools,
        create_tool,
        create_tool_definition,
    )

    assert ALL_TOOL_NAMES == ("read", "bash", "edit", "write", "grep", "find", "ls")
    assert ToolName is not None
    assert create_tool_definition("read").name == "read"
    assert create_tool("read").name == "read"
    assert [
        definition.name for definition in create_core_workspace_tool_definitions()
    ] == [
        "read",
        "bash",
        "edit",
        "write",
    ]
    assert [definition.name for definition in create_coding_tool_definitions()] == [
        "read",
        "bash",
        "edit",
        "write",
    ]
    assert [definition.name for definition in create_read_only_tool_definitions()] == [
        "read",
        "grep",
        "find",
        "ls",
    ]
    assert list(create_all_tool_definitions()) == [
        "read",
        "bash",
        "edit",
        "write",
        "grep",
        "find",
        "ls",
    ]
    assert [tool.name for tool in create_core_workspace_tools()] == [
        "read",
        "bash",
        "edit",
        "write",
    ]
    assert [tool.name for tool in create_coding_tools()] == [
        "read",
        "bash",
        "edit",
        "write",
    ]
    assert [tool.name for tool in create_read_only_tools()] == [
        "read",
        "grep",
        "find",
        "ls",
    ]
    assert list(create_all_tools()) == [
        "read",
        "bash",
        "edit",
        "write",
        "grep",
        "find",
        "ls",
    ]


def test_workspace_factory_binds_cwd_without_pi_aliases(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace.factory import create_tool

    (tmp_path / "note.txt").write_text("from workspace factory", encoding="utf-8")

    runtime_tool = create_tool("read", cwd=str(tmp_path))
    result = asyncio.run(runtime_tool.execute("call-read-camel", {"path": "note.txt"}))

    assert result.content[0].text == "from workspace factory"


def test_tool_factory_create_tool_binds_cwd_context(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_tool

    (tmp_path / "note.txt").write_text("from cwd-bound tool", encoding="utf-8")

    runtime_tool = create_tool("read", cwd=str(tmp_path))
    result = asyncio.run(runtime_tool.execute("call-read", {"path": "note.txt"}))

    assert result.content[0].text == "from cwd-bound tool"


def test_tool_factory_options_forward_to_file_tools(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        async def exists(self, path):
            return True

        async def is_file(self, path):
            return True

        async def read_bytes(self, path):
            return b"from virtual operations"

    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "read", options=ToolsOptions(read_operations=VirtualOperations())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-read", {"path": "remote.txt"}))

    assert result.content[0].text == "from virtual operations"


def test_tool_factory_forwards_external_tool_resolver_to_find(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nprintf 'factory.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    class Resolver:
        def __init__(self) -> None:
            self.names: list[str] = []

        def resolve_tool(self, name: str) -> str | None:
            self.names.append(name)
            return str(fake_fd) if name == "fd" else None

    resolver = Resolver()
    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "find", options=ToolsOptions(external_tool_resolver=resolver)
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-factory-resolver", {"pattern": "*.py", "path": "."}
        )
    )

    assert resolver.names == ["fd"]
    assert result.content[0].text == "factory.py"


def test_tool_factory_forwards_external_tool_downloader_to_find_when_enabled(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nprintf 'downloaded.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def download_tool(self, name: str) -> str | None:
            self.calls.append(name)
            return str(fake_fd) if name == "fd" else None

    downloader = Downloader()
    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "find",
            options=ToolsOptions(
                external_tool_resolver=MissingResolver(),
                external_tool_downloader=downloader,
                allow_external_tool_downloads=True,
            ),
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-downloader", {"pattern": "*.py", "path": "."})
    )

    assert downloader.calls == ["fd"]
    assert result.content[0].text == "downloaded.py"


def test_tool_factory_external_tool_policy_auto_downloads_without_legacy_flag(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nprintf 'policy.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> str | None:
            self.calls.append(name)
            return str(fake_fd) if name == "fd" else None

    downloader = Downloader()
    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "find",
            options=ToolsOptions(
                external_tool_policy="auto",
                external_tool_resolver=MissingResolver(),
                external_tool_downloader=downloader,
            ),
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-policy-auto", {"pattern": "*.py", "path": "."})
    )

    assert downloader.calls == ["fd"]
    assert result.content[0].text == "policy.py"


def test_tool_factory_external_tool_policy_never_skips_resolver_and_uses_fallback(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "local.py").write_text("pass", encoding="utf-8")

    class Resolver:
        def __init__(self) -> None:
            self.names: list[str] = []

        def resolve_tool(self, name: str) -> str:
            self.names.append(name)
            return "/should/not/run"

    resolver = Resolver()
    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "find",
            options=ToolsOptions(
                external_tool_policy="never",
                external_tool_resolver=resolver,
            ),
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-policy-never", {"pattern": "*.py", "path": "."})
    )

    assert resolver.names == []
    assert result.content[0].text == "local.py"


def test_tool_factory_external_tool_policy_required_errors_when_unavailable(
    tmp_path,
) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class MissingDownloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> None:
            self.calls.append(name)
            return None

    downloader = MissingDownloader()
    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "grep",
            options=ToolsOptions(
                external_tool_policy="required",
                external_tool_resolver=MissingResolver(),
                external_tool_downloader=downloader,
            ),
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        RuntimeError, match="rg external tool is required but unavailable"
    ):
        asyncio.run(
            runtime_tool.execute(
                "call-grep-policy-required", {"pattern": "needle", "path": "."}
            )
        )
    assert downloader.calls == ["rg"]


def test_tool_factory_download_failure_surfaces_as_stable_unavailable_error(
    tmp_path,
) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class FailingDownloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> str:
            self.calls.append(name)
            raise RuntimeError("network unavailable")

    downloader = FailingDownloader()
    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "grep",
            options=ToolsOptions(
                external_tool_resolver=MissingResolver(),
                external_tool_downloader=downloader,
                allow_external_tool_downloads=True,
                require_external_tools=True,
            ),
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        RuntimeError, match="rg external tool is required but unavailable"
    ):
        asyncio.run(
            runtime_tool.execute(
                "call-grep-downloader-failure", {"pattern": "needle", "path": "."}
            )
        )
    assert downloader.calls == ["rg"]


def test_tool_factory_uses_builtin_external_tool_downloader_when_enabled(
    tmp_path, monkeypatch
) -> None:
    import asyncio

    import loushang.coding.tool_pack as coding_factory
    import loushang.harness.tools.workspace.factory as workspace_factory
    from loushang.harness.tools.workspace import ToolsOptions
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nprintf 'builtin.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    class BuiltinDownloader:
        def __init__(self) -> None:
            created.append(self)

        def download_tool(self, name: str) -> str | None:
            calls.append(name)
            return str(fake_fd) if name == "fd" else None

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    created: list[BuiltinDownloader] = []
    calls: list[str] = []
    monkeypatch.setattr(
        workspace_factory,
        "GitHubReleaseExternalToolDownloader",
        BuiltinDownloader,
    )
    runtime_tool = wrap_tool_definition(
        coding_factory.create_coding_tool_definition(
            "find",
            options=ToolsOptions(
                external_tool_resolver=MissingResolver(),
                allow_external_tool_downloads=True,
            ),
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-builtin-downloader", {"pattern": "*.py", "path": "."}
        )
    )

    assert len(created) == 1
    assert calls == ["fd"]
    assert result.content[0].text == "builtin.py"


def test_tool_factory_does_not_download_external_tools_by_default(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "local.py").write_text("pass", encoding="utf-8")

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> str:
            self.calls.append(name)
            return "/downloaded/fd"

    downloader = Downloader()
    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "find",
            options=ToolsOptions(
                external_tool_resolver=MissingResolver(),
                external_tool_downloader=downloader,
            ),
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-no-download", {"pattern": "*.py", "path": "."})
    )

    assert downloader.calls == []
    assert result.content[0].text == "local.py"


def test_register_builtin_tools_reuses_factory_but_keeps_legacy_order() -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    registry = ToolRegistry()
    register_builtin_tools(registry)

    assert [definition.name for definition in registry.list_definitions()] == [
        "bash",
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    ]


def test_register_builtin_tools_uses_harness_pack_resolver(monkeypatch) -> None:
    import loushang.coding.tool_pack as builtins
    import loushang.harness.tools.workspace.registry as registry_module
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    calls: list[dict[str, object]] = []
    real_resolver = registry_module.resolve_tool_contributions

    def spy_resolver(contributions, **kwargs):
        calls.append(
            {
                "contributions": tuple(contributions),
                "packs": tuple(kwargs.get("packs", ())),
                "include_packs": tuple(kwargs.get("include_packs", ())),
            }
        )
        return real_resolver(calls[-1]["contributions"], **kwargs)

    monkeypatch.setattr(registry_module, "resolve_tool_contributions", spy_resolver)

    registry = ToolRegistry()
    builtins.register_coding_builtin_tools(registry)

    assert len(calls) == 1
    assert [
        contribution.definition.name for contribution in calls[0]["contributions"]
    ] == [
        "bash",
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    ]
    assert [pack.name for pack in calls[0]["packs"]] == ["coding.builtin"]
    assert calls[0]["include_packs"] == ("coding.builtin",)
    assert [definition.name for definition in registry.list_definitions()] == [
        "bash",
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    ]


def test_register_builtin_tools_forwards_external_tool_policy_to_read_only_tools(
    tmp_path,
) -> None:
    import asyncio

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nprintf 'registered.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> str | None:
            self.calls.append(name)
            return str(fake_fd) if name == "fd" else None

    downloader = Downloader()
    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        external_tool_policy="auto",
        external_tool_resolver=MissingResolver(),
        external_tool_downloader=downloader,
    )
    runtime_tool = registry.materialize_definitions(
        [registry.get_definition("find")],
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )[0]

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-registered-policy", {"pattern": "*.py", "path": "."}
        )
    )

    assert downloader.calls == ["fd"]
    assert result.content[0].text == "registered.py"


def test_bash_tool_uses_policy_and_exec(tmp_path) -> None:
    import asyncio

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )
    from loushang.harness.workspace.exec import ExecResult

    class RecordingPolicyEngine:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def evaluate(self, subject):
            self.calls.append((subject.tool_name, subject))
            return PolicyDecision.allow()

    class RecordingExecService:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request):
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="hi", stderr="")

    async def scenario() -> None:
        policy_engine = RecordingPolicyEngine()
        exec_service = RecordingExecService()

        registry = ToolRegistry()
        register_builtin_tools(
            registry, policy_engine=policy_engine, exec_service=exec_service
        )
        result = await registry.materialize_tool("bash").execute(
            "call-1",
            {"command": ["/bin/sh", "-lc", "printf hi"], "cwd": str(tmp_path)},
        )

        assert result.content[0].text == "hi"
        assert policy_engine.calls[0][0] == "bash"
        assert exec_service.requests[0].command == ("/bin/sh", "-lc", "printf hi")

    asyncio.run(scenario())


def test_bash_tool_invokes_canonical_policy_once(tmp_path) -> None:
    import asyncio

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    class CountingPolicyEngine:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, subject):
            del subject
            self.calls += 1
            return PolicyDecision.allow()

    async def scenario() -> None:
        policy_engine = CountingPolicyEngine()
        registry = ToolRegistry()
        register_builtin_tools(registry, policy_engine=policy_engine)
        bash = registry.materialize_tool("bash")

        await bash.execute(
            "call-bash-count", {"command": "printf ok", "cwd": str(tmp_path)}
        )

        assert policy_engine.calls == 1

    asyncio.run(scenario())


def test_bash_tool_accepts_pi_style_shell_command_string(tmp_path) -> None:
    import asyncio

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )
    from loushang.harness.workspace.exec import ExecResult

    class RecordingPolicyEngine:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def evaluate(self, subject):
            self.requests.append(subject)
            return PolicyDecision.allow()

    class RecordingExecService:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request, **kwargs):
            del kwargs
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="shell-ok", stderr="")

    async def scenario() -> None:
        policy_engine = RecordingPolicyEngine()
        exec_service = RecordingExecService()
        registry = ToolRegistry()
        register_builtin_tools(
            registry, policy_engine=policy_engine, exec_service=exec_service
        )

        result = await registry.materialize_tool("bash").execute(
            "call-shell",
            {"command": "printf shell-ok", "cwd": str(tmp_path), "timeout": 3},
        )

        assert result.content[0].text == "shell-ok"
        assert exec_service.requests[0].command == (
            "/bin/bash",
            "-lc",
            "printf shell-ok",
        )
        assert exec_service.requests[0].timeout_seconds == 3
        assert policy_engine.requests[0].command.command == (
            "/bin/bash",
            "-lc",
            "printf shell-ok",
        )

    asyncio.run(scenario())


def test_bash_tool_applies_prefix_shell_path_and_spawn_hook(tmp_path) -> None:
    import asyncio
    from dataclasses import replace

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import (
        BashSpawnContext,
        create_bash_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class RecordingPolicyEngine:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def evaluate(self, subject):
            self.requests.append(subject)
            return PolicyDecision.allow()

    class RecordingExecService:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request, **kwargs):
            del kwargs
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="ok\n")

    alt_cwd = tmp_path / "alt"
    alt_cwd.mkdir()

    def spawn_hook(context: BashSpawnContext) -> BashSpawnContext:
        return replace(
            context,
            command=f"{context.command}\nprintf hooked",
            cwd=str(alt_cwd),
            env=(*context.env, ("HOOKED", "1")),
        )

    async def scenario() -> None:
        policy_engine = RecordingPolicyEngine()
        exec_service = RecordingExecService()
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=policy_engine,
                exec_service=exec_service,
                command_prefix="set -e",
                shell_path="/custom/bash",
                spawn_hook=spawn_hook,
            )
        )

        result = await tool.execute(
            "call-bash-config", {"command": "printf ok", "cwd": str(tmp_path)}
        )

        assert result.content[0].text == "ok\n"
        assert exec_service.requests[0].command == (
            "/custom/bash",
            "-lc",
            "set -e\nprintf ok\nprintf hooked",
        )
        assert exec_service.requests[0].cwd == str(alt_cwd)
        assert ("HOOKED", "1") in exec_service.requests[0].env
        assert (
            policy_engine.requests[0].command.command
            == exec_service.requests[0].command
        )

    asyncio.run(scenario())


def test_bash_tool_can_execute_through_custom_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class FailingExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("custom operations should bypass exec_service")

    class RecordingOperations:
        def __init__(self) -> None:
            self.calls: list[tuple[object, object | None]] = []

        async def execute(self, request, *, signal=None, on_update=None):
            self.calls.append((request, signal))
            if on_update is not None:
                await on_update(
                    type("Chunk", (), {"stream": "stdout", "text": "partial\n"})()
                )
            return ExecResult(exit_code=0, stdout="remote\n")

    async def scenario() -> None:
        operations = RecordingOperations()
        updates: list[str] = []
        signal = object()
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=AllowingPolicyEngine(),
                exec_service=FailingExecService(),
                operations=operations,
            )
        )

        result = await tool.execute(
            "call-bash-operations",
            {"command": "printf remote", "cwd": str(tmp_path)},
            signal=signal,
            on_update=lambda partial: updates.append(
                partial.content[0].text if partial.content else ""
            ),
        )

        assert result.content[0].text == "remote\n"
        assert operations.calls[0][0].command == ("/bin/bash", "-lc", "printf remote")
        assert operations.calls[0][1] is signal
        assert updates == ["", "partial\n"]

    asyncio.run(scenario())


def test_bash_tool_requests_rolling_capture_by_default(tmp_path) -> None:
    import asyncio

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class RecordingExecService:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request, **kwargs):
            del kwargs
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="ok\n")

    async def scenario() -> None:
        exec_service = RecordingExecService()
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=AllowingPolicyEngine(),
                exec_service=exec_service,
            )
        )

        await tool.execute(
            "call-bash-rolling", {"command": "printf ok", "cwd": str(tmp_path)}
        )

        assert exec_service.requests[0].capture_full_output is False
        assert exec_service.requests[0].rolling_max_bytes == 100 * 1024

    asyncio.run(scenario())


def test_bash_tool_accepts_pi_style_request_aliases(tmp_path) -> None:
    import asyncio

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class RecordingExecService:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request, **kwargs):
            del kwargs
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="ok\n")

    async def scenario() -> None:
        exec_service = RecordingExecService()
        tool_definition = create_bash_tool_definition(
            policy_engine=AllowingPolicyEngine(),
            exec_service=exec_service,
        )
        tool = wrap_tool_definition(tool_definition)

        await tool.execute(
            "call-bash-aliases",
            {
                "command": "printf ok",
                "cwd": str(tmp_path),
                "timeoutSeconds": 3,
                "artifactDir": str(tmp_path),
                "captureFullOutput": True,
                "rollingMaxBytes": 4096,
            },
        )

        request = exec_service.requests[0]
        assert request.timeout_seconds == 3
        assert request.artifact_dir == str(tmp_path)
        assert request.capture_full_output is True
        assert request.rolling_max_bytes == 4096
        assert "timeoutSeconds" in tool_definition.parameters["properties"]
        assert "artifactDir" in tool_definition.parameters["properties"]
        assert "captureFullOutput" in tool_definition.parameters["properties"]
        assert "rollingMaxBytes" in tool_definition.parameters["properties"]

    asyncio.run(scenario())


def test_bash_tool_rejects_conflicting_alias_parameters(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class RecordingExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            return ExecResult(exit_code=0, stdout="ok\n")

    async def scenario(params, message: str) -> None:
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=AllowingPolicyEngine(),
                exec_service=RecordingExecService(),
            )
        )
        with pytest.raises(ValueError, match=message):
            await tool.execute("call-bash-conflicting-aliases", params)

    asyncio.run(
        scenario(
            {"command": "printf ok", "timeout_seconds": 1, "timeoutSeconds": 2},
            "conflicting tool arguments: timeout_seconds and timeoutSeconds",
        )
    )
    asyncio.run(
        scenario(
            {
                "command": "printf ok",
                "artifact_dir": str(tmp_path),
                "artifactDir": str(tmp_path / "other"),
            },
            "conflicting tool arguments: artifact_dir and artifactDir",
        )
    )
    asyncio.run(
        scenario(
            {
                "command": "printf ok",
                "capture_full_output": True,
                "captureFullOutput": False,
            },
            "conflicting tool arguments: capture_full_output and captureFullOutput",
        )
    )
    asyncio.run(
        scenario(
            {
                "command": "printf ok",
                "rolling_max_bytes": 1024,
                "rollingMaxBytes": 2048,
            },
            "conflicting tool arguments: rolling_max_bytes and rollingMaxBytes",
        )
    )


def test_bash_tool_rejects_runtime_values_that_do_not_match_schema() -> None:
    import asyncio

    import pytest

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class RecordingExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            return ExecResult(exit_code=0, stdout="ok\n")

    async def scenario(params, message: str) -> None:
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=AllowingPolicyEngine(),
                exec_service=RecordingExecService(),
            )
        )
        with pytest.raises(TypeError, match=message):
            await tool.execute("call-bash-invalid-runtime-value", params)

    asyncio.run(
        scenario(
            {"command": "printf ok", "timeoutSeconds": "3"},
            "timeout_seconds must be a number",
        )
    )
    asyncio.run(
        scenario(
            {"command": "printf ok", "artifactDir": 123},
            "artifact_dir must be a string",
        )
    )
    asyncio.run(
        scenario(
            {"command": "printf ok", "captureFullOutput": "true"},
            "capture_full_output must be a boolean",
        )
    )
    asyncio.run(
        scenario(
            {"command": "printf ok", "env": [["A", 1]]},
            "env must contain 2-item string pairs",
        )
    )


def test_bash_tool_truncates_large_output_with_shared_tail_policy(tmp_path) -> None:
    import asyncio

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class LargeOutputExecService:
        async def execute(self, request):
            del request
            stdout = "".join(f"line-{index:04d}\n" for index in range(3000))
            stderr = "".join(f"err-{index:04d}\n" for index in range(3000))
            return ExecResult(exit_code=0, stdout=stdout, stderr=stderr)

    async def scenario() -> None:
        registry = ToolRegistry()
        register_builtin_tools(
            registry,
            policy_engine=AllowingPolicyEngine(),
            exec_service=LargeOutputExecService(),
        )

        result = await registry.materialize_tool("bash").execute(
            "call-truncate",
            {"command": ["/bin/sh", "-lc", "printf large"], "cwd": str(tmp_path)},
        )

        assert result.details["truncated"] is True
        assert result.details["truncated_by"] == "lines"
        assert result.details["stdout_total_lines"] == 3000
        assert result.details["stdout_output_lines"] == 2000
        assert result.details["stdout_max_lines"] == 2000
        assert "line-2999\n" in result.content[0].text
        assert result.content[0].text.endswith("err-2999\n")
        assert result.details["stderr"].startswith("err-1000\n")
        assert result.details["stderr"].endswith("err-2999\n")
        assert result.details["stderr_truncated"] is True
        assert result.details["stderr_truncated_by"] == "lines"
        assert result.details["stderr_total_lines"] == 3000
        assert result.details["stderr_output_lines"] == 2000

    asyncio.run(scenario())


def test_bash_tool_preserves_interleaved_stdout_and_stderr_output(tmp_path) -> None:
    import asyncio

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class InterleavedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            return ExecResult(
                exit_code=0,
                stdout="out1\nout2\n",
                stderr="err1\n",
                output_chunks=(
                    ExecOutputChunk(stream="stdout", text="out1\n"),
                    ExecOutputChunk(stream="stderr", text="err1\n"),
                    ExecOutputChunk(stream="stdout", text="out2\n"),
                ),
            )

    async def scenario() -> None:
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=AllowingPolicyEngine(),
                exec_service=InterleavedExecService(),
            )
        )

        result = await tool.execute(
            "call-bash-interleaved", {"command": "printf mixed", "cwd": str(tmp_path)}
        )

        assert result.content[0].text == "out1\nerr1\nout2\n"
        assert result.details["stderr"] == "err1\n"

    asyncio.run(scenario())


def test_bash_tool_error_message_preserves_interleaved_stdout_and_stderr(
    tmp_path,
) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class InterleavedFailingExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            return ExecResult(
                exit_code=7,
                stdout="out1\nout2\n",
                stderr="err1\n",
                output_chunks=(
                    ExecOutputChunk(stream="stdout", text="out1\n"),
                    ExecOutputChunk(stream="stderr", text="err1\n"),
                    ExecOutputChunk(stream="stdout", text="out2\n"),
                ),
            )

    async def scenario() -> None:
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=AllowingPolicyEngine(),
                exec_service=InterleavedFailingExecService(),
            )
        )

        with pytest.raises(RuntimeError) as exc:
            await tool.execute(
                "call-bash-interleaved-error",
                {"command": "printf mixed", "cwd": str(tmp_path)},
            )

        assert str(exc.value) == "out1\nerr1\nout2\n\nCommand exited with code 7"

    asyncio.run(scenario())


def test_bash_tool_rolling_artifact_details_count_full_output(tmp_path) -> None:
    import asyncio
    from pathlib import Path

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    full_output = "".join(f"line-{index:04d}\n" for index in range(3000))

    async def scenario() -> None:
        tool = wrap_tool_definition(
            create_bash_tool_definition(policy_engine=AllowingPolicyEngine())
        )

        result = await tool.execute(
            "call-bash-artifact-contract",
            {
                "command": (
                    "i=0; while [ $i -lt 3000 ]; do "
                    "printf 'line-%04d\\n' \"$i\"; i=$((i+1)); done"
                ),
                "cwd": str(tmp_path),
                "artifactDir": str(tmp_path),
                "rollingMaxBytes": 2048,
            },
        )

        assert (
            result.details["full_output_path"] == result.details["stdout_artifact_path"]
        )
        assert "fullOutputPath" not in result.details
        assert result.details["stdout_artifact_path"] is not None
        assert (
            Path(result.details["stdout_artifact_path"]).read_text(encoding="utf-8")
            == full_output
        )
        assert result.details["stdout_total_lines"] == 3000
        assert result.details["stdout_total_bytes"] == len(full_output.encode("utf-8"))
        assert (
            result.details["stdout_output_lines"] < result.details["stdout_total_lines"]
        )
        assert result.details["truncated"] is True
        assert result.details["truncation"]["totalLines"] == 3000

    asyncio.run(scenario())


def test_bash_tool_returns_no_output_placeholder(tmp_path) -> None:
    import asyncio

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class EmptyExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            return ExecResult(exit_code=0)

    async def scenario() -> None:
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=AllowingPolicyEngine(),
                exec_service=EmptyExecService(),
            )
        )

        result = await tool.execute(
            "call-bash-empty", {"command": "true", "cwd": str(tmp_path)}
        )

        assert result.content[0].text == "(no output)"
        assert result.details["exit_code"] == 0

    asyncio.run(scenario())


def test_bash_tool_raises_for_nonzero_exit_code_with_buffered_output(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class FailingExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            return ExecResult(exit_code=2, stdout="out\n", stderr="err\n")

    async def scenario() -> None:
        tool = wrap_tool_definition(
            create_bash_tool_definition(
                policy_engine=AllowingPolicyEngine(),
                exec_service=FailingExecService(),
            )
        )

        with pytest.raises(RuntimeError) as exc_info:
            await tool.execute(
                "call-bash-fail", {"command": "exit 2", "cwd": str(tmp_path)}
            )

        message = str(exc_info.value)
        assert "out" in message
        assert "err" in message
        assert "Command exited with code 2" in message

    asyncio.run(scenario())


def test_bash_tool_raises_for_invalid_command_and_env_shapes(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    class RecordingPolicyEngine:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, subject):
            self.calls += 1
            raise AssertionError("policy should not run for invalid params")

    class RecordingExecService:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, request):
            self.calls += 1
            raise AssertionError("exec should not run for invalid params")

    async def scenario() -> None:
        policy_engine = RecordingPolicyEngine()
        exec_service = RecordingExecService()
        registry = ToolRegistry()
        register_builtin_tools(
            registry, policy_engine=policy_engine, exec_service=exec_service
        )
        bash_tool = registry.materialize_tool("bash")

        with pytest.raises(TypeError):
            await bash_tool.execute(
                "call-empty",
                {"command": [], "cwd": str(tmp_path)},
            )
        with pytest.raises(TypeError):
            await bash_tool.execute(
                "call-env",
                {
                    "command": ["/bin/sh", "-lc", "printf hi"],
                    "cwd": str(tmp_path),
                    "env": [["A", "B", "C"]],
                },
            )
        assert policy_engine.calls == 0
        assert exec_service.calls == 0

    asyncio.run(scenario())


def test_bash_tool_policy_decisions_do_not_record_runtime_diagnostics(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    class SequencedPolicyEngine:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, subject):
            del subject
            self.calls += 1
            if self.calls == 1:
                return PolicyDecision.deny("blocked by policy")
            return PolicyDecision.ask("approval required")

    class RecordingExecService:
        async def execute(self, request):
            raise AssertionError("exec should not run when policy blocks execution")

    async def scenario() -> None:
        diagnostics_service = DiagnosticsService()
        registry = ToolRegistry()
        register_builtin_tools(
            registry,
            policy_engine=SequencedPolicyEngine(),
            exec_service=RecordingExecService(),
            diagnostics_service=diagnostics_service,
        )
        bash_tool = registry.materialize_tool("bash")

        with pytest.raises(PermissionError) as deny_exc:
            await bash_tool.execute(
                "call-deny",
                {"command": ["/bin/sh", "-lc", "printf blocked"], "cwd": str(tmp_path)},
            )
        with pytest.raises(PermissionError) as ask_exc:
            await bash_tool.execute(
                "call-ask",
                {"command": ["/bin/sh", "-lc", "printf ask"], "cwd": str(tmp_path)},
            )

        assert str(deny_exc.value) == "blocked by policy"
        assert str(ask_exc.value) == "approval required"
        assert diagnostics_service.get_last_diagnostics() == []

    asyncio.run(scenario())


def test_bash_tool_exec_timeout_does_not_record_runtime_diagnostics(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class TimeoutExecService:
        async def execute(self, request):
            del request
            return ExecResult(exit_code=-1, stdout="out", stderr="err", timed_out=True)

    async def scenario() -> None:
        diagnostics_service = DiagnosticsService()
        registry = ToolRegistry()
        register_builtin_tools(
            registry,
            policy_engine=AllowingPolicyEngine(),
            exec_service=TimeoutExecService(),
            diagnostics_service=diagnostics_service,
        )

        with pytest.raises(TimeoutError) as exc:
            await registry.materialize_tool("bash").execute(
                "call-timeout",
                {"command": ["/bin/sh", "-lc", "printf timeout"], "cwd": str(tmp_path)},
            )

        assert "timed out" in str(exc.value)
        assert diagnostics_service.get_last_diagnostics() == []

    asyncio.run(scenario())


def test_bash_tool_timeout_error_includes_buffered_output(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.coding.tool_pack import register_coding_builtin_tools
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
    from loushang.harness.workspace.exec import ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision(disposition="allow")

    class TimeoutExecService:
        async def execute(self, request):
            del request
            return ExecResult(
                exit_code=-1,
                stdout="partial stdout\n",
                stderr="partial stderr\n",
                timed_out=True,
            )

    async def scenario() -> None:
        registry = WorkspaceToolRegistry()
        diagnostics_service = DiagnosticsService()
        register_coding_builtin_tools(
            registry,
            policy_engine=AllowingPolicyEngine(),
            exec_service=TimeoutExecService(),
            diagnostics_service=diagnostics_service,
        )

        with pytest.raises(TimeoutError) as exc_info:
            await registry.materialize_tool("bash").execute(
                "call-timeout-output",
                {
                    "command": ["/bin/sh", "-lc", "printf partial; sleep 1"],
                    "cwd": str(tmp_path),
                },
            )

        message = str(exc_info.value)
        assert "partial stdout" in message
        assert "partial stderr" in message
        assert "Command timed out during execution." in message
        assert diagnostics_service.get_last_diagnostics() == []

    asyncio.run(scenario())


def test_bash_tool_exec_exception_does_not_record_runtime_diagnostics_and_reraises(
    tmp_path,
) -> None:
    import asyncio

    from loushang.coding.tool_pack import register_coding_builtin_tools
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class FailingExecService:
        async def execute(self, request):
            del request
            raise RuntimeError("subprocess spawn failed")

    async def scenario() -> None:
        diagnostics_service = DiagnosticsService()
        registry = WorkspaceToolRegistry()
        register_coding_builtin_tools(
            registry,
            policy_engine=AllowingPolicyEngine(),
            exec_service=FailingExecService(),
            diagnostics_service=diagnostics_service,
        )

        try:
            await registry.materialize_tool("bash").execute(
                "call-exec-error",
                {"command": ["/bin/sh", "-lc", "printf fail"], "cwd": str(tmp_path)},
            )
        except RuntimeError as exc:
            assert str(exc) == "subprocess spawn failed"
        else:
            raise AssertionError("expected exec failure to be re-raised")

        assert diagnostics_service.get_last_diagnostics() == []

    asyncio.run(scenario())


def test_read_uses_shared_path_resolution(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    nested = tmp_path / "nested"
    nested.mkdir()
    path = nested / "notes.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    definition = create_read_tool_definition()
    runtime_tool = wrap_tool_definition(
        definition,
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-read", {"path": "nested/../nested/notes.txt"})
    )

    assert result.content[0].text == "alpha\nbeta\ngamma\n"
    assert result.details["path"] == str(path)
    assert result.details["start_line"] == 1
    assert result.details["end_line"] == 3
    assert result.details["truncated"] is False
    assert result.details["total_lines"] == 3
    assert result.details["total_bytes"] == len(result.content[0].text.encode("utf-8"))
    assert result.details["output_lines"] == 3
    assert result.details["output_bytes"] == len(result.content[0].text.encode("utf-8"))
    assert result.details["max_lines"] == 2000
    assert result.details["max_bytes"] == 50 * 1024


def test_read_preserves_offset_and_limit_contract(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "notes.txt"
    path.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-read", {"path": "notes.txt", "offset": 2, "limit": 2}
        )
    )

    assert result.content[0].text.startswith("beta\ngamma\n")
    assert result.details["start_line"] == 2
    assert result.details["end_line"] == 3
    assert result.details["truncated"] is True


def test_read_accepts_integral_numeric_offset_and_limit(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-read-float-window", {"path": "notes.txt", "offset": 2.0, "limit": 1.0}
        )
    )

    assert (
        result.content[0].text
        == "beta\n\n[1 more lines in file. Use offset=3 to continue.]"
    )


def test_read_reports_remaining_lines_when_user_limit_stops_before_eof(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "notes.txt"
    path.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-read", {"path": "notes.txt", "offset": 2, "limit": 2}
        )
    )

    assert (
        result.content[0].text
        == "beta\ngamma\n\n[1 more lines in file. Use offset=4 to continue.]"
    )
    assert result.details["start_line"] == 2
    assert result.details["end_line"] == 3
    assert result.details["truncated"] is True


def test_read_reports_first_line_too_large_without_partial_payload(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "long.txt"
    path.write_text(("x" * (60 * 1024)) + "\nsecond\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-read-long-line", {"path": "long.txt"})
    )

    assert result.content[0].text.startswith("[Line 1 is ")
    assert "exceeds 50.0KB limit" in result.content[0].text
    assert "Use bash: sed -n '1p' long.txt | head -c 51200" in result.content[0].text
    assert "x" * 100 not in result.content[0].text
    assert result.details["truncated"] is True
    assert result.details["truncated_by"] == "bytes"
    assert result.details["first_line_exceeds_limit"] is True


def test_read_aligns_line_metadata_after_shared_truncation(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "notes.txt"
    path.write_text(
        "".join(f"line {index:04d}\n" for index in range(2500)), encoding="utf-8"
    )

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-read-large", {"path": "notes.txt", "offset": 2, "limit": 2100}
        )
    )

    visible_text = result.content[0].text.split("\n[Showing lines ", 1)[0]
    visible_lines = visible_text.splitlines()
    assert len(visible_lines) == 2000
    assert result.details["start_line"] == 2
    assert result.details["end_line"] == 2001
    assert (
        result.details["end_line"]
        == result.details["start_line"] + len(visible_lines) - 1
    )
    assert result.details["truncated"] is True
    assert result.details["truncated_by"] == "lines"
    assert result.details["total_lines"] == 2100
    assert result.details["output_lines"] == 2000
    assert result.details["max_lines"] == 2000
    assert result.details["truncation"]["truncatedBy"] == "lines"
    assert result.details["truncation"]["totalLines"] == 2100
    assert result.details["truncation"]["outputLines"] == 2000
    assert result.details["truncation"]["maxLines"] == 2000


def test_read_prepare_arguments_accepts_legacy_file_path_alias(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "notes.txt").write_text("legacy path", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    prepared = runtime_tool.prepare_arguments({"file_path": "notes.txt"})
    result = asyncio.run(runtime_tool.execute("call-read-legacy-path", prepared))

    assert prepared == {"path": "notes.txt"}
    assert result.content[0].text == "legacy path"


def test_file_tool_prepare_arguments_reject_conflicting_file_path_aliases(
    tmp_path,
) -> None:
    import pytest

    from loushang.harness.tools.workspace import (
        create_find_tool_definition,
        create_ls_tool_definition,
        create_read_tool_definition,
        create_write_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    for definition in (
        create_read_tool_definition(),
        create_ls_tool_definition(),
        create_find_tool_definition(),
        create_write_tool_definition(),
    ):
        runtime_tool = wrap_tool_definition(
            definition,
            context_provider=_tool_context_provider(cwd=str(tmp_path)),
        )
        with pytest.raises(
            ValueError, match="conflicting tool arguments: path and file_path"
        ):
            runtime_tool.prepare_arguments({"path": "main.py", "file_path": "other.py"})


def test_read_rejects_binary_file_payloads(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    binary_path = tmp_path / "payload.bin"
    binary_path.write_bytes(b"alpha\x00beta")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(ValueError, match="binary"):
        asyncio.run(runtime_tool.execute("call-binary-read", {"path": "payload.bin"}))


def test_read_returns_image_content_for_supported_image(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
    )
    (tmp_path / "pixel.png").write_bytes(png_payload)

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-image-read", {"path": "pixel.png"}))

    assert result.content[0].type == "text"
    assert "Read image file [image/png]" in result.content[0].text
    assert result.content[1].type == "image"
    assert result.content[1].mime_type == "image/png"
    assert result.details["mime_type"] == "image/png"
    assert result.details["is_image"] is True


def test_read_omits_oversized_image_when_resize_is_unavailable(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + (3001).to_bytes(4, "big")
        + (10).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    (tmp_path / "wide.png").write_bytes(png_payload)

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-image-read", {"path": "wide.png"}))

    assert len(result.content) == 1
    assert "Read image file [image/png]" in result.content[0].text
    assert "Image omitted" in result.content[0].text
    assert result.details["is_image"] is True
    assert result.details["image_omitted"] is True
    assert result.details["width"] == 3001
    assert result.details["height"] == 10


def test_read_reports_unavailable_resize_backend_for_oversized_image(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import (
        ReadToolOptions,
        create_read_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + (3001).to_bytes(4, "big")
        + (10).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    (tmp_path / "wide.png").write_bytes(png_payload)

    class UnavailableResizer:
        def is_available(self) -> bool:
            return False

        async def resize_image(
            self, payload: bytes, *, mime_type: str, dimensions: tuple[int, int] | None
        ):
            raise AssertionError("unavailable resizer should not be called")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(
            options=ReadToolOptions(image_resizer=UnavailableResizer())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-image-read", {"path": "wide.png"}))

    assert len(result.content) == 1
    assert "auto-resize backend is unavailable" in result.content[0].text
    assert result.details["image_omitted"] is True
    assert result.details["image_resized"] is False
    assert result.details["resize_unavailable"] is True
    assert result.details["resize_reason"] == "unavailable"


def test_read_resizes_oversized_image_when_resizer_is_available(tmp_path) -> None:
    import asyncio
    import base64

    from loushang.harness.tools.workspace import (
        ReadImageResizeResult,
        ReadToolOptions,
        create_read_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + (3001).to_bytes(4, "big")
        + (10).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    resized_payload = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + (2000).to_bytes(4, "big")
        + (7).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    (tmp_path / "wide.png").write_bytes(png_payload)

    class FakeResizer:
        def __init__(self) -> None:
            self.calls: list[tuple[bytes, str, tuple[int, int] | None]] = []

        async def resize_image(
            self,
            payload: bytes,
            *,
            mime_type: str,
            dimensions: tuple[int, int] | None,
        ) -> ReadImageResizeResult:
            self.calls.append((payload, mime_type, dimensions))
            return ReadImageResizeResult(
                payload=resized_payload,
                mime_type="image/png",
                original_dimensions=(3001, 10),
                dimensions=(2000, 7),
                was_resized=True,
            )

    resizer = FakeResizer()
    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(options=ReadToolOptions(image_resizer=resizer)),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-image-read", {"path": "wide.png"}))

    assert result.content[0].text == (
        "Read image file [image/png]\n"
        "[Image: original 3001x10, displayed at 2000x7. "
        "Multiply coordinates by 1.50 to map to original image.]"
    )
    assert result.content[1].type == "image"
    assert result.content[1].data == base64.b64encode(resized_payload).decode("ascii")
    assert result.details["image_omitted"] is False
    assert result.details["image_resized"] is True
    assert result.details["original_width"] == 3001
    assert result.details["original_height"] == 10
    assert result.details["width"] == 2000
    assert result.details["height"] == 7
    assert resizer.calls == [(png_payload, "image/png", (3001, 10))]


def test_read_does_not_resize_when_auto_resize_is_disabled(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import (
        ReadToolOptions,
        create_read_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + (3001).to_bytes(4, "big")
        + (10).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    (tmp_path / "wide.png").write_bytes(png_payload)

    class FailingIfCalledResizer:
        async def resize_image(
            self, payload: bytes, *, mime_type: str, dimensions: tuple[int, int] | None
        ):
            raise AssertionError("resizer should not be called")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(
            options=ReadToolOptions(
                auto_resize_images=False,
                image_resizer=FailingIfCalledResizer(),
            )
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-image-read", {"path": "wide.png"}))

    assert len(result.content) == 1
    assert "auto-resize is disabled" in result.content[0].text
    assert result.details["image_omitted"] is True
    assert result.details["image_resized"] is False
    assert result.details["omit_reason"] == "inline_image_limit"


def test_read_accepts_pi_style_auto_resize_option_alias() -> None:
    from loushang.harness.tools.workspace import ReadToolOptions

    options = ReadToolOptions(autoResizeImages=False)

    assert options.autoResizeImages is False
    assert options.auto_resize_images is True


def test_read_notes_when_current_model_does_not_support_images(tmp_path) -> None:
    import asyncio
    from types import SimpleNamespace

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
    )
    (tmp_path / "pixel.png").write_bytes(png_payload)

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(
            cwd=str(tmp_path), model=SimpleNamespace(input=("text",))
        ),
    )

    result = asyncio.run(runtime_tool.execute("call-image-read", {"path": "pixel.png"}))

    assert len(result.content) == 1
    assert result.content[0].text.endswith(
        "[Current model does not support images. The image will be omitted from this request.]"
    )
    assert result.details["image_omitted"] is True
    assert result.details["omit_reason"] == "non_vision_model"
    assert result.details["model_supports_image_input"] is False


def test_read_description_mentions_text_and_images() -> None:
    from loushang.harness.tools.workspace import create_read_tool_definition

    definition = create_read_tool_definition()

    assert "text files and images" in definition.description


def test_read_tool_raises_for_missing_file(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(FileNotFoundError):
        asyncio.run(runtime_tool.execute("call-read", {"path": "missing.txt"}))


def test_ls_tool_lists_directory_entries(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_ls_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "nested").mkdir()

    runtime_tool = wrap_tool_definition(
        create_ls_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-ls", {"path": "."}))
    lines = result.content[0].text.splitlines()

    assert "a.txt" in lines
    assert "nested/" in lines
    assert result.details["path"] == str(tmp_path)
    assert result.details["truncated"] is False


def test_ls_truncates_large_listing_with_default_limit_and_notice(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_ls_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    for index in range(510):
        (tmp_path / f"entry-{index:04d}.txt").write_text("x", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_ls_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-ls-large", {"path": "."}))
    lines = result.content[0].text.splitlines()

    assert len(lines) == 502
    assert lines[0] == "entry-0000.txt"
    assert lines[499] == "entry-0499.txt"
    assert lines[-1] == "[500 entries limit reached. Use limit=1000 for more]"
    assert result.details["path"] == str(tmp_path)
    assert result.details["truncated"] is True
    assert result.details["truncated_by"] is None
    assert result.details["entry_limit_reached"] is True
    assert result.details["entry_limit"] == 500
    assert "entryLimitReached" not in result.details


def test_ls_accepts_integral_numeric_limit(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_ls_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_ls_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-ls-float-limit", {"path": ".", "limit": 1.0})
    )

    assert (
        result.content[0].text
        == "a.txt\n\n[1 entries limit reached. Use limit=2 for more]"
    )
    assert result.details["entry_limit"] == 1


def test_ls_prepare_arguments_accepts_legacy_file_path_alias(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_ls_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "file.txt").write_text("x", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_ls_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    prepared = runtime_tool.prepare_arguments({"file_path": "nested"})
    result = asyncio.run(runtime_tool.execute("call-ls-legacy-path", prepared))

    assert prepared == {"path": "nested"}
    assert result.content[0].text == "file.txt"


def test_ls_tool_returns_empty_directory_message(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_ls_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_ls_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-empty", {"path": "."}))

    assert result.content[0].text == "(empty directory)"
    assert result.details["path"] == str(tmp_path)


def test_ls_tool_raises_for_file_path(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import create_ls_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    file_path = tmp_path / "plain.txt"
    file_path.write_text("hello", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_ls_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(NotADirectoryError):
        asyncio.run(runtime_tool.execute("call-ls", {"path": "plain.txt"}))


def test_find_tool_returns_matching_paths(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text("pass", encoding="utf-8")
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find", {"pattern": "agent", "path": "."})
    )

    assert "src/agent.py" in result.content[0].text.splitlines()
    assert result.details["path"] == str(tmp_path)
    assert result.details["truncated"] is False


def test_find_respects_gitignore_and_skips_common_vendor_dirs(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / ".gitignore").write_text("ignored.py\nbuild/\n", encoding="utf-8")
    (tmp_path / "visible.py").write_text("pass", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("pass", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "built.py").write_text("pass", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.py").write_text("pass", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.py").write_text("pass", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-ignore", {"pattern": "*.py", "path": "."})
    )

    assert result.details["matches"] == [{"path": "visible.py"}]
    assert result.content[0].text == "visible.py"


def test_find_fallback_scopes_nested_gitignore_rules_to_their_subtrees(
    monkeypatch, tmp_path
) -> None:
    import asyncio

    import loushang.harness.tools.workspace.find as find_module
    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    monkeypatch.setattr(find_module.shutil, "which", lambda name: None)

    (tmp_path / "a" / "deep").mkdir(parents=True)
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "a" / "deep" / ".gitignore").write_text(
        "secret.txt\n", encoding="utf-8"
    )
    (tmp_path / "a" / "ignored.txt").write_text("", encoding="utf-8")
    (tmp_path / "a" / "kept.txt").write_text("", encoding="utf-8")
    (tmp_path / "a" / "deep" / "ignored.txt").write_text("", encoding="utf-8")
    (tmp_path / "a" / "deep" / "secret.txt").write_text("", encoding="utf-8")
    (tmp_path / "a" / "deep" / "kept.txt").write_text("", encoding="utf-8")
    (tmp_path / "b" / "ignored.txt").write_text("", encoding="utf-8")
    (tmp_path / "b" / "kept.txt").write_text("", encoding="utf-8")
    (tmp_path / "root.txt").write_text("", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-nested-ignore", {"pattern": "**/*.txt", "path": "."}
        )
    )
    paths = sorted(
        line
        for line in result.content[0].text.splitlines()
        if line and not line.startswith("[")
    )

    assert paths == [
        "a/deep/kept.txt",
        "a/kept.txt",
        "b/ignored.txt",
        "b/kept.txt",
        "root.txt",
    ]


def test_find_returns_structured_match_details(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text("pass", encoding="utf-8")
    (tmp_path / "src" / "agent_test.py").write_text("pass", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-structured", {"pattern": "agent", "path": "."})
    )

    assert result.details["matches"] == [
        {"path": "src/agent.py"},
        {"path": "src/agent_test.py"},
    ]
    assert result.details["truncated"] is False


def test_find_direct_options_external_tool_policy_auto_downloads(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import (
        FindToolOptions,
        create_find_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nprintf 'direct-policy.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> str | None:
            self.calls.append(name)
            return str(fake_fd) if name == "fd" else None

    downloader = Downloader()
    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(
            options=FindToolOptions(
                external_tool_policy="auto",
                external_tool_resolver=MissingResolver(),
                external_tool_downloader=downloader,
            )
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-direct-policy-auto", {"pattern": "*.py", "path": "."}
        )
    )

    assert downloader.calls == ["fd"]
    assert result.content[0].text == "direct-policy.py"


def test_find_applies_default_limit_with_actionable_notice(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        async def exists(self, path):
            return True

        async def is_dir(self, path):
            return True

        async def walk_files(self, path):
            return [tmp_path / f"entry-{index:04d}.py" for index in range(1005)]

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(operations=VirtualOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-default-limit", {"pattern": "*.py", "path": "."}
        )
    )
    lines = result.content[0].text.splitlines()

    assert len(result.details["matches"]) == 1000
    assert lines[0] == "entry-0000.py"
    assert lines[999] == "entry-0999.py"
    assert (
        lines[-1]
        == "[1000 results limit reached. Use limit=2000 for more, or refine pattern]"
    )
    assert result.details["truncated"] is True
    assert result.details["truncated_by"] is None
    assert result.details["result_limit_reached"] is True
    assert result.details["result_limit"] == 1000


def test_find_accepts_integral_numeric_limit(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        async def exists(self, path):
            return True

        async def is_dir(self, path):
            return True

        async def walk_files(self, path):
            return [tmp_path / "a.py", tmp_path / "b.py"]

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(operations=VirtualOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-float-limit", {"pattern": "*.py", "path": ".", "limit": 1.0}
        )
    )

    assert (
        result.content[0].text
        == "a.py\n\n[1 results limit reached. Use limit=2 for more, or refine pattern]"
    )
    assert result.details["result_limit"] == 1


def test_find_fd_full_path_pattern_uses_full_path_glob(monkeypatch, tmp_path) -> None:
    import asyncio
    from types import SimpleNamespace

    import loushang.harness.tools.workspace.find as find_module

    captured: dict[str, object] = {}

    def fake_which(name):
        return "/usr/bin/fd" if name == "fd" else None

    async def fake_run_external_process(command, *, cwd, signal=None):
        del signal
        captured["command"] = command
        captured["cwd"] = cwd
        return SimpleNamespace(returncode=0, stdout="./src/pkg/agent.py\n", stderr="")

    monkeypatch.setattr(find_module.shutil, "which", fake_which)
    monkeypatch.setattr(find_module, "run_external_process", fake_run_external_process)

    matches = asyncio.run(
        find_module._walk_matching_paths_with_fd(
            tmp_path, pattern="src/**/*.py", limit=1000
        )
    )

    assert "--full-path" in captured["command"]
    assert "--color=never" in captured["command"]
    assert "--max-results" in captured["command"]
    assert "1000" in captured["command"]
    assert "**/src/**/*.py" in captured["command"]
    assert matches == [{"path": "src/pkg/agent.py"}]


def test_find_uses_external_tool_resolver_when_available(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import (
        FindToolOptions,
        create_find_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nprintf 'src/app.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    class Resolver:
        def __init__(self) -> None:
            self.names: list[str] = []

        async def resolve_tool(self, name: str) -> str | None:
            self.names.append(name)
            return str(fake_fd) if name == "fd" else None

    resolver = Resolver()
    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(
            options=FindToolOptions(external_tool_resolver=resolver)
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-resolver", {"pattern": "*.py", "path": "."})
    )

    assert resolver.names == ["fd"]
    assert result.content[0].text == "src/app.py"
    assert result.details["matches"] == [{"path": "src/app.py"}]


def test_find_falls_back_when_external_tool_resolver_misses(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import (
        FindToolOptions,
        create_find_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass", encoding="utf-8")

    class MissingResolver:
        async def resolve_tool(self, name: str) -> None:
            del name
            return None

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(
            options=FindToolOptions(external_tool_resolver=MissingResolver())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-fallback", {"pattern": "*.py", "path": "."})
    )

    assert result.content[0].text == "src/app.py"


def test_find_external_tool_failure_is_not_masked_by_fallback(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import (
        FindToolOptions,
        create_find_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass", encoding="utf-8")
    fake_fd = tmp_path / "fd"
    fake_fd.write_text(
        "#!/bin/sh\nprintf 'fd failed\\n' >&2\nexit 2\n", encoding="utf-8"
    )
    fake_fd.chmod(0o755)

    class Resolver:
        def resolve_tool(self, name: str) -> str | None:
            return str(fake_fd) if name == "fd" else None

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(
            options=FindToolOptions(external_tool_resolver=Resolver())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(RuntimeError, match="fd failed"):
        asyncio.run(
            runtime_tool.execute(
                "call-find-fd-failure", {"pattern": "*.py", "path": "."}
            )
        )


def test_find_requires_external_tool_when_configured(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import (
        FindToolOptions,
        create_find_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class MissingResolver:
        async def resolve_tool(self, name: str) -> None:
            del name
            return None

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(
            options=FindToolOptions(
                external_tool_resolver=MissingResolver(),
                require_external_tool=True,
            )
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(RuntimeError, match="fd external tool is required"):
        asyncio.run(
            runtime_tool.execute("call-find-required", {"pattern": "*.py", "path": "."})
        )


def test_find_fd_process_is_killed_when_signal_aborts(monkeypatch, tmp_path) -> None:
    import asyncio
    import time

    import pytest

    import loushang.harness.tools.workspace.find as find_module
    from loushang.agent import AbortController
    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nsleep 1\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    monkeypatch.setattr(
        find_module.shutil, "which", lambda name: str(fake_fd) if name == "fd" else None
    )

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    async def scenario() -> float:
        controller = AbortController()

        async def abort_soon() -> None:
            await asyncio.sleep(0.05)
            controller.abort()

        asyncio.create_task(abort_soon())
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="Operation aborted"):
            await runtime_tool.execute(
                "call-find-abort",
                {"pattern": "*.py", "path": "."},
                signal=controller.signal,
            )
        return time.monotonic() - started

    assert asyncio.run(scenario()) < 0.5


def test_find_byte_truncation_keeps_only_fully_rendered_matches(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    for index in range(260):
        name = f"entry-{index:04d}-" + ("a" * 220) + ".txt"
        (tmp_path / name).write_text("x", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-byte-truncation", {"pattern": "entry-", "path": "."}
        )
    )

    rendered_prefix = "\n".join(match["path"] for match in result.details["matches"])
    assert result.details["truncated"] is True
    assert result.details["truncated_by"] == "bytes"
    assert result.details["matches"]
    assert result.content[0].text.startswith(rendered_prefix)
    assert result.content[0].text != rendered_prefix
    assert result.content[0].text.startswith(f"{rendered_prefix}\n")
    assert result.details["truncation"]["truncatedBy"] == "bytes"
    assert result.details["truncation"]["maxBytes"] == 50 * 1024


def test_find_details_keep_python_snake_case_result_limit(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    for index in range(3):
        (tmp_path / f"entry-{index}.txt").write_text("x", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-limit", {"pattern": "entry-", "path": ".", "limit": 2}
        )
    )

    assert result.details["result_limit_reached"] is True
    assert result.details["result_limit"] == 2
    assert "resultLimitReached" not in result.details


def test_find_tool_returns_no_match_message(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find", {"pattern": "missing", "path": "."})
    )

    assert result.content[0].text == "No files found matching pattern"
    assert result.details["path"] == str(tmp_path)


def test_find_tool_raises_for_missing_root(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(FileNotFoundError):
        asyncio.run(
            runtime_tool.execute(
                "call-find", {"pattern": "agent", "path": "missing-dir"}
            )
        )


def test_grep_tool_returns_matching_lines(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "main.py").write_text(
        "def create_agent_session():\n    pass\n", encoding="utf-8"
    )

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep",
            {"pattern": "create_agent_session", "path": ".", "literal": True},
        )
    )

    assert (
        "main.py:1:def create_agent_session():" in result.content[0].text.splitlines()
    )
    assert result.details["path"] == str(tmp_path)
    assert result.details["truncated"] is False


def test_grep_tool_renders_context_lines(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "main.py").write_text("before\nneedle\n after\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-context",
            {"pattern": "needle", "path": ".", "literal": True, "context": 1},
        )
    )

    assert result.content[0].text.splitlines() == [
        "main.py-1-before",
        "main.py:2:needle",
        "main.py-3- after",
    ]
    assert result.details["matches"] == [
        {"path": "main.py", "line_number": 2, "line": "needle"},
    ]


def test_grep_accepts_integral_numeric_context_and_limit(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "main.py").write_text(
        "before\nneedle\n after\nneedle again\n", encoding="utf-8"
    )

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-float-context-limit",
            {
                "pattern": "needle",
                "path": ".",
                "literal": True,
                "context": 1.0,
                "limit": 1.0,
            },
        )
    )

    assert result.content[0].text.splitlines() == [
        "main.py-1-before",
        "main.py:2:needle",
        "main.py-3- after",
        "",
        "[1 matches limit reached. Use limit=2 for more, or refine pattern]",
    ]
    assert result.details["match_limit"] == 1


def test_grep_accepts_file_path_as_search_target(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "main.py").write_text("before\nneedle\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-file", {"pattern": "needle", "path": "main.py", "literal": True}
        )
    )

    assert result.content[0].text == "main.py:2:needle"
    assert result.details["path"] == str(tmp_path / "main.py")
    assert result.details["matches"] == [
        {"path": "main.py", "line_number": 2, "line": "needle"},
    ]


def test_grep_uses_external_tool_resolver_when_available(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import (
        GrepToolOptions,
        create_grep_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_rg = tmp_path / "rg"
    fake_rg.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' "
        '\'{"type":"match","data":{"path":{"text":"./main.py"},'
        '"line_number":2,"lines":{"text":"needle\\n"}}}\'\n',
        encoding="utf-8",
    )
    fake_rg.chmod(0o755)
    (tmp_path / "main.py").write_text("before\nneedle\n", encoding="utf-8")

    class Resolver:
        def __init__(self) -> None:
            self.names: list[str] = []

        def resolve_tool(self, name: str) -> str | None:
            self.names.append(name)
            return str(fake_rg) if name == "rg" else None

    resolver = Resolver()
    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(
            options=GrepToolOptions(external_tool_resolver=resolver)
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-resolver", {"pattern": "needle", "path": ".", "literal": True}
        )
    )

    assert resolver.names == ["rg"]
    assert result.content[0].text == "main.py:2:needle"
    assert result.details["matches"] == [
        {"path": "main.py", "line_number": 2, "line": "needle"}
    ]


def test_grep_external_regex_is_not_prevalidated_by_python_re(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import (
        GrepToolOptions,
        create_grep_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_rg = tmp_path / "rg"
    fake_rg.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' "
        '\'{"type":"match","data":{"path":{"text":"./main.py"},'
        '"line_number":1,"lines":{"text":"alpha\\n"}}}\'\n',
        encoding="utf-8",
    )
    fake_rg.chmod(0o755)
    (tmp_path / "main.py").write_text("alpha\n", encoding="utf-8")

    class Resolver:
        def resolve_tool(self, name: str) -> str | None:
            return str(fake_rg) if name == "rg" else None

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(
            options=GrepToolOptions(external_tool_resolver=Resolver())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-grep-rg-regex", {"pattern": r"\p{L}", "path": "."})
    )

    assert result.content[0].text == "main.py:1:alpha"


def test_grep_requires_external_tool_when_configured(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import (
        GrepToolOptions,
        create_grep_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(
            options=GrepToolOptions(
                external_tool_resolver=MissingResolver(),
                require_external_tool=True,
            )
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(RuntimeError, match="rg external tool is required"):
        asyncio.run(
            runtime_tool.execute(
                "call-grep-required", {"pattern": "needle", "path": "."}
            )
        )


def test_grep_external_tool_failure_is_not_masked_by_fallback(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import (
        GrepToolOptions,
        create_grep_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "main.py").write_text("needle\n", encoding="utf-8")
    fake_rg = tmp_path / "rg"
    fake_rg.write_text(
        "#!/bin/sh\nprintf 'rg failed\\n' >&2\nexit 2\n", encoding="utf-8"
    )
    fake_rg.chmod(0o755)

    class Resolver:
        def resolve_tool(self, name: str) -> str | None:
            return str(fake_rg) if name == "rg" else None

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(
            options=GrepToolOptions(external_tool_resolver=Resolver())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(RuntimeError, match="rg failed"):
        asyncio.run(
            runtime_tool.execute(
                "call-grep-rg-failure",
                {"pattern": "needle", "path": ".", "literal": True},
            )
        )


def test_grep_rg_process_is_killed_when_signal_aborts(monkeypatch, tmp_path) -> None:
    import asyncio
    import time

    import pytest

    import loushang.harness.tools.workspace.grep as grep_module
    from loushang.agent import AbortController
    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_rg = tmp_path / "rg"
    fake_rg.write_text("#!/bin/sh\nsleep 1\n", encoding="utf-8")
    fake_rg.chmod(0o755)

    monkeypatch.setattr(
        grep_module.shutil, "which", lambda name: str(fake_rg) if name == "rg" else None
    )

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    async def scenario() -> float:
        controller = AbortController()

        async def abort_soon() -> None:
            await asyncio.sleep(0.05)
            controller.abort()

        asyncio.create_task(abort_soon())
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="Operation aborted"):
            await runtime_tool.execute(
                "call-grep-abort",
                {"pattern": "needle", "path": ".", "literal": True},
                signal=controller.signal,
            )
        return time.monotonic() - started

    assert asyncio.run(scenario()) < 0.5


def test_grep_rg_stops_process_after_match_limit(monkeypatch, tmp_path) -> None:
    import asyncio
    import time

    import loushang.harness.tools.workspace.grep as grep_module
    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_rg = tmp_path / "rg"
    fake_rg.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "i=1",
                'while [ "$i" -le 10 ]; do',
                '  printf \'{"type":"match","data":{"path":{"text":"./main.py"},"line_number":%s,"lines":{"text":"needle %s\\\\n"}}}\\n\' "$i" "$i"',
                "  i=$((i + 1))",
                "  sleep 0.1",
                "done",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_rg.chmod(0o755)
    (tmp_path / "main.py").write_text("needle\n" * 10, encoding="utf-8")

    monkeypatch.setattr(
        grep_module.shutil, "which", lambda name: str(fake_rg) if name == "rg" else None
    )

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    async def scenario():
        started = time.monotonic()
        result = await runtime_tool.execute(
            "call-grep-limit-stop",
            {"pattern": "needle", "path": ".", "literal": True, "limit": 2},
        )
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(scenario())

    assert elapsed < 0.5
    assert (
        result.content[0].text.splitlines()[-1]
        == "[2 matches limit reached. Use limit=4 for more, or refine pattern]"
    )
    assert result.details["matches"] == [
        {"path": "main.py", "line_number": 1, "line": "needle 1"},
        {"path": "main.py", "line_number": 2, "line": "needle 2"},
    ]
    assert result.details["match_limit_reached"] is True


def test_grep_respects_gitignore_and_skips_common_vendor_dirs(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / ".gitignore").write_text("ignored.txt\nbuild/\n", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "built.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.txt").write_text("needle\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-ignore", {"pattern": "needle", "path": ".", "literal": True}
        )
    )

    assert result.details["matches"] == [
        {"path": "visible.txt", "line_number": 1, "line": "needle"},
    ]
    assert result.content[0].text == "visible.txt:1:needle"


def test_grep_truncates_large_match_sets_with_default_limit_and_notice(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    haystack = "".join(f"needle line {index:04d}\n" for index in range(105))
    (tmp_path / "main.py").write_text(haystack, encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-large",
            {"pattern": "needle", "path": ".", "literal": True},
        )
    )
    lines = result.content[0].text.splitlines()

    assert len(result.details["matches"]) == 100
    assert len(lines) == 102
    assert lines[0] == "main.py:1:needle line 0000"
    assert lines[99] == "main.py:100:needle line 0099"
    assert (
        lines[-1]
        == "[100 matches limit reached. Use limit=200 for more, or refine pattern]"
    )
    assert result.details["matches"][0] == {
        "path": "main.py",
        "line_number": 1,
        "line": "needle line 0000",
    }
    rendered_prefix = "\n".join(
        f"{match['path']}:{match['line_number']}:{match['line']}"
        for match in result.details["matches"]
    )
    assert result.content[0].text.startswith(rendered_prefix)
    assert result.details["truncated"] is True
    assert result.details["truncated_by"] is None
    assert result.details["match_limit_reached"] is True
    assert result.details["match_limit"] == 100
    assert "matchLimitReached" not in result.details


def test_grep_byte_truncation_excludes_partial_context_entries_from_details(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    haystack = "".join(
        f"before {index:04d}\nneedle {index:04d}\nafter {index:04d}\n"
        for index in range(2000)
    )
    (tmp_path / "main.py").write_text(haystack, encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-byte-truncation",
            {
                "pattern": "needle",
                "path": ".",
                "literal": True,
                "context": 1,
                "limit": 2000,
            },
        )
    )

    assert result.details["truncated"] is True
    assert result.details["truncated_by"] == "bytes"
    assert result.details["matches"]
    rendered_matches = [
        line for line in result.content[0].text.splitlines() if ":needle " in line
    ]
    assert len(rendered_matches) == len(result.details["matches"])
    assert result.details["truncation"]["truncatedBy"] == "bytes"
    assert "linesTruncated" not in result.details


def test_grep_prepare_arguments_accepts_legacy_aliases(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "main.py").write_text("Needle\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    prepared = runtime_tool.prepare_arguments(
        {"pattern": "needle", "file_path": "main.py", "ignore_case": True}
    )
    result = asyncio.run(runtime_tool.execute("call-grep-legacy-aliases", prepared))

    assert prepared == {"pattern": "needle", "path": "main.py", "ignoreCase": True}
    assert result.details["matches"][0]["line"] == "Needle"


def test_grep_prepare_arguments_rejects_conflicting_legacy_aliases(tmp_path) -> None:
    import pytest

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        ValueError, match="conflicting tool arguments: path and file_path"
    ):
        runtime_tool.prepare_arguments(
            {"pattern": "needle", "path": "main.py", "file_path": "other.py"}
        )
    with pytest.raises(
        ValueError, match="conflicting tool arguments: ignoreCase and ignore_case"
    ):
        runtime_tool.prepare_arguments(
            {"pattern": "needle", "ignoreCase": True, "ignore_case": False}
        )


def test_grep_truncates_long_lines_but_keeps_match_details(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    long_line = "needle:" + ("x" * (60 * 1024))
    (tmp_path / "main.py").write_text(f"{long_line}\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-long-line",
            {"pattern": "needle:", "path": ".", "literal": True},
        )
    )

    assert result.details["matches"] == [
        {"path": "main.py", "line_number": 1, "line": long_line},
    ]
    assert result.details["lines_truncated"] is True
    assert result.content[0].text.startswith("main.py:1:needle:")
    assert "... [truncated]" in result.content[0].text
    assert len(result.content[0].text) < 3000


def test_grep_tool_returns_no_matches_message(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-grep", {"pattern": "missing", "path": "."})
    )

    assert result.content[0].text == "No matches found"
    assert result.details["path"] == str(tmp_path)


def test_grep_tool_raises_for_missing_root(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(FileNotFoundError):
        asyncio.run(
            runtime_tool.execute(
                "call-grep", {"pattern": "needle", "path": "missing-dir"}
            )
        )


def test_write_tool_writes_text_file_from_context_cwd(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "nested").mkdir()
    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-write", {"path": "nested/notes.txt", "content": "alpha\nbeta\n"}
        )
    )

    assert (tmp_path / "nested" / "notes.txt").read_text(
        encoding="utf-8"
    ) == "alpha\nbeta\n"
    assert result.content[0].text == "Successfully wrote 11 bytes to nested/notes.txt"
    assert result.details["path"] == str((tmp_path / "nested" / "notes.txt").resolve())
    assert result.details["bytes_written"] == 11
    assert result.details["operation"] == "create"


def test_write_tool_writes_html_payload_with_script_content(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )
    html = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>BMI</title></head>
<body>
  <button id="calc">计算</button>
  <script>
    const label = "BMI <正常>";
    document.getElementById("calc").addEventListener("click", () => {
      document.body.dataset.result = label;
    });
  </script>
</body>
</html>
"""

    result = asyncio.run(
        runtime_tool.execute(
            "call-write-html", {"path": "tmp/bmi.html", "content": html}
        )
    )

    assert (tmp_path / "tmp" / "bmi.html").read_text(encoding="utf-8") == html
    assert (
        result.content[0].text
        == f"Successfully wrote {len(html.encode('utf-8'))} bytes to tmp/bmi.html"
    )
    assert result.details["bytes_written"] == len(html.encode("utf-8"))
    assert result.details["operation"] == "create"


def test_write_prepare_arguments_accepts_legacy_file_path_alias(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    prepared = runtime_tool.prepare_arguments(
        {"file_path": "notes.txt", "content": "legacy write"}
    )
    result = asyncio.run(runtime_tool.execute("call-write-legacy-path", prepared))

    assert prepared == {"content": "legacy write", "path": "notes.txt"}
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "legacy write"
    assert result.details["operation"] == "create"


def test_write_reports_create_vs_overwrite_details(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    existing = tmp_path / "existing.txt"
    existing.write_text("before\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()

    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    create_result = asyncio.run(
        runtime_tool.execute(
            "call-write-create", {"path": "nested/new.txt", "content": "alpha\n"}
        )
    )
    overwrite_result = asyncio.run(
        runtime_tool.execute(
            "call-write-overwrite", {"path": "existing.txt", "content": "after\n"}
        )
    )

    assert create_result.details["operation"] == "create"
    assert overwrite_result.details["operation"] == "overwrite"
    assert (tmp_path / "nested" / "new.txt").read_text(encoding="utf-8") == "alpha\n"
    assert existing.read_text(encoding="utf-8") == "after\n"


def test_write_uses_file_mutation_queue_for_same_path(tmp_path, monkeypatch) -> None:
    import asyncio
    from contextlib import asynccontextmanager

    import pytest

    import loushang.harness.tools.workspace.write as write_module
    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )
    target = tmp_path / "queued.txt"
    queue_paths: list[str] = []
    events: list[str] = []
    entered_first = asyncio.Event()
    entered_second = asyncio.Event()
    release_first = asyncio.Event()
    original_queue = write_module.with_file_mutation_queue
    entry_count = 0

    @asynccontextmanager
    async def recording_queue(path: str):
        nonlocal entry_count
        queue_paths.append(path)
        async with original_queue(path):
            entry_count += 1
            events.append(f"enter-{entry_count}")
            if entry_count == 1:
                entered_first.set()
                await release_first.wait()
            else:
                entered_second.set()
            try:
                yield
            finally:
                events.append(f"exit-{entry_count}")

    monkeypatch.setattr(write_module, "with_file_mutation_queue", recording_queue)

    async def run_both():
        first_task = asyncio.create_task(
            runtime_tool.execute(
                "call-write-first", {"path": "queued.txt", "content": "alpha\n"}
            )
        )
        await asyncio.wait_for(entered_first.wait(), timeout=0.1)
        second_task = asyncio.create_task(
            runtime_tool.execute(
                "call-write-second", {"path": "./queued.txt", "content": "beta\n"}
            )
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(entered_second.wait(), timeout=0.02)
        release_first.set()
        return await asyncio.gather(first_task, second_task)

    first_result, second_result = asyncio.run(run_both())

    assert queue_paths == [str(target.resolve()), str(target.resolve())]
    assert events == ["enter-1", "exit-1", "enter-2", "exit-2"]
    assert first_result.details["operation"] == "create"
    assert second_result.details["operation"] == "overwrite"
    assert target.read_text(encoding="utf-8") == "beta\n"


def test_write_creates_missing_parent_directories(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-write-missing-parent", {"path": "nested/notes.txt", "content": "x"}
        )
    )

    assert (tmp_path / "nested" / "notes.txt").read_text(encoding="utf-8") == "x"
    assert result.details["operation"] == "create"


def test_write_raises_when_non_directory_ancestor_blocks_traversal(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    blocker = tmp_path / "foo"
    blocker.write_text("not a directory", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(NotADirectoryError):
        asyncio.run(
            runtime_tool.execute(
                "call-write-blocked-ancestor",
                {"path": "foo/bar/baz.txt", "content": "x"},
            )
        )


def test_write_raises_for_conflict_or_policy_rejection(tmp_path, monkeypatch) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.operations import LocalToolOperations

    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    (tmp_path / "target-dir").mkdir()
    with pytest.raises(IsADirectoryError):
        asyncio.run(
            runtime_tool.execute(
                "call-write-directory", {"path": "target-dir", "content": "x"}
            )
        )

    blocked = (tmp_path / "blocked.txt").resolve()
    original_write_text = LocalToolOperations.write_text

    def raising_write_text(self, path, content, *, newline=None):
        if path.resolve() == blocked:
            raise PermissionError("blocked by policy")
        return original_write_text(self, path, content, newline=newline)

    monkeypatch.setattr(LocalToolOperations, "write_text", raising_write_text)

    with pytest.raises(PermissionError, match="blocked by policy"):
        asyncio.run(
            runtime_tool.execute(
                "call-write-blocked", {"path": "blocked.txt", "content": "x"}
            )
        )


def test_write_tool_raises_for_invalid_inputs(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(TypeError):
        asyncio.run(runtime_tool.execute("call-write", {"path": "", "content": "x"}))
    with pytest.raises(TypeError):
        asyncio.run(
            runtime_tool.execute("call-write", {"path": "notes.txt", "content": None})
        )


def test_edit_returns_diff_aware_details(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    nested = tmp_path / "nested"
    nested.mkdir()
    path = nested / "main.py"
    path.write_text("def old_name():\n    pass\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-edit",
            {
                "path": "nested/../nested/main.py",
                "edits": [{"oldText": "old_name", "newText": "new_name"}],
            },
        )
    )

    assert path.read_text(encoding="utf-8") == "def new_name():\n    pass\n"
    assert result.content[0].text == "Applied 1 edits to nested/../nested/main.py"
    assert result.details["path"] == str(path)
    assert result.details["applied_edit_count"] == 1
    assert f"--- {path}" in result.details["diff"]
    assert f"+++ {path}" in result.details["diff"]
    assert "-def old_name():" in result.details["diff"]
    assert "+def new_name():" in result.details["diff"]


def test_edit_prepare_arguments_accepts_json_string_edits_and_legacy_fields(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    prepared = runtime_tool.prepare_arguments(
        {
            "path": "main.py",
            "edits": json.dumps([{"oldText": "alpha", "newText": "ALPHA"}]),
            "oldText": "gamma",
            "newText": "GAMMA",
        }
    )
    asyncio.run(runtime_tool.execute("call-edit-prepared", prepared))

    assert path.read_text(encoding="utf-8") == "ALPHA\nbeta\nGAMMA\n"


def test_edit_prepare_arguments_accepts_legacy_file_path_alias(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    path.write_text("alpha\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    prepared = runtime_tool.prepare_arguments(
        {
            "file_path": "main.py",
            "oldText": "alpha",
            "newText": "ALPHA",
        }
    )
    asyncio.run(runtime_tool.execute("call-edit-legacy-path", prepared))

    assert prepared["path"] == "main.py"
    assert "file_path" not in prepared
    assert path.read_text(encoding="utf-8") == "ALPHA\n"


def test_edit_prepare_arguments_rejects_conflicting_file_path_alias(tmp_path) -> None:
    import pytest

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        ValueError, match="conflicting tool arguments: path and file_path"
    ):
        runtime_tool.prepare_arguments(
            {
                "path": "main.py",
                "file_path": "other.py",
                "oldText": "alpha",
                "newText": "ALPHA",
            }
        )


def test_edit_details_keep_python_snake_case_first_changed_line(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    path.write_text("alpha\nbeta\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-edit-details",
            {"path": "main.py", "edits": [{"oldText": "beta", "newText": "BETA"}]},
        )
    )

    assert result.details["first_changed_line"] == 2
    assert "firstChangedLine" not in result.details


def test_edit_matches_lf_old_text_in_bom_prefixed_crlf_file(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    path.write_bytes(b"\xef\xbb\xbfalpha\r\nbeta\r\n")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    asyncio.run(
        runtime_tool.execute(
            "call-edit-bom-crlf",
            {
                "path": "main.py",
                "edits": [{"oldText": "alpha\nbeta\n", "newText": "ALPHA\nBETA\n"}],
            },
        )
    )

    assert path.read_bytes() == b"\xef\xbb\xbfALPHA\r\nBETA\r\n"


def test_edit_fuzzy_matches_smart_quotes_and_trailing_whitespace(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    path.write_text("message = \u201chello\u201d  \nkeep = 1\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    asyncio.run(
        runtime_tool.execute(
            "call-edit-fuzzy",
            {
                "path": "main.py",
                "edits": [
                    {"oldText": 'message = "hello"\n', "newText": 'message = "world"\n'}
                ],
            },
        )
    )

    assert path.read_text(encoding="utf-8") == 'message = "world"\nkeep = 1\n'


def test_edit_matches_exact_crlf_old_text(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    path.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-edit-crlf-match",
            {
                "path": "main.py",
                "edits": [
                    {"oldText": "alpha\r\nbeta\r\n", "newText": "ALPHA\r\nBETA\r\n"}
                ],
            },
        )
    )

    assert path.read_bytes() == b"ALPHA\r\nBETA\r\ngamma\r\n"
    assert "-alpha\r\n-beta\r\n" in result.details["diff"]
    assert "+ALPHA\r\n+BETA\r\n" in result.details["diff"]


def test_edit_preserves_crlf_line_endings_in_written_output(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    original = b"first\r\nmiddle\r\nlast\r\n"
    path.write_bytes(original)

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    asyncio.run(
        runtime_tool.execute(
            "call-edit-crlf-preserve",
            {
                "path": "main.py",
                "edits": [{"oldText": "middle", "newText": "changed"}],
            },
        )
    )

    assert path.read_bytes() == b"first\r\nchanged\r\nlast\r\n"


def test_edit_tool_applies_multiple_disjoint_edits_against_original_file(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    path.write_text("alpha = 1\nbeta = 2\ngamma = 3\n", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    asyncio.run(
        runtime_tool.execute(
            "call-edit",
            {
                "path": "main.py",
                "edits": [
                    {"oldText": "alpha = 1", "newText": "alpha = 10"},
                    {"oldText": "gamma = 3", "newText": "gamma = 30"},
                ],
            },
        )
    )

    assert path.read_text(encoding="utf-8") == "alpha = 10\nbeta = 2\ngamma = 30\n"


def test_edit_raises_for_no_match(tmp_path) -> None:
    import asyncio
    import re

    import pytest

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    original = "alpha\nbeta\n"
    path.write_text(original, encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        ValueError,
        match=rf"edits\[0\].*{re.escape(str(path))}.*did not match any content",
    ):
        asyncio.run(
            runtime_tool.execute(
                "call-edit-miss",
                {
                    "path": "main.py",
                    "edits": [{"oldText": "missing", "newText": "new"}],
                },
            )
        )

    assert path.read_text(encoding="utf-8") == original


def test_edit_raises_for_multi_match_ambiguity(tmp_path) -> None:
    import asyncio
    import re

    import pytest

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    original = "repeat\nrepeat\n"
    path.write_text(original, encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        ValueError, match=rf"edits\[0\].*{re.escape(str(path))}.*matched more than once"
    ):
        asyncio.run(
            runtime_tool.execute(
                "call-edit-duplicate",
                {
                    "path": "main.py",
                    "edits": [{"oldText": "repeat", "newText": "new"}],
                },
            )
        )

    assert path.read_text(encoding="utf-8") == original


def test_edit_rejects_overlapping_edits(tmp_path) -> None:
    import asyncio
    import re

    import pytest

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    path = tmp_path / "main.py"
    original = "one\ntwo\nthree\n"
    path.write_text(original, encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        ValueError,
        match=rf"edits\[0\].*edits\[1\].*overlap.*{re.escape(str(path))}",
    ):
        asyncio.run(
            runtime_tool.execute(
                "call-edit-overlap",
                {
                    "path": "main.py",
                    "edits": [
                        {"oldText": "one\ntwo\n", "newText": "ONE\nTWO\n"},
                        {"oldText": "two\nthree\n", "newText": "TWO\nTHREE\n"},
                    ],
                },
            )
        )

    assert path.read_text(encoding="utf-8") == original
