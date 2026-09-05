from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.apphost import (
    AppHostError,
    AppHostFailureCategory,
    CleanupIncompleteError,
    GenerationRetiredError,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCandidateStaleError,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.apphost._ownership import RetryableCloser
from loushang.apphost.integrations import harness_session as integration
from loushang.apphost.integrations.harness_session import (
    HarnessAppHostSessionAdapterV1,
    HarnessSessionScopeBindingV1,
)
from loushang.harness.conversation import ConversationHeader, ConversationRecord
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    AgentTranscriptDirectoryRuntime,
    SessionDiscoverySource,
    write_agent_transcript_export,
)


def _header(conversation_id: str) -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-09-05T00:00:00Z",
        metadata={"cwd": "/workspace/project"},
    )


def _record(record_id: str, text: str) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-09-05T00:00:01Z",
        payload=UserMessage(role="user", content=text, timestamp=1.0),
    )


def _runtime(tmp_path: Path) -> tuple[AgentTranscriptDirectoryRuntime, Path, Path, Path]:
    canonical = tmp_path / "machine-selected-canonical"
    cwd = tmp_path / "machine-selected-cwd"
    home = tmp_path / "machine-selected-home"
    for root, session_id in (
        (canonical, "canonical-session"),
        (cwd, "cwd-session"),
        (home, "home-session"),
    ):
        root.mkdir(parents=True)
        write_agent_transcript_export(
            root / f"{session_id}.jsonl",
            _header(session_id),
            [_record(f"{session_id}-record", session_id)],
        )
    runtime = AgentTranscriptDirectoryRuntime(
        session_dir=canonical,
        authority_session_source=SessionDiscoverySource(
            "sessions.global", canonical, "canonical", "global", priority=0
        ),
        discovery_session_sources=(
            SessionDiscoverySource(
                "sessions.cwd_compatibility", cwd, "compatibility", "cwd", priority=10
            ),
            SessionDiscoverySource(
                "sessions.home_compatibility",
                home,
                "compatibility",
                "home",
                priority=20,
            ),
        ),
    )
    return runtime, canonical, cwd, home


def _adapter(runtime: AgentTranscriptDirectoryRuntime) -> HarnessAppHostSessionAdapterV1:
    return HarnessAppHostSessionAdapterV1(
        runtime,
        scope_bindings=(
            HarnessSessionScopeBindingV1(
                SessionDiscoveryScope.USER_GLOBAL_CANONICAL, "sessions.global"
            ),
            HarnessSessionScopeBindingV1(
                SessionDiscoveryScope.CURRENT_DIRECTORY,
                "sessions.cwd_compatibility",
            ),
            HarnessSessionScopeBindingV1(
                SessionDiscoveryScope.USER_GLOBAL_LEGACY,
                "sessions.home_compatibility",
            ),
        ),
    )


class _CanonicalClaimed:
    def __init__(self, reference: SessionCandidateRefV1) -> None:
        self._reference = reference
        self.closed = 0

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> object:
        return {"canonical": True}

    async def close(self) -> None:
        self.closed += 1


class _CanonicalCandidate:
    def __init__(self, projection: SessionIdentityProjectionV1) -> None:
        self._projection = projection
        self.closed = 0
        self.cancel_first_close = False
        self.fail_first_close = False
        self.always_fail_close = False
        self.close_entered: asyncio.Event | None = None
        self.close_release: asyncio.Event | None = None

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._projection

    async def verify_current(self) -> None:
        return None

    async def claim(self) -> _CanonicalClaimed:
        return _CanonicalClaimed(self._projection.reference)

    async def close(self) -> None:
        self.closed += 1
        if self.close_entered is not None:
            self.close_entered.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.cancel_first_close and self.closed == 1:
            raise asyncio.CancelledError
        if self.fail_first_close and self.closed == 1:
            raise RuntimeError("secret cleanup failure")
        if self.always_fail_close:
            raise RuntimeError("secret permanent cleanup failure")


class _InvalidCanonicalCandidate(_CanonicalCandidate):
    @property
    def projection(self) -> object:
        return object()


