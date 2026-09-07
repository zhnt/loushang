from __future__ import annotations

import ast
import sys
from pathlib import Path

APPHOST = Path("src/loushang/apphost")
APPSERVER = Path("src/loushang/appserver")
CORE = {
    APPHOST / "__init__.py",
    APPHOST / "_ownership.py",
    APPHOST / "catalog.py",
    APPHOST / "contracts.py",
    APPHOST / "errors.py",
    APPHOST / "router.py",
    APPHOST / "runtime.py",
}
HOSTED = APPHOST / "hosted.py"
SCOPE = Path("docs/internals/architecture/apphost/README.md")
CONTRACT = Path("docs/internals/architecture/apphost/contract-model-a0.md")
APPSERVER_SCOPE = Path("docs/internals/architecture/appserver/README.md")
WORKFLOW = Path(".github/workflows/apphost-quality.yml")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    package = path.parent.relative_to("src").parts
    for node in ast.walk(ast.parse(_source(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            retained = len(package) - (node.level - 1) if node.level else 0
            base = (
                (*package[:retained], *(node.module or "").split("."))
                if node.level
                else tuple((node.module or "").split("."))
            )
            normalized = tuple(part for part in base if part)
            if normalized:
                imports.add(".".join(normalized))
            imports.update(
                ".".join((*normalized, alias.name)) for alias in node.names
            )
    return imports


def test_a0_3_core_is_stdlib_only_and_facade_exposes_no_optional_edge() -> None:
    assert {path for path in APPHOST.glob("*.py")} == CORE | {HOSTED}
    for path in CORE:
        for imported in _imports(path):
            if imported == "loushang.apphost" or imported.startswith(
                "loushang.apphost."
            ):
                continue
            assert imported.partition(".")[0] in sys.stdlib_module_names, (
                path,
                imported,
            )
    facade = _source(APPHOST / "__init__.py")
    facade_imports = _imports(APPHOST / "__init__.py")
    assert '"AppHostRuntimeV1"' in facade
    assert '"AppHostSessionLeaseV1"' in facade
    assert "loushang.apphost.hosted" not in facade_imports
    assert not any(item.startswith("loushang.appserver") for item in facade_imports)


def test_a0_3_has_one_private_runtime_route_and_catalog_execution_seam() -> None:
    router = _source(APPHOST / "router.py")
    catalog = _source(APPHOST / "catalog.py")
    runtime = _source(APPHOST / "runtime.py")
    assert "async def _prepare_runtime_resume_candidate(" in router
    assert "async def _prepare_runtime_create_candidate(" in router
    assert "async def _acquire_runtime_product(" in catalog
    assert "async def acquire_runtime_product(" not in catalog
    assert "self._router._prepare_runtime_resume_candidate(" in runtime
    assert "self._router._prepare_runtime_create_candidate(" in runtime
    assert "self._catalog._acquire_runtime_product(" not in runtime
    consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if "._acquire_runtime_product(" in _source(path)
    }
    assert consumers == {APPHOST / "router.py"}


def test_a0_3_registry_owns_single_flight_and_dependency_ordered_close() -> None:
    source = _source(APPHOST / "runtime.py")
    for proof in (
        "self._slots: dict[SessionBindingKeyV1, _LiveSlot]",
        "task = asyncio.create_task(self._build(route))",
        "await route.discard_current()",
        "await route.open_with(binding._admission)",
        "DependentCloseChain(",
        "await self._inflight_drained.wait()",
        "await self._all_drained.wait()",
        "await self._owner_chain.close()",
        "_ACTIVE_RUNTIME_CALLBACKS",
    ):
        assert proof in source
    assert "default_product" not in source
    assert "importlib" not in source
    assert "entry_points" not in source


def test_a0_4_hosted_binder_stays_wiring_only_after_g11_consumers() -> None:
    hosted_imports = _imports(HOSTED)
    assert "loushang.appserver.ports" in hosted_imports
    appserver_consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if path != HOSTED and not path.is_relative_to(APPSERVER)
        and any(
            item == "loushang.appserver"
            or item.startswith("loushang.appserver.")
            for item in _imports(path)
        )
    }
    for consumer in appserver_consumers:
        assert (
            consumer == Path("src/loushang/coding/appservice_adapter.py")
            or consumer.is_relative_to(Path("src/loushang/appservice"))
            or consumer.is_relative_to(Path("src/loushang/harnesstui/mux"))
        ), consumer
    hosted = _source(HOSTED)
    for forbidden in (
        ".session.",
        ".work.",
        ".projection.",
        ".interaction.",
        "listen(",
        "accept(",
        "subprocess",
        "loushang.hosting",
        "loushang.harness",
    ):
        assert forbidden not in hosted


def test_a0_4_appserver_ports_remain_contract_only_after_g11() -> None:
    ports = APPSERVER / "ports.py"
    imports = _imports(ports)
    for forbidden in (
        "loushang.apphost",
        "loushang.harness",
        "loushang.hosting",
        "asyncio",
        "socket",
    ):
        assert all(
            imported != forbidden and not imported.startswith(f"{forbidden}.")
            for imported in imports
        )
    combined = _source(ports)
    assert "async def " not in combined
    assert " def listen(" not in combined
    assert " def accept(" not in combined
    assert (APPSERVER / "protocol" / "__init__.py").is_file()
    assert (APPSERVER / "client.py").is_file()


def test_a0_3_a0_4_docs_and_quality_gate_are_current() -> None:
    scope = _source(SCOPE)
    contract = _source(CONTRACT)
    appserver = _source(APPSERVER_SCOPE)
    workflow = _source(WORKFLOW)
    assert "A0.3 adds:" in scope
    assert "A0.4 adds one optional" in scope
    assert "A0.3 Live Binding And Embedded Profile" in contract
    assert "A0.4 Hosted Binder" in contract
    assert "contract-only structural Product port bundle" in appserver
    assert "tests/architecture/test_apphost_a03_a04_architecture.py" in workflow
    assert "src/loushang/appserver" in workflow
