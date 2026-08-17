from __future__ import annotations

import importlib
import subprocess
import sys

_MODULE_EXPORTS = {
    "types": (
        "ArtifactRef",
        "ArtifactStatus",
        "DeliveryHint",
        "WorkCancellationOutcome",
        "WorkCancellationStatus",
        "WorkEvent",
        "WorkEventFact",
        "WorkOperation",
        "WorkPlanRun",
        "WorkRun",
        "WorkRunSpec",
        "WorkRunStatus",
        "WorkStepDeviation",
        "WorkStepRun",
        "WorkStepSpec",
        "WorkStepStatus",
    ),
    "event_log": (
        "EventLogBackend",
        "EventLogEntry",
        "EventPosition",
        "InMemoryEventLogBackend",
        "JsonlEventLogBackend",
    ),
    "ports": (
        "WorkAcceptPort",
        "WorkCancelPort",
        "WorkDomainCancellation",
        "WorkDomainExecutionResolver",
        "WorkDomainExecutor",
        "WorkExecutionBinding",
        "WorkExecutionContext",
        "WorkEventPublisher",
        "WorkQueryPort",
        "WorkSubscribePort",
        "WorkWaitPort",
    ),
    "runtime": (
        "DuplicateWorkOperationError",
        "UnknownWorkRunError",
        "WorkCancellationFailedError",
        "WorkCancellationTimeoutError",
        "WorkLifecycleOwnershipError",
        "WorkRunTerminalError",
        "WorkRuntime",
        "WorkRuntimeError",
    ),
    "run_projection": ("WorkRunReplayError", "project_work_runs"),
    "plan_projection": ("project_work_plan_runs",),
    "cli": (
        "WorkLogInspectionError",
        "create_work_event_log",
        "inspect_work_log",
        "resolve_work_log_path",
        "run_work_log_inspection_operation",
    ),
}

_INTEGRATION_FORWARDERS = {
    "session": (
        "loushang.harnesswork.integrations.session",
        (
            "PreparedSessionWorkTurn",
            "RuntimeEventListener",
            "SessionEventFactProjector",
            "SessionIdReader",
            "SessionOperationInProgressError",
            "SessionPromptPort",
            "SessionTurnExecutor",
            "SessionTurnHook",
            "SessionWorkHostPort",
            "SessionWorkProfile",
            "SessionWorkRuntime",
            "SessionWorkTurn",
            "project_prepared_session_work_turns",
            "require_session_work_turn",
            "submit_session_turn",
        ),
    ),
    "agent_projection": (
        "loushang.harnesswork.integrations.agent_session",
        (
            "AgentWorkFactProjectionContext",
            "create_agent_session_work_runtime",
            "project_agent_event_to_work_facts",
            "project_agent_runtime_event_to_work_facts",
        ),
    ),
    "projection": (
        "loushang.harnesswork.integrations.agent_events",
        ("WorkEventProjectionContext", "project_agent_event_to_work_events"),
    ),
}


def test_harnesswork_public_api_is_the_product_neutral_work_kernel() -> None:
    import loushang.harnesswork as harnesswork

    expected = {
        symbol
        for module_exports in _MODULE_EXPORTS.values()
        for symbol in module_exports
    }

    assert set(harnesswork.__all__) == expected
    assert not hasattr(harnesswork, "AgentWorkFactProjectionContext")
    assert not hasattr(harnesswork, "SessionWorkRuntime")
    assert hasattr(harnesswork, "project_work_plan_runs")


def test_legacy_work_kernel_modules_forward_the_canonical_symbols() -> None:
    for module_name, symbols in _MODULE_EXPORTS.items():
        canonical = importlib.import_module(f"loushang.harnesswork.{module_name}")
        legacy = importlib.import_module(f"loushang.work.{module_name}")

        assert legacy.__all__ == canonical.__all__
        for symbol in symbols:
            canonical_value = getattr(canonical, symbol)
            assert getattr(legacy, symbol) is canonical_value
            if isinstance(canonical_value, type):
                assert canonical_value.__module__.startswith("loushang.harnesswork")


def test_importing_harnesswork_does_not_load_domains_or_legacy_work() -> None:
    script = """
import sys
import loushang.harnesswork

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.channel",
    "loushang.coding",
    "loushang.harnesstui",
    "loushang.method",
    "loushang.ontology",
    "loushang.tui",
    "loushang.work",
)
loaded = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert loaded == [], loaded
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_legacy_integration_modules_forward_canonical_symbols() -> None:
    for legacy_name, (canonical_name, symbols) in _INTEGRATION_FORWARDERS.items():
        legacy = importlib.import_module(f"loushang.work.{legacy_name}")
        canonical = importlib.import_module(canonical_name)

        assert legacy.__all__ == canonical.__all__
        for symbol in symbols:
            canonical_value = getattr(canonical, symbol)
            assert getattr(legacy, symbol) is canonical_value
            owner = getattr(canonical_value, "__module__", "")
            if owner.startswith("loushang"):
                assert owner == canonical_name


def test_legacy_and_canonical_kernel_import_order_is_stable() -> None:
    for first, second in (
        ("loushang.work", "loushang.harnesswork"),
        ("loushang.harnesswork", "loushang.work"),
    ):
        script = f"""
import importlib

first = importlib.import_module({first!r})
second = importlib.import_module({second!r})
legacy = importlib.import_module("loushang.work")
canonical = importlib.import_module("loushang.harnesswork")

assert legacy.WorkRuntime is canonical.WorkRuntime
assert legacy.WorkOperation is canonical.WorkOperation
assert legacy.project_work_runs is canonical.project_work_runs
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )

        assert completed.returncode == 0, completed.stderr
