from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from loushang.coding.composition_provenance import CodingCompositionProvenanceV1
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    prepare_coding_activation_attempt_record,
)
from loushang.coding.resume_activation_plan import (
    ActivationOwnerInputRefV1,
    ActivationOwnerSelectionRefV1,
    ResumePlanStaleError,
    build_session_activation_plan,
    plan_coding_resume,
    plan_coding_resume_async,
    require_current_resume_plan_inputs,
    require_current_resume_plan_source,
)
from loushang.coding.resume_binding import project_coding_runtime_binding_path
from loushang.coding.resume_history import (
    CodingResumeHeaderPreview,
    CodingResumeHistoryPreview,
    read_coding_resume_snapshot,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.conversation import ConversationHeader
from loushang.harness.resources.loader import (
    ResourceLoader,
    ResourceLoaderCompatibilityError,
)


def _history() -> CodingResumeHistoryPreview:
    current = resolve_coding_composition_set("coding-standard")
    return CodingResumeHistoryPreview(
        header_preview=CodingResumeHeaderPreview(
            header=ConversationHeader(
                conversation_id="session-1", version=1,
                created_at="2026-10-12T00:00:00Z",
            ),
            product_identity="coding",
            composition=CodingCompositionProvenanceV1(
                current.set_id, current.fingerprint,
            ),
        ),
        records=(), selected_records=(), selected_leaf_id=None,
        startup=None, provenance_conflict=False,
        binding_status="none", binding=None,
        selected_ancestry_digest=project_coding_runtime_binding_path(
            (), current_session_id="session-1",
        ).ancestry_digest,
        source_fingerprint="stat-v1:1:2:3:4:5",
        source_content_digest="a" * 64,
    )


def test_activation_plan_is_deterministic_and_stale_on_source_or_branch_change() -> None:
    history = _history()
    selection = ActivationOwnerSelectionRefV1(
        owner_id="resources.catalog", fingerprint="b" * 64,
        generation="generation-1",
    )
    current = resolve_coding_composition_set("coding-standard")
    first = build_session_activation_plan(
        history, current, workspace_root=Path("/workspace"),
        owner_selections=(selection,),
    )
    second = build_session_activation_plan(
        history, current, workspace_root=Path("/workspace"),
        owner_selections=(selection,),
    )

    assert first == second
    assert len(first.plan_id) == 64
    assert first.status == "needs_final_validation"
    assert first.composition_comparison.status == "same"
    require_current_resume_plan_source(first, history)
    for changed in (
        replace(history, source_fingerprint="stat-v1:changed"),
        replace(history, selected_leaf_id="another-leaf"),
        replace(history, selected_ancestry_digest="c" * 64),
        replace(history, source_content_digest="b" * 64),
    ):
        with pytest.raises(ResumePlanStaleError):
            require_current_resume_plan_source(first, changed)
    assert build_session_activation_plan(
        history, current, workspace_root=Path("/workspace"),
        owner_selections=(replace(selection, fingerprint="c" * 64),),
    ).plan_id != first.plan_id
    assert build_session_activation_plan(
        replace(history, source_content_digest="b" * 64), current,
        workspace_root=Path("/workspace"), owner_selections=(selection,),
    ).plan_id != first.plan_id


def test_activation_plan_cannot_treat_unknown_history_as_ready() -> None:
    history = replace(_history(), binding_status="unknown_version")
    plan = build_session_activation_plan(
        history, resolve_coding_composition_set("coding-standard"),
        workspace_root=Path("/workspace"),
    )
    assert plan.status == "unavailable"
    assert plan.composition_comparison.reason_codes == (
        "history.binding_unknown_version",
    )
    future_attempt = build_session_activation_plan(
        replace(_history(), activation_status="unknown_version"),
        resolve_coding_composition_set("coding-standard"),
        workspace_root=Path("/workspace"),
    )
    assert future_attempt.status == "unavailable"
    assert future_attempt.composition_comparison.reason_codes == (
        "history.activation_unknown_version",
    )


def test_unbound_durable_attempt_remains_readable_but_plan_is_unavailable(
    tmp_path: Path,
) -> None:
    async def create() -> Path:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path, cwd=str(tmp_path),
            composition_set="coding-standard", defer_materialization=False,
        )
        try:
            ancestry = project_coding_runtime_binding_path(
                manager._transcript.active_path(),
                current_session_id=manager.header.conversation_id,
            ).ancestry_digest
            attempt = CodingActivationAttemptV1(
                attempt_id="attempt-1", request_id="input-1",
                session_id=manager.header.conversation_id,
                original_leaf_id=None, ancestry_digest=ancestry,
                plan_fingerprint="a" * 64, epoch_fingerprint="b" * 64,
                subject_digest="c" * 64,
            )
            record = prepare_coding_activation_attempt_record(
                attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
            )
            await manager.commit_prebuilt_extension_data(record)
            assert manager.session_file is not None
            return manager.session_file
        finally:
            await manager.dispose_runtime_profile()

    path = asyncio.run(create())
    history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    assert history.activation_status == "pending"
    assert history.pending_activation_record_id == "attempt-1"
    plan = build_session_activation_plan(
        history, resolve_coding_composition_set("coding-standard"),
        workspace_root=tmp_path,
    )
    assert plan.status == "unavailable"
    assert plan.composition_comparison.reason_codes == (
        "history.activation_pending",
    )


