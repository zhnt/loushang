from __future__ import annotations

import asyncio
import sys
import threading

import pytest

from loushang.coding.hosted_catalog import (
    CodingHostedCatalogError,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.managed_catalog import CodingManagedSessionCatalogV1
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from ..harness.transcript.test_writer_io import wait_until
from .test_hosted_catalog import _intent
from .test_managed_catalog import discovery, ordinary, tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux shared store discovery")


def catalog(root):
    return CodingManagedSessionCatalogV1(session_root=root / "data/sessions", workspace=root,
                                         store_state_root=root / "state/session-stores")


async def initialize(root):
    selected = catalog(root)
    candidate = None
    try:
        candidate = await selected.create_candidate(_intent(selected.scopes[0]))
    finally:
        if candidate is not None:
            await candidate.close()
        await selected.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_browse_never_initializes_or_registers_unknown_store(tmp_path, legacy):
    async def scenario():
        selected = catalog(tmp_path)
        if legacy:
            selected.scopes[0].session_dir.mkdir(parents=True, mode=0o700)
            await ordinary(selected, image=True)
        before = tree(tmp_path)
        try:
            for scope in selected.scopes:
                snapshot = await discovery(selected, scope)
                assert snapshot.complete and len(snapshot.candidates) == int(legacy)
                rows = await selected.list_identities((scope.discovery_scope,), limit=256)
                assert len(rows) == int(legacy)
            assert not selected._store_probes
        finally:
            await selected.close()
        assert tree(tmp_path) == before
        assert not (tmp_path / "state").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["discovery", "routing"])
@pytest.mark.parametrize("loss", ["none", "missing", "replacement", "parent", "marker", "corrupt", "family_marker", "family_corrupt"])
def test_fresh_catalog_known_store_loss_is_unavailable_not_empty(tmp_path, mode, loss):
    async def scenario():
        await initialize(tmp_path)
        root = tmp_path / "data/sessions"
        if loss in ("missing", "replacement"):
            root.rename(tmp_path / "original")
            if loss == "replacement":
                root.mkdir(mode=0o700)
        elif loss == "parent":
            root.parent.rename(tmp_path / "original")
            root.parent.mkdir(mode=0o700)
            (tmp_path / "original/sessions").rename(root)
        elif loss in ("marker", "corrupt", "family_marker", "family_corrupt"):
            admission = TranscriptStoreAdmission(root, state_root=tmp_path / "state/session-stores")
            witness = admission._family.root if loss.startswith("family_") else admission.witness_root
            marker = witness / "admission.json"
            if loss.endswith("marker"):
                marker.rename(tmp_path / "original-marker")
            else:
                marker.write_bytes(b"{}")
        before = tree(tmp_path)
        selected = catalog(tmp_path)  # No in-memory observation from the creator.
        try:
            scope = selected.scopes[0]
            call = (discovery(selected, scope) if mode == "discovery"
                    else selected.list_identities((scope.discovery_scope,), limit=256))
            if loss == "none":
                result = await call
                assert len(result.candidates if mode == "discovery" else result) == 1
            else:
                with pytest.raises((CodingHostedCatalogError, TranscriptWriterError)):
                    await call
            assert not selected._store_probes
        finally:
            await selected.close()
        assert tree(tmp_path) == before

    asyncio.run(scenario())


def test_failed_probe_cleanup_is_retained_and_fences_additional_reads(tmp_path, monkeypatch):
    async def scenario():
        await initialize(tmp_path)
        selected = catalog(tmp_path)
        close = TranscriptStoreAdmission.close
        failures = []

        def fail(owner):
            failures.append(owner)
            raise OSError("injected observation cleanup failure")

        with monkeypatch.context() as patch:
            patch.setattr(TranscriptStoreAdmission, "close", fail)
            with pytest.raises(CodingHostedCatalogError):
                await discovery(selected, selected.scopes[0])
            original, = selected._store_probes
            assert selected._store_probes[original] is False and original.cleanup_pending
            with pytest.raises(CodingHostedCatalogError):
                await discovery(selected, selected.scopes[1])
            assert tuple(selected._store_probes) == (original,) and len(failures) == 1
            with pytest.raises(OSError, match="cleanup"):
                await selected.close()
            assert failures == [original, original]
            patch.setattr(TranscriptStoreAdmission, "close", close)
            await selected.close()
        assert not original.cleanup_pending and not selected._store_probes

    asyncio.run(scenario())


