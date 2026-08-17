from pathlib import Path

from loushang.harness.bootstrap import (
    BootstrapActivationPlan,
    BootstrapActivationRuntime,
    ResourceBootstrapPorts,
    ResourceBootstrapRuntime,
    create_standard_resource_bootstrap_runtime,
    register_extension_tools,
    register_resource_extension_tools,
)
from loushang.harness.config.activation import ConfigActivationStep
from loushang.harness.diagnostics import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


def test_resource_bootstrap_orders_flags_before_extension_rediscovery() -> None:
    calls: list[str] = []

    class Loader:
        def discover_resources(self, cwd: Path) -> dict[str, object]:
            calls.append(f"discover:{cwd.name}")
            return {"diagnostics": ["loader"], "extensions": ["extension"]}

    class Extensions:
        def __init__(self, values: list[str]) -> None:
            self.values = values

        def get_diagnostics(self) -> list[str]:
            return ["extension-diagnostic"]

        def discover_resources(self, bundle: dict[str, object]) -> dict[str, object]:
            calls.append("rediscover")
            return {**bundle, "rediscovered": True}

    runtime = ResourceBootstrapRuntime(
        ResourceBootstrapPorts(
            discover_resources=lambda loader, cwd: loader.discover_resources(cwd),
            create_extension_runtime=lambda bundle: Extensions(bundle["extensions"]),
            apply_extension_flags=lambda _runtime, _flags: (
                calls.append("flags") or ["flag-diagnostic"]
            ),
            rediscover_resources=lambda extensions, bundle: (
                extensions.discover_resources(bundle)
            ),
            bundle_diagnostics=lambda bundle: bundle["diagnostics"],
            extension_diagnostics=lambda extensions: extensions.get_diagnostics(),
            normalize_diagnostic=lambda diagnostic, phase, source: (
                phase,
                source,
                diagnostic,
            ),
        )
    )

    result = runtime.prepare(
        loader=Loader(), cwd=Path("/tmp/project"), extension_flags={}
    )

    assert calls == ["discover:project", "flags", "rediscover"]
    assert result.resource_bundle["rediscovered"] is True
    assert result.diagnostics == (
        ("resource_loading", "loader", "loader"),
        ("resource_loading", "extensions", "extension-diagnostic"),
        ("resource_loading", "bootstrap", "flag-diagnostic"),
    )


def test_resource_bootstrap_exposes_discovery_and_extension_activation_phases() -> (
    None
):
    transforms: list[str] = []

    class Loader:
        pass

    class Extensions:
        def get_diagnostics(self) -> list[str]:
            return ["extension"]

    runtime = ResourceBootstrapRuntime(
        ResourceBootstrapPorts(
            discover_resources=lambda _loader, cwd: {
                "cwd": cwd,
                "diagnostics": ["loader"],
            },
            create_extension_runtime=lambda _bundle: Extensions(),
            apply_extension_flags=lambda _runtime, _flags: ["flag"],
            rediscover_resources=lambda _runtime, bundle: {
                **bundle,
                "rediscovered": True,
            },
            bundle_diagnostics=lambda bundle: bundle["diagnostics"],
            extension_diagnostics=lambda runtime: runtime.get_diagnostics(),
            normalize_diagnostic=lambda diagnostic, phase, source: (
                phase,
                source,
                diagnostic,
            ),
        )
    )

    def transform(bundle: dict[str, object]) -> dict[str, object]:
        transforms.append("transform")
        return {**bundle, "transformed": len(transforms)}

    discovery = runtime.discover(
        loader=Loader(),
        cwd=Path("/tmp/project"),
        transform_bundle=transform,
    )
    activation = runtime.activate_extensions(
        resource_bundle=discovery.resource_bundle,
        extension_flags={"plan": True},
        transform_bundle=transform,
    )

    assert transforms == ["transform", "transform"]
    assert discovery.resource_bundle["transformed"] == 1
    assert discovery.diagnostics == (
        ("resource_loading", "loader", "loader"),
    )
    assert activation.resource_bundle["transformed"] == 2
    assert activation.resource_bundle["rediscovered"] is True
    assert activation.flag_diagnostics == (
        ("resource_loading", "bootstrap", "flag"),
    )
    assert activation.extension_diagnostics == (
        ("resource_loading", "extensions", "extension"),
    )


def test_standard_resource_bootstrap_binds_shared_components(tmp_path) -> None:
    class Loader:
        def discover_resources(self, cwd: Path) -> ResourceBundle:
            return ResourceBundle(
                cwd=cwd,
                diagnostics=[DiagnosticDraft(code="loader", message="loaded")],
            )

    class Extensions:
        def apply_flag_values(self, _values):
            return [DiagnosticDraft(code="flag", message="flagged")]

        def discover_resources(self, bundle: ResourceBundle) -> ResourceBundle:
            return bundle

        def get_diagnostics(self):
            return [DiagnosticDraft(code="extension", message="activated")]

    runtime = create_standard_resource_bootstrap_runtime(
        create_extension_runtime=lambda _bundle: Extensions(),
        diagnostics_service=DiagnosticsService(),
        session_id="session-1",
    )

    result = runtime.prepare(
        loader=Loader(),
        cwd=tmp_path,
        extension_flags={"flag": True},
    )

    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "loader",
        "extension",
        "flag",
    ]
    assert all(
        diagnostic.session_id == "session-1" for diagnostic in result.diagnostics
    )


