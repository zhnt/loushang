from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.apphost import SessionCreateIntentV1, SessionCreateRequestV1
from loushang.appserver.protocol import SessionScopeV1
from loushang.coding.hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedCandidateValidatorV1,
    CodingHostedCatalogError,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.session_manager import SessionManager


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
        try:
            await manager.append_message(
                UserMessage(
                    role="user", content="persisted real transcript", timestamp=1.0
                )
            )
        finally:
            await manager.dispose_runtime_profile()
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
            await manager.append_message(
                UserMessage(role="user", content="changed", timestamp=1.0)
            )
        finally:
            await manager.dispose_runtime_profile()
        try:
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
