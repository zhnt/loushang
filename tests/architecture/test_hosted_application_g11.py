from __future__ import annotations

import ast
import json
import sys
import tomllib
from pathlib import Path

APPSERVER = Path("src/loushang/appserver")
APPSERVICE = Path("src/loushang/appservice")
CODING_ADAPTER = Path("src/loushang/coding/appservice_adapter.py")
HARNESSTUI_MUX = Path("src/loushang/harnesstui/mux")
INVENTORY = Path(
    "docs/internals/architecture/appserver/"
    "hosted-application-g11-entrypoint-inventory.json"
)


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


def _package_imports(root: Path) -> set[str]:
    return {
        imported
        for path in root.rglob("*.py")
        for imported in _imports(path)
    }


def _imports_prefix(imports: set[str], prefix: str) -> bool:
    return any(item == prefix or item.startswith(f"{prefix}.") for item in imports)


def test_G11_DEPENDENCY_GRAPH_appserver_remains_contract_and_client_only() -> None:
    imports = _package_imports(APPSERVER)
    for forbidden in (
        "loushang.appservice",
        "loushang.apphost",
        "loushang.hosting",
        "loushang.harness",
        "loushang.coding",
        "loushang.harnesstui",
        "loushang.tui",
    ):
        assert not _imports_prefix(imports, forbidden)
    for path in (APPSERVER / "ports.py", *sorted((APPSERVER / "protocol").glob("*.py"))):
        for imported in _imports(path):
            if imported == "loushang.appserver" or imported.startswith(
                "loushang.appserver."
            ):
                continue
            assert imported.partition(".")[0] in sys.stdlib_module_names, (
                path,
                imported,
            )
    combined = "\n".join(_read(path) for path in APPSERVER.rglob("*.py"))
    for forbidden in ("socket", "subprocess", "listen(", "accept(", "connect("):
        assert forbidden not in combined


def test_G11_DEPENDENCY_GRAPH_appservice_is_product_and_process_neutral() -> None:
    imports = _package_imports(APPSERVICE)
    assert _imports_prefix(imports, "loushang.appserver")
    for forbidden in (
        "loushang.apphost",
        "loushang.hosting",
        "loushang.harness",
        "loushang.coding",
        "loushang.harnesstui",
        "loushang.tui",
    ):
        assert not _imports_prefix(imports, forbidden)
    combined = "\n".join(_read(path) for path in APPSERVICE.rglob("*.py"))
    for forbidden in ("socket", "subprocess", "listen(", "accept(", "connect("):
        assert forbidden not in combined


def test_G11_PRODUCT_ADAPTER_is_the_only_product_harness_bridge() -> None:
    imports = _imports(CODING_ADAPTER)
    assert _imports_prefix(imports, "loushang.appservice")
    assert "loushang.apphost" in imports
    assert "loushang.harness.events" in imports
    assert "loushang.harness.session" in imports
    for forbidden in (
        "loushang.hosting",
        "loushang.harness.session.facade",
        "loushang.harness.session.runtime",
    ):
        assert not _imports_prefix(imports, forbidden)
    consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if not path.is_relative_to(APPSERVICE)
        and _imports_prefix(_imports(path), "loushang.appservice")
    }
    assert consumers == {CODING_ADAPTER}


def test_G11_HOSTED_PROFILE_depends_on_client_contract_not_service_or_product() -> None:
    imports = _package_imports(HARNESSTUI_MUX)
    assert _imports_prefix(imports, "loushang.appserver.client")
    assert _imports_prefix(imports, "loushang.appserver.protocol")
    for forbidden in (
        "loushang.appservice",
        "loushang.apphost",
        "loushang.hosting",
        "loushang.harness",
        "loushang.coding",
    ):
        assert not _imports_prefix(imports, forbidden)


def test_G11_EMBEDDED_OMISSION_preserves_every_installed_current_route() -> None:
    scripts = tomllib.loads(_read(Path("pyproject.toml")))["project"]["scripts"]
    assert scripts["loushang"] == "loushang.coding.cli.__main__:main"
    assert scripts["loushang-tui"] == "loushang.coding.ui.cli:main"
    for path in (
        Path("src/loushang/coding/__init__.py"),
        Path("src/loushang/coding/bootstrap.py"),
        Path("src/loushang/coding/cli/__main__.py"),
        Path("src/loushang/coding/ui/cli.py"),
        Path("src/loushang/harnesstui/__init__.py"),
        Path("src/loushang/harnesstui/conversation/application_host.py"),
    ):
        source = _read(path)
        assert "appservice_adapter" not in source
        assert "loushang.appservice" not in source
        assert "loushang.harnesstui.mux" not in source


def test_G11_INVENTORY_V4_is_source_backed_and_has_no_installed_hosted_route() -> None:
    inventory = json.loads(_read(INVENTORY))
    assert inventory["inventoryVersion"] == 4
    assert inventory["activation"] == "explicit-in-process-only"
    rows = {row["entrypointId"]: row for row in inventory["entries"]}
    assert set(rows) == {
        "appserver.client",
        "appserver.protocol",
        "appservice.runtime",
        "coding.apphost.canary",
        "coding.appservice-adapter",
        "coding.cli",
        "coding.sdk",
        "coding.tui",
        "harnesstui.embedded",
        "harnesstui.hosted-mux",
    }
    for row in rows.values():
        assert Path(row["source"]).is_file()
    for row_id in (
        "appserver.client",
        "appserver.protocol",
        "appservice.runtime",
        "coding.appservice-adapter",
        "harnesstui.hosted-mux",
    ):
        assert rows[row_id]["packagingBinding"] is None
    assert rows["coding.cli"]["omissionOwner"] == "current"
    assert rows["coding.tui"]["omissionOwner"] == "current"


def test_g11_package_budgets_keep_new_owners_reviewable() -> None:
    groups = {
        "appserver": tuple((APPSERVER / "protocol").glob("*.py"))
        + (APPSERVER / "client.py",),
        "appservice": tuple(APPSERVICE.glob("*.py")),
        "coding-adapter": (CODING_ADAPTER,),
        "harnesstui-mux": tuple(HARNESSTUI_MUX.glob("*.py")),
    }
    limits = {
        "appserver": 1_800,
        "appservice": 1_200,
        "coding-adapter": 400,
        "harnesstui-mux": 600,
    }
    for name, paths in groups.items():
        lines = sum(len(_read(path).splitlines()) for path in paths)
        assert lines <= limits[name], (name, lines, limits[name])