class _CanonicalOwner:
    def __init__(self) -> None:
        reference = SessionCandidateRefV1(
            "canonical.owner", "candidate-canonical", "revision-canonical"
        )
        envelope = SessionIdentityEnvelopeV1(
            "coding",
            "coding-session-v1",
            "continuity-canonical",
            "session-canonical",
            "canonical.owner",
            "locator-canonical",
        )
        self.projection = SessionIdentityProjectionV1(
            reference,
            SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
            SessionCandidateMode.CANONICAL,
            envelope,
        )
        self.list_calls: list[tuple[tuple[SessionDiscoveryScope, ...], int]] = []
        self.create_calls = 0
        self.open_calls = 0
        self.invalid: _InvalidCanonicalCandidate | None = None
        self.raise_secret = False

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        self.list_calls.append((scopes, limit))
        return (self.projection,) if self.projection.scope in scopes else ()

    async def open_candidate(
        self, reference: SessionCandidateRefV1
    ) -> _CanonicalCandidate:
        self.open_calls += 1
        if self.raise_secret:
            raise RuntimeError("secret-token at /private/session.jsonl")
        assert reference == self.projection.reference
        if self.invalid is not None:
            return self.invalid
        return _CanonicalCandidate(self.projection)

    async def find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> _CanonicalCandidate | None:
        return _CanonicalCandidate(self.projection) if self.create_calls else None

    async def create_candidate(
        self, intent: SessionCreateIntentV1
    ) -> _CanonicalCandidate:
        self.create_calls += 1
        return _CanonicalCandidate(self.projection)


@pytest.mark.skipif(os.name != "posix", reason="POSIX retained-descriptor contract")
def test_adapter_projects_explicit_cwd_home_and_global_sources_without_paths(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, canonical, cwd, home = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (
                SessionDiscoveryScope.CURRENT_DIRECTORY,
                SessionDiscoveryScope.USER_GLOBAL_LEGACY,
                SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
            ),
            limit=10,
        )
        assert {item.scope for item in projected} == {
            SessionDiscoveryScope.CURRENT_DIRECTORY,
            SessionDiscoveryScope.USER_GLOBAL_LEGACY,
            SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
        }
        assert all(item.mode is SessionCandidateMode.MIGRATION_REQUIRED for item in projected)
        roots = (canonical.as_posix(), cwd.as_posix(), home.as_posix())
        assert all(
            not any(root in item.reference.candidate_id for root in roots)
            for item in projected
        )
        assert all("/" not in item.reference.revision for item in projected)

        selected = next(
            item for item in projected if item.scope is SessionDiscoveryScope.CURRENT_DIRECTORY
        )
        lease = await adapter.open_candidate(selected.reference)
        await lease.verify_current()
        claimed = await lease.claim()
        binding = claimed.opaque_binding
        assert getattr(binding, "conversation_id") == "cwd-session"
        with pytest.raises(SessionCandidateStaleError):
            await lease.claim()
        await claimed.close()
        await lease.close()
        await lease.close()

    asyncio.run(exercise())


def test_adapter_does_not_infer_unbound_scope_or_treat_token_as_path(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
        )
        assert await adapter.list_identities(
            (SessionDiscoveryScope.USER_GLOBAL_LEGACY,), limit=10
        ) == ()
        forged = SessionCandidateRefV1(
            "sessions.cwd_compatibility", "etc-passwd", "revision-1"
        )
        with pytest.raises(SessionCandidateStaleError):
            await adapter.open_candidate(forged)

    asyncio.run(exercise())


