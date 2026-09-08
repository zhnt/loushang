from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionAvailabilityV1,
    SessionCompatibilityV1,
    SessionListV1,
    SessionScopeV1,
)
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryBindingV1,
    HostedSessionDiscoveryScopeV1,
)
from loushang.appservice.session_discovery import SessionDiscoveryOwnerV1
from loushang.coding.hosted_catalog import (
    CodingHostedCatalogError,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.journal import journal_file_lock

from .test_hosted_catalog import _intent, _scope


def _query(scope):
    return HostedSessionDiscoveryScopeV1("coding", scope.scope, scope.fingerprint)


async def _create(owner, scope, count=1):
    for number in range(count):
        intent = _intent(scope)
        candidate = await owner.create_candidate(replace(
            intent, request=replace(intent.request, operation_id=f"operation-{number:024d}")
        ))
        await candidate.close()


@pytest.mark.parametrize("kind", list(SessionScopeV1))
def test_G17_PRODUCT_discovery_observes_real_headers_without_routing_cache(tmp_path, kind):
    async def scenario():
        scope = _scope(tmp_path, kind)
        owner = CodingHostedSessionCatalogV1((scope,))
        empty = await owner.discover_sessions(_query(scope), stop=lambda: False)
        assert not empty.candidates and empty.complete
        assert not scope.session_dir.exists()
        await _create(owner, scope, 3)
        owner = CodingHostedSessionCatalogV1((scope,))
        before = set(scope.session_dir.iterdir())
        snapshot = await owner.discover_sessions(_query(scope), stop=lambda: False)
        assert len(snapshot.candidates) == 3 and snapshot.complete
        assert all(row.availability is SessionAvailabilityV1.AVAILABLE for row in snapshot.candidates)
        assert not owner._records
        assert set(scope.session_dir.iterdir()) == before
        assert str(tmp_path) not in repr(snapshot)
    asyncio.run(scenario())


def test_G17_PRODUCT_unknown_scope_rejected_before_directory_io(tmp_path, monkeypatch):
    async def scenario():
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        def forbidden(*_args, **_kwargs):
            raise AssertionError("unadmitted scope performed IO")
        monkeypatch.setattr(Path, "lstat", forbidden)
        with pytest.raises(ValueError):
            await owner.discover_sessions(replace(_query(scope), scope_fingerprint="b" * 64),
                                          stop=lambda: False)
    asyncio.run(scenario())


def test_G17_PRODUCT_cancelled_waiter_waits_for_actual_read_worker(tmp_path, monkeypatch):
    async def scenario():
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        entered, release = threading.Event(), threading.Event()
        original = owner._read_discovery
        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(2)
            return original(*args, **kwargs)
        monkeypatch.setattr(owner, "_read_discovery", blocked)
        task = asyncio.create_task(owner.discover_sessions(_query(scope), stop=lambda: False))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_G17_PRODUCT_all_task_cancellation_retains_actual_worker_debt(tmp_path, monkeypatch):
    async def scenario():
        scope = _scope(tmp_path)
        catalog = CodingHostedSessionCatalogV1((scope,))
        owner = SessionDiscoveryOwnerV1(
            HostedSessionDiscoveryBindingV1("generation", (_query(scope),), catalog),
            close_timeout=0.01,
        )
        entered, release, ended = threading.Event(), threading.Event(), threading.Event()
        original = catalog._read_discovery
        def blocked(*args):
            entered.set()
            try:
                assert release.wait(3)
                return original(*args)
            finally:
                ended.set()
        monkeypatch.setattr(catalog, "_read_discovery", blocked)
        prior = asyncio.all_tasks()
        request = SessionListV1("coding", scope.scope, scope.fingerprint)
        query = asyncio.create_task(owner.open_view().list_sessions(request))
        tasks = set()
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            tasks = asyncio.all_tasks() - prior
            # Simulate Runner cancellation of every outstanding application Task,
            # including an independently cancellable to_thread wrapper, if any.
            for task in tasks:
                task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await query
            with pytest.raises(AppServiceError) as pending:
                await owner.close()
            assert pending.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert owner.pending_count == 1 and not ended.is_set()
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            assert ended.is_set()
            await owner.close()
            assert owner.pending_count == 0
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await owner.close()
    asyncio.run(scenario())


def test_G17_PRODUCT_nonblocking_lock_contention_is_visible_and_read_only(tmp_path):
    async def scenario():
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        await _create(owner, scope)
        path = next(scope.session_dir.glob("*.jsonl"))
        code = (
            "from pathlib import Path; import sys; "
            "from loushang.harness.journal import journal_file_lock\n"
            "with journal_file_lock(Path(sys.argv[1]), 'exclusive'):\n"
            " print('locked', flush=True)\n"
            " sys.stdin.read(1)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", code, str(path)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        )
        try:
            assert child.stdout is not None
            assert await asyncio.to_thread(child.stdout.readline) == b"locked\n"
            snapshot = await asyncio.wait_for(
                owner.discover_sessions(_query(scope), stop=lambda: False), 1,
            )
            assert not snapshot.complete and snapshot.omitted_count == 1
            assert not snapshot.omitted_count_exact
        finally:
            if child.stdin is not None:
                child.stdin.close()
            try:
                await asyncio.to_thread(child.wait, 2)
            except subprocess.TimeoutExpired:
                child.kill()
                await asyncio.to_thread(child.wait, 2)
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G17_PRODUCT_budget_exhaustion_cannot_offer_unverified_rows(tmp_path, monkeypatch):
    async def scenario():
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        await _create(owner, scope, 2)
        monkeypatch.setattr("loushang.coding.hosted_catalog._DISCOVERY_BYTES", 65536)
        snapshot = await owner.discover_sessions(_query(scope), stop=lambda: False)
        assert not snapshot.complete and not snapshot.omitted_count_exact
        assert len(snapshot.candidates) == 1
        assert snapshot.candidates[0].availability is SessionAvailabilityV1.UNVERIFIED
    asyncio.run(scenario())


def test_G17_PRODUCT_budget_external_duplicate_disables_partial_directory(tmp_path):
    async def scenario():
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        await _create(owner, scope)
        source = next(scope.session_dir.glob("*.jsonl"))
        content = source.read_bytes()
        for index in range(256):
            copied = scope.session_dir / f"copy-{index}.jsonl"
            copied.write_bytes(content)
            with journal_file_lock(copied, "exclusive"):
                pass
        snapshot = await owner.discover_sessions(_query(scope), stop=lambda: False)
        assert not snapshot.complete and not snapshot.omitted_count_exact
        assert all(row.availability is SessionAvailabilityV1.UNVERIFIED for row in snapshot.candidates)
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["malformed", "legacy", "unsupported", "duplicate", "missing-lock"])
def test_G17_PRODUCT_classifies_unavailable_history_without_adoption(tmp_path, case):
    async def scenario():
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        await _create(owner, scope, 2)
        path = next(scope.session_dir.glob("*.jsonl"))
        if case == "malformed":
            path.write_text("{malformed\n")
        elif case == "legacy":
            manager = await SessionManager.new(
                session_dir=scope.session_dir, cwd=str(scope.cwd), defer_materialization=False,
            )
            await manager.dispose_runtime_profile()
        elif case == "unsupported":
            lines = path.read_text().splitlines()
            header = json.loads(lines[0])
            header["metadata"]["coding.hosted"]["compatibilityId"] = "unsupported-v99"
            lines[0] = json.dumps(header)
            path.write_text("\n".join(lines) + "\n")
        elif case == "duplicate":
            duplicate = scope.session_dir / "copy.jsonl"
            duplicate.write_bytes(path.read_bytes())
            with journal_file_lock(duplicate, "exclusive"):
                pass
        else:
            path.with_suffix(".jsonl.lock").unlink()
        before = set(scope.session_dir.iterdir())
        snapshot = await owner.discover_sessions(_query(scope), stop=lambda: False)
        assert set(scope.session_dir.iterdir()) == before
        if case in {"malformed", "missing-lock"}:
            assert not snapshot.complete and snapshot.omitted_count == 1
            assert all(row.availability is SessionAvailabilityV1.UNVERIFIED for row in snapshot.candidates)
        elif case == "legacy":
            assert snapshot.complete and snapshot.omitted_count == 1
            assert len(snapshot.candidates) == 2
        elif case == "unsupported":
            assert snapshot.complete
            unsupported = [row for row in snapshot.candidates
                           if row.compatibility is SessionCompatibilityV1.UNSUPPORTED]
            assert len(unsupported) == 1
            assert unsupported[0].availability is SessionAvailabilityV1.UNAVAILABLE
        else:
            assert snapshot.complete and snapshot.omitted_count == 1
            assert len(snapshot.candidates) == 2
            assert all(row.availability is SessionAvailabilityV1.UNAVAILABLE for row in snapshot.candidates)
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["file", "unreadable"])
def test_G17_PRODUCT_invalid_roots_are_not_empty_success(tmp_path, monkeypatch, case):
    async def scenario():
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        if case == "file":
            scope.session_dir.write_text("not a directory")
        else:
            scope.session_dir.mkdir()
            def unavailable(*_args):
                raise PermissionError("private-root-sentinel")
            monkeypatch.setattr(os, "scandir", unavailable)
        with pytest.raises(CodingHostedCatalogError) as error:
            await owner.discover_sessions(_query(scope), stop=lambda: False)
        assert "sentinel" not in str(error.value)
    asyncio.run(scenario())
