from __future__ import annotations

from pathlib import Path


def test_coding_binds_product_vocabulary_to_shared_session_work_runtime() -> None:
    from loushang.coding.adapters.harnesswork import (
        CODING_WORK_PROFILE,
        create_coding_work_runtime,
    )
    from loushang.coding.domain import work as legacy_work
    from loushang.harnesswork.integrations.session import SessionWorkRuntime

    assert CODING_WORK_PROFILE.domain == "coding"
    assert CODING_WORK_PROFILE.operation_kind == "SubmitCodingTurn"
    assert (
        create_coding_work_runtime.__module__
        == "loushang.coding.adapters.harnesswork"
    )
    assert (
        SessionWorkRuntime.__module__
        == "loushang.harnesswork.integrations.session"
    )
    assert legacy_work.CODING_WORK_PROFILE is CODING_WORK_PROFILE
    assert legacy_work.create_coding_work_runtime is create_coding_work_runtime
    assert not Path("src/loushang/coding/work_shell.py").exists()
    assert not Path("src/loushang/work/coding.py").exists()