def test_adapter_rejects_revision_swap_between_list_and_open(tmp_path: Path) -> None:
    async def exercise() -> None:
        runtime, _, cwd, _ = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=10
        )
        target = cwd / "cwd-session.jsonl"
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with pytest.raises(SessionCandidateStaleError):
            await adapter.open_candidate(projected[0].reference)

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX retained-descriptor contract")
def test_adapter_pinned_claim_survives_rename_and_path_replacement(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, cwd, _ = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=10
        )
        lease = await adapter.open_candidate(projected[0].reference)
        await lease.verify_current()
        claimed = await lease.claim()
        binding = claimed.opaque_binding
        original = cwd / "cwd-session.jsonl"
        archived = cwd / "archived.jsonl"
        original.rename(archived)
        archived_content = archived.read_bytes()
        archived.write_bytes(
            archived_content.replace(b"cwd-session", b"bad-session", 1)
        )
        write_agent_transcript_export(
            original,
            _header("replacement-session"),
            [_record("replacement-record", "replacement-secret")],
        )

        assert getattr(binding, "conversation_id") == "cwd-session"
        content = getattr(binding, "read_bytes")()
        assert b"cwd-session" in content
        assert b"replacement-secret" not in content
        assert repr(binding) == "<PinnedHarnessSessionContent>"
        assert original.as_posix() not in repr(binding)
        await claimed.close()
        await lease.close()

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow contract")
def test_adapter_rejects_symlink_swap_between_list_and_open(tmp_path: Path) -> None:
    async def exercise() -> None:
        runtime, _, cwd, home = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=10
        )
        target = cwd / "cwd-session.jsonl"
        target.unlink()
        target.symlink_to(home / "home-session.jsonl")
        with pytest.raises(SessionCandidateStaleError):
            await adapter.open_candidate(projected[0].reference)

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX snapshot contract")
def test_adapter_rejects_same_inode_same_size_rewrite_with_restored_mtime(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, cwd, _ = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=10
        )
        target = cwd / "cwd-session.jsonl"
        before = target.stat()
        content = target.read_bytes()
        replacement = content.replace(b"cwd-session", b"bad-session", 1)
        assert len(replacement) == len(content)
        target.write_bytes(replacement)
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        with pytest.raises(SessionCandidateStaleError):
            await adapter.open_candidate(projected[0].reference)

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX snapshot contract")
def test_adapter_fails_closed_on_mutation_during_snapshot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        runtime, _, cwd, _ = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=10
        )
        target = cwd / "cwd-session.jsonl"
        native_pread = os.pread
        calls = 0

        def mutating_pread(descriptor: int, size: int, offset: int) -> bytes:
            nonlocal calls
            calls += 1
            chunk = native_pread(descriptor, min(size, 7), offset)
            if calls == 1:
                content = target.read_bytes()
                target.write_bytes(content.replace(b"cwd-session", b"bad-session", 1))
            return chunk

        monkeypatch.setattr(integration.os, "pread", mutating_pread)
        with pytest.raises(SessionCandidateStaleError):
            await adapter.open_candidate(projected[0].reference)
        assert calls > 1

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX snapshot contract")
def test_adapter_accepts_chunked_short_pread_and_seals_exact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        runtime, _, cwd, _ = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=10
        )
        expected = (cwd / "cwd-session.jsonl").read_bytes()
        native_pread = os.pread
        monkeypatch.setattr(
            integration.os,
            "pread",
            lambda descriptor, size, offset: native_pread(
                descriptor, min(size, 7), offset
            ),
        )
        lease = await adapter.open_candidate(projected[0].reference)
        claimed = await lease.claim()
        assert getattr(claimed.opaque_binding, "read_bytes")() == expected
        await claimed.close()
        await lease.close()

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX snapshot contract")
def test_adapter_rejects_content_over_snapshot_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=10
        )
        monkeypatch.setattr(integration, "HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1", 16)
        with pytest.raises(SessionCandidateStaleError):
            await adapter.open_candidate(projected[0].reference)

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "nt", reason="native Windows fail-closed gate")
def test_adapter_windows_native_backend_is_explicitly_fail_closed(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        assert os.name == "nt"
        assert not integration._native_descriptor_supported()
        runtime, _, _, _ = _runtime(tmp_path)
        adapter = _adapter(runtime)
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=10
        )
        with pytest.raises(SessionCandidateStaleError):
            await adapter.open_candidate(projected[0].reference)

    asyncio.run(exercise())


