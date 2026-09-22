"""Lifecycle assembly for one optional Agent transcript session.

Products provide the selected store/profile binding and their own header
policy. This module owns the durable create, restore, detached restore, fork,
and disposal mechanics shared by Conversation JSONL Agent transcripts.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar
from uuid import uuid4

from loushang.harness.artifacts import (
    SessionBlobHealth,
    SessionBlobRef,
    session_blob_authority_id,
)
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    ConversationStore,
    StoreNotFoundError,
)
from loushang.harness.conversation.store import ConversationOperationScope
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
    load_agent_transcript_file,
    load_agent_transcript_header,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile
from loushang.harness.transcript.session_artifacts import (
    inspect_agent_transcript_session_blobs,
)
from loushang.harness.transcript.session_catalog import (
    agent_transcript_header_cwd,
    build_agent_transcript_label_indexes,
    same_agent_transcript_session_path,
)
from loushang.harness.transcript.types import AgentTranscriptRecord
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork

if TYPE_CHECKING:
    from loushang.harness.journal._rooted_io import RootedFileIO
    from loushang.harness.runtime import RuntimeProfileSnapshot
    from loushang.harness.transcript.compaction import (
        AgentTranscriptCompactionCapability,
    )
    from loushang.harness.transcript.writer_lease import TranscriptWriterLease
    from loushang.harness.transcript.writer_lifecycle import TranscriptWriterPreparation

BindingInputT = TypeVar("BindingInputT")
ProductBindingT = TypeVar("ProductBindingT")

IdFactory = Callable[[], str]
AsyncDisposer = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class AgentTranscriptBindingOwner:
    """Binding-time projections of an existing owner, not another lifetime."""

    retain_disposer: Callable[[AsyncDisposer], None]
    operation_scope: ConversationOperationScope
    file_io: RootedFileIO | None = None

    def __call__(self, disposer: AsyncDisposer) -> None:
        self.retain_disposer(disposer)


class _WriterLifecycleOwner(Protocol):
    def _mark_import_delivered(self) -> None: ...

    @property
    def blob_file_io(self) -> RootedFileIO | None: ...

    @property
    def transcript_file_io(self) -> RootedFileIO | None: ...

    @property
    def closing(self) -> bool: ...

    def _operation_scope(
        self, target: ConversationKey | str,
    ) -> AbstractAsyncContextManager[None]: ...

    def _sync_operation_scope(
        self, target: ConversationKey | str,
    ) -> AbstractContextManager[None]: ...

    async def _dispose_bound_resources(self) -> None: ...


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
        session_file = None
        if self.session_file is not None:
            absolute = Path(os.path.abspath(Path(self.session_file).expanduser()))
            # Keep the selected leaf intact for the Store's no-follow checks.
            session_file = absolute.parent.resolve(strict=False) / absolute.name
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
    runtime_profile_snapshot: RuntimeProfileSnapshot | None = None
    get_compaction_capability: (
        Callable[[], AgentTranscriptCompactionCapability] | None
    ) = None


@dataclass
class AgentTranscriptLifecycleSession(Generic[ProductBindingT]):
    """A bound transcript plus the Product lease that must be released."""

    context: AgentTranscriptLifecycleContext
    transcript: AgentTranscriptUnitOfWork
    runtime_binding: AgentTranscriptRuntimeBinding[ProductBindingT]
    labels_by_target_id: dict[str, str]
    label_timestamps_by_target_id: dict[str, str]
    session_blob_health: tuple[SessionBlobHealth, ...] = ()
    _disposed: bool = field(default=False, init=False, repr=False)
    _writer_owner: _WriterLifecycleOwner | None = field(default=None, init=False, repr=False)
    _ownership_state: str = field(default="root_owned", init=False, repr=False)
    _dispose_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )

    @property
    def product_binding(self) -> ProductBindingT:
        return self.runtime_binding.product_binding

    def _mark_import_delivered(self) -> None:
        if self._writer_owner is not None:
            self._writer_owner._mark_import_delivered()

    @property
    def ownership_state(self) -> str:
        return self._ownership_state

    @property
    def blob_file_io(self) -> RootedFileIO | None:
        """Borrowed storage projection; callers must enter operation_scope."""
        return self._writer_owner.blob_file_io if self._writer_owner is not None else None

    @property
    def transcript_file_io(self) -> RootedFileIO | None:
        """Borrow the original transcript port inside operation_scope only."""
        return self._writer_owner.transcript_file_io if self._writer_owner is not None else None

    @asynccontextmanager
    async def operation_scope(self) -> AsyncIterator[None]:
        """Keep Product-side effects inside the existing writer lifetime.

        This is admission/drain, not authorization of additional storage roots.
        Legacy unowned bindings retain their existing behavior. Nested Store
        calls must still acquire their own admission and respect closing.
        """
        if self._writer_owner is None:
            yield
        else:
            async with self._writer_owner._operation_scope(self.runtime_binding.key):
                yield

    @contextmanager
    def sync_operation_scope(self) -> Iterator[None]:
        """Borrow the same admission for synchronous, owning-loop consumers."""
        if self._writer_owner is None:
            yield
        else:
            with self._writer_owner._sync_operation_scope(self.runtime_binding.key):
                yield

    def _begin_graph_construction(self) -> None:
        if self._ownership_state != "root_owned" or (self._writer_owner is not None and self._writer_owner.closing):
            raise RuntimeError("transcript candidate is not root-owned")
        self._ownership_state = "graph_constructing"

    def _commit_graph_ownership(self) -> None:
        if self._ownership_state != "graph_constructing":
            raise RuntimeError("transcript candidate is not being graph-constructed")
        self._ownership_state = "graph_owned"

    def _restore_root_ownership(self) -> None:
        if self._ownership_state != "graph_constructing":
            raise RuntimeError("transcript candidate cannot restore root ownership")
        self._ownership_state = "root_owned"

    def _rollback_unpublished_graph_ownership(self) -> None:
        """Return a not-yet-returned Provider value to its construction root."""

        if self._ownership_state not in {"graph_constructing", "graph_owned"}:
            raise RuntimeError("transcript candidate is not unpublished")
        self._ownership_state = "root_owned"

    async def _dispose_graph_owned(self) -> None:
        await self._dispose_owned("graph_owned")

    async def dispose(self) -> None:
        """Release the Product runtime binding exactly once."""

        if self._ownership_state in {"graph_owned", "graph_constructing"}:
            # Graph construction/release owns this binding. The Product wrapper
            # may still run its compatibility disposer after Graph retirement.
            return
        await self._dispose_owned("root_owned")

    async def _dispose_owned(self, expected_state: str) -> None:
        async with self._dispose_lock:
            if self._ownership_state == "disposed":
                return
            if self._ownership_state != expected_state:
                raise RuntimeError(
                    "transcript candidate ownership changed during disposal"
                )
            if self._writer_owner is None:
                await self.runtime_binding.dispose()
            else:
                await self._writer_owner._dispose_bound_resources()
            self._ownership_state = "disposed"
            self._disposed = True


RuntimeBinder = Callable[
    [AgentTranscriptLifecycleContext, BindingInputT],
    Awaitable[AgentTranscriptRuntimeBinding[ProductBindingT]],
]
OwnedRuntimeBinder = Callable[
    [AgentTranscriptLifecycleContext, BindingInputT, AgentTranscriptBindingOwner],
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
        bind_runtime_owned: OwnedRuntimeBinder[BindingInputT, ProductBindingT] | None = None,
        header_loader: HeaderLoader = load_agent_transcript_header,
        snapshot_loader: SnapshotLoader = load_agent_transcript_file,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._bind_runtime = bind_runtime
        self._bind_runtime_owned = bind_runtime_owned
        self._header_loader = header_loader
        self._snapshot_loader = snapshot_loader
        self._id_factory = id_factory or _default_id

    def prepare_owned_writer(
        self, context: AgentTranscriptLifecycleContext, binding_input: BindingInputT, *,
        product_id: str, records: Sequence[AgentTranscriptRecord] = (),
        leaf_id: str | None = None, defer_materialization: bool = True,
        manage_blobs: bool = False,
        initial_blobs: Sequence[tuple[SessionBlobRef, bytes]] = (),
        create_root: bool = False,
        expected_root_identity: tuple[int, int] | None = None,
        expected_parent_identity: tuple[int, int] | None = None,
        store_state_root: Path | None = None,
        initialize_store: bool = False,
        store_root_observed: Event | None = None,
    ) -> TranscriptWriterPreparation[BindingInputT, ProductBindingT]:
        """Purely prepare acquisition; callers retain this before the first await.

        The same preparation owns even a failed acquire before claim. Its
        retained driver, not the factory, performs acquire/borrow/claim.
        Optional root creation is create-only and chooses no default paths.
        """
        from loushang.harness.transcript.writer_lifecycle import (
            TranscriptWriterPreparation,
        )

        return TranscriptWriterPreparation(
            self, context, binding_input, writer=None, product_id=product_id,
            records=records, leaf_id=leaf_id, defer_materialization=defer_materialization,
            manage_blobs=manage_blobs,
            initial_blobs=initial_blobs,
            create_root=create_root,
            expected_root_identity=expected_root_identity, expected_parent_identity=expected_parent_identity,
            store_state_root=store_state_root, initialize_store=initialize_store,
            store_root_observed=store_root_observed,
        )

    def prepare_writer(
        self, context: AgentTranscriptLifecycleContext, binding_input: BindingInputT, *,
        writer: TranscriptWriterLease, product_id: str,
        records: Sequence[AgentTranscriptRecord] = (), leaf_id: str | None = None,
        defer_materialization: bool = True,
        manage_blobs: bool = False,
    ) -> TranscriptWriterPreparation[BindingInputT, ProductBindingT]:
        """Claim an already held writer for an explicit, retained construction.

        Only direct-root persistent contexts and pure binding inputs are valid.
        The trusted binder must map this key to the claimed physical root.
        ``manage_blobs`` adds a second lifetime writer for the shared data root;
        it does not automatically wire existing pathname-based blob consumers.
        Default create/restore and Product factories are not activated here.
        """
        from loushang.harness.transcript.writer_lifecycle import (
            TranscriptWriterPreparation,
        )

        owner = TranscriptWriterPreparation(
            self, context, binding_input, writer=writer, product_id=product_id,
            records=records, leaf_id=leaf_id, defer_materialization=defer_materialization,
            manage_blobs=manage_blobs,
        )
        writer._claim(owner, root=context.session_dir, product_id=product_id,
                      conversation_id=context.header.conversation_id)
        return owner

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

        root = Path(session_dir).expanduser().resolve(strict=False)
        target = (root / _default_session_filename(header)).resolve(strict=False)
        if target.parent != root:
            raise ValueError("session filename escapes the selected session directory")
        return target

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
        defer_materialization: bool = True,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Create one bound transcript and release its lease on failure."""

        if type(defer_materialization) is not bool:
            raise TypeError("defer_materialization must be a boolean")
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
                defer_materialization=context.persist
                and defer_materialization
                and not records,
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


