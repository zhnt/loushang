from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

APPHOST = Path("src/loushang/apphost")
APPSERVICE = Path("src/loushang/appservice")
APPHOST_CONTINUITY = APPHOST / "continuity.py"
CODING_CONTINUITY = Path("src/loushang/coding/hosted_continuity.py")
INVENTORY = Path(
    "docs/internals/architecture/apphost/"
    "durable-hosted-application-continuity-g13-entrypoint-inventory.json"
)
APPSERVICE_WORKFLOW = Path(".github/workflows/appservice-quality.yml")
APPHOST_WORKFLOW = Path(".github/workflows/apphost-quality.yml")


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
            normalized = tuple(item for item in base if item)
            if normalized:
                imported.add(".".join(normalized))
    return imported


def _has(imports: set[str], prefix: str) -> bool:
    return any(item == prefix or item.startswith(f"{prefix}.") for item in imports)


def test_G13_DEPENDENCY_DIRECTION_keeps_core_and_mechanism_owners_independent() -> None:
    apphost = _imports(APPHOST_CONTINUITY)
    assert _has(apphost, "loushang.apphost.application")
    assert _has(apphost, "loushang.appservice")
    assert _has(apphost, "loushang.appserver.client")
    for forbidden in (
        "loushang.coding",
        "loushang.harness",
        "loushang.hosting",
        "loushang.harnesstui",
        "loushang.tui",
    ):
        assert not _has(apphost, forbidden)

    coding = _imports(CODING_CONTINUITY)
    for required in (
        "loushang.apphost",
        "loushang.apphost.application",
        "loushang.apphost.continuity",
        "loushang.appservice",
        "loushang.coding.hosted_application",
    ):
        assert _has(coding, required)
    for forbidden in (
        "loushang.harness",
        "loushang.hosting",
        "loushang.harnesstui",
        "loushang.tui",
    ):
        assert not _has(coding, forbidden)

    for path in APPSERVICE.glob("continuity*.py"):
        imports = _imports(path)
        for forbidden in (
            "loushang.apphost",
            "loushang.coding",
            "loushang.harness",
            "loushang.hosting",
            "loushang.harnesstui",
            "loushang.tui",
        ):
            assert not _has(imports, forbidden), (path, forbidden)
    facade = _imports(APPHOST / "__init__.py")
    assert not _has(facade, "loushang.apphost.application")
    assert not _has(facade, "loushang.apphost.continuity")

    coding_tree = ast.parse(_read(CODING_CONTINUITY))
    open_once = next(
        node
        for node in ast.walk(coding_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_open_once"
    )
    open_source = ast.get_source_segment(_read(CODING_CONTINUITY), open_once)
    assert open_source is not None
    assert open_source.index("self._request.store.acquire(") < open_source.index(
        "AppHostCatalogV1.admit("
    )


def test_G13_NO_AUTHORITY_EXPANSION_has_no_transport_process_or_path_discovery() -> (
    None
):
    sources = "\n".join(
        _read(path)
        for path in (
            APPHOST_CONTINUITY,
            CODING_CONTINUITY,
            *sorted(APPSERVICE.glob("continuity*.py")),
        )
    )
    for forbidden in (
        "import socket",
        "import subprocess",
        "listen(",
        "accept(",
        "connect(",
        "os.environ",
        "os.getcwd",
        ".expanduser(",
        "PlatformPaths",
    ):
        assert forbidden not in sources

    scripts = tomllib.loads(_read(Path("pyproject.toml")))["project"]["scripts"]
    assert scripts["loushang"] == "loushang.coding.cli.__main__:main"
    assert scripts["loushang-tui"] == "loushang.coding.ui.cli:main"
    for path in (
        Path("src/loushang/coding/__init__.py"),
        Path("src/loushang/coding/bootstrap.py"),
        Path("src/loushang/coding/cli/__main__.py"),
        Path("src/loushang/coding/cli/application.py"),
        Path("src/loushang/coding/ui/cli.py"),
        Path("src/loushang/harnesstui/__init__.py"),
        Path("src/loushang/harnesstui/conversation/application_host.py"),
    ):
        source = _read(path)
        assert "hosted_continuity" not in source
        assert "apphost.continuity" not in source


def test_G13_INVENTORY_V6_is_exact_source_backed_and_default_dark() -> None:
    inventory = json.loads(_read(INVENTORY))
    assert inventory["inventoryVersion"] == 6
    assert inventory["activation"] == "explicit-durable-in-process-library-only"
    rows = {row["entrypointId"]: row for row in inventory["entries"]}
    assert set(rows) == {
        "appserver.client",
        "appserver.protocol",
        "appservice.runtime",
        "appservice.continuity-contract",
        "appservice.continuity-store",
        "appservice.continuity-recovery",
        "apphost.application",
        "apphost.continuity",
        "coding.apphost.canary",
        "coding.appservice-adapter",
        "coding.hosted-application",
        "coding.hosted-continuity",
        "coding.cli",
        "coding.sdk",
        "coding.tui",
        "harnesstui.embedded",
        "harnesstui.hosted-mux",
    }
    for row in rows.values():
        assert Path(row["source"]).is_file()
    for row_id in (
        "appservice.continuity-contract",
        "appservice.continuity-store",
        "appservice.continuity-recovery",
        "apphost.continuity",
        "coding.hosted-continuity",
    ):
        assert rows[row_id]["packagingBinding"] is None
        assert rows[row_id]["omissionOwner"] is None
    assert rows["coding.cli"]["omissionOwner"] == "current"
    assert rows["coding.tui"]["omissionOwner"] == "current"
    assert rows["coding.sdk"]["omissionOwner"] == "current"


def test_G13_NEW_OWNERS_remain_independently_reviewable() -> None:
    groups = {
        "appservice-continuity": tuple(APPSERVICE.glob("continuity*.py")),
        "apphost-continuity": (APPHOST_CONTINUITY,),
        "coding-continuity": (CODING_CONTINUITY,),
    }
    limits = {
        "appservice-continuity": 1_250,
        # G17's reviewed borrowed discovery getter and recovery passthrough
        # add seven lines to this exact file, not another lifecycle owner.
        "apphost-continuity": 675,
        "coding-continuity": 350,
    }
    for name, paths in groups.items():
        lines = sum(len(_read(path).splitlines()) for path in paths)
        assert lines <= limits[name], (name, lines, limits[name])


def test_G13_PLATFORM_GATES_retain_linux_macos_and_windows_evidence() -> None:
    appservice = _read(APPSERVICE_WORKFLOW)
    for platform in ("ubuntu-24.04", "macos-15", "windows-latest"):
        assert platform in appservice
    assert "make check-appservice" in appservice
    apphost = _read(APPHOST_WORKFLOW)
    assert "Prove G13 durable continuity on Windows" in apphost
    assert "hosted-application-g13-windows.xml" in apphost
