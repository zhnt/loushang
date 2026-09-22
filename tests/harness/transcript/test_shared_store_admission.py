from __future__ import annotations

import asyncio
import json
import os
import selectors
import subprocess
import sys

import pytest

from loushang.harness.transcript import ProductTranscriptSession
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_owned_session_factory import factory, new
from .test_writer_images import message
from .test_writer_lifecycle import assert_busy

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux shared store family")


def test_fresh_sibling_stores_share_original_attachment_domain(tmp_path):
    async def scenario():
        state = tmp_path / "state/session-stores"
        first, second = factory(store_state_root=state), factory(store_state_root=state)
        a = b = None
        try:
            a = await new(first, tmp_path / "data/project-a", "a")
            b = await new(second, tmp_path / "data/project-b", "b")
            assert a.context.session_dir != b.context.session_dir
            assert a._writer_owner._blob_writer._expected_root_identity == b._writer_owner._blob_writer._expected_root_identity
            assert (tmp_path / "data/session-assets/.locks").is_dir()
            assert a._writer_owner._store_admission._binding.family_id == b._writer_owner._store_admission._binding.family_id
        finally:
            if b is not None:
                await b.dispose()
            if a is not None:
                await a.dispose()
            await second.close()
            await first.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("loss", ["root", "witness", "both"])
