from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

import pytest

DESIGN = Path("docs/internals/architecture/apphost/installed-explicit-canary-g10.md")
INVENTORY = Path(
    "docs/internals/architecture/apphost/hosted-product-g9-entrypoint-inventory.json"
)
CANARY = Path("src/loushang/coding/apphost_canary.py")
CONTROL = Path("src/loushang/coding/_apphost_canary_control.py")
CLI_ADAPTER = Path("src/loushang/coding/cli/apphost.py")
CLI_ROOT = Path("src/loushang/coding/cli/__main__.py")
MACHINE_RESOURCES = Path("src/loushang/harness/machine_resources/control_plane.py")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    package = path.parent.relative_to("src").parts
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            retained = len(package) - (node.level - 1) if node.level else 0
            base = (
                (*package[:retained], *(node.module or "").split("."))
                if node.level
                else tuple((node.module or "").split("."))
            )
            normalized = tuple(part for part in base if part)
            if normalized:
                imported.add(".".join(normalized))
    return imported


@pytest.mark.parametrize(
    "_case",
    ("G10-INVENTORY-V3",),
    ids=("G10-INVENTORY-V3",),
)
def test_inventory_v3_records_one_explicit_canary_and_current_omission(
    _case: str,
) -> None:
    del _case
    inventory = json.loads(_read(INVENTORY))
    assert inventory["inventoryVersion"] == 3
    assert inventory["decision"] == "RETAIN"
    rows = {row["entrypointId"]: row for row in inventory["entries"]}
    assert rows["coding.apphost.canary"] == {
        "disposition": "explicit-hosting-canary",
        "entrypointId": "coding.apphost.canary",
        "importsComposition": True,
        "omissionOwner": None,
        "packagingBinding": "project.scripts.loushang",
        "source": CANARY.as_posix(),
        "supportStatus": "installed-subcommand",
        "surface": "canary",
    }
    assert rows["coding.cli"]["disposition"] == ("current-default-explicit-canary")
    assert rows["coding.cli"]["omissionOwner"] == "current"
    for entrypoint_id in ("coding.bootstrap", "coding.sdk", "coding.tui"):
        assert rows[entrypoint_id]["disposition"] == "current-only"
        assert rows[entrypoint_id]["omissionOwner"] == "current"
    scripts = tomllib.loads(_read(Path("pyproject.toml")))["project"]["scripts"]
    assert scripts["loushang"] == "loushang.coding.cli.__main__:main"
    assert scripts["loushang-tui"] == "loushang.coding.ui.cli:main"


@pytest.mark.parametrize(
    "_case",
    ("G10-DEPENDENCY-GRAPH",),
    ids=("G10-DEPENDENCY-GRAPH",),
)
def test_dependency_graph_has_only_the_accepted_product_owned_edges(
    _case: str,
) -> None:
    del _case
    assert {
        "loushang.apphost",
        "loushang.coding._apphost_canary_control",
        "loushang.coding.apphost_composition",
        "loushang.hosting",
    }.issubset(_imports(CANARY))
    assert {
        "loushang.foundation.platform_paths",
        "loushang.harness.journal",
    }.issubset(_imports(CONTROL))
    assert "loushang.coding.cli.apphost" in _imports(CLI_ROOT)
    assert "loushang.coding.apphost_canary" not in _imports(CLI_ROOT)

    adapter_tree = ast.parse(_read(CLI_ADAPTER), filename=str(CLI_ADAPTER))
    top_level_imports = {
        node.module
        for node in adapter_tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "loushang.coding.apphost_canary" not in top_level_imports
    lazy_function = next(
        node
        for node in adapter_tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_run_installed_canary"
    )
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "loushang.coding.apphost_canary"
        for node in ast.walk(lazy_function)
    )
    for root in (
        Path("src/loushang/coding/bootstrap.py"),
        Path("src/loushang/coding/__init__.py"),
        Path("src/loushang/coding/ui/cli.py"),
    ):
        source = _read(root)
        assert "apphost_canary" not in source
        assert "apphost_composition" not in source

    for package, forbidden in (
        (Path("src/loushang/apphost"), ("loushang.coding", "loushang.hosting")),
        (Path("src/loushang/hosting"), ("loushang.coding", "loushang.apphost")),
    ):
        for path in package.rglob("*.py"):
            imports = _imports(path)
            assert not any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in forbidden
                for name in imports
            )


def test_product_control_is_in_the_machine_resource_inventory() -> None:
    source = _read(MACHINE_RESOURCES)
    assert '"coding.apphost_canary.control"' in source
    assert 'paths.state\n            / "products"\n            / "coding"' in source
    assert "Coding Product canary control only; never generic cleanup" in source


def test_g10_implementation_status_and_gate_are_reconciled() -> None:
    design = _read(DESIGN)
    assert "- Implementation status: implemented — G10.0--G10.4 complete" in design
    assert "- Activation status: default-dark; explicit installed canary only" in design
    makefile = _read(Path("Makefile"))
    workflow = _read(Path(".github/workflows/apphost-quality.yml"))
    for source in (makefile, workflow):
        assert "tests/coding/test_apphost_canary.py" in source
        assert "tests/coding/test_cli_apphost.py" in source
        assert "test_hosted_product_g10_explicit_canary.py" in source
        assert "hosted-product-g10-evidence-manifest.json" in source
