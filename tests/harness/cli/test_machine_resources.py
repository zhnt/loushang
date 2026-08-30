from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

from loushang.foundation.platform_paths import PlatformPaths
from loushang.harness.cli import (
    extract_machine_resource_argv,
    run_machine_resource_command,
)
from loushang.harness.conversation import ConversationHeader
from loushang.harness.transcript.jsonl_file import write_agent_transcript_export


def _paths(tmp_path: Path) -> PlatformPaths:
    home = tmp_path / "home" / ".loushang"
    return PlatformPaths(
        home=home,
        data=home / "data",
        state=home / "state",
        cache=home / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "temporary",
    )


def _run(tmp_path: Path, *argv: str):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = asyncio.run(
        run_machine_resource_command(
            argv,
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path / "project",
            platform_paths=_paths(tmp_path),
        )
    )
    return code, stdout.getvalue(), stderr.getvalue()


def test_extract_machine_resource_command_preserves_leading_cwd() -> None:
    assert extract_machine_resource_argv(("storage", "paths")) == ("paths",)
    assert extract_machine_resource_argv(
        ("--cwd", "/workspace", "storage", "status")
    ) == ("--cwd", "/workspace", "status")
    assert extract_machine_resource_argv(("chat",)) is None


def test_machine_resource_paths_and_status_support_json(tmp_path: Path) -> None:
    code, output, error = _run(tmp_path, "paths", "--format", "json")

    assert code == 0
    assert error == ""
    paths = json.loads(output)
    assert paths["schemaVersion"] == 1
    assert paths["cwd"] == str((tmp_path / "project").resolve())
    assert any(
        item["resourceId"] == "session_assets.global" for item in paths["resources"]
    )

    code, output, error = _run(tmp_path, "status", "--format", "json")
    assert code == 0
    assert error == ""
    status = json.loads(output)
    assert status["schemaVersion"] == 1
    assert status["totalBytes"] == 0
    assert all(item["state"] == "missing" for item in status["resources"])


def test_machine_resource_clean_requires_apply_to_mutate(tmp_path: Path) -> None:
    diagnostics = _paths(tmp_path).state / "diagnostics"
    diagnostics.mkdir(parents=True)
    archive = diagnostics / "loushang-diag-old.zip"
    archive.write_bytes(b"archive")

    code, output, error = _run(
        tmp_path,
        "clean",
        "--target",
        "diagnostics",
        "--format",
        "json",
    )

    assert code == 0
    assert error == ""
    assert json.loads(output)["applied"] is False
    assert archive.exists()
    code, output, error = _run(
        tmp_path,
        "clean",
        "--target",
        "diagnostics",
        "--apply",
        "--format",
        "json",
    )
    assert code == 0
    assert error == ""
    assert json.loads(output)["reports"][0]["removed"] == 1
    assert not archive.exists()


def test_machine_resource_usage_errors_do_not_exit_process(tmp_path: Path) -> None:
    code, output, error = _run(tmp_path, "clean", "--target", "sessions")

    assert code == 2
    assert output == ""
    assert "invalid choice" in error


def test_machine_resource_migrate_previews_then_copies(tmp_path: Path) -> None:
    source_dir = tmp_path / "project" / ".loushang" / "sessions"
    source_dir.mkdir(parents=True)
    source = source_dir / "legacy.jsonl"
    write_agent_transcript_export(
        source,
        ConversationHeader(
            conversation_id="legacy",
            version=1,
            created_at="2026-08-27T00:00:00Z",
            metadata={"cwd": "/workspace"},
        ),
        [],
    )

    code, output, error = _run(tmp_path, "migrate", "--format", "json")

    assert code == 0
    assert error == ""
    preview = json.loads(output)
    assert preview["schemaVersion"] == 1
    assert preview["applied"] is False
    assert len(preview["candidates"]) == 1
    assert not Path(preview["candidates"][0]["destination"]).exists()

    code, output, error = _run(
        tmp_path,
        "migrate",
        "--apply",
        "--format",
        "json",
    )

    assert code == 0
    assert error == ""
    applied = json.loads(output)
    assert applied["schemaVersion"] == 1
    assert applied["results"][0]["disposition"] == "migrated"
    assert source.exists()
    assert Path(applied["results"][0]["destination"]).exists()


def test_machine_resource_migrate_apply_reports_planning_rejection(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "project" / ".loushang" / "sessions"
    source_dir.mkdir(parents=True)
    (source_dir / "corrupt.jsonl").write_text("not-json\n", encoding="utf-8")

    code, output, error = _run(
        tmp_path,
        "migrate",
        "--apply",
        "--format",
        "json",
    )

    assert code == 1
    assert error == ""
    assert json.loads(output)["diagnostics"][0]["code"] == "source_rejected"
