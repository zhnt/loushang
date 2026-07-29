from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.ai.types import ToolCall
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
)
from loushang.harness.effects import (
    FilesystemEffect,
    NetworkEffect,
    ProcessEffect,
    PublicationEffect,
)
from loushang.harness.policy import build_tool_policy_subject
from loushang.harness.policy_effects import detect_policy_effects
from loushang.harness.tools import (
    FilesystemActionAdapter,
    NetworkActionAdapter,
    ProcessActionAdapter,
    PublicationActionAdapter,
    ToolContext,
    authorized_tool,
    direct_tool,
    tool,
)
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    DirectExecution,
    ToolCallContext,
)
from loushang.harness.tools.workspace.audit import build_action_audit_details
from loushang.harness.tools.workspace.authorization import (
    _execute_authorized_tool_action,
)


@tool()
async def _echo(value: str, ctx: ToolContext) -> str:
    return f"{ctx.cwd}:{value}"


def _prepare(adapter, arguments: dict[str, object], *, cwd: str):
    return adapter.prepare(
        ToolCall(
            type="toolCall",
            id="call-1",
            name="demo",
            arguments=arguments,
        ),
        ToolCallContext(tool_call_id="call-1", cwd=cwd),
    )


def test_public_authoring_surface_selects_an_explicit_execution_route() -> None:
    direct = direct_tool(_echo)
    authorized = authorized_tool(
        _echo,
        action=FilesystemActionAdapter("read", path_argument="value"),
    )

    assert isinstance(direct.execution, DirectExecution)
    assert isinstance(authorized.execution, AuthorizedExecution)


def test_filesystem_adapter_resolves_authority_bearing_paths(tmp_path: Path) -> None:
    prepared = _prepare(
        FilesystemActionAdapter(
            "write",
            authorization_fields=("content",),
        ),
        {"path": "notes.txt", "content": "hello"},
        cwd=str(tmp_path),
    )

    target = str((tmp_path / "notes.txt").resolve())
    assert prepared.authorization_arguments == {
        "path": target,
        "content": "hello",
    }
    assert prepared.effects == (FilesystemEffect("write", (target,)),)


def test_process_network_and_publication_adapters_declare_typed_effects(
    tmp_path: Path,
) -> None:
    process = _prepare(
        ProcessActionAdapter(),
        {"command": ["git", "status"]},
        cwd=str(tmp_path),
    )
    network = _prepare(
        NetworkActionAdapter(mutation=True),
        {"url": "https://example.test/api"},
        cwd=str(tmp_path),
    )
    publication = _prepare(
        PublicationActionAdapter(),
        {
            "target": "refs/heads/main",
            "repository": str(tmp_path),
            "remote": "origin",
        },
        cwd=str(tmp_path),
    )

    assert process.effects == (ProcessEffect(("git", "status")),)
    assert network.effects == (
        NetworkEffect("https://example.test/api", mutation=True),
    )
    assert publication.effects == (
        PublicationEffect(
            "refs/heads/main",
            repository=str(tmp_path),
            remote="origin",
        ),
    )


@pytest.mark.parametrize(
    ("effect", "code"),
    (
        (FilesystemEffect("delete", ("/tmp/example",)), "filesystem_deletion"),
        (
            NetworkEffect("https://example.test/api", mutation=True),
            "external_system_effect",
        ),
        (
            PublicationEffect("refs/heads/main", remote="origin"),
            "external_publication",
        ),
    ),
)
def test_declared_effects_drive_policy_detection(effect, code: str) -> None:
    subject = build_tool_policy_subject(
        tool_name="custom",
        arguments={},
        effects=(effect,),
    )

    assert code in {item.code for item in detect_policy_effects(subject)}


def test_effect_audit_summary_does_not_copy_raw_resource_values() -> None:
    subject = build_tool_policy_subject(
        tool_name="publish",
        arguments={},
        effects=(
            FilesystemEffect("write", ("/private/workspace/secret.txt",)),
            NetworkEffect("https://secret.example.test/token", mutation=True),
            PublicationEffect(
                "refs/heads/private",
                repository="/private/repository",
                remote="secret-origin",
            ),
        ),
    )

    details = build_action_audit_details(
        tool_name="publish",
        arguments={},
        cwd="/private/workspace",
        policy_subject=subject,
    )

    rendered = repr(details)
    assert "/private" not in rendered
    assert "secret.example.test" not in rendered
    assert "secret-origin" not in rendered


def test_generic_filesystem_effect_is_revalidated_by_the_gateway(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.txt"

    with pytest.raises(ExecutionAuthorizationError, match="outside"):
        asyncio.run(
            _execute_authorized_tool_action(
                None,
                tool_name="custom_reader",
                arguments={"resource": "opaque"},
                effects=(FilesystemEffect("read", (str(outside),)),),
                execution_profile_ceiling=EffectiveExecutionProfile(
                    readable_roots=(tmp_path / "workspace",),
                ),
                executor=lambda _action: pytest.fail("executor must not run"),
            )
        )
