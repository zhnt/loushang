"""Product-neutral in-process runtime event contracts and delivery."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "BranchSummaryCompleted": "loushang.harness.events.session",
    "BranchSummaryStarted": "loushang.harness.events.session",
    "CompactionReason": "loushang.harness.events.session",
    "CompactionStage": "loushang.harness.events.session",
    "ContextCompactionCompleted": "loushang.harness.events.session",
    "ContextCompactionStarted": "loushang.harness.events.session",
    "ConversationMetadataChanged": "loushang.harness.events.session",
    "EventListener": "loushang.harness.events.protocols",
    "EventPublisher": "loushang.harness.events.protocols",
    "HostLifecycleEvent": "loushang.harness.events.host",
    "HostLifecycleEventKind": "loushang.harness.events.host",
    "HostStatus": "loushang.harness.events.host",
    "OrderedEventBus": "loushang.harness.events.bus",
    "PackageProgressAction": "loushang.harness.events.session",
    "PackageProgressChanged": "loushang.harness.events.session",
    "PackageProgressType": "loushang.harness.events.session",
    "PermissionProfileChanged": "loushang.harness.events.session",
    "QueueChanged": "loushang.harness.events.session",
    "QueuedMessageSnapshot": "loushang.harness.events.session",
    "QueueKind": "loushang.harness.events.session",
    "QueueSnapshot": "loushang.harness.events.session",
    "RetryAttempt": "loushang.harness.events.session",
    "RetryCompleted": "loushang.harness.events.session",
    "RetryOutcome": "loushang.harness.events.session",
    "RetryStarted": "loushang.harness.events.session",
    "RuntimeEvent": "loushang.harness.events.types",
    "RuntimeEventDeliveryHint": "loushang.harness.events.projection",
    "RuntimeEventPublisher": "loushang.harness.events.publisher",
    "RuntimeEventView": "loushang.harness.events.projection",
    "event_writes_transcript": "loushang.harness.events.recording_policy",
    "is_cancelled_error_message": "loushang.harness.events.recording_policy",
    "SessionRuntimeEventPayload": "loushang.harness.events.session",
    "ToolPolicyAuditEvent": "loushang.harness.events.session",
    "ToolPolicyAuditEventType": "loushang.harness.events.session",
    "TranscriptRecordCommitted": "loushang.harness.events.types",
    "matches_event_select": "loushang.harness.events.projection",
    "normalize_event_select": "loushang.harness.events.projection",
    "project_runtime_event": "loushang.harness.events.projection",
    "project_session_runtime_event": "loushang.harness.events.runtime_projection",
    "select_runtime_event_views": "loushang.harness.events.projection",
    "snake_case_json_keys": "loushang.harness.events.json",
    "session_runtime_event_kind": "loushang.harness.events.session",
}


def __getattr__(name: str) -> Any:
    """Load optional event contracts only when a caller asks for them."""

    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORT_MODULES})


__all__ = list(_EXPORT_MODULES)
