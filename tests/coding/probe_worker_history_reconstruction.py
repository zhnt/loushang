"""Retired generations stay absent while a caller reconstructs retained bytes."""

from __future__ import annotations

import hashlib
import sys
from types import SimpleNamespace

import pytest

from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerSealedSegmentV1,
    CodingWorkerSegmentManifestV1,
)
from loushang.harness.worker.history._read_v2 import RetainedHistoryReader
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux rooted Worker history"
)


@pytest.mark.parametrize("changed", [False, True])
def test_reconstruction_keeps_absent_retired_bytes_and_delays_error(tmp_path, changed):
    stem = "worker-start-gates"
    old = b"old\n"
    manifest = CodingWorkerSegmentManifestV1(
        stem,
        1,
        (
            CodingWorkerSealedSegmentV1(
                0,
                1,
                1,
                len(old),
                hashlib.sha256(old).hexdigest(),
            ),
        ),
    )
    retained = SimpleNamespace(
        active_generation=2 if changed else 1,
        first_retained_generation=1,
        segments=(b"new\n",),
    )
    original = RuntimeError("original profile generation mismatch")
    called = []

    def mismatch():
        called.append("error")
        return original

    with _rooted(tmp_path) as rooted:
        rooted.sibling(stem + ".segments.json").create_new(manifest.to_bytes())
        before = sorted(tmp_path.iterdir())
        if changed:
            with pytest.raises(RuntimeError) as failure:
                RetainedHistoryReader.history_from_retained(
                    rooted,
                    retained,
                    stem=stem,
                    manifest_changed=mismatch,
                )
            assert failure.value is original
            assert failure.value.__cause__ is None
            assert called == ["error"]
        else:
            history = RetainedHistoryReader.history_from_retained(
                rooted,
                retained,
                stem=stem,
                manifest_changed=mismatch,
            )
            assert history.segments == (b"", b"new\n")
            assert history.manifest == manifest
            assert not called
        assert sorted(tmp_path.iterdir()) == before
        assert (
            rooted.sibling(stem + ".segments.json").read_bytes() == manifest.to_bytes()
        )
