"""Strict closed execution algebra, negotiated separately from legacy v1."""

from __future__ import annotations

from enum import Enum
from types import UnionType
from typing import Literal, Union, cast, get_args, get_origin, get_type_hints

from ..protocol import (
    AckV1,
    AppFailureV1,
    InvalidAppMessageError,
    SessionEventV1,
    SessionIdentityV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    SessionSubmissionModeV1,
    TranscriptRecordV1,
    UserChoiceOptionV1,
    UserChoicePromptV1,
)
from ..protocol.codec import _dumps, _loads, _object, _string
from ..resume_model import ResumeInputLookupQueryV1, ResumeInputLookupResultV1
from .model import (
    ExecutionCallV1,
    ExecutionContentEventV1,
    ExecutionEventsV1,
    ExecutionFailureV1,
    ExecutionGoalBatchV1,
    ExecutionGoalProgressV1,
    ExecutionInterruptResultV1,
    ExecutionObservationV1,
    ExecutionOperationV1,
    ExecutionOutcomeV1,
    ExecutionRecordV1,
    ExecutionResponseV1,
    ExecutionResultV1,
    ExecutionSessionSnapshotV1,
    ExecutionSessionViewV1,
    ExecutionSourceSnapshotV1,
    ExecutionStateV1,
    ExecutionUpdateV1,
    InteractiveGoalCommandV1,
    InteractiveGoalCommandViewV1,
    InteractiveGoalRecoveryV1,
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    InteractiveGoalViewV1,
    _identifier,
)

EXECUTION_PROTOCOL_VERSION = "loushang.execution/v1"

# Explicit fields freeze the wire independently of future dataclass additions.
# No arbitrary type/name lookup or untyped Product payload is admitted.
_FIELDS: dict[type, tuple[str, ...]] = {
    ResumeInputLookupQueryV1: ("input_id", "record_digest"),
    ResumeInputLookupResultV1: ("input_id", "record_id", "status"),
    AckV1: (), AppFailureV1: ("code",), ExecutionFailureV1: ("code",),
    SessionIdentityV1: ("product_id", "continuity_id", "session_id", "scope", "scope_fingerprint"),
    TranscriptRecordV1: ("kind", "text"),
    UserChoiceOptionV1: ("id", "label", "description"),
    UserChoicePromptV1: ("question_id", "question", "options"),
    SessionSnapshotV1: ("identity", "title", "cursor", "revision", "running", "records"),
    SessionSnapshotRequestV1: ("attachment_id", "controller_generation", "member_id"),
    SessionEventV1: ("session_id", "cursor", "kind", "text", "interaction_id"),
    ExecutionOutcomeV1: ("status", "error_code", "legacy_result"),
    ExecutionStateV1: ("execution_id", "status", "revision", "interrupt_requested", "outcome"),
    ExecutionObservationV1: ("execution_id", "status", "final_cursor"),
    ExecutionSourceSnapshotV1: ("source", "observation", "draft", "truncated"),
    ExecutionRecordV1: ("service_instance_id", "identity", "submission_id", "state"),
    ExecutionGoalBatchV1: (
        "batch_id", "work_status", "recording_available", "cancellation_status", "observation_unavailable",
    ),
    ExecutionGoalProgressV1: (
        "execution_id", "presence", "goal_id", "status", "reason_code", "validity",
        "execution_unresolved", "advances", "model_calls", "batch_count", "batches",
    ),
    InteractiveGoalCommandV1: ("goal_id", "command_id", "action"),
    InteractiveGoalCommandViewV1: ("command_id", "action", "status"),
    InteractiveGoalRecoveryV1: (
        "presence", "reason_code", "goal_id", "goal_status", "revision", "epoch",
        "batch_count", "completed_count", "failed_count", "cancelled_count", "orphaned_count",
        "execution_unresolved", "read_only",
    ),
    InteractiveGoalReviewSubmissionV1: ("goal_id", "review_token", "command_id", "decision", "reason"),
    InteractiveGoalReviewV1: ("goal_id", "revision", "epoch", "review_token", "changed_files",
                              "files_truncated", "check_count", "checks_satisfied"),
    InteractiveGoalViewV1: ("availability", "goal_id", "status", "revision", "epoch", "execution_unresolved"),
    ExecutionSessionViewV1: ("identity", "revision", "quiescent", "active", "latest_terminal"),
    ExecutionSessionSnapshotV1: ("service_instance_id", "source", "executions"),
    ExecutionContentEventV1: ("source", "execution_id"),
    ExecutionUpdateV1: ("revision", "execution"),
    ExecutionEventsV1: ("events",),
    ExecutionInterruptResultV1: ("record", "disposition"),
}
_GOAL_CAPABILITIES = (
    "supports_goal_progress", "supports_goal_start", "supports_interactive_goal",
    "supports_interactive_goal_commands", "supports_interactive_goal_recovery",
)
_REVIEW_SUBMISSION_KEYS = {"goalId", "reviewToken", "commandId", "decision", "reason"}
_GOAL_COMMAND_KEYS = {"goalId", "commandId", "action"}

