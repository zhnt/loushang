"""Model-checked snapshot/event evidence, including states; not runtime fixtures."""

import copy
import json
from dataclasses import replace
from pathlib import Path

from loushang.appserver.execution import model as em
from loushang.appserver.execution.codec import decode_response, encode_response
from loushang.appserver.protocol import InvalidAppMessageError
from loushang.appserver.protocol import model as pm


def emit_projection_vectors() -> None:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "tests/appserver/fixtures/execution_v1.json"
    )
    identity = decode_response(
        json.dumps(json.loads(fixture.read_text(encoding="utf-8"))["accepted"]).encode()
    ).result.identity
    observation = em.ExecutionObservationV1()
    snapshot = em.ExecutionSessionSnapshotV1(
        "instance",
        em.ExecutionSourceSnapshotV1(
            pm.SessionSnapshotV1(
                identity,
                "空闲会话",
                0,
                0,
                False,
                (pm.TranscriptRecordV1(pm.TranscriptRecordKindV1.USER, "你好"),),
            ),
            observation,
        ),
        em.ExecutionSessionViewV1(identity, 0, observation),
    )
    base = json.loads(encode_response(em.ExecutionResponseV1("snapshot", snapshot)))
    cases = []

    def add(name, kind, value, valid=True):
        cases.append((name, kind, json.dumps(value, ensure_ascii=False), valid))

    add("idle", "snapshot", base)
    for field in ("supportsGoalProgress", "supportsGoalStart", "supportsInteractiveGoal"):
        for flag in (True, False, None):
            value = copy.deepcopy(base)
            value["result"][field] = flag
            add(f"{field}-{flag}", "snapshot", value, flag is True)
    goal_ready = replace(snapshot, supports_goal_start=True, supports_goal_progress=True)
    goal_ready_wire = json.loads(encode_response(em.ExecutionResponseV1("goal-ready", goal_ready)))
    add("goal-ready", "snapshot", goal_ready_wire)
    interactive = em.InteractiveGoalViewV1("present", "dynamic-1", "active", 1, 1, False)
    interactive_wire = json.loads(encode_response(em.ExecutionResponseV1("dynamic", interactive)))
    add("interactive-present", "interactive_goal", interactive_wire)
    for availability in ("ready", "not_ready", "creating", "historical", "cleanup_pending"):
        response = em.ExecutionResponseV1("dynamic", em.InteractiveGoalViewV1(availability))
        add(f"interactive-{availability}", "interactive_goal", json.loads(encode_response(response)))
    for field, invalid in (
        ("availability", "ready"), ("status", "running"), ("goalId", "/private/file"),
        ("revision", 0), ("epoch", 2**53), ("executionUnresolved", 0), ("goalTarget", "private"),
    ):
        value = copy.deepcopy(interactive_wire)
        value["result"][field] = invalid
        add(f"interactive-invalid-{field}", "interactive_goal", value, False)
    missing = copy.deepcopy(interactive_wire)
    del missing["result"]["status"]
    add("interactive-missing-status", "interactive_goal", missing, False)
    capable = replace(snapshot, supports_interactive_goal=True, supports_interactive_goal_commands=True)
    capable_wire = json.loads(encode_response(em.ExecutionResponseV1("command-capability", capable)))
    add("interactive-commands-capability", "snapshot", capable_wire)
    for value in (False, None):
        invalid = copy.deepcopy(capable_wire)
        invalid["result"]["supportsInteractiveGoalCommands"] = value
        add(f"interactive-commands-capability-{value}", "snapshot", invalid, False)
    invalid = copy.deepcopy(capable_wire)
    del invalid["result"]["supportsInteractiveGoal"]
    add("interactive-commands-without-goal", "snapshot", invalid, False)
    for action, status in (
        ("run", "running"), ("step", "finished"), ("pause", "settling"),
        ("cancel", "unknown"), ("resume", "failed"),
    ):
        command = em.InteractiveGoalCommandViewV1("gui-1", action, status)
        view = replace(interactive, command=command)
        response = em.ExecutionResponseV1("interactive-command", view)
        add(f"interactive-{action}-{status}", "interactive_goal", json.loads(encode_response(response)))
    for name, command in (
        ("null", None), ("unknown", {"commandId": "gui-1", "action": "abandon", "status": "finished"}),
        ("identity", {"commandId": "/private", "action": "run", "status": "finished"}),
        ("cancel-running", {"commandId": "gui-1", "action": "cancel", "status": "running"}),
        ("run-settling", {"commandId": "gui-1", "action": "run", "status": "settling"}),
        ("extra", {"commandId": "gui-1", "action": "pause", "status": "settling", "error": "private"}),
        ("missing", {"commandId": "gui-1", "action": "run"}),
    ):
        invalid = copy.deepcopy(interactive_wire)
        invalid["result"]["command"] = command
        add(f"interactive-command-invalid-{name}", "interactive_goal", invalid, False)
    invalid = json.loads(encode_response(em.ExecutionResponseV1("ready", em.InteractiveGoalViewV1("ready"))))
    invalid["result"]["command"] = {"commandId": "gui-1", "action": "run", "status": "running"}
    add("interactive-command-nonpresent", "interactive_goal", invalid, False)
    paused = replace(interactive, status="paused", review_available=True)
    reviewable = json.loads(encode_response(em.ExecutionResponseV1("reviewable", paused)))
    add("interactive-reviewable", "interactive_goal", reviewable)
    for field, value in (("reviewAvailable", None), ("reviewAvailable", False), ("status", "active"), ("executionUnresolved", True)):
        invalid = copy.deepcopy(reviewable)
        invalid["result"][field] = value
        add(f"reviewable-invalid-{field}-{value}", "interactive_goal", invalid, False)
    decision = replace(interactive, command=em.InteractiveGoalCommandViewV1("accept-1", "accept", "running"))
    add("interactive-accept-running", "interactive_goal", json.loads(encode_response(em.ExecutionResponseV1("accept", decision))))
    review = em.InteractiveGoalReviewV1("dynamic-1", 2, 5, "a" * 64, ("hello.txt", "目录/说明.md"), False, 1, False)
    summary = json.loads(encode_response(em.ExecutionResponseV1("review", review)))
    add("interactive-review-summary", "interactive_goal_review", summary)
    for field, value in (
        ("goalId", "/other"), ("reviewToken", "x" * 64), ("revision", 0), ("epoch", 2**53),
        ("changedFiles", ["../outside"]), ("changedFiles", ["/absolute"]),
        ("changedFiles", ["C:/outside"]), ("changedFiles", ["a", "a"]),
        ("changedFiles", [f"path-{n}" for n in range(101)]), ("changedFiles", ["界" * 350]),
        ("checkCount", 9), ("filesTruncated", 0), ("checksSatisfied", 1), ("inventory", {}),
    ):
        invalid = copy.deepcopy(summary)
        invalid["result"][field] = value
        add(f"interactive-review-invalid-{field}", "interactive_goal_review", invalid, False)
    recovery_snapshot = replace(snapshot, supports_interactive_goal_recovery=True)
    recovery_wire = json.loads(encode_response(em.ExecutionResponseV1("recovery-capability", recovery_snapshot)))
    add("interactive-recovery-capability", "snapshot", recovery_wire)
    for flag in (None, False):
        item = copy.deepcopy(recovery_wire)
        item["result"]["supportsInteractiveGoalRecovery"] = flag
        add(f"interactive-recovery-capability-{flag}", "snapshot", item, False)
    for recovery in (
        em.InteractiveGoalRecoveryV1("absent", "no_goal"),
        em.InteractiveGoalRecoveryV1("unavailable", "goal_journal_invalid", execution_unresolved=True),
        em.InteractiveGoalRecoveryV1("present", "requirements_satisfied", "goal-1", "completed", 1, 2, 4, 4),
        em.InteractiveGoalRecoveryV1("present", "review_required", "goal-1", "paused", 1, 2, 3, 3),
        em.InteractiveGoalRecoveryV1("present", "created", "goal-1", "active", 1, 1, 2, 1,
                                     orphaned_count=1, execution_unresolved=True),
    ):
        wire = json.loads(encode_response(em.ExecutionResponseV1("recovery", recovery)))
        add(f"recovery-{recovery.presence}-{recovery.reason_code}", "interactive_goal_recovery", wire)
    for index, (field, value) in enumerate((
        ("goalStatus", "running"), ("orphanedCount", -1), ("orphanedCount", 2),
        ("completedCount", 2**53), ("executionUnresolved", False), ("readOnly", False),
        ("reasonCode", "workspace private detail"), ("revision", 0), ("goalId", None), ("commandId", "old"),
    )):
        invalid = copy.deepcopy(wire)
        invalid["result"][field] = value
        add(f"recovery-invalid-{field}-{index}", "interactive_goal_recovery", invalid, False)
    goal = em.ExecutionGoalProgressV1(
        "execution-1", "present", "goal-1", "paused", "advance_budget_exhausted",
        "not_checked", True, 3, 6, 2,
        (
            em.ExecutionGoalBatchV1("batch-1", "completed", True, "not_requested", False),
            em.ExecutionGoalBatchV1("batch-2", None, False, None, True),
        ),
    )
    goal_wire = json.loads(encode_response(em.ExecutionResponseV1("goal-progress", goal)))
    add("goal-progress-paused", "goal_progress", goal_wire)
    for field, invalid in (
        ("status", "waiting_input"), ("goalId", None), ("validity", "current"),
        ("presence", "initializing"), ("reasonCode", "a file path /private"),
        ("batchCount", 2**53), ("modelCalls", -1), ("advances", True),
        ("goalPrivate", {}),
    ):
        value = copy.deepcopy(goal_wire)
        value["result"][field] = invalid
        add(f"goal-invalid-{field}", "goal_progress", value, False)
    empty = replace(goal, batch_count=0, batches=())
    add("goal-progress-empty", "goal_progress", json.loads(encode_response(em.ExecutionResponseV1("empty", empty))))
    limited = replace(goal, batch_count=19, batches=tuple(
        replace(goal.batches[0], batch_id=f"batch-{number}") for number in range(4, 20)
    ))
    add("goal-progress-limited", "goal_progress", json.loads(encode_response(em.ExecutionResponseV1("limited", limited))))
    for field, invalid in (
        ("batchId", "/private/batch"), ("workStatus", "invented"), ("recordingAvailable", 1),
        ("cancellationStatus", "cancelled"), ("observationUnavailable", "error"), ("planId", "private"),
    ):
        value = copy.deepcopy(goal_wire)
        value["result"]["batches"][0][field] = invalid
        add(f"batch-invalid-{field}", "goal_progress", value, False)
    for name in ("missing-state", "duplicate", "too-many", "truncated-too-early"):
        value = copy.deepcopy(goal_wire)
        result = value["result"]
        if name == "missing-state":
            del result["batches"][1]["cancellationStatus"]
        elif name == "duplicate":
            result["batches"][1]["batchId"] = result["batches"][0]["batchId"]
        elif name == "too-many":
            result["batchCount"] = 17
            result["batches"] = [dict(result["batches"][0], batchId=f"batch-{i}") for i in range(17)]
        else:
            result["batchCount"] = 17
        add(f"batch-{name}", "goal_progress", value, False)
    choice = pm.UserChoicePromptV1("question-1", "选择设计", (
        pm.UserChoiceOptionV1("a", "渐进", "复用 API"),
        pm.UserChoiceOptionV1("B", "重构"),
    ))
    chosen = replace(snapshot, source=replace(
        snapshot.source, source=replace(snapshot.source.source, user_choice=choice),
    ))
    wire = json.loads(encode_response(em.ExecutionResponseV1("snapshot", chosen)))
    add("pending-user-choice", "snapshot", wire)
    for error in ("null", "duplicate", "missing-description", "too-few", "too-many", "long-text", "bad-id", "extra-field"):
        value = copy.deepcopy(wire)
        source = value["result"]["source"]["source"]
        prompt = source["userChoice"]
        if error == "null":
            source["userChoice"] = None
        elif error == "duplicate":
            prompt["options"][1]["id"] = prompt["options"][0]["id"]
        elif error == "missing-description":
            del prompt["options"][0]["description"]
        elif error == "too-few":
            prompt["options"].pop()
        elif error == "too-many":
            prompt["options"] = [{"id": str(i), "label": "choice", "description": None} for i in range(6)]
        elif error == "long-text":
            prompt["question"] = "问" * 1025
        elif error == "bad-id":
            prompt["options"][0]["id"] = "a\n"
        elif error == "extra-field":
            prompt["approvalId"] = "unrelated"
        add(f"invalid-user-choice-{error}", "snapshot", value, False)
    for mode in ["execution", "legacy", None, "unknown", 1, {}]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"]["submissionMode"] = mode
        add(f"submission-mode-{mode}", "snapshot", value, mode == "execution")
    for count in [2**53 + 1, 2**100 + 1]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"].update(cursor=count, revision=count)
        add(f"snapshot-large-{count}", "snapshot", value)
    for count in [0, 2**53 - 1, 2**53, True, -1, 1.5]:
        value = copy.deepcopy(base)
        value["result"]["executions"]["revision"] = count
        add(
            f"metadata-revision-{count}",
            "snapshot",
            value,
            type(count) is int and 0 <= count <= 2**53 - 1,
        )
    for field, bad in [
        ("cursor", True),
        ("cursor", -1),
        ("revision", "1"),
        ("running", 1),
    ]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"][field] = bad
        add(f"source-{field}-{bad}", "snapshot", value, False)
    for size in [256, 257]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"]["records"] *= size
        add(f"snapshot-records-{size}", "snapshot", value, size <= 256)
    for size in [65_536, 65_537]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"]["records"][0]["text"] = "x" * size
        add(f"snapshot-text-{size}", "snapshot", value, size <= 65_536)
    for name in ["identity-mismatch", "draft-idle", "missing", "extra"]:
        value = copy.deepcopy(base)
        if name == "identity-mismatch":
            value["result"]["executions"]["identity"]["sessionId"] = "another"
        elif name == "draft-idle":
            value["result"]["source"]["draft"] = "unowned draft"
        elif name == "missing":
            del value["result"]["executions"]["active"]
        else:
            value["result"]["source"]["observation"]["unexpected"] = True
        add(name, "snapshot", value, False)

    def event_batch(kind=pm.SessionEventKindV1.ASSISTANT_DELTA, cursor=1):
        interaction = (
            "interaction"
            if kind
            in {
                pm.SessionEventKindV1.INTERACTION_REQUESTED,
                pm.SessionEventKindV1.INTERACTION_DISMISSED,
            }
            else None
        )
        event = em.ExecutionContentEventV1(
            pm.SessionEventV1("session", cursor, kind, "你好🙂", interaction),
            "execution",
        )
        return json.loads(
            encode_response(
                em.ExecutionResponseV1("events", em.ExecutionEventsV1((event,)))
            )
        )

    for kind in pm.SessionEventKindV1:
        add(f"content-{kind.value}", "events", event_batch(kind))
    nullable = event_batch()
    nullable["result"]["events"][0]["executionId"] = None
    nullable["result"]["events"][0]["source"]["text"] = None
    add("nullable-content", "events", nullable)
    for count in [2**53 + 1, 2**100 + 1]:
        add(f"event-large-{count}", "events", event_batch(cursor=count))
    for count in [0, True, -1, "1", 1.0]:
        value = event_batch()
        value["result"]["events"][0]["source"]["cursor"] = count
        add(f"event-invalid-cursor-{count}", "events", value, False)
    for size in [0, 256, 257]:
        value = event_batch()
        value["result"]["events"] *= size
        add(f"event-batch-{size}", "events", value, size <= 256)
    for name in [
        "interaction-missing",
        "interaction-unexpected",
        "unknown-kind",
        "missing-nullable",
        "extra",
    ]:
        value = event_batch(
            pm.SessionEventKindV1.INTERACTION_REQUESTED
            if name == "interaction-missing"
            else pm.SessionEventKindV1.STATUS
        )
        source = value["result"]["events"][0]["source"]
        if name == "interaction-missing":
            source["interactionId"] = None
        elif name == "interaction-unexpected":
            source["interactionId"] = "unexpected"
        elif name == "unknown-kind":
            source["kind"] = "unknown"
        elif name == "missing-nullable":
            del source["text"]
        else:
            source["unexpected"] = True
        add(name, "events", value, False)
    from state_vectors import append_state_vectors

    append_state_vectors(cases, base, event_batch())
    for name, kind, wire, valid in cases:
        try:
            expected = json.loads(encode_response(decode_response(wire.encode())))
            if kind == "snapshot":
                source = expected["result"]["source"]["source"]
                for field in ["cursor", "revision"]:
                    source[field] = str(source[field])
            elif kind == "events":
                for event in expected["result"]["events"]:
                    if "source" in event:
                        event["source"]["cursor"] = str(event["source"]["cursor"])
            accepted = True
        except InvalidAppMessageError:
            expected, accepted = None, False
        assert accepted == valid, f"Python projection contract changed: {name}"
        print(
            json.dumps(
                dict(name=name, kind=kind, wire=wire, valid=valid, expected=expected),
                ensure_ascii=False,
            )
        )