def test_bootstrap_activation_runtime_runs_product_steps_in_dependency_order() -> None:
    calls: list[str] = []
    steps = (
        ConfigActivationStep(
            "resources",
            select=lambda config: config["resources"],
            apply=lambda _selection, context: calls.append("resources") or context,
        ),
        ConfigActivationStep(
            "extensions",
            select=lambda config: config["extensions"],
            apply=lambda _selection, context: calls.append("extensions") or context,
            depends_on=("resources",),
        ),
    )

    runtime = BootstrapActivationRuntime(BootstrapActivationPlan(steps=steps))
    result = runtime.activate(
        {"resources": True, "extensions": True},
        {"ready": True},
    )

    assert result.report.ok
    assert result.context == {"ready": True}
    assert runtime.ordered_step_names == ("resources", "extensions")
    assert calls == ["resources", "extensions"]


def test_bootstrap_activation_runtime_reports_failure_and_rolls_back() -> None:
    calls: list[str] = []

    def apply_resources(_selection: object, context: list[str]) -> None:
        context.append("resources")

    def dispose_resources(context: list[str]) -> None:
        calls.append("dispose")
        context.append("disposed")

    def fail_extensions(_selection: object, _context: list[str]) -> None:
        raise RuntimeError("extension activation failed")

    runtime = BootstrapActivationRuntime(
        BootstrapActivationPlan(
            steps=(
                ConfigActivationStep(
                    "resources",
                    select=lambda config: config,
                    apply=apply_resources,
                    dispose=dispose_resources,
                ),
                ConfigActivationStep(
                    "extensions",
                    select=lambda config: config,
                    apply=fail_extensions,
                    depends_on=("resources",),
                ),
            )
        )
    )

    context: list[str] = []
    result = runtime.activate(True, context)

    assert not result.report.ok
    assert result.report.failures[0].step == "extensions"
    assert calls == ["dispose"]
    assert context == ["resources", "disposed"]


def test_extension_tool_registration_is_product_neutral(tmp_path) -> None:
    async def execute(_name, _arguments, _context, _signal):
        return {"ok": True}

    tool = ToolDefinition(
        name="review",
        label="Review",
        description="Review changes",
        parameters={"type": "object", "properties": {}, "required": []},
        execution=direct_execution(execute),
    )

    class ExtensionRuntime:
        def list_tool_definitions(self):
            return [tool]

        def get_tool_source_info(self, name: str):
            return {"source": "extension", "name": name}

    registry = WorkspaceToolRegistry()
    bundle = ResourceBundle(cwd=tmp_path)
    result_bundle, result_registry, diagnostics = register_extension_tools(
        extension_runtime=ExtensionRuntime(),
        resource_bundle=bundle,
        tool_registry=registry,
        list_tool_definitions=lambda runtime: runtime.list_tool_definitions(),
        get_tool_source_info=lambda runtime, name: runtime.get_tool_source_info(name),
        merge_diagnostics=lambda current, values: current.merge(diagnostics=list(values)),
        make_conflict_diagnostic=lambda name, message: (name, message),
    )

    assert result_bundle is bundle
    assert result_registry is registry
    assert diagnostics == []
    assert [definition.name for definition in registry.list_definitions()] == [
        "review"
    ]


def test_resource_extension_tool_registration_uses_shared_bundle_types(
    tmp_path,
) -> None:
    async def execute(_name, _arguments, _context, _signal):
        return {"ok": True}

    tool = ToolDefinition(
        name="review",
        label="Review",
        description="Review changes",
        parameters={"type": "object", "properties": {}, "required": []},
        execution=direct_execution(execute),
    )

    class ExtensionRuntime:
        def list_tool_definitions(self):
            return [tool]

        def get_tool_source_info(self, name: str):
            return {"source": "extension", "name": name}

    bundle = ResourceBundle(cwd=tmp_path)
    result_bundle, result_registry, diagnostics = register_resource_extension_tools(
        extension_runtime=ExtensionRuntime(),
        resource_bundle=bundle,
        tool_registry=None,
        list_tool_definitions=lambda runtime: runtime.list_tool_definitions(),
        get_tool_source_info=lambda runtime, name: runtime.get_tool_source_info(name),
    )

    assert result_bundle is bundle
    assert result_registry is not None
    assert diagnostics == []
    assert [definition.name for definition in result_registry.list_definitions()] == [
        "review"
    ]