def test_activation_plan_rejects_noncanonical_or_duplicate_owner_inputs() -> None:
    history = _history()
    current = resolve_coding_composition_set("coding-standard")
    selection = ActivationOwnerSelectionRefV1(
        owner_id="resources.catalog", fingerprint="b" * 64,
        generation="generation-1",
    )
    with pytest.raises(ValueError, match="sorted and unique"):
        build_session_activation_plan(
            history, current, workspace_root=Path("/workspace"),
            owner_selections=(selection, selection),
        )
    with pytest.raises(ValueError, match="canonical absolute"):
        build_session_activation_plan(
            history, current, workspace_root=Path("workspace"),
        )
    with pytest.raises(ValueError, match="fingerprint"):
        replace(selection, fingerprint="raw-secret")
    with pytest.raises(ValueError, match="source fingerprint"):
        build_session_activation_plan(
            replace(history, source_fingerprint="raw-secret"), current,
            workspace_root=Path("/workspace"),
        )


def test_activation_plan_rejects_rewritten_real_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding import resume_history as resume_history_module

    async def create() -> Path:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path, cwd=str(tmp_path),
            composition_set="coding-standard", defer_materialization=False,
        )
        try:
            assert manager.session_file is not None
            return manager.session_file
        finally:
            await manager.dispose_runtime_profile()

    path = asyncio.run(create())
    monkeypatch.setattr(
        resume_history_module, "session_file_authority_fingerprint",
        lambda _path: "stat-v1:1:2:3:4:5",
    )
    current = resolve_coding_composition_set("coding-standard")
    original = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    plan = build_session_activation_plan(
        original, current, workspace_root=tmp_path,
    )
    assert plan.status == "needs_final_validation"
    with path.open("ab") as stream:
        stream.write(b"\n")
    revised = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    assert revised.source_fingerprint == original.source_fingerprint
    assert revised.source_content_digest != original.source_content_digest
    assert revised.selected_ancestry_digest == original.selected_ancestry_digest
    with pytest.raises(ResumePlanStaleError):
        require_current_resume_plan_source(plan, revised)


def test_activation_plan_references_resource_owner_input_without_retaining_receipt(
    tmp_path: Path,
) -> None:
    loader = ResourceLoader(user_resource_roots=())
    context = tmp_path / "AGENTS.md"
    context.write_text("AAAA", encoding="utf-8")
    first_receipt = loader.preview_catalog_input_receipt(tmp_path)
    first_ref = ActivationOwnerInputRefV1(
        "resources.catalog", first_receipt.input_fingerprint,
    )
    current = resolve_coding_composition_set("coding-standard")
    first = build_session_activation_plan(
        _history(), current, workspace_root=tmp_path,
        owner_inputs=(first_ref,),
    )

    context.write_text("BBBB", encoding="utf-8")
    next_receipt = loader.preview_catalog_input_receipt(tmp_path)
    next_ref = ActivationOwnerInputRefV1(
        "resources.catalog", next_receipt.input_fingerprint,
    )
    changed = build_session_activation_plan(
        _history(), current, workspace_root=tmp_path,
        owner_inputs=(next_ref,),
    )
    assert first.plan_id != changed.plan_id
    assert first_receipt.context_content_complete
    assert next_receipt.context_content_complete
    assert first.owner_inputs == (first_ref,)
    assert "ResourceCatalogInputReceipt" not in repr(first)
    require_current_resume_plan_inputs(first, (first_ref,))
    with pytest.raises(ResumePlanStaleError, match="owner inputs changed"):
        require_current_resume_plan_inputs(first, (next_ref,))
    with pytest.raises(ResumePlanStaleError, match="owner inputs changed"):
        require_current_resume_plan_inputs(first, ())
    with pytest.raises(ResumePlanStaleError, match="owner inputs changed"):
        require_current_resume_plan_inputs(changed, (first_ref,))


