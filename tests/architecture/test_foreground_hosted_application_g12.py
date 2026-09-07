from __future__ import annotations

import ast
import json
import sys
import tomllib
from pathlib import Path

APPHOST = Path("src/loushang/apphost")
APPHOST_APPLICATION = APPHOST / "application.py"
APPHOST_CORE = {
    APPHOST / "__init__.py",
    APPHOST / "_ownership.py",
    APPHOST / "catalog.py",
    APPHOST / "contracts.py",
    APPHOST / "errors.py",
    APPHOST / "router.py",
    APPHOST / "runtime.py",
}
CODING_APPLICATION = Path("src/loushang/coding/hosted_application.py")
HARNESSTUI_MUX = Path("src/loushang/harnesstui/mux")
INVENTORY = Path(
    "docs/internals/architecture/apphost/"
    "foreground-hosted-application-g12-entrypoint-inventory.json"
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
    return {item for path in root.glob("*.py") for item in _imports(path)}


def _imports_prefix(imports: set[str], prefix: str) -> bool:
    return any(item == prefix or item.startswith(f"{prefix}.") for item in imports)


def test_G12_OPTIONAL_EDGE_keeps_apphost_core_and_facade_independent() -> None:
    for path in APPHOST_CORE:
        imports = _imports(path)
        for imported in imports:
            if imported == "loushang.apphost" or imported.startswith(
                "loushang.apphost."
            ):
                continue
            assert imported.partition(".")[0] in sys.stdlib_module_names, (
                path,
                imported,
            )
    facade_imports = _imports(APPHOST / "__init__.py")
    assert not _imports_prefix(facade_imports, "loushang.apphost.application")
    application_imports = _imports(APPHOST_APPLICATION)
    assert _imports_prefix(application_imports, "loushang.appservice")
    assert _imports_prefix(application_imports, "loushang.appserver.client")
    for forbidden in (
        "loushang.coding",
        "loushang.harness",
        "loushang.hosting",
        "loushang.harnesstui",
        "loushang.tui",
    ):
        assert not _imports_prefix(application_imports, forbidden)
    application = _read(APPHOST_APPLICATION)
    for forbidden in ("socket", "subprocess", "listen(", "accept(", "connect("):
        assert forbidden not in application


def test_G12_CANONICAL_ROUTING_carries_and_fences_create_identity() -> None:
    contracts = _read(APPHOST / "contracts.py")
    router = _read(APPHOST / "router.py")
    coding = _read(CODING_APPLICATION)
    for field in ("requested_continuity_id", "requested_scope"):
        assert field in contracts
        assert field in router
        assert field in coding
    create = next(
        node
        for node in ast.walk(ast.parse(router))
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_prepare_runtime_create_candidate"
    )
    create_source = ast.get_source_segment(router, create)
    assert create_source is not None
    assert create_source.index("_validate_created_projection(") < (
        create_source.index("_RuntimeCandidateRoute(")
    )


def test_G12_FOREGROUND_PRODUCT_has_only_reviewed_dependencies() -> None:
    imports = _imports(CODING_APPLICATION)
    for required in (
        "loushang.apphost",
        "loushang.apphost.application",
        "loushang.appservice",
        "loushang.coding.appservice_adapter",
    ):
        assert _imports_prefix(imports, required)
    for forbidden in (
        "loushang.hosting",
        "loushang.harnesstui",
        "loushang.tui",
        "loushang.coding.apphost_composition",
        "loushang.coding.apphost_product",
    ):
        assert not _imports_prefix(imports, forbidden)
    source = _read(CODING_APPLICATION)
    for forbidden in ("socket", "subprocess", "listen(", "accept(", "connect("):
        assert forbidden not in source


def test_G12_CLIENT_ONLY_TUI_preserves_the_client_only_mux_boundary() -> None:
    imports = _package_imports(HARNESSTUI_MUX)
    assert _imports_prefix(imports, "loushang.appserver.client")
    for forbidden in (
        "loushang.appservice",
        "loushang.apphost",
        "loushang.hosting",
        "loushang.harness",
        "loushang.coding",
    ):
        assert not _imports_prefix(imports, forbidden)


def test_G12_EXPLICIT_ACTIVATION_preserves_installed_omission_routes() -> None:
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
        assert "coding.hosted_application" not in source
        assert "apphost.application" not in source


def test_G12_INVENTORY_V5_is_exact_source_backed_and_default_dark() -> None:
    inventory = json.loads(_read(INVENTORY))
    assert inventory["inventoryVersion"] == 5
    assert inventory["activation"] == "explicit-foreground-in-process-only"
    rows = {row["entrypointId"]: row for row in inventory["entries"]}
    assert set(rows) == {
        "appserver.client",
        "appserver.protocol",
        "appservice.runtime",
        "apphost.application",
        "coding.apphost.canary",
        "coding.appservice-adapter",
        "coding.hosted-application",
        "coding.cli",
        "coding.sdk",
        "coding.tui",
        "harnesstui.embedded",
        "harnesstui.hosted-mux",
    }
    for row in rows.values():
        assert Path(row["source"]).is_file()
    assert rows["apphost.application"]["packagingBinding"] is None
    assert rows["coding.hosted-application"]["packagingBinding"] is None
    assert rows["coding.cli"]["omissionOwner"] == "current"
    assert rows["coding.tui"]["omissionOwner"] == "current"
    assert rows["coding.sdk"]["omissionOwner"] == "current"


def test_g12_new_owners_remain_independently_reviewable() -> None:
    limits = {
        APPHOST_APPLICATION: 450,
        CODING_APPLICATION: 750,
    }
    for path, limit in limits.items():
        lines = len(_read(path).splitlines())
        assert lines <= limit, (path, lines, limit)
