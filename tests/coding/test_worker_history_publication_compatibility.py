"""Original Rooted publication/retirement commands, including lost acknowledgements."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_history_commit_v2 import (
    commit_coding_worker_v2_owner_under_guard,
)
from loushang.coding.package_product_worker_history_retire_v2 import (
    retire_coding_worker_v2_history_under_guard,
)
from loushang.coding.package_product_worker_history_segments import _head_name
from loushang.coding.package_product_worker_history_stage_v2 import (
    rollback_coding_worker_v2_preparation,
    stage_coding_worker_v2_preparation,
)
from loushang.coding.package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
    PREPARED_INDEX_NAME,
    PRODUCT_OWNER_INDEX_NAME,
    semantic_base_name,
)
from loushang.harness.journal._rooted_io import RootedFile
from tests.coding.test_package_product_worker_history_commit_v2 import _locks
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _prepared, _rooted

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux Rooted Worker history"
)
CASES = (
    "stage-retry",
    "stage-paused",
    "rollback-empty",
    "rollback-changed",
    "commit-missing-lock",
    "commit-lost-ack",
    "retire-paused",
    "retire-bad-ledger",
)


def observe_publication(case, root, patch):
    prepared = _prepared()
    if case.startswith("commit-") or case.startswith("retire-"):
        with _rooted(root) as rooted:
            prepared = _write_sources(rooted)
            if case != "commit-missing-lock":
                _locks(rooted)
            if case.startswith("retire-"):
                commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)
                if case == "retire-bad-ledger":
                    rooted.sibling(DELETION_LEDGER_NAME).create_new(b"{}")
    elif case == "rollback-changed":
        with _rooted(root) as rooted:
            stage_coding_worker_v2_preparation(rooted, prepared=prepared)
            rooted.sibling(semantic_base_name("worker-opt-in")).atomic_write(b"changed")
    trace = []
    paused = False
    original_create = RootedFile.create_new
    original_unlink = RootedFile.unlink_owned
    original_lock = RootedFile.acquire_lock

    def create(self, data):
        nonlocal paused
        trace.append(["create", self._name, hashlib.sha256(data).hexdigest()])
        if case == "stage-paused" and self._name == PREPARED_INDEX_NAME and not paused:
            paused = True
            raise OSError("pause before artifact")
        result = original_create(self, data)
        if (
            case == "commit-lost-ack"
            and self._name == PRODUCT_OWNER_INDEX_NAME
            and not paused
        ):
            paused = True
            raise OSError("owner persisted but acknowledgement lost")
        return result

    def unlink(self, identity):
        nonlocal paused
        trace.append(["unlink", self._name])
        if (
            case == "retire-paused"
            and self._name == _head_name("worker-opt-in", 0)
            and not paused
        ):
            paused = True
            raise OSError("pause after first retired segment")
        return original_unlink(self, identity)

    def lock(self, **kwargs):
        trace.append(["lock", self._name, kwargs])
        return original_lock(self, **kwargs)

    patch.setattr(RootedFile, "create_new", create)
    patch.setattr(RootedFile, "unlink_owned", unlink)
    patch.setattr(RootedFile, "acquire_lock", lock)
    outcomes = []
    count = (
        2
        if case in {"stage-retry", "stage-paused", "commit-lost-ack", "retire-paused"}
        else 1
    )
    for _ in range(count):
        value = None
        error = None
        try:
            with _rooted(root) as rooted:
                if case.startswith("stage-"):
                    result = stage_coding_worker_v2_preparation(
                        rooted, prepared=prepared
                    )
                elif case.startswith("rollback-"):
                    result = rollback_coding_worker_v2_preparation(rooted)
                elif case.startswith("commit-"):
                    result = commit_coding_worker_v2_owner_under_guard(
                        rooted, prepared=prepared
                    )
                else:
                    result = retire_coding_worker_v2_history_under_guard(rooted)
            value = (
                result
                if isinstance(result, bool)
                else dict(
                    type=type(result).__module__ + "." + type(result).__name__,
                    digest=hashlib.sha256(result.to_bytes()).hexdigest(),
                )
            )
        except Exception as exc:
            error = []
            while exc is not None:
                error.append(
                    [
                        type(exc).__name__,
                        str(exc).replace(str(root), "<root>"),
                        getattr(exc, "code", None),
                        exc.__suppress_context__,
                    ]
                )
                exc = exc.__cause__
        outcomes.append(
            dict(
                value=value,
                error=error,
                files={
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(root.iterdir())
                    if p.is_file()
                },
            )
        )
    if case in {"stage-paused", "commit-lost-ack", "retire-paused"}:
        assert paused, "the named interruption must have actually fired"
    return dict(trace=trace, outcomes=outcomes)


@pytest.mark.parametrize("case", CASES)
def test_original_publication_commands(case, tmp_path, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/worker_publication_v2.json").read_text()
    )
    assert observe_publication(case, tmp_path, monkeypatch) == expected[case]
