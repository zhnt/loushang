"""Product-neutral durable Work kernel built on Harness foundations."""

from importlib import import_module
from typing import TYPE_CHECKING

from loushang.harnesswork.types import (
    ArtifactRef,
    ArtifactStatus,
    DeliveryHint,
    WorkCancellationOutcome,
    WorkCancellationStatus,
    WorkEvent,
    WorkEventFact,
    WorkOperation,
    WorkPlanRun,
    WorkRun,
    WorkRunSpec,
    WorkRunStatus,
    WorkStepDeviation,
    WorkStepRun,
    WorkStepSpec,
    WorkStepStatus,
)

if TYPE_CHECKING:
    from loushang.harnesswork.cli import (
        WorkLogInspectionError,
        create_work_event_log,
        inspect_work_log,
        resolve_work_log_path,
        run_work_log_inspection_operation,
    )
    from loushang.harnesswork.event_log import (
        EventLogBackend,
        EventLogEntry,
        EventPosition,
        InMemoryEventLogBackend,
        JsonlEventLogBackend,
    )
    from loushang.harnesswork.plan_projection import project_work_plan_runs
    from loushang.harnesswork.ports import (
        WorkAcceptPort,
        WorkCancelPort,
        WorkDomainCancellation,
        WorkDomainExecutionResolver,
        WorkDomainExecutor,
        WorkEventPublisher,
        WorkExecutionBinding,
        WorkExecutionContext,
        WorkQueryPort,
        WorkSubscribePort,
        WorkWaitPort,
    )
    from loushang.harnesswork.run_projection import (
        WorkRunReplayError,
        project_work_runs,
    )
    from loushang.harnesswork.runtime import (
        DuplicateWorkOperationError,
        UnknownWorkRunError,
        WorkCancellationFailedError,
        WorkCancellationTimeoutError,
        WorkLifecycleOwnershipError,
        WorkRunTerminalError,
        WorkRuntime,
        WorkRuntimeError,
    )

_LAZY_EXPORTS = {
    "WorkLogInspectionError": (
        "loushang.harnesswork.cli",
        "WorkLogInspectionError",
    ),
    "create_work_event_log": (
        "loushang.harnesswork.cli",
        "create_work_event_log",
    ),
    "inspect_work_log": ("loushang.harnesswork.cli", "inspect_work_log"),
    "resolve_work_log_path": (
        "loushang.harnesswork.cli",
        "resolve_work_log_path",
    ),
    "run_work_log_inspection_operation": (
        "loushang.harnesswork.cli",
        "run_work_log_inspection_operation",
    ),
    "EventLogBackend": ("loushang.harnesswork.event_log", "EventLogBackend"),
    "EventLogEntry": ("loushang.harnesswork.event_log", "EventLogEntry"),
    "EventPosition": ("loushang.harnesswork.event_log", "EventPosition"),
    "InMemoryEventLogBackend": (
        "loushang.harnesswork.event_log",
        "InMemoryEventLogBackend",
    ),
    "JsonlEventLogBackend": (
        "loushang.harnesswork.event_log",
        "JsonlEventLogBackend",
    ),
    "project_work_plan_runs": (
        "loushang.harnesswork.plan_projection",
        "project_work_plan_runs",
    ),
    "project_work_runs": (
        "loushang.harnesswork.run_projection",
        "project_work_runs",
    ),
    "WorkRunReplayError": (
        "loushang.harnesswork.run_projection",
        "WorkRunReplayError",
    ),
    "WorkAcceptPort": ("loushang.harnesswork.ports", "WorkAcceptPort"),
    "WorkCancelPort": ("loushang.harnesswork.ports", "WorkCancelPort"),
    "WorkDomainExecutor": ("loushang.harnesswork.ports", "WorkDomainExecutor"),
    "WorkDomainCancellation": (
        "loushang.harnesswork.ports",
        "WorkDomainCancellation",
    ),
    "WorkDomainExecutionResolver": (
        "loushang.harnesswork.ports",
        "WorkDomainExecutionResolver",
    ),
    "WorkExecutionBinding": (
        "loushang.harnesswork.ports",
        "WorkExecutionBinding",
    ),
    "WorkExecutionContext": (
        "loushang.harnesswork.ports",
        "WorkExecutionContext",
    ),
    "WorkEventPublisher": (
        "loushang.harnesswork.ports",
        "WorkEventPublisher",
    ),
    "WorkQueryPort": ("loushang.harnesswork.ports", "WorkQueryPort"),
    "WorkSubscribePort": ("loushang.harnesswork.ports", "WorkSubscribePort"),
    "WorkWaitPort": ("loushang.harnesswork.ports", "WorkWaitPort"),
    "DuplicateWorkOperationError": (
        "loushang.harnesswork.runtime",
        "DuplicateWorkOperationError",
    ),
    "WorkCancellationFailedError": (
        "loushang.harnesswork.runtime",
        "WorkCancellationFailedError",
    ),
    "WorkCancellationTimeoutError": (
        "loushang.harnesswork.runtime",
        "WorkCancellationTimeoutError",
    ),
    "UnknownWorkRunError": (
        "loushang.harnesswork.runtime",
        "UnknownWorkRunError",
    ),
    "WorkLifecycleOwnershipError": (
        "loushang.harnesswork.runtime",
        "WorkLifecycleOwnershipError",
    ),
    "WorkRunTerminalError": (
        "loushang.harnesswork.runtime",
        "WorkRunTerminalError",
    ),
    "WorkRuntime": ("loushang.harnesswork.runtime", "WorkRuntime"),
    "WorkRuntimeError": ("loushang.harnesswork.runtime", "WorkRuntimeError"),
}


def __getattr__(name: str) -> object:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "ArtifactRef",
    "ArtifactStatus",
    "DeliveryHint",
    "DuplicateWorkOperationError",
    "EventLogBackend",
    "EventLogEntry",
    "EventPosition",
    "InMemoryEventLogBackend",
    "JsonlEventLogBackend",
    "WorkLogInspectionError",
    "UnknownWorkRunError",
    "WorkAcceptPort",
    "WorkCancelPort",
    "WorkCancellationFailedError",
    "WorkCancellationOutcome",
    "WorkCancellationStatus",
    "WorkCancellationTimeoutError",
    "WorkDomainCancellation",
    "WorkDomainExecutionResolver",
    "WorkDomainExecutor",
    "WorkEvent",
    "WorkEventFact",
    "WorkExecutionBinding",
    "WorkExecutionContext",
    "WorkEventPublisher",
    "WorkLifecycleOwnershipError",
    "WorkOperation",
    "WorkPlanRun",
    "WorkQueryPort",
    "WorkRun",
    "WorkRunReplayError",
    "WorkRunSpec",
    "WorkRunStatus",
    "WorkRunTerminalError",
    "WorkRuntime",
    "WorkRuntimeError",
    "WorkStepDeviation",
    "WorkStepRun",
    "WorkStepSpec",
    "WorkStepStatus",
    "WorkSubscribePort",
    "WorkWaitPort",
    "create_work_event_log",
    "inspect_work_log",
    "project_work_plan_runs",
    "project_work_runs",
    "resolve_work_log_path",
    "run_work_log_inspection_operation",
]
