"""Compare next decisions and input bytes with the independently frozen selector."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from loushang.coding.adapters._goal_planning_shared import BatchPlanningPolicy

from .goal_batch_contract import CASES, capture_cases


def test_batch_selector_keeps_parent_decisions_trace_and_next_input_bytes():
    directory = Path(__file__).parent / "fixtures/goal_batch_planning_v1"
    manifest = json.loads((directory / "manifest.json").read_text())
    raw = (directory / "expected.json").read_bytes()
    assert manifest["baseline_commit"] == "3cffb41999fc7b972a106e951f30d2352a98f727"
    assert manifest["source_sha256"] == "2023aa48f4cf4b590d2b530bda7b85f44d26c4ef036ae3a9f84fc903cb0cb162"
    assert manifest["expected_sha256"] == hashlib.sha256(raw).hexdigest()
    assert manifest["cases"] == list(CASES)
    assert capture_cases(BatchPlanningPolicy) == json.loads(raw)


def test_original_profiles_use_one_shared_selector_and_confirmation_algorithm():
    from loushang.coding.adapters._goal_planning import ModelPlanningPolicy
    from loushang.coding.adapters._goal_repository import (
        RepositoryDomain,
        RepositoryPolicy,
    )
    from loushang.harnesswork.goal.batch_planning import (
        BatchPlanningPolicy as SharedPolicy,
    )

    assert ModelPlanningPolicy.prepare is SharedPolicy.prepare
    assert ModelPlanningPolicy.confirm_candidate is SharedPolicy.confirm_candidate
    assert RepositoryPolicy.confirm_candidate is SharedPolicy.confirm_candidate
    assert RepositoryPolicy.trace is ModelPlanningPolicy.trace is SharedPolicy.trace
    # Repository's existing host-verification/review priority still precedes
    # the shared selector; its existing domain still supplies the parent check.
    assert RepositoryPolicy.__mro__.index(SharedPolicy) < RepositoryPolicy.__mro__.index(RepositoryDomain)
