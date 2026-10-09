"""Public local discovery keeps Plugin and native Resource evidence distinct."""

from __future__ import annotations

import asyncio
import json
import os
from io import StringIO
from pathlib import Path

import pytest

from loushang.coding.cli.application import run_cli
from loushang.coding.resource_runtime import CodingResourceLoader
from loushang.harness.config.agent import SettingsManager


def _discover(workspace: Path, *options: str) -> tuple[int, dict[str, object], str]:
    stdout, stderr = StringIO(), StringIO()
    code = asyncio.run(
        run_cli(
            ["--discover-local-plugins", "--discover-local-plugins-format", "json", *options],
            cwd=workspace,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def test_local_discovery_lists_native_resources_without_product_or_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill = workspace / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: review\ndescription: Review changes.\n---\n# Review\n",
        encoding="utf-8",
    )
    prompt = workspace / "prompts" / "audit.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Audit\n", encoding="utf-8")
    before = {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }

    code, document, stderr = _discover(workspace)

    assert code == 0 and not stderr
    assert document["discoveryVersion"] == 1
    assert document["disposition"] == "partial"
    assert document["sourceCompleteness"] == {
        "catalog": "complete",
        "product": "unavailable",
    }
    assert document["totalMatchingRowsKnown"] is False
    rows = document["rows"]
    assert isinstance(rows, list)
    native = [row for row in rows if row["identityKind"] == "native_resource"]
    assert {row["resourceKind"] for row in native} >= {"skill", "prompt"}
    assert all(row["pluginId"] is None for row in native)
    assert all(row["sourceClass"] == "project_local" for row in native)
    assert {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    } == before

    code, limited, _ = _discover(workspace, "--discover-local-limit", "1")
    assert code == 0
    assert limited["truncated"] is True
    assert limited["totalMatchingRows"] >= 2
    assert len(limited["rows"]) == 1
    code, filtered, _ = _discover(
        workspace, "--discover-local-kind", "skill", "--discover-local-query", "review"
    )
    assert code == 0
    assert len(filtered["rows"]) == 1
    assert filtered["rows"][0]["name"] == "review/SKILL.md"
    stdout, stderr = StringIO(), StringIO()
    assert asyncio.run(
        run_cli(
            ["--discover-local-plugins"],
            cwd=workspace,
            stdout=stdout,
            stderr=stderr,
        )
    ) == 0
    assert "scope=workspace" in stdout.getvalue()
    assert "catalog=selected" in stdout.getvalue()
    assert "product=not_checked" in stdout.getvalue()
    settings = SettingsManager(
        global_settings_path=tmp_path / "home" / "coding" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    settings.set_disabled_skills(("review",), scope="project")
    code, disabled, _ = _discover(workspace, "--discover-local-kind", "skill")
    assert code == 0
    [disabled_skill] = disabled["rows"]
    assert disabled_skill["enabled"] is False
    assert disabled_skill["nativeCatalogSelection"] == "not_selected"
    skill.unlink()
    code, removed, _ = _discover(workspace, "--discover-local-kind", "skill")
    assert code == 0
    assert removed["rows"] == []


def test_malformed_native_entry_keeps_readable_sibling_as_partial_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    unsafe = workspace / "skills" / "bad" / "SKILL.md"
    unsafe.parent.mkdir(parents=True)
    outside = workspace / "outside"
    outside.write_text("# Outside\n", encoding="utf-8")
    unsafe.symlink_to(outside)
    prompt = workspace / "prompts" / "okay.md"
    prompt.parent.mkdir()
    prompt.write_text("# Okay\n", encoding="utf-8")

    code, document, stderr = _discover(workspace)

    assert code == 0 and not stderr
    assert document["disposition"] == "partial"
    assert document["sourceCompleteness"]["catalog"] == "partial"
    assert "local_discovery_catalog_unavailable" in document["diagnosticCodes"]
    assert [row["name"] for row in document["rows"]] == ["okay.md"]
    [row] = document["rows"]
    assert row["discoveryEvidence"] == "fallback_metadata"
    assert row["candidateFingerprint"] is None
    assert row["nativeCatalogSelection"] == "not_checked"


def test_unavailable_workspace_blocks_versioned_inventory(tmp_path: Path) -> None:
    code, document, stderr = _discover(tmp_path / "missing")
    assert code == 1 and not stderr
    assert document["discoveryVersion"] == 1
    assert document["disposition"] == "blocked"
    assert document["rows"] == []
    assert document["diagnosticCodes"] == ["local_discovery_workspace_unavailable"]


def test_native_fallback_refuses_root_replacement_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loushang.coding import plugin_local_discovery as discovery

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    receipt = CodingResourceLoader(workspace_root=workspace).prepare_catalog_input_receipt(
        workspace
    )
    outside = tmp_path / "outside"
    (outside / "prompts").mkdir(parents=True)
    (outside / "prompts" / "leak.md").write_text("# Leak\n", encoding="utf-8")
    parked = tmp_path / "parked"
    original_open = os.open
    swapped = False

    def swap_at_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if path == workspace and not swapped:
            workspace.rename(parked)
            workspace.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(discovery.os, "open", swap_at_open)
    try:
        with pytest.raises(discovery._NativeFallbackAuthorityError):
            discovery._fallback_native_metadata(receipt)
    finally:
        monkeypatch.setattr(discovery.os, "open", original_open)
        if workspace.is_symlink():
            workspace.unlink()
            parked.rename(workspace)
    assert swapped
