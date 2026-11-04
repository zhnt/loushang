"""Deterministic domain ports for comparing the old batch selector with its extraction.

No provider, filesystem execution, or source verifier is replaced by a new
selector here. Golden outputs are generated separately by the parent algorithm.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import sys
from types import SimpleNamespace

from loushang.coding.adapters._goal_proposal import ProposalRejected
from loushang.harness.artifacts import SessionBlobRef
from loushang.harnesswork.goal import (
    GoalBasis,
    GoalError,
    GoalFacts,
    PolicyStop,
    WorkCandidate,
)
from loushang.harnesswork.goal.records import (
    GoalBatch,
    GoalHeader,
    GoalState,
    Requirement,
    plain,
)
from loushang.harnesswork.types import WorkOperation, WorkRunSpec, WorkStepSpec

CASES = (
    "initial", "initial_budget", "pending_input", "proposal", "semantic_rejection",
    "report_rejection", "source_failure", "no_progress", "intent_limit",
    "parent_refuses", "own_intent", "consumed_not_submitted",
)


class _Blobs:
    def __init__(self):
        self.data, self.inputs = {}, {}

    def put_bytes(self, data, **metadata):
        digest = hashlib.sha256(data).hexdigest()
        self.data[digest] = data
        self.inputs[metadata["logical_name"]] = data.decode()
        return SessionBlobRef(session_id="batch-session", blob_id=digest, sha256=digest,
                              size_bytes=len(data), disclosure="private", created_at=0, **metadata)

    def read_bytes(self, reference):
        return self.data[reference.sha256]


class _Budget:
    def model_budget(self):
        return {"hosted_budget": {"max_advances": 3, "advances_including_current_command": 1,
                                  "model_calls_remaining_including_next_call": 2}}

    def model_limits(self, limits):
        return {**limits, "provider_attempts": 1}


def _candidate(value):
    if isinstance(value, PolicyStop):
        return {"stop": value.reason}
    operation, spec = value.operation, value.spec
    return {
        "basis": plain(value.basis.identity), "source": plain(value.source),
        "operation": {"id": operation.operation_id, "kind": operation.kind,
                      "session_id": operation.session_id, "domain": operation.domain,
                      "payload": plain(operation.payload), "source": plain(operation.source)},
        "spec": {"run_id": spec.run_id, "method_id": spec.method_id,
                 "plan_id": spec.plan_id, "step_id": spec.step_id,
                 "run_event_payload": plain(spec.run_event_payload),
                 "scope_event_payload": plain(spec.scope_event_payload),
                 "recording_policy": None if spec.recording_policy is None else spec.recording_policy.require_persistence,
                 "steps": [{"id": step.step_id, "payload": plain(step.payload)} for step in spec.steps]},
    }


async def _capture(base, scenario):
    header = GoalHeader("batch-session", "batch-session", "coding-calculator-model-planning/v1")
    goal = GoalState("g", (Requirement("R1", "Preserve the frozen requirement"),), 6, {})
    inventory = {"source.py": "a" * 64}
    source, tests, code = bytearray(b"domain source"), bytearray(b"domain tests"), object()
    parent_basis = GoalBasis(header, goal, 1)
    has_proposal = scenario not in {"initial", "initial_budget", "pending_input", "no_progress", "intent_limit"}
    batches = [GoalBatch("proposal-batch", "g", "proposal-op", 1, 1, 2, "plan", {
        "phase": "planning", "inventory": inventory, "basis": parent_basis.identity,
        "input_ref": {"reference": "original-input"},
    }, run_receipt="proposal-run")] if has_proposal else []
    runs = [SimpleNamespace(operation_id="proposal-op", run_id="proposal-run",
                            session_id="batch-session", status="completed")] if has_proposal else []
    sequence = 5 if batches else 1
    history = SimpleNamespace(sequence=sequence, batches=tuple(batches),
                              records=[SimpleNamespace(data={}) for _ in range(sequence)],
                              goal=lambda goal_id: goal)
    basis = GoalBasis(header, goal, sequence)

    class Domain:
        def _current_inputs(self, current):
            self.samples += 1
            return dict(inventory), source, tests, code

        def _observations(self, current, facts):
            routes = [{"proposal_id": "proposal-op", "route": [{"id": "r1", "text": "do the work"}]}] if has_proposal else []
            return ([{"id": "e1", "result": "known"}], copy.deepcopy(routes), [],
                    self.limits["planning_intents"] if scenario == "intent_limit" else int(has_proposal),
                    0, self.limits["no_progress"] if scenario == "no_progress" else 0)

        def _implementation(self, current, proposal, snapshot, actual_source, actual_tests, actual_code, evidence):
            assert actual_source is source and actual_tests is tests and actual_code is code
            if scenario == "semantic_rejection":
                raise ProposalRejected("domain action rejected")
            return WorkCandidate(current, WorkOperation("action-op", "DomainAction", "batch-session", "test", {}),
                                 WorkRunSpec(plan_id="action-plan", steps=(WorkStepSpec("act"),)),
                                 {"phase": "repair", "inventory": snapshot})

        def confirm_candidate(self, candidate):
            self.parent_checks += 1
            return scenario != "parent_refuses"

        def _bind_source(self, operation, spec, executor):
            return operation, executor

    class Policy(base, Domain):
        def planning_material(self, snapshot):
            return {"task": "domain-owned material"}

    policy = Policy()
    policy.samples = policy.parent_checks = 0
    policy.session = SimpleNamespace(session_id="batch-session", pending_message_count=int(scenario == "pending_input"))
    policy.execution_session, policy.execution = policy.session, None
    policy.blobs, policy.prepared = _Blobs(), {"unaccepted-binding": object()}
    policy.tool_policy, policy.allowance = object(), _Budget() if scenario == "initial_budget" else None
    policy.limits = copy.deepcopy(dict(base.limits))
    policy.history = lambda: history
    policy.log = SimpleNamespace(query=lambda **kwargs: [])
    proposal = SimpleNamespace(action=SimpleNamespace(data=lambda: {"name": "domain-action"}),
                               data=lambda: {"action": "domain-action", "route": "r1"})

    def original_proposal(batch, run):
        if scenario == "report_rejection":
            raise ProposalRejected("original report rejected")
        if scenario == "source_failure":
            raise GoalError("original planning response evidence unavailable or inconsistent")
        return proposal

    def original_report(batch, run, role):
        if scenario == "source_failure":
            raise GoalError("original planning response evidence unavailable or inconsistent")
        return {"response_ref": {"reference": "response"}, "response_proof": {"proof": "original"}}

    policy._proposal, policy._report = original_proposal, original_report
    planning_module = sys.modules[base._planning.__module__]
    confirm_module = sys.modules[base.confirm_candidate.__module__]
    old_uuid, old_projection = planning_module.uuid4, confirm_module.project_work_runs
    planning_module.uuid4 = lambda: SimpleNamespace(hex="d" * 32)
    confirm_module.project_work_runs = lambda entries: runs
    try:
        facts = GoalFacts(tuple(batches), tuple(runs))
        candidate = await policy.prepare(basis, facts)
        first = policy.confirm_candidate(candidate) if isinstance(candidate, WorkCandidate) else None
        if scenario in {"own_intent", "consumed_not_submitted"}:
            own = scenario == "own_intent"
            extra = GoalBatch("intent", "g", candidate.operation.operation_id if own else "other-action", 1, 1,
                              sequence + 1, "act", candidate.source if own else {"proposal_id": "proposal-op"},
                              not_submitted=not own)
            history.batches = (*history.batches, extra)
            history.sequence += 1
            history.records.append(SimpleNamespace(data={"basis": basis.identity}))
        second = policy.confirm_candidate(candidate) if isinstance(candidate, WorkCandidate) else None
        trace = policy.trace(basis, GoalFacts(history.batches, tuple(runs)))
        return {"candidate": _candidate(candidate), "confirm": [first, second], "trace": plain(trace),
                "prepared_keys": sorted(policy.prepared), "next_inputs": policy.blobs.inputs,
                "input_samples": policy.samples, "parent_checks": policy.parent_checks}
    finally:
        planning_module.uuid4, confirm_module.project_work_runs = old_uuid, old_projection


def capture_cases(base):
    async def run():
        return {name: await _capture(base, name) for name in CASES}

    return asyncio.run(run())
