from __future__ import annotations

import asyncio

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resume_activation_plan import plan_coding_resume_async
from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime
from loushang.coding.session_manager import SessionManager
from loushang.harness.resources.loader import ResourceLoader


async def _root(tmp_path):
    original = await SessionManager.new(
        session_dir=tmp_path / "sessions",
        cwd=str(tmp_path),
        defer_materialization=False,
    )
    await original.append_message(
        UserMessage(role="user", content="saved", timestamp=1.0)
    )
    path = original.session_file
    await original.dispose_runtime_profile()
    assert path is not None

    def forbidden(*args, **kwargs):
        pytest.fail("pure planning constructed an Agent/Runtime")

    root = AgentSessionRuntime(
        session_dir=tmp_path / "sessions", session_factory=forbidden
    )
    history = await root.preview_resume_history(path)
    loader = ResourceLoader(user_resource_roots=())
    return root, history, loader, path


def _inputs(tmp_path, loader, **changes):
    return {
        "workspace_root": tmp_path,
        "resource_loader": loader,
        "subject_digest": "a" * 64,
        "policy_digest": "b" * 64,
        "max_work_units": 200,
        "time_budget_seconds": 5.0,
        **changes,
    }


async def _completed(root):
    task = root._resume_planning._task
    if task is not None:
        await asyncio.shield(task)
        await asyncio.sleep(0)  # Deliver the exact task's completion callback.


def _files(tmp_path):
    return {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }


def test_runtime_background_plan_reuses_only_with_fresh_resource_owner_inputs(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    (tmp_path / "AGENTS.md").write_text("original instructions")

    async def scenario():
        root, history, loader, path = await _root(tmp_path)
        current = resolve_coding_composition_set("coding-standard")
        request = _inputs(tmp_path, loader)
        before = _files(tmp_path)
        try:
            await root.start_resume_planning(history, current, **request)
            await _completed(root)
            fresh = await plan_coding_resume_async(
                history, current, priority="foreground", **request
            )
            cached = root.current_resume_plan(
                history, current_owner_inputs=fresh.owner_inputs
            )
            assert cached == fresh
            assert cached is root.current_resume_plan(
                history, current_owner_inputs=fresh.owner_inputs
            )
            assert root.current_session is None
            assert root._owned_transcript_factory is None
            assert _files(tmp_path) == before
            (tmp_path / "AGENTS.md").write_text("changed instructions")
            changed = await plan_coding_resume_async(
                history, current, priority="foreground", **request
            )
            assert (
                root.current_resume_plan(
                    history, current_owner_inputs=changed.owner_inputs
                )
                is None
            )
            await root.start_resume_planning(history, current, **request)
            await _completed(root)
            assert (
                root.current_resume_plan(
                    history, current_owner_inputs=changed.owner_inputs
                )
                == changed
            )
        finally:
            await root.dispose_session_runtime()
            await loader.aclose()

    asyncio.run(scenario())


def test_configured_background_plan_starts_from_history_preview_inputs(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        root, history, loader, path = await _root(tmp_path)
        try:
            root.configure_resume_planning(
                current_composition=resolve_coding_composition_set("coding-standard"),
                workspace_root=tmp_path,
                resource_loader=loader,
                subject_digest=lambda: "a" * 64,
                policy_digest=lambda: "b" * 64,
            )
            assert await root.start_configured_resume_planning(history)
            await _completed(root)
            fresh = await plan_coding_resume_async(
                history,
                resolve_coding_composition_set("coding-standard"),
                priority="foreground",
                **_inputs(tmp_path, loader),
            )
            cached = root.current_resume_plan(
                history, current_owner_inputs=fresh.owner_inputs
            )
            assert cached == fresh
            assert await root.prepare_configured_resume_plan(history) is cached
            (tmp_path / "AGENTS.md").write_text("changed instructions")
            changed = await root.prepare_configured_resume_plan(history)
            assert changed != cached
            assert changed.owner_inputs != cached.owner_inputs
            assert root.current_resume_plan(
                history, current_owner_inputs=changed.owner_inputs
            ) is None
        finally:
            await root.dispose_session_runtime()
            await loader.aclose()

    asyncio.run(scenario())


def test_runtime_changed_history_invalidates_completed_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        root, history, loader, path = await _root(tmp_path)
        current = resolve_coding_composition_set("coding-standard")
        request = _inputs(tmp_path, loader)
        try:
            await root.start_resume_planning(history, current, **request)
            await _completed(root)
            fresh = await plan_coding_resume_async(
                history, current, priority="foreground", **request
            )
            writer = await SessionManager.load(path)
            try:
                await writer.append_message(
                    UserMessage(role="user", content="external change", timestamp=2.0)
                )
            finally:
                await writer.dispose_runtime_profile()
            changed = await root.preview_resume_history(path)
            assert (
                root.current_resume_plan(
                    changed, current_owner_inputs=fresh.owner_inputs
                )
                is None
            )
        finally:
            await root.dispose_session_runtime()
            await loader.aclose()

    asyncio.run(scenario())


def test_duplicate_background_requests_share_one_slot_and_close_releases_waiter(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        root, history, loader, path = await _root(tmp_path)
        current = resolve_coding_composition_set("coding-standard")
        request = _inputs(tmp_path, loader)
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()
        calls = 0
        preview = loader.preview_catalog_input_fingerprint

        async def held(*args, **kwargs):
            nonlocal calls
            calls += 1
            entered.set()
            try:
                await release.wait()
                return await preview(*args, **kwargs)
            finally:
                cancelled.set()

        before = _files(tmp_path)
        try:
            with monkeypatch.context() as scope:
                scope.setattr(loader, "preview_catalog_input_fingerprint", held)
                await asyncio.gather(
                    *(
                        root.start_resume_planning(history, current, **request)
                        for _ in range(8)
                    )
                )
                await entered.wait()
                assert calls == 1
                await root.dispose_session_runtime()
                assert cancelled.is_set()
                assert root._resume_planning._task is None
                assert root._resume_planning._plan is None
            # Runtime released its waiter, without closing the shared Resource owner.
            fresh = await plan_coding_resume_async(
                history, current, priority="foreground", **request
            )
            assert fresh.status == "needs_final_validation"
            assert (
                root.current_resume_plan(
                    history, current_owner_inputs=fresh.owner_inputs
                )
                is None
            )
            with pytest.raises(RuntimeError, match="planning_unavailable"):
                await root.start_resume_planning(history, current, **request)
            assert _files(tmp_path) == before
        finally:
            release.set()
            await root.dispose_session_runtime()
            await loader.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"subject_digest": "wrong"},
        {"max_work_units": 0},
        {"time_budget_seconds": float("nan")},
        {"time_budget_seconds": 61},
    ],
)
def test_invalid_planning_request_schedules_no_work(tmp_path, monkeypatch, change):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        root, history, loader, path = await _root(tmp_path)
        try:
            with pytest.raises(ValueError):
                await root.start_resume_planning(
                    history,
                    resolve_coding_composition_set("coding-standard"),
                    **_inputs(tmp_path, loader, **change),
                )
            assert root._resume_planning._task is None
            assert root.current_session is None
        finally:
            await root.dispose_session_runtime()
            await loader.aclose()

    asyncio.run(scenario())


