"""Old Coding bridge plus real Transcript IO, before the bytes-route refactor.

The small runtime binds the actual owned-import/transient-open leaves. It does
not stand in for Coding SDK discovery, Agent construction or lifecycle hooks.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from loushang.coding.continuity import CodingContinuityActivationBridge
from loushang.harness.artifacts.store import ArtifactSourceRejected
from loushang.harness.continuity import (
    CONTINUITY_BUNDLE_MEDIA_TYPE,
    CONTINUITY_JSONL_MEDIA_TYPE,
    ContinuityActivationPayload,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
)
from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptSessionFactory,
    ProductTranscriptSession,
    write_agent_transcript_export,
)
from loushang.harness.transcript.export import read_agent_transcript_bundle

from .test_owned_bundle_import import bundle
from .test_owned_session_factory import factory
from .test_runtime_profile import _runtime

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux owned Transcript source contract"
)


def _files(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


class _Prepared:
    def __init__(self, session):
        self.session = session

    async def abort(self):
        await self.session.dispose()

    async def close(self):
        await self.abort()

    async def consume(self):
        self.session._mark_import_delivered()
        return self.session


class _Runtime:
    def __init__(self, selected, target, persist):
        self.selected, self.target, self.persist = selected, target, persist
        self.session = None

    async def prepare_restore_session_operation(
        self, source, *, fallback_cwd=None, missing_cwd="error"
    ):
        if self.persist:
            self.session = await self.selected.import_transcript(
                source,
                session_dir=self.target,
                cwd_override=fallback_cwd,
                _unpublished=True,
            )
        elif Path(source).suffix == ".zip":
            self.session = await self.selected.import_bundle(
                source,
                session_dir=self.target,
                cwd_override=fallback_cwd,
                persist=False,
            )
        else:
            self.session = await self.selected.open(
                source,
                session_dir=self.target,
                cwd_override=fallback_cwd,
                persist=False,
            )
        return _Prepared(self.session)


@pytest.mark.parametrize(
    "archive,images,persist,missing_temporary",
    [
        (False, False, True, False),
        (False, True, True, False),
        (False, True, True, True),
        (True, False, True, False),
        (True, True, True, False),
        (False, False, False, False),
        (True, False, False, False),
    ],
)
def test_old_bridge_reuses_real_blob_source_and_retracts_undelivered_import(
    archive, images, persist, missing_temporary
):
    async def scenario(root):
        zipped, target = await bundle(root, images=images)
        source_dir = root / "source/sessions"
        # Empty owned Sessions are lazy; create the actual old JSONL input
        # using the existing export codec rather than assuming it was written.
        if not archive and not tuple(source_dir.glob("*.jsonl")):
            exported = read_agent_transcript_bundle(zipped)
            write_agent_transcript_export(
                source_dir / "input.jsonl", exported.header, exported.records
            )
        source = zipped if archive else next(source_dir.glob("*.jsonl"))
        before = _files(root / "source")
        if persist:
            selected = factory()
        else:
            profile = _runtime("coding")
            selected = AgentTranscriptSessionFactory(
                lifecycle=AgentTranscriptLifecycle(bind_runtime=profile.bind_lifecycle),
                resolve_binding_input=lambda value: profile.resolve(persist=value),
                header_metadata=lambda _: {},
            )
        runtime = _Runtime(selected, target, persist)
        temporary = (
            source_dir.parent / "missing-sessions" if missing_temporary else source_dir
        )
        if missing_temporary:
            assert not temporary.exists()
        bridge = CodingContinuityActivationBridge(
            runtime,
            temporary_root=temporary,
            fallback_cwd=str(root),
        )
        try:
            lease = await bridge.prepare(
                ContinuityTarget(provider_id="remote", opaque_id="one"),
                ContinuityActivationPayload.from_bytes(
                    source.read_bytes(),
                    media_type=(
                        CONTINUITY_BUNDLE_MEDIA_TYPE
                        if archive
                        else CONTINUITY_JSONL_MEDIA_TYPE
                    ),
                ),
                ContinuityProviderSourceDescriptor(
                    provider_id="remote",
                    source="oem",
                    source_id="oem:remote",
                    implementation="remote.continuity",
                    implementation_version=1,
                ),
            )
            session = runtime.session
            assert session is not None
            assert session.context.cwd == str(root)
            if images:
                context = ProductTranscriptSession(
                    lifecycle_session=session
                ).build_session_context()
                assert context.messages[0].content[0].data == "aGVsbG8="
                assert session.session_blob_health[0].state == "available"
            await lease.abort()
            assert not tuple(target.glob("*.jsonl"))
            assert not (target.parent / "session-assets/conversation-1").exists()
            after = _files(root / "source")
            if not persist and not archive:
                # The old transient JSONL open leaves its source lock behind.
                # Record that actual old artifact; it is not a requirement to
                # manufacture a temporary lock in a future bytes-only route.
                added = set(after) - set(before)
                assert len(added) == 1
                lock = added.pop()
                assert lock.startswith("sessions/continuity-")
                assert lock.endswith(".jsonl.lock")
                assert after.pop(lock) == b"\x00"
            assert after == before
            assert not selected.pending_preparations
            if missing_temporary:
                assert temporary.is_dir()
                assert not tuple(temporary.iterdir())
        finally:
            if runtime.session is not None:
                await runtime.session.dispose()
            await selected.close()

    # Actual input authorities need private ancestors; the managed pytest run
    # lease/runtime stays unchanged. This directory is removed on every exit.
    with TemporaryDirectory(
        prefix=".loushang-continuity-source-", dir=Path.home()
    ) as directory:
        asyncio.run(scenario(Path(directory)))


def test_old_jsonl_bridge_does_not_borrow_another_blob_root():
    async def scenario(root):
        _, target = await bundle(root)
        source = next((root / "source/sessions").glob("*.jsonl"))
        scratch = root / "foreign/continuity"
        scratch.parent.mkdir(mode=0o700)
        selected = factory()
        runtime = _Runtime(selected, target, True)
        try:
            bridge = CodingContinuityActivationBridge(runtime, temporary_root=scratch)
            with pytest.raises(ArtifactSourceRejected, match="not owned"):
                await bridge.prepare(
                    ContinuityTarget(provider_id="remote", opaque_id="one"),
                    ContinuityActivationPayload.from_bytes(
                        source.read_bytes(),
                        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
                    ),
                    ContinuityProviderSourceDescriptor(
                        provider_id="remote",
                        source="oem",
                        source_id="oem:remote",
                        implementation="remote.continuity",
                        implementation_version=1,
                    ),
                )
            assert not tuple(target.glob("*.jsonl"))
            assert not (scratch.parent / "session-assets").exists()
            assert not tuple(scratch.glob("continuity-*"))
            assert not selected.pending_preparations
        finally:
            await selected.close()

    with TemporaryDirectory(
        prefix=".loushang-continuity-source-", dir=Path.home()
    ) as directory:
        asyncio.run(scenario(Path(directory)))
