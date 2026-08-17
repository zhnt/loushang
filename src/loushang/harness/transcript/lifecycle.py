"""Lifecycle assembly for one optional Agent transcript session.

Products provide the selected store/profile binding and their own header
policy. This module owns the durable create, restore, detached restore, fork,
and disposal mechanics shared by Conversation JSONL Agent transcripts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, TypeVar
from uuid import uuid4

from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    ConversationStore,
    StoreNotFoundError,
)
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
    load_agent_transcript_file,
    load_agent_transcript_header,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile
from loushang.harness.transcript.session_catalog import (
    agent_transcript_header_cwd,
    build_agent_transcript_label_indexes,
    same_agent_transcript_session_path,
)
from loushang.harness.transcript.types import AgentTranscriptRecord
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork

BindingInputT = TypeVar("BindingInputT")
ProductBindingT = TypeVar("ProductBindingT")

IdFactory = Callable[[], str]
AsyncDisposer = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class AgentTranscriptLifecycleContext:
    """One Product-selected transcript location and persistence mode."""

    session_dir: Path
    cwd: str
    persist: bool
    header: ConversationHeader
    session_file: Path | None = None

    def __post_init__(self) -> None:
        session_dir = Path(self.session_dir).expanduser().resolve(strict=False)
        session_file = (
            Path(self.session_file).expanduser().resolve(strict=False)
            if self.session_file is not None
            else None
        )
        object.__setattr__(self, "session_dir", session_dir)
        object.__setattr__(self, "session_file", session_file)
        object.__setattr__(self, "cwd", str(self.cwd))


@dataclass(frozen=True)
class AgentTranscriptRuntimeBinding(Generic[ProductBindingT]):
    """One Product-selected store/profile binding for a transcript lifetime."""

    store: ConversationStore[ConversationHeader, AgentTranscriptRecord]
    key: ConversationKey
    profile: AgentTranscriptProfile
    product_binding: ProductBindingT
    dispose: AsyncDisposer


@dataclass
class AgentTranscriptLifecycleSession(Generic[ProductBindingT]):
    """A bound transcript plus the Product lease that must be released."""

    context: AgentTranscriptLifecycleContext
    transcript: AgentTranscriptUnitOfWork
    runtime_binding: AgentTranscriptRuntimeBinding[ProductBindingT]
    labels_by_target_id: dict[str, str]
    label_timestamps_by_target_id: dict[str, str]
    _disposed: bool = field(default=False, init=False, repr=False)

    @property
    def product_binding(self) -> ProductBindingT:
        return self.runtime_binding.product_binding

    async def dispose(self) -> None:
        """Release the Product runtime binding exactly once."""

        if self._disposed:
            return
        self._disposed = True
        await self.runtime_binding.dispose()


RuntimeBinder = Callable[
    [AgentTranscriptLifecycleContext, BindingInputT],
    Awaitable[AgentTranscriptRuntimeBinding[ProductBindingT]],
]
HeaderLoader = Callable[[Path], ConversationHeader]
SnapshotLoader = Callable[
    [Path], tuple[ConversationHeader, list[AgentTranscriptRecord]]
]


class AgentTranscriptLifecycle(Generic[BindingInputT, ProductBindingT]):
    """Bind and construct Conversation JSONL transcript sessions through ports.

    The lifecycle deliberately does not resolve a Product profile, construct
    Product header metadata, select a root, or validate Product resume policy.
    Those decisions are supplied by the caller and become immutable when a
    session is constructed.
    """

    def __init__(
        self,
        *,
        bind_runtime: RuntimeBinder[BindingInputT, ProductBindingT],
        header_loader: HeaderLoader = load_agent_transcript_header,
        snapshot_loader: SnapshotLoader = load_agent_transcript_file,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._bind_runtime = bind_runtime
        self._header_loader = header_loader
        self._snapshot_loader = snapshot_loader
        self._id_factory = id_factory or _default_id

    def new_context(
        self,
        *,
        session_dir: str | Path,
        cwd: str | Path,
        persist: bool,
        header: ConversationHeader,
        session_file: str | Path | None = None,
    ) -> AgentTranscriptLifecycleContext:
        """Create a context from Product-selected persistence and location data."""

        return AgentTranscriptLifecycleContext(
            session_dir=Path(session_dir),
            cwd=str(cwd),
            persist=persist,
            header=header,
            session_file=Path(session_file) if session_file is not None else None,
        )

    def default_jsonl_session_file(
        self,
        session_dir: str | Path,
        header: ConversationHeader,
    ) -> Path:
        """Return the Conversation JSONL filename without selecting a Product root."""

        return Path(session_dir) / _default_session_filename(header)

    def conversation_jsonl_context(
        self,
        session_file: str | Path,
        *,
        persist: bool,
        session_dir: str | Path | None = None,
        cwd_override: str | Path | None = None,
    ) -> AgentTranscriptLifecycleContext:
        """Read a Conversation JSONL header and build a Product-bindable context."""

        path = Path(session_file).expanduser().resolve(strict=False)
        header = self._header_loader(path)
        return AgentTranscriptLifecycleContext(
            session_dir=Path(session_dir) if session_dir is not None else path.parent,
            cwd=(
                str(cwd_override)
                if cwd_override is not None
                else agent_transcript_header_cwd(header)
            ),
            persist=persist,
            header=header,
            session_file=path,
        )

    async def create(
        self,
        context: AgentTranscriptLifecycleContext,
        binding_input: BindingInputT,
        *,
        records: Sequence[AgentTranscriptRecord] = (),
        leaf_id: str | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Create one bound transcript and release its lease on failure."""

        runtime_binding = await self._bind_runtime(context, binding_input)
        try:
            transcript = await AgentTranscriptUnitOfWork.create(
                runtime_binding.store,
                runtime_binding.key,
                context.header,
                records=records,
                leaf_id=leaf_id,
                id_factory=self._id_factory,
                profile=runtime_binding.profile,
                defer_materialization=context.persist and not records,
            )
        except BaseException:
            await runtime_binding.dispose()
            raise
        return _lifecycle_session(context, transcript, runtime_binding)

    async def restore(
        self,
        context: AgentTranscriptLifecycleContext,
        binding_input: BindingInputT,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Restore a bound session or create a detached writable copy.

        A non-persistent restore reads the Conversation JSONL source but always
        creates the resulting session through the selected Product store. It
        therefore never mutates the source transcript.
        """

        runtime_binding = await self._bind_runtime(context, binding_input)
        try:
            if context.persist:
                transcript = await AgentTranscriptUnitOfWork.load(
                    runtime_binding.store,
                    runtime_binding.key,
                    id_factory=self._id_factory,
                    profile=runtime_binding.profile,
                )
            else:
                if context.session_file is None:
                    raise ValueError(
                        "detached transcript restores require a session file"
                    )
                source_header, source_records = self._snapshot_loader(
                    context.session_file
                )
                transcript = await AgentTranscriptUnitOfWork.create(
                    runtime_binding.store,
                    runtime_binding.key,
                    source_header,
                    records=source_records,
                    id_factory=self._id_factory,
                    profile=runtime_binding.profile,
                )
        except BaseException:
            await runtime_binding.dispose()
            raise
        return _lifecycle_session(context, transcript, runtime_binding)

    async def fork(
        self,
        source: AgentTranscriptUnitOfWork,
        context: AgentTranscriptLifecycleContext,
        binding_input: BindingInputT,
        *,
        leaf_id: str,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Create a new transcript containing only one selected source path."""

        records = source.records_for_fork(leaf_id)
        return await self.create(
            context,
            binding_input,
            records=records,
            leaf_id=leaf_id,
        )


async def delete_agent_transcript_jsonl(
    session_file: str | Path,
    *,
    current_session_file: str | Path | None = None,
) -> bool:
    """Delete one Conversation JSONL file after protecting the active transcript."""

    target = Path(session_file).expanduser()
    if current_session_file is not None and same_agent_transcript_session_path(
        target, Path(current_session_file).expanduser()
    ):
        raise ValueError("Cannot delete the currently active session")
    if not target.is_file():
        return False
    layout = AgentTranscriptFileLayout(target.parent)
    key = layout.bind_existing_path(target)
    store = create_agent_transcript_file_store(layout)
    try:
        revision = (await store.load(key)).snapshot.revision
        await store.delete(
            key,
            expected_revision=revision,
            operation_id=f"delete:{key.namespace}:{key.conversation_id}:{revision}",
        )
    except StoreNotFoundError:
        return False
    return True


def _lifecycle_session(
    context: AgentTranscriptLifecycleContext,
    transcript: AgentTranscriptUnitOfWork,
    runtime_binding: AgentTranscriptRuntimeBinding[ProductBindingT],
) -> AgentTranscriptLifecycleSession[ProductBindingT]:
    labels_by_target_id, label_timestamps_by_target_id = (
        build_agent_transcript_label_indexes(transcript.records)
    )
    return AgentTranscriptLifecycleSession(
        context=context,
        transcript=transcript,
        runtime_binding=runtime_binding,
        labels_by_target_id=labels_by_target_id,
        label_timestamps_by_target_id=label_timestamps_by_target_id,
    )


def _default_session_filename(header: ConversationHeader) -> str:
    timestamp = header.created_at.replace(":", "-").replace(".", "-")
    return f"{timestamp}_{header.conversation_id}.jsonl"


def _default_id() -> str:
    return uuid4().hex[:8]


__all__ = [
    "AgentTranscriptLifecycle",
    "AgentTranscriptLifecycleContext",
    "AgentTranscriptLifecycleSession",
    "AgentTranscriptRuntimeBinding",
    "delete_agent_transcript_jsonl",
]
