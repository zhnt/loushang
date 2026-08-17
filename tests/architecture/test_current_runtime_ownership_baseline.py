from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path("src/loushang")
HARNESS_DOC_ROOT = Path("docs/internals/architecture/harness")


def _loushang_dependencies(package: str) -> set[str]:
    dependencies: set[str] = set()
    for source_path in (SOURCE_ROOT / package).rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("loushang."):
                    dependencies.add(module.split(".", 2)[1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("loushang."):
                        dependencies.add(alias.name.split(".", 2)[1])
    dependencies.discard(package)
    return dependencies


def test_current_top_level_runtime_dependency_direction() -> None:
    harness_dependencies = _loushang_dependencies("harness")
    harnesswork_dependencies = _loushang_dependencies("harnesswork")
    harnesstui_dependencies = _loushang_dependencies("harnesstui")
    work_dependencies = _loushang_dependencies("work")
    channel_dependencies = _loushang_dependencies("channel")
    coding_dependencies = _loushang_dependencies("coding")

    assert harness_dependencies.isdisjoint(
        {"channel", "work", "harnesswork", "harnesstui", "coding"}
    )
    assert harnesswork_dependencies.isdisjoint(
        {"channel", "work", "harnesstui", "coding"}
    )
    assert "harness" in harnesswork_dependencies
    assert harnesstui_dependencies.isdisjoint({"channel", "work", "coding"})
    assert "harness" in harnesstui_dependencies

    assert work_dependencies.isdisjoint({"channel", "harnesstui", "coding"})
    assert work_dependencies == {"harnesswork"}

    assert channel_dependencies.isdisjoint({"harnesstui", "coding"})
    assert {"harness", "harnesswork"} <= channel_dependencies

    assert {"channel", "harness", "harnesswork", "harnesstui"} <= coding_dependencies


def test_retired_product_sources_and_distinct_jsonl_owners_stay_retired() -> None:
    assert not tuple((SOURCE_ROOT / "coding/policy").glob("*.py"))
    assert not tuple((SOURCE_ROOT / "coding/mode").glob("*.py"))

    product_rpc_root = SOURCE_ROOT / "harness/host/rpc"
    channel_rpc_path = SOURCE_ROOT / "channel/rpc_jsonl.py"
    assert product_rpc_root.is_dir()
    assert not (SOURCE_ROOT / "harness/host/rpc.py").exists()
    assert channel_rpc_path.is_file()

    product_rpc_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in product_rpc_root.rglob("*.py")
    )
    channel_rpc_source = channel_rpc_path.read_text(encoding="utf-8")
    assert "loushang.channel" not in product_rpc_source
    assert "loushang.harness.host.rpc" not in channel_rpc_source


def test_current_owner_documents_do_not_restore_superseded_claims() -> None:
    rebaseline = (HARNESS_DOC_ROOT / "coding-shared-layer-owner-rebaseline.md").read_text(
        encoding="utf-8"
    )
    inventory = (
        HARNESS_DOC_ROOT / "coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    mode_boundary = (HARNESS_DOC_ROOT / "mode-host-boundary.md").read_text(
        encoding="utf-8"
    )
    rpc_boundary = (
        HARNESS_DOC_ROOT / "session-rpc-operation-boundary.md"
    ).read_text(encoding="utf-8")

    assert "Current Top-Level Dependency Direction" in rebaseline
    assert "Product command JSONL" in rebaseline
    assert "`coding.policy` | Product adapter" not in inventory
    assert "No Coding policy compatibility package remains." in inventory
    assert "There are two independent JSONL vocabularies." in mode_boundary
    assert "There is no `RpcMode` or `PrintMode` Product adapter." in mode_boundary
    assert "Product RPC And Channel Are Separate" in rpc_boundary
    assert "`coding.mode.rpc_mode.RpcMode` is" not in rpc_boundary
