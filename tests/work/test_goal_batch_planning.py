"""The shared selector accepts a non-Coding domain and opaque input context."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from loushang.harnesswork.goal import GoalBasis, GoalFacts, WorkCandidate
from loushang.harnesswork.goal.batch_planning import BatchPlanningPolicy
from loushang.harnesswork.goal.records import (
    GoalBatch,
    GoalHeader,
    GoalState,
    Requirement,
)
from loushang.harnesswork.types import WorkOperation, WorkRunSpec


def test_shared_selector_passes_opaque_domain_context_without_coding_inputs():
    async def scenario():
        context = object()
        fingerprint = {"sources": "original-revision"}
        goal = GoalState("research", (Requirement("R1", "Summarize the supplied sources"),), 4, {})
        basis = GoalBasis(GoalHeader("session", "session", "research/v1"), goal, 2)
        batch = GoalBatch("plan", "research", "plan-op", 1, 1, 1, "plan", {
            "phase": "planning", "inventory": fingerprint, "basis": basis.identity,
        })
        run = SimpleNamespace(operation_id="plan-op", run_id="plan-run", session_id="session", status="completed")
        proposal = SimpleNamespace(action=SimpleNamespace(data=lambda: {"name": "summarize-sources"}))

        class Domain:
            def confirm_candidate(self, candidate):
                return True

        class RejectedAction(ValueError):
            pass

        class Policy(BatchPlanningPolicy, Domain):
            rejection_error = RejectedAction
            limits = {"invalid_proposals": 2, "no_progress": 2, "planning_intents": 3}
            prepared = {"old-unaccepted-binding": object()}

            def planning_input_pending(self):
                return False

            def planning_context(self, current):
                return fingerprint, context

            def planning_session_id(self):
                return "session"

            def _observations(self, current, facts):
                return [], [], [], 1, 0, 0

            def _proposal(self, previous, original_run):
                assert previous is batch and original_run is run
                return proposal

            def _implementation(self, *args):
                raise AssertionError("shared selector must not require a Coding implementation hook")

            def bind_planned_action(self, current, proposed, snapshot, original_context, evidence):
                assert original_context is context and snapshot is fingerprint and proposed is proposal
                return WorkCandidate(current, WorkOperation("summary-op", "SummarizeSources", "session", "research", {}),
                                     WorkRunSpec(), {"phase": "summary"})

            def _planning(self, *args):
                raise AssertionError("existing proposal must be selected without another planning batch")

        policy = Policy()
        result = await policy.prepare(basis, GoalFacts((batch,), (run,)))
        assert isinstance(result, WorkCandidate)
        assert result.operation.domain == "research" and result.source["proposal_id"] == "plan-op"
        assert not policy.prepared

    asyncio.run(scenario())
