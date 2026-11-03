from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.apphost import SessionCreateIntentV1, SessionCreateRequestV1
from loushang.appserver.protocol import SessionScopeV1
from loushang.coding.bootstrap import create_agent_session
from loushang.coding.composition_provenance import CODING_COMPOSITION_HEADER_KEY
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedCandidateBindingV1,
    CodingHostedCandidateValidatorV1,
    CodingHostedCatalogError,
    CodingHostedHistoryCandidateBindingV1,
    CodingHostedResumeCatalogV1,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.product_plan import CODING_CAPABILITY_PROFILE_METADATA_KEY
from loushang.coding.session_manager import SessionManager
from loushang.harness.transcript.jsonl_file import (
    load_agent_transcript_file,
    write_agent_transcript_export,
)


@pytest.mark.parametrize("delivery_fault", [
    "none", "source_changed",
    pytest.param("fenced", marks=pytest.mark.skipif(
        sys.platform != "linux", reason="Linux owned transcript fence",
    )),
])
def test_hosted_readonly_binding_preserves_selected_branch_and_delivery_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery_fault: str,
) -> None:
    from loushang.coding.appservice_adapter import CodingHostedSessionV1
    from loushang.harness.conversation import ConversationRecord
    from loushang.harness.transcript import AGENT_MESSAGE_KIND

    async def scenario() -> None:
        scope = _scope(tmp_path)
        scope.session_dir.mkdir(mode=0o700, exist_ok=True)
        catalog = CodingHostedSessionCatalogV1(
            (scope,), owned_transcripts=delivery_fault == "fenced",
        )
        candidate = await catalog.create_candidate(_intent(scope))
        await candidate.close()
        path = next(scope.session_dir.glob("*.jsonl"))
        header, _ = load_agent_transcript_file(path, read_only=True)

        def message(record_id: str, parent_id: str | None):
            return ConversationRecord(
                record_id=record_id, parent_id=parent_id, kind=AGENT_MESSAGE_KIND,
                payload_version=1, created_at=header.created_at,
                payload=UserMessage(role="user", content=record_id, timestamp=1.0),
            )

        write_agent_transcript_export(path, header, [
            message("root", None), message("left", "root"),
            message("right", "root"),
        ])
        before = path.read_bytes()
        rows = await catalog.list_identities((scope.discovery_scope,), limit=256)
        original_preview = catalog.preview_history_snapshot

        async def preview_with_delivery_fault(*args, **kwargs):
            history = await original_preview(*args, **kwargs)
            if delivery_fault == "source_changed":
                path.write_bytes(before + b"\n")
            elif delivery_fault == "fenced":
                catalog.fence()
            return history

        monkeypatch.setattr(catalog, "preview_history_snapshot", preview_with_delivery_fault)
        if delivery_fault != "none":
            with pytest.raises(CodingHostedCatalogError):
                await catalog.open_history_binding(
                    rows[0].reference, max_bytes=1024 * 1024, selected_leaf_id="left",
                )
            await catalog.close()
            return
        binding = await catalog.open_history_binding(
            rows[0].reference, max_bytes=1024 * 1024, selected_leaf_id="left",
        )
        hosted = CodingHostedSessionV1(binding)
        snapshot = await hosted.snapshot()
        assert [record.text for record in snapshot.records[:-1]] == ["root", "left"]
        assert binding.control is None
        assert path.read_bytes() == before
        # Delivered display is detached, rather than a live claim or lookup grant.
        catalog.fence()
        assert await hosted.snapshot() == snapshot
        await hosted.close()
        await catalog.close()

    asyncio.run(scenario())


def _scope(
    root: Path, scope: SessionScopeV1 = SessionScopeV1.CWD
) -> CodingHostedScopeV1:
    return CodingHostedScopeV1(scope, root / scope.value, root)


def _intent(scope: CodingHostedScopeV1) -> SessionCreateIntentV1:
    return SessionCreateIntentV1(
        SessionCreateRequestV1(
            "coding",
            scope.fingerprint,
            "a" * 32,
            requested_continuity_id="continuity-1",
            requested_scope=scope.discovery_scope,
        ),
        CODING_HOSTED_COMPATIBILITY_ID,
    )


