from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import pytest

from loushang.harness.resources.plugins.declarations import (
    PLUGIN_DECLARATION_DOCUMENT_VERSION,
    PLUGIN_DECLARATION_IR_VERSION,
    PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
    PluginContributionExecutionModel,
    PluginContributionReservation,
    PluginDeclarationCodecError,
    PluginDeclarationSource,
    PluginDeclarationSourceKind,
)

BASELINE = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c0-baseline.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9-inventory.md"
)
INDEX = Path("docs/internals/architecture/harness/plugin/README.md")

DECLARATIONS = Path("src/loushang/harness/resources/plugins/declarations.py")
PROCESS_HOST = Path("src/loushang/harness/workspace/process/host.py")
PROCESS_HOSTING = Path("src/loushang/harness/tools/process_hosting.py")
SANDBOX_RUNTIME = Path("src/loushang/harness/sandbox/runtime.py")
SKILL_ACTIONS = Path("src/loushang/harness/tools/skill_actions.py")
AUTHOR_SDK = Path("src/loushang/plugin/__init__.py")
AUTHOR_SDK_ROOT = Path("src/loushang/plugin")
PLUGIN_MANAGEMENT_ROOT = Path("src/loushang/harness/plugin_management")
HARNESS_ROOT = Path("src/loushang/harness")
WORKER_ROOT = HARNESS_ROOT / "worker"
WORKER_LAUNCH = WORKER_ROOT / "launch.py"
WORKER_PROTOCOL = WORKER_ROOT / "protocol.py"
WORKER_SUPERVISOR = WORKER_ROOT / "supervisor.py"
CAPABILITY_WORKER_ADAPTER = WORKER_ROOT / "capability_query.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, qualified_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    scope: list[str] = []

    def visit(node: ast.AST) -> str | None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.append(node.name)
            if ".".join(scope) == qualified_name:
                return ast.get_source_segment(source, node)
            for child in node.body:
                result = visit(child)
                if result is not None:
                    return result
            scope.pop()
            return None
        for child in ast.iter_child_nodes(node):
            result = visit(child)
            if result is not None:
                return result
        return None

    result = visit(tree)
    assert result is not None
    return result


def _imports_from_source(source: str, *, package: str) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
                imports.add(base)
                imports.update(
                    f"{base}.{alias.name}" if base else alias.name
                    for alias in node.names
                    if alias.name != "*"
                )
                continue
            package_parts = package.split(".")
            parent_count = node.level - 1
            assert parent_count < len(package_parts)
            resolved = package_parts[: len(package_parts) - parent_count]
            if node.module:
                resolved.extend(node.module.split("."))
                imports.add(".".join(resolved))
                imports.update(
                    ".".join((*resolved, alias.name))
                    for alias in node.names
                    if alias.name != "*"
                )
            else:
                imports.update(
                    ".".join((*resolved, alias.name)) for alias in node.names
                )
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


def _imports(path: Path) -> set[str]:
    module_parts = list(path.relative_to("src").with_suffix("").parts)
    module_parts.pop()
    return _imports_from_source(_source(path), package=".".join(module_parts))


def _if_conditions(function_source: str) -> set[str]:
    return {
        ast.unparse(node.test)
        for node in ast.walk(ast.parse(function_source))
        if isinstance(node, ast.If)
    }


def _bound_runtime_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(_source(path), filename=str(path))):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def test_plc9c0_baseline_is_indexed_and_names_the_complete_boundary() -> None:
    baseline = _source(BASELINE)
    inventory = _source(INVENTORY)
    index = _source(INDEX)

    assert index.count("(plugin-lifecycle-plc9c0-baseline.md)") == 1
    assert "Implementation base: `90f6a9de`" in baseline
    for owner in (
        "PluginContributionExecutionModel",
        "ScopeBoundProcessLauncher.start",
        "ScopeBoundProcessLauncher._start_managed",
        "SandboxExecutionRuntime.bind_process_launcher",
        "ManagedWorkerLaunchPort",
        "CapabilityComponentHost",
        "CapabilityOwnerComponentRuntime",
        "CapabilityOwnerComponentBinder",
        "PreparedResourceOwnerGeneration",
        "PluginContinuityProvider",
    ):
        assert owner in baseline
        assert owner in inventory
    for slice_name in (
        "PLC9C.0",
        "PLC9C1",
        "PLC9C2",
        "PLC9C3",
        "PLC9C4",
        "PLC9C5",
    ):
        assert slice_name in baseline


