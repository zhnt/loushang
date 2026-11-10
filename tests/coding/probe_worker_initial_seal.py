"""Explicit old-first native Rooted seal observations; no default PR discovery."""

import hashlib
import json
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_history_rotate_v2 as coding
import loushang.harness.worker.history._publication as publication
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.worker.history._snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS as STEMS,
)
from loushang.harness.worker.history._v2_names import (
    PREPARATION_INTENT_NAME,
    PREPARED_INDEX_NAME,
    PRODUCT_OWNER_INDEX_NAME,
)
from tests.coding.test_package_product_worker_history_commit_v2 import _product
from tests.coding.test_package_product_worker_history_rotate_v2 import _sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted

FIXTURE = Path(__file__).parent / "fixtures" / "worker_initial_seal_v1.jsonl"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Rooted Worker history"
)


def observe(root, patch, mode, faults=()):
    root.mkdir(mode=0o700)
    _sources(
        root, empty_stem="worker-supervisor" if mode.startswith("empty_") else None
    )
    if mode.startswith("missing_") or mode in ("false_missing",):
        for path in root.glob("worker-supervisor.*"):
            path.unlink()
    if mode == "empty_regular":
        for path in root.glob(STEMS[0] + ".*"):
            path.unlink()
        with _rooted(root) as rooted:
            rooted.sibling(STEMS[0] + ".jsonl.lock").create_new(b"")
            rooted.sibling(STEMS[0] + ".jsonl").create_new(b"")
            from loushang.harness.worker._segmented_history import _head_bytes

            rooted.sibling(STEMS[0] + ".head.json").create_new(
                _head_bytes(STEMS[0], 0, b"")
            )
    if mode == "incomplete":
        from loushang.harness.worker._segmented_history import _head_bytes

        raw = b'{"journalRevision":1}'
        with _rooted(root) as rooted:
            rooted.sibling(STEMS[2] + ".jsonl").atomic_write(raw)
            rooted.sibling(STEMS[2] + ".head.json").atomic_write(
                _head_bytes(STEMS[2], 0, raw)
            )
    if mode in ("owner", "missing_owner", "owner_large", "owner_unsafe"):
        (root / PRODUCT_OWNER_INDEX_NAME).write_bytes(
            b"x" * (8193 if mode == "owner_large" else 1)
        )
    if mode == "owner_directory":
        (root / PRODUCT_OWNER_INDEX_NAME).mkdir(mode=0o700)
    if mode in ("intent", "intent_unsafe"):
        (root / PREPARATION_INTENT_NAME).write_bytes(b"staged")
    if mode in ("artifact", "artifact_unsafe"):
        (root / PREPARED_INDEX_NAME).write_bytes(b"orphan")
    # Direct fixture writes follow umask; valid metadata must use the same
    # private file mode as the real Rooted writers. Keep unsafe variants too.
    if mode.endswith("_unsafe"):
        unsafe_name = {
            "owner_unsafe": PRODUCT_OWNER_INDEX_NAME,
            "intent_unsafe": PREPARATION_INTENT_NAME,
            "artifact_unsafe": PREPARED_INDEX_NAME,
        }[mode]
        (root / unsafe_name).chmod(0o664)
    else:
        for path in root.iterdir():
            if path.is_file():
                path.chmod(0o600)
    trace, counts, custody = [], {}, []
    remaining_faults = set(faults)

    def event(name):
        counts[name] = counts.get(name, 0) + 1
        tag = name + "#" + str(counts[name])
        trace.append(tag)
        if tag in remaining_faults:
            remaining_faults.remove(tag)
            raise OSError("injected:" + tag)

    product = _product(root, patch, custody)
    patch.setattr(
        type(product), "assert_root_gc_authority_current", lambda self: event("current")
    )
    original_pin = type(product).pinned_state_root_gc_read

    @contextmanager
    def pin(self):
        try:
            with original_pin(self) as fd:
                event("pin.enter")
                yield fd
        finally:
            event("pin.exit")

    patch.setattr(type(product), "pinned_state_root_gc_read", pin)

    def checkpoints(product):
        event("checkpoints")
        qualified = mode in ("empty_qualified", "missing_qualified", "missing_owner")
        if not qualified:
            return ()
        snapshot = SimpleNamespace(
            stem="worker-supervisor",
            total_revision=0,
            active_generation=0,
            segment_byte_counts=(0,),
            segment_digests=(hashlib.sha256(b"").hexdigest(),),
        )
        return (SimpleNamespace(stream_snapshots=(None, None, None, None, snapshot)),)

    patch.setattr(
        coding,
        "read_coding_product_worker_history_checkpoints_under_gc_guard",
        checkpoints,
    )

    for name in (
        "initialize_coding_worker_active_head",
        "rollback_coding_worker_unpublished_successor",
        "read_coding_worker_segmented_history",
        "seal_coding_worker_active_segment",
    ):
        # R1 Code references are aliases of these original Core operations.
        original = getattr(coding, name, None) or getattr(publication, name, None)
        assert original is not None

        def wrapped(*args, _name=name, _original=original, **kwargs):
            stem = kwargs["stem"]
            event(_name + ".before:" + stem)
            value = _original(*args, **kwargs)
            event(_name + ".after:" + stem)
            return value

        patch.setattr(coding, name, wrapped, raising=False)
        patch.setattr(publication, name, wrapped, raising=False)
    for name in ("acquire_lock", "create_new", "stat", "scan_sibling_names"):
        original = getattr(RootedFile, name)

        def wrapped(self, *args, _name=name, _original=original, **kwargs):
            event(_name + ".before:" + self._name)
            value = _original(self, *args, **kwargs)
            event(_name + ".after:" + self._name)
            return value

        patch.setattr(RootedFile, name, wrapped)
    original_exit = RootedFileIO.__exit__

    def exit_io(self, *args):
        try:
            return original_exit(self, *args)
        finally:
            event("io.exit")

    patch.setattr(RootedFileIO, "__exit__", exit_io)
    original_bind = RootedFileIO.bind

    @contextmanager
    def bind(self, *args, **kwargs):
        try:
            with original_bind(self, *args, **kwargs) as rooted:
                event("bind.enter")
                yield rooted
        finally:
            event("bind.exit")

    patch.setattr(RootedFileIO, "bind", bind)

    def error_value(error):
        if error is None:
            return None
        return {
            "type": type(error).__name__,
            "text": str(error).replace(str(root), "<root>"),
            "code": getattr(error, "code", None),
            "context": error_value(error.__context__),
            "cause": error_value(error.__cause__),
        }

    value, failure = None, None
    try:
        if mode.startswith("false_"):
            with _rooted(root) as rooted:
                publication.HistoryPublication._lock_streams(
                    rooted, coding.CodingWorkerV2SealError
                )
        else:
            value = list(coding.seal_coding_product_worker_v1_history_for_v2(product))
    except BaseException as error:
        failure = error_value(error)
    tree = []
    for path in sorted(root.iterdir()):
        metadata = path.lstat()
        tree.append(
            {
                "name": path.name,
                "mode": stat.S_IMODE(metadata.st_mode),
                "kind": "directory" if path.is_dir() else "file",
                "bytes": path.read_bytes().hex() if path.is_file() else None,
            }
        )
    return {
        "trace": trace,
        "value": value,
        "error": failure,
        "custody": custody,
        "tree": tree,
        "unreached_faults": sorted(remaining_faults),
    }


DOCUMENTS = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
BYTE_VALUES = DOCUMENTS[0]["byteValues"]
ROWS = DOCUMENTS[1:]
for record in ROWS:
    for entry in record["expected"]["tree"]:
        reference = entry.pop("byteRef")
        entry["bytes"] = None if reference is None else BYTE_VALUES[reference]


@pytest.mark.parametrize(
    "row", ROWS, ids=lambda r: r["mode"] + ":" + ",".join(r["faults"])
)
def test_replay(tmp_path, monkeypatch, row):
    assert (
        observe(tmp_path / "root", monkeypatch, row["mode"], row["faults"])
        == row["expected"]
    )
