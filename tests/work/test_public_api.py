from __future__ import annotations


def test_work_public_api_exposes_current_work_surface_without_multi_agent_types() -> (
    None
):
    import loushang.work as work

    assert set(work.__all__) == {
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
        "WorkEvent",
        "WorkEventFact",
        "WorkEventProjectionContext",
        "WorkLogInspectionError",
        "WorkAcceptPort",
        "WorkCancelPort",
        "WorkCancellationFailedError",
        "WorkCancellationOutcome",
        "WorkCancellationStatus",
        "WorkCancellationTimeoutError",
        "WorkDomainExecutor",
        "WorkDomainCancellation",
        "WorkDomainExecutionResolver",
        "WorkExecutionBinding",
        "WorkExecutionContext",
        "WorkLifecycleOwnershipError",
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
            "create_agent_session_work_runtime",
            "create_work_event_log",
            "project_agent_event_to_work_events",
        "project_agent_event_to_work_facts",
        "project_agent_runtime_event_to_work_facts",
        "project_work_plan_runs",
        "project_work_runs",
        "inspect_work_log",
        "run_work_log_inspection_operation",
        "resolve_work_log_path",
    }

    assert not hasattr(work, "AgentLane")
    assert not hasattr(work, "TaskLedger")
    assert not hasattr(work, "CollaborationBus")
    assert not hasattr(work, "CodingWorkShell")
    assert not hasattr(work, "PromptSession")


def test_work_ports_are_split_by_runtime_capability() -> None:
    from loushang.work.ports import (
        WorkAcceptPort,
        WorkCancelPort,
        WorkDomainExecutor,
        WorkExecutionContext,
        WorkQueryPort,
        WorkSubscribePort,
        WorkWaitPort,
    )

    assert set(WorkAcceptPort.__dict__) >= {"accept"}
    assert set(WorkWaitPort.__dict__) >= {"wait"}
    assert set(WorkCancelPort.__dict__) >= {"cancel"}
    assert set(WorkSubscribePort.__dict__) >= {"subscribe"}
    assert set(WorkQueryPort.__dict__) >= {"query"}
    assert set(WorkDomainExecutor.__dict__) >= {"execute"}
    assert set(WorkExecutionContext.__dict__) >= {
        "run_id",
        "step_id",
        "step_index",
        "step_payload",
        "publish",
    }


def test_work_projection_exports_remain_available_from_the_root_package() -> None:
    import loushang.work as work
    from loushang.work.projection import (
        WorkEventProjectionContext,
        project_agent_event_to_work_events,
    )

    assert work.WorkEventProjectionContext is WorkEventProjectionContext
    assert work.project_agent_event_to_work_events is project_agent_event_to_work_events


def test_agent_fact_projection_is_work_owned() -> None:
    import loushang.work as work
    from loushang.work.agent_projection import (
        AgentWorkFactProjectionContext,
        project_agent_event_to_work_facts,
    )

    assert work.AgentWorkFactProjectionContext is AgentWorkFactProjectionContext
    assert work.project_agent_event_to_work_facts is project_agent_event_to_work_facts
