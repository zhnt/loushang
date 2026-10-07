"""Product-owned five-stream seal makes low-volume Worker history cutover-ready."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_history_rotate_v2 import (
    CodingWorkerV2SealError,
    seal_coding_product_worker_v1_history_for_v2,
)
from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    _head_bytes,
    commit_coding_worker_active_segment,
    read_coding_worker_segmented_history,
    seal_coding_worker_active_segment,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from loushang.coding.package_product_worker_history_v2_names import (
    PREPARATION_INTENT_NAME,
    PREPARED_INDEX_NAME,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.journal._rooted_io import RootedFile
from tests.coding.test_package_product_worker_history_commit_v2 import _product
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product Worker history")


def _sources(root: Path, *, empty_stem: str | None = None) -> None:
    with _rooted(root) as rooted:
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
            raw = b"" if stem == empty_stem else b'{"journalRevision":1}\n'
            rooted.sibling(stem + ".jsonl.lock").create_new(b"")
            rooted.sibling(stem + ".jsonl").create_new(raw)
            rooted.sibling(stem + ".head.json").create_new(_head_bytes(stem, 0, raw))


def _generations(root: Path) -> tuple[int, ...]:
    with _rooted(root) as rooted:
        return tuple(
            read_coding_worker_segmented_history(
                rooted,
                stem=stem,
                stream_id=stem,
                max_segment_bytes=32 * 1024 * 1024,
            ).active_generation
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS
        )


def test_product_seals_five_low_volume_streams_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path)
    calls: list[str] = []
    product = _product(tmp_path, monkeypatch, calls)
    assert seal_coding_product_worker_v1_history_for_v2(product) == (1,) * 5
    assert _generations(tmp_path) == (1,) * 5
    assert seal_coding_product_worker_v1_history_for_v2(product) == (1,) * 5
    assert _generations(tmp_path) == (1,) * 5
    assert calls.count("runtime-enter") == 2
    assert calls.count("gc-enter") == 2


def test_real_fenced_product_seals_five_streams_without_worker_runtime(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        _sources(product.state_root)
        assert seal_coding_product_worker_v1_history_for_v2(product) == (1,) * 5
        assert _generations(product.state_root) == (1,) * 5
    finally:
        owner.close()


def test_product_seal_returns_minimal_cutoff_after_prior_stream_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path)
    stem = "worker-start-gates"
    with _rooted(tmp_path) as rooted:
        history = read_coding_worker_segmented_history(
            rooted, stem=stem, stream_id=stem, max_segment_bytes=1024
        )
        seal_coding_worker_active_segment(
            rooted, stem=stem, stream_id=stem, history=history, last_revision=1
        )
        line = b'{"journalRevision":2}\n'
        rooted.sibling(stem + ".g00000001.jsonl").append_bytes(line)
        commit_coding_worker_active_segment(
            rooted,
            stem=stem,
            stream_id=stem,
            generation=1,
            previous_raw=b"",
            appended_line=line,
        )
        history = read_coding_worker_segmented_history(
            rooted, stem=stem, stream_id=stem, max_segment_bytes=1024
        )
        seal_coding_worker_active_segment(
            rooted, stem=stem, stream_id=stem, history=history, last_revision=2
        )
    product = _product(tmp_path, monkeypatch, [])
    assert seal_coding_product_worker_v1_history_for_v2(product) == (1,) * 5
    assert _generations(tmp_path) == (1, 1, 1, 2, 1)


def test_product_seal_resumes_exact_empty_successor_after_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path)
    product = _product(tmp_path, monkeypatch, [])
    original_write = RootedFile.atomic_write

    def pause_third_manifest(
        target: RootedFile,
        data: bytes,
        *,
        fsync: bool = True,
        exclusive: bool = False,
    ) -> None:
        if target._name == "worker-activation-state.segments.json":
            raise OSError("pause before third manifest")
        original_write(target, data, fsync=fsync, exclusive=exclusive)

    with monkeypatch.context() as interrupted:
        interrupted.setattr(RootedFile, "atomic_write", pause_third_manifest)
        with pytest.raises(OSError, match="third manifest"):
            seal_coding_product_worker_v1_history_for_v2(product)
    assert seal_coding_product_worker_v1_history_for_v2(product) == (1,) * 5
    assert _generations(tmp_path) == (1,) * 5


def test_product_seal_refuses_empty_stream_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path, empty_stem=CODING_WORKER_HISTORY_STREAM_STEMS[-1])
    product = _product(tmp_path, monkeypatch, [])
    with pytest.raises(CodingWorkerV2SealError, match="stream_empty"):
        seal_coding_product_worker_v1_history_for_v2(product)
    assert _generations(tmp_path) == (0,) * 5


def test_product_seal_refuses_incomplete_stream_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path)
    stem = CODING_WORKER_HISTORY_STREAM_STEMS[-1]
    with _rooted(tmp_path) as rooted:
        raw = b'{"journalRevision":1}'
        rooted.sibling(stem + ".jsonl").atomic_write(raw)
        rooted.sibling(stem + ".head.json").atomic_write(_head_bytes(stem, 0, raw))
    product = _product(tmp_path, monkeypatch, [])
    with pytest.raises(CodingWorkerV2SealError, match="stream_incomplete"):
        seal_coding_product_worker_v1_history_for_v2(product)
    assert _generations(tmp_path) == (0,) * 5


def test_product_seal_refuses_active_runtime_lease_before_gc_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path)
    calls: list[str] = []
    product = _product(tmp_path, monkeypatch, calls)

    @contextmanager
    def occupied(*, store_id: str) -> Iterator[SimpleNamespace]:
        assert store_id == "store"
        calls.append("runtime-enter")
        try:
            yield SimpleNamespace(active_runtime_lease_ids=("live-session",))
        finally:
            calls.append("runtime-exit")

    monkeypatch.setattr(
        product.epoch_runtime.registry, "exclusive_runtime_quiescence", occupied
    )
    with pytest.raises(CodingWorkerV2SealError, match="runtime_active"):
        seal_coding_product_worker_v1_history_for_v2(product)
    assert calls == ["runtime-enter", "runtime-exit"]
    assert _generations(tmp_path) == (0,) * 5


def test_product_seal_refuses_staged_cutover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path)
    with _rooted(tmp_path) as rooted:
        rooted.sibling(PREPARATION_INTENT_NAME).create_new(b"staged")
    product = _product(tmp_path, monkeypatch, [])
    with pytest.raises(CodingWorkerV2SealError, match="preparation_present"):
        seal_coding_product_worker_v1_history_for_v2(product)
    assert _generations(tmp_path) == (0,) * 5


def test_product_seal_refuses_orphaned_preparation_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path)
    with _rooted(tmp_path) as rooted:
        rooted.sibling(PREPARED_INDEX_NAME).create_new(b"orphan")
    product = _product(tmp_path, monkeypatch, [])
    with pytest.raises(CodingWorkerV2SealError, match="artifact_present"):
        seal_coding_product_worker_v1_history_for_v2(product)
    assert _generations(tmp_path) == (0,) * 5


def test_product_seal_refuses_changed_unpublished_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sources(tmp_path)
    product = _product(tmp_path, monkeypatch, [])
    original_write = RootedFile.atomic_write

    def pause_first_manifest(
        target: RootedFile,
        data: bytes,
        *,
        fsync: bool = True,
        exclusive: bool = False,
    ) -> None:
        if target._name == CODING_WORKER_HISTORY_STREAM_STEMS[0] + ".segments.json":
            raise OSError("pause before first manifest")
        original_write(target, data, fsync=fsync, exclusive=exclusive)

    with monkeypatch.context() as interrupted:
        interrupted.setattr(RootedFile, "atomic_write", pause_first_manifest)
        with pytest.raises(OSError, match="first manifest"):
            seal_coding_product_worker_v1_history_for_v2(product)
    (tmp_path / (CODING_WORKER_HISTORY_STREAM_STEMS[0] + ".g00000001.jsonl")).write_bytes(
        b"changed"
    )
    with pytest.raises(
        CodingWorkerHistorySegmentError, match="unpublished_successor_changed"
    ):
        seal_coding_product_worker_v1_history_for_v2(product)
