from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.harness.commands import parse_slash_command
from loushang.harness.extensions.types import ResolvedCommand
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
)
from loushang.harness.session.command_sources import (
    ExtensionCommandSourceRuntime,
    ResourceCommandSourceRuntime,
)


class _ExtensionProvider:
    def __init__(self, command: ResolvedCommand) -> None:
        self._command = command
        self.contexts: list[object] = []

    def get_registered_commands(self) -> list[ResolvedCommand]:
        return [self._command]

    def get_command(self, invocation_name: str) -> ResolvedCommand | None:
        return (
            self._command if invocation_name == self._command.invocation_name else None
        )

    def create_command_context(self, *, fallback_cwd: str = "") -> object:
        context = {"cwd": fallback_cwd}
        self.contexts.append(context)
        return context

    async def get_command_argument_completions(
        self, invocation_name: str, prefix: str
    ) -> list[object] | None:
        if invocation_name != self._command.invocation_name:
            return None
        return [f"{prefix}-choice"]


def test_extension_command_source_dispatches_through_provider_ports() -> None:
    calls: list[tuple[str, object]] = []
    errors: list[tuple[str, str]] = []

    async def _handler(args: str, context: object) -> None:
        calls.append((args, context))

    command = ResolvedCommand(
        name="deploy",
        handler=_handler,
        description="Deploy a revision",
        invocation_name="deploy",
        source_info=_source_info("/tmp/extensions/deploy.py"),
        extension_name="deploy-ext",
    )
    provider = _ExtensionProvider(command)
    runtime = ExtensionCommandSourceRuntime(
        get_provider=lambda: provider,
        get_cwd=lambda: "/tmp/project",
        result_factory=lambda resolved: {"command": resolved.invocation_name},
        record_error=lambda resolved, exc: errors.append(
            (resolved.invocation_name, str(exc))
        ),
    )
    invocation = parse_slash_command("/deploy staging")
    assert invocation is not None

    outcome = asyncio.run(runtime.dispatch(invocation))

    assert [descriptor.name for descriptor in runtime.list_descriptors()] == ["deploy"]
    assert outcome.handled is True
    assert outcome.result == {"command": "deploy"}
    assert calls == [("staging", {"cwd": "/tmp/project"})]
    assert errors == []
    assert asyncio.run(runtime.get_argument_completions("deploy", "stage")) == [
        "stage-choice"
    ]
    assert runtime.extract_invocation("/deploy staging") == ("deploy", "staging")
    assert runtime.extract_invocation("/missing") is None


def test_extension_command_source_records_handler_errors_without_losing_dispatch() -> (
    None
):
    errors: list[str] = []

    async def _handler(_args: str, _context: object) -> None:
        raise RuntimeError("extension failed")

    command = ResolvedCommand(
        name="deploy",
        handler=_handler,
        invocation_name="deploy",
        source_info=_source_info("/tmp/extensions/deploy.py"),
        extension_name="deploy-ext",
    )
    runtime = ExtensionCommandSourceRuntime(
        get_provider=lambda: _ExtensionProvider(command),
        get_cwd=lambda: "/tmp/project",
        result_factory=lambda resolved: resolved.invocation_name,
        record_error=lambda _resolved, exc: errors.append(str(exc)),
    )
    invocation = parse_slash_command("/deploy")
    assert invocation is not None

    outcome = asyncio.run(runtime.dispatch(invocation))

    assert outcome.handled is True
    assert outcome.result == "deploy"
    assert errors == ["extension failed"]


def test_resource_command_source_projects_results_and_reports_failures() -> None:
    diagnostics: list[tuple[str, ...]] = []
    missing: list[tuple[str, str]] = []
    bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="review",
                source_path=Path("/tmp/project/prompts/review.md"),
                text="Review $ARGUMENTS",
            )
        ],
    )
    runtime = ResourceCommandSourceRuntime(
        get_resource_bundle=lambda: bundle,
        record_diagnostics=lambda values: diagnostics.append(
            tuple(value.code for value in values)
        ),
        record_command_not_found=lambda name, args: missing.append((name, args)),
        result_factory=lambda name, source, text: {
            "name": name,
            "source": source,
            "text": text,
        },
    )
    review = parse_slash_command("/review current diff")
    unknown = parse_slash_command("/unknown")
    assert review is not None
    assert unknown is not None

    outcome = runtime.dispatch(review)
    unresolved = runtime.dispatch(unknown)

    assert [descriptor.name for descriptor in runtime.list_descriptors()] == ["review"]
    assert outcome.handled is True
    assert outcome.result == {
        "name": "review",
        "source": "prompt",
        "text": "Review current diff",
    }
    assert unresolved.handled is False
    assert diagnostics == [(), ("unresolved_prompt_reference",)]
    assert missing == []


def test_command_source_runtimes_have_no_coding_import() -> None:
    module_path = (
        Path(__file__).parents[3] / "src/loushang/harness/session/command_sources.py"
    )

    assert "loushang.coding" not in module_path.read_text(encoding="utf-8")


def _source_info(path: str):
    from loushang.harness.resources.source import SourceInfo

    return SourceInfo(path=Path(path), base_dir=Path(path).parent)