@pytest.mark.skipif(sys.platform != "linux", reason="Linux owned transcript Writer")
def test_hosted_resume_catalog_transfers_history_and_original_writer_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        scope = _scope(tmp_path)
        scope.session_dir.mkdir(mode=0o700)
        catalog = CodingHostedSessionCatalogV1((scope,), owned_transcripts=True)
        routed = CodingHostedResumeCatalogV1(catalog)
        created = await routed.create_candidate(_intent(scope))
        created_claim = await created.claim()
        assert type(created_claim.opaque_binding) is CodingHostedCandidateBindingV1
        manager = created_claim.opaque_binding.take_manager()
        session = create_agent_session(session_manager=manager, no_tools=True)
        await session.prepare_model_call_runtime()
        await manager.append_message(
            UserMessage(role="user", content="history first", timestamp=1.0)
        )
        await session.dispose()
        await created_claim.close()
        await created.close()

        rows = await routed.list_identities((scope.discovery_scope,), limit=256)

        async def reject_writable_open(*args, **kwargs):
            raise AssertionError("Hosted Resume opened a Writer during history display")

        monkeypatch.setattr(catalog, "_open", reject_writable_open)
        candidate = await routed.open_candidate(rows[0].reference)
        claimed = await candidate.claim()
        opaque = claimed.opaque_binding
        assert type(opaque) is CodingHostedHistoryCandidateBindingV1
        source = opaque.take_resume_source()
        assert source.record.path == next(scope.session_dir.glob("*.jsonl"))
        assert [
            entry.payload.content
            for entry in source.history.selected_records
            if isinstance(entry.payload, UserMessage)
        ] == [
            "history first"
        ]
        assert source.writer_factory.owns_persistent_sessions
        assert issubclass(source.manager_type, SessionManager)
        source.require_current_source()
        await claimed.close()
        await candidate.close()
        await source.close()
        with pytest.raises(CodingHostedCatalogError):
            source.require_current_source()

    asyncio.run(scenario())


@pytest.mark.parametrize("scope_kind", [SessionScopeV1.CWD, SessionScopeV1.USER_HOME])
def test_G14_PRODUCT_canonical_transcript_create_and_fresh_owner_resume(
    tmp_path: Path, scope_kind: SessionScopeV1
) -> None:
    async def scenario() -> None:
        scope = _scope(tmp_path, scope_kind)
        owner = CodingHostedSessionCatalogV1((scope,))
        candidate = await owner.create_candidate(_intent(scope))
        identity = candidate.projection.envelope
        assert identity is not None
        assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1
        claimed = await candidate.claim()
        opened = await CodingHostedCandidateValidatorV1().open_product_candidate(
            claimed, identity
        )
        assert opened.binding_key.session_id == identity.session_id
        manager = claimed.opaque_binding.take_manager()
        await claimed.close()
        await candidate.close()
        session = create_agent_session(session_manager=manager, no_tools=True)
        try:
            await session.prepare_model_call_runtime()
            await manager.append_message(
                UserMessage(
                    role="user", content="persisted real transcript", timestamp=1.0
                )
            )
        finally:
            await session.dispose()
        await opened.close()

        fresh = CodingHostedSessionCatalogV1((scope,))
        projections = await fresh.list_identities((scope.discovery_scope,), limit=256)
        assert len(projections) == 1
        assert projections[0].envelope == identity
        resumed = await fresh.open_candidate(projections[0].reference)
        resumed_claim = await resumed.claim()
        reopened = resumed_claim.opaque_binding.take_manager()
        try:
            messages = reopened.build_session_context().messages
            assert messages and messages[0].role == "user"
            assert reopened.header.conversation_id == identity.session_id
        finally:
            await reopened.dispose_runtime_profile()
            await resumed_claim.close()
            await resumed.close()

    asyncio.run(scenario())