def test_adapter_fails_closed_on_incompatible_duplicate(tmp_path: Path) -> None:
    async def exercise() -> None:
        runtime, canonical, cwd, _ = _runtime(tmp_path)
        write_agent_transcript_export(
            cwd / "conflicting.jsonl",
            _header("canonical-session"),
            [_record("different-record", "different")],
        )
        assert canonical.is_dir()
        adapter = _adapter(runtime)
        with pytest.raises(SessionAmbiguousError):
            await adapter.list_identities(
                (
                    SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                ),
                limit=10,
            )

    from loushang.apphost import SessionAmbiguousError

    asyncio.run(exercise())


def test_adapter_keeps_canonical_creation_default_dark_without_injected_owner(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        adapter = _adapter(runtime)
        request = SessionCreateRequestV1(
            "coding", "user-1", "01K4J8F3N3J7M9Q2R6T5V8W0XY"
        )
        assert await adapter.find_created_candidate(request) is None
        with pytest.raises(AppHostError) as error:
            await adapter.create_candidate(
                SessionCreateIntentV1(request, "coding-session-v1")
            )
        assert error.value.category is AppHostFailureCategory.RUNTIME_UNAVAILABLE

    asyncio.run(exercise())


def test_adapter_delegates_canonical_owner_without_deriving_authority(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )
        projected = await adapter.list_identities(
            (SessionDiscoveryScope.USER_GLOBAL_CANONICAL,), limit=1
        )
        assert projected == (owner.projection,)
        assert owner.list_calls == [
            ((SessionDiscoveryScope.USER_GLOBAL_CANONICAL,), 1)
        ]
        opened = await adapter.open_candidate(owner.projection.reference)
        await opened.verify_current()
        await opened.close()

        request = SessionCreateRequestV1(
            "coding", "user-1", "01K4J8F3N3J7M9Q2R6T5V8W0XY"
        )
        assert await adapter.find_created_candidate(request) is None
        created = await adapter.create_candidate(
            SessionCreateIntentV1(request, "coding-session-v1")
        )
        recovered = await adapter.find_created_candidate(request)
        assert recovered is not None
        assert created.projection.reference == recovered.projection.reference
        await created.close()
        await recovered.close()

    asyncio.run(exercise())


def test_adapter_rejects_and_settles_malicious_canonical_return(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        invalid = _InvalidCanonicalCandidate(owner.projection)
        owner.invalid = invalid
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )
        with pytest.raises(SessionCandidateStaleError) as error:
            await adapter.open_candidate(owner.projection.reference)
        assert error.value.__cause__ is None
        assert invalid.closed == 1

    asyncio.run(exercise())


def test_adapter_retains_failed_validation_cleanup_for_concurrent_retry(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        invalid = _InvalidCanonicalCandidate(owner.projection)
        invalid.fail_first_close = True
        owner.invalid = invalid
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )

        with pytest.raises(CleanupIncompleteError) as caught:
            await adapter.open_candidate(owner.projection.reference)
        assert caught.value.primary_category is AppHostFailureCategory.SESSION_CANDIDATE_STALE
        assert caught.value.__cause__ is None
        assert invalid.closed == 1

        await asyncio.gather(
            adapter.settle_pending_cleanup(),
            adapter.settle_pending_cleanup(),
        )
        assert invalid.closed == 2
        await adapter.settle_pending_cleanup()
        assert invalid.closed == 2

    asyncio.run(exercise())


def test_adapter_refuses_new_provider_calls_while_permanent_debt_remains(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        invalid = _InvalidCanonicalCandidate(owner.projection)
        invalid.always_fail_close = True
        owner.invalid = invalid
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )

        for _ in range(4):
            with pytest.raises(CleanupIncompleteError):
                await adapter.open_candidate(owner.projection.reference)
            assert owner.open_calls == 1
            assert adapter._cleanup.pending_count == 1

        with pytest.raises(CleanupIncompleteError):
            await adapter.close()
        with pytest.raises(GenerationRetiredError):
            await adapter.open_candidate(owner.projection.reference)
        assert owner.open_calls == 1
        assert adapter._cleanup.pending_count == 1

    asyncio.run(exercise())


def test_adapter_drains_cleanup_debt_before_resuming_provider_calls(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        invalid = _InvalidCanonicalCandidate(owner.projection)
        invalid.fail_first_close = True
        owner.invalid = invalid
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )

        with pytest.raises(CleanupIncompleteError):
            await adapter.open_candidate(owner.projection.reference)
        assert owner.open_calls == 1
        owner.invalid = None

        recovered = await adapter.open_candidate(owner.projection.reference)
        assert owner.open_calls == 2
        assert invalid.closed == 2
        assert adapter._cleanup.pending_count == 0
        await recovered.close()
        await adapter.close()

    asyncio.run(exercise())


def test_adapter_bounds_concurrent_canonical_provider_calls(tmp_path: Path) -> None:
    class _BlockingOwner(_CanonicalOwner):
        def __init__(self) -> None:
            super().__init__()
            self.all_entered = asyncio.Event()
            self.release = asyncio.Event()

        async def open_candidate(
            self, reference: SessionCandidateRefV1
        ) -> _CanonicalCandidate:
            self.open_calls += 1
            if (
                self.open_calls
                == integration.HARNESS_SESSION_MAX_ACTIVE_CANONICAL_OPS_V1
            ):
                self.all_entered.set()
            await self.release.wait()
            return _CanonicalCandidate(self.projection)

    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _BlockingOwner()
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )
        limit = integration.HARNESS_SESSION_MAX_ACTIVE_CANONICAL_OPS_V1
        calls = tuple(
            asyncio.create_task(
                adapter.open_candidate(owner.projection.reference)
            )
            for _ in range(limit)
        )
        await owner.all_entered.wait()
        with pytest.raises(AppHostError) as caught:
            await adapter.open_candidate(owner.projection.reference)
        assert caught.value.category is AppHostFailureCategory.RUNTIME_UNAVAILABLE
        assert owner.open_calls == limit

        owner.release.set()
        leases = await asyncio.gather(*calls)
        for lease in leases:
            await lease.close()
        resumed = await adapter.open_candidate(owner.projection.reference)
        assert owner.open_calls == limit + 1
        await resumed.close()
        await adapter.close()

    asyncio.run(exercise())