def test_known_sibling_loss_never_becomes_a_new_member(tmp_path, loss):
    state = tmp_path / "state/session-stores"
    first = TranscriptStoreAdmission(tmp_path / "data/project-a", state_root=state, create_if_missing=True)
    second = TranscriptStoreAdmission(tmp_path / "data/project-b", state_root=state, create_if_missing=True)
    try:
        first.open()
        first.close()
        second.open()
    finally:
        second.close()
        first.close()
    if loss in {"root", "both"}:
        second.root.rename(tmp_path / "saved-root")
    if loss in {"witness", "both"}:
        second.witness_root.rename(tmp_path / "saved-witness")
    attempted = TranscriptStoreAdmission(second.root, state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict|incomplete|unavailable"):
            attempted.open()
        if loss in {"root", "both"}:
            assert not second.root.exists()
    finally:
        attempted.close()


@pytest.mark.parametrize("also_member", [False, True])
def test_missing_family_never_falls_back_to_v1_adoption(tmp_path, also_member):
    root, state = tmp_path / "data/project-a", tmp_path / "state/stores"
    admission = TranscriptStoreAdmission(root, state_root=state, create_if_missing=True)
    try:
        admission.open()
    finally:
        admission.close()
    admission._family.root.rename(tmp_path / "saved-family")
    if also_member:
        admission.witness_root.rename(tmp_path / "saved-member")
    retry = TranscriptStoreAdmission(root, state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict|unavailable|incomplete"):
            retry.open()
        assert not admission._family.root.exists()
        if also_member:
            assert not admission.witness_root.exists()
    finally:
        retry.close()


@pytest.mark.parametrize("domain", ["session-assets", "session-assets/.locks", ".session-blob-writers"])
@pytest.mark.parametrize("replace", [False, True])
def test_registered_shared_domain_cannot_be_recreated_or_adopted(tmp_path, domain, replace):
    root, state = tmp_path / "data/project-a", tmp_path / "state/stores"
    admission = TranscriptStoreAdmission(root, state_root=state, create_if_missing=True)
    try:
        admission.open()
    finally:
        admission.close()
    selected = root.parent / domain
    selected.rename(tmp_path / "saved-domain")
    if replace:
        selected.mkdir(mode=0o700)
    retry = TranscriptStoreAdmission(root.parent / "project-b", state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict|unavailable"):
            retry.open()
        assert selected.exists() is replace
        assert not retry.root.exists()
    finally:
        retry.close()


@pytest.mark.parametrize("domain", ["session-assets", "session-assets/.locks"])
@pytest.mark.parametrize("replace", [False, True])
def test_live_blob_operations_check_original_shared_domains(tmp_path, domain, replace):
    async def scenario():
        root, state = tmp_path / "data/project-a", tmp_path / "state/stores"
        selected = factory(store_state_root=state)
        session = await new(selected, root)
        moved = root.parent / domain
        moved.rename(tmp_path / "saved-domain")
        if replace:
            moved.mkdir(mode=0o700)
        try:
            with pytest.raises(OSError):
                await ProductTranscriptSession(lifecycle_session=session).append_message(message())
            assert moved.exists() is replace
            if replace:
                assert not tuple(moved.iterdir())
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_short_lock_handoff_keeps_root_pin_and_rejects_replacement(tmp_path, monkeypatch):
    async def scenario():
        root, state = tmp_path / "data/project-a", tmp_path / "state/stores"
        selected = factory(store_state_root=state)
        release = TranscriptStoreAdmission.release_locks
        observed = []

        def replaced(admission):
            release(admission)
            assert not admission._witness.cleanup_pending
            fd = admission._store._fds["root"]
            original = os.fstat(fd)
            root.rename(tmp_path / "old-store")
            root.mkdir(mode=0o700)
            assert os.fstat(fd).st_ino == original.st_ino
            observed.append(1)

        try:
            monkeypatch.setattr(TranscriptStoreAdmission, "release_locks", replaced)
            with pytest.raises(TranscriptWriterError, match="conflict"):
                await new(selected, root)
            assert observed == [1] and not tuple(root.iterdir())
        finally:
            await selected.close()

    asyncio.run(scenario())


def test_valid_standalone_v1_restores_without_enrollment_but_cannot_add_sibling(tmp_path):
    root, state = tmp_path / "data/project-a", tmp_path / "state/stores"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    legacy = TranscriptStoreAdmission(root, state_root=state)
    try:
        expected = legacy.open()
    finally:
        legacy.close()
    assert json.loads((legacy.witness_root / "admission.json").read_bytes())["version"].endswith("/v1")
    (root.parent / "session-assets").mkdir(mode=0o700)
    restored = TranscriptStoreAdmission(root, state_root=state)
    try:
        assert restored.open() == expected
        assert not restored._family.present
    finally:
        restored.close()
    sibling = TranscriptStoreAdmission(root.parent / "project-b", state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            sibling.open()
        assert not sibling.root.exists() and not sibling._family.present
    finally:
        sibling.close()


def test_v1_exact_member_stays_protected_without_global_cross_path_inference(tmp_path):
    root, state = tmp_path / "data/project-a", tmp_path / "state/stores"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    legacy = TranscriptStoreAdmission(root, state_root=state)
    try:
        legacy.open()
    finally:
        legacy.close()
    root.parent.rename(tmp_path / "saved-data")
    exact = TranscriptStoreAdmission(root, state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError):
            exact.open()
        assert not root.parent.exists()
    finally:
        exact.close()
    sibling = TranscriptStoreAdmission(root.parent / "project-b", state_root=state, create_if_missing=True)
    try:
        # v1 has no parent path mapping: it cannot identify an unknown sibling
        # after that parent disappears. Do not pretend this is a v2 guarantee.
        assert sibling.open().family_id is not None
    finally:
        sibling.close()


def test_valid_unrelated_v1_does_not_block_fresh_family_or_change_old_evidence(tmp_path):
    root, state = tmp_path / "old/project", tmp_path / "state/stores"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    old = TranscriptStoreAdmission(root, state_root=state)
    try:
        binding = old.open()
        witness = old.witness_root / "admission.json"
        before = witness.read_bytes()
    finally:
        old.close()
    fresh = TranscriptStoreAdmission(tmp_path / "new/project", state_root=state, create_if_missing=True)
    try:
        assert fresh.open().family_id is not None
        assert witness.read_bytes() == before
    finally:
        fresh.close()
    restored = TranscriptStoreAdmission(root, state_root=state)
    try:
        assert restored.open() == binding
    finally:
        restored.close()


@pytest.mark.parametrize("field,value", [
    ("extra", True), ("store", "0" * 64), ("operation", "invalid"),
    ("phase", "initializing"), ("parent", [True, 1]),
    ("witness", [0, 1]), ("lock", [0, 1]),
])
def test_unrelated_bad_v1_is_not_ignored(tmp_path, field, value):
    root, state = tmp_path / "old/project", tmp_path / "state/stores"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    old = TranscriptStoreAdmission(root, state_root=state)
    try:
        old.open()
        witness = old.witness_root / "admission.json"
    finally:
        old.close()
    record = json.loads(witness.read_bytes())
    record[field] = value
    witness.write_text(json.dumps(record))
    before = witness.read_bytes()
    fresh = TranscriptStoreAdmission(tmp_path / "new/project", state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError):
            fresh.open()
        assert not fresh.root.parent.exists()
        assert witness.read_bytes() == before
    finally:
        fresh.close()


def test_empty_but_known_v1_parent_does_not_grant_new_family(tmp_path):
    root, state = tmp_path / "old/project", tmp_path / "state/stores"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    old = TranscriptStoreAdmission(root, state_root=state)
    try:
        old.open()
    finally:
        old.close()
    root.rmdir()
    sibling = TranscriptStoreAdmission(root.parent / "sibling", state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            sibling.open()
        assert not sibling.root.exists()
        assert not sibling._family.present
    finally:
        sibling.close()


def test_data_root_replaced_after_legacy_validation_is_not_adopted(tmp_path, monkeypatch):
    root, state = tmp_path / "old/project", tmp_path / "state/stores"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    old = TranscriptStoreAdmission(root, state_root=state)
    try:
        old.open()
    finally:
        old.close()
    data = tmp_path / "new"
    data.mkdir(mode=0o700)
    fresh = TranscriptStoreAdmission(data / "project", state_root=state, create_if_missing=True)
    original = fresh._family._validate_legacy_evidence

    def validate_then_replace(*args):
        original(*args)
        data.rename(tmp_path / "retained-new")
        data.mkdir(mode=0o700)
        (data / "sentinel").write_bytes(b"do not adopt")

    monkeypatch.setattr(fresh._family, "_validate_legacy_evidence", validate_then_replace)
    try:
        with pytest.raises(TranscriptWriterError):
            fresh.open()
        assert {path.name for path in data.iterdir()} == {"sentinel"}
        assert (data / "sentinel").read_bytes() == b"do not adopt"
    finally:
        fresh.close()


def test_legacy_evidence_unknown_close_retains_parent_and_never_recloses_reused_fd(tmp_path, monkeypatch):
    from loushang.harness.journal._rooted_io import RootedDirectory

    root, state = tmp_path / "old/project", tmp_path / "state/stores"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    old = TranscriptStoreAdmission(root, state_root=state)
    try:
        old.open()
        key = old.witness_root.name
    finally:
        old.close()
    fresh = TranscriptStoreAdmission(tmp_path / "new/project", state_root=state, create_if_missing=True)
    original_child, original_close = RootedDirectory.child, os.close
    retained = {}
    calls = []

    def capture(directory, name, **kwargs):
        child = original_child(directory, name, **kwargs)
        if name == key and not retained:
            retained.update(fd=child._fd, operation=child._operation)
        return child

    def lose_close(fd):
        if fd == retained.get("fd"):
            assert not calls, "retried an unknown close against a reused descriptor"
            original_close(fd)
            replacement = os.open(os.devnull, os.O_RDONLY)
            if replacement != fd:
                os.dup2(replacement, fd)
                original_close(replacement)
            calls.append(fd)
            raise OSError("test legacy evidence close receipt lost")
        original_close(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(RootedDirectory, "child", capture)
            patch.setattr(os, "close", lose_close)
            with pytest.raises(TranscriptWriterError):
                fresh.open()
            assert calls
            for _ in range(2):
                with pytest.raises(OSError, match="unknown"):
                    fresh.close()
                assert fresh.cleanup_pending
                os.fstat(fresh._family._state._fds["root"])
                assert os.fstat(calls[0]).st_rdev == os.stat(os.devnull).st_rdev
            assert calls == [retained["fd"]]
    finally:
        if calls:
            # Only this injector knows the original close completed. Production
            # retains unknown debt; the test removes that witnessed tombstone.
            operation = retained["operation"]
            operation.descriptors.pop(calls[0], None)
            operation.directory_fds.discard(calls[0])
            original_close(calls[0])
        fresh.close()


def test_unregistered_legacy_shared_assets_are_not_implicitly_migrated(tmp_path):
    root, state = tmp_path / "data/project-a", tmp_path / "state/stores"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    (root.parent / "session-assets").mkdir(mode=0o700)
    source = root / "legacy.jsonl"
    source.write_bytes(b"legacy transcript")
    admission = TranscriptStoreAdmission(root, state_root=state)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            admission.open()
        assert source.read_bytes() == b"legacy transcript"
        assert not state.exists()
    finally:
        admission.close()


def test_surviving_v2_state_prevents_v1_fallback_after_family_and_shared_loss(tmp_path):
    state = tmp_path / "state/stores"
    first = TranscriptStoreAdmission(tmp_path / "data/project-a", state_root=state, create_if_missing=True)
    try:
        first.open()
    finally:
        first.close()
    first._family.root.rename(tmp_path / "saved-family")
    (first.root.parent / "session-assets").rename(tmp_path / "saved-assets")
    (first.root.parent / ".session-blob-writers").rename(tmp_path / "saved-writers")
    candidate = first.root.parent / "empty-legacy-candidate"
    candidate.mkdir(mode=0o700)
    admission = TranscriptStoreAdmission(candidate, state_root=state)
    try:
        with pytest.raises(TranscriptWriterError, match="conflict"):
            admission.open()
        assert not admission.witness_root.exists()
    finally:
        admission.close()


@pytest.mark.parametrize("phase", ["shared", "member"])
def test_incomplete_shared_vs_member_facts_have_distinct_scope(tmp_path, monkeypatch, phase):
    state = tmp_path / "state/stores"
    first = TranscriptStoreAdmission(tmp_path / "data/project-a", state_root=state, create_if_missing=True)
    if phase == "shared":
        original = first._family._assets.acquire_child

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("test shared publication not settled")

        monkeypatch.setattr(first._family._assets, "acquire_child", fail)
    else:
        def fail(*args, **kwargs):
            raise OSError("test member publication not settled")

        monkeypatch.setattr(first, "_open_store", fail)
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            first.open()
    finally:
        first.close()
    retry = TranscriptStoreAdmission(first.root, state_root=state, create_if_missing=True)
    sibling = TranscriptStoreAdmission(first.root.parent / "project-b", state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError, match="incomplete"):
            retry.open()
        retry.close()
        if phase == "shared":
            with pytest.raises(TranscriptWriterError, match="incomplete"):
                sibling.open()
        else:
            assert sibling.open().family_id is not None
            assert not first.root.exists()
    finally:
        retry.close()
        sibling.close()


def test_family_discovery_does_not_enroll_an_unseen_sibling(tmp_path):
    from .test_store_admission import snapshot

    state = tmp_path / "state/stores"
    first = TranscriptStoreAdmission(tmp_path / "data/project-a", state_root=state, create_if_missing=True)
    try:
        first.open()
    finally:
        first.close()
    before = snapshot(tmp_path)
    sibling = TranscriptStoreAdmission(first.root.parent / "project-b", state_root=state, create_if_missing=True)
    try:
        assert sibling.inspect() is None
    finally:
        sibling.close()
    assert snapshot(tmp_path) == before


def test_distinct_fresh_data_roots_share_state_without_reclassifying_members(tmp_path):
    state = tmp_path / "state/stores"
    bindings = []
    for name in ("one", "two"):
        admission = TranscriptStoreAdmission(tmp_path / name / "sessions", state_root=state, create_if_missing=True)
        try:
            bindings.append(admission.open())
        finally:
            admission.close()
    assert bindings[0].family_id != bindings[1].family_id
    assert bindings[0].parent_identity != bindings[1].parent_identity


def test_family_member_capacity_is_no_effect_and_does_not_evict_old_identity(tmp_path, monkeypatch):
    from loushang.harness.transcript import _store_family

    from .test_store_admission import snapshot

    state = tmp_path / "state/stores"
    first = TranscriptStoreAdmission(tmp_path / "data/project-a", state_root=state, create_if_missing=True)
    try:
        binding = first.open()
    finally:
        first.close()
    before = snapshot(tmp_path)
    monkeypatch.setattr(_store_family, "_MAX_MEMBERS", 1)
    sibling = TranscriptStoreAdmission(first.root.parent / "project-b", state_root=state, create_if_missing=True)
    try:
        with pytest.raises(TranscriptWriterError, match="capacity"):
            sibling.open()
    finally:
        sibling.close()
    restored = TranscriptStoreAdmission(first.root, state_root=state)
    try:
        assert restored.open() == binding
    finally:
        restored.close()
    assert snapshot(tmp_path) == before


_MEMBER_CHILD = """
import sys, time
from pathlib import Path
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission
from loushang.harness.transcript.writer_lease import TranscriptWriterError
base, name = Path(sys.argv[1]), sys.argv[2]
print('ready', flush=True)
assert sys.stdin.readline().strip() == 'go'
deadline = time.monotonic() + 5
while True:
    owner = TranscriptStoreAdmission(base / 'data' / name, state_root=base / 'state/stores', create_if_missing=True)
    try:
        result = owner.open()
    except TranscriptWriterError as error:
        owner.close()
        if error.code != 'busy' or owner.cleanup_pending or time.monotonic() >= deadline:
            raise
        time.sleep(.01)
    else:
        owner.close()
        print(result.member_id, flush=True)
        break
"""


def test_two_process_member_additions_preserve_both_entries(tmp_path):
    state = tmp_path / "state/stores"
    first = TranscriptStoreAdmission(tmp_path / "data/project-a", state_root=state, create_if_missing=True)
    try:
        binding = first.open()
    finally:
        first.close()
    children = []
    try:
        for name in ("project-b", "project-c"):
            child = subprocess.Popen([sys.executable, "-c", _MEMBER_CHILD, str(tmp_path), name],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            children.append(child)
            with selectors.DefaultSelector() as selected:
                selected.register(child.stdout, selectors.EVENT_READ)
                assert selected.select(15), "member child did not reach gate"
                assert child.stdout.readline().strip() == "ready"
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        for child in children:
            output, error = child.communicate(timeout=15)
            assert child.returncode == 0, error
            assert len(output.strip()) == 32
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
    raw = json.loads((first._family.root / "admission.json").read_bytes())
    assert {member["name"] for member in raw["members"].values()} == {"project-a", "project-b", "project-c"}
    reopened = TranscriptStoreAdmission(first.root, state_root=state)
    try:
        assert reopened.open() == binding  # Ledger revision did not invalidate A.
        reopened.check()
    finally:
        reopened.close()


def test_handoff_pin_close_unknown_does_not_release_lifetime_writers(tmp_path, monkeypatch):
    async def scenario():
        root, state = tmp_path / "data/project-a", tmp_path / "state/stores"
        selected = factory(store_state_root=state)
        session = await new(selected, root)
        admission = session._writer_owner._store_admission
        original = admission._family._assets
        fd = original._fds["root"]
        close, calls = os.close, []

        def lost(value):
            close(value)
            if value == fd and not calls:
                calls.append(value)
                raise OSError("test lost pin close receipt")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, "close", lost)
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await session.dispose()
                assert_busy(root)
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await session.dispose()
                assert calls == [fd]
        finally:
            # Only the test injector witnessed the completed close syscall.
            original._unknown.remove("root")
            del original._fds["root"]
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())
