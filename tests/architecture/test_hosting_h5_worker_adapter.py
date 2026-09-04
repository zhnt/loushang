from __future__ import annotations

import ast
import re
from pathlib import Path

SPECIFICATION = Path(
    "docs/internals/architecture/hosting/harness-worker-adapter-h5.md"
)
ADAPTER = Path("src/loushang/harness/worker/hosting_adapter.py")
SELECTION = Path("src/loushang/harness/worker/owner_selection.py")
SESSION = Path("src/loushang/harness/worker/session.py")
SUPERVISOR = Path("src/loushang/harness/worker/supervisor.py")
WORKER_ROOT = Path("src/loushang/harness/worker")
HARNESS_ROOT = Path("src/loushang/harness")


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    assert marker in text
    body = text.split(marker, maxsplit=1)[1]
    return body.split("\n## ", maxsplit=1)[0]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def test_h5_freezes_three_dark_slices_and_keeps_plc9c5_separate() -> None:
    specification = " ".join(SPECIFICATION.read_text(encoding="utf-8").split())

    for statement in (
        "H5a | aggregate `ManagedWorkerSessionLaunchPort`",
        "H5b | executable Current-owner versus Hosting-owner compatibility matrix",
        "H5c | explicit typed owner selection",
        "not PLC9C5 Product activation",
        "Current Harness Worker route remains unchanged",
        "no production Product composition",
        "sealed-descriptor transfer and Product/native activation remain separate gaps",
    ):
        assert statement in specification or statement in " ".join(
            Path("docs/internals/architecture/hosting/README.md")
            .read_text(encoding="utf-8")
            .split()
        )


def test_h5_compatibility_matrix_keeps_authority_gap_explicit() -> None:
    matrix = " ".join(
        _section(
            SPECIFICATION.read_text(encoding="utf-8"),
            "H5b Current Versus Hosting Compatibility Matrix",
        ).split()
    )
    for statement in (
        "mandatory Approval",
        "required Sandbox containment",
        "gap remains",
        "sealed executable and bound cwd",
        "not representable; production Hosting owner unavailable",
        "never retries the other port",
        "mutable path as a substitute",
        "use `close_fds=False`",
        "separately reviewed opaque preparation capability",
    ):
        assert statement in matrix or statement in SPECIFICATION.read_text(
            encoding="utf-8"
        )


def test_h5_conformance_inventory_is_complete_and_ordered() -> None:
    inventory = _section(
        SPECIFICATION.read_text(encoding="utf-8"), "Conformance Inventory"
    )
    assert tuple(re.findall(r"^\| `([^`]+)` \|", inventory, re.MULTILINE)) == (
        "H5-ADAPT-MAP",
        "H5-AGGREGATE",
        "H5-SUPERVISOR",
        "H5-CURRENT-COMPAT",
        "H5-SELECT",
        "H5-NO-FALLBACK",
        "H5-ROLLBACK",
        "H5-DIAGNOSTIC",
        "H5-NO-PRODUCT",
    )


def test_h5_code_uses_atomic_session_and_explicit_default_current() -> None:
    adapter = ADAPTER.read_text(encoding="utf-8")
    selection = SELECTION.read_text(encoding="utf-8")
    session = SESSION.read_text(encoding="utf-8")
    supervisor = SUPERVISOR.read_text(encoding="utf-8")

    for statement in (
        "ChildSessionHostingPort",
        "ChildSessionRequest(process=process_request)",
        "stdin=ProcessStdinMode.CLOSED",
        "stdout=ProcessStdoutMode.DISCARD",
        "effective_environment=()",
    ):
        assert statement in adapter
    for statement in (
        'owner: WorkerSessionOwner = "current"',
        "return await port.start(",
        "rollback_to_current",
    ):
        assert statement in selection
    assert "await self._session.close()" in adapter
    assert "await self._endpoint.close()" not in adapter
    assert "os.environ" not in adapter
    assert "getenv" not in adapter
    assert "os.environ" not in selection
    assert "getenv" not in selection
    assert "ManagedWorkerSessionLaunchPort" in session
    assert "async def start_session(" in supervisor
    assert "bind_current_worker_session_port(" in supervisor


def test_h5_adapter_is_not_composed_by_non_worker_production_modules() -> None:
    forbidden_names = {
        "HostingManagedWorkerSessionAdapter",
        "WorkerHostingActivationV1",
        "WorkerSessionOwnerRouter",
    }
    consumers: set[Path] = set()
    for path in HARNESS_ROOT.rglob("*.py"):
        if path.is_relative_to(WORKER_ROOT):
            continue
        source = path.read_text(encoding="utf-8")
        if any(name in source for name in forbidden_names):
            consumers.add(path)
    assert consumers == set()

    # The dark consumer dependency points inward; Hosting remains independent.
    hosting_imports = {
        imported
        for path in Path("src/loushang/hosting").rglob("*.py")
        for imported in _imports(path)
    }
    assert not any(imported.startswith("loushang.harness") for imported in hosting_imports)
