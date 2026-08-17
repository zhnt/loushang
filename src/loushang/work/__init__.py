from importlib import import_module
from typing import TYPE_CHECKING

from loushang.work.types import (
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
    from loushang.work.agent_projection import (
        AgentWorkFactProjectionContext,
        create_agent_session_work_runtime,
        project_agent_event_to_work_facts,
        project_agent_runtime_event_to_work_facts,
    )
    from loushang.work.event_log import (
        EventLogBackend,
        EventLogEntry,
        EventPosition,
        InMemoryEventLogBackend,
        JsonlEventLogBackend,
    )
    from loushang.work.plan_projection import project_work_plan_runs
    from loushang.work.ports import (
        WorkAcceptPort,
        WorkCancelPort,
        WorkDomainCancellation,
        WorkDomainExecutionResolver,
        WorkDomainExecutor,
        WorkExecutionBinding,
        WorkExecutionContext,
        WorkQueryPort,
        WorkSubscribePort,
        WorkWaitPort,
    )
    from loushang.work.projection import (
        WorkEventProjectionContext,
        project_agent_event_to_work_events,
    )
    from loushang.work.run_projection import WorkRunReplayError, project_work_runs
    from loushang.work.runtime import (
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
    "AgentWorkFactProjectionContext": (
        "loushang.work.agent_projection",
        "AgentWorkFactProjectionContext",
    ),
    "project_agent_event_to_work_facts": (
        "loushang.work.agent_projection",
        "project_agent_event_to_work_facts",
    ),
    "project_agent_runtime_event_to_work_facts": (
        "loushang.work.agent_projection",
        "project_agent_runtime_event_to_work_facts",
    ),
    "create_agent_session_work_runtime": (
        "loushang.work.agent_projection",
        "create_agent_session_work_runtime",
    ),
    "EventLogBackend": ("loushang.work.event_log", "EventLogBackend"),
    "EventLogEntry": ("loushang.work.event_log", "EventLogEntry"),
    "EventPosition": ("loushang.work.event_log", "EventPosition"),
    "InMemoryEventLogBackend": (
        "loushang.work.event_log",
        "InMemoryEventLogBackend",
    ),
    "JsonlEventLogBackend": (
        "loushang.work.event_log",
        "JsonlEventLogBackend",
    ),
    "WorkEventProjectionContext": (
        "loushang.work.projection",
        "WorkEventProjectionContext",
    ),
    "project_agent_event_to_work_events": (
        "loushang.work.projection",
        "project_agent_event_to_work_events",
    ),
    "project_work_plan_runs": (
        "loushang.work.plan_projection",
        "project_work_plan_runs",
    ),
    "WorkLogInspectionError": (
        "loushang.work.cli",
        "WorkLogInspectionError",
    ),
    "inspect_work_log": ("loushang.work.cli", "inspect_work_log"),
    "run_work_log_inspection_operation": (
        "loushang.work.cli",
        "run_work_log_inspection_operation",
    ),
    "create_work_event_log": ("loushang.work.cli", "create_work_event_log"),
    "resolve_work_log_path": ("loushang.work.cli", "resolve_work_log_path"),
    "project_work_runs": ("loushang.work.run_projection", "project_work_runs"),
    "WorkRunReplayError": (
        "loushang.work.run_projection",
        "WorkRunReplayError",
    ),
    "WorkAcceptPort": ("loushang.work.ports", "WorkAcceptPort"),
    "WorkCancelPort": ("loushang.work.ports", "WorkCancelPort"),
    "WorkDomainExecutor": ("loushang.work.ports", "WorkDomainExecutor"),
    "WorkDomainCancellation": (
        "loushang.work.ports",
        "WorkDomainCancellation",
    ),
    "WorkDomainExecutionResolver": (
        "loushang.work.ports",
        "WorkDomainExecutionResolver",
    ),
    "WorkExecutionBinding": ("loushang.work.ports", "WorkExecutionBinding"),
    "WorkExecutionContext": ("loushang.work.ports", "WorkExecutionContext"),
    "WorkQueryPort": ("loushang.work.ports", "WorkQueryPort"),
    "WorkSubscribePort": ("loushang.work.ports", "WorkSubscribePort"),
    "WorkWaitPort": ("loushang.work.ports", "WorkWaitPort"),
    "DuplicateWorkOperationError": (
        "loushang.work.runtime",
        "DuplicateWorkOperationError",
    ),
    "WorkCancellationFailedError": (
        "loushang.work.runtime",
        "WorkCancellationFailedError",
    ),
    "WorkCancellationTimeoutError": (
        "loushang.work.runtime",
        "WorkCancellationTimeoutError",
    ),
    "UnknownWorkRunError": ("loushang.work.runtime", "UnknownWorkRunError"),
    "WorkLifecycleOwnershipError": (
        "loushang.work.runtime",
        "WorkLifecycleOwnershipError",
    ),
    "WorkRunTerminalError": ("loushang.work.runtime", "WorkRunTerminalError"),
    "WorkRuntime": ("loushang.work.runtime", "WorkRuntime"),
    "WorkRuntimeError": ("loushang.work.runtime", "WorkRuntimeError"),
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
    "AgentWorkFactProjectionContext",
    "ArtifactRef",
    "ArtifactStatus",
    "DeliveryHint",
    "DuplicateWorkOperationError",
    "EventLogBackend",
    "EventLogEntry",
    "EventPosition",
    "InMemoryEventLogBackend",
    "JsonlEventLogBackend",
    "create_work_event_log",
    "WorkEventProjectionContext",
    "WorkEvent",
    "WorkEventFact",
    "WorkCancellationOutcome",
    "WorkCancellationStatus",
    "WorkAcceptPort",
    "WorkCancelPort",
    "WorkDomainExecutor",
    "WorkDomainCancellation",
    "WorkDomainExecutionResolver",
    "WorkExecutionBinding",
    "WorkExecutionContext",
    "WorkLifecycleOwnershipError",
    "WorkCancellationFailedError",
    "WorkCancellationTimeoutError",
    "WorkOperation",
    "WorkPlanRun",
    "WorkRun",
    "WorkRunStatus",
    "WorkRunSpec",
    "WorkRunReplayError",
    "WorkRunTerminalError",
    "WorkRuntime",
    "WorkRuntimeError",
    "UnknownWorkRunError",
    "WorkQueryPort",
    "WorkSubscribePort",
    "WorkWaitPort",
    "WorkStepDeviation",
    "WorkStepSpec",
    "WorkStepRun",
    "WorkStepStatus",
    "project_agent_event_to_work_events",
    "project_agent_event_to_work_facts",
    "project_agent_runtime_event_to_work_facts",
    "create_agent_session_work_runtime",
    "project_work_plan_runs",
    "project_work_runs",
    "WorkLogInspectionError",
    "inspect_work_log",
    "run_work_log_inspection_operation",
    "resolve_work_log_path",
]
