"""P0 author commands through a separate target Coding Product and Session."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Sequence
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.protocol import ProviderRequest
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.cli.application import run_cli
from loushang.coding.cli.package_cutover import main as cutover_cli_main
from loushang.coding.cli.package_gc import main as gc_cli_main
from loushang.coding.plugin_author_smoke import _user_message_text
from loushang.coding.plugin_author_smoke import main as smoke_cli_main
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateLedger,
    PluginLifecycleError,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetLedger,
)
from loushang.harness.resources.packages.plugin_lifecycle.product_retention import (
    PackageProductRetentionSettlementOwner,
)
from loushang.plugin.__main__ import main as author_cli_main


class _OfflineModelTransport:
    """Model transport only; Product and Resource selection stay real."""

    api = "plugin-p0-public-journey-offline"

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": request.context.system_prompt,
                "messages": [
                    serialize_message(item) for item in request.context.messages
                ],
                "model": request.model.id,
            },
        )

    async def invoke_prepared_raw(
        self, request: ProviderRequest, prepared: PreparedModelRequest
    ) -> AsyncIterator[RawPart]:
        del request
        prepared.payload_for_transport()
        yield {"type": "response_start", "response_id": "p0-public-journey"}
        yield {"type": "text_delta", "text": "done"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        prepared = self.prepare_request(request)
        async for part in self.invoke_prepared_raw(request, prepared):
            yield part


def _author_command(
    args: Sequence[str], capsys: pytest.CaptureFixture[str]
) -> dict[str, Any]:
    assert author_cli_main(args) == 0
    return json.loads(capsys.readouterr().out)


def _target_command(workspace: Path, *args: str) -> Any:
    stdout = StringIO()
    stderr = StringIO()
    assert (
        asyncio.run(
            run_cli(
                list(args),
                cwd=workspace,
                stdin=StringIO(),
                stdout=stdout,
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    output = stdout.getvalue().strip()
    return json.loads(output) if output.startswith(("[", "{")) else None


def _session(
    workspace: Path, settings: SettingsManager, session_root: Path
) -> tuple[object, SessionManager]:
    manager = asyncio.run(
        SessionManager.new(session_dir=session_root, cwd=str(workspace), persist=True)
    )
    session = create_agent_session(
        session_manager=manager,
        model=Model(
            id="p0-offline-model",
            name="P0 Offline Model",
            provider="test",
            endpoint="p0-offline",
            api=_OfflineModelTransport.api,
            base_url="https://provider.invalid/v1",
            auth=Auth(kind="none"),
            capabilities=Capabilities(
                input=("text",),
                output=("text",),
                context_window=128000,
                stream=True,
                tool_use=True,
            ),
        ),
        services=create_services(settings_manager=settings),
        composition_set="coding-standard",
    )
    return session, manager


def _prepared_contains(
    session: object, manager: SessionManager, invocation: str, marker: str
) -> None:
    asyncio.run(session.prompt(invocation))  # type: ignore[attr-defined]
    snapshots = [
        item for item in manager.get_entries() if item.kind == "model.input.prepared"
    ]
    assert snapshots
    snapshot_id = getattr(snapshots[-1].payload, "snapshot_id", None)
    assert isinstance(snapshot_id, str)
    rebuilt = manager.rebuild_model_input(snapshot_id)
    assert any(marker in value for value in _user_message_text(rebuilt.logical_input))
    assert any(
        marker in value for value in _user_message_text(rebuilt.prepared_payload)
    )


@pytest.mark.skipif(os.name != "posix", reason="fenced data Product is POSIX")
def test_p0_public_author_to_target_skill_and_prompt_journey(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "target"
    workspace.mkdir(mode=0o700)
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()

    artifacts: dict[str, dict[str, object]] = {}
    for kind, plugin_id, resource_name, marker in (
        ("skill", "skillpack", "review", "P0 skill v1 marker"),
        ("prompt", "promptpack", "audit", "P0 prompt marker"),
    ):
        scaffold = _author_command(
            [
                f"init-coding-{kind}",
                str(tmp_path / plugin_id),
                "--resource-name",
                resource_name,
            ],
            capsys,
        )
        source = Path(str(scaffold["sourcePath"]))
        source.write_text(f"# {resource_name}\n{marker}\n", encoding="utf-8")
        built = _author_command(scaffold["buildCommand"][1:], capsys)  # type: ignore[index]
        validated = _author_command(built["validationCommand"][1:], capsys)  # type: ignore[index]
        assert validated["sha256"] == built["sha256"]
        assert validated["productAdmission"] == "not_checked"
        assert smoke_cli_main(scaffold["smokeCommand"][1:]) == 0  # type: ignore[index]
        smoke = json.loads(capsys.readouterr().out)
        assert smoke["workspace"] == "disposable"
        receipt = _target_command(workspace, *built["targetInstallCommand"][1:])  # type: ignore[index]
        assert receipt is not None and receipt["pluginId"] == plugin_id
        assert receipt["sourceSha256"] == built["sha256"]
        assert receipt["nextCommands"][0] == f"loushang --enable-plugin {plugin_id}"
        _target_command(workspace, "--enable-plugin", plugin_id)
        artifacts[kind] = built

    listing = _target_command(
        workspace, "--list-plugins", "--list-plugins-format", "json"
    )
    assert listing is not None
    assert {
        item["name"] for item in listing if item["desiredState"] == "installed_enabled"
    } >= {"skillpack", "promptpack"}

    transport = _OfflineModelTransport()
    registry = get_default_api_registry()
    registry.register_api_adapter(transport, source_id=transport.api)
    sessions: list[object] = []
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    try:
        first, first_manager = _session(workspace, settings, tmp_path / "sessions-1")
        sessions.append(first)
        _prepared_contains(
            first, first_manager, "/skill:review Check", "P0 skill v1 marker"
        )
        _prepared_contains(first, first_manager, "/audit Check", "P0 prompt marker")

        skill_source = tmp_path / "skillpack" / "skills" / "review" / "SKILL.md"
        skill_source.write_text("# review\nP0 skill v2 marker\n", encoding="utf-8")
        updated = _author_command(
            [
                "build-coding-skill",
                str(skill_source),
                "--plugin-id",
                "skillpack",
                "--version",
                "2",
                "--output-dir",
                str(tmp_path / "skillpack" / "dist"),
            ],
            capsys,
        )
        _author_command(updated["validationCommand"][1:], capsys)  # type: ignore[index]
        update_receipt = _target_command(
            workspace,
            "--update-package",
            str(updated["artifactPath"]),
            "--package-scope",
            "project",
        )
        assert update_receipt is not None and update_receipt["pluginId"] == "skillpack"
        second, second_manager = _session(workspace, settings, tmp_path / "sessions-2")
        sessions.append(second)
        _prepared_contains(
            second, second_manager, "/skill:review Check", "P0 skill v2 marker"
        )
        _prepared_contains(
            first, first_manager, "/skill:review Check", "P0 skill v1 marker"
        )

        _target_command(workspace, "--disable-plugin", "promptpack")
        third, _ = _session(workspace, settings, tmp_path / "sessions-3")
        sessions.append(third)
        assert third.resource_bundle is not None  # type: ignore[attr-defined]
        assert not any(  # type: ignore[attr-defined]
            item.name == "audit" and item.source_kind == "external_package"
            for item in third.resource_bundle.prompts  # type: ignore[attr-defined]
        )

        removed = _target_command(
            workspace, "--uninstall-package", "skillpack", "--package-scope", "project"
        )
        assert removed is not None and removed["operationKind"] == "A1"
        assert removed["stage"] == "desired_absent"
        assert removed["retirementStatus"]["evidence"] == "observed"
        assert removed["gcStatus"] == "not_checked"
        assert removed["nextCommands"][-1] == [
            "loushang",
            "--list-plugins",
            "--list-plugins-format",
            "json",
        ]
        assert removed["gcStatusCommand"] == [
            "loushang-package-gc",
            "--workspace",
            str(workspace),
            "list",
        ]
        assert removed["gcPrepareCommand"] == [
            "loushang-package-gc",
            "--workspace",
            str(workspace),
            "prepare",
        ]
        assert removed["gcStatusPrerequisite"] == "close_active_sessions_and_prepare_gc"
        batch_stdout = StringIO()
        batch_stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    [
                        "--uninstall-package",
                        "promptpack",
                        "--uninstall-package",
                        "missingpack",
                        "--package-scope",
                        "project",
                    ],
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=batch_stdout,
                    stderr=batch_stderr,
                )
            )
            == 1
        )
        first_uninstall = json.loads(batch_stdout.getvalue())
        assert first_uninstall["record"]["pluginId"] == "promptpack"
        assert "missingpack" in batch_stderr.getvalue()
        assert first_uninstall["record"]["operationId"] not in batch_stderr.getvalue()
        fourth, _ = _session(workspace, settings, tmp_path / "sessions-4")
        sessions.append(fourth)
        assert fourth.resource_bundle is not None  # type: ignore[attr-defined]
        assert not any(  # type: ignore[attr-defined]
            item.name == "review" and item.source_kind == "external_package"
            for item in fourth.resource_bundle.skills  # type: ignore[attr-defined]
        )
    finally:
        for session in reversed(sessions):
            asyncio.run(session.dispose())  # type: ignore[attr-defined]
        registry.unregister_api_adapters(transport.api)
    assert gc_cli_main(["--workspace", str(workspace), "prepare"]) == 0
    prepared_gc = json.loads(capsys.readouterr().out)
    assert prepared_gc["disposition"] == "prepared"
    assert gc_cli_main(["--workspace", str(workspace), "list"]) == 0
    gc_status = json.loads(capsys.readouterr().out)
    assert "candidates" in gc_status


@pytest.mark.skipif(os.name != "posix", reason="fenced data Product is POSIX")
def test_p0_public_update_failure_reports_post_cas_handoff_and_repairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "target"
    workspace.mkdir(mode=0o700)
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()
    source = tmp_path / "review" / "skills" / "review" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Review\nVersion one.\n", encoding="utf-8")
    built_v1 = _author_command(
        [
            "build-coding-skill",
            str(source),
            "--plugin-id",
            "reviewpack",
            "--version",
            "1",
            "--output-dir",
            str(tmp_path / "dist"),
        ],
        capsys,
    )
    _target_command(workspace, *built_v1["targetInstallCommand"][1:])
    _target_command(workspace, "--enable-plugin", "reviewpack")
    source.write_text("# Review\nVersion two.\n", encoding="utf-8")
    built_v2 = _author_command(
        [
            "build-coding-skill",
            str(source),
            "--plugin-id",
            "reviewpack",
            "--version",
            "2",
            "--output-dir",
            str(tmp_path / "dist"),
        ],
        capsys,
    )
    original_settle = PackageProductRetentionSettlementOwner.settle
    interrupted = False

    def interrupt_once(
        owner: object, receipt: object, *, desired_receipt: object
    ) -> object:
        nonlocal interrupted
        if not interrupted and receipt.request.operation_id.startswith(  # type: ignore[attr-defined]
            "coding-external-update:"
        ):
            interrupted = True
            raise OSError("injected settlement interruption")
        return original_settle(owner, receipt, desired_receipt=desired_receipt)  # type: ignore[arg-type]

    monkeypatch.setattr(
        PackageProductRetentionSettlementOwner, "settle", interrupt_once
    )
    stdout = StringIO()
    stderr = StringIO()
    result = asyncio.run(
        run_cli(
            [
                "--update-package",
                str(built_v2["artifactPath"]),
                "--package-scope",
                "project",
            ],
            cwd=workspace,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )
    assert result == 1
    assert interrupted
    failure = json.loads(stderr.getvalue().splitlines()[-1])
    operation_id = failure["operationId"]
    assert operation_id.startswith("coding-external-update:")
    assert failure["stage"] == "desired_committed"
    assert failure["desiredInventoryRevision"] >= 1
    assert failure["committedRevision"]["version"] == "2"
    assert failure["handoffEvidence"] == "incomplete"
    assert failure["nextCommands"][-1] == [
        "loushang-package-repair",
        "--workspace",
        str(workspace),
        "repair-handoff",
        operation_id,
    ]
    pending = _target_command(workspace, "--explain-plugin-operation", operation_id)
    assert pending is not None and pending["handoffEvidence"] == "incomplete"
    selected = _target_command(
        workspace, "--list-plugins", "--list-plugins-format", "json"
    )
    assert selected is not None
    assert (
        next(item for item in selected if item["name"] == "reviewpack")["version"]
        == "2"
    )

    monkeypatch.setattr(
        PackageProductRetentionSettlementOwner, "settle", original_settle
    )
    from loushang.coding.cli.package_repair import main as repair_cli_main

    assert (
        repair_cli_main(["--workspace", str(workspace), "repair-handoff", operation_id])
        == 0
    )
    repaired = json.loads(capsys.readouterr().out)
    assert repaired["disposition"] == "committed"
    settled = _target_command(workspace, "--explain-plugin-operation", operation_id)
    assert settled is not None and settled["handoffEvidence"] == "settled"


@pytest.mark.skipif(os.name != "posix", reason="fenced data Product is POSIX")
def test_p0_public_update_pre_cas_refusal_preserves_previous_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "target"
    workspace.mkdir(mode=0o700)
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()
    source = tmp_path / "review" / "skills" / "review" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Review\nVersion one.\n", encoding="utf-8")

    def build(version: str) -> dict[str, Any]:
        return _author_command(
            [
                "build-coding-skill",
                str(source),
                "--plugin-id",
                "reviewpack",
                "--version",
                version,
                "--output-dir",
                str(tmp_path / "dist"),
            ],
            capsys,
        )

    built_v1 = build("1")
    _target_command(workspace, *built_v1["targetInstallCommand"][1:])
    _target_command(workspace, "--enable-plugin", "reviewpack")
    source.write_text("# Review\nVersion two.\n", encoding="utf-8")
    built_v2 = build("2")
    original_commit_update = PluginDesiredStateLedger.commit_update
    refused = False

    def refuse_before_cas(owner: PluginDesiredStateLedger, mutation: object) -> object:
        nonlocal refused
        if not refused and mutation.installation_key.plugin_id == "reviewpack":  # type: ignore[attr-defined]
            refused = True
            raise PluginLifecycleError(
                "injected pre-CAS update refusal",
                code="plugin_inventory_revision_conflict",
                path=owner.path,
            )
        return original_commit_update(owner, mutation)  # type: ignore[arg-type]

    monkeypatch.setattr(PluginDesiredStateLedger, "commit_update", refuse_before_cas)
    stderr = StringIO()
    assert (
        asyncio.run(
            run_cli(
                [
                    "--update-package",
                    str(built_v2["artifactPath"]),
                    "--package-scope",
                    "project",
                ],
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
        == 1
    )
    assert refused
    failure = json.loads(stderr.getvalue().splitlines()[-1])
    assert failure["operationKind"] == "A2"
    assert failure["committedRevision"] is None
    assert failure["stage"] != "desired_committed"
    assert not any("repair-handoff" in command for command in failure["nextCommands"])
    explained = _target_command(
        workspace, "--explain-plugin-operation", failure["operationId"]
    )
    assert explained["package"]["disposition"] == "committed"
    assert explained["managementDisposition"] == "failed"
    selected = _target_command(
        workspace, "--list-plugins", "--list-plugins-format", "json"
    )
    assert (
        next(item for item in selected if item["name"] == "reviewpack")["version"]
        == "1"
    )


@pytest.mark.skipif(os.name != "posix", reason="fenced data Product is POSIX")
def test_p0_public_target_refuses_pre_b_workspace_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "target"
    project_settings = workspace / ".loushang" / "settings.json"
    project_settings.parent.mkdir(parents=True, mode=0o700)
    project_settings.write_text(
        json.dumps({"plugin_sources": ["legacy-source"]}), encoding="utf-8"
    )
    source = tmp_path / "review" / "skills" / "review" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Review\n", encoding="utf-8")
    built = _author_command(
        [
            "build-coding-skill",
            str(source),
            "--plugin-id",
            "reviewpack",
            "--version",
            "1",
            "--output-dir",
            str(tmp_path / "dist"),
        ],
        capsys,
    )

    def snapshot() -> tuple[tuple[str, bytes | None], ...]:
        return tuple(
            sorted(
                (
                    path.relative_to(workspace).as_posix(),
                    path.read_bytes() if path.is_file() else None,
                )
                for path in workspace.rglob("*")
            )
        )

    before = snapshot()
    stderr = StringIO()
    for arguments in (
        built["targetInstallCommand"][1:],  # type: ignore[index]
        [
            f"--install-package={built['artifactPath']}",
            "--package-scope=project",
        ],
    ):
        result = asyncio.run(
            run_cli(
                arguments,
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
        assert result == 1
        assert "pre-B workspace is unsupported" in stderr.getvalue()
        assert snapshot() == before


@pytest.mark.skipif(os.name != "posix", reason="fenced data Product is POSIX")
def test_p0_public_uninstall_retirement_interruption_reports_committed_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "target"
    workspace.mkdir(mode=0o700)
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()
    source = tmp_path / "review" / "skills" / "review" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Review\n", encoding="utf-8")
    built = _author_command(
        [
            "build-coding-skill",
            str(source),
            "--plugin-id",
            "reviewpack",
            "--version",
            "1",
            "--output-dir",
            str(tmp_path / "dist"),
        ],
        capsys,
    )
    _target_command(workspace, *built["targetInstallCommand"][1:])  # type: ignore[index]
    _target_command(workspace, "--enable-plugin", "reviewpack")
    original_open_set = PluginRetirementSetLedger.open_set
    interrupted = False

    def interrupt_retirement(owner: object, intent: object) -> object:
        nonlocal interrupted
        if (
            not interrupted
            and intent.source_transition.committed_state.installation_key.plugin_id  # type: ignore[attr-defined]
            == "reviewpack"
        ):
            interrupted = True
            raise OSError("injected retirement handoff interruption")
        return original_open_set(owner, intent)  # type: ignore[arg-type]

    monkeypatch.setattr(PluginRetirementSetLedger, "open_set", interrupt_retirement)
    stdout = StringIO()
    stderr = StringIO()
    result = asyncio.run(
        run_cli(
            ["--uninstall-package", "reviewpack", "--package-scope", "project"],
            cwd=workspace,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )
    assert result == 1
    assert interrupted
    failure = json.loads(stderr.getvalue().splitlines()[-1])
    operation_id = failure["operationId"]
    assert failure["operationKind"] == "A1"
    assert failure["actorId"] == "coding:cli"
    assert failure["operationStatus"] == "running"
    assert failure["stage"] == "desired_absent"
    assert failure["desiredInventoryRevision"] >= 1
    assert failure["retirementEvidence"] == "incomplete"
    assert failure["nextCommands"][-1] == [
        "loushang",
        "--repair-plugin-desired-operation",
        operation_id,
    ]
    listing = _target_command(
        workspace, "--list-plugins", "--list-plugins-format", "json"
    )
    assert (
        next(item for item in listing if item["name"] == "reviewpack")["desiredState"]
        == "absent"
    )
    explained = _target_command(workspace, "--explain-plugin-operation", operation_id)
    assert explained["managementStatus"] == "observed"
    assert explained["managementProgressCode"] == "desired_state_committing"

    monkeypatch.setattr(PluginRetirementSetLedger, "open_set", original_open_set)
    repaired = _target_command(
        workspace, "--repair-plugin-desired-operation", operation_id
    )
    assert repaired["disposition"] == "replayed_pending"
    assert repaired["result"]["operation"]["result"]["disposition"] == "succeeded"
    settled = _target_command(workspace, "--explain-plugin-operation", operation_id)
    assert settled["managementDisposition"] == "succeeded"


@pytest.mark.skipif(os.name != "posix", reason="fenced data Product is POSIX")
def test_p0_public_update_retirement_interruption_reports_committed_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "target"
    workspace.mkdir(mode=0o700)
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()
    source = tmp_path / "review" / "skills" / "review" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Review\nVersion one.\n", encoding="utf-8")

    def build(version: str) -> dict[str, Any]:
        return _author_command(
            [
                "build-coding-skill",
                str(source),
                "--plugin-id",
                "reviewpack",
                "--version",
                version,
                "--output-dir",
                str(tmp_path / "dist"),
            ],
            capsys,
        )

    built_v1 = build("1")
    _target_command(workspace, *built_v1["targetInstallCommand"][1:])
    _target_command(workspace, "--enable-plugin", "reviewpack")
    source.write_text("# Review\nVersion two.\n", encoding="utf-8")
    built_v2 = build("2")
    original_open_set = PluginRetirementSetLedger.open_set
    interrupted = False

    def interrupt_retirement(owner: object, intent: object) -> object:
        nonlocal interrupted
        if (
            not interrupted
            and intent.source_transition.committed_state.selection.package_revision.plugin_version  # type: ignore[attr-defined]
            == "2"
        ):
            interrupted = True
            raise OSError("injected update retirement interruption")
        return original_open_set(owner, intent)  # type: ignore[arg-type]

    monkeypatch.setattr(PluginRetirementSetLedger, "open_set", interrupt_retirement)
    stderr = StringIO()
    assert (
        asyncio.run(
            run_cli(
                [
                    "--update-package",
                    str(built_v2["artifactPath"]),
                    "--package-scope",
                    "project",
                ],
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
        == 1
    )
    assert interrupted
    failure = json.loads(stderr.getvalue().splitlines()[-1])
    operation_id = failure["operationId"]
    assert failure["stage"] == "desired_committed"
    assert failure["committedRevision"]["version"] == "2"
    assert failure["desiredInventoryRevision"] >= 1
    assert failure["handoffEvidence"] == "incomplete"
    assert failure["nextCommands"][-1] == [
        "loushang-package-repair",
        "--workspace",
        str(workspace),
        "repair-handoff",
        operation_id,
    ]
    selected = _target_command(
        workspace, "--list-plugins", "--list-plugins-format", "json"
    )
    assert (
        next(item for item in selected if item["name"] == "reviewpack")["version"]
        == "2"
    )
    pending_explain = _target_command(
        workspace, "--explain-plugin-operation", operation_id
    )
    expected_repair = f"loushang-package-repair repair-handoff {operation_id}"
    assert pending_explain["operationKind"] == "a2_package"
    assert pending_explain["managementActorId"] == "product:coding"
    assert pending_explain["desiredCommitEvidence"] == "verified_transition"
    assert pending_explain["repairCommand"] == expected_repair
    from loushang.coding.plugin_management_read_sdk import (
        open_coding_plugin_management_read_client,
    )
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    sdk_explain = open_coding_plugin_management_read_client(
        workspace
    ).explain_operation(operation_id, correlation_id="test:pending-a2-sdk")
    assert sdk_explain["repairCommand"] == expected_repair
    tui_explain = asyncio.run(
        build_coding_ui_controller(
            session=object(), plugin_workspace=workspace
        ).dispatch(PromptIntent(text=f"/plugins explain {operation_id}"))
    )
    assert tui_explain.error_message is None
    assert expected_repair in (tui_explain.status_message or "")
    monkeypatch.setattr(PluginRetirementSetLedger, "open_set", original_open_set)
    from loushang.coding.cli.package_repair import main as repair_cli_main

    assert (
        repair_cli_main(["--workspace", str(workspace), "repair-handoff", operation_id])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "committed"
    explained = _target_command(workspace, "--explain-plugin-operation", operation_id)
    assert explained["handoffEvidence"] == "settled"
