from __future__ import annotations

import asyncio
import threading

import pytest

from loushang.harness.resources._catalog_preview_tasks import CatalogPreviewTaskError
from loushang.harness.resources.loader import (
    ResourceLoader,
    ResourceLoaderCompatibilityError,
)


async def _entered(event: threading.Event) -> None:
    async with asyncio.timeout(5):
        while not event.is_set():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("mode", ["shared", "close_first", "cancel_first", "different_policy", "different_subject"])
def test_distinct_resource_owners_share_only_matching_live_work(tmp_path, monkeypatch, mode) -> None:
    first = ResourceLoader(user_resource_roots=())
    second = ResourceLoader(user_resource_roots=())
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered, released = threading.Event(), threading.Event()
    calls = 0

    def compute(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiter = asyncio.create_task(_request(first, tmp_path))
        peer = None
        close = None
        try:
            await _entered(entered)
            peer = asyncio.create_task(_request(
                second, tmp_path, policy="c" * 64 if mode == "different_policy" else "b" * 64,
                subject="c" * 64 if mode == "different_subject" else "a" * 64,
                priority="foreground",
            ))
            async with asyncio.timeout(5):
                while second._catalog_preview_tasks is None or not second._catalog_preview_tasks._jobs:
                    await asyncio.sleep(0)
            first_job = first._catalog_preview_tasks._jobs[0]
            second_job = second._catalog_preview_tasks._jobs[0]
            isolated = mode in {"different_policy", "different_subject"}
            assert (first_job is second_job) == (not isolated)
            if mode == "cancel_first":
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
                assert not first_job.cancelled.is_set()
                assert not peer.done()
            if mode == "close_first":
                close = asyncio.create_task(first.aclose())
                async with asyncio.timeout(5):
                    while not first._catalog_preview_tasks._closed:
                        await asyncio.sleep(0)
                assert not first_job.cancelled.is_set()
                assert not peer.done()
            released.set()
            result = await peer
            if mode == "close_first":
                with pytest.raises(CatalogPreviewTaskError, match="catalog_preview_closed"):
                    await waiter
                await close
            elif mode != "cancel_first":
                assert await waiter == result
            assert calls == (2 if isolated else 1)
            assert result == second.preview_catalog_input_receipt(tmp_path).input_fingerprint
            assert not first._catalog_authority_selected
            assert not second._catalog_authority_selected
        finally:
            released.set()
            await first.aclose()
            await second.aclose()
            await asyncio.gather(*(item for item in (waiter, peer, close) if item is not None), return_exceptions=True)
            assert not first._catalog_preview_tasks._jobs
            assert not second._catalog_preview_tasks._jobs

    asyncio.run(scenario())


def test_last_view_close_releases_waiter_before_native_settlement(tmp_path, monkeypatch) -> None:
    loader = ResourceLoader(user_resource_roots=())
    view = loader.create_catalog_session_view()
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered, released = threading.Event(), threading.Event()

    def compute(*args, **kwargs):
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiter = asyncio.create_task(_request(view, tmp_path))
        try:
            await _entered(entered)
            await view.aclose()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not released.is_set()
            assert not view._catalog_preview_waiters
            with pytest.raises(ResourceLoaderCompatibilityError, match="settlement_pending"):
                loader.close()
            released.set()
            await loader.aclose()
            assert not loader._catalog_preview_tasks._jobs
        finally:
            released.set()
            waiter.cancel()
            await loader.aclose()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(scenario())


def _request(loader, root, *, subject="a" * 64, policy="b" * 64, units=4096, priority="background"):
    return loader.preview_catalog_input_fingerprint(
        root, subject_digest=subject, policy_digest=policy,
        max_work_units=units, time_budget_seconds=30, priority=priority,
    )


@pytest.mark.parametrize("reuse_background_job", [False, True])
def test_foreground_preview_precedes_queued_background_without_replaying_shared_work(
    tmp_path, monkeypatch, reuse_background_job,
) -> None:
    loader = ResourceLoader(user_resource_roots=())
    foreground_view = loader.create_catalog_session_view()
    initial_catalog_state = (
        loader._catalog_authority_selected, loader._catalog_inputs_pending,
        loader._catalog_projection,
    )
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    order: list[str] = []
    roots = {name: tmp_path / name for name in (
        "blocker0", "blocker1", "background0", "background1", "foreground",
    )}
    for root in roots.values():
        root.mkdir()

    def compute(state, cwd, **kwargs):
        order.append(cwd.name)
        if cwd.name.startswith("blocker"):
            index = int(cwd.name[-1])
            entered[index].set()
            assert release[index].wait(5)
        return original(state, cwd, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiters = [asyncio.create_task(_request(loader, roots[f"blocker{i}"])) for i in range(2)]
        try:
            await _entered(entered[0])
            await _entered(entered[1])
            background = [asyncio.create_task(_request(loader, roots[f"background{i}"])) for i in range(2)]
            waiters.extend(background)
            await asyncio.sleep(0)
            foreground_root = roots["background1" if reuse_background_job else "foreground"]
            foreground = asyncio.create_task(_request(foreground_view, foreground_root, priority="foreground"))
            waiters.append(foreground)
            # Session views own a child waiter. Observe original-scope admission
            # rather than assuming one event-loop yield has submitted that child.
            async with asyncio.timeout(5):
                while not any(
                    job.key[0] == foreground_root
                    and job.references == (2 if reuse_background_job else 1)
                    for job in loader._catalog_preview_tasks._jobs
                ):
                    await asyncio.sleep(0)
            assert len(loader._catalog_preview_tasks._jobs) == (4 if reuse_background_job else 5)
            release[0].set()
            result = await foreground
            background_results = await asyncio.gather(*background)
            assert [name for name in order if not name.startswith("blocker")][0] == foreground_root.name
            if reuse_background_job:
                assert result == background_results[1]
                assert order.count("background1") == 1
            assert (
                loader._catalog_authority_selected, loader._catalog_inputs_pending,
                loader._catalog_projection,
            ) == initial_catalog_state
            assert foreground_view._catalog_projection is None
        finally:
            for event in release:
                event.set()
            await foreground_view.aclose()
            await loader.aclose()
            await asyncio.gather(*waiters, return_exceptions=True)

    asyncio.run(scenario())


def test_resource_waiters_share_scan_and_cancel_only_their_own_reference(tmp_path, monkeypatch) -> None:
    loader = ResourceLoader(user_resource_roots=())
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered, released = threading.Event(), threading.Event()
    calls = 0

    def compute(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        first = asyncio.create_task(_request(loader, tmp_path))
        second = asyncio.create_task(_request(loader, tmp_path))
        try:
            await _entered(entered)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert calls == 1
            assert not second.done()
            released.set()
            fingerprint = await second
            assert len(fingerprint) == 64
            assert fingerprint == loader.preview_catalog_input_receipt(tmp_path).input_fingerprint
            assert loader._catalog_authority_selected is False
            assert loader._legacy_authority_selected is False
        finally:
            released.set()
            await loader.aclose()
            await asyncio.gather(first, second, return_exceptions=True)

    asyncio.run(scenario())


def test_closing_background_owner_settles_before_blocked_foreground_peer(tmp_path, monkeypatch) -> None:
    background = ResourceLoader(user_resource_roots=())
    peer = ResourceLoader(user_resource_roots=())
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    foreground_entered, foreground_release = threading.Event(), threading.Event()
    roots = {name: tmp_path / name for name in ("blocker0", "blocker1", "cancelled", "foreground")}
    for root in roots.values():
        root.mkdir()

    def compute(state, cwd, **kwargs):
        if cwd.name == "cancelled":
            pytest.fail("cancelled preview read source content")
        if cwd.name.startswith("blocker"):
            index = int(cwd.name[-1])
            entered[index].set()
            assert release[index].wait(5)
        elif cwd.name == "foreground":
            foreground_entered.set()
            assert foreground_release.wait(5)
        return original(state, cwd, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiters = [asyncio.create_task(_request(peer, roots[f"blocker{i}"])) for i in range(2)]
        closing = None
        try:
            for event in entered:
                await _entered(event)
            waiters.append(asyncio.create_task(_request(background, roots["cancelled"])))
            await asyncio.sleep(0)
            waiters.append(asyncio.create_task(_request(peer, roots["foreground"], priority="foreground")))
            await asyncio.sleep(0)
            closing = asyncio.create_task(background.aclose())
            await asyncio.sleep(0)
            release[0].set()
            await _entered(foreground_entered)
            async with asyncio.timeout(1):
                await closing
            assert not foreground_release.is_set()
            assert not background._catalog_preview_tasks._jobs
        finally:
            for event in (*release, foreground_release):
                event.set()
            await background.aclose()
            await peer.aclose()
            await asyncio.gather(*waiters, return_exceptions=True)
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)

    asyncio.run(scenario())


def test_resource_close_joins_actual_native_completion_even_when_close_is_cancelled(tmp_path, monkeypatch) -> None:
    loader = ResourceLoader(user_resource_roots=())
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered, released = threading.Event(), threading.Event()

    def compute(*args, **kwargs):
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiter = asyncio.create_task(_request(loader, tmp_path))
        closing = None
        try:
            await _entered(entered)
            with pytest.raises(ResourceLoaderCompatibilityError, match="settlement_pending"):
                loader.close()
            closing = asyncio.create_task(loader.aclose())
            await asyncio.sleep(0)
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done()
            released.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            with pytest.raises(CatalogPreviewTaskError, match="catalog_preview_closed"):
                await waiter
            loader.close()
        finally:
            released.set()
            await loader.aclose()
            await asyncio.gather(waiter, *(() if closing is None else (closing,)), return_exceptions=True)

    asyncio.run(scenario())


def test_resource_background_budget_exhaustion_is_discardable(tmp_path) -> None:
    loader = ResourceLoader(user_resource_roots=())

    async def scenario():
        try:
            with pytest.raises(CatalogPreviewTaskError, match="work_budget_exceeded"):
                await _request(loader, tmp_path, units=1)
            assert loader._catalog_authority_selected is False
            assert loader._legacy_authority_selected is False
            assert len(await _request(loader, tmp_path)) == 64
        finally:
            await loader.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("domain", ("subject", "policy"))
def test_resource_background_jobs_do_not_cross_isolation_domains(tmp_path, monkeypatch, domain) -> None:
    loader = ResourceLoader(user_resource_roots=())
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered, released = threading.Event(), threading.Event()
    counter_lock = threading.Lock()
    calls = 0

    def compute(*args, **kwargs):
        nonlocal calls
        with counter_lock:
            calls += 1
            if calls == 2:
                entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        first = asyncio.create_task(_request(loader, tmp_path))
        second = asyncio.create_task(_request(loader, tmp_path, **{domain: "c" * 64}))
        try:
            await _entered(entered)
            assert calls == 2
            released.set()
            assert await first == await second
        finally:
            released.set()
            await loader.aclose()
            await asyncio.gather(first, second, return_exceptions=True)

    asyncio.run(scenario())


def test_resource_background_result_rejects_configuration_changed_during_scan(tmp_path, monkeypatch) -> None:
    loader = ResourceLoader(user_resource_roots=())
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered, released = threading.Event(), threading.Event()

    def compute(*args, **kwargs):
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiter = asyncio.create_task(_request(loader, tmp_path))
        try:
            await _entered(entered)
            loader.set_runtime_options(no_skills=True)
            released.set()
            with pytest.raises(ResourceLoaderCompatibilityError, match="catalog_preview_stale"):
                await waiter
        finally:
            released.set()
            await loader.aclose()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(scenario())


def test_failed_native_submission_does_not_admit_queued_source_reads(tmp_path, monkeypatch) -> None:
    from loushang.harness.resources import _catalog_preview_tasks as tasks

    loader = ResourceLoader(user_resource_roots=())
    accepted = []
    original_executor = tasks._EXECUTOR
    monkeypatch.setattr(tasks, "_SUBMISSION_FENCED", threading.Event())

    class LostSubmissionReceipt:
        def submit(self, operation, **kwargs):
            accepted.append(original_executor.submit(operation, **kwargs))
            raise RuntimeError("receipt lost after enqueue")

    def forbidden_read(*args, **kwargs):
        pytest.fail("failed native submission admitted source reads")

    monkeypatch.setattr(tasks, "_EXECUTOR", LostSubmissionReceipt())
    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(forbidden_read))

    async def scenario():
        try:
            with pytest.raises(RuntimeError, match="receipt lost after enqueue"):
                await _request(loader, tmp_path)
            with pytest.raises(CatalogPreviewTaskError, match="scheduler_unavailable"):
                await _request(loader, tmp_path)
        finally:
            await loader.aclose()

    asyncio.run(scenario())
    assert len(accepted) == 1
    assert accepted[0].result(timeout=5) is None


def test_priority_dispatch_unknown_submission_preserves_an_admitted_peer(tmp_path, monkeypatch) -> None:
    from loushang.harness.resources import _catalog_preview_tasks as tasks
    from loushang.harness.resources._catalog_preview_scheduler import (
        CatalogPreviewExecutor,
    )

    scheduler = CatalogPreviewExecutor()
    executor = scheduler._executor
    accepted = []
    entered = [threading.Event(), threading.Event()]
    released = threading.Event()
    loader = ResourceLoader(user_resource_roots=())
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    roots = {name: tmp_path / name for name in ("blocker0", "blocker1", "peer", "unknown")}
    for root in roots.values():
        root.mkdir()

    class LostFourthDispatchReceipt:
        def submit(self, operation):
            future = executor.submit(operation)
            accepted.append(future)
            if len(accepted) == 4:
                raise RuntimeError("dispatch receipt lost after enqueue")
            return future

    def compute(state, cwd, **kwargs):
        if cwd.name == "unknown":
            pytest.fail("unknown submission admitted source reads")
        if cwd.name.startswith("blocker"):
            entered[int(cwd.name[-1])].set()
            assert released.wait(5)
        return original(state, cwd, **kwargs)

    monkeypatch.setattr(scheduler, "_executor", LostFourthDispatchReceipt())
    monkeypatch.setattr(tasks, "_EXECUTOR", scheduler)
    monkeypatch.setattr(tasks, "_SUBMISSION_FENCED", threading.Event())
    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiters = [asyncio.create_task(_request(loader, roots[f"blocker{i}"])) for i in range(2)]
        try:
            for event in entered:
                await _entered(event)
            peer = asyncio.create_task(_request(loader, roots["peer"]))
            waiters.append(peer)
            await asyncio.sleep(0)
            with pytest.raises(RuntimeError, match="dispatch receipt lost"):
                await _request(loader, roots["unknown"], priority="foreground")
            assert len(loader._catalog_preview_tasks._jobs) == 3
            released.set()
            assert len(await peer) == 64
        finally:
            released.set()
            await loader.aclose()
            await asyncio.gather(*waiters, return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)
    assert len(accepted) == 4
    assert all(future.result(timeout=5) is None for future in accepted)


def test_process_preview_capacity_rejects_extra_work_without_changing_peers(tmp_path, monkeypatch) -> None:
    loader = ResourceLoader(user_resource_roots=())
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    entered, released = threading.Event(), threading.Event()

    def compute(*args, **kwargs):
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiters = [asyncio.create_task(_request(loader, tmp_path, policy=f"{index:064x}")) for index in range(6)]
        try:
            await _entered(entered)
            with pytest.raises(CatalogPreviewTaskError, match="background_capacity_exceeded"):
                await _request(loader, tmp_path, policy=f"{8:064x}")
            waiters.extend(asyncio.create_task(_request(
                loader, tmp_path, policy=f"{index:064x}", priority="foreground",
            )) for index in (6, 7))
            await asyncio.sleep(0)
            assert len(loader._catalog_preview_tasks._jobs) == 8
            with pytest.raises(CatalogPreviewTaskError, match="capacity_exceeded"):
                await _request(loader, tmp_path, policy=f"{8:064x}", priority="foreground")
            released.set()
            fingerprints = await asyncio.gather(*waiters)
            assert len(set(fingerprints)) == 1
        finally:
            released.set()
            await loader.aclose()
            await asyncio.gather(*waiters, return_exceptions=True)

    asyncio.run(scenario())


def test_background_read_pin_survives_mount_retirement_and_closes_at_native_completion(tmp_path, monkeypatch) -> None:
    from loushang.harness.resources.packages.mounts import PackageResourceMount
    from loushang.harness.resources.plugins.manifest import PluginManifestParser
    from loushang.harness.resources.plugins.revisions import PluginRevisionStore

    source = tmp_path / "source"
    prompts = source / "resources" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "review.md").write_text("review", encoding="utf-8")
    (source / "plugin.json").write_text('{"name":"review-pack","packageRoot":"resources"}', encoding="utf-8")
    published = PluginRevisionStore(tmp_path / "revisions").publish(PluginManifestParser().parse(source))
    handle = published.revision_handle
    assert handle is not None
    loader = ResourceLoader(user_resource_roots=())
    loader.set_package_mounts((PackageResourceMount(
        root=published.package_root, content_digest=published.content_digest,
        revision_handle=handle,
    ),))
    pins = []
    original_acquire = handle.acquire_readonly_capture

    def acquire():
        pin = original_acquire()
        pins.append(pin)
        return pin

    monkeypatch.setattr(handle, "acquire_readonly_capture", acquire)
    original_compute = ResourceLoader._compute_catalog_input_receipt_from_state
    entered, released = threading.Event(), threading.Event()

    def compute(*args, **kwargs):
        entered.set()
        assert released.wait(5)
        return original_compute(*args, **kwargs)

    monkeypatch.setattr(ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute))

    async def scenario():
        waiter = asyncio.create_task(_request(loader, tmp_path))
        try:
            await _entered(entered)
            assert len(pins) == 1
            loader.set_package_mounts(())
            assert handle.closed is True
            assert pins[0].closed is False
            released.set()
            with pytest.raises(ResourceLoaderCompatibilityError, match="catalog_preview_stale"):
                await waiter
            assert pins[0].closed is True
        finally:
            released.set()
            await loader.aclose()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(scenario())
