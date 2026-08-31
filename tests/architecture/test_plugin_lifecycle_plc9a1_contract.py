from __future__ import annotations

import ast
from pathlib import Path

CONTRACT = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9a1-contract.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9-inventory.md"
)
INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
APPLICATION = Path("src/loushang/harness/plugin_management/application.py")
AUTHOR_SDK = Path("src/loushang/plugin/__init__.py")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_plc9a1_contract_and_new_owner_sites_are_indexed() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)

    assert index.count("(plugin-lifecycle-plc9a1-contract.md)") == 1
    assert "A1-1 is implemented" in contract
    assert "A1-2 and" in contract
    assert "A1-3 are accepted delivery slices" in contract
    assert "application.py::PluginManagementCommandApplication" in inventory
    assert "application.py::PluginManagementReadModelProjector" in inventory
    assert "application.py::PluginManagementSourceSnapshotV1" in inventory


def test_plc9a1_application_is_transport_neutral_and_projection_only() -> None:
    source = _source(APPLICATION)
    imports = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        value.startswith(
            (
                "loushang.coding",
                "loushang.harness.cli",
                "loushang.harness.host.rpc",
                "loushang.harness.config",
            )
        )
        for value in imports
    )
    for forbidden in (
        "PluginDesiredStateLedger(",
        "PluginManagementService(",
        "PluginManager(",
        "append_jsonl_record(",
        "journal_file_lock(",
        ".jsonl",
    ):
        assert forbidden not in source
    assert "class PluginManagementCommandPort(Protocol):" in source
    assert "class PluginManagementQueryPort(Protocol):" in source
    assert "class PluginManagementReadModelProjector:" in source


def test_plc9a1_does_not_widen_the_public_author_sdk() -> None:
    author_sdk = _source(AUTHOR_SDK)
    for symbol in (
        "PluginManagementCommandPort",
        "PluginManagementQueryPort",
        "PluginManagementReadModelProjector",
        "PluginManagementService",
        "PluginDesiredStateLedger",
    ):
        assert symbol not in author_sdk


def test_plc9a1_contract_keeps_later_authority_out_of_scope() -> None:
    contract = _source(CONTRACT)

    for boundary in (
        "RPC/UI/management SDK transport bindings (PLC9A2)",
        "Plugin-bound\n  Package acquisition (PLC9B)",
        "Worker/remote topologies",
        "artifact GC",
        "private\n  data deletion",
        "(PLC9E)",
    ):
        assert boundary in contract
