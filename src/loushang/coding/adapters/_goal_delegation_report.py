"""One live/cold decoder for Product-owned delegated evidence, not a ledger."""

from __future__ import annotations

from types import SimpleNamespace

from loushang.harness.multiagent import AgentPath, AgentRef, ForkTier
from loushang.harness.transcript.writer_lease import TranscriptWriterError
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import plain
from loushang.harnesswork.plan_projection import project_work_plan_runs

from ._goal_delegation import KEY
from ._goal_execution_context import (
    MAPPER,
    OPERATION_KIND,
    ROLE,
    TOOLS,
    SessionChoice,
    build_context,
)
from ._work_evidence import project_work_evidence


def decode_selection(batch, run, entries):
    """Validate the private recording extension before reporting source absence."""
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
        return None
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
        or not isinstance(selected["mode"], str)
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
        or not isinstance(selected["model"]["value"], str)
        or not selected["model"]["value"]
        or not isinstance(selected["model"]["label"], str)
    ):
        raise GoalError("delegated context identity mismatch")
    history = selected["history"]
    if (
        not isinstance(history, dict)
        or set(history)
        != {
            "mapper",
            "source_session_id",
            "source_store_identity",
            "watermark",
            "requested_tier",
            "turns",
            "effective_tier",
            "allow_empty",
            "messages_sha256",
            "diagnostics",
        }
        or history["mapper"] != MAPPER
        or not isinstance(history["requested_tier"], str)
        or not isinstance(history["effective_tier"], str)
        or history["effective_tier"] not in {"none", "all", "last"}
        or not isinstance(history["messages_sha256"], str)
        or len(history["messages_sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in history["messages_sha256"])
        or not isinstance(history["diagnostics"], list)
        or any(not isinstance(d, str) for d in history["diagnostics"])
    ):
        raise GoalError("delegated history missing or unsupported")
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
        history.get("source_session_id") != run.session_id
        or not isinstance(history.get("source_store_identity"), str)
        or not history["source_store_identity"]
        or not isinstance(history.get("watermark"), str)
        or not history["watermark"]
    ):
        raise GoalError("inherited source identity mismatch")
    if history["effective_tier"] != choice.tier.mode and not (
        history["effective_tier"] == "none" and choice.allow_empty
    ):
        raise GoalError("inherited effective tier was not authorized")
    if choice.mode != "inherit" and any(
        history[key] is not None
        for key in ("source_session_id", "source_store_identity", "watermark")
    ):
        raise GoalError("fresh/reuse cannot declare inherited history")
    return selected, choice


def observe_delegation(policy, batch, run, previous):
    entries = policy.log.query(operation_id=batch.operation_id)
    decoded = decode_selection(batch, run, entries)
    if decoded is None:
        return False
    selected, choice = decoded
    history, reuse, target = selected["history"], selected["reuse"], choice.target
    if choice.mode == "inherit":
        if policy.source_reader is None:
            raise GoalError("inherited source reader unavailable")
        records = tuple(policy.session.session_manager.get_branch(history["watermark"]))
        try:
            observed = policy.source_reader.read_sync([r.record_id for r in records])
        except TranscriptWriterError as error:
            raise GoalError("inherited source authority unavailable") from error
        if (
            observed.store_identity != history["source_store_identity"]
            or tuple(r.record for r in observed.records) != records
        ):
            raise GoalError("inherited source identity or records changed")
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
    plans = project_work_plan_runs(entries)
    if (
        len(plans) != 1
        or plans[0].plan_id != run.plan_id
        or plans[0].method_id != run.method_id
        or plans[0].status != "completed"
        or len(plans[0].steps) != 1
    ):
        raise GoalError("delegated Method execution missing or ambiguous")
    step = plans[0].steps[0]
    if (
        step.step_id != "repair"
        or step.run_id != run.run_id
        or step.status != "completed"
        or run.current_step_id != "repair"
    ):
        raise GoalError("delegated Method step mismatch")
    for role in (ROLE, "repository_report"):
        refs = [r for r in project_work_evidence(entries) if r.role == role]
        if (
            len(refs) != 1
            or refs[0].run_id != run.run_id
            or refs[0].reported_step_id != "repair"
        ):
            raise GoalError("delegated evidence step missing or ambiguous")
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
