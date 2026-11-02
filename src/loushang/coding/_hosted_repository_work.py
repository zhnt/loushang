"""Repository-specific command selection inside the original guarded invocation."""

from __future__ import annotations

import json
from types import MappingProxyType

from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1
from loushang.harnesswork.goal.records import canonical

from .adapters._goal_repository_review import review_value


def _frozen(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _frozen(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_frozen(v) for v in value)
    return value


def review_material(owner, goal_id):
    identity, passed = owner.review_basis(goal_id)
    if not passed:
        raise ValueError("current full verification required")
    task = owner._profile.task
    candidate = task.read_files(task.allowed, identity["inventory"])
    initial = dict(task.initial)
    from .adapters._goal_repository_task import digest

    if any(
        digest(v.encode()) != task.config["workspace_start"][n]
        for n, v in initial.items()
    ):
        raise ValueError("initial material changed")
    batch = next(
        b
        for b in owner.controller.history.batches
        if b.operation_id == identity["verification_operation_id"]
    )
    run = owner._work.get_run_for_operation(batch.operation_id)
    if run is None or run.run_id != identity["verification_run_id"]:
        raise ValueError("verification identity unavailable")
    # This is the original identity-bound Blob/Work reader, not unbound stdout.
    verification = owner._policy._verification(batch, run)
    material = dict(
        identity=identity,
        requirements=task.config["requirements"],
        initial=initial,
        candidate=candidate,
        verification=verification,
    )
    encoded = canonical(material).encode()
    if len(encoded) > 4 * 1024 * 1024:
        raise ValueError("review material exceeds limit")
    return json.loads(canonical(identity)), _frozen(json.loads(encoded))


async def drive_repository(invocation):
    owner, setup = invocation.owner, invocation.setup
    goal_id, task = setup.goal_id, setup.repository.task

    def fail(reason):
        invocation.reason = reason
        return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, reason)

    async def command(name, **fields):
        invocation.checkpoint()
        if invocation.advances >= setup.config.max_advances:
            raise ValueError("command budget exhausted")
        invocation.advances += 1
        result = await getattr(owner, name)(goal_id, **fields)
        invocation.checkpoint()
        return result

    while invocation.advances < setup.config.max_advances:
        invocation.checkpoint()
        if owner.controller.fenced or not invocation._recording_available():
            return fail("work_recording_unavailable")
        try:
            task.snapshot()
        except Exception:
            return fail("task_changed")
        view = await owner.query(goal_id)
        invocation.checkpoint()
        if view.goal.status == "completed":
            if (
                view.validity == "current"
                and not view.execution_unresolved
                and invocation._recording_available()
            ):
                invocation.reason = "goal_completed"
                return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
            return fail("goal_evidence_unavailable")
        if view.goal.status != "active" or setup.allowance.fenced:
            return fail("goal_stopped")
        batches = owner.controller.history.batches
        last = batches[-1] if batches else None
        phase = last.source.get("phase") if last is not None else None
        run = (
            owner._work.get_run_for_operation(last.operation_id)
            if last is not None
            else None
        )
        state = view.goal
        if phase == "review":
            return fail(
                "review_rejected"
                if view.reason == "review_rejected"
                else "goal_evidence_unavailable"
            )
        if phase == "verification":
            if invocation.advances + 1 > setup.config.max_advances:
                return fail("advance_budget_exhausted")
            if view.reason != "review_required":
                return fail("verification_failed")
            try:
                identity, material = review_material(owner, goal_id)
            except Exception:
                return fail("goal_evidence_unavailable")
            invocation.checkpoint()
            if not invocation._recording_available():
                return fail("work_recording_unavailable")
            invocation.reason = "awaiting_review"
            try:
                response = await setup.config.reviewer(material)
            except Exception:
                return fail("review_unavailable")
            invocation.checkpoint()
            try:
                if (
                    not isinstance(response, dict)
                    or not {"decision", "reason", "coverage", "findings"}
                    <= set(response)
                    or set(response)
                    - {"decision", "reason", "coverage", "findings", "reviewer"}
                ):
                    raise ValueError("invalid reviewer response")
                if (
                    response.get("reviewer", setup.config.reviewer_id)
                    != setup.config.reviewer_id
                ):
                    raise ValueError("reviewer identity mismatch")
                value = review_value(
                    command_id=f"{invocation.execution_id}:review",
                    review_id=f"{invocation.execution_id}:review",
                    identity=identity,
                    reviewer=setup.config.reviewer_id,
                    **{
                        k: response[k]
                        for k in ("decision", "reason", "coverage", "findings")
                    },
                )
            except Exception:
                return fail("review_unavailable")
            try:
                current, passed = owner.review_basis(goal_id)
                if current != identity or not passed:
                    return fail("task_changed")
            except Exception:
                return fail("task_changed")
            invocation.checkpoint()
            if not invocation._recording_available():
                return fail("work_recording_unavailable")
            invocation.reason = "recording_review"
            await command(
                "submit_review",
                expected_identity=value.pop("identity"),
                **{k: v for k, v in value.items() if k != "version"},
            )
        elif phase == "repair":
            if run is None or run.status != "completed":
                return fail("repair_failed")
            if invocation.advances + 2 > setup.config.max_advances:
                return fail("advance_budget_exhausted")
            invocation.reason = "verifying"
            await command(
                "verify_current",
                command_id=f"{invocation.execution_id}:verify",
                revision=state.revision,
                epoch=state.epoch,
                expected_inventory=task.snapshot(),
            )
        else:
            if run is not None and run.status != "completed":
                return fail("goal_stopped")
            invocation.reason = "planning"
            await command(
                "advance",
                command_id=f"{invocation.execution_id}:advance:{invocation.advances}",
                revision=state.revision,
                epoch=state.epoch,
            )
        # Final original command may be the sixth. Observe it without a seventh.
        invocation.checkpoint()
        if owner.controller.fenced or not invocation._recording_available():
            return fail("work_recording_unavailable")
        view = await owner.query(goal_id)
        invocation.checkpoint()
        if (
            view.goal.status == "completed"
            and view.validity == "current"
            and not view.execution_unresolved
        ):
            if not invocation._recording_available():
                return fail("work_recording_unavailable")
            invocation.reason = "goal_completed"
            return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
        if view.reason == "review_rejected":
            return fail("review_rejected")
    return fail("advance_budget_exhausted")