def test_plc9c0_freezes_the_current_inert_declaration_codec() -> None:
    assert PLUGIN_DECLARATION_IR_VERSION == 2
    assert PLUGIN_DECLARATION_DOCUMENT_VERSION == 1
    assert PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION == 3
    assert PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION == 3
    assert PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION == 2
    assert set(get_args(PluginContributionExecutionModel)) == {
        "data_only",
        "in_process",
        "local_worker",
    }
    assert set(get_args(PluginDeclarationSourceKind)) == {"document", "in_process"}

    reservation = PluginContributionReservation(
        contribution_id="worker-candidate",
        kind="capability_provider",
        owner="coding",
        declaration_source=PluginDeclarationSource.in_process(
            "provider.py:create_provider"
        ),
        contribution_execution_model="in_process",
        requested_authorities=(),
    ).to_dict()
    for model in ("local_worker", "remote_service"):
        candidate = dict(reservation)
        candidate["contributionExecutionModel"] = model
        with pytest.raises(PluginDeclarationCodecError) as caught:
            PluginContributionReservation.from_dict(candidate)
        assert caught.value.code == "unsupported_plugin_contribution_execution_model"

    declarations = _source(DECLARATIONS)
    assert "local_worker" in declarations
    assert "remote_service" not in declarations
    assert "subprocess" not in _imports(DECLARATIONS)
    assert "loushang.harness.workspace.process" not in _imports(DECLARATIONS)
    assert "loushang.harness.sandbox" not in _imports(DECLARATIONS)


def test_plc9c0_keeps_generic_and_private_managed_launch_paths_distinct() -> None:
    generic = _function_source(PROCESS_HOSTING, "ScopeBoundProcessLauncher.start")
    managed = _function_source(
        PROCESS_HOSTING,
        "ScopeBoundProcessLauncher._start_managed",
    )
    authority = _function_source(
        PROCESS_HOSTING,
        "ScopeBoundProcessLauncher._verify_managed_start_authority",
    )
    host_start = _function_source(PROCESS_HOST, "ProcessHost.start")
    composition = _function_source(
        SANDBOX_RUNTIME,
        "SandboxExecutionRuntime.bind_process_launcher",
    )
    worker_composition = _function_source(
        SANDBOX_RUNTIME,
        "SandboxExecutionRuntime.bind_managed_worker_launch_port",
    )
    worker_start = _function_source(WORKER_LAUNCH, "_ManagedWorkerLaunchPort.start")
    skill = _function_source(SKILL_ACTIONS, "execute_managed_skill_action")

    assert "managed process requests require the owner-only start path" in generic
    assert managed.index("self._verify_managed_start_authority()") < managed.index(
        "self._start_authorized("
    )
    conditions = _if_conditions(authority)
    assert "self._managed_owner_authority is None" in conditions
    assert "not self._scope.require_approval" in conditions
    assert "self.containment_requirement != 'required'" in conditions
    assert (
        host_start.index("self._reservations[reservation.reservation_id] = reservation")
        < host_start.index("containment = await containment_planner(request)")
        < host_start.index("transport = await self._spawner(")
    )
    assert "_bind_process_owner_launcher(" in composition
    assert "_claim_managed_process_owner_authority()" in composition
    assert "_verify_managed_process_plan" in composition
    assert worker_composition.index("_bind_process_owner_launcher(") < (
        worker_composition.index("_bind_managed_worker_launch_port(launcher)")
    )
    assert "_claim_managed_process_owner_authority()" in worker_composition
    assert "_verify_managed_process_plan" in worker_composition
    assert worker_start.count("request.validate_current()") == 2
    assert "_capture_sealed_process_executable(" in worker_start
    assert "_capture_bound_process_directory(" in worker_start
    assert "effective_environment=()" in worker_start
    assert "self._launcher._start_managed(" in worker_start
    assert "self._launcher.start(" not in worker_start
    assert "_managed_process_launch_request(" in skill
    assert "launcher._start_managed(" in skill


