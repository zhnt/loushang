from __future__ import annotations

import ast
import json
import sys
import tomllib
from pathlib import Path

from tests.architecture._source_imports import resolved_imports

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
    return resolved_imports(path, include_members=False, reject_invalid_relative=False)


def _package_imports(root: Path) -> set[str]:
    return {imported for path in root.rglob("*.py") for imported in _imports(path)}


def _imports_prefix(imports: set[str], prefix: str) -> bool:
    return any(item == prefix or item.startswith(f"{prefix}.") for item in imports)


def test_G17_controller_borrows_only_appserver_semantics() -> None:
    imports = _imports(HARNESSTUI_MUX / "controller.py")
    assert {name for name in imports if name.startswith("loushang.appserver")} == {
        "loushang.appserver.client",
        "loushang.appserver.execution.client",
        "loushang.appserver.execution.recovery",
        "loushang.appserver.protocol",
    }


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
    for path in (
        APPSERVER / "ports.py",
        APPSERVER / "managed_mux_close.py",
        *sorted((APPSERVER / "protocol").glob("*.py")),
    ):
        for imported in _imports(path):
            if imported == "loushang.appserver" or imported.startswith(
                "loushang.appserver."
            ):
                continue
            assert imported.partition(".")[0] in sys.stdlib_module_names, (
                path,
                imported,
            )
    # G16 grants native IO to exactly its explicit local deployment adapter;
    # every contract, dispatcher, scope adapter and legacy route stays dark.
    combined = "\n".join(_read(path) for path in APPSERVER.rglob("*.py")
                         if path != APPSERVER / "local.py")
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
    assert consumers == {
        CODING_ADAPTER,
        Path("src/loushang/apphost/application.py"),
        Path("src/loushang/apphost/continuity.py"),
        Path("src/loushang/apphost/foreground.py"),
        Path("src/loushang/coding/hosted_application.py"),
        Path("src/loushang/coding/hosted_continuity.py"),
        Path("src/loushang/coding/hosted_bootstrap.py"),
        Path("src/loushang/coding/hosted_catalog.py"),
        Path("src/loushang/coding/hosted_execution.py"),
        Path("src/loushang/coding/hosted_resume.py"),
        Path("src/loushang/coding/hosted_session.py"),
        Path("src/loushang/coding/_hosted_execution_work.py"),
        # COD-KD-HMW-001: original guard/registry, no second execution owner.
        Path("src/loushang/coding/hosted_method.py"),
        Path("src/loushang/coding/_hosted_method_work.py"),
        # COD-KD-HG-001: original registry/guard drives one bounded Goal.
        Path("src/loushang/coding/hosted_goal.py"),
        Path("src/loushang/coding/_hosted_goal_work.py"),
        # COD-KD-HG-002: fixed repository command selection in that same guard.
        Path("src/loushang/coding/_hosted_repository_work.py"),
        Path("src/loushang/apphost/managed/bootstrap.py"),
        Path("src/loushang/apphost/managed/mux_creation.py"),
        Path("src/loushang/apphost/managed/mux_management.py"),
        Path("src/loushang/apphost/managed/mux_probe.py"),
        Path("src/loushang/coding/managed_local.py"),
        Path("src/loushang/coding/managed_bootstrap.py"),
        Path("src/loushang/coding/managed_catalog.py"),
    }
    assert {name for name in _imports(Path("src/loushang/apphost/managed/mux_probe.py"))
            if name.startswith("loushang.appservice")} == {"loushang.appservice.continuity"}
    assert {name for name in _imports(Path("src/loushang/coding/hosted_catalog.py"))
            if name.startswith("loushang.appservice")} == {
        "loushang.appservice.discovery_ports",
    }
    # The new capability is selected by its owner, never discovered by importing
    # a default Product or by altering the legacy Hosted Session port.
    for path in (
        CODING_ADAPTER,
        Path("src/loushang/coding/__init__.py"),
    ):
        assert "hosted_execution" not in _read(path)
    bootstrap = ast.parse(_read(Path("src/loushang/coding/hosted_bootstrap.py")))
    bootstrap_execution_imports = {
        node
        for node in ast.walk(bootstrap)
        if isinstance(node, ast.ImportFrom) and node.module == "hosted_execution"
    }
    bootstrap_guarded_imports = {
        imported
        for node in ast.walk(bootstrap)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "not managed_selection"
        for statement in node.body
        for imported in ast.walk(statement)
        if isinstance(imported, ast.ImportFrom)
        and imported.module == "hosted_execution"
    }
    assert len(bootstrap_execution_imports) == 1
    assert bootstrap_execution_imports == bootstrap_guarded_imports
    # The foreground owner may select the optional adapter, but only within
    # its explicit execution branch. Default construction must not import it.
    composition = ast.parse(_read(Path("src/loushang/coding/hosted_application.py")))
    execution_imports = {
        node for node in ast.walk(composition)
        if isinstance(node, ast.ImportFrom) and node.module == "hosted_execution"
    }
    guarded_imports = {
        imported for node in ast.walk(composition)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "self._execution"
        for statement in node.body for imported in ast.walk(statement)
        if isinstance(imported, ast.ImportFrom) and imported.module == "hosted_execution"
    }
    assert len(execution_imports) == 1
    assert execution_imports == guarded_imports


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
        Path("src/loushang/coding/cli/application.py"),
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
        "appservice-core": tuple(
            APPSERVICE / name
            for name in ("__init__.py", "client.py", "ports.py", "runtime.py")
        ),
        "appservice-continuity": tuple(APPSERVICE.glob("continuity*.py")),
        "appservice-managed-contract": (APPSERVICE / "managed_mux.py", APPSERVICE / "managed_mux_close.py"),
        "appserver-close-values": (APPSERVER / "managed_mux_close.py",),
        "coding-adapter": (CODING_ADAPTER,),
        "harnesstui-mux": tuple(
            HARNESSTUI_MUX / name for name in
            ("__init__.py", "controller.py", "model.py", "profile.py", "projection.py", "reducer.py")
        ),
    }
    limits = {
        # G17's independently reviewed optional discovery algebra/codec adds
        # 271 lines to this exact group; all protocol modules still count.
        # See hosted-session-workflow-g17.md, Reviewability Budget Supplement.
        # GUI's attachment-scoped model control adds 121 net lines to the
        # existing protocol/client group (6 client, 6 exports, 49 codec, 60 model).
        "appserver": 2_100 + 121,
        # LMUX M0 §60 reviewed ManagedCreate adds 170 net lines for the same
        # state lock/atomic continuity authority; all four core files still count.
        # LMUX M0 §72 keeps close coordination on the same state/continuity
        # owner; reviewed core is 1876 lines, including original core files.
        # Hosted capability routing and attachment-scoped model control share
        # this existing AppService core owner.
        "appservice-core": 1_961,
        # LMUX M0 §71 reviewed v3 close history adds 59 net lines to the
        # same continuity schema/recovery boundary; no owner split or activation.
        # LMUX M0 §73 reviewed recovery stays on the original Attempt/lease;
        # complete continuity group 1378 lines, two managed contracts 134.
        "appservice-continuity": 1_400,
        "appservice-managed-contract": 150,
        "appserver-close-values": 80,
        # Hosted execution plus redacted, session-local model control remain
        # isolated in the Coding AppService adapter.
        "coding-adapter": 470,
        # Stable execution recovery and explicit profile wiring from main.
        "harnesstui-mux": 688,
    }
    for name, paths in groups.items():
        lines = sum(len(_read(path).splitlines()) for path in paths)
        assert lines <= limits[name], (name, lines, limits[name])
    # The terminal owner has its own separately tested 1042-line budget;
    # do not move shell code into this semantic group or hide new files.
    assert {path.name for path in HARNESSTUI_MUX.glob("*.py")} == {
        *(path.name for path in groups["harnesstui-mux"]),
        "shell.py", "terminal.py", "_shell_tasks.py", "_shell_screen.py",
        "session_picker.py", "conversation_binding.py",
    }
