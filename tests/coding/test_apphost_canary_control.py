from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

import pytest

from loushang.coding._apphost_canary_control import (
    CodingAppHostCanaryControlError,
    CodingAppHostCanaryControlJournal,
    default_coding_apphost_canary_control_path,
)
from loushang.foundation.platform_paths import PlatformPaths


def _operation(value: int) -> str:
    return f"{value:032x}"


def test_control_is_fail_closed_until_explicitly_enabled(tmp_path: Path) -> None:
    path = tmp_path / "control.jsonl"
    control = CodingAppHostCanaryControlJournal(path)

    snapshot = control.snapshot()
    assert snapshot.state == "unconfigured"
    assert snapshot.selection_generation == 0
    assert not path.exists()

    with pytest.raises(CodingAppHostCanaryControlError) as disabled:
        with control.admitted_run():
            raise AssertionError("unconfigured canary must not be admitted")
    assert disabled.value.code == "coding_apphost_canary_disabled"

    enabled = control.enable(operation_id=_operation(1))
    assert enabled.state == "enabled"
    assert enabled.selection_generation == 1
    with control.admitted_run() as admitted:
        assert admitted == enabled


def test_control_transitions_are_monotonic_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "control.jsonl"
    control = CodingAppHostCanaryControlJournal(path)

    first = control.rollback(operation_id=_operation(1))
    repeated = control.rollback(operation_id=_operation(2))
    enabled = control.enable(operation_id=_operation(3))
    enabled_repeated = control.enable(operation_id=_operation(4))
    disabled = control.rollback(operation_id=_operation(5))

    assert (first.state, first.selection_generation) == ("disabled", 1)
    assert repeated == first
    assert (enabled.state, enabled.selection_generation) == ("enabled", 2)
    assert enabled_repeated == enabled
    assert (disabled.state, disabled.selection_generation) == ("disabled", 3)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_control_rejects_partial_or_non_monotonic_history(tmp_path: Path) -> None:
    path = tmp_path / "control.jsonl"
    control = CodingAppHostCanaryControlJournal(path)
    control.enable(operation_id=_operation(1))
    with path.open("ab") as handle:
        handle.write(b'{"operation":"rollback"')

    with pytest.raises(CodingAppHostCanaryControlError) as corrupt:
        control.snapshot()
    assert corrupt.value.code == "coding_apphost_canary_control_corrupt"

    path.write_text(
        '{"operation":"enable","operationId":"00000000000000000000000000000001",'
        '"recordRevision":2,"recordVersion":1,"selectionGeneration":2,'
        '"state":"enabled"}\n',
        encoding="utf-8",
    )
    path.chmod(0o600)
    with pytest.raises(CodingAppHostCanaryControlError) as non_monotonic:
        control.snapshot()
    assert non_monotonic.value.code == "coding_apphost_canary_control_corrupt"


@pytest.mark.parametrize(
    "_case",
    ("G10-RUN-ROLLBACK-LINEARIZATION",),
    ids=("G10-RUN-ROLLBACK-LINEARIZATION",),
)
def test_run_and_rollback_linearize_on_one_cross_process_lock(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case
    control = CodingAppHostCanaryControlJournal(tmp_path / "control.jsonl")
    control.enable(operation_id=_operation(1))
    entered = threading.Event()
    release = threading.Event()
    rolled_back = threading.Event()

    def run_owner() -> None:
        with control.admitted_run():
            entered.set()
            assert release.wait(2.0)

    def rollback_owner() -> None:
        control.rollback(operation_id=_operation(2))
        rolled_back.set()

    run_thread = threading.Thread(target=run_owner)
    rollback_thread = threading.Thread(target=rollback_owner)
    run_thread.start()
    assert entered.wait(2.0)
    rollback_thread.start()
    assert not rolled_back.wait(0.05)
    release.set()
    run_thread.join(2.0)
    rollback_thread.join(2.0)

    assert not run_thread.is_alive()
    assert not rollback_thread.is_alive()
    assert rolled_back.is_set()
    assert control.snapshot().state == "disabled"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_control_rejects_public_or_aliased_storage(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(CodingAppHostCanaryControlError) as unsafe:
        CodingAppHostCanaryControlJournal(public / "control.jsonl").enable(
            operation_id=_operation(1)
        )
    assert unsafe.value.code == "coding_apphost_canary_control_storage_unsafe"

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    control = CodingAppHostCanaryControlJournal(private / "control.jsonl")
    control.enable(operation_id=_operation(2))
    alias = private / "alias.jsonl"
    os.link(control.path, alias)
    with pytest.raises(CodingAppHostCanaryControlError) as aliased:
        control.snapshot()
    assert aliased.value.code == "coding_apphost_canary_control_storage_unsafe"


def test_default_control_path_is_product_owned_machine_state(tmp_path: Path) -> None:
    paths = PlatformPaths(
        home=tmp_path / "home",
        data=tmp_path / "data",
        state=tmp_path / "state",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "temporary",
    )
    assert default_coding_apphost_canary_control_path(platform_paths=paths) == (
        paths.state / "products" / "coding" / "apphost-explicit-canary-control.jsonl"
    )


def test_async_control_wait_is_bounded_without_blocking_the_event_loop(
    tmp_path: Path,
) -> None:
    control = CodingAppHostCanaryControlJournal(tmp_path / "control.jsonl")
    control.enable(operation_id=_operation(1))

    async def scenario() -> None:
        with control.admitted_run():
            with pytest.raises(CodingAppHostCanaryControlError) as busy:
                await control.rollback_async(
                    operation_id=_operation(2),
                    timeout_seconds=0.02,
                )
            assert busy.value.code == "coding_apphost_canary_control_busy"

    asyncio.run(scenario())
