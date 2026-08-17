"""Product-composed factory for Conversation JSONL Agent transcript sessions.

The factory owns the repeated session assembly sequence: conversation identity,
header construction, Conversation JSONL file context, runtime binding, restore, recent
resume, and branch/fork creation.  Products supply the binding input, their
header metadata, and resume validation without reimplementing that sequence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Generic, TypeVar
from uuid import uuid4

from loushang.foundation.json import JSONValue
from loushang.harness.conversation import (
    CURRENT_CONVERSATION_FORMAT_VERSION,
    ConversationHeader,
)
from loushang.harness.transcript.lifecycle import (
    AgentTranscriptLifecycle,
    AgentTranscriptLifecycleContext,
    AgentTranscriptLifecycleSession,
)
from loushang.harness.transcript.session_catalog import (
    AgentTranscriptSessionCatalog,
)
from loushang.harness.transcript.types import AgentTranscriptRecord

BindingInputT = TypeVar("BindingInputT")
ProductBindingT = TypeVar("ProductBindingT")
SourceProductBindingT = TypeVar("SourceProductBindingT")

BindingInputResolver = Callable[[bool], BindingInputT]
HeaderMetadataFactory = Callable[[BindingInputT], Mapping[str, JSONValue]]
RestoredHeaderValidator = Callable[[ConversationHeader, BindingInputT, bool], None]
SessionFileFactory = Callable[[Path, ConversationHeader], Path | None]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class AgentTranscriptSessionFactory(Generic[BindingInputT, ProductBindingT]):
    """Compose one Product's standard Agent transcript session lifecycle.

    ``AgentTranscriptLifecycle`` remains the low-level store and lease owner.
    This factory adds the reusable create, Conversation JSONL restore, recent-resume, and
    fork orchestration that Products previously repeated in their facades.
    A Product callback remains the sole owner of runtime/profile selection,
    header metadata, and compatibility validation.
    """

    def __init__(
        self,
        *,
        lifecycle: AgentTranscriptLifecycle[BindingInputT, ProductBindingT],
        resolve_binding_input: BindingInputResolver,
        header_metadata: HeaderMetadataFactory,
        validate_restored_header: RestoredHeaderValidator | None = None,
        session_file_factory: SessionFileFactory | None = None,
        conversation_version: int = CURRENT_CONVERSATION_FORMAT_VERSION,
        clock: Clock | None = None,
        conversation_id_factory: IdFactory | None = None,
    ) -> None:
        if type(conversation_version) is not int or conversation_version < 1:
            raise ValueError("conversation version must be a positive integer")
        self._lifecycle = lifecycle
        self._resolve_binding_input = resolve_binding_input
        self._header_metadata = header_metadata
        self._validate_restored_header = validate_restored_header or _validate_nothing
        self._session_file_factory = session_file_factory
        self._conversation_version = conversation_version
        self._clock = clock or _utc_now
        self._conversation_id_factory = conversation_id_factory or _default_id

    async def new(
        self,
        *,
        session_dir: str | Path,
        cwd: str | Path,
        persist: bool = True,
        parent_session: str | None = None,
        session_id: str | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Create one empty transcript with Product-selected runtime metadata."""

        resolved_session_id = self._resolve_conversation_id(session_id)
        binding_input = self._resolve_binding_input(persist)
        return await self._create(
            session_dir=session_dir,
            cwd=cwd,
            persist=persist,
            binding_input=binding_input,
            conversation_id=resolved_session_id,
            parent_session=parent_session,
        )

    async def load(
        self,
        session_file: str | Path,
        *,
        persist: bool = True,
        session_dir: str | Path | None = None,
        cwd_override: str | Path | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Restore one Conversation JSONL transcript through the selected binding."""

        context = self._lifecycle.conversation_jsonl_context(
            session_file,
            persist=persist,
            session_dir=session_dir,
            cwd_override=cwd_override,
        )
        binding_input = self._resolve_binding_input(persist)
        self._validate_restored_header(context.header, binding_input, persist)
        return await self._lifecycle.restore(context, binding_input)

    async def open(
        self,
        session_file: str | Path,
        *,
        session_dir: str | Path | None = None,
        cwd_override: str | Path | None = None,
        persist: bool = True,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Restore a transcript while applying Product-selected path overrides."""

        return await self.load(
            session_file,
            persist=persist,
            session_dir=session_dir,
            cwd_override=cwd_override,
        )

    async def continue_recent(
        self,
        *,
        session_dir: str | Path,
        cwd: str | Path,
        persist: bool = True,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Resume the most recent Conversation JSONL transcript or create a new one."""

        resolved_session_dir = Path(session_dir)
        for summary in AgentTranscriptSessionCatalog(
            resolved_session_dir
        ).list_summaries():
            if summary.session_file is not None:
                return await self.open(
                    summary.session_file,
                    session_dir=resolved_session_dir,
                    cwd_override=cwd,
                    persist=persist,
                )
        return await self.new(
            session_dir=resolved_session_dir,
            cwd=cwd,
            persist=persist,
        )

    async def in_memory(
        self,
        *,
        cwd: str | Path = ".",
        session_id: str | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Create a transient transcript without choosing a Product root."""

        return await self.new(
            session_dir=Path(),
            cwd=cwd,
            persist=False,
            session_id=session_id,
        )

    async def fork_from(
        self,
        source_file: str | Path,
        *,
        target_cwd: str | Path,
        session_dir: str | Path,
        persist: bool = True,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Copy a Conversation JSONL transcript into a new Product-selected session."""

        source = await self.load(source_file, persist=False)
        try:
            return await self._create(
                session_dir=session_dir,
                cwd=target_cwd,
                persist=persist,
                binding_input=self._resolve_binding_input(persist),
                parent_conversation_id=source.context.header.conversation_id,
                parent_session=str(Path(source_file)),
                records=source.transcript.records,
            )
        finally:
            await source.dispose()

    async def fork(
        self,
        source: AgentTranscriptLifecycleSession[SourceProductBindingT],
        *,
        leaf_id: str,
        binding_input: BindingInputT,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Fork one selected source path using an already selected Product binding."""

        source_context = source.context
        header = self._new_header(
            conversation_id=None,
            cwd=source_context.cwd,
            parent_conversation_id=source_context.header.conversation_id,
            parent_session=(
                str(source_context.session_file)
                if source_context.session_file is not None
                else None
            ),
            binding_input=binding_input,
        )
        context = self._new_context(
            session_dir=source_context.session_dir,
            cwd=source_context.cwd,
            persist=source_context.persist,
            header=header,
        )
        return await self._lifecycle.fork(
            source.transcript,
            context,
            binding_input,
            leaf_id=leaf_id,
        )

    async def _create(
        self,
        *,
        session_dir: str | Path,
        cwd: str | Path,
        persist: bool,
        binding_input: BindingInputT,
        conversation_id: str | None = None,
        parent_conversation_id: str | None = None,
        parent_session: str | None = None,
        records: Sequence[AgentTranscriptRecord] = (),
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        header = self._new_header(
            conversation_id=conversation_id,
            cwd=cwd,
            parent_conversation_id=parent_conversation_id,
            parent_session=parent_session,
            binding_input=binding_input,
        )
        context = self._new_context(
            session_dir=session_dir,
            cwd=cwd,
            persist=persist,
            header=header,
        )
        return await self._lifecycle.create(context, binding_input, records=records)

    def _new_context(
        self,
        *,
        session_dir: str | Path,
        cwd: str | Path,
        persist: bool,
        header: ConversationHeader,
    ) -> AgentTranscriptLifecycleContext:
        resolved_session_dir = Path(session_dir)
        session_file = (
            self._session_file_factory(resolved_session_dir, header)
            if persist and self._session_file_factory is not None
            else None
        )
        return self._lifecycle.new_context(
            session_dir=resolved_session_dir,
            cwd=cwd,
            persist=persist,
            header=header,
            session_file=session_file,
        )

    def _new_header(
        self,
        *,
        conversation_id: str | None,
        cwd: str | Path,
        parent_conversation_id: str | None = None,
        parent_session: str | None = None,
        binding_input: BindingInputT,
    ) -> ConversationHeader:
        metadata: dict[str, JSONValue] = {"cwd": str(cwd)}
        if parent_session is not None:
            metadata["parentSession"] = parent_session
        metadata.update(self._header_metadata(binding_input))
        return ConversationHeader(
            conversation_id=self._resolve_conversation_id(conversation_id),
            version=self._conversation_version,
            created_at=_encode_timestamp(self._clock()),
            parent_conversation_id=parent_conversation_id,
            metadata=metadata,
        )

    def _resolve_conversation_id(self, conversation_id: str | None) -> str:
        if conversation_id is None:
            conversation_id = self._conversation_id_factory()
        if not isinstance(conversation_id, str):
            raise TypeError("session_id must be a string")
        if not conversation_id.strip():
            raise ValueError("session_id must not be blank")
        return conversation_id


def _validate_nothing(
    header: ConversationHeader,
    binding_input: object,
    persist: bool,
) -> None:
    del header, binding_input, persist


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _default_id() -> str:
    return uuid4().hex[:8]


def _encode_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("session clock must return datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "AgentTranscriptSessionFactory",
    "BindingInputResolver",
    "Clock",
    "HeaderMetadataFactory",
    "IdFactory",
    "RestoredHeaderValidator",
    "SessionFileFactory",
]