def test_adapter_retains_cancelled_cleanup_callback_for_retry(tmp_path: Path) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        invalid = _InvalidCanonicalCandidate(owner.projection)
        invalid.cancel_first_close = True
        owner.invalid = invalid
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )

        with pytest.raises(CleanupIncompleteError):
            await adapter.open_candidate(owner.projection.reference)
        assert invalid.closed == 1
        await adapter.settle_pending_cleanup()
        assert invalid.closed == 2

    asyncio.run(exercise())


def test_adapter_settlement_cancellation_keeps_joinable_owner(tmp_path: Path) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        invalid = _InvalidCanonicalCandidate(owner.projection)
        invalid.fail_first_close = True
        owner.invalid = invalid
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )
        with pytest.raises(CleanupIncompleteError):
            await adapter.open_candidate(owner.projection.reference)

        invalid.close_entered = asyncio.Event()
        invalid.close_release = asyncio.Event()
        settlement = asyncio.create_task(adapter.settle_pending_cleanup())
        await invalid.close_entered.wait()
        settlement.cancel()
        invalid.close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await settlement

        await adapter.settle_pending_cleanup()
        assert invalid.closed == 2

    asyncio.run(exercise())


def test_adapter_close_fences_and_joins_inflight_validation_cleanup(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        invalid = _InvalidCanonicalCandidate(owner.projection)
        invalid.close_entered = asyncio.Event()
        invalid.close_release = asyncio.Event()
        owner.invalid = invalid
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )

        opening = asyncio.create_task(
            adapter.open_candidate(owner.projection.reference)
        )
        await invalid.close_entered.wait()
        closing_one = asyncio.create_task(adapter.close())
        closing_two = asyncio.create_task(adapter.close())
        await asyncio.sleep(0)
        assert not closing_one.done()
        assert not closing_two.done()
        with pytest.raises(GenerationRetiredError):
            await adapter.list_identities(
                (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=1
            )

        invalid.close_release.set()
        with pytest.raises(SessionCandidateStaleError):
            await opening
        await asyncio.gather(closing_one, closing_two)
        assert invalid.closed == 1

    asyncio.run(exercise())


def test_adapter_close_retries_retained_debt_once(tmp_path: Path) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        invalid = _InvalidCanonicalCandidate(owner.projection)
        invalid.fail_first_close = True
        owner.invalid = invalid
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )
        with pytest.raises(CleanupIncompleteError):
            await adapter.open_candidate(owner.projection.reference)
        await adapter.close()
        assert invalid.closed == 2
        await adapter.close()
        assert invalid.closed == 2

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX close ambiguity contract")
def test_descriptor_owner_never_retries_relinquished_fd_after_post_effect_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        target = tmp_path / "descriptor-owner.txt"
        target.write_bytes(b"owner")
        descriptor = os.open(target, os.O_RDONLY)
        native_close = os.close
        owner = integration._DescriptorOwner(descriptor)
        closer = RetryableCloser.bind(owner)

        def close_then_raise(value: int) -> None:
            native_close(value)
            if value == descriptor:
                raise OSError("ambiguous post-effect close")

        monkeypatch.setattr(integration.os, "close", close_then_raise)
        assert not await closer.settle()
        monkeypatch.setattr(integration.os, "close", native_close)

        reused = os.open(target, os.O_RDONLY)
        try:
            assert reused == descriptor
            assert await closer.settle()
            assert await closer.settle()
            os.fstat(reused)
        finally:
            native_close(reused)

    asyncio.run(exercise())