class TranscriptDeletionOwner(Protocol):
    """Caller-retained maintenance authority, including failed cleanup debt."""

    async def delete_transcript(
        self, session_file: str | Path, *, current_session_file: str | Path | None = None,
    ) -> bool: ...


async def delete_agent_transcript_jsonl(
    session_file: str | Path,
    *,
    current_session_file: str | Path | None = None,
    maintenance_owner: TranscriptDeletionOwner | None = None,
) -> bool:
    """Delete through retained maintenance; Linux requires explicit ownership."""

    if maintenance_owner is not None:
        return await maintenance_owner.delete_transcript(
            session_file, current_session_file=current_session_file,
        )
    if sys.platform == "linux":
        raise ValueError("Linux transcript deletion requires a retained maintenance_owner")

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
    *,
    blob_file_io: RootedFileIO | None = None,
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
        session_blob_health=inspect_agent_transcript_session_blobs(
            session_dir=context.session_dir,
            session_id=context.header.conversation_id,
            records=transcript.records,
            file_io=blob_file_io,
            read_only=not context.persist,
        ),
    )


def _default_session_filename(header: ConversationHeader) -> str:
    timestamp = header.created_at.replace(":", "-").replace(".", "-")
    return f"{timestamp}_{session_blob_authority_id(header.conversation_id)}.jsonl"


def _default_id() -> str:
    return uuid4().hex[:8]


__all__ = [
    "AgentTranscriptLifecycle",
    "AgentTranscriptLifecycleContext",
    "AgentTranscriptLifecycleSession",
    "AgentTranscriptRuntimeBinding",
    "delete_agent_transcript_jsonl",
]
