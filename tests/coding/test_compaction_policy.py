from __future__ import annotations


def test_compaction_budget_uses_more_conservative_percent_threshold() -> None:
    from loushang.coding.control import CompactionSettings
    from loushang.harness.context.budget import calculate_compaction_budget

    budget = calculate_compaction_budget(
        context_window=128_000,
        settings=CompactionSettings(compact_percent=80, reserve_tokens=8_192),
    )

    assert budget.percent_threshold_tokens == 102_400
    assert budget.reserve_threshold_tokens == 119_808
    assert budget.threshold_tokens == 102_400
    assert budget.threshold_reason == "compact_percent"


def test_compaction_budget_uses_more_conservative_reserve_threshold() -> None:
    from loushang.coding.control import CompactionSettings
    from loushang.harness.context.budget import calculate_compaction_budget

    budget = calculate_compaction_budget(
        context_window=32_000,
        settings=CompactionSettings(compact_percent=80, reserve_tokens=16_384),
    )

    assert budget.percent_threshold_tokens == 25_600
    assert budget.reserve_threshold_tokens == 15_616
    assert budget.threshold_tokens == 15_616
    assert budget.threshold_reason == "reserve_tokens"
