from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

UNRESOLVED_RELATIVE_IMPORT = "<unresolved-relative-import>"


@dataclass(frozen=True)
class ImportBoundary:
    name: str
    root: Path
    forbidden_prefixes: tuple[str, ...]
    allowed_paths: frozenset[str] = frozenset()


def test_core_runtime_packages_do_not_import_product_layers() -> None:
    boundaries = (
        ImportBoundary(
            name="protocol",
            root=Path("src/loushang/protocol"),
            forbidden_prefixes=(
                "loushang.agent",
                "loushang.ai",
                "loushang.channel",
                "loushang.coding",
                "loushang.harness",
                "loushang.method",
                "loushang.observability",
                "loushang.ontology",
                "loushang.resource",
                "loushang.tui",
                "loushang.work",
            ),
        ),
        ImportBoundary(
            name="ai",
            root=Path("src/loushang/ai"),
            forbidden_prefixes=(
                "loushang.agent",
                "loushang.channel",
                "loushang.coding",
                "loushang.harness",
                "loushang.method",
                "loushang.tui",
                "loushang.work",
            ),
        ),
        ImportBoundary(
            name="agent",
            root=Path("src/loushang/agent"),
            forbidden_prefixes=(
                "loushang.coding",
                "loushang.harness",
                "loushang.method",
                "loushang.tui",
                "loushang.work",
            ),
        ),
        ImportBoundary(
            name="harness",
            root=Path("src/loushang/harness"),
            forbidden_prefixes=(
                "loushang.agent.Agent",
                "loushang.agent.agent",
                "loushang.agent.harness",
                "loushang.coding",
                "loushang.method",
                "loushang.tui",
                "loushang.work",
            ),
            allowed_paths=frozenset(
                {
                    "src/loushang/harness/session/agent_adapter.py",
                    "src/loushang/harness/session/agent_product.py",
                    "src/loushang/harness/session/composition.py",
                    "src/loushang/harness/session/operations_runtime.py",
                    "src/loushang/harness/session/side_question.py",
                }
            ),
        ),
        ImportBoundary(
            name="work",
            root=Path("src/loushang/work"),
            forbidden_prefixes=(
                "loushang.agent",
                "loushang.coding",
                "loushang.method",
                "loushang.tui",
            ),
            allowed_paths=frozenset(
                {
                    "src/loushang/work/agent_projection.py",
                    "src/loushang/work/coding.py",
                }
            ),
        ),
        ImportBoundary(
            name="method",
            root=Path("src/loushang/method"),
            forbidden_prefixes=(
                "loushang.coding",
                "loushang.tui",
            ),
        ),
        ImportBoundary(
            name="channel",
            root=Path("src/loushang/channel"),
            forbidden_prefixes=(
                "loushang.agent",
                "loushang.ai",
                "loushang.coding",
                "loushang.harness",
                "loushang.method",
                "loushang.tui",
            ),
            allowed_paths=frozenset(
                {
                    "src/loushang/channel/json_codec.py",
                    "src/loushang/channel/types.py",
                }
            ),
        ),
    )

    offenders: list[str] = []
    for boundary in boundaries:
        offenders.extend(_find_forbidden_imports(boundary))

    assert offenders == []


def test_harness_profiles_have_explicit_ai_agent_dependency_allowlists() -> None:
    harness_root = Path("src/loushang/harness")
    profile_allowlists = {
        harness_root / "transcript": (
            "loushang.ai",
            "loushang.ai.model",
            "loushang.ai.types",
            "loushang.ai.json_codec",
            "loushang.agent.types",
            "loushang.agent.json_codec",
        ),
        harness_root / "session": (
            "loushang.ai.api_registry",
            "loushang.ai.json_codec",
            "loushang.ai.model",
            "loushang.ai.types",
            "loushang.ai.utils",
            "loushang.agent",
        ),
        harness_root / "extensions" / "agent": (
            "loushang.ai.types",
            "loushang.agent",
        ),
        harness_root / "extensions": (
            "loushang.ai.api_registry",
            "loushang.ai.model",
            "loushang.ai.types",
            "loushang.agent",
        ),
        harness_root / "tools": (
            "loushang.ai.types",
            "loushang.agent.types",
        ),
        harness_root / "config" / "agent": (
            "loushang.ai.model",
            "loushang.agent",
        ),
        harness_root / "host": (
            "loushang.ai.model",
            "loushang.ai.types",
            "loushang.agent",
        ),
        harness_root / "events": (
            "loushang.ai.json_codec",
            "loushang.agent.json_codec",
            "loushang.agent.types",
        ),
        harness_root / "model_catalog.py": (
            "loushang.ai.model",
            "loushang.ai.model.domain",
            "loushang.ai.model.loader",
            "loushang.ai.model.registry",
            "loushang.ai.model.selection",
        ),
    }
    offenders: list[str] = []

    for path in sorted(harness_root.rglob("*.py")):
        allowed_prefixes = next(
            (
                prefixes
                for profile_root, prefixes in profile_allowlists.items()
                if path == profile_root or profile_root in path.parents
            ),
            (),
        )
        for imported in _absolute_imports(path):
            is_ai_import = _matches_any(imported, ("loushang.ai",))
            is_profile_agent_import = bool(allowed_prefixes) and _matches_any(
                imported, ("loushang.agent",)
            )
            if not is_ai_import and not is_profile_agent_import:
                continue
            if _matches_any(imported, allowed_prefixes):
                continue
            offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_extension_agent_profile_has_no_session_or_product_dependency() -> None:
    profile_root = Path("src/loushang/harness/extensions/agent")
    forbidden_prefixes = (
        "loushang.harness.session",
        "loushang.coding",
        "loushang.channel",
        "loushang.work",
        "loushang.method",
        "loushang.tui",
    )
    offenders = [
        f"{path.as_posix()} imports {imported}"
        for path in sorted(profile_root.rglob("*.py"))
        for imported in _absolute_imports(path)
        if _matches_any(imported, forbidden_prefixes)
    ]

    assert offenders == []
    assert not Path("src/loushang/coding/extensions/hooks.py").exists()
    assert not Path("src/loushang/harness/session/extension_hooks.py").exists()
    assert not Path("src/loushang/harness/session/extension_events.py").exists()
    assert not Path("src/loushang/harness/session/extension_input.py").exists()


def test_harness_internal_dependency_graph_is_acyclic() -> None:
    graph = _harness_internal_dependency_graph(Path("src/loushang/harness"))

    cycles = [
        component
        for component in _strongly_connected_components(graph)
        if len(component) > 1
    ]

    assert cycles == []


def test_runtime_event_layers_follow_declared_dependency_direction() -> None:
    graph = _harness_internal_dependency_graph(Path("src/loushang/harness"))
    forbidden_edges = {
        "transcript": {"host", "session"},
        "events": {"host", "runtime", "session", "transcript"},
        "session": {"host"},
    }
    offenders = sorted(
        f"{source} -> {target}"
        for source, forbidden_targets in forbidden_edges.items()
        for target in graph.get(source, set()) & forbidden_targets
    )

    assert offenders == []


def test_runtime_event_legacy_owner_modules_are_extinct() -> None:
    legacy_paths = (
        "src/loushang/harness/transcript/session_export.py",
        "src/loushang/harness/events/runtime_views.py",
        "src/loushang/harness/events/session_projection.py",
        "src/loushang/harness/events/session_serialization.py",
        "src/loushang/harness/events/session_types.py",
        "src/loushang/harness/host/queue.py",
        "src/loushang/harness/host/retry.py",
        "src/loushang/harness/host/runtime.py",
        "src/loushang/harness/host/turn.py",
    )

    assert [path for path in legacy_paths if Path(path).exists()] == []


def test_capability_composition_runtime_has_no_product_dependency() -> None:
    path = Path("src/loushang/harness/capabilities/composition_runtime.py")
    offenders = [
        imported
        for imported in _absolute_imports(path)
        if _matches_any(imported, ("loushang.coding",))
    ]

    assert offenders == []


def test_coding_runtime_plans_are_declarative_over_shared_bindings() -> None:
    assert not Path("src/loushang/coding/capability_profile.py").exists()
    assert not Path("src/loushang/coding/capability_plan.py").exists()
    assert not Path("src/loushang/coding/runtime_profile.py").exists()

    expected_imports = {
        Path("src/loushang/coding/product_plan.py"): {
            "loushang.harness.transcript.AgentTranscriptProfileRuntime",
            "loushang.harness.transcript.AgentTranscriptRuntimeSpec",
            "loushang.harness.capabilities.standard_capability_composition_plan",
            "loushang.harness.runtime.RuntimeProfileResolver",
        },
        Path("src/loushang/coding/bootstrap.py"): {
            "loushang.coding.product_plan.CODING_CAPABILITY_PROFILE",
            "loushang.harness.capabilities.bind_capability_composition_runtime",
        },
        Path("src/loushang/coding/session/agent_session.py"): {
            "loushang.coding.product_plan.CODING_CAPABILITY_PROFILE",
            "loushang.harness.capabilities.CapabilityCompositionRuntime",
            "loushang.harness.capabilities.bind_capability_composition_runtime",
        },
        Path("src/loushang/coding/session_manager.py"): {
            "loushang.coding.product_plan.CODING_CAPABILITY_PROFILE",
            "loushang.coding.product_plan.CODING_TRANSCRIPT_RUNTIME",
        },
    }
    missing: list[str] = []
    for path, required in expected_imports.items():
        imports = set(_absolute_imports(path))
        missing.extend(
            f"{path.as_posix()} missing {name}" for name in sorted(required - imports)
        )

    assert missing == []


def test_harnesstui_neutral_modules_do_not_import_product_or_model_layers() -> None:
    agent_binding = Path("src/loushang/harnesstui/conversation/agent_binding.py")
    offenders = _find_forbidden_imports(
        ImportBoundary(
            name="harnesstui",
            root=Path("src/loushang/harnesstui"),
            forbidden_prefixes=(
                "loushang.agent",
                "loushang.ai",
                "loushang.ai.provider",
                "loushang.ai.providers",
                "loushang.coding",
            ),
            allowed_paths=frozenset({agent_binding.as_posix()}),
        )
    )

    assert offenders == []
    assert {
        imported
        for imported in _absolute_imports(agent_binding)
        if imported.startswith(("loushang.agent", "loushang.ai"))
    } == {
        "loushang.agent.types",
        "loushang.agent.types.AgentToolResult",
    }


def test_production_harnesstui_imports_only_approved_loushang_layers() -> None:
    root = Path("src/loushang/harnesstui")
    testing_root = root / "testing"
    agent_binding = root / "conversation" / "agent_binding.py"
    allowed_prefixes = (
        "loushang.harnesstui",
        "loushang.tui",
        "loushang.harness",
        "loushang.protocol",
    )
    offenders = [
        f"{path.as_posix()} imports {imported}"
        for path in sorted(root.rglob("*.py"))
        if testing_root not in path.parents
        for imported in _absolute_imports(path)
        if imported.startswith("loushang.")
        and not _matches_any(
            imported,
            allowed_prefixes
            + (("loushang.agent.types",) if path == agent_binding else ()),
        )
    ]

    assert offenders == []


def test_harnesstui_testing_does_not_import_runtime_or_product_layers() -> None:
    offenders = _find_forbidden_imports(
        ImportBoundary(
            name="harnesstui.testing",
            root=Path("src/loushang/harnesstui/testing"),
            forbidden_prefixes=(
                "loushang.agent",
                "loushang.ai",
                "loushang.coding",
                "loushang.harness",
            ),
        )
    )

    assert offenders == []


def test_harnesstui_testing_imports_only_approved_loushang_layers() -> None:
    root = Path("src/loushang/harnesstui/testing")
    allowed_prefixes = (
        "loushang.harnesstui",
        "loushang.tui",
    )
    offenders = [
        f"{path.as_posix()} imports {imported}"
        for path in sorted(root.rglob("*.py"))
        for imported in _absolute_imports(path)
        if imported.startswith("loushang.")
        and not _matches_any(imported, allowed_prefixes)
    ]

    assert offenders == []


def test_production_harnesstui_does_not_import_testing_support() -> None:
    testing_root = Path("src/loushang/harnesstui/testing")
    offenders = [
        f"{path.as_posix()} imports {imported}"
        for path in sorted(Path("src/loushang/harnesstui").rglob("*.py"))
        if testing_root not in path.parents
        for imported in _absolute_imports(path)
        if _matches_any(imported, ("loushang.harnesstui.testing",))
    ]

    assert offenders == []


def test_neutral_conversation_core_does_not_import_agent_ai_or_products() -> None:
    boundary = ImportBoundary(
        name="conversation",
        root=Path("src/loushang/harness/conversation"),
        forbidden_prefixes=(
            "loushang.agent",
            "loushang.ai",
            "loushang.coding",
            "loushang.method",
            "loushang.tui",
            "loushang.work",
        ),
    )

    assert _find_forbidden_imports(boundary) == []


def test_neutral_conversation_and_event_cores_do_not_import_runtime_or_products() -> (
    None
):
    forbidden = (
        "loushang.agent",
        "loushang.ai",
        "loushang.channel",
        "loushang.coding",
        "loushang.method",
        "loushang.tui",
        "loushang.work",
    )
    boundaries = (
        ImportBoundary(
            name="events",
            root=Path("src/loushang/harness/events"),
            # The session serializer is an optional Agent/AI-aware event
            # profile.  It is still forbidden from importing products or
            # transports; neutral event facts remain product-independent.
            forbidden_prefixes=tuple(
                prefix
                for prefix in forbidden
                if prefix not in {"loushang.agent", "loushang.ai"}
            ),
        ),
    )

    assert [
        offender
        for boundary in boundaries
        for offender in _find_forbidden_imports(boundary)
    ] == []


def test_scenario_runtime_is_product_neutral_and_never_executes_shell() -> None:
    boundary = ImportBoundary(
        name="scenario",
        root=Path("src/loushang/harness/scenario"),
        forbidden_prefixes=(
            "loushang.agent",
            "loushang.ai",
            "loushang.channel",
            "loushang.coding",
            "loushang.method",
            "loushang.tui",
            "loushang.work",
        ),
    )

    assert _find_forbidden_imports(boundary) == []
    assert all(
        "subprocess" not in path.read_text(encoding="utf-8")
        for path in boundary.root.rglob("*.py")
    )


def test_shared_session_work_projection_subscribes_to_runtime_events() -> None:
    session_work_source = Path("src/loushang/work/session.py").read_text(
        encoding="utf-8"
    )
    coding_binding = Path("src/loushang/coding/domain/work.py").read_text(
        encoding="utf-8"
    )

    assert "subscribe_runtime_events" in session_work_source
    assert "self.session.subscribe(listener)" not in session_work_source
    assert "WorkRuntime" in session_work_source
    assert "subscribe_runtime_events" not in coding_binding


def test_agent_work_projection_is_work_owned() -> None:
    work_projection = Path("src/loushang/work/agent_projection.py").read_text(
        encoding="utf-8"
    )
    work_event_projection = Path("src/loushang/work/projection.py").read_text(
        encoding="utf-8"
    )
    coding_binding = Path("src/loushang/coding/domain/work.py").read_text(
        encoding="utf-8"
    )

    assert "def project_agent_event_to_work_facts" in work_projection
    assert "loushang.coding" not in work_projection
    assert "loushang.coding" not in work_event_projection
    assert "loushang.work.agent_projection" in coding_binding
    assert not Path("src/loushang/coding/work_projection.py").exists()

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import loushang.work.agent_projection; "
            "assert not any(name == 'loushang.coding' or "
            "name.startswith('loushang.coding.') for name in sys.modules)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_coding_session_uses_harness_runtime_events_as_the_only_internal_stream() -> (
    None
):
    session_source = Path("src/loushang/coding/session/agent_session.py").read_text(
        encoding="utf-8"
    )

    assert "SessionEventBus" not in session_source
    assert "self._event_bus" not in session_source
    assert not Path("src/loushang/coding/session/session_event_bus.py").exists()
    assert not Path("src/loushang/coding/session/retry_controller.py").exists()
    assert not Path("src/loushang/coding/session/session_view_controller.py").exists()
    assert not Path("src/loushang/coding/session/compaction_controller.py").exists()
    assert not Path("src/loushang/coding/session/tree_controller.py").exists()
    assert "project_runtime_event_to_session_event" in session_source


def test_coding_agent_session_delegates_shared_turn_runtime_to_harness() -> None:
    coding_source = Path("src/loushang/coding/session/agent_session.py").read_text(
        encoding="utf-8"
    )
    shared_source = Path("src/loushang/harness/session/agent_product.py").read_text(
        encoding="utf-8"
    )

    assert "compose_session_runtime" in shared_source
    assert "initialize_composed_session" in shared_source
    assert "class AgentSession(AgentProductSession):" in coding_source
    forbidden_owners = (
        "OrderedEventBus",
        "RuntimeEventPublisher",
        "HostRuntime",
        "QueueController",
        "PromptController",
        "ApplicationInputRuntime",
        "AgentEventRouter",
    )
    assert all(owner not in coding_source for owner in forbidden_owners)


