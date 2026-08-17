from __future__ import annotations

import loushang.foundation.observability as observability


def test_observability_root_exposes_only_the_stable_daily_surface() -> None:
    assert set(observability.__all__) == {
        "LogContext",
        "ObservabilityLog",
        "ProblemRecord",
        "ProblemSeverity",
        "get_log",
        "log_context",
    }


def test_observability_root_symbols_have_canonical_owners() -> None:
    assert observability.LogContext.__module__ == (
        "loushang.foundation.observability.context"
    )
    assert observability.ObservabilityLog.__module__ == (
        "loushang.foundation.observability.logger"
    )
    assert observability.ProblemRecord.__module__ == (
        "loushang.foundation.observability.records"
    )