def test_plc9c1_through_c4_runtime_is_present_but_default_dark() -> None:
    harness_paths = tuple(HARNESS_ROOT.rglob("*.py"))
    source = "\n".join(_source(path) for path in harness_paths)

    assert "local_worker" in source
    assert "remote_service" not in source
    runtime_names = {
        name for path in harness_paths for name in _bound_runtime_names(path)
    }
    assert {
        "ManagedWorkerLaunchPort",
        "WorkerSupervisor",
        "WorkerProtocolMessage",
        "CapabilityQueryWorkerAdapter",
    }.issubset(runtime_names)
    adapter_binding = _function_source(
        CAPABILITY_WORKER_ADAPTER,
        "bind_capability_query_worker_adapter",
    )
    assert "enabled: bool = False" in adapter_binding
    assert "worker_disabled_by_policy" in adapter_binding
    worker_imports = {
        imported for path in WORKER_ROOT.rglob("*.py") for imported in _imports(path)
    }
    assert not any(
        imported.startswith(
            (
                "loushang.harness.plugin_management",
                "loushang.harness.capabilities.component_runtime",
            )
        )
        for imported in worker_imports
    )
    worker_consumers = {
        path
        for path in harness_paths
        if not path.is_relative_to(WORKER_ROOT)
        and any(
            imported.startswith("loushang.harness.worker")
            for imported in _imports(path)
        )
    }
    assert worker_consumers == {SANDBOX_RUNTIME}


def test_plc9c0_preserves_the_author_sdk_authority_firewall() -> None:
    author_sources = "\n".join(_source(path) for path in AUTHOR_SDK_ROOT.rglob("*.py"))
    author_imports = {
        imported
        for path in AUTHOR_SDK_ROOT.rglob("*.py")
        for imported in _imports(path)
    }

    for forbidden in (
        "ProcessHost",
        "ScopeBoundProcessLauncher",
        "LocalSandboxService",
        "HostedProcessContainmentPlanner",
        "ManagedWorkerLaunchPort",
        "local_worker",
        "remote_service",
    ):
        assert forbidden not in author_sources
    assert not any(
        imported.startswith(
            (
                "loushang.harness.plugin_management",
                "loushang.harness.sandbox",
                "loushang.harness.tools.process_hosting",
                "loushang.harness.workspace.process",
            )
        )
        for imported in author_imports
    )
    assert AUTHOR_SDK.is_file()


def test_plc9c0_plugin_management_has_no_process_or_sandbox_authority() -> None:
    sources = "\n".join(_source(path) for path in PLUGIN_MANAGEMENT_ROOT.rglob("*.py"))
    imports = {
        imported
        for path in PLUGIN_MANAGEMENT_ROOT.rglob("*.py")
        for imported in _imports(path)
    }

    assert not any(
        imported.startswith(
            (
                "loushang.harness.sandbox",
                "loushang.harness.tools.process_hosting",
                "loushang.harness.workspace.process",
            )
        )
        for imported in imports
    )
    for forbidden in (
        "ProcessHost",
        "ScopeBoundProcessLauncher",
        "LocalSandboxService",
        "HostedProcessContainmentPlanner",
        "ManagedWorkerLaunchPort",
        "__import__(",
        "import_module(",
    ):
        assert forbidden not in sources


def test_plc9c0_import_guard_resolves_relative_authority_edges() -> None:
    assert "loushang.harness.sandbox" in _imports_from_source(
        "from ..sandbox import LocalSandboxService",
        package="loushang.harness.plugin_management",
    )
    assert "loushang.harness.tools.process_hosting" in _imports_from_source(
        "from ..tools.process_hosting import ScopeBoundProcessLauncher",
        package="loushang.harness.plugin_management",
    )
    assert "loushang.harness.tools.process_hosting" in _imports_from_source(
        "from loushang.harness.tools import process_hosting as ph",
        package="loushang.harness.plugin_management",
    )
    assert "loushang.harness.sandbox" in _imports_from_source(
        "from .. import sandbox",
        package="loushang.harness.plugin_management",
    )
    assert "loushang.harness.tools.process_hosting" in _imports_from_source(
        "from ..harness.tools.process_hosting import ScopeBoundProcessLauncher",
        package="loushang.plugin",
    )


def test_plc9c1_through_c4_claim_only_the_bounded_local_protocol() -> None:
    baseline = _source(BASELINE)

    assert "bounded canonical-JSON frame protocol" in baseline
    assert "Native IPC activation remains in PLC9C5" in baseline
    assert "`remote_service` remains absent" in baseline
    assert "separate threat model" in baseline
    assert "Default runtime effect: none" in baseline
    assert "disabled by policy" in baseline


def test_plc9c0_freezes_protocol_recovery_and_product_failure_gates() -> None:
    baseline = " ".join(_source(BASELINE).split())

    for evidence in (
        "before allocating or decoding its body",
        "cancellation leaves a bounded correlation tombstone",
        "first production route does not adopt a surviving Worker",
        "Product Failure And Rollback Matrix",
        "required; pre-spawn admission fails",
        "optional; runtime loss after publication",
        "Product kill switch",
        "distinct implementation/contribution identity",
        "guard-transition ledger",
        "WSL",
        "every unlisted OS/environment",
    ):
        assert evidence in baseline