def test_agent_transcript_interaction_runtime_is_neutral_and_adopted() -> None:
    interaction_source = Path(
        "src/loushang/harness/transcript/interaction.py"
    ).read_text(encoding="utf-8")
    composition_source = Path("src/loushang/harness/session/composition.py").read_text(
        encoding="utf-8"
    )
    product_source = Path("src/loushang/harness/session/agent_product.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/agent-transcript-interaction-runtime-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in interaction_source
    assert "AgentTranscriptNavigationRuntime" in composition_source
    assert "compose_session_runtime" in product_source
    assert "AgentSessionInspector" in composition_source
    assert "AgentSessionAdapterMixin" in product_source
    assert not Path("src/loushang/coding/session/tree_controller.py").exists()
    assert not Path("src/loushang/coding/session/selection_controller.py").exists()
    assert "Product-supplied" in boundary
    assert "Coding keeps" in boundary


def test_agent_transcript_maintenance_runtime_is_neutral_and_adopted() -> None:
    maintenance_source = Path(
        "src/loushang/harness/transcript/maintenance.py"
    ).read_text(encoding="utf-8")
    composition_source = Path("src/loushang/harness/session/composition.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/agent-transcript-maintenance-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in maintenance_source
    assert "AgentTranscriptCompactionRuntime" in composition_source
    assert "AgentTranscriptRetryRuntime" in composition_source
    assert not Path("src/loushang/coding/session/compaction_controller.py").exists()
    assert "Product-selected" in boundary
    assert "Coding keeps" in boundary


def test_agent_transcript_export_runtime_is_neutral_and_adopted() -> None:
    export_root = Path("src/loushang/harness/transcript/export")
    session_adapter = Path("src/loushang/harness/session/export.py")
    boundary = Path(
        "docs/internals/architecture/harness/agent-transcript-export-boundary.md"
    )

    assert export_root.exists()
    assert not any(
        imported.startswith("loushang.coding")
        for path in export_root.rglob("*.py")
        for imported in _absolute_imports(path)
    )
    assert "TranscriptExportRequest" in session_adapter.read_text(encoding="utf-8")
    assert "TranscriptHtmlExportProfile" in session_adapter.read_text(encoding="utf-8")
    assert not Path("src/loushang/coding/session/export_html/index.py").exists()
    assert not Path("src/loushang/coding/session/export_html/tool_renderer.py").exists()
    assert not Path("src/loushang/coding/session/export_jsonl.py").exists()
    assert "Agent Transcript Export Boundary" in boundary.read_text(encoding="utf-8")


def test_transcript_compaction_capability_is_neutral_and_adopted() -> None:
    capability_source = Path("src/loushang/harness/transcript/compaction.py").read_text(
        encoding="utf-8"
    )
    runtime_profile_source = Path(
        "src/loushang/harness/transcript/runtime_profile.py"
    ).read_text(encoding="utf-8")
    product_plan_source = Path("src/loushang/coding/product_plan.py").read_text(
        encoding="utf-8"
    )
    composition_source = Path("src/loushang/harness/session/composition.py").read_text(
        encoding="utf-8"
    )
    session_source = Path("src/loushang/coding/session/agent_session.py").read_text(
        encoding="utf-8"
    )
    summary_executor_source = Path(
        "src/loushang/harness/transcript/summarization.py"
    ).read_text(encoding="utf-8")
    coding_adapter_source = Path("src/loushang/coding/compaction/adapter.py").read_text(
        encoding="utf-8"
    )
    binding = Path(
        "docs/internals/architecture/harness/product-runtime-injection/"
        "02-context-compaction-binding.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in capability_source
    assert "ConversationCompactionPlanner" in capability_source
    assert "loushang.coding" not in runtime_profile_source
    assert "TURN_AWARE_SUMMARY_IMPLEMENTATION" in runtime_profile_source
    assert "create_agent_transcript_compaction_capability" in runtime_profile_source
    assert "AgentTranscriptRuntimeSpec" in product_plan_source
    assert "AgentTranscriptCompactionCapability" in composition_source
    assert "loushang.coding" not in summary_executor_source
    assert "execute_transcript_compaction" in summary_executor_source
    assert "execute_branch_summary" in summary_executor_source
    assert "ConversationCompactionPlanner" not in coding_adapter_source
    assert "execute_transcript_compaction" in coding_adapter_source
    assert "CodingCompactionRuntime" not in runtime_profile_source
    assert "CodingCompactionRuntime" not in session_source
    assert "Harness owns the mechanism" in binding


def test_session_capabilities_runtime_is_neutral_and_adopted() -> None:
    capabilities_source = Path(
        "src/loushang/harness/session/capabilities.py"
    ).read_text(encoding="utf-8")
    tool_source = Path("src/loushang/harness/session/tool_controller.py").read_text(
        encoding="utf-8"
    )
    command_source = Path(
        "src/loushang/harness/session/command_controller.py"
    ).read_text(encoding="utf-8")
    bash_source = Path("src/loushang/harness/session/bash.py").read_text(
        encoding="utf-8"
    )
    composition_source = Path("src/loushang/harness/session/composition.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/session-capabilities-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in capabilities_source
    assert "loushang.coding" not in command_source
    assert "loushang.coding" not in bash_source
    assert "SessionToolRuntime" in tool_source
    assert "SessionCommandController" in command_source
    assert "BashExecutionRuntime" in bash_source
    assert "BashExecutionRuntime" in composition_source
    assert not Path("src/loushang/coding/session/bash_controller.py").exists()
    assert not Path("src/loushang/coding/session/command_controller.py").exists()
    assert "Product Binding" in boundary
    assert "Coding keeps" in boundary


def test_standard_session_command_pack_is_neutral_and_adopted() -> None:
    command_pack_source = Path(
        "src/loushang/harness/session/command_pack.py"
    ).read_text(encoding="utf-8")
    builtin_source = Path("src/loushang/harness/session/command_pack.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/session-command-pack-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in command_pack_source
    assert "execute_standard_session_command_async" in builtin_source
    assert "project_standard_session_command_result" in builtin_source
    assert "STANDARD_SESSION_COMMANDS" in builtin_source
    assert not Path("src/loushang/coding/session/builtin_commands.py").exists()
    assert not Path("src/loushang/coding/commands/types.py").exists()
    assert not Path("src/loushang/coding/commands/profile.py").exists()
    assert "one command catalog and one ordered dispatcher" in boundary
    assert "existing builtin source" in boundary


def test_session_facade_is_neutral_and_adopted() -> None:
    facade_source = Path("src/loushang/harness/session/facade.py").read_text(
        encoding="utf-8"
    )
    product_source = Path("src/loushang/harness/session/agent_product.py").read_text(
        encoding="utf-8"
    )
    coding_source = Path("src/loushang/coding/session/agent_session.py").read_text(
        encoding="utf-8"
    )
    channel_source = Path("src/loushang/coding/domain/work.py").read_text(
        encoding="utf-8"
    )
    rpc_source = Path("src/loushang/harness/host/rpc.py").read_text(encoding="utf-8")
    boundary = Path(
        "docs/internals/architecture/harness/session-facade-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in facade_source
    assert "execute_pi_style" not in facade_source
    assert (
        "class AgentProductSession(AgentSessionAdapterMixin, SessionFacade):"
        in product_source
    )
    assert "class AgentSession(AgentProductSession):" in coding_source
    assert "_facade" not in coding_source
    assert "SessionControlPort" in facade_source
    assert "SessionResourcePort" in facade_source
    assert "def session_control" not in coding_source
    assert "def session_control" in facade_source
    assert "SessionWorkRuntime" in channel_source
    assert "require_active_session_control" in facade_source
    assert "SessionOperationRuntime" in rpc_source
    assert "_require_session_control" not in rpc_source
    assert "Product Binding" in boundary
    assert "Coding Binding" in boundary
    assert "Pi-style" in boundary


def test_session_inspection_projection_is_harness_owned() -> None:
    projection = Path(
        "src/loushang/harness/session/inspection_projection.py"
    ).read_text(encoding="utf-8")
    session_source = Path("src/loushang/coding/session/agent_session.py").read_text(
        encoding="utf-8"
    )

    assert "loushang.coding" not in projection
    assert "project_session_stats" in projection
    assert "project_fork_candidates" in projection
    assert "get_session_stats" not in session_source
    assert not Path("src/loushang/coding/platform/session_projection.py").exists()


def test_session_rpc_operations_are_neutral_and_adopted() -> None:
    operations_source = Path("src/loushang/harness/session/operations.py").read_text(
        encoding="utf-8"
    )
    binding_source = Path("src/loushang/harness/session/rpc_operations.py").read_text(
        encoding="utf-8"
    )
    rpc_source = Path("src/loushang/harness/host/rpc.py").read_text(encoding="utf-8")
    channel_adapter_source = Path("src/loushang/coding/domain/work.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/session-rpc-operations-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in operations_source
    assert "loushang.channel" not in operations_source
    assert "json" not in operations_source
    assert "loushang.coding" not in binding_source
    assert "loushang.channel" not in binding_source
    assert "SessionRpcOperationBinding" in rpc_source
    assert "_rpc_operations.prompt_request" in rpc_source
    assert "_rpc_operations.new_session" in rpc_source
    assert "_rpc_operations.compact" in rpc_source
    assert "SessionOperationAvailability" in operations_source
    assert "SessionOperationRuntime" in rpc_source
    assert "SessionWorkRuntime" in channel_adapter_source
    assert "capability-grouped" in boundary
    assert "must not import Harness" in boundary


def test_jsonl_command_router_is_neutral_and_rpc_uses_explicit_routes() -> None:
    router_source = Path("src/loushang/channel/jsonl_command_router.py").read_text(
        encoding="utf-8"
    )
    rpc_source = Path("src/loushang/harness/host/rpc.py").read_text(encoding="utf-8")
    boundary = Path(
        "docs/internals/architecture/harness/session-rpc-operation-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.harness" not in router_source
    assert "loushang.coding" not in router_source
    assert "JsonlCommandRouter(" in rpc_source
    assert 'getattr(self, f"_handle_{command.command_type}_command")' not in rpc_source
    assert "Channel command-routing slice" in boundary


def test_channel_product_host_runtime_is_neutral_and_adopted() -> None:
    runtime_source = Path("src/loushang/channel/product_host.py").read_text(
        encoding="utf-8"
    )
    channel_host_source = Path("src/loushang/channel/host.py").read_text(
        encoding="utf-8"
    )
    rpc_source = Path("src/loushang/harness/host/rpc.py").read_text(encoding="utf-8")
    boundary = Path(
        "docs/internals/architecture/channel/product-host-runtime-boundary.md"
    ).read_text(encoding="utf-8")

    assert "from loushang." not in runtime_source
    assert "import loushang." not in runtime_source
    assert "ProductHostRuntime" in channel_host_source
    assert "ProductHostRuntime" in rpc_source
    assert "ProductHostTaskTracker" in rpc_source
    assert "Product Binding" in boundary
    assert "Coding Adoption" in boundary
    assert "Dependency Rule" in boundary


def test_mode_host_implementation_is_shared_and_coding_is_thin() -> None:
    rpc_host = Path("src/loushang/harness/host/rpc.py").read_text(encoding="utf-8")
    plain_host = Path("src/loushang/harnesstui/conversation/plain_mode.py").read_text(
        encoding="utf-8"
    )
    agent_binding = Path(
        "src/loushang/harnesstui/conversation/agent_binding.py"
    ).read_text(encoding="utf-8")
    coding_work = Path("src/loushang/coding/domain/work.py").read_text(encoding="utf-8")
    boundary = Path(
        "docs/internals/architecture/harness/mode-host-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in rpc_host
    assert "loushang.coding" not in plain_host
    assert "class RpcHost" in rpc_host
    assert "class PlainHost" in plain_host
    assert "class AgentPlainHost" in agent_binding
    assert "run_agent_mode" in agent_binding
    assert "run_coding_work_channel" in coding_work
    assert not tuple(Path("src/loushang/coding/mode").glob("*.py"))
    assert "Mode Host Boundary" in boundary


def test_prompt_input_runtime_is_harness_owned_and_coding_adopts_it() -> None:
    prompt_input_source = Path("src/loushang/harness/host/prompt_input.py").read_text(
        encoding="utf-8"
    )
    agent_args_source = Path("src/loushang/harness/cli/agent_args.py").read_text(
        encoding="utf-8"
    )
    cli_source = Path("src/loushang/coding/cli/__main__.py").read_text(encoding="utf-8")

    assert "loushang.coding" not in prompt_input_source
    assert "resolve_prompt_input" in agent_args_source
    assert "resolve_agent_prompt_input" in cli_source
    assert "_process_file_args" not in cli_source
    assert "_detect_supported_image_mime_type" not in cli_source


def test_package_projection_is_harness_owned_and_product_free() -> None:
    projection_source = Path(
        "src/loushang/harness/resources/packages/projection.py"
    ).read_text(encoding="utf-8")
    catalog_source = Path(
        "src/loushang/harness/resources/packages/catalog.py"
    ).read_text(encoding="utf-8")
    coding_resources = Path("src/loushang/coding/resource_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "loushang.coding" not in projection_source
    assert "loushang.coding" not in catalog_source
    assert "project_package_entry" in projection_source
    assert "serialize_package_materialization_record" in projection_source
    assert "collect_projected_package_entries" in projection_source
    assert "summarize_profiled_package_resources" in catalog_source
    assert "summarize_coding_package_root" in coding_resources
    assert "summarize_profiled_package_resources" in coding_resources
    assert "discover_resources" not in coding_resources
    assert not Path("src/loushang/coding/package_projection.py").exists()


def test_reusable_product_bindings_use_existing_shared_owners() -> None:
    workspace_factory = Path(
        "src/loushang/harness/tools/workspace/factory.py"
    ).read_text(encoding="utf-8")
    workspace_registry = Path(
        "src/loushang/harness/tools/workspace/registry.py"
    ).read_text(encoding="utf-8")
    coding_tools = Path("src/loushang/coding/tool_pack.py").read_text(encoding="utf-8")
    agent_application = Path(
        "src/loushang/harnesstui/conversation/agent_application.py"
    ).read_text(encoding="utf-8")
    coding_ui = Path("src/loushang/coding/ui/mode.py").read_text(encoding="utf-8")
    coding_surfaces = Path("src/loushang/coding/ui/screen_surfaces.py").read_text(
        encoding="utf-8"
    )
    coding_session = Path("src/loushang/coding/session/agent_session.py").read_text(
        encoding="utf-8"
    )
    coding_runtime = Path(
        "src/loushang/coding/runtime/agent_session_runtime.py"
    ).read_text(encoding="utf-8")

    assert "class WorkspaceToolProfile" in workspace_factory
    assert "def register_profile" in workspace_registry
    assert "WorkspaceToolProfile" in coding_tools
    assert "resolve_tool_contributions" not in coding_tools
    assert "handle_agent_screen_approval" in agent_application
    assert "bind_agent_screen_approval_presenter" in coding_ui
    assert "build_agent_screen_surface_workflow_ports" in agent_application
    assert "build_agent_screen_surface_workflow_ports" in coding_surfaces
    for duplicate in (
        "snapshot_conversation_command_catalog",
        "format_available_session_models",
        "get_session_model_identity",
        "ApprovalSurfaceDecision",
    ):
        assert duplicate not in coding_surfaces
    assert not Path("src/loushang/coding/policy/tui.py").exists()
    assert "async def _sleep_for_retry" not in coding_session
    assert "sleep_for_retry" in coding_session
    assert "MissingSessionCwdIssue" not in coding_runtime
    assert "_coding_missing_cwd_error" not in coding_runtime


def test_plain_services_and_work_bindings_remove_coding_duplication() -> None:
    agent_plain = Path(
        "src/loushang/harnesstui/conversation/agent_plain_app.py"
    ).read_text(encoding="utf-8")
    coding_plain = Path("src/loushang/coding/ui/plain_app.py").read_text(
        encoding="utf-8"
    )
    session_bootstrap = Path("src/loushang/harness/session/bootstrap.py").read_text(
        encoding="utf-8"
    )
    coding_bootstrap = Path("src/loushang/coding/bootstrap.py").read_text(
        encoding="utf-8"
    )
    work_session = Path("src/loushang/work/session.py").read_text(encoding="utf-8")
    coding_prompt = Path("src/loushang/coding/prompt_command.py").read_text(
        encoding="utf-8"
    )

    assert "build_agent_plain_conversation_ports" in agent_plain
    assert "build_agent_plain_conversation_ports" in coding_plain
    for duplicate in (
        "ConversationCommandCatalog",
        "snapshot_conversation_command_catalog",
        "format_available_session_models",
        "AgentPlainConversationPorts",
    ):
        assert duplicate not in coding_plain

    assert "prepare_agent_session_services" in session_bootstrap
    assert "prepare_standard_agent_session_services" in coding_bootstrap
    assert "bootstrap_runtime.prepare" not in coding_bootstrap
    assert "service components cannot be overridden" not in coding_bootstrap

    assert "submit_session_turn" in work_session
    assert "require_session_work_turn" in work_session
    assert "submit_session_turn" in coding_prompt
    assert "require_session_work_turn" in coding_prompt
    for duplicate in (
        "def _run_prompt_session",
        "def _prompt_session",
        "def _require_session_work_turn",
    ):
        assert duplicate not in coding_prompt


def test_channel_product_host_stdio_and_shutdown_helpers_are_neutral() -> None:
    product_host_source = Path("src/loushang/channel/product_host.py").read_text(
        encoding="utf-8"
    )
    stdout_guard_source = Path("src/loushang/channel/stdout_guard.py").read_text(
        encoding="utf-8"
    )
    cli_source = Path("src/loushang/coding/cli/__main__.py").read_text(encoding="utf-8")
    application_source = Path("src/loushang/harness/cli/application.py").read_text(
        encoding="utf-8"
    )

    assert "from loushang." not in product_host_source
    assert "import loushang." not in product_host_source
    assert "from loushang." not in stdout_guard_source
    assert "import loushang." not in stdout_guard_source
    assert "ProductHostLifecycle.resolve" in cli_source
    assert "host_lifecycle.run_turns" in cli_source
    assert "host_lifecycle=host_lifecycle" in cli_source
    assert "binding.host_lifecycle.output_guard" in application_source
    assert not Path("src/loushang/coding/platform/output_guard.py").exists()


def test_cli_product_host_operations_are_shared_and_product_neutral() -> None:
    operations_source = Path("src/loushang/harness/cli/host_operations.py").read_text(
        encoding="utf-8"
    )
    launch_source = Path("src/loushang/harness/cli/launch.py").read_text(
        encoding="utf-8"
    )
    application_source = Path("src/loushang/harness/cli/application.py").read_text(
        encoding="utf-8"
    )
    package_diagnostics_source = Path(
        "src/loushang/harness/resources/packages/catalog_diagnostics.py"
    ).read_text(encoding="utf-8")
    turns_source = Path("src/loushang/harness/cli/turns.py").read_text(encoding="utf-8")
    agent_host_source = Path("src/loushang/harness/cli/agent_host.py").read_text(
        encoding="utf-8"
    )
    agent_args_source = Path("src/loushang/harness/cli/agent_args.py").read_text(
        encoding="utf-8"
    )
    session_configuration_source = Path(
        "src/loushang/harness/cli/session_configuration.py"
    ).read_text(encoding="utf-8")
    scenario_cli_source = Path("src/loushang/harness/scenario/cli.py").read_text(
        encoding="utf-8"
    )
    coding_source = Path("src/loushang/coding/cli/__main__.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/cli-product-host-collapse.md"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "loushang.coding",
        "loushang.method",
        "loushang.work",
        "loushang.tui",
    ):
        assert forbidden not in operations_source
        assert forbidden not in launch_source
        assert forbidden not in application_source
        assert forbidden not in package_diagnostics_source
        assert forbidden not in turns_source
        assert forbidden not in agent_host_source
        assert forbidden not in agent_args_source
        assert forbidden not in session_configuration_source
        assert forbidden not in scenario_cli_source
    assert "AgentCliApplicationBinding" in coding_source
    assert "run_agent_cli_application" in coding_source
    assert "run_standard_cli_operations" in coding_source
    assert "AgentCliSessionHostBinding" in coding_source
    assert "WorkspaceToolRuntimeSettings" in application_source
    assert "runtime_settings=runtime_settings" in coding_source
    assert "record_package_source_policy_denial" in package_diagnostics_source
    assert "record_package_source_policy_denial" in coding_source
    assert "_record_package_policy_diagnostic" not in coding_source
    assert "run_keyword_cli_turns" in agent_host_source
    assert "CliOperationSequence" not in coding_source
    assert "CliApplicationRuntime" not in coding_source
    assert "run_agent_cli_session_listing" not in coding_source
    assert "resolve_agent_cli_session" not in coding_source
    assert "collect_agent_cli_help_extension_flags" not in coding_source
    assert "def _run_list_sessions(" not in coding_source
    assert "def _run_list_models(" not in coding_source
    assert "def _run_command(" not in coding_source
    assert "def _runtime_args_for_bootstrap(" not in coding_source
    assert "def _resource_loader_options_from_args(" not in coding_source
    assert "def _report_settings_errors(" not in coding_source
    assert "Shared Contracts" in boundary
    assert "Dependency Rule" in boundary


def test_session_inspection_is_neutral_and_adopted() -> None:
    inspection_source = Path("src/loushang/harness/session/inspection.py").read_text(
        encoding="utf-8"
    )
    composition_source = Path("src/loushang/harness/session/composition.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/session-inspection-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in inspection_source
    assert "AgentSessionInspector" in composition_source
    assert not Path("src/loushang/coding/session/types.py").exists()
    assert "Product Binding" in boundary
    assert "Coding Binding" in boundary


def test_session_diagnostics_runtime_is_neutral_and_adopted() -> None:
    runtime_source = Path("src/loushang/harness/session/diagnostics.py").read_text(
        encoding="utf-8"
    )
    product_source = Path("src/loushang/harness/session/agent_product.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/session-diagnostics-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in runtime_source
    assert "SessionDiagnosticsRuntime" in product_source
    assert not Path(
        "src/loushang/coding/session/session_diagnostics_bridge.py"
    ).exists()
    assert "Product Binding" in boundary
    assert "Coding Binding" in boundary


def test_session_resource_refresh_runtime_is_neutral_and_adopted() -> None:
    runtime_source = Path("src/loushang/harness/session/resource_refresh.py").read_text(
        encoding="utf-8"
    )
    composition_source = Path("src/loushang/harness/session/composition.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/session-resource-refresh-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in runtime_source
    assert "SessionResourceRefreshRuntime" in composition_source
    assert not Path(
        "src/loushang/coding/session/resource_refresh_controller.py"
    ).exists()
    assert not Path("src/loushang/coding/session/resource_watcher.py").exists()
    assert "Product Binding" in boundary
    assert "Coding Binding" in boundary


def test_package_session_operations_are_neutral_and_adopted() -> None:
    operations_source = Path(
        "src/loushang/harness/resources/packages/operations.py"
    ).read_text(encoding="utf-8")
    diagnostics_source = Path(
        "src/loushang/harness/resources/packages/catalog_diagnostics.py"
    ).read_text(encoding="utf-8")
    controller_source = Path(
        "src/loushang/harness/resources/packages/session.py"
    ).read_text(encoding="utf-8")
    boundary = Path(
        "docs/internals/architecture/harness/package-session-operations-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in operations_source
    assert "loushang.coding" not in diagnostics_source
    assert "loushang.coding" not in controller_source
    assert "PackageOperationsRuntime" in controller_source
    assert "PackageCatalogDiagnosticsRecorder" in controller_source
    assert not Path("src/loushang/coding/session/package_controller.py").exists()
    assert "Product Binding" in boundary
    assert "Coding Binding" in boundary


def test_extension_input_runtime_is_harness_owned() -> None:
    source = Path("src/loushang/harness/extensions/agent/input.py").read_text(
        encoding="utf-8"
    )
    coding_input_adapter = Path(
        "src/loushang/harness/extensions/agent/input_adapter.py"
    ).read_text(encoding="utf-8")
    composition_source = Path("src/loushang/harness/session/composition.py").read_text(
        encoding="utf-8"
    )

    assert "ApplicationInputDeliveryPort" in source
    assert "loushang.coding" not in source
    assert "SessionManager" not in source
    assert "append_message(" not in source
    assert "customType" not in source
    assert "deliverAs" not in source
    assert "ExtensionInputAdapter" in coding_input_adapter
    assert "ExtensionInputRuntime" in composition_source


def test_product_transcript_session_is_neutral_and_adopted() -> None:
    session_source = Path(
        "src/loushang/harness/transcript/product_session.py"
    ).read_text(encoding="utf-8")
    coding_adapter_source = Path("src/loushang/coding/session_manager.py").read_text(
        encoding="utf-8"
    )
    boundary = Path(
        "docs/internals/architecture/harness/product-transcript-session-boundary.md"
    ).read_text(encoding="utf-8")

    assert "loushang.coding" not in session_source
    assert "ProductTranscriptSession" in coding_adapter_source
    assert "Standard Session Contract" in boundary


def test_tui_and_harness_keep_harnesstui_dependency_one_way() -> None:
    boundaries = (
        ImportBoundary(
            name="tui",
            root=Path("src/loushang/tui"),
            forbidden_prefixes=("loushang.harnesstui",),
        ),
        ImportBoundary(
            name="harness",
            root=Path("src/loushang/harness"),
            forbidden_prefixes=("loushang.harnesstui", "loushang.tui"),
        ),
    )

    offenders = [
        offender
        for boundary in boundaries
        for offender in _find_forbidden_imports(boundary)
    ]

    assert offenders == []


def test_continuity_core_and_common_tui_keep_product_boundaries() -> None:
    boundaries = (
        ImportBoundary(
            name="continuity core",
            root=Path("src/loushang/harness/continuity"),
            forbidden_prefixes=(
                "loushang.agent",
                "loushang.ai",
                "loushang.coding",
                "loushang.design",
                "loushang.method",
                "loushang.presentation",
                "loushang.tui",
                "loushang.work",
                "loushang.harness.conversation",
                "loushang.harness.journal",
                "loushang.harness.transcript",
                "loushang.harness.workspace",
            ),
        ),
        ImportBoundary(
            name="continuity tui",
            root=Path("src/loushang/harnesstui/continuity"),
            forbidden_prefixes=(
                "loushang.agent",
                "loushang.ai",
                "loushang.coding",
                "loushang.design",
                "loushang.presentation",
            ),
        ),
    )

    offenders = [
        offender
        for boundary in boundaries
        for offender in _find_forbidden_imports(boundary)
    ]

    assert offenders == []
    design = Path(
        "docs/internals/architecture/harness/"
        "capability-domain-presentation-continuity-architecture.md"
    ).read_text(encoding="utf-8")
    assert "Accepted and implemented for V1" in design
    assert "cross-Experience Host coordinator remains intentionally deferred" in design


def test_workspace_git_and_clipboards_have_canonical_owners() -> None:
    expected_imports = {
        Path("src/loushang/harness/session/footer.py"): {
            "loushang.harness.workspace.git.find_git_paths",
            "loushang.harness.workspace.git.get_git_branch",
        },
        Path("src/loushang/harnesstui/conversation/session_view.py"): {
            "loushang.harness.workspace.git.get_git_branch",
        },
        Path("src/loushang/coding/session/agent_session.py"): {
            "loushang.tui.clipboard.copy_to_clipboard",
        },
    }

    missing = [
        f"{path.as_posix()} missing {target}"
        for path, targets in expected_imports.items()
        for target in sorted(targets - set(_absolute_imports(path)))
    ]

    assert missing == []


def test_retired_coding_platform_capability_paths_stay_absent() -> None:
    retired = {
        "loushang.coding.platform.clipboard": Path(
            "src/loushang/coding/platform/clipboard.py"
        ),
        "loushang.coding.platform.clipboard_image": Path(
            "src/loushang/coding/platform/clipboard_image.py"
        ),
        "loushang.coding.platform.git": Path("src/loushang/coding/platform/git.py"),
    }

    assert [path.as_posix() for path in retired.values() if path.exists()] == []

    offenders = [
        f"{path.as_posix()} imports {imported}"
        for root in (Path("src"), Path("tests"), Path("examples"), Path("scripts"))
        for path in sorted(root.rglob("*.py"))
        for imported in _absolute_imports(path)
        if imported in retired
        or any(imported.startswith(f"{module}.") for module in retired)
    ]
    assert offenders == []

    package_source = Path("src/loushang/coding/platform/__init__.py").read_text(
        encoding="utf-8"
    )
    for retired_export in (
        "ClipboardCopyResult",
        "ClipboardImage",
        "copy_to_clipboard",
        "extension_for_image_mime_type",
        "get_git_branch",
        "read_clipboard_image",
    ):
        assert f'"{retired_export}"' not in package_source


def test_workspace_platform_capability_cutover_is_documented() -> None:
    boundary_path = Path(
        "docs/internals/architecture/harness/"
        "workspace-platform-capabilities-boundary.md"
    )
    boundary = boundary_path.read_text(encoding="utf-8")
    normalized_boundary = " ".join(boundary.split())

    for required in (
        "`loushang.harness.workspace.git`",
        "`loushang.tui.clipboard`",
        "`loushang.tui.clipboard_image`",
        "no compatibility facade is retained",
        "Harness and TUI therefore remain peers",
    ):
        assert required in normalized_boundary

    readme = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert boundary_path.name in readme


def test_tui_does_not_import_runtime_product_or_model_layers() -> None:
    boundary = ImportBoundary(
        name="tui",
        root=Path("src/loushang/tui"),
        forbidden_prefixes=(
            "loushang.agent",
            "loushang.ai",
            "loushang.coding",
            "loushang.harness",
            "loushang.harnesstui",
            "loushang.method",
            "loushang.work",
        ),
    )

    assert _find_forbidden_imports(boundary) == []


def test_importing_transcript_region_stays_tui_only() -> None:
    script = """
import importlib
import sys

importlib.import_module("loushang.tui.ui_parts.transcript")
forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
    "loushang.harness",
    "loushang.harnesstui",
    "loushang.method",
    "loushang.work",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_harnesstui_architecture_lists_stable_capability_entrypoints() -> None:
    path = Path("docs/internals/architecture/harnesstui/README.md")
    text = path.read_text(encoding="utf-8")

    assert "`loushang.coding.ui` -> `loushang.harnesstui`" in text
    assert "`loushang.harness` and `loushang.tui` are\nindependent peers" in text
    assert "`tests/coding/tui_support` -> `loushang.harnesstui.testing`" in text
    assert "`loushang.harnesstui.conversation.queue`" in text
    assert "`loushang.harnesstui.conversation.reader`" in text
    assert "`loushang.harnesstui.conversation.screen_app`" in text
    assert "`loushang.harnesstui.conversation.screen_frame`" in text
    assert "`loushang.harnesstui.conversation.screen_state`" in text
    assert "`loushang.harnesstui.conversation.window_budget`" in text
    assert "`loushang.harnesstui.conversation.source`" in text
    assert "`loushang.harnesstui.conversation.attachments`" in text
    assert "`loushang.harnesstui.conversation.control`" in text
    assert "`loushang.harnesstui.conversation.dispatch`" in text
    assert "`loushang.harnesstui.conversation.input`" in text
    assert "`loushang.harnesstui.conversation.run_context`" in text
    assert "`loushang.harnesstui.conversation.screen_runner`" in text
    assert "`loushang.harnesstui.conversation.application_host`" in text
    assert "`loushang.harnesstui.conversation.plain_app`" in text
    assert "`loushang.harnesstui.conversation.plain_prompt_host`" in text
    assert "`loushang.harnesstui.conversation.history`" in text
    assert "`loushang.harnesstui.conversation.transcript_display`" in text
    assert "`loushang.harnesstui.conversation.startup`" in text
    assert "`loushang.harnesstui.conversation.projection`" in text
    assert "`loushang.harnesstui.conversation.plain_target`" in text
    assert "`loushang.harnesstui.conversation.screen_target`" in text
    assert "`loushang.harnesstui.conversation.tool_transcript`" in text
    assert "`loushang.harnesstui.conversation.transcript_style`" in text
    assert "`loushang.harnesstui.plain.renderer`" in text
    assert "`loushang.harnesstui.commands.interaction`" in text
    assert "`loushang.harnesstui.commands.presentation`" in text
    assert "`loushang.harnesstui.commands.source`" in text
    assert "`loushang.harnesstui.selection.catalog`" in text
    assert "`loushang.harnesstui.selection.interaction`" in text
    assert "`loushang.harnesstui.selection.model`" in text
    assert "`loushang.harnesstui.settings.dashboard`" in text
    assert "`loushang.harnesstui.settings.model`" in text
    assert "`loushang.harnesstui.settings.page`" in text
    assert "`loushang.harnesstui.settings.workflow`" in text
    assert "`loushang.harnesstui.status.persistence`" in text
    assert "`loushang.harnesstui.status.settings`" in text
    assert "`loushang.harnesstui.status.line`" in text
    assert "`loushang.harnesstui.status.plain`" in text
    assert "`loushang.harnesstui.status.provider`" in text
    assert "`loushang.harnesstui.status.snapshot`" in text
    assert "`loushang.harnesstui.surface.controller`" in text
    assert "`loushang.harnesstui.surface.factory`" in text
    assert "`loushang.harnesstui.surface.view`" in text
    assert "`loushang.harnesstui.testing.action_host`" in text
    assert "`loushang.harnesstui.testing.ports`" in text
    assert "`loushang.harnesstui.testing.input_playback`" in text
    assert "`loushang.harnesstui.testing.performance`" in text
    assert "`loushang.harnesstui.testing.screen_loop_playback`" in text
    assert "`loushang.harnesstui.testing.render_scenario`" in text
    assert "`loushang.harnesstui.testing.scenarios.factory`" in text
    assert "`loushang.harnesstui.testing.scenarios`" in text
    assert "`tests/coding/tui_support`" in text
    assert "`loushang.tui.settings`" in text
    assert "`loushang.tui.ui_parts.transcript`" in text


def test_harnesstui_capability_entrypoints_exist() -> None:
    paths = (
        Path("src/loushang/harnesstui/conversation/attachments.py"),
        Path("src/loushang/harnesstui/conversation/control.py"),
        Path("src/loushang/harnesstui/conversation/dispatch.py"),
        Path("src/loushang/harnesstui/conversation/input.py"),
        Path("src/loushang/harnesstui/conversation/plain_target.py"),
        Path("src/loushang/harnesstui/conversation/projection.py"),
        Path("src/loushang/harnesstui/conversation/queue.py"),
        Path("src/loushang/harnesstui/conversation/reader.py"),
        Path("src/loushang/harnesstui/conversation/screen_app.py"),
        Path("src/loushang/harnesstui/conversation/screen_frame.py"),
        Path("src/loushang/harnesstui/conversation/screen_state.py"),
        Path("src/loushang/harnesstui/conversation/screen_target.py"),
        Path("src/loushang/harnesstui/conversation/run_context.py"),
        Path("src/loushang/harnesstui/conversation/screen_runner.py"),
        Path("src/loushang/harnesstui/conversation/source.py"),
        Path("src/loushang/harnesstui/conversation/tool_transcript.py"),
        Path("src/loushang/harnesstui/conversation/transcript_style.py"),
        Path("src/loushang/harnesstui/conversation/window_budget.py"),
        Path("src/loushang/harnesstui/plain/renderer.py"),
        Path("src/loushang/harnesstui/commands/interaction.py"),
        Path("src/loushang/harnesstui/commands/presentation.py"),
        Path("src/loushang/harnesstui/commands/source.py"),
        Path("src/loushang/harnesstui/selection/catalog.py"),
        Path("src/loushang/harnesstui/selection/interaction.py"),
        Path("src/loushang/harnesstui/selection/model.py"),
        Path("src/loushang/harnesstui/settings/dashboard.py"),
        Path("src/loushang/harnesstui/settings/model.py"),
        Path("src/loushang/harnesstui/settings/page.py"),
        Path("src/loushang/harnesstui/settings/workflow.py"),
        Path("src/loushang/harnesstui/status/line.py"),
        Path("src/loushang/harnesstui/status/persistence.py"),
        Path("src/loushang/harnesstui/status/plain.py"),
        Path("src/loushang/harnesstui/status/provider.py"),
        Path("src/loushang/harnesstui/status/settings.py"),
        Path("src/loushang/harnesstui/status/snapshot.py"),
        Path("src/loushang/harnesstui/surface/controller.py"),
        Path("src/loushang/harnesstui/surface/factory.py"),
        Path("src/loushang/harnesstui/surface/view.py"),
        Path("src/loushang/harnesstui/testing/action_host.py"),
        Path("src/loushang/harnesstui/testing/ports.py"),
        Path("src/loushang/harnesstui/testing/input_playback.py"),
        Path("src/loushang/harnesstui/testing/performance.py"),
        Path("src/loushang/harnesstui/testing/screen_loop_playback.py"),
        Path("src/loushang/harnesstui/testing/scenarios/factory.py"),
        Path("src/loushang/harnesstui/testing/scenarios/composer.py"),
        Path("src/loushang/harnesstui/testing/scenarios/lifecycle.py"),
        Path("src/loushang/harnesstui/testing/scenarios/terminal.py"),
        Path("src/loushang/harnesstui/testing/scenarios/transcript.py"),
        Path("src/loushang/harnesstui/testing/scenarios/surface.py"),
        Path("src/loushang/tui/settings.py"),
        Path("src/loushang/tui/ui_parts/transcript.py"),
    )

    missing = [path.as_posix() for path in paths if not path.is_file()]

    assert missing == []


def test_importing_conversation_interaction_entrypoints_stays_product_neutral() -> None:
    script = """
import importlib
import sys

for module_name in (
    "loushang.harnesstui.conversation.control",
    "loushang.harnesstui.conversation.dispatch",
    "loushang.harnesstui.conversation.input",
    "loushang.harnesstui.conversation.run_context",
    "loushang.harnesstui.conversation.screen_app",
    "loushang.harnesstui.conversation.screen_frame",
    "loushang.harnesstui.conversation.screen_runner",
    "loushang.harnesstui.conversation.transcript_style",
    "loushang.harnesstui.conversation.window_budget",
):
    importlib.import_module(module_name)

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
    "loushang.harness",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_importing_catalog_interaction_entrypoints_stays_product_neutral() -> None:
    script = """
import importlib
import sys

for module_name in (
    "loushang.harnesstui.commands.interaction",
    "loushang.harnesstui.commands.source",
    "loushang.harnesstui.selection.interaction",
):
    importlib.import_module(module_name)

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
    "loushang.harness",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_importing_surface_controller_stays_product_neutral() -> None:
    script = """
import importlib
import sys

importlib.import_module("loushang.harnesstui.surface.controller")
forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
    "loushang.harness",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_importing_harnesstui_testing_entrypoints_stays_product_neutral() -> None:
    script = """
import importlib
import sys

for module_name in (
    "loushang.harnesstui.testing.action_host",
    "loushang.harnesstui.testing.ports",
    "loushang.harnesstui.testing.input_playback",
    "loushang.harnesstui.testing.performance",
    "loushang.harnesstui.testing.screen_loop_playback",
    "loushang.harnesstui.testing.scenarios.factory",
    "loushang.harnesstui.testing.scenarios.composer",
    "loushang.harnesstui.testing.scenarios.lifecycle",
    "loushang.harnesstui.testing.scenarios.terminal",
    "loushang.harnesstui.testing.scenarios.transcript",
    "loushang.harnesstui.testing.scenarios.surface",
):
    importlib.import_module(module_name)

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
    "loushang.harness",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_importing_channel_types_does_not_eagerly_load_agent_or_ai() -> None:
    script = """
import importlib
import sys

importlib.import_module("loushang.channel.types")
forbidden = sorted(
    name
    for name in sys.modules
    if name == "loushang.agent"
    or name.startswith("loushang.agent.")
    or name == "loushang.ai"
    or name.startswith("loushang.ai.")
    or name == "loushang.work.agent_projection"
    or name == "loushang.work.projection"
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_importing_channel_public_api_loads_only_runtime_event_contracts_or_products() -> (
    None
):
    script = """
import importlib
import sys

importlib.import_module("loushang.channel")
forbidden = sorted(
    name
    for name in sys.modules
    if name == "loushang.agent"
    or name.startswith("loushang.agent.")
    or name == "loushang.ai"
    or name.startswith("loushang.ai.")
    or name == "loushang.coding"
    or name.startswith("loushang.coding.")
    or name == "loushang.harness.session"
    or name.startswith("loushang.harness.session.")
)
assert forbidden == [], forbidden
assert "loushang.harness.events.projection" in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_legacy_agent_harness_package_has_been_removed() -> None:
    assert not Path("src/loushang/agent/harness").exists()


def test_coding_message_legacy_package_and_imports_have_been_removed() -> None:
    assert not any(Path("src/loushang/coding/message").glob("*.py"))
    offenders = [
        f"{path.as_posix()} imports {imported}"
        for path in sorted(Path("src/loushang/coding").rglob("*.py"))
        for imported in _absolute_imports(path)
        if _matches_any(imported, ("loushang.coding.message",))
    ]
    assert offenders == []


def test_harness_slice1_symbols_are_not_top_level_exports() -> None:
    import loushang.harness as harness

    slice1_symbols = {
        "ApprovalDecision",
        "ApprovalRequest",
        "ApprovalResolver",
        "DenyApprovalResolver",
        "HeadlessApprovalResolver",
        "MaybeAwaitable",
        "ToolDefinitionResolver",
        "ToolContribution",
        "ToolDefinition",
        "ToolPackDefinition",
        "ToolRegistry",
        "ToolRenderContext",
        "ToolRenderResultOptions",
        "ToolRenderRuntime",
        "ToolResolutionDiagnostic",
        "ToolResolutionError",
        "ToolResolutionResult",
        "ToolResultPresentation",
        "collapse_text",
        "normalize_display_text",
        "normalize_line_endings",
        "resolve_approval",
        "resolve_tool_contributions",
        "strip_ansi",
        "tool",
    }

    assert slice1_symbols.isdisjoint(set(harness.__all__))


def test_harness_workspace_symbols_are_not_top_level_exports() -> None:
    import loushang.harness as harness

    workspace_symbols = {
        "ExecBackend",
        "ExecOutputChunk",
        "ExecRequest",
        "ExecResult",
        "ExecService",
        "ExecUpdateCallback",
        "LocalExecBackend",
        "TruncationResult",
        "truncate_head",
        "truncate_tail",
    }

    assert workspace_symbols.isdisjoint(set(harness.__all__))


def test_harness_sandbox_symbols_are_not_top_level_exports() -> None:
    import loushang.harness as harness

    sandbox_symbols = {
        "HostEnvironment",
        "HostEnvironmentProbe",
        "LocalHostEnvironmentProbe",
        "LocalSandboxService",
        "SandboxBackend",
        "SandboxBackendRegistry",
        "SandboxExecBackend",
        "SandboxScope",
        "SandboxService",
        "SandboxSettings",
    }

    assert sandbox_symbols.isdisjoint(set(harness.__all__))


def test_harness_authorization_values_do_not_depend_on_enforcement_or_products() -> None:
    import loushang.harness as harness

    assert _find_forbidden_imports(
        ImportBoundary(
            name="authorization values",
            root=Path("src/loushang/harness/authorization"),
            forbidden_prefixes=(
                "loushang.coding",
                "loushang.harness.sandbox",
                "loushang.method",
                "loushang.tui",
                "loushang.work",
            ),
        )
    ) == []
    assert {
        "EffectiveExecutionProfile",
        "ExecutionAuthorizationError",
    }.isdisjoint(set(harness.__all__))


def test_harness_contribution_symbols_are_not_top_level_exports() -> None:
    import loushang.harness as harness

    contribution_symbols = {
        "ContributionDescriptor",
        "ContributionRegistry",
        "ContributionType",
        "DuplicateContributionKeyError",
        "DuplicateExtensionSurfaceKeyError",
        "ExtensionInventory",
        "ExtensionSurfaceDescriptor",
        "ExtensionSurfaceType",
    }

    assert contribution_symbols.isdisjoint(set(harness.__all__))


def test_harness_context_and_journal_symbols_are_not_top_level_exports() -> None:
    import loushang.harness as harness

    context_symbols = {
        "CompactionBudget",
        "CompactionCoordinator",
        "ContextCompactionCoordinator",
        "ContextItem",
        "ContextPacker",
        "ContextUsageEstimate",
        "ContextSalienceRanker",
        "BranchGraph",
        "JsonProjectionIndex",
        "JsonlJournal",
        "LayeredConfig",
        "SummaryProfile",
        "TranscriptRepository",
        "calculate_compaction_budget",
    }

    assert context_symbols.isdisjoint(set(harness.__all__))


def test_harness_diagnostics_symbols_are_subpackage_exports_only() -> None:
    import loushang.harness as harness
    import loushang.harness.diagnostics as diagnostics

    diagnostic_symbols = {
        "DiagnosticDraft",
        "DiagnosticLevel",
        "DiagnosticBundleProfile",
        "DiagnosticPhase",
        "DiagnosticRecord",
        "DiagnosticSource",
        "DiagnosticSummary",
        "DiagnosticsQuery",
        "DiagnosticsService",
        "directory_available_startup_check",
        "collect_diagnostics",
        "DEFAULT_DIAGNOSTIC_BUNDLE_PROFILE",
        "DEFAULT_DIAGNOSTICS_LIMIT",
        "ErrorReport",
        "export_diagnostics_bundle",
        "path_exists",
        "resolve_export_output_path",
        "run_standard_startup_checks",
        "StartupCheck",
        "StartupCheckResult",
        "serialize_diagnostic",
        "serialize_diagnostic_summary",
        "serialize_error_report",
        "utc_now",
    }

    assert diagnostic_symbols.isdisjoint(set(harness.__all__))
    assert set(diagnostics.__all__) == diagnostic_symbols


def test_harness_host_symbols_are_not_package_exports() -> None:
    import loushang.harness as harness
    import loushang.harness.host as host

    host_symbols = {
        "HostInputQueue",
        "HostLifecycleEvent",
        "HostRuntime",
        "HostSnapshot",
        "HostStateError",
        "OrderedEventBus",
        "QueueSnapshot",
        "QueuedMessageSnapshot",
        "RunState",
    }

    assert host_symbols.isdisjoint(set(harness.__all__))
    assert host.__all__ == []


def test_product_runtime_core_symbols_are_not_top_level_exports() -> None:
    import loushang.harness as harness

    runtime_symbols = {
        "BoundProductRuntimeContext",
        "CoalescingScheduler",
        "ProductRuntimeBindings",
        "RuntimeBindingLease",
        "RuntimeBindingState",
        "SessionTransitionHost",
        "UnboundProductRuntimeContext",
    }

    assert runtime_symbols.isdisjoint(set(harness.__all__))


def test_agent_product_host_bindings_use_existing_shared_owners() -> None:
    boundaries = (
        ImportBoundary(
            name="Agent CLI host binding",
            root=Path("src/loushang/harness/cli/agent_host.py"),
            forbidden_prefixes=(
                "loushang.coding",
                "loushang.method",
                "loushang.tui",
                "loushang.work",
            ),
        ),
        ImportBoundary(
            name="Agent plain host binding",
            root=Path("src/loushang/harnesstui/conversation/agent_binding.py"),
            forbidden_prefixes=("loushang.coding",),
        ),
        ImportBoundary(
            name="session Work Channel binding",
            root=Path("src/loushang/work/channel.py"),
            forbidden_prefixes=("loushang.coding",),
        ),
    )
    assert [
        f"{boundary.name}: {boundary.root.as_posix()} imports {imported}"
        for boundary in boundaries
        for imported in _absolute_imports(boundary.root)
        if _matches_any(imported, boundary.forbidden_prefixes)
    ] == []

    cli_source = Path("src/loushang/coding/cli/__main__.py").read_text(encoding="utf-8")
    coding_work_source = Path("src/loushang/coding/domain/work.py").read_text(
        encoding="utf-8"
    )
    assert "host_binding.bind(host_runners)" in cli_source
    assert "run_agent_cli_session_host(" not in cli_source
    assert "run_keyword_cli_turns(" not in cli_source
    assert "run_coding_work_channel" in coding_work_source
    assert "SessionWorkHostPort" in cli_source
    assert not tuple(Path("src/loushang/coding/mode").glob("*.py"))


def test_conversation_runtime_core_symbols_are_not_top_level_exports() -> None:
    import loushang.harness as harness
    import loushang.harness.context.conversation as conversation_context
    import loushang.harness.conversation as conversation

    conversation_symbols = set(conversation.__all__)
    context_conversation_symbols = set(conversation_context.__all__)

    assert conversation_symbols.isdisjoint(set(harness.__all__))
    assert context_conversation_symbols.isdisjoint(set(harness.__all__))


def test_conversation_runtime_core_does_not_import_channel_implementations() -> None:
    boundaries = (
        ImportBoundary(
            name="conversation",
            root=Path("src/loushang/harness/conversation"),
            forbidden_prefixes=("loushang.channel",),
        ),
        ImportBoundary(
            name="conversation context",
            root=Path("src/loushang/harness/context"),
            forbidden_prefixes=("loushang.channel",),
        ),
    )

    offenders = [
        offender
        for boundary in boundaries
        for offender in _find_forbidden_imports(boundary)
    ]
    assert offenders == []


def test_coding_diagnostics_facades_are_extinct() -> None:
    legacy_symbols = (
        "loushang.coding.DiagnosticRecord",
        "loushang.coding.DiagnosticSummary",
        "loushang.coding.DiagnosticsQuery",
        "loushang.coding.DiagnosticsService",
        "loushang.coding.ErrorReport",
        "loushang.coding.StartupCheck",
        "loushang.coding.StartupCheckResult",
        "loushang.coding.diagnostics.DiagnosticLevel",
        "loushang.coding.diagnostics.DiagnosticPhase",
        "loushang.coding.diagnostics.DiagnosticRecord",
        "loushang.coding.diagnostics.DiagnosticSource",
        "loushang.coding.diagnostics.DiagnosticSummary",
        "loushang.coding.diagnostics.DiagnosticsQuery",
        "loushang.coding.diagnostics.DiagnosticsService",
        "loushang.coding.diagnostics.ErrorReport",
        "loushang.coding.diagnostics.StartupCheck",
        "loushang.coding.diagnostics.StartupCheckResult",
        "loushang.coding.diagnostics.service.DiagnosticsService",
        "loushang.coding.diagnostics.types.DiagnosticLevel",
        "loushang.coding.diagnostics.types.DiagnosticPhase",
        "loushang.coding.diagnostics.types.DiagnosticRecord",
        "loushang.coding.diagnostics.types.DiagnosticSource",
        "loushang.coding.diagnostics.types.DiagnosticSummary",
        "loushang.coding.diagnostics.types.DiagnosticsQuery",
        "loushang.coding.diagnostics.types.ErrorReport",
        "loushang.coding.diagnostics.types.StartupCheck",
        "loushang.coding.diagnostics.types.StartupCheckResult",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []
    assert not Path("src/loushang/coding/diagnostics/service.py").exists()
    assert not Path("src/loushang/coding/diagnostics/types.py").exists()


def test_harness_diagnostics_core_boundary_is_documented() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/diagnostics-core-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Diagnostics Core Boundary",
        "`loushang.harness.diagnostics.types`",
        "`loushang.harness.diagnostics.service`",
        "`loushang.harness.diagnostics.observability_bridge`",
        "canonical owners",
        "`harness.diagnostics.serialization`",
        "Coding's source-classification resolver",
        "must not import coding, method, work, TUI, AI, agent runtime, provider, observability, or product packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Diagnostics Core Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "`loushang.harness.diagnostics`" in inventory_text
    assert "diagnostics core implementation complete" in inventory_text


def test_harness_diagnostics_core_does_not_import_resources_or_observability() -> None:
    paths_and_forbidden_prefixes = (
        (
            Path("src/loushang/harness/diagnostics/types.py"),
            ("loushang.harness.resources", "loushang.observability"),
        ),
        (
            Path("src/loushang/harness/diagnostics/service.py"),
            ("loushang.harness.resources", "loushang.observability"),
        ),
        (
            Path("src/loushang/harness/diagnostics/observability_bridge.py"),
            ("loushang.coding",),
        ),
    )
    offenders = [
        f"{path.as_posix()} imports {imported}"
        for path, forbidden_prefixes in paths_and_forbidden_prefixes
        for imported in _absolute_imports(path)
        if _matches_any(imported, forbidden_prefixes)
    ]
    assert offenders == []


def test_diagnostic_draft_has_no_resource_specific_compatibility_api() -> None:
    legacy_names = (
        "ResourceDiagnostic",
        "normalize_resource_diagnostic",
        "record_resource_diagnostics",
    )
    offenders = [
        f"{path.as_posix()} contains {name}"
        for path in sorted(Path("src/loushang/harness").rglob("*.py"))
        for name in legacy_names
        if name in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_coding_shared_layer_migration_plan_is_documented() -> None:
    plan_path = Path(
        "docs/internals/architecture/harness/coding-shared-layer-migration-plan.md"
    )
    assert plan_path.exists()
    plan_text = " ".join(plan_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Coding To Shared-Layer Migration Plan",
        "Wave R: Owner And Duplicate Rebaseline",
        "ProductRuntimePlan",
        "Harness is not globally prohibited from importing Agent or AI",
        "Wave 1: Leaf Foundations",
        "Wave 2: Event And Extension Product Adapter Collapse",
        "Wave 3: Standard Session Capabilities And Command Subsets",
        "Wave 4: Session Composition And Bootstrap Transaction",
        "Wave 5: Channel, RPC, Print, And TUI Adapter Collapse",
        "Wave 6: Config, Shared Defaults, CLI, And Work/Method Cleanup",
        "Every capability batch uses three reviewable commits",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in plan_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Coding To Shared-Layer Migration Plan" in readme_text
    assert "Coding Shared-Layer Migration Ledger" in readme_text
    assert "Diagnostics Export Boundary" in readme_text

    ledger_text = Path(
        "docs/internals/architecture/harness/coding-shared-layer-migration-ledger.md"
    ).read_text(encoding="utf-8")
    assert "## Wave 1: Leaf Foundations" in ledger_text
    assert "`harness.diagnostics.export`" in ledger_text

    export_boundary_text = Path(
        "docs/internals/architecture/harness/diagnostics-export-boundary.md"
    ).read_text(encoding="utf-8")
    assert "redacts both text artifacts and JSON values" in export_boundary_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "Coding To Shared-Layer Migration Plan" in inventory_text

    subsystem_text = Path("docs/internals/architecture/subsystem.md").read_text(
        encoding="utf-8"
    )
    assert "### loushang-channel (target)" not in subsystem_text
    assert "该源码包已落地" in subsystem_text


def test_coding_context_budget_facades_are_extinct() -> None:
    legacy_symbols = (
        "loushang.coding.ContextUsageEstimate",
        "loushang.coding.compaction.CompactionBudget",
        "loushang.coding.compaction.ContextUsageEstimate",
        "loushang.coding.compaction.calculate_compaction_budget",
        "loushang.coding.compaction.policy.CompactionBudget",
        "loushang.coding.compaction.policy.calculate_compaction_budget",
        "loushang.coding.compaction.types.ContextUsageEstimate",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []
    assert not Path("src/loushang/coding/compaction/policy.py").exists()


def test_harness_context_budget_and_accounting_boundary_is_documented() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/context-budget-accounting-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Context Budget And Accounting Boundary",
        "`loushang.harness.context.budget`",
        "`loushang.harness.context.usage`",
        "canonical owners",
        "This migration establishes budget and accounting ownership only",
        "must not import coding, method, work, TUI, AI, agent runtime, provider, or product packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Context Budget And Accounting Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "`loushang.harness.context`" in inventory_text
    assert "context budget and accounting implementation complete" in inventory_text


def test_harness_context_compaction_and_journal_design_is_documented() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/context-compaction-journal-foundations.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Context, Compaction, And Journal Foundations",
        "Status: implementation complete for integration into `lane/harness`",
        "`RecentWindowStrategy`",
        "`RollingSummaryStrategy`",
        "`CodingCompactionStrategy`",
        "`JournalFormatProfile`",
        "`JournalDurabilityProfile`",
        "`JournalLoadPolicy`",
        "context compaction changes the bounded projection sent to a model and never deletes source journal records",
        "journal-offset checkpoints, destructive journal vacuum, and retention remain deferred",
        "AI owns the stable base-message and message-part codec",
        "Agent owns the extension-message codec protocol and registry",
        "Work adopts only common JSONL I/O in the first wave",
        "three delivery batches for foundation, engines, and product cutover",
        "No type-only, protocol-only, codec-only, or single-adapter change counts as a finished delivery batch",
        "remove the replaced Coding and Work implementations in the same batch as their adapters",
        "must not depend on context",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Context, Compaction, And Journal Foundations" in readme_text

    inventory_text = " ".join(
        Path(
            "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
        )
        .read_text(encoding="utf-8")
        .split()
    )
    assert (
        "context, compaction, journal, and branch implementation complete"
        in inventory_text
    )
    assert "rebuildable generic JSON projection indexes" in inventory_text


def test_context_compaction_and_journal_mechanics_use_harness_owners() -> None:
    expected_imports = {
        Path("src/loushang/harness/transcript/jsonl_file.py"): {
            "loushang.harness.conversation.ConversationJsonlHeaderCodec",
            "loushang.harness.conversation.ConversationJsonlRecordCodec",
            "loushang.harness.journal.JsonlJournal",
            "loushang.harness.journal.journal_file_lock",
        },
        Path("src/loushang/coding/session_manager.py"): {
            "loushang.harness.transcript.AgentTranscriptLifecycle",
            "loushang.harness.transcript.AgentTranscriptSessionFactory",
            "loushang.harness.transcript.ProductTranscriptSession",
        },
        Path("src/loushang/work/event_log.py"): {
            "loushang.harness.journal.FunctionalJournalRecordCodec",
            "loushang.harness.journal.JsonlJournal",
        },
    }

    missing: list[str] = []
    for path, required in expected_imports.items():
        imports = set(_absolute_imports(path))
        missing.extend(
            f"{path.as_posix()} missing {name}" for name in sorted(required - imports)
        )
    assert missing == []


def test_harness_agent_transcript_file_store_is_documented() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/agent-transcript-file-store-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Agent Transcript File Store Boundary",
        "implementation complete for integration into `lane/harness`",
        "`AgentTranscriptFileLayout`",
        "`ConversationStore[ConversationHeader, AgentTranscriptRecord]`",
        "`AgentTranscriptSession`",
        "accepts only `ConversationHeader.version == 1`",
        "The normal native loader never performs implicit migration",
        "does not implement SQL, Redis, outbox delivery, or extension-owned persistence providers",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Agent Transcript File Store Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "Conversation JSONL Agent transcript codec" in inventory_text


def test_harness_agent_transcript_catalog_is_documented_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/agent-transcript-catalog-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Agent Transcript Catalog Boundary",
        "`AgentTranscriptSessionCatalog`",
        "`SessionSummary`",
        "`ConversationCatalog`",
        "does not create another repository or replay implementation",
        "must not import Coding",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Agent Transcript Catalog Boundary" in readme_text

    catalog_imports = set(
        _absolute_imports(Path("src/loushang/harness/transcript/session_catalog.py"))
    )
    assert "loushang.harness.conversation.ConversationCatalog" in catalog_imports
    assert not any(
        imported.startswith("loushang.coding") for imported in catalog_imports
    )

    directory_runtime_imports = set(
        _absolute_imports(Path("src/loushang/harness/transcript/directory.py"))
    )
    assert (
        "loushang.harness.transcript.session_catalog.AgentTranscriptSessionCatalog"
        in (directory_runtime_imports)
    )
    assert not any(
        imported.startswith("loushang.coding") for imported in directory_runtime_imports
    )

    session_manager_imports = set(
        _absolute_imports(Path("src/loushang/coding/session_manager.py"))
    )
    assert (
        "loushang.harness.transcript.ProductTranscriptSession"
        in session_manager_imports
    )

    runtime_source = Path(
        "src/loushang/coding/runtime/agent_session_runtime.py"
    ).read_text(encoding="utf-8")
    assert "class AgentSessionRuntime(" in runtime_source
    assert "AgentProductSessionRuntime[AgentSession, SessionManager]" in runtime_source
    assert "build_agent_product_session_runtime_ports(" not in runtime_source
    assert "ProductSessionRuntimePorts(" not in runtime_source
    assert "ProductTranscriptSessionBinding(" not in runtime_source
    assert "build_agent_session_lifecycle_hooks(" not in runtime_source
    assert "SessionManager.list_summaries" not in runtime_source
    assert "SessionManager.refresh_index" not in runtime_source
    assert "def _create_transcript_session(" not in runtime_source
    assert "def _restore_transcript_session(" not in runtime_source
    assert "def _fork_transcript_session(" not in runtime_source
    assert "def _before_lifecycle_transition(" not in runtime_source
    assert "def _after_lifecycle_commit(" not in runtime_source


def test_harness_agent_transcript_lifecycle_is_documented_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/agent-transcript-lifecycle-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Agent Transcript Lifecycle Boundary",
        "`AgentTranscriptLifecycle`",
        "`AgentTranscriptLifecycleContext`",
        "`AgentTranscriptRuntimeBinding`",
        "does not import Coding",
        "exactly once",
        "Detached restore therefore never mutates its source file",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Agent Transcript Lifecycle Boundary" in readme_text

    lifecycle_imports = set(
        _absolute_imports(Path("src/loushang/harness/transcript/lifecycle.py"))
    )
    assert not any(
        imported.startswith("loushang.coding") for imported in lifecycle_imports
    )

    session_manager_imports = set(
        _absolute_imports(Path("src/loushang/coding/session_manager.py"))
    )
    assert (
        "loushang.harness.transcript.AgentTranscriptLifecycle"
        in session_manager_imports
    )


def test_harness_agent_transcript_session_factory_is_documented_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/agent-transcript-session-factory-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Agent Transcript Session Factory Boundary",
        "`AgentTranscriptSessionFactory`",
        "does not import Coding",
        "detached copy",
        "runtime binding",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Agent Transcript Session Factory Boundary" in readme_text

    factory_imports = set(
        _absolute_imports(Path("src/loushang/harness/transcript/session_factory.py"))
    )
    assert not any(
        imported.startswith("loushang.coding") for imported in factory_imports
    )

    session_manager_imports = set(
        _absolute_imports(Path("src/loushang/coding/session_manager.py"))
    )
    assert (
        "loushang.harness.transcript.AgentTranscriptSessionFactory"
        in session_manager_imports
    )


def test_harness_runtime_data_foundations_are_documented_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/runtime-data-foundations.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Runtime Data Foundations",
        "`harness/runtime-data-foundations`",
        "`loushang.harness.conversation.ConversationRepository[H, R]`",
        "`JsonConversationIndex[P, Q]`",
        "`loushang.harness.config.LayeredConfig[T]`",
        "`ContextSalienceRanker`",
        "`SummaryProfile`",
        "Only the separate optional Agent transcript profile serializes Agent messages",
        "Harness never stores credentials",
        "No type-only, protocol-only, or duplicate parallel implementation counts as a completed batch",
        "Lack of a second production consumer is not a blocking gate",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Runtime Data Foundations" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "parent-linked transcript repositories" in inventory_text
    assert "`loushang.harness.config`" in inventory_text
    assert "summary-profile mechanics" in inventory_text
    assert "SummaryResourceOperations" in inventory_text

    expected_imports = {
        Path("src/loushang/coding/session_manager.py"): {
            "loushang.harness.transcript.ProductTranscriptSession",
        },
        Path("src/loushang/harness/config/agent/manager.py"): {
            "loushang.harness.config.LayeredConfig",
        },
        Path("src/loushang/harness/transcript/compaction.py"): {
            "loushang.harness.context.ConversationCompactionPlanner",
        },
        Path("src/loushang/harness/transcript/summarization.py"): {
            "loushang.harness.context.SummaryProfile",
            "loushang.harness.context.build_summary_prompt",
        },
        Path("src/loushang/harness/context/summary_evaluation.py"): {
            "loushang.harness.context.summary.SummaryProfile",
            "loushang.harness.context.summary.validate_summary",
        },
    }
    missing: list[str] = []
    for path, required in expected_imports.items():
        imports = set(_absolute_imports(path))
        missing.extend(
            f"{path.as_posix()} missing {name}" for name in sorted(required - imports)
        )
    assert missing == []

    assert not Path("src/loushang/coding/compaction/summary_quality.py").exists()
    summary_evaluation_imports = set(
        _absolute_imports(Path("src/loushang/harness/context/summary_evaluation.py"))
    )
    assert not any(
        imported.startswith("loushang.coding")
        for imported in summary_evaluation_imports
    )

    assert "Summary Evaluation Boundary" in readme_text
    summary_evaluation_design = Path(
        "docs/internals/architecture/harness/summary-evaluation-boundary.md"
    )
    assert summary_evaluation_design.exists()
    assert "SummaryResourceOperations" in summary_evaluation_design.read_text(
        encoding="utf-8"
    )

    assert "import json" not in Path("src/loushang/work/event_log.py").read_text(
        encoding="utf-8"
    )


def test_product_configuration_runtime_boundary_is_documented_and_adopted() -> None:
    import loushang.harness as harness
    from loushang.coding.control import (
        ControlConfig as CodingControlConfig,
    )
    from loushang.coding.control import (
        SettingsManager as CodingSettingsManager,
    )
    from loushang.harness.config.agent import ControlConfig, SettingsManager

    design_path = Path(
        "docs/internals/architecture/harness/product-configuration-runtime-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Product Configuration Runtime Boundary",
        "`loushang.harness.config`",
        "`ConfigFieldSpec[T]`",
        "`SchemaConfigCodec`",
        "`ScopedConfigRuntime`",
        "`ConfigActivationRuntime`",
        "`ConfigValueResolver`",
        "Harness configuration never stores credentials",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Product Configuration Runtime Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "`loushang.harness.config`" in inventory_text
    assert "### Product Configuration Runtime" in inventory_text
    assert "`harness/product-configuration-runtime`" in inventory_text
    assert (
        "Keep `coding.control` frozen during runtime consolidation."
        not in inventory_text
    )

    expected_imports = {
        Path("src/loushang/harness/config/agent/manager.py"): {
            "loushang.harness.config.ConfigFieldSpec",
            "loushang.harness.config.LayeredConfig",
            "loushang.harness.config.SchemaConfigCodec",
            "loushang.harness.config.ScopedConfigRuntime",
        },
        Path("src/loushang/coding/bootstrap.py"): {
            "loushang.harness.session.AgentProductConstructionBinding",
        },
    }
    missing: list[str] = []
    for path, required in expected_imports.items():
        imports = set(_absolute_imports(path))
        missing.extend(
            f"{path.as_posix()} missing {name}" for name in sorted(required - imports)
        )
    assert missing == []
    assert not Path("src/loushang/coding/control/settings_manager.py").exists()
    assert not Path("src/loushang/coding/control/types.py").exists()
    assert not Path("src/loushang/coding/control/config_value.py").exists()
    config_values = Path("src/loushang/harness/config/values.py").read_text(
        encoding="utf-8"
    )
    for symbol in ("class ConfigValueResolver",):
        assert symbol in config_values
    subprocess_values = Path(
        "src/loushang/harness/config/subprocess_values.py"
    ).read_text(encoding="utf-8")
    for symbol in (
        "class SubprocessConfigValueResolver",
        "def resolve_subprocess_config_value",
    ):
        assert symbol in subprocess_values
    assert CodingControlConfig is ControlConfig
    assert CodingSettingsManager is SettingsManager

    assert (
        _find_forbidden_imports(
            ImportBoundary(
                name="harness config product boundary",
                root=Path("src/loushang/harness/config"),
                forbidden_prefixes=("loushang.coding",),
            )
        )
        == []
    )
    agent_profile_paths = frozenset(
        path.as_posix()
        for path in Path("src/loushang/harness/config/agent").rglob("*.py")
    )
    assert (
        _find_forbidden_imports(
            ImportBoundary(
                name="neutral harness config",
                root=Path("src/loushang/harness/config"),
                forbidden_prefixes=("loushang.ai", "loushang.agent"),
                allowed_paths=agent_profile_paths,
            )
        )
        == []
    )

    value_imports = _absolute_imports(Path("src/loushang/harness/config/values.py"))
    assert not any(
        _matches_any(imported, ("subprocess",)) for imported in value_imports
    )

    config_symbols = {
        "ConfigActivationRuntime",
        "ConfigFieldSpec",
        "ConfigValueResolver",
        "LayeredConfig",
        "SchemaConfigCodec",
        "ScopedConfigRuntime",
    }
    assert config_symbols.isdisjoint(set(harness.__all__))


def test_harness_conversation_runtime_core_is_documented_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/conversation-runtime-core-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Conversation Runtime Core Boundary",
        "Status: implementation complete for integration into `lane/harness`",
        "`ConversationRepository`",
        "`ConversationReplayFolder`",
        "`ConversationCatalog`",
        "`ConversationCompactionPlanner`",
        "`CommandExecutionRecord`",
        "These neutral conversation packages must not import Coding, Agent, AI messages, model/provider code, Product stores, Method, Work, TUI, or channel implementations",
        "the neutral core owns control mechanics, the optional Agent profile owns common Agent transcript meanings",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Conversation Runtime Core Boundary" in readme_text

    coding_store_imports = {
        imported
        for path in (Path("src/loushang/coding/session_manager.py"),)
        for imported in _absolute_imports(path)
    }
    assert "loushang.harness.transcript.ProductTranscriptSession" in (
        coding_store_imports
    )
    assert "loushang.harness.journal.TranscriptRepository" not in (coding_store_imports)
    assert "loushang.harness.journal.BranchGraph" not in coding_store_imports

    harness_compaction_imports = set(
        _absolute_imports(Path("src/loushang/harness/transcript/compaction.py"))
    )
    assert "loushang.harness.context.ConversationCompactionPlanner" in (
        harness_compaction_imports
    )

    coding_compaction_imports = set(
        _absolute_imports(Path("src/loushang/coding/compaction/adapter.py"))
    )
    assert "loushang.harness.context.ConversationCompactionPlanner" not in (
        coding_compaction_imports
    )


def test_conversation_persistence_has_one_native_writer_boundary() -> None:
    roots = (
        Path("src/loushang/harness/conversation"),
        Path("src/loushang/harness/transcript"),
    )
    allowed = {
        Path("src/loushang/harness/conversation/stores/file.py"),
        Path("src/loushang/harness/transcript/jsonl_file.py"),
    }
    writer_calls = {"append_jsonl_record", "write_jsonl"}
    offenders: list[str] = []
    for path in sorted(
        file_path
        for root in roots
        for file_path in root.rglob("*.py")
        if file_path not in allowed
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in writer_calls:
                offenders.append(f"{path.as_posix()} calls {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "rewrite":
                offenders.append(f"{path.as_posix()} calls rewrite")

    assert offenders == []
    assert not any(Path("src/loushang/harness/storage").glob("*.py"))
    assert not Path("src/loushang/harness/journal/branch.py").exists()
    assert not Path("src/loushang/harness/journal/transcript.py").exists()
    assert not Path("src/loushang/harness/journal/index.py").exists()
    assert not Path("src/loushang/harness/transcript/store.py").exists()
    assert not Path("src/loushang/harness/transcript/file_store.py").exists()
    assert not Path("src/loushang/harness/transcript/catalog.py").exists()


def test_agent_session_catalog_uses_bound_store_discovery() -> None:
    path = Path("src/loushang/harness/transcript/session_catalog.py")
    source = path.read_text(encoding="utf-8")
    imports = set(_absolute_imports(path))

    assert "AgentTranscriptSessionCatalog" in source
    assert "ConversationProviderBinding" in source
    assert "create_agent_transcript_file_store" in source
    assert ".glob(" not in source
    assert "load_agent_transcript_repository" not in source
    assert not any(
        imported.startswith("loushang.harness.journal") for imported in imports
    )


def test_coding_internal_contribution_imports_use_harness_owner() -> None:
    legacy_symbols = (
        "loushang.coding.extensions.contributions.ContributionDescriptor",
        "loushang.coding.extensions.contributions.ContributionRegistry",
        "loushang.coding.extensions.contributions.ContributionType",
        "loushang.coding.extensions.contributions.DuplicateContributionKeyError",
        "loushang.coding.extensions.contributions.DuplicateExtensionSurfaceKeyError",
        "loushang.coding.extensions.contributions.ExtensionInventory",
        "loushang.coding.extensions.contributions.ExtensionSurfaceDescriptor",
        "loushang.coding.extensions.contributions.ExtensionSurfaceType",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []
    assert not Path("src/loushang/coding/extensions/contributions.py").exists()


def test_harness_contribution_inventory_boundary_is_documented() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/contribution-inventory-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Contribution Inventory Boundary",
        "`loushang.harness.contributions`",
        "same harness-owned classes",
        "`surfaces_from_loaded_extension`",
        "`loushang.harness.extensions.contributions`",
        "must not import coding, method, work, TUI, AI, agent runtime, provider, or product packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Contribution Inventory Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "`loushang.harness.contributions`" in inventory_text
    assert "contribution inventory implementation complete" in inventory_text


def test_harness_extension_runtime_core_boundary_is_documented() -> None:
    import loushang.harness as harness
    import loushang.harness.extensions as extensions

    design_path = Path(
        "docs/internals/architecture/harness/extension-runtime-core-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Extension Runtime Core Boundary",
        "`loushang.harness.extensions`",
        "`ExtensionContributionAPI`",
        "`ExtensionRuntime`",
        "`ExtensionSessionRuntime`",
        "The optional Agent profile owns",
        "Products keep",
        "neutral modules directly under `loushang.harness.extensions` must not",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    assert set(extensions.__all__) == {
        "ExtensionProviderRuntime",
        "ProviderFactory",
        "provider_from_extension_config",
    }
    assert "ExtensionContributionAPI" not in harness.__all__

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Extension Runtime Core Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "extension runtime core implementation" in inventory_text
    assert "Wave 2: Extension Runtime Core" in inventory_text

    runner_imports = set(
        _absolute_imports(Path("src/loushang/harness/extensions/agent/runner.py"))
    )
    assert "loushang.harness.extensions.runner.ExtensionRunner" in runner_imports

    runtime_path = Path("src/loushang/harness/extensions/runtime.py")
    forbidden_prefixes = (
        "loushang.coding",
        "loushang.design",
        "loushang.method",
        "loushang.ppt",
        "loushang.research",
        "loushang.tui",
        "loushang.work",
    )
    offenders = [
        imported
        for imported in _absolute_imports(runtime_path)
        if _matches_any(imported, forbidden_prefixes)
    ]
    assert offenders == []

    session_extension_paths = (
        Path("src/loushang/harness/extensions/session_runtime.py"),
        Path("src/loushang/harness/extensions/agent/lifecycle.py"),
        Path("src/loushang/harness/extensions/agent/hooks.py"),
        Path("src/loushang/harness/extensions/agent/input.py"),
    )
    for path in session_extension_paths:
        imports = _absolute_imports(path)
        assert not any(imported.startswith("loushang.coding") for imported in imports)


def test_harness_extension_context_runtime_is_documented_and_adopted() -> None:
    from loushang.harness.extensions.context import (
        BoundExtensionContext,
        ExtensionContext,
        ExtensionUiContext,
        UnboundExtensionContext,
    )
    from loushang.harness.host.rpc import RpcExtensionUIContext

    design_path = Path(
        "docs/internals/architecture/harness/extension-context-runtime-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Extension Context Runtime Boundary",
        "`ExtensionContext`",
        "`ExtensionRuntimeBindings`",
        "snake_case only",
        "Pi-style aliases",
        "not a Python extension method name",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    pi_ui_aliases = {
        "setStatus",
        "setWidget",
        "setTitle",
        "setEditorText",
        "pasteToEditor",
        "getEditorText",
        "onTerminalInput",
        "setWorkingMessage",
        "setWorkingVisible",
        "setWorkingIndicator",
        "setHiddenThinkingLabel",
        "setFooter",
        "setHeader",
        "addAutocompleteProvider",
        "setEditorComponent",
        "getAllThemes",
        "getTheme",
        "setTheme",
        "getToolsExpanded",
        "setToolsExpanded",
    }
    for context_type in (
        ExtensionUiContext,
        ExtensionContext,
        BoundExtensionContext,
        UnboundExtensionContext,
        RpcExtensionUIContext,
    ):
        assert pi_ui_aliases.isdisjoint(set(context_type.__dict__))

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Extension Context Runtime Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "snake_case context API is the sole extension API" in inventory_text

    runner_imports = set(
        _absolute_imports(Path("src/loushang/harness/extensions/agent/runner.py"))
    )
    assert "loushang.harness.extensions.runner.ExtensionRunner" in runner_imports
    assert "loushang.harness.extensions.agent.loader.ExtensionLoader" in runner_imports


def test_harness_control_plane_runtime_boundary_is_documented() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/control-plane-runtime-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Control Plane Runtime Boundary",
        "`loushang.harness.extensions.routing`",
        "`PolicyEvaluatorChain`",
        "`ApprovalBroker`",
        "Products and OEM adapters continue to own:",
        "Harness must not import Coding, Design, Research, PPT, Cowork, Method, Work, Channel, TUI, AI",
        "No compatibility module may retain a parallel routing, pending-request, command normalization, or rule-evaluation implementation",
        "top-level `loushang.harness.__all__` remains unchanged",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    design_link = "[Control Plane Runtime Boundary](control-plane-runtime-boundary.md)"
    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert design_link in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert design_link in inventory_text
    assert "Wave 2 Follow-On: Control Plane Runtime" in inventory_text


def test_harness_control_plane_symbols_are_not_top_level_exports() -> None:
    import loushang.harness as harness

    control_plane_symbols = {
        "ApprovalBroker",
        "ApprovalPresenter",
        "ApprovalRequestCollisionError",
        "CommandPolicySubject",
        "CommandSubstringMatcher",
        "CommandTokenSequenceMatcher",
        "CustomPolicySubject",
        "ExactToolNameMatcher",
        "ExtensionContextFactory",
        "ExtensionRouteError",
        "ExtensionRoutePlan",
        "ExtensionRouter",
        "ExtensionRuntimeErrorHandler",
        "IncompleteCommandMatcher",
        "PathPolicySubject",
        "PathSubstringMatcher",
        "PolicyChainStrategy",
        "PolicyDisposition",
        "PolicyEvaluationError",
        "PolicyEvaluator",
        "PolicyEvaluatorChain",
        "PolicyMatcher",
        "PolicyRule",
        "RegisteredExtensionHandler",
        "ResolvedControlContributions",
        "ResolvedExtensionRoute",
        "RouteErrorPolicy",
        "RouteReducer",
        "RouteStep",
        "RulePolicyEvaluator",
        "ShellPayloadSubstringMatcher",
        "ToolPolicySubject",
        "build_path_policy_subjects",
        "build_tool_policy_subject",
        "ensure_approval_action_id",
        "evaluate_policy",
        "normalize_command_subject",
        "resolve_control_contributions",
    }

    assert control_plane_symbols.isdisjoint(set(harness.__all__))


def test_policy_and_approval_have_only_harness_owners() -> None:
    retired_policy_root = Path("src/loushang/coding/policy")
    assert not tuple(retired_policy_root.glob("*.py"))

    owner_names = {
        "ApprovalDecision",
        "ApprovalRequest",
        "ApprovalResolver",
        "HeadlessApprovalResolver",
        "InteractiveApprovalResolver",
        "PolicyDecision",
        "PolicyEngine",
    }
    reimplementations: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=path.as_posix(),
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in owner_names:
                reimplementations.append(f"{path.as_posix()} defines {node.name}")
    assert reimplementations == []

    retired_prefix = "loushang.coding.policy"
    offenders: list[str] = []
    for root in (Path("src"), Path("tests"), Path("examples")):
        for path in sorted(root.rglob("*.py")):
            for imported in _absolute_imports(path):
                if imported == retired_prefix or imported.startswith(
                    f"{retired_prefix}."
                ):
                    offenders.append(f"{path.as_posix()} imports {imported}")
    assert offenders == []

    import loushang.coding as coding

    assert owner_names.isdisjoint(coding.__all__)

    shared_policy_path = Path("src/loushang/harness/policy_engine.py")
    shared_policy_imports = set(_absolute_imports(shared_policy_path))
    assert not any(
        _matches_any(imported, ("loushang.coding", "loushang.design", "loushang.ppt"))
        for imported in shared_policy_imports
    )

    extension_paths = (
        Path("src/loushang/harness/extensions/agent/runner.py"),
        Path("src/loushang/harness/extensions/agent/hooks.py"),
    )
    extension_imports = {
        imported for path in extension_paths for imported in _absolute_imports(path)
    }
    assert {
        "loushang.harness.extensions.routing.ExtensionRoutePlan",
        "loushang.harness.extensions.routing.ExtensionRouter",
    }.issubset(extension_imports)

    route_calls: set[str] = set()
    route_function_names: set[str] = set()
    for path in extension_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        route_calls.update(
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        )
        route_function_names.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        )
    assert {"from_extensions", "intercept", "observe", "reduce"}.issubset(route_calls)
    assert {
        "_order_routes",
        "_route_order_key",
        "_strongly_connected_components",
        "_topological_sort",
    }.isdisjoint(route_function_names)


def test_harness_control_plane_modules_do_not_import_product_layers() -> None:
    control_plane_paths = (
        Path("src/loushang/harness/approval.py"),
        Path("src/loushang/harness/policy.py"),
        Path("src/loushang/harness/extensions/control.py"),
        Path("src/loushang/harness/extensions/routing.py"),
    )
    assert [path.as_posix() for path in control_plane_paths if not path.exists()] == []

    forbidden_prefixes = (
        "loushang.ai",
        "loushang.channel",
        "loushang.coding",
        "loushang.cowork",
        "loushang.design",
        "loushang.method",
        "loushang.ppt",
        "loushang.research",
        "loushang.tui",
        "loushang.work",
    )
    offenders = [
        f"{path.as_posix()} imports {imported}"
        for path in control_plane_paths
        for imported in _absolute_imports(path)
        if _matches_any(imported, forbidden_prefixes)
    ]
    assert offenders == []


def test_agent_extension_profile_binds_neutral_harness_owners() -> None:
    from loushang.harness.extensions.agent.loader import ExtensionLoader as AgentLoader
    from loushang.harness.extensions.agent.policy import (
        ExtensionPolicyDecision as AgentPolicyDecision,
    )
    from loushang.harness.extensions.loader import ExtensionLoader as HarnessLoader
    from loushang.harness.extensions.types import (
        ExtensionPolicyDecision as HarnessPolicyDecision,
    )

    assert issubclass(AgentLoader, HarnessLoader)
    assert AgentPolicyDecision is HarnessPolicyDecision


def test_coding_exec_facade_is_extinct() -> None:
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if imported.startswith("loushang.coding.exec"):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []
    assert not Path("src/loushang/coding/exec").exists()


def test_coding_internal_workspace_operation_imports_use_harness_owner() -> None:
    legacy_symbols = (
        "loushang.coding.tools.operations.EditOperations",
        "loushang.coding.tools.operations.FindOperations",
        "loushang.coding.tools.operations.GrepOperations",
        "loushang.coding.tools.operations.LOCAL_TOOL_OPERATIONS",
        "loushang.coding.tools.operations.LocalToolOperations",
        "loushang.coding.tools.operations.LsOperations",
        "loushang.coding.tools.operations.ReadOperations",
        "loushang.coding.tools.operations.ToolOperations",
        "loushang.coding.tools.operations.WriteOperations",
        "loushang.coding.tools.operations.resolve_operation",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_harness_workspace_operation_boundary_is_documented() -> None:
    import loushang.harness as harness

    operation_symbols = {
        "EditOperations",
        "FindOperations",
        "GrepOperations",
        "LOCAL_TOOL_OPERATIONS",
        "LocalToolOperations",
        "LsOperations",
        "OperationResult",
        "ReadOperations",
        "ToolOperations",
        "WriteOperations",
        "resolve_operation",
    }
    assert operation_symbols.isdisjoint(set(harness.__all__))

    design_path = Path(
        "docs/internals/architecture/harness/workspace-operation-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Workspace Operation Boundary",
        "`loushang.harness.workspace.operations`",
        "The focused harness module is the public owner",
        "`loushang.coding.tools.operations` is removed",
        "does not select an allowed root",
        "must not import coding, method, work, TUI, AI, provider, or product packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Workspace Operation Boundary" in readme_text


def test_coding_internal_mutation_queue_imports_use_harness_owner() -> None:
    legacy_symbols = (
        "loushang.coding.tools.file_mutation_queue.run_with_file_mutation_queue",
        "loushang.coding.tools.file_mutation_queue.with_file_mutation_queue",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_harness_workspace_path_and_mutation_boundary_is_documented() -> None:
    import loushang.harness as harness

    path_mutation_symbols = {
        "PathNormalizer",
        "PathVariantProvider",
        "canonicalize_workspace_path",
        "expand_user_path",
        "normalize_unicode_spaces",
        "resolve_path_from_cwd",
        "resolve_workspace_path",
        "run_with_file_mutation_queue",
        "user_input_path_variants",
        "with_file_mutation_queue",
    }
    assert path_mutation_symbols.isdisjoint(set(harness.__all__))

    design_path = Path(
        "docs/internals/architecture/harness/workspace-path-mutation-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Workspace Path And Mutation Boundary",
        "`loushang.harness.workspace.paths`",
        "`loushang.harness.workspace.mutation_queue`",
        "The engine does not enable product syntax or correction policy by itself",
        "Coding's product tool pack chooses its accepted input syntax",
        "must not import coding, method, work, TUI, AI, provider, or product packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Workspace Path And Mutation Boundary" in readme_text


def test_harness_tools_core_does_not_expose_pi_style_module_aliases() -> None:
    pi_style_aliases = {
        "createToolDefinitionFromAgentTool",
        "wrapToolDefinition",
        "wrapToolDefinitions",
    }

    for module_name in (
        "loushang.harness.tools.core",
        "loushang.harness.tools.workspace.wrapper",
    ):
        module = importlib.import_module(module_name)
        assert [name for name in sorted(pi_style_aliases) if hasattr(module, name)] == []


def test_harness_workspace_tool_pack_boundary_is_documented() -> None:
    import loushang.harness as harness

    workspace_tool_symbols = {
        "BashToolOptions",
        "ReadToolOptions",
        "ToolContext",
        "ToolsOptions",
        "create_all_tool_definitions",
        "create_read_tool_definition",
    }
    assert workspace_tool_symbols.isdisjoint(set(harness.__all__))

    design_path = Path(
        "docs/internals/architecture/harness/workspace-tool-pack-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Workspace Tool Pack Boundary",
        "`loushang.harness.tools.workspace`",
        "reusable concrete workspace tool pack",
        "builtin pack membership, default activation, and activation order",
        "`coding.control` is frozen",
        "does not import Coding or AI packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Workspace Tool Pack Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "Workspace Tool Pack" in inventory_text
    assert "reusable concrete workspace tools implemented" in inventory_text


def test_coding_internal_workspace_tool_imports_use_harness_owners() -> None:
    legacy_prefixes = tuple(
        f"loushang.coding.tools.{module_name}"
        for module_name in (
            "bash",
            "builtin_renderers",
            "context",
            "edit",
            "edit_diff",
            "external_tools",
            "find",
            "grep",
            "ignore",
            "ls",
            "normalize",
            "operations",
            "output_preview",
            "path_utils",
            "policy",
            "presentation",
            "process",
            "protocol",
            "read",
            "runtime",
            "truncate",
            "wrapper",
            "write",
        )
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_prefixes):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_harness_tool_facade_extinction_is_documented_and_enforced() -> None:
    import loushang.coding as coding

    assert not Path("src/loushang/coding/tools").exists()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loushang.coding.tools")

    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if imported.startswith("loushang.coding.tools"):
                offenders.append(f"{path.as_posix()} imports {imported}")
    assert offenders == []
    assert "ToolDefinition" not in coding.__all__

    text = " ".join(
        Path("docs/internals/architecture/harness/tool-facade-extinction-boundary.md")
        .read_text(encoding="utf-8")
        .split()
    )

    required_phrases = {
        "Harness Tool Facade Extinction Boundary",
        "`loushang.coding.tools` is removed",
        "`loushang.coding.tool_pack` is the only Coding module",
        "`WorkspaceToolRegistry`",
        "must not be recreated as a compatibility shim",
    }

    assert sorted(phrase for phrase in required_phrases if phrase not in text) == []


def test_harness_slice1_closure_status_is_documented() -> None:
    path = Path("docs/internals/architecture/harness/slice-1-status.md")
    assert path.exists()

    text = " ".join(path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Slice 1 Closure Status",
        "Current status: closed on `lane/harness`",
        "`loushang.harness.approval`",
        "`loushang.harness.tools.core`",
        "`loushang.harness.tools.contribution`",
        "`loushang.harness.presentation`",
        "Coding still owns",
        "Compatibility shims",
        "Deferred items",
        "Validation matrix",
        "runtime dynamic extension registration",
        "concrete coding tools",
        "TUI controller/render loop",
        "AI provider/model/auth",
    }

    assert sorted(phrase for phrase in required_phrases if phrase not in text) == []


def test_harness_slice2_execution_context_design_is_documented() -> None:
    path = Path(
        "docs/internals/architecture/harness/slice-2-execution-context-design.md"
    )
    assert path.exists()

    text = " ".join(path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Slice 2 Execution Context Design",
        "Slice 2A status: implementation complete for `lane/harness`",
        "Slice 2B status: eligible under the neutrality evidence gate; not yet "
        "implemented",
        "neutral execution context",
        "product execution adapter",
        "runtime dynamic extension registration",
        "`loushang.harness.tools.authoring.ToolContext`",
        "`ExtensionRuntimeBindings.register_tool`",
        "`ToolController.register_runtime_tool`",
        "`harness.tools.contribution`",
        "Product-owned behavior remains product-owned",
        "resolver diagnostics are advisory inputs to coding policy",
        "runtime duplicate overwrite behavior remains coding-owned",
        "No neutral execution context API is introduced by Slice 2A",
        "Deferred implementation items",
        "not import `loushang.coding`",
    }

    assert sorted(phrase for phrase in required_phrases if phrase not in text) == []

    status_paths = (
        Path("docs/internals/architecture/harness/README.md"),
        Path(
            "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
        ),
    )
    for status_path in status_paths:
        status_text = " ".join(status_path.read_text(encoding="utf-8").split())
        assert "Slice 2A" in status_text, status_path
        assert "implementation complete" in status_text, status_path
        assert "Slice 2B" in status_text, status_path
        assert "eligible under the neutrality evidence gate" in status_text, status_path


def test_harness_neutrality_evidence_gate_is_documented() -> None:
    path = Path("docs/internals/architecture/harness/refactoring-principles.md")
    text = " ".join(path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Neutrality Evidence Gate",
        "does not require a second production consumer",
        "the existing product adapter proves compatibility",
        "an independent contract probe",
        "a minimal reference adapter",
        "a product-neutral test fixture",
        "A renamed Coding fixture is not sufficient",
        "Product imports, Product-exclusive defaults, or product-specific storage and UI semantics",
        "its absence is not a migration blocker",
    }
    assert sorted(phrase for phrase in required_phrases if phrase not in text) == []


def test_harness_dependency_first_migration_rule_is_documented() -> None:
    principles_path = Path(
        "docs/internals/architecture/harness/refactoring-principles.md"
    )
    principles_text = " ".join(principles_path.read_text(encoding="utf-8").split())
    required_principles = {
        "Dependency-First Migration Order",
        "Move `B` before `A` when `B` belongs in Harness",
        "decide ownership before considering topology",
        "strongly connected component",
        "Dependency count is evidence about leverage, not evidence about ownership",
        "Use capability-sized migration batches",
        "Do not create a separate branch or named slice for every leaf type",
        "Batch size never relaxes neutrality, dependency direction, compatibility, or test requirements",
    }
    assert (
        sorted(
            phrase for phrase in required_principles if phrase not in principles_text
        )
        == []
    )

    inventory_path = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    )
    inventory_text = " ".join(inventory_path.read_text(encoding="utf-8").split())
    required_inventory = {
        "Accelerated Dependency-First Execution",
        "Wave 1: Resource And Package Runtime",
        "Wave 2: Extension Runtime Core",
        "Wave 3: Persistence, Context, And Workflow Mechanics",
        "Wave 4: Session And Runtime Consolidation",
        "This is one capability batch",
        "The later Agent Transcript Profile wave completed this ownership transfer",
    }
    assert (
        sorted(phrase for phrase in required_inventory if phrase not in inventory_text)
        == []
    )


def test_core_workspace_effects_only_execute_through_gateway() -> None:
    workspace_root = Path("src/loushang/harness/tools/workspace")
    effectful_tools = ("bash", "read", "write", "edit", "grep", "find", "ls")

    for tool_name in effectful_tools:
        source = (workspace_root / f"{tool_name}.py").read_text(encoding="utf-8")
        assert (
            "AuthorizedExecution(" in source or "authorized_tool(" in source
        ), tool_name
        assert "execute_workspace_tool_action(" not in source, tool_name
        assert "enforce_tool_policy(" not in source, tool_name
        assert "CallableToolActionAdapter" not in source, tool_name

    for tool_name in ("read", "write", "edit", "grep", "find", "ls"):
        source = (workspace_root / f"{tool_name}.py").read_text(encoding="utf-8")
        assert "FilesystemActionAdapter" in source, tool_name
    assert "ProcessEffect" in (workspace_root / "bash.py").read_text(
        encoding="utf-8"
    )


def test_tool_authoring_and_execution_scope_have_single_harness_owners() -> None:
    workspace_root = Path("src/loushang/harness/tools/workspace")
    assert not (workspace_root / "authoring.py").exists()
    assert not (workspace_root / "context.py").exists()
    assert not (workspace_root / "normalize.py").exists()
    assert not (workspace_root / "schema.py").exists()

    registry_source = (workspace_root / "registry.py").read_text(encoding="utf-8")
    assert "policy_evaluator" not in registry_source
    assert "approval_resolver" not in registry_source
    assert "create_workspace_tool_execution_host" not in registry_source

    controller_source = Path(
        "src/loushang/harness/session/tool_controller.py"
    ).read_text(encoding="utf-8")
    assert "create_workspace_tool_execution_host" in controller_source

    for path in Path("src/loushang/coding").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "WorkspaceToolAuthorizationGateway" not in source, path
        assert "create_workspace_tool_execution_host" not in source, path


def test_resource_package_runtime_has_harness_owners() -> None:
    import loushang.coding as coding
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer,
        CodingResourceLoader,
        CodingSkillLoader,
    )
    from loushang.harness.resources.loader import ResourceLoader
    from loushang.harness.resources.packages import (
        PackageCatalogBuilder,
        PackageMaterializer,
        PackageSourceResolver,
    )
    from loushang.harness.resources.skills import SkillLoader

    assert issubclass(CodingResourceLoader, ResourceLoader)
    assert issubclass(CodingPackageMaterializer, PackageMaterializer)
    assert issubclass(CodingSkillLoader, SkillLoader)
    assert PackageCatalogBuilder.__module__.startswith("loushang.harness")
    assert PackageSourceResolver.__module__.startswith("loushang.harness")
    assert "ResourceBundle" not in coding.__all__
    assert "PluginManager" not in coding.__all__


def test_coding_internal_resource_consumers_use_harness_owners() -> None:
    from importlib.util import find_spec

    retired_directories = (
        Path("src/loushang/coding/loader"),
        Path("src/loushang/coding/package"),
        Path("src/loushang/coding/plugin"),
        Path("src/loushang/coding/skill"),
    )
    assert all(not path.exists() for path in retired_directories)

    retired_prefixes = (
        "loushang.coding.loader",
        "loushang.coding.package",
        "loushang.coding.plugin",
        "loushang.coding.skill",
    )
    assert all(find_spec(prefix) is None for prefix in retired_prefixes)
    offenders: list[str] = []
    for root in (Path("src"), Path("tests"), Path("examples")):
        for path in sorted(root.rglob("*.py")):
            for imported in _absolute_imports(path):
                if any(
                    imported == prefix or imported.startswith(f"{prefix}.")
                    for prefix in retired_prefixes
                ):
                    offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_coding_legacy_shared_utility_facades_are_extinct() -> None:
    from importlib.util import find_spec

    import loushang.coding as coding
    import loushang.coding.control as coding_control
    import loushang.coding.prompt as coding_prompt

    retired_prefixes = (
        "loushang.coding.commands.slash",
        "loushang.coding.control.model_registry",
        "loushang.coding.event",
        "loushang.coding.extensions",
        "loushang.coding.frontmatter",
        "loushang.coding.policy",
        "loushang.coding.prompt.preflight",
        "loushang.coding.prompt.templates",
        "loushang.coding.prompt.types",
        "loushang.coding.session.context_usage",
        "loushang.coding.types",
        "loushang.coding.work_projection",
        "loushang.coding.workflow.assertions",
        "loushang.coding.workflow.events",
        "loushang.coding.workflow.fake_runtime",
        "loushang.coding.workflow.loader",
        "loushang.coding.workflow.schema",
    )
    for prefix in retired_prefixes:
        try:
            spec = find_spec(prefix)
        except ModuleNotFoundError:
            spec = None
        assert spec is None, prefix
    assert {
        "AgentSessionEvent",
        "JsonEventView",
        "ModelRegistry",
        "select_events",
    }.isdisjoint(coding.__all__)
    assert "ModelRegistry" not in coding_control.__all__
    assert {
        "PromptPreflightResult",
        "parse_prompt_template_args",
        "preflight_user_input",
        "preflight_user_input_async",
        "prompt_template_has_args",
        "substitute_prompt_template_args",
    }.isdisjoint(coding_prompt.__all__)

    offenders: list[str] = []
    for root in (Path("src"), Path("tests"), Path("examples")):
        for path in sorted(root.rglob("*.py")):
            for imported in _absolute_imports(path):
                if any(
                    imported == prefix or imported.startswith(f"{prefix}.")
                    for prefix in retired_prefixes
                ):
                    offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_harness_host_runtime_boundary_is_documented() -> None:
    design_path = Path("docs/internals/architecture/harness/host-runtime-boundary.md")
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Host Runtime Boundary",
        "implementation complete for integration into `lane/harness`",
        "`loushang.harness.runtime.execution.HostRuntime`",
        "`loushang.harness.runtime.input_queue.HostInputQueue`",
        "`loushang.harness.events.OrderedEventBus`",
        "must not implement a second agent loop",
        "Coding maps running, aborting, and disposing",
        "product-neutral reference driver",
        "no host symbols are added to top-level `loushang.harness.__all__`",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Host Runtime Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "host runtime core implementation complete" in inventory_text


def test_harness_product_runtime_core_is_documented_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/product-runtime-core-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Product Runtime Core Boundary",
        "implementation complete for integration into `lane/harness`",
        "`ProductRuntimeBindings`",
        "`RuntimeBindingState`",
        "`BoundProductRuntimeContext`",
        "`SessionTransitionHost`",
        "`CoalescingScheduler`",
        "Candidate preparation failure leaves the previous session current",
        "Research-shaped fixture",
        "does not import AI or Product",
        "full non-live repository test suite passes",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Product Runtime Core Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "product runtime core implementation complete" in inventory_text
    assert "coalesced index scheduling" in inventory_text

    from loushang.harness.extensions.context import ExtensionRuntimeBindings
    from loushang.harness.extensions.runner import (
        _BoundExtensionContext,
        _RunnerContext,
    )
    from loushang.harness.runtime import (
        BoundProductRuntimeContext,
        ProductRuntimeBindings,
        UnboundProductRuntimeContext,
    )

    assert issubclass(ExtensionRuntimeBindings, ProductRuntimeBindings)
    assert issubclass(_BoundExtensionContext, BoundProductRuntimeContext)
    assert issubclass(_RunnerContext, UnboundProductRuntimeContext)

    expected_imports = {
        Path("src/loushang/harness/extensions/runner.py"): {
            "loushang.harness.extensions.context.BoundExtensionContext",
            "loushang.harness.extensions.context.UnboundExtensionContext",
            "loushang.harness.runtime.RuntimeBindingState",
        },
        Path("src/loushang/coding/runtime/agent_session_runtime.py"): {
            "loushang.harness.session.AgentProductSessionRuntime",
        },
    }
    missing: list[str] = []
    for path, required in expected_imports.items():
        imports = set(_absolute_imports(path))
        missing.extend(
            f"{path.as_posix()} missing {name}" for name in sorted(required - imports)
        )
    assert missing == []


def test_host_turn_session_orchestration_core_is_documented_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/host-turn-session-orchestration-core.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Host Turn And Session Orchestration Core Boundary",
        "implementation complete for integration into `lane/harness`",
        "`TurnOrchestrator`",
        "`TurnInputQueue`",
        "`RetryCoordinator`",
        "`SessionOperationCoordinator`",
        "`NavigationTransactionCoordinator`",
        "prepare -> load -> discover -> commit",
        "Cancellation during candidate preparation or replacement cleans up",
        "Product retains controller policy, Product semantics, and adapters",
        "full non-live repository suite pass",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Host Turn And Session Orchestration Core Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert (
        "host turn and session orchestration core implementation complete"
        in inventory_text
    )

    expected_imports = {
        Path("src/loushang/harness/session/lifecycle.py"): {
            "loushang.harness.runtime.SessionOperationCoordinator",
            "loushang.harness.runtime.stage_file_import",
        },
        Path("src/loushang/harness/session/transcript_lifecycle.py"): {
            "loushang.harness.transcript.directory.AgentTranscriptDirectoryRuntime",
            "loushang.harness.session.lifecycle.SessionLifecycleRuntime",
        },
        Path("src/loushang/coding/runtime/agent_session_runtime.py"): {
            "loushang.harness.session.AgentProductSessionRuntime",
        },
        Path("src/loushang/harness/extensions/session_runtime.py"): {
            "loushang.harness.extensions.lifecycle.ExtensionRuntimeCoordinator",
        },
        Path("src/loushang/harness/session/prompt_controller.py"): {
            "loushang.harness.runtime.turn.TurnOrchestrator",
        },
        Path("src/loushang/harness/session/queue_controller.py"): {
            "loushang.harness.runtime.turn.TurnInputQueue",
        },
        Path("src/loushang/harness/session/resource_refresh.py"): {
            "loushang.harness.resources.refresh.ResourceRefreshCoordinator",
        },
        Path("src/loushang/harness/session/composition.py"): {
            "loushang.harness.transcript.AgentTranscriptRetryRuntime",
            "loushang.harness.transcript.AgentTranscriptCompactionRuntime",
            "loushang.harness.transcript.AgentTranscriptNavigationRuntime",
            "loushang.harness.transcript.AgentTranscriptSelectionRuntime",
            "loushang.harness.extensions.session_runtime.ExtensionSessionRuntime",
            "loushang.harness.extensions.agent.ExtensionInputRuntime",
        },
    }
    missing: list[str] = []
    for path, required in expected_imports.items():
        imports = set(_absolute_imports(path))
        missing.extend(
            f"{path.as_posix()} missing {name}" for name in sorted(required - imports)
        )
    assert missing == []

    from loushang.harness import __all__ as harness_exports

    assert "RetryCoordinator" not in harness_exports
    assert "SessionOperationCoordinator" not in harness_exports
    assert "TurnOrchestrator" not in harness_exports


def test_session_lifecycle_runtime_is_documented_neutral_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/session-lifecycle-runtime-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Session Lifecycle Runtime Boundary",
        "implementation complete for integration into `lane/harness`",
        "`SessionLifecycleRuntime`",
        "`AgentTranscriptSessionRuntime`",
        "`SessionLifecycleStore`",
        "default position is `at`",
        "default fork position: before",
        "`resolve_fork_target`",
        "Fork target lookup, position validation, and target resolution happen while",
        "must not import Agent, AI, Coding",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    composition_path = Path(
        "docs/internals/architecture/harness/session-product-runtime-composition-boundary.md"
    )
    assert composition_path.exists()
    composition_text = " ".join(composition_path.read_text(encoding="utf-8").split())
    assert "`harness.session.ProductSessionRuntime`" in composition_text
    assert "does not create a second session engine" in composition_text

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "Session Lifecycle Runtime Boundary" in readme_text
    assert (
        "`harness.session.SessionLifecycleRuntime` owns the active session"
        in inventory_text
    )
    assert "`harness.session.AgentTranscriptSessionRuntime` composes" in inventory_text
    assert "`harness.session.ProductSessionRuntime` binds" in inventory_text

    boundary = ImportBoundary(
        name="session lifecycle",
        root=Path("src/loushang/harness/session/lifecycle.py"),
        forbidden_prefixes=(
            "loushang.agent",
            "loushang.ai",
            "loushang.coding",
            "loushang.method",
            "loushang.tui",
            "loushang.work",
        ),
    )
    assert _find_forbidden_imports(boundary) == []

    transcript_lifecycle_boundary = ImportBoundary(
        name="transcript session lifecycle",
        root=Path("src/loushang/harness/session/transcript_lifecycle.py"),
        forbidden_prefixes=(
            "loushang.coding",
            "loushang.method",
            "loushang.tui",
            "loushang.work",
        ),
    )
    assert _find_forbidden_imports(transcript_lifecycle_boundary) == []

    imports = set(
        _absolute_imports(Path("src/loushang/coding/runtime/agent_session_runtime.py"))
    )
    assert "loushang.harness.session.AgentProductSessionRuntime" in imports
    assert "loushang.harness.runtime.SessionOperationCoordinator" not in imports


def test_coding_session_lifecycle_consumers_use_operation_results() -> None:
    runtime_source = Path(
        "src/loushang/coding/runtime/agent_session_runtime.py"
    ).read_text(encoding="utf-8")
    extension_source = Path(
        "src/loushang/harness/extensions/agent/replacement.py"
    ).read_text(encoding="utf-8")
    session_source = Path("src/loushang/coding/session/agent_session.py").read_text(
        encoding="utf-8"
    )
    rpc_source = Path("src/loushang/harness/host/rpc.py").read_text(encoding="utf-8")
    cli_source = Path("src/loushang/coding/cli/__main__.py").read_text(encoding="utf-8")

    assert "fork_session_with_result" not in runtime_source
    assert "entry_id: str, options: object | None = None" not in runtime_source
    assert "async def clone(\n        self\n" not in runtime_source
    assert "import_session_operation" not in runtime_source
    assert "fork_session_operation" in extension_source
    assert "new_session_operation" in extension_source
    assert "restore_session_operation" in extension_source
    assert "import_session_operation" in extension_source
    assert "_clone_from_builtin" not in session_source
    assert "_import_from_builtin" not in session_source
    assert "SessionRpcOperationBinding" in rpc_source
    assert "ProductHostLifecycle" in cli_source
    assert "require_session_operation_session" not in cli_source


def test_product_capability_composition_core_is_documented_and_adopted() -> None:
    import loushang.harness as harness
    import loushang.harness.capabilities as capabilities

    capability_symbols = {
        "CommandCatalog",
        "CommandDescriptor",
        "CommandDispatchOutcome",
        "PreparedPrompt",
        "PromptSection",
        "PromptTemplateExpander",
        "ToolActivationCoordinator",
        "ToolActivationDiff",
        "ToolActivationSnapshot",
    }
    assert capability_symbols.isdisjoint(set(harness.__all__))
    assert set(capabilities.__all__) == {
        "CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION",
        "CapabilityCompositionRuntime",
        "CapabilityPack",
        "CapabilityPackComposer",
        "CapabilityPackComposition",
        "CapabilityPackSource",
        "CapabilityPackTraceEntry",
        "bind_capability_composition_runtime",
        "compose_capability_packs",
        "standard_capability_composition_plan",
        "standard_capability_composition_implementations",
    }

    design_path = Path(
        "docs/internals/architecture/harness/product-capability-composition-core.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Product Capability Composition Core Boundary",
        "Implementation complete for integration into `lane/harness`",
        "`loushang.harness.commands`",
        "`loushang.harness.capabilities.prompt`",
        "`loushang.harness.capabilities.tools`",
        "standard `/skill:<name>` and `/<prompt>` resource preflight",
        "Product adapters should be small",
        "Coding and future Product adapters retain",
        "full non-live repository suite remain merge gates",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Product Capability Composition Core Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "Wave 5: Product Capability Composition" in inventory_text
    assert (
        "product capability composition core implementation complete" in inventory_text
    )
    assert not Path("src/loushang/coding/prompt/types.py").exists()
    assert not Path("src/loushang/coding/prompt/preflight.py").exists()

    expected_imports = {
        Path("src/loushang/harnesstui/commands/catalog.py"): {
            "loushang.harness.commands.CommandCatalog",
            "loushang.harness.commands.MixedCommandCatalog",
        },
        Path("src/loushang/coding/bootstrap.py"): {
            "loushang.harness.session.AgentProductConstructionBinding",
        },
        Path("src/loushang/coding/prompt/assembler.py"): {
            "loushang.harness.capabilities.prompt_assembly.PromptAssembly",
            "loushang.harness.capabilities.prompt_assembly.assemble_prompt",
        },
        Path("src/loushang/harness/session/tool_controller.py"): {
            "loushang.harness.session.SessionToolRuntime",
        },
    }
    missing: list[str] = []
    for path, required in expected_imports.items():
        imports = set(_absolute_imports(path))
        missing.extend(
            f"{path.as_posix()} missing {name}" for name in sorted(required - imports)
        )
    assert missing == []
    assert not Path("src/loushang/coding/commands/catalog.py").exists()
    assert not Path("src/loushang/coding/commands/__init__.py").exists()

    product_neutral_boundaries = (
        ImportBoundary(
            name="harness commands",
            root=Path("src/loushang/harness/commands"),
            forbidden_prefixes=("loushang.coding",),
        ),
        ImportBoundary(
            name="harness prompt assembly",
            root=Path("src/loushang/harness/capabilities/prompt_assembly.py"),
            forbidden_prefixes=("loushang.coding",),
        ),
        ImportBoundary(
            name="harness prompt preflight",
            root=Path("src/loushang/harness/capabilities/prompt_preflight.py"),
            forbidden_prefixes=("loushang.coding",),
        ),
    )
    assert [
        offender
        for boundary in product_neutral_boundaries
        for offender in _find_forbidden_imports(boundary)
    ] == []


def test_tool_output_projection_core_is_documented_and_adopted() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/tool-output-projection-core.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Tool Output Projection Core Boundary",
        "implementation complete for integration into `lane/harness`",
        "`loushang.protocol` owns `JSONValue`",
        "`ToolOutputProjector[TDetails]`",
        "Transcript, event, and hook projections are snapshotted independently",
        "`tool_output_projection_failed`",
        "The raw unprojectable value is not copied into a journal",
        "live rendering and replay rendering consume the same result semantics",
        "In-memory and JSONL event logs enforce the same strict snapshot contract",
        "Channel envelope encoding validates the complete wire object",
        "`loushang.observability` remains a documented compatibility exception",
        "Product adapters still own tool-specific detail vocabulary",
        "Protocol -> AI -> Agent -> Harness -> Product dependency direction",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Tool Output Projection Core Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "multi-view tool-output projection core live in Agent" in inventory_text

    from loushang.agent import AgentToolResult, ToolOutputProjector
    from loushang.protocol import JSONValue, require_json_value

    assert (
        AgentToolResult.__annotations__["projector"] == "ToolOutputProjector[TDetails]"
    )
    assert ToolOutputProjector is not None
    assert require_json_value({"ok": True}) == {"ok": True}
    assert JSONValue is not None


def test_observability_json_compatibility_exception_does_not_expand() -> None:
    allowed_consumers = {
        "src/loushang/ai/errors.py",
        "src/loushang/ai/auth/support.py",
        "src/loushang/ai/event_stream/raw_parts.py",
        "src/loushang/ai/provider/errors.py",
        "src/loushang/ai/structured.py",
        "src/loushang/ai/trace.py",
    }
    actual_consumers: set[str] = set()
    for path in Path("src/loushang").rglob("*.py"):
        if path.is_relative_to("src/loushang/observability"):
            continue
        if any(
            imported.startswith("loushang.observability.problem.")
            for imported in _absolute_imports(path)
        ):
            actual_consumers.add(path.as_posix())

    assert actual_consumers == allowed_consumers


def test_coding_internal_run_state_imports_use_harness_owner() -> None:
    compatibility_paths = {
        "src/loushang/coding/session/__init__.py",
        "src/loushang/coding/session/types.py",
    }
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        if path.as_posix() in compatibility_paths:
            continue
        for imported in _absolute_imports(path):
            if imported == "loushang.coding.session.types.RunState":
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_coding_internal_session_type_imports_use_owners() -> None:
    compatibility_paths = {
        "src/loushang/coding/session/__init__.py",
        "src/loushang/coding/session/types.py",
    }
    legacy_symbols = (
        "loushang.coding.session.types.AgentSessionState",
        "loushang.coding.session.types.CompactionDecision",
        "loushang.coding.session.types.ContextUsage",
        "loushang.coding.session.types.ContextUsageSnapshot",
        "loushang.coding.session.types.ModelSelection",
        "loushang.coding.session.types.SessionStats",
        "loushang.coding.session.types.TokenUsageTotals",
        "loushang.coding.session.types.TreeNavigationResult",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        if path.as_posix() in compatibility_paths:
            continue
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_coding_store_alias_facades_are_extinct() -> None:
    legacy_symbols = (
        "loushang.coding.store.CodingSessionFileLayout",
        "loushang.coding.store.SessionFileError",
        "loushang.coding.store.SessionMetadata",
        "loushang.coding.store.SessionQuery",
        "loushang.coding.store.SessionRecord",
        "loushang.coding.store.SessionSummary",
        "loushang.coding.store.SessionTreeNode",
        "loushang.coding.store.append_session_entry",
        "loushang.coding.store.create_coding_file_store",
        "loushang.coding.store.create_session_repository",
        "loushang.coding.store.load_current_session_header",
        "loushang.coding.store.load_session_file",
        "loushang.coding.store.load_session_repository",
        "loushang.coding.store.session_file_lock",
        "loushang.coding.store.session_journal",
        "loushang.coding.store.write_session_file",
        "loushang.coding.store.backend",
        "loushang.coding.store.file_codec",
        "loushang.coding.store.file_lock",
        "loushang.coding.store.types",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []
    assert not Path("src/loushang/coding/store").exists()
    assert Path("src/loushang/coding/session_manager.py").exists()
    canonical = importlib.import_module("loushang.coding.session_manager")
    public = importlib.import_module("loushang.coding")
    assert public.SessionManager is canonical.SessionManager
    for path in (
        "src/loushang/coding/store/backend.py",
        "src/loushang/coding/store/file_codec.py",
        "src/loushang/coding/store/file_lock.py",
        "src/loushang/coding/store/types.py",
    ):
        assert not Path(path).exists()


def test_coding_internal_scenario_imports_use_harness_owner() -> None:
    legacy_prefixes = (
        "loushang.coding.workflow.assertions",
        "loushang.coding.workflow.events",
        "loushang.coding.workflow.fake_runtime",
        "loushang.coding.workflow.loader",
        "loushang.coding.workflow.schema",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if imported.startswith(legacy_prefixes):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []
    assert all(
        not Path(path).exists()
        for path in (
            "src/loushang/coding/workflow/assertions.py",
            "src/loushang/coding/workflow/events.py",
            "src/loushang/coding/workflow/fake_runtime.py",
            "src/loushang/coding/workflow/loader.py",
            "src/loushang/coding/workflow/schema.py",
        )
    )


def test_coding_compaction_type_facades_are_extinct() -> None:
    legacy_symbols = (
        "loushang.coding.compaction.types.CompactionPlan",
        "loushang.coding.compaction.types.CompactionPreparation",
        "loushang.coding.compaction.types.CompactionResult",
        "loushang.coding.compaction.types.CompactionStatus",
        "loushang.coding.compaction.types.ContextUsageEstimate",
    )
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_harness_product_kernel_ownership_is_documented() -> None:
    path = Path("docs/internals/architecture/harness/shared-capability-boundaries.md")
    text = " ".join(path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Product Kernel Ownership",
        "product goals, domain language, and completion criteria",
        "system prompt and prompt-section content",
        "skill content and default activation policy",
        "domain-specific concrete tools",
        "selection and activation policy for shared tool packs",
        "context salience, compaction, and summarization policy",
        "risk classification, approval defaults, and permission policy",
        "artifact semantics",
        "product commands, configuration defaults, and presentation projections",
        "product resource content, convention activation, additional/override roots",
        "cross-product platform defaults such as standard resource roots",
        "these semantics must not migrate merely to reduce the number of lines",
    }
    assert sorted(phrase for phrase in required_phrases if phrase not in text) == []

    readme_text = " ".join(
        Path("docs/internals/architecture/harness/README.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "product kernel that must remain product-owned" in readme_text


def test_harness_platform_resource_layout_boundary_is_documented() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/platform-resource-layout-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Platform Resource Layout Boundary",
        "resource and package runtime implementation complete for integration into `lane/harness`",
        "a **platform default** is useful to every Loushang product",
        "$LOUSHANG_HOME, otherwise ~/.loushang/",
        "<workspace>/.loushang/",
        "temporary > project > user > package > built_in",
        "`AGENTS.md` is a cross-product agent-instruction convention",
        "Products own their built-in resource content and register it with Harness",
        "Resource discovery is not resource authorization",
        "`coding.resource_runtime.CodingResourceLoader` is Coding's resource binding",
        "must not import Coding, Design, Research, PPT, Cowork, TUI, Method, Work, or AI provider packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Platform Resource Layout Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "Resource And Package Runtime" in inventory_text
    assert "resource and package runtime implementation complete" in inventory_text

    authoritative_text = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "docs/internals/architecture/harness/refactoring-principles.md",
            "docs/internals/architecture/harness/shared-capability-boundaries.md",
            "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md",
        )
    )
    assert (
        "resource search roots, file conventions, and compatibility formats"
        not in authoritative_text
    )
    assert "AGENTS.md or equivalent loading policy" not in authoritative_text


def test_frontmatter_consumers_use_harness_owner() -> None:
    compatibility_paths = {
        "src/loushang/resource/__init__.py",
        "src/loushang/resource/frontmatter.py",
    }
    legacy_prefixes = ("loushang.resource.frontmatter",)
    offenders: list[str] = []
    for root in (Path("src/loushang/coding"), Path("src/loushang/method")):
        for path in sorted(root.rglob("*.py")):
            if path.as_posix() in compatibility_paths:
                continue
            for imported in _absolute_imports(path):
                if imported.startswith(legacy_prefixes):
                    offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []
    assert not Path("src/loushang/coding/frontmatter.py").exists()


def test_harness_resource_frontmatter_boundary_is_documented() -> None:
    import loushang.harness as harness

    resource_symbols = {
        "FrontmatterParseError",
        "ParsedFrontmatter",
        "parse_frontmatter",
        "strip_frontmatter",
    }
    assert resource_symbols.isdisjoint(set(harness.__all__))

    design_path = Path(
        "docs/internals/architecture/harness/resource-frontmatter-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Resource Frontmatter Boundary",
        "`loushang.harness.resources.frontmatter`",
        "Coding does not provide a frontmatter import facade",
        "does not move or redesign",
        "must not import coding, method, work, TUI, AI, or provider packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Resource Frontmatter Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "`loushang.harness.resources.frontmatter`" in inventory_text
    assert "frontmatter parsing implementation complete" in inventory_text


def test_resource_provenance_consumers_use_harness_owners() -> None:
    compatibility_paths = {
        "src/loushang/coding/source_info.py",
    }
    legacy_symbols = ("loushang.coding.extensions.SourceInfo",)
    offenders: list[str] = []
    for path in sorted(Path("src/loushang/coding").rglob("*.py")):
        if path.as_posix() in compatibility_paths:
            continue
        for imported in _absolute_imports(path):
            if _matches_any(imported, legacy_symbols):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_harness_resource_provenance_boundary_is_documented() -> None:
    import loushang.harness as harness

    provenance_symbols = {
        "SourceInfo",
        "SourceOrigin",
        "SourceScope",
        "resource_diagnostic",
    }
    assert provenance_symbols.isdisjoint(set(harness.__all__))

    design_path = Path(
        "docs/internals/architecture/harness/resource-provenance-boundary.md"
    )
    assert design_path.exists()
    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_phrases = {
        "Harness Resource Provenance Boundary",
        "`DiagnosticDraft`",
        "`loushang.harness.resources.source`",
        "`loushang.harness.resources.diagnostics`",
        "`resource_diagnostic`",
        "does not move or redesign",
        "must not import coding, method, work, TUI, AI, provider, or product packages",
    }
    assert (
        sorted(phrase for phrase in required_phrases if phrase not in design_text) == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Resource Provenance Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "`loushang.harness.resources.source`" in inventory_text
    assert "resource provenance implementation complete" in inventory_text


def test_harness_workspace_execution_boundary_is_documented() -> None:
    design_path = Path(
        "docs/internals/architecture/harness/workspace-execution-boundary.md"
    )
    assert design_path.exists()

    design_text = " ".join(design_path.read_text(encoding="utf-8").split())
    required_design_phrases = {
        "Harness Workspace Execution Boundary",
        "`loushang.harness.workspace.truncation`",
        "`loushang.harness.workspace.exec`",
        "Coding remains a product adapter",
        "Harness-owned classes keep their harness `__module__`",
        "does not introduce a neutral execution context",
    }
    assert (
        sorted(
            phrase for phrase in required_design_phrases if phrase not in design_text
        )
        == []
    )

    readme_text = Path("docs/internals/architecture/harness/README.md").read_text(
        encoding="utf-8"
    )
    assert "Workspace Execution Boundary" in readme_text

    inventory_text = Path(
        "docs/internals/architecture/harness/coding-to-harness-migration-inventory.md"
    ).read_text(encoding="utf-8")
    assert "`loushang.harness.workspace.truncation`" in inventory_text
    assert "workspace execution implementation complete" in inventory_text

    coding_exec_text = Path(
        "docs/internals/architecture/coding/component-interfaces/exec.md"
    ).read_text(encoding="utf-8")
    assert "`loushang.harness.workspace.exec`" in coding_exec_text
    assert "compatibility" in coding_exec_text


def test_coding_agent_product_construction_uses_shared_binding() -> None:
    coding_path = Path("src/loushang/coding/bootstrap.py")
    imports = set(_absolute_imports(coding_path))

    assert "loushang.harness.session.AgentProductConstructionBinding" in imports
    assert "loushang.harness.session.build_standard_agent_session_result" in imports
    assert (
        "loushang.harness.session.create_standard_agent_bootstrap_services" in imports
    )
    for direct_owner in (
        "loushang.harness.config.agent.ControlConfig",
        "loushang.harness.diagnostics.service.DiagnosticsService",
        "loushang.harness.model_catalog.ModelCatalog",
        "loushang.harness.session.AgentProductConstructionPorts",
        "loushang.harness.session.AgentProductConstructionRequest",
        "loushang.harness.session.AgentProductConstructionRuntime",
        "loushang.harness.session.StandardAgentSessionConfigurationRequest",
    ):
        assert direct_owner not in imports

    harness_source = Path("src/loushang/harness/session/bootstrap.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("loushang.coding", "loushang.method", "loushang.work"):
        assert forbidden not in harness_source


def test_absolute_imports_include_child_aliases_from_package_import(
    tmp_path: Path,
) -> None:
    path = _write_module(
        tmp_path / "src/loushang/coding/example.py",
        "from loushang import harness\n",
    )

    assert "loushang.harness" in _absolute_imports(path)


def test_harness_boundary_rejects_agent_facade_reexport(tmp_path: Path) -> None:
    path = _write_module(
        tmp_path / "src/loushang/harness/example.py",
        "from loushang.agent import Agent\n",
    )

    assert _find_forbidden_imports(
        ImportBoundary(
            name="harness",
            root=tmp_path / "src/loushang/harness",
            forbidden_prefixes=("loushang.agent.Agent",),
        )
    ) == [f"harness: {path.as_posix()} imports loushang.agent.Agent"]


def test_absolute_imports_resolve_relative_imports_from_package_path(
    tmp_path: Path,
) -> None:
    path = _write_module(
        tmp_path / "src/loushang/agent/example.py",
        "from ..harness import run_agent\n",
    )

    imports = _absolute_imports(path)

    assert "loushang.harness" in imports
    assert "loushang.harness.run_agent" in imports


def _write_module(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    return path


def _find_forbidden_imports(boundary: ImportBoundary) -> list[str]:
    offenders: list[str] = []
    for path in sorted(boundary.root.rglob("*.py")):
        relative_path = path.as_posix()
        if relative_path in boundary.allowed_paths:
            continue
        for imported in _absolute_imports(path):
            if imported.startswith(UNRESOLVED_RELATIVE_IMPORT):
                offenders.append(
                    f"{boundary.name}: {relative_path} has unresolved relative import {imported}"
                )
            elif _matches_any(imported, boundary.forbidden_prefixes):
                offenders.append(f"{boundary.name}: {relative_path} imports {imported}")
    return offenders


def _absolute_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(_import_from_targets(path, node))
    return imports


def _harness_internal_dependency_graph(root: Path) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        source = relative.parts[0]
        if len(relative.parts) == 1:
            source = path.stem
        graph.setdefault(source, set())
        imported_modules = [
            *_absolute_imports(path),
            *_lazy_export_modules(path),
        ]
        for imported in imported_modules:
            prefix = "loushang.harness."
            if not imported.startswith(prefix):
                continue
            target = imported.removeprefix(prefix).split(".", 1)[0]
            if target != source:
                graph[source].add(target)
                graph.setdefault(target, set())
    return graph


def _lazy_export_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    modules: list[str] = []
    for node in tree.body:
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_EXPORT_MODULES"
            for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_EXPORT_MODULES"
        ):
            value = node.value
        if not isinstance(value, ast.Dict):
            continue
        modules.extend(
            item.value
            for item in value.values
            if isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and item.value.startswith("loushang.harness.")
        )
    return modules


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[tuple[str, ...]]:
    next_index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal next_index
        indices[node] = next_index
        lowlinks[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack.add(node)

        for target in sorted(graph.get(node, set())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def _import_from_targets(path: Path, node: ast.ImportFrom) -> list[str]:
    module = _resolve_import_from_module(path, node)
    if module is None:
        return [f"{UNRESOLVED_RELATIVE_IMPORT}:{_format_import_from(node)}"]

    imports = [module]
    imports.extend(
        f"{module}.{alias.name}" for alias in node.names if alias.name != "*"
    )
    return imports


def _resolve_import_from_module(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module

    package_parts = _package_parts(path)
    if package_parts is None:
        return None

    ancestor_length = len(package_parts) - (node.level - 1)
    if ancestor_length <= 0:
        return None

    module_parts = package_parts[:ancestor_length]
    if node.module is not None:
        module_parts.extend(node.module.split("."))

    return ".".join(module_parts)


def _package_parts(path: Path) -> list[str] | None:
    path_parts = path.with_suffix("").parts
    src_indices = [index for index, part in enumerate(path_parts) if part == "src"]
    if not src_indices:
        return None

    package_parts = list(path_parts[src_indices[-1] + 1 : -1])
    if not package_parts:
        return None

    return package_parts


def _format_import_from(node: ast.ImportFrom) -> str:
    module = "." * node.level + (node.module or "")
    names = ", ".join(alias.name for alias in node.names)
    return f"from {module} import {names}"


def _matches_any(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes
    )