def test_readonly_snapshot_and_pure_plan_have_no_authority_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def create() -> Path:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path, cwd=str(tmp_path),
            composition_set="coding-standard", defer_materialization=False,
        )
        try:
            assert manager.session_file is not None
            return manager.session_file
        finally:
            await manager.dispose_runtime_profile()

    path = asyncio.run(create())
    loader = ResourceLoader(user_resource_roots=())
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()}
    original_open = os.open

    def deny_effect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read-only Resume attempted an authority effect")

    def guarded_os_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            deny_effect()
        return original_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(importlib, "import_module", deny_effect)
        context.setattr(subprocess, "Popen", deny_effect)
        context.setattr(asyncio, "create_subprocess_exec", deny_effect)
        context.setattr(os, "open", guarded_os_open)
        context.setattr(Path, "write_bytes", deny_effect)
        context.setattr(Path, "write_text", deny_effect)
        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        plan = plan_coding_resume(
            history, resolve_coding_composition_set("coding-standard"),
            workspace_root=tmp_path, resource_loader=loader,
        )

    assert plan.status == "needs_final_validation"
    assert tuple(item.owner_id for item in plan.owner_inputs) == ("resources.catalog",)
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()} == before


def test_resume_plan_entry_tracks_resource_edits_and_drops_borrowed_receipts(tmp_path) -> None:
    loader = ResourceLoader(user_resource_roots=())
    context = tmp_path / "AGENTS.md"
    context.write_text("before", encoding="utf-8")
    current = resolve_coding_composition_set("coding-standard")
    first = plan_coding_resume(
        _history(), current, workspace_root=tmp_path, resource_loader=loader,
    )
    context.write_text("after", encoding="utf-8")
    second = plan_coding_resume(
        _history(), current, workspace_root=tmp_path, resource_loader=loader,
    )
    assert first.plan_id != second.plan_id
    assert first.owner_inputs != second.owner_inputs
    assert "ResourceCatalogInputReceipt" not in repr(second)
    with pytest.raises(ResumePlanStaleError, match="owner inputs changed"):
        require_current_resume_plan_inputs(first, second.owner_inputs)


def test_unavailable_history_does_not_request_resource_planning(tmp_path, monkeypatch) -> None:
    loader = ResourceLoader(user_resource_roots=())

    def forbidden_preview(*args, **kwargs):
        pytest.fail("unavailable Resume requested resource planning")

    monkeypatch.setattr(loader, "preview_catalog_input_receipt", forbidden_preview)
    plan = plan_coding_resume(
        replace(_history(), activation_status="unknown_version"),
        resolve_coding_composition_set("coding-standard"),
        workspace_root=tmp_path, resource_loader=loader,
    )
    assert plan.status == "unavailable"
    assert plan.owner_inputs == ()


def test_resume_plan_propagates_cancellation_without_delivering_a_plan(tmp_path) -> None:
    from concurrent.futures import CancelledError

    loader = ResourceLoader(user_resource_roots=())

    def cancelled():
        raise CancelledError("Session released its planning reference")

    with pytest.raises(CancelledError):
        plan_coding_resume(
            _history(), resolve_coding_composition_set("coding-standard"),
            workspace_root=tmp_path, resource_loader=loader, work_probe=cancelled,
        )
    # Cancellation leaves the original Resource owner usable for re-planning.
    assert plan_coding_resume(
        _history(), resolve_coding_composition_set("coding-standard"),
        workspace_root=tmp_path, resource_loader=loader,
    ).status == "needs_final_validation"


def _async_plan(loader, root, *, history=None, subject="a" * 64, policy="b" * 64, priority="background"):
    return plan_coding_resume_async(
        _history() if history is None else history,
        resolve_coding_composition_set("coding-standard"),
        workspace_root=root, resource_loader=loader,
        subject_digest=subject, policy_digest=policy,
        max_work_units=4096, time_budget_seconds=30,
        priority=priority,
    )


def test_async_resume_plan_uses_original_facts_and_tracks_security_inputs(tmp_path) -> None:
    loader = ResourceLoader(user_resource_roots=())
    (tmp_path / "AGENTS.md").write_text("current context", encoding="utf-8")
    sync_plan = plan_coding_resume(
        _history(), resolve_coding_composition_set("coding-standard"),
        workspace_root=tmp_path, resource_loader=loader,
    )

    async def scenario():
        try:
            first = await _async_plan(loader, tmp_path)
            expected = build_session_activation_plan(
                _history(), resolve_coding_composition_set("coding-standard"),
                workspace_root=tmp_path,
                owner_inputs=(
                    ActivationOwnerInputRefV1("coding.policy", "b" * 64),
                    ActivationOwnerInputRefV1("coding.subject", "a" * 64),
                    *sync_plan.owner_inputs,
                ),
            )
            assert first == expected
            assert await _async_plan(loader, tmp_path, priority="foreground") == first
            assert first.owner_selections == ()
            changed_policy = await _async_plan(loader, tmp_path, policy="c" * 64)
            changed_subject = await _async_plan(loader, tmp_path, subject="c" * 64)
            for changed in (changed_policy, changed_subject):
                assert changed.plan_id != first.plan_id
                with pytest.raises(ResumePlanStaleError, match="owner inputs changed"):
                    require_current_resume_plan_inputs(first, changed.owner_inputs)
            assert loader._catalog_authority_selected is False
            assert loader._legacy_authority_selected is False
        finally:
            await loader.aclose()

    asyncio.run(scenario())