_KINDS: dict[str, type] = {
    "resume_input_lookup": ResumeInputLookupResultV1,
    "goal_progress": ExecutionGoalProgressV1,
    "interactive_goal": InteractiveGoalViewV1,
    "interactive_goal_review": InteractiveGoalReviewV1,
    "interactive_goal_recovery": InteractiveGoalRecoveryV1,
    "record": ExecutionRecordV1, "snapshot": ExecutionSessionSnapshotV1,
    "events": ExecutionEventsV1, "failure": ExecutionFailureV1,
    "app_failure": AppFailureV1,
    "interrupt": ExecutionInterruptResultV1,
}


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


def _encode(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if type(value) is tuple:
        return [_encode(item) for item in value]
    fields = _FIELDS.get(type(value))
    if fields is None:
        raise InvalidAppMessageError()
    encoded = {_camel(name): _encode(getattr(value, name)) for name in fields}
    if type(value) is SessionSnapshotV1:
        if value.submission_mode is SessionSubmissionModeV1.EXECUTION:
            encoded["submissionMode"] = value.submission_mode.value
        if value.user_choice is not None:
            encoded["userChoice"] = _encode(value.user_choice)
    if type(value) is ExecutionSessionSnapshotV1:
        for flag in _GOAL_CAPABILITIES:
            if getattr(value, flag):
                encoded[_camel(flag)] = True
    if type(value) is InteractiveGoalViewV1:
        if value.command is not None:
            encoded["command"] = _encode(value.command)
        if value.review_available:
            encoded["reviewAvailable"] = True
    return encoded


def _decode(expected: object, raw: object) -> object:
    if expected is type(None):
        if raw is not None:
            raise InvalidAppMessageError()
        return None
    if expected in (str, bool, int):
        if type(raw) is not expected:
            raise InvalidAppMessageError()
        return raw
    origin, args = get_origin(expected), get_args(expected)
    if origin is Literal:
        if type(raw) is not str or raw not in args:
            raise InvalidAppMessageError()
        return raw
    if origin in (UnionType, Union):
        for member in args:
            try:
                return _decode(member, raw)
            except (TypeError, ValueError, InvalidAppMessageError):
                pass
        raise InvalidAppMessageError()
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        if type(raw) is not list or len(raw) > 256:
            raise InvalidAppMessageError()
        return tuple(_decode(args[0], item) for item in raw)
    if isinstance(expected, type) and issubclass(expected, Enum):
        return expected(_string(raw))
    if not isinstance(expected, type) or expected not in _FIELDS:
        raise InvalidAppMessageError()
    fields = _FIELDS[expected]
    wire_fields = {_camel(name) for name in fields}
    if expected is SessionSnapshotV1 and type(raw) is dict:
        wire_fields.update({"submissionMode", "userChoice"} & raw.keys())
    if expected is ExecutionSessionSnapshotV1 and type(raw) is dict:
        wire_fields.update(_camel(flag) for flag in _GOAL_CAPABILITIES if _camel(flag) in raw)
    if expected is InteractiveGoalViewV1 and type(raw) is dict:
        wire_fields.update({"command", "reviewAvailable"} & raw.keys())
    value = _object(raw, wire_fields)
    annotations = get_type_hints(expected)
    values = {
        name: _decode(annotations[name], value[_camel(name)]) for name in fields
    }
    if expected is SessionSnapshotV1:
        mode = (
            _decode(SessionSubmissionModeV1, value["submissionMode"])
            if "submissionMode" in value
            else SessionSubmissionModeV1.LEGACY
        )
        if "submissionMode" in value and mode is not SessionSubmissionModeV1.EXECUTION:
            raise InvalidAppMessageError()
        values["submission_mode"] = mode
        if "userChoice" in value:
            values["user_choice"] = _decode(UserChoicePromptV1, value["userChoice"])
    if expected is ExecutionSessionSnapshotV1:
        for flag in _GOAL_CAPABILITIES:
            field = _camel(flag)
            if field in value:
                if value[field] is not True:
                    raise InvalidAppMessageError()
                values[flag] = True
    if expected is InteractiveGoalViewV1:
        if "command" in value:
            values["command"] = _decode(InteractiveGoalCommandViewV1, value["command"])
        if "reviewAvailable" in value:
            if value["reviewAvailable"] is not True:
                raise InvalidAppMessageError()
            values["review_available"] = True
    return expected(**values)


def is_execution_frame(payload: bytes) -> bool:
    return _loads(payload).get("protocolVersion") == EXECUTION_PROTOCOL_VERSION


def encode_call(call: ExecutionCallV1) -> bytes:
    if type(call) is not ExecutionCallV1:
        raise TypeError("invalid execution call")
    body = {
        "control": _encode(call.control), "expectedInstanceId": call.expected_instance_id,
    }
    if call.submission_id is not None:
        body["submissionId"] = call.submission_id
    if call.execution_id is not None:
        body["executionId"] = call.execution_id
    if call.goal_target is not None:
        body["goalTarget"] = call.goal_target
    if call.goal_command is not None:
        body.update(goalId=call.goal_command.goal_id, commandId=call.goal_command.command_id,
                    action=call.goal_command.action)
    if call.review_goal_id is not None:
        body["goalId"] = call.review_goal_id
    if call.review_submission is not None:
        review = _encode(call.review_submission)
        assert isinstance(review, dict)
        body.update(review)
    if call.include_goal_batches:
        body["includeBatches"] = True
    if call.text is not None:
        body["text"] = call.text
    if call.resume_query is not None:
        body["resumeQuery"] = _encode(call.resume_query)
    return _dumps({
        "protocolVersion": EXECUTION_PROTOCOL_VERSION, "requestId": call.request_id,
        "operation": call.operation.value, "payload": body,
    })


def decode_call(payload: bytes) -> ExecutionCallV1:
    try:
        root = _object(_loads(payload), {"protocolVersion", "requestId", "operation", "payload"})
        if root["protocolVersion"] != EXECUTION_PROTOCOL_VERSION:
            raise InvalidAppMessageError()
        operation = ExecutionOperationV1(_string(root["operation"]))
        fields = {"control", "expectedInstanceId"}
        if operation in {
            ExecutionOperationV1.SUBMIT, ExecutionOperationV1.FIND, ExecutionOperationV1.GOAL_START,
        }:
            fields.add("submissionId")
        if operation in {
            ExecutionOperationV1.GET, ExecutionOperationV1.INTERRUPT, ExecutionOperationV1.GOAL_PROGRESS,
        }:
            fields.add("executionId")
        if operation is ExecutionOperationV1.SUBMIT:
            fields.add("text")
        if operation is ExecutionOperationV1.INTERACTIVE_GOAL_CREATE:
            fields.add("goalTarget")
        if operation is ExecutionOperationV1.INTERACTIVE_GOAL_COMMAND:
            fields.update(_GOAL_COMMAND_KEYS)
        if operation is ExecutionOperationV1.RESUME_INPUT_LOOKUP:
            fields.add("resumeQuery")
        if operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW:
            fields.add("goalId")
        if operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW_SUBMIT:
            fields.update(_REVIEW_SUBMISSION_KEYS)
        raw = root["payload"]
        include_batches = (
            operation is ExecutionOperationV1.GOAL_PROGRESS and type(raw) is dict and "includeBatches" in raw
        )
        if include_batches:
            fields.add("includeBatches")
        body = _object(raw, fields)
        if include_batches and body["includeBatches"] is not True:
            raise InvalidAppMessageError()
        return ExecutionCallV1(
            _string(root["requestId"]), operation,
            cast(SessionSnapshotRequestV1, _decode(SessionSnapshotRequestV1, body["control"])),
            _string(body["expectedInstanceId"]),
            _string(body["submissionId"]) if "submissionId" in fields else None,
            _string(body["executionId"]) if "executionId" in fields else None,
            _string(body["text"]) if "text" in fields else None,
            cast(ResumeInputLookupQueryV1, _decode(ResumeInputLookupQueryV1, body["resumeQuery"]))
            if "resumeQuery" in fields else None,
            include_goal_batches=include_batches,
            goal_target=_string(body["goalTarget"]) if "goalTarget" in fields else None,
            goal_command=cast(InteractiveGoalCommandV1, _decode(
                InteractiveGoalCommandV1, {key: body[key] for key in _GOAL_COMMAND_KEYS},
            )) if operation is ExecutionOperationV1.INTERACTIVE_GOAL_COMMAND else None,
            review_goal_id=_string(body["goalId"]) if operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW else None,
            review_submission=cast(InteractiveGoalReviewSubmissionV1, _decode(
                InteractiveGoalReviewSubmissionV1, {key: body[key] for key in _REVIEW_SUBMISSION_KEYS},
            )) if operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW_SUBMIT else None,
        )
    except (TypeError, ValueError, KeyError, RecursionError):
        raise InvalidAppMessageError() from None


def encode_response(response: ExecutionResponseV1, *, include_goal_batches: bool = True) -> bytes:
    if type(response) is not ExecutionResponseV1:
        raise TypeError("invalid execution response")
    kind = "not_found" if response.result is None else next(
        key for key, value in _KINDS.items() if value is type(response.result)
    )
    result = _encode(response.result)
    if type(response.result) is ExecutionGoalProgressV1 and not include_goal_batches:
        # Retain the closed legacy shape for callers that did not request details.
        assert isinstance(result, dict)
        del result["batches"]
    return _dumps({
        "protocolVersion": EXECUTION_PROTOCOL_VERSION, "requestId": response.request_id,
        "resultType": kind, "result": result,
    })


def decode_response(payload: bytes) -> ExecutionResponseV1:
    try:
        root = _object(_loads(payload), {"protocolVersion", "requestId", "resultType", "result"})
        if root["protocolVersion"] != EXECUTION_PROTOCOL_VERSION:
            raise InvalidAppMessageError()
        kind = _string(root["resultType"])
        expected = type(None) if kind == "not_found" else _KINDS[kind]
        return ExecutionResponseV1(
            _string(root["requestId"]), cast(ExecutionResultV1, _decode(expected, root["result"]))
        )
    except (TypeError, ValueError, KeyError, RecursionError):
        raise InvalidAppMessageError() from None


def execution_hello(profile: str, service_instance_id: str) -> bytes:
    _identifier(service_instance_id)
    return _dumps({
        "profile": profile, "protocolVersion": "loushang.app/v1",
        "executionVersion": EXECUTION_PROTOCOL_VERSION, "serviceInstanceId": service_instance_id,
        "submissionRetention": "service_instance_lifetime",
        "restartRecovery": False,
    })


def decode_execution_hello(payload: bytes, profile: str) -> str:
    root = _loads(payload)
    instance = _string(root.get("serviceInstanceId"))
    try:
        if payload != execution_hello(profile, instance):
            raise InvalidAppMessageError()
    except (TypeError, ValueError):
        raise InvalidAppMessageError() from None
    return instance