def test_changed_subject_cancels_previous_waiter_before_replanning(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        root, history, loader, path = await _root(tmp_path)
        current = resolve_coding_composition_set("coding-standard")
        entered = asyncio.Event()
        released = asyncio.Event()
        preview = loader.preview_catalog_input_fingerprint
        calls = 0

        async def held(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    released.set()
            return await preview(*args, **kwargs)

        try:
            monkeypatch.setattr(loader, "preview_catalog_input_fingerprint", held)
            await root.start_resume_planning(history, current, **_inputs(tmp_path, loader))
            await entered.wait()
            previous = root._resume_planning._task
            changed = _inputs(tmp_path, loader, subject_digest="c" * 64)
            await root.start_resume_planning(history, current, **changed)
            assert released.is_set()
            assert previous is not None and previous.cancelled()
            await _completed(root)
            fresh = await plan_coding_resume_async(
                history, current, priority="foreground", **changed
            )
            assert root.current_resume_plan(
                history, current_owner_inputs=fresh.owner_inputs
            ) == fresh
            assert root.current_session is None
        finally:
            await root.dispose_session_runtime()
            await loader.aclose()

    asyncio.run(scenario())


def test_planning_cleanup_failure_still_drains_history_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        root, history, loader, path = await _root(tmp_path)
        drain = root._drain_resume_history_reads
        drained = False

        async def failed_close():
            raise RuntimeError("planning cleanup failed")

        async def observed_drain():
            nonlocal drained
            await drain()
            drained = True

        try:
            with monkeypatch.context() as scope:
                scope.setattr(root._resume_planning, "close", failed_close)
                scope.setattr(root, "_drain_resume_history_reads", observed_drain)
                with pytest.raises(RuntimeError, match="planning cleanup failed"):
                    await root.dispose_session_runtime()
                assert drained
        finally:
            await root.dispose_session_runtime()
            await loader.aclose()

    asyncio.run(scenario())