def test_unavailable_async_resume_does_not_start_native_work(tmp_path, monkeypatch) -> None:
    loader = ResourceLoader(user_resource_roots=())

    async def forbidden(*args, **kwargs):
        pytest.fail("unavailable history started native Resource work")

    monkeypatch.setattr(loader, "preview_catalog_input_fingerprint", forbidden)
    plan = asyncio.run(_async_plan(
        loader, tmp_path, history=replace(_history(), activation_status="pending"),
    ))
    assert plan.status == "unavailable"
    assert tuple(item.owner_id for item in plan.owner_inputs) == ("coding.policy", "coding.subject")
    assert loader._catalog_preview_tasks is None


@pytest.mark.parametrize("separate_owner", [False, True])
def test_completed_background_plan_rechecks_same_stat_context_content(tmp_path, separate_owner) -> None:
    background = ResourceLoader(user_resource_roots=())
    foreground = ResourceLoader(user_resource_roots=()) if separate_owner else background
    context = tmp_path / "AGENTS.md"
    context.write_text("context before", encoding="utf-8")
    original_stat = context.stat()

    async def scenario():
        try:
            first = await _async_plan(background, tmp_path)
            # A completed job's configuration key contains no context bytes.
            # Matching inode/size/mtime therefore cannot justify reusing it.
            context.write_text("context after!", encoding="utf-8")
            os.utime(context, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            changed_stat = context.stat()
            assert (
                changed_stat.st_dev, changed_stat.st_ino,
                changed_stat.st_size, changed_stat.st_mtime_ns,
            ) == (
                original_stat.st_dev, original_stat.st_ino,
                original_stat.st_size, original_stat.st_mtime_ns,
            )
            second = await _async_plan(foreground, tmp_path, priority="foreground")
            assert first.plan_id != second.plan_id
            assert first.owner_inputs != second.owner_inputs
            current = foreground.preview_catalog_input_receipt(tmp_path).input_fingerprint
            assert ActivationOwnerInputRefV1("resources.catalog", current) in second.owner_inputs
            with pytest.raises(ResumePlanStaleError, match="owner inputs changed"):
                require_current_resume_plan_inputs(first, second.owner_inputs)
            assert await _async_plan(foreground, tmp_path, priority="foreground") == second
            assert first.owner_selections == second.owner_selections == ()
            for loader in (background, foreground):
                assert not loader._catalog_authority_selected
                assert not loader._legacy_authority_selected
        finally:
            await background.aclose()
            if separate_owner:
                await foreground.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("async_close", [False, True])
def test_async_resume_cancelled_view_does_not_fence_peer_planning(tmp_path, monkeypatch, async_close) -> None:
    loader = ResourceLoader(user_resource_roots=())
    first_view = loader.create_catalog_session_view()
    peer_view = loader.create_catalog_session_view()
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
        first = asyncio.create_task(_async_plan(first_view, tmp_path))
        peer = asyncio.create_task(_async_plan(peer_view, tmp_path))
        try:
            async with asyncio.timeout(5):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            if async_close:
                await first_view.aclose()
            else:
                first_view.close()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert not first_view._catalog_preview_waiters
            with pytest.raises(ResourceLoaderCompatibilityError, match="catalog_preview_view_closed"):
                await _async_plan(first_view, tmp_path)
            assert not peer.done()
            assert calls == 1
            released.set()
            assert (await peer).status == "needs_final_validation"
            # Closing one projection must not close the shared task scope.
            assert (await _async_plan(peer_view, tmp_path)).status == "needs_final_validation"
        finally:
            released.set()
            first.cancel()
            peer.cancel()
            await loader.aclose()
            await asyncio.gather(first, peer, return_exceptions=True)

    asyncio.run(scenario())


def test_async_resume_validates_inputs_before_native_work(tmp_path) -> None:
    loader = ResourceLoader(user_resource_roots=())
    for root, subject in ((Path("relative"), "a" * 64), (tmp_path, "raw-subject")):
        with pytest.raises(ValueError):
            asyncio.run(_async_plan(loader, root, subject=subject))
    assert loader._catalog_preview_tasks is None