def test_G14_RECOVERY_create_identity_is_idempotent_across_catalog_instances(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scope = _scope(tmp_path)
        first = await CodingHostedSessionCatalogV1((scope,)).create_candidate(
            _intent(scope)
        )
        identity = first.projection.envelope
        await first.close()
        recovered = await CodingHostedSessionCatalogV1((scope,)).find_created_candidate(
            _intent(scope).request
        )
        assert recovered is not None
        assert recovered.projection.envelope == identity
        await recovered.close()
        repeated = await CodingHostedSessionCatalogV1((scope,)).create_candidate(
            _intent(scope)
        )
        assert repeated.projection.envelope == identity
        await repeated.close()
        assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1

    asyncio.run(scenario())


def test_canonical_hosted_history_previews_changed_environment_without_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Installed-evidence fixtures also import this module. Keep this optional
    # Resume dependency local to the regression that actually exercises it.
    from loushang.coding.resume_composition_comparison import (
        compare_coding_resume_composition,
    )

    async def scenario() -> None:
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        candidate = await owner.create_candidate(_intent(scope))
        await candidate.close()
        path = next(scope.session_dir.glob("*.jsonl"))
        header, records = load_agent_transcript_file(path, read_only=True)
        metadata = deepcopy(dict(header.metadata))
        metadata[CODING_COMPOSITION_HEADER_KEY] = {
            "version": 1,
            "setId": "retired-coding-set",
            "planFingerprint": "a" * 64,
        }
        capability = metadata[CODING_CAPABILITY_PROFILE_METADATA_KEY]
        assert isinstance(capability, dict)
        capability["capabilities"] = []
        write_agent_transcript_export(path, replace(header, metadata=metadata), records)
        before = path.read_bytes()

        fresh = CodingHostedSessionCatalogV1((scope,))
        rows = await fresh.list_identities((scope.discovery_scope,), limit=256)
        preview = await fresh.preview_history_header(rows[0].reference)
        assert preview.product_identity == "coding"
        assert preview.composition is not None
        assert preview.composition.set_id == "retired-coding-set"
        history = await fresh.preview_history_snapshot(
            rows[0].reference, max_bytes=1024 * 1024,
        )
        assert history.header_preview == preview
        assert history.records == ()
        comparison = compare_coding_resume_composition(
            history, resolve_coding_composition_set("coding-standard"),
        )
        assert comparison.status == "changed"
        assert comparison.difference_codes == ("composition.set_changed",)
        from loushang.coding.resume_input_lookup import CodingResumeInputLookupQueryV1

        model_observation = await fresh.preview_resume_model_outcome(
            rows[0].reference, CodingResumeInputLookupQueryV1("unknown-input", "a" * 64),
            max_bytes=1024 * 1024,
        )
        assert model_observation.status == "unknown"
        assert model_observation.invocation_id is None
        from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
        from loushang.coding.appservice_adapter import CodingHostedSessionV1

        async def reject_writable_open(*args, **kwargs):
            raise AssertionError("historical display acquired writable candidate")

        original_open = fresh._open
        monkeypatch.setattr(fresh, "_open", reject_writable_open)

        binding = await fresh.open_history_binding(
            rows[0].reference, max_bytes=1024 * 1024,
        )
        assert binding.control is None
        hosted = CodingHostedSessionV1(binding)
        snapshot = await hosted.snapshot()
        assert snapshot.identity.session_id == header.conversation_id
        assert snapshot.running is False
        assert snapshot.records[-1].kind.value == "status"
        with pytest.raises(AppServiceError) as unavailable:
            await hosted.start_turn("continue")
        assert unavailable.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
        for operation in (hosted.steer_turn, hosted.follow_up_turn):
            with pytest.raises(AppServiceError):
                operation("continue")
        assert hosted.interrupt_turn() is False
        await hosted.close()
        await hosted.close()
        with pytest.raises(RuntimeError, match="closed"):
            await hosted.snapshot()
        monkeypatch.setattr(fresh, "_open", original_open)
        reopened = await fresh.open_candidate(rows[0].reference)
        await reopened.close()
        assert path.read_bytes() == before

    asyncio.run(scenario())


def test_G14_PRODUCT_concurrent_same_key_creators_cannot_duplicate_sessions(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scope = _scope(tmp_path)
        candidates = await asyncio.gather(
            *(
                CodingHostedSessionCatalogV1((scope,)).create_candidate(_intent(scope))
                for _ in range(2)
            )
        )
        assert candidates[0].projection.envelope == candidates[1].projection.envelope
        for candidate in candidates:
            await candidate.close()
        assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_G14_PRODUCT_scope_and_create_identity_conflicts_fail_closed(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,))
        intent = _intent(scope)
        candidate = await owner.create_candidate(intent)
        await candidate.close()
        for request in (
            replace(intent.request, creator_scope_id="b" * 64),
            replace(intent.request, requested_continuity_id="another"),
            replace(intent.request, requested_scope=None),
        ):
            with pytest.raises(CodingHostedCatalogError):
                await owner.create_candidate(replace(intent, request=request))
        assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1

    asyncio.run(scenario())


def test_G14_PRODUCT_legacy_transcript_is_not_implicitly_adopted(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scope = _scope(tmp_path)
        manager = await SessionManager.new(
            session_dir=scope.session_dir,
            cwd=str(scope.cwd),
            defer_materialization=False,
        )
        await manager.dispose_runtime_profile()
        owner = CodingHostedSessionCatalogV1((scope,))
        assert await owner.list_identities((scope.discovery_scope,), limit=256) == ()

    asyncio.run(scenario())


def test_G14_PRODUCT_home_scope_is_global_but_execution_cwd_is_explicit(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        first_workspace = tmp_path / "first"
        next_workspace = tmp_path / "next"
        first_workspace.mkdir()
        next_workspace.mkdir()
        source = CodingHostedScopeV1(
            SessionScopeV1.USER_HOME, tmp_path / "global-sessions", first_workspace
        )
        target = replace(source, cwd=next_workspace)
        assert source.fingerprint == target.fingerprint
        candidate = await CodingHostedSessionCatalogV1((source,)).create_candidate(
            _intent(source)
        )
        identity = candidate.projection.envelope
        await candidate.close()
        fresh = CodingHostedSessionCatalogV1((target,))
        projections = await fresh.list_identities((target.discovery_scope,), limit=256)
        assert projections[0].envelope == identity
        resumed = await fresh.open_candidate(projections[0].reference)
        claimed = await resumed.claim()
        manager = claimed.opaque_binding.take_manager()
        try:
            assert manager.cwd == str(next_workspace)
            assert manager.header.metadata["cwd"] == str(first_workspace)
        finally:
            await manager.dispose_runtime_profile()
            await claimed.close()
            await resumed.close()

    asyncio.run(scenario())


def test_G14_PRODUCT_candidate_revision_is_fenced_before_claim(tmp_path: Path) -> None:
    async def scenario() -> None:
        scope = _scope(tmp_path)
        catalog = CodingHostedSessionCatalogV1((scope,))
        initial = await catalog.create_candidate(_intent(scope))
        await initial.close()
        projections = await catalog.list_identities((scope.discovery_scope,), limit=256)
        candidate = await catalog.open_candidate(projections[0].reference)
        path = next(scope.session_dir.glob("*.jsonl"))
        manager = await SessionManager.open(path)
        try:
            await manager.append_custom_entry("test.revision-bump/v1", {"version": 1})
        finally:
            await manager.dispose_runtime_profile()
        try:
            with pytest.raises(CodingHostedCatalogError):
                await catalog.preview_history_header(projections[0].reference)
            with pytest.raises(CodingHostedCatalogError):
                await catalog.preview_history_snapshot(
                    projections[0].reference, max_bytes=1024 * 1024,
                )
            from loushang.coding.resume_input_lookup import (
                CodingResumeInputLookupQueryV1,
            )

            with pytest.raises(CodingHostedCatalogError):
                await catalog.preview_resume_model_outcome(
                    projections[0].reference, CodingResumeInputLookupQueryV1("input-1", "a" * 64),
                    max_bytes=1024 * 1024,
                )
            with pytest.raises(CodingHostedCatalogError):
                await candidate.claim()
        finally:
            await candidate.close()

    asyncio.run(scenario())


def test_G14_PRODUCT_listing_another_scope_preserves_admitted_candidates(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        cwd_scope = _scope(tmp_path)
        home_scope = _scope(tmp_path, SessionScopeV1.USER_HOME)
        catalog = CodingHostedSessionCatalogV1((cwd_scope, home_scope))
        for scope in (cwd_scope, home_scope):
            candidate = await catalog.create_candidate(_intent(scope))
            await candidate.close()
        cwd_records = await catalog.list_identities(
            (cwd_scope.discovery_scope,), limit=256
        )
        home_records = await catalog.list_identities(
            (home_scope.discovery_scope,), limit=256
        )
        for projection in (*cwd_records, *home_records):
            candidate = await catalog.open_candidate(projection.reference)
            await candidate.close()
        # Repeated listings replace each scope's revisions, without growth.
        await catalog.list_identities((cwd_scope.discovery_scope,), limit=256)
        assert len(catalog._records) == 2

    asyncio.run(scenario())


def test_G14_PRODUCT_bound_restore_does_not_resolve_selected_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        scope = _scope(tmp_path)
        catalog = CodingHostedSessionCatalogV1((scope,))
        candidate = await catalog.create_candidate(_intent(scope))
        await candidate.close()
        projections = await catalog.list_identities((scope.discovery_scope,), limit=256)
        selected = next(scope.session_dir.glob("*.jsonl"))
        resolve = Path.resolve

        def guarded_resolve(path: Path, *args, **kwargs):
            assert path != selected, "bound candidate must retain its selected leaf"
            return resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", guarded_resolve)
        resumed = await catalog.open_candidate(projections[0].reference)
        await resumed.close()

    asyncio.run(scenario())
