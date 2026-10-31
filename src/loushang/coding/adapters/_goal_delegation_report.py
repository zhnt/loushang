"""One live/cold decoder for Product-owned delegated evidence, not a ledger."""

from __future__ import annotations

from types import SimpleNamespace

from loushang.harness.multiagent import AgentPath, AgentRef, ForkTier
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import plain

from ._goal_delegation import KEY
from ._goal_execution_context import (
    OPERATION_KIND,
    ROLE,
    TOOLS,
    SessionChoice,
    build_context,
)


def observe_delegation(policy, batch, run, previous):
    entries = policy.log.query(operation_id=batch.operation_id)
    originals = [
        e for e in entries if e.entry_type == "operation" and e.run_id == run.run_id
    ]
    if len(originals) != 1:
        raise GoalError("original Work operation missing or ambiguous")
    operation = originals[0].payload
    selected = plain(batch.source.get(KEY))
    delegated = operation.get("kind") == OPERATION_KIND
    if not delegated:
        if selected is not None or KEY in operation.get("payload", {}):
            raise GoalError("delegated choice bound to another operation kind")
        return False
    if batch.source.get("phase") != "repair" or selected != plain(
        operation.get("payload", {}).get(KEY)
    ):
        raise GoalError("delegated choice differs from original operation")
    if (
        not isinstance(selected, dict)
        or set(selected)
        != {
            "version",
            "mode",
            "reason",
            "selection_revision",
            "basis",
            "operation_id",
            "method_id",
            "plan_id",
            "step_id",
            "model",
            "tools",
            "history",
            "reuse",
        }
        or type(selected["version"]) is not int
        or selected["version"] != 1
    ):
        raise GoalError("unsupported delegated context schema")
    if (
        selected["operation_id"] != batch.operation_id
        or selected["basis"] != plain(batch.source.get("basis"))
        or selected["method_id"] != run.method_id
        or selected["plan_id"] != run.plan_id
        or selected["step_id"] != "repair"
        or selected["tools"] != list(TOOLS)
        or type(selected["selection_revision"]) is not int
        or selected["selection_revision"] < 0
        or not isinstance(selected["model"], dict)
        or set(selected["model"]) != {"label", "value"}
        or not selected["model"]["value"]
    ):
        raise GoalError("delegated context identity mismatch")
    history = selected["history"]
    if not isinstance(history, dict):
        raise GoalError("delegated history missing")
    reuse = selected["reuse"]
    target = None
    if selected["mode"] == "reuse":
        if not isinstance(reuse, dict) or set(reuse) != {
            "ref",
            "session_id",
            "origin_operation_id",
            "prior_operation_id",
            "prior_round",
        }:
            raise GoalError("invalid reuse binding")
        target = _ref(reuse["ref"])
    elif reuse is not None:
        raise GoalError("new Session contains a reuse binding")
    choice = SessionChoice(
        selected["mode"],
        target=target,
        tier=ForkTier(history.get("requested_tier"), history.get("turns")),
        allow_empty=history.get("allow_empty"),
        reason=selected["reason"],
    )
    if choice.mode == "inherit" and (
        history.get("source_session_id") != policy.session.session_id
        or not isinstance(history.get("source_store_identity"), str)
        or not history["source_store_identity"]
        or not isinstance(history.get("watermark"), str)
        or not history["watermark"]
    ):
        raise GoalError("inherited source identity mismatch")
    # Same original projection/mapper at live use and detached reading. Child raw
    # Transcript is intentionally not a declared source.
    _, rebuilt = build_context(
        session=SimpleNamespace(
            session_id=policy.session.session_id,
            session_manager=policy.session.session_manager,
        ),
        blobs=policy.blobs,
        choice=choice,
        system_prompt="Validate history material only.",
        source_identity=history.get("source_store_identity"),
        watermark=history.get("watermark"),
    )
    if rebuilt != history:
        raise GoalError("inherited material no longer matches admitted history")
    if run.status != "completed":
        return True
    report = policy._report(batch, run, ROLE)
    if set(report) != {
        "version",
        "operation_id",
        "run_id",
        "session_id",
        "context",
        "child_ref",
        "child_session_id",
        "origin_operation_id",
        "round_id",
        "terminal",
    } or (
        report["context"] != selected
        or report["session_id"] != run.session_id
        or report["terminal"] != "completed"
        or type(report["round_id"]) is not int
        or not isinstance(report["child_session_id"], str)
        or not report["child_session_id"]
        or report["child_session_id"] == run.session_id
    ):
        raise GoalError("delegated report identity mismatch")
    ref = _ref(report["child_ref"])
    if choice.mode == "reuse":
        prior = previous.get(reuse["prior_operation_id"])
        if prior is None or (
            prior["child_ref"] != report["child_ref"]
            or ref != target
            or prior["child_session_id"] != report["child_session_id"]
            or report["child_session_id"] != reuse["session_id"]
            or prior["origin_operation_id"] != report["origin_operation_id"]
            or report["origin_operation_id"] != reuse["origin_operation_id"]
            or type(reuse["prior_round"]) is not int
            or prior["round_id"] != reuse["prior_round"]
            or report["round_id"] != prior["round_id"] + 1
            or any(
                p["child_ref"] == report["child_ref"]
                and p["round_id"] >= report["round_id"]
                for p in previous.values()
            )
        ):
            raise GoalError("reused child origin or round mismatch")
    elif (
        report["origin_operation_id"] != batch.operation_id
        or report["round_id"] != 1
        or any(
            p["child_ref"] == report["child_ref"]
            or p["child_session_id"] == report["child_session_id"]
            for p in previous.values()
        )
    ):
        raise GoalError("new child identity reused")
    previous[batch.operation_id] = report
    return True


def _ref(value):
    if not isinstance(value, dict) or set(value) != {"path", "incarnation"}:
        raise GoalError("invalid exact child reference")
    ref = AgentRef(AgentPath.parse(value["path"]), value["incarnation"])
    if ref.path == AgentPath.root():
        raise GoalError("parent cannot be a delegated child")
    return ref
