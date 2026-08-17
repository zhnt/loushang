from __future__ import annotations


def test_coding_context_budget_facades_are_removed() -> None:
    import importlib.util

    import loushang.coding as coding
    import loushang.coding.compaction as compaction
    from loushang.harness.context import budget, usage

    assert importlib.util.find_spec("loushang.coding.compaction.policy") is None
    assert not hasattr(coding, "ContextUsageEstimate")
    assert not hasattr(compaction, "calculate_compaction_budget")
    assert budget.CompactionBudget.__module__ == "loushang.harness.context.budget"
    assert (
        budget.calculate_compaction_budget.__module__
        == "loushang.harness.context.budget"
    )
    assert usage.ContextUsageEstimate.__module__ == "loushang.harness.context.usage"


def test_agent_transcript_context_estimator_returns_harness_record() -> None:
    from loushang.ai.types import UserMessage
    from loushang.harness.context.usage import ContextUsageEstimate
    from loushang.harness.transcript import estimate_context_tokens

    estimate = estimate_context_tokens(
        [UserMessage(role="user", content="follow up", timestamp=1.0)]
    )

    assert isinstance(estimate, ContextUsageEstimate)
    assert estimate.usage_tokens == 0
    assert estimate.trailing_tokens == estimate.tokens
    assert estimate.last_usage_index is None