def test_cancelled_browse_and_close_keep_active_probe_until_real_worker_finishes(tmp_path, monkeypatch):
    async def scenario():
        await initialize(tmp_path)
        selected = catalog(tmp_path)
        entered, release = threading.Event(), threading.Event()
        inspect = TranscriptStoreAdmission.inspect

        def paused(owner):
            result = inspect(owner)
            entered.set()
            assert release.wait(10)
            return result

        monkeypatch.setattr(TranscriptStoreAdmission, "inspect", paused)
        caller = asyncio.create_task(discovery(selected, selected.scopes[0]))
        try:
            await wait_until(entered.is_set)
            original, = selected._store_probes
            assert original.cleanup_pending
            caller.cancel()
            await asyncio.sleep(0)
            assert not caller.done()
            with pytest.raises(CodingHostedCatalogError):
                await selected.close()
            assert original.cleanup_pending and selected._store_probes[original] is True
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(caller, 10)
            await selected.close()
            assert not original.cleanup_pending and not selected._store_probes
            assert selected._store_active_reads == 0
        finally:
            release.set()
            await asyncio.gather(caller, return_exceptions=True)
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["discovery", "routing"])
@pytest.mark.parametrize("replacement", ["root", "parent"])
def test_store_replaced_after_inspect_is_rejected_by_original_probe(tmp_path, monkeypatch, mode, replacement):
    async def scenario():
        await initialize(tmp_path)
        selected = catalog(tmp_path)
        root = selected.scopes[0].session_dir
        inspect = TranscriptStoreAdmission.inspect
        snapshots = []

        def replace(owner):
            result = inspect(owner)
            source = root if replacement == "root" else root.parent
            source.rename(tmp_path / "original")
            source.mkdir(mode=0o700)
            if replacement == "parent":
                (tmp_path / "original/sessions").rename(root)
            snapshots.append(tree(tmp_path))
            return result

        monkeypatch.setattr(TranscriptStoreAdmission, "inspect", replace)
        try:
            scope = selected.scopes[0]
            with pytest.raises((CodingHostedCatalogError, TranscriptWriterError)):
                if mode == "discovery":
                    await discovery(selected, scope)
                else:
                    await selected.list_identities((scope.discovery_scope,), limit=256)
            assert not selected._store_probes
        finally:
            await selected.close()
        assert len(snapshots) == 1 and tree(tmp_path) == snapshots[0]

    asyncio.run(scenario())


def test_lost_executor_submission_receipt_does_not_admit_untracked_discovery(tmp_path, monkeypatch):
    async def scenario():
        await initialize(tmp_path)
        selected = catalog(tmp_path)
        loop = asyncio.get_running_loop()
        submit = loop.run_in_executor
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        futures, reads = [], []

        def forbidden(*args, **kwargs):
            reads.append(True)
            raise AssertionError("unpublished submission ran actual discovery")

        def lost(executor, work, *args):
            def gated():
                entered.set()
                assert release.wait(10)
                try:
                    return work(*args)
                finally:
                    finished.set()

            futures.append(submit(executor, gated))
            assert entered.wait(10)
            raise OSError("lost executor submission receipt")

        monkeypatch.setattr(selected, "_read_discovery", forbidden)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(loop, "run_in_executor", lost)
                with pytest.raises(OSError, match="submission receipt"):
                    await discovery(selected, selected.scopes[0])
            assert not selected._store_probes and selected._store_active_reads == 0
            await selected.close()
            assert not finished.is_set()
            release.set()
            await asyncio.wait_for(asyncio.gather(*futures), 10)
            assert finished.is_set() and not reads
        finally:
            release.set()
            await asyncio.gather(*futures, return_exceptions=True)
            await selected.close()

    asyncio.run(scenario())


def test_read_capacity_is_bounded_before_executor_submission(tmp_path, monkeypatch):
    async def scenario():
        selected = catalog(tmp_path)
        release = asyncio.Event()
        entered = []

        async def paused(*args, **kwargs):
            entered.append(True)
            await release.wait()

        monkeypatch.setattr(CodingHostedSessionCatalogV1, "discover_sessions", paused)
        callers = [asyncio.create_task(discovery(selected, selected.scopes[0])) for _ in range(8)]
        try:
            await wait_until(lambda: len(entered) == 8)
            with pytest.raises(CodingHostedCatalogError):
                await discovery(selected, selected.scopes[1])
            assert len(entered) == selected._store_active_reads == 8
        finally:
            release.set()
            await asyncio.gather(*callers)
            await selected.close()
        assert selected._store_active_reads == 0 and not selected._store_probes

    asyncio.run(scenario())


@pytest.mark.parametrize("known_witness", [False, True])
def test_live_catalog_does_not_forget_known_identity_when_persistent_evidence_disappears(tmp_path, known_witness):
    async def scenario():
        if known_witness:
            await initialize(tmp_path)
        else:
            (tmp_path / "data/sessions").mkdir(parents=True, mode=0o700)
        selected = catalog(tmp_path)
        try:
            await discovery(selected, selected.scopes[0])
            if known_witness:
                (tmp_path / "state/session-stores").rename(tmp_path / "original-witness")
            else:
                root = selected.scopes[0].session_dir
                root.rename(tmp_path / "original-sessions")
                root.mkdir(mode=0o700)
            before = tree(tmp_path)
            with pytest.raises(CodingHostedCatalogError):
                await discovery(selected, selected.scopes[0])
            assert tree(tmp_path) == before and not selected._store_probes
        finally:
            await selected.close()

    asyncio.run(scenario())
