"""Public local discovery keeps Plugin and native Resource evidence distinct."""

from __future__ import annotations

import asyncio
import json
import os
from io import StringIO
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.cli.application import run_cli
from loushang.coding.cli.package_cutover import main as cutover_cli_main
from loushang.coding.package_product_preview import (
    CodingFencedProductReadOnlyPreviewOwner,
)
from loushang.coding.resource_runtime import CodingResourceLoader
from loushang.harness.config.agent import SettingsManager
from loushang.plugin.__main__ import main as author_cli_main


def _discover(workspace: Path, *options: str) -> tuple[int, dict[str, object], str]:
    stdout, stderr = StringIO(), StringIO()
    code = asyncio.run(
        run_cli(
            [
                "--discover-local-plugins",
                "--discover-local-plugins-format",
                "json",
                *options,
            ],
            cwd=workspace,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def _product_command(workspace: Path, *options: str) -> dict[str, object]:
    stdout, stderr = StringIO(), StringIO()
    code = asyncio.run(
        run_cli(
            list(options),
            cwd=workspace,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )
    assert code == 0, stderr.getvalue()
    output = stdout.getvalue().strip()
    return json.loads(output) if output.startswith("{") else {}


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, int, bytes | None], ...]:
    return tuple(
        sorted(
            (
                str(path.relative_to(root)),
                path.lstat().st_mode,
                path.lstat().st_mtime_ns,
                path.read_bytes() if path.is_file() and not path.is_symlink() else None,
            )
            for path in root.rglob("*")
        )
    )


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
    assert (
        asyncio.run(
            run_cli(
                ["--discover-local-plugins"],
                cwd=workspace,
                stdout=stdout,
                stderr=stderr,
            )
        )
        == 0
    )
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
    receipt = CodingResourceLoader(
        workspace_root=workspace
    ).prepare_catalog_input_receipt(workspace)
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


@pytest.mark.skipif(os.name != "posix", reason="fenced data Product is POSIX")
def test_public_discovery_keeps_same_name_native_and_installed_rows_when_source_stales(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    assert cutover_cli_main(["--workspace", str(workspace)]) == 0
    capsys.readouterr()

    source = tmp_path / "author" / "skills" / "review" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\nname: review\ndescription: Review changes.\n---\n# External review\n",
        encoding="utf-8",
    )
    assert (
        author_cli_main(
            [
                "build-coding-skill",
                str(source),
                "--plugin-id",
                "reviewpack",
                "--version",
                "1",
                "--output-dir",
                str(tmp_path / "dist"),
            ]
        )
        == 0
    )
    built = json.loads(capsys.readouterr().out)
    installed = _product_command(
        workspace,
        "--install-package",
        built["artifactPath"],
        "--package-scope",
        "project",
    )
    assert installed["pluginId"] == "reviewpack"
    _product_command(workspace, "--enable-plugin", "reviewpack")

    native = workspace / "skills" / "review" / "SKILL.md"
    native.parent.mkdir(parents=True)
    native.write_text(
        "---\nname: review\ndescription: Native review.\n---\n# Native review\n",
        encoding="utf-8",
    )
    before = _tree_snapshot(tmp_path)
    code, document, stderr = _discover(workspace, "--discover-local-kind", "skill")
    assert code == 0 and not stderr
    assert _tree_snapshot(tmp_path) == before
    rows = document["rows"]
    assert isinstance(rows, list)
    plugin_rows = [
        row
        for row in rows
        if row["identityKind"] == "plugin_installation"
        and row["pluginId"] == "reviewpack"
    ]
    native_rows = [
        row
        for row in rows
        if row["identityKind"] == "native_resource" and row["name"] == "review/SKILL.md"
    ]
    assert len(plugin_rows) == len(native_rows) == 1
    assert plugin_rows[0]["pluginId"] == "reviewpack"
    assert plugin_rows[0]["resourceKinds"] == ["skill"]
    assert plugin_rows[0]["packageRevisionFingerprint"]
    assert plugin_rows[0]["productSelection"] == "projected"
    assert plugin_rows[0]["productAdmission"] == "not_checked"
    assert native_rows[0]["pluginId"] is None
    assert native_rows[0]["name"] == "review/SKILL.md"
    assert native_rows[0]["candidateFingerprint"]
    assert native_rows[0]["resourceIdentity"]

    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as owner:
        [binding] = [
            item for item in owner.policy.bindings if item.plugin_id == "reviewpack"
        ]
        captured = Path(binding.source_identity)
    original = captured.read_bytes()
    try:
        for damaged in (b"changed after Product capture", None):
            if damaged is None:
                captured.unlink()
            else:
                captured.write_bytes(damaged)
            before = _tree_snapshot(tmp_path)
            code, stale, stderr = _discover(workspace, "--discover-local-kind", "skill")
            assert code == 0 and not stderr
            assert _tree_snapshot(tmp_path) == before
            assert stale["disposition"] == "partial"
            assert stale["sourceCompleteness"]["product"] == "partial"
            stale_rows = stale["rows"]
            assert isinstance(stale_rows, list)
            assert any(row["identityKind"] == "native_resource" for row in stale_rows)
            plugins = [
                row
                for row in stale_rows
                if row["identityKind"] == "plugin_installation"
                and row["pluginId"] == "reviewpack"
            ]
            assert all(
                plugin["productSelection"] != "selected"
                and plugin["productAdmission"] != "observed_in_preview"
                for plugin in plugins
            )
            assert {
                "local_discovery_product_stale",
                "local_discovery_source_unavailable",
            } <= set(stale["diagnosticCodes"])
            if damaged is not None:
                captured.write_bytes(original)
    finally:
        captured.write_bytes(original)