def test_adapter_redacts_canonical_owner_failures(tmp_path: Path) -> None:
    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CanonicalOwner()
        owner.raise_secret = True
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )
        with pytest.raises(SessionCandidateStaleError) as caught:
            await adapter.open_candidate(owner.projection.reference)
        assert str(caught.value) == "session_candidate_stale"
        assert caught.value.__cause__ is None
        assert "secret-token" not in repr(caught.value)
        assert "/private" not in repr(caught.value)

    asyncio.run(exercise())


def test_adapter_preserves_canonical_owner_cancellation(tmp_path: Path) -> None:
    class _CancelledOwner(_CanonicalOwner):
        async def open_candidate(
            self, reference: SessionCandidateRefV1
        ) -> _CanonicalCandidate:
            raise asyncio.CancelledError

    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        owner = _CancelledOwner()
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=owner,
        )
        with pytest.raises(asyncio.CancelledError):
            await adapter.open_candidate(owner.projection.reference)

    asyncio.run(exercise())


def test_adapter_rejects_malicious_scope_and_invalid_limits(tmp_path: Path) -> None:
    class _WrongScopeOwner(_CanonicalOwner):
        async def list_identities(
            self,
            scopes: tuple[SessionDiscoveryScope, ...],
            *,
            limit: int,
        ) -> tuple[SessionIdentityProjectionV1, ...]:
            return (self.projection,)

    async def exercise() -> None:
        runtime, _, _, _ = _runtime(tmp_path)
        adapter = HarnessAppHostSessionAdapterV1(
            runtime,
            scope_bindings=(
                HarnessSessionScopeBindingV1(
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    "sessions.cwd_compatibility",
                ),
            ),
            canonical_owner=_WrongScopeOwner(),
        )
        with pytest.raises(SessionCandidateStaleError):
            await adapter.list_identities(
                (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=1
            )
        with pytest.raises(ValueError):
            await adapter.list_identities(
                (SessionDiscoveryScope.CURRENT_DIRECTORY,), limit=257
            )
        with pytest.raises(TypeError):
            await adapter.list_identities(
                (
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                    SessionDiscoveryScope.CURRENT_DIRECTORY,
                ),
                limit=1,
            )

    asyncio.run(exercise())
