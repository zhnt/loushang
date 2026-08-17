from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.session import (
    ForkProfile,
    ForkSelection,
    ProductSessionRuntime,
    ProductSessionRuntimePorts,
    SessionLifecycleHooks,
)


@dataclass(frozen=True)
class _Transcript:
    ref: str
    cwd: str
    leaf_id: str = "leaf"


@dataclass(frozen=True)
class _Session:
    transcript: _Transcript


def test_product_session_runtime_composes_transcript_and_lifecycle_ports(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        actions: list[tuple[object, ...]] = []
        disposed: list[str] = []

        async def create_transcript(
            cwd: str, parent_ref: str | None
        ) -> _Transcript:
            actions.append(("create", cwd, parent_ref))
            return _Transcript("new.jsonl", cwd)

        async def fork_transcript(
            transcript: _Transcript, target_entry_id: str | None
        ) -> _Transcript:
            actions.append(("fork", transcript.ref, target_entry_id))
            return _Transcript("fork.jsonl", transcript.cwd)

        async def dispose_transcript(transcript: _Transcript) -> None:
            actions.append(("dispose-transcript", transcript.ref))

        def build_session(
            transcript: _Transcript,
            _current: _Session | None,
            _transition: object,
        ) -> _Session:
            return _Session(transcript)

        runtime = ProductSessionRuntime[
            _Session, _Transcript, object
        ](
            session_dir=tmp_path,
            ports=ProductSessionRuntimePorts(
                session_factory=lambda transcript: _Session(transcript),
                persist=True,
                create_transcript=create_transcript,
                restore_transcript=lambda ref, _cwd: _Transcript(str(ref), "/restored"),
                fork_transcript=fork_transcript,
                dispose_transcript=dispose_transcript,
                transcript_for_session=lambda session: session.transcript,
                transcript_cwd=lambda transcript: transcript.cwd,
                transcript_session_ref=lambda transcript: transcript.ref,
                transcript_leaf_entry_id=lambda transcript: transcript.leaf_id,
                build_session=build_session,
                validate_restored_transcript=None,
                fork_profile=ForkProfile(
                    default_position="at", supported_positions=frozenset({"at"})
                ),
                fork_target_resolver=lambda _session, entry_id, _position: ForkSelection(
                    target_entry_id=entry_id
                ),
                hooks=SessionLifecycleHooks(
                    dispose_session=lambda session: disposed.append(
                        session.transcript.ref
                    )
                ),
            ),
        )

        created = await runtime.create_session(
            cwd=str(tmp_path), parent_session="parent.jsonl"
        )
        assert created.transcript == _Transcript("new.jsonl", str(tmp_path))
        assert runtime.get_current_session() == created

        forked = await runtime.fork_session("leaf")
        assert forked.transcript == _Transcript("fork.jsonl", str(tmp_path))
        assert runtime.get_current_session() == forked
        assert actions[:2] == [
            ("create", str(tmp_path), "parent.jsonl"),
            ("fork", "new.jsonl", "leaf"),
        ]

        await runtime.dispose_session_runtime()
        assert disposed == ["new.jsonl", "fork.jsonl"]

    asyncio.run(scenario())
