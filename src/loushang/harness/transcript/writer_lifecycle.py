"""Explicit retained construction and lease-last disposal for writer Sessions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from pathlib import Path
from threading import Event
from typing import Generic, TypeVar
from uuid import uuid4

from loushang.harness.artifacts import (
    SessionBlobPublication,
    SessionBlobRef,
    SessionBlobStore,
)
from loushang.harness.artifacts._writer_lease import SessionBlobWriterLease
from loushang.harness.conversation import (
    ConversationKey,
    DeletionReceipt,
    StoreAlreadyExistsError,
    StoreCommitOutcomeUnknown,
    StoreDataError,
)
from loushang.harness.conversation.stores.file import FileConversationStore
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.journal._rooted_io import RootedFileIO

from .jsonl_file import AgentTranscriptFileLayout, load_agent_transcript_header
from .lifecycle import (
    AgentTranscriptBindingOwner,
    AgentTranscriptLifecycle,
    AgentTranscriptLifecycleContext,
    AgentTranscriptLifecycleSession,
    AgentTranscriptRuntimeBinding,
    AsyncDisposer,
    _lifecycle_session,
)
from .store_admission import TranscriptStoreAdmission
from .types import AgentTranscriptRecord
from .unit_of_work import AgentTranscriptUnitOfWork
from .writer_lease import TranscriptWriterError, TranscriptWriterLease

InputT = TypeVar("InputT")
ProductT = TypeVar("ProductT")
TaskT = TypeVar("TaskT")


class TranscriptWriterPreparation(Generic[InputT, ProductT]):
    """Retain one construction intent and release its writer after its runtime.

    Only trusted binders whose disposer settles all their admitted work may use
    this seam. Scoped Store references drain before disposal; independently
    constructed unscoped Stores require separate authority. ``manage_blobs``
    adds attachment lifetime exclusion and retains its physical root, but does
    not retrofit descriptor-relative IO into independently created BlobStores.
    Callers retain the preparation before awaiting create/restore or disposal.
    """

    def __init__(
        self, lifecycle: AgentTranscriptLifecycle[InputT, ProductT],
        context: AgentTranscriptLifecycleContext, binding_input: InputT, *,
        writer: TranscriptWriterLease | None, product_id: str,
        records: Sequence[AgentTranscriptRecord], leaf_id: str | None, defer_materialization: bool,
        manage_blobs: bool = False,
        initial_blobs: Sequence[tuple[SessionBlobRef, bytes]] = (),
        create_root: bool = False,
        expected_root_identity: tuple[int, int] | None = None,
        expected_parent_identity: tuple[int, int] | None = None,
        store_state_root: Path | None = None,
        initialize_store: bool = False,
        store_root_observed: Event | None = None,
    ) -> None:
        if (type(context) is not AgentTranscriptLifecycleContext or not context.persist
                or context.session_file is None or context.session_file.parent != context.session_dir
                or (writer is not None and type(writer) is not TranscriptWriterLease)
                or type(product_id) is not str or not product_id.strip()
                or type(defer_materialization) is not bool or type(manage_blobs) is not bool
                or type(create_root) is not bool or (create_root and writer is not None)):
            raise TranscriptWriterError("invalid")
        if writer is not None and (expected_root_identity is not None or expected_parent_identity is not None):
            raise TranscriptWriterError("invalid")
        if (type(initialize_store) is not bool or (initialize_store and store_state_root is None)
                or (store_state_root is not None and (writer is not None or create_root
                    or expected_root_identity is not None or expected_parent_identity is not None))):
            raise TranscriptWriterError("invalid")
        self._store_admission = (TranscriptStoreAdmission(
            context.session_dir, state_root=store_state_root, create_if_missing=initialize_store,
            root_observed=store_root_observed,
        ) if store_state_root is not None else None)
        self._admission_cleanup_task: asyncio.Task[None] | None = None
        self._context = deepcopy(context)
        self._input, self._records = deepcopy(binding_input), deepcopy(tuple(records))
        self._initial_blobs = deepcopy(tuple((reference, bytes(payload)) for reference, payload in initial_blobs))
        if self._initial_blobs and (not manage_blobs or lifecycle._bind_runtime_owned is None):
            raise TranscriptWriterError("invalid")
        self._publication: SessionBlobPublication | None = None
        self._preserve_publication = False
        self._publication_rollback_task: asyncio.Task[None] | None = None
        self._import_create_operation: str | None = None
        self._import_delete_operation: str | None = None
        self._import_revision: int | None = None
        self._import_identity: tuple[int, int] | None = None
        self._import_delivered = self._import_unknown = False
        self._import_delete_task: asyncio.Task[None] | None = None
        self._import_delete_receipt: DeletionReceipt | None = None
        self._internal_writer = writer is None
        self._create_root = create_root
        self._writer = writer if writer is not None else TranscriptWriterLease(
            context.session_dir, product_id, context.header.conversation_id, create_root=create_root,
            expected_root_identity=expected_root_identity, expected_parent_identity=expected_parent_identity,
        )
        self._lifecycle, self._product = lifecycle, product_id
        self._leaf, self._defer = leaf_id, defer_materialization
        self._loop: asyncio.AbstractEventLoop | None = None
        self._driver: asyncio.Task[AgentTranscriptLifecycleSession[ProductT]] | None = None
        self._runtime_task: asyncio.Task[None] | None = None
        self._io_cleanup_task: asyncio.Task[None] | None = None
        self._blob_io_cleanup_task: asyncio.Task[None] | None = None
        self._blob_close_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._runtime: AgentTranscriptRuntimeBinding[ProductT] | None = None
        self._retained_disposer: AsyncDisposer | None = None
        self._retain_open = False
        self._session: AgentTranscriptLifecycleSession[ProductT] | None = None
        self._mode: str | None = None
        self._cleanup_lock = asyncio.Lock()
        self._active_io = 0
        self._io_drained = asyncio.Event()
        self._io_drained.set()
        self._file_io = None
        # Pure construction: the existing preparation exclusively retains this
        # second lease before any native acquire, including failed admissions.
        self._blob_writer = (
            SessionBlobWriterLease(context.session_dir.parent, product_id, context.header.conversation_id,
                                   expected_root_identity=self._writer._expected_parent_identity)
            if manage_blobs else None
        )
        self._blob_file_io = None
        if lifecycle._bind_runtime_owned is not None:
            if lifecycle._header_loader is not load_agent_transcript_header:
                raise TranscriptWriterError("invalid")
            if writer is not None:
                self._file_io = writer._borrow_file_io(
                    root=context.session_dir, product_id=product_id, conversation_id=context.header.conversation_id,
                )
        self._binding_owner = AgentTranscriptBindingOwner(self._retain_disposer, self._operation_scope, self._file_io)
        self._binding_started = self._runtime_done = self._closing = self._unknown = False

    @property
    def closing(self) -> bool:
        return self._closing

    @property
    def blob_file_io(self) -> RootedFileIO | None:
        return self._blob_file_io

    @property
    def transcript_file_io(self) -> RootedFileIO | None:
        return self._file_io

    @property
    def cleanup_pending(self) -> bool:
        return (self._writer.cleanup_pending or self._unknown or self._import_unknown or self._active_io > 0
                or (self._import_create_operation is not None and not self._import_delivered
                    and self._import_revision is not None and self._import_delete_receipt is None)
                or (self._store_admission is not None and self._store_admission.cleanup_pending)
                or (self._publication is not None and not self._preserve_publication)
                or (self._blob_writer is not None and self._blob_writer.cleanup_pending)
                or (self._blob_file_io is not None and self._blob_file_io.cleanup_pending)
                or (self._file_io is not None and self._file_io.cleanup_pending)
                or any(task is not None and not task.done() for task in (self._driver, self._runtime_task, self._close_task))
                or (self._driver is not None and self._driver.cancelled())
                or (self._io_cleanup_task is not None and not self._io_cleanup_task.done())
                or any(task is not None and not task.done()
                       for task in (self._blob_io_cleanup_task, self._blob_close_task, self._publication_rollback_task))
                or any(task is not None and task.done() and (task.cancelled() or task.exception() is not None)
                       for task in (self._runtime_task, self._io_cleanup_task, self._blob_io_cleanup_task,
                                    self._blob_close_task, self._close_task, self._publication_rollback_task))
                or ((self._runtime is not None or self._retained_disposer is not None) and not self._runtime_done))

    def _prepare_import_rollback(self) -> None:
        """Arm only this fresh preparation before any binding or create effect."""
        if self._driver is not None or self._import_create_operation is not None or self._defer:
            raise TranscriptWriterError("invalid")
        nonce = uuid4().hex
        self._import_create_operation = f"import-create:{nonce}"
        self._import_delete_operation = f"import-abort:{nonce}"

    def _mark_import_delivered(self) -> None:
        # A conservative, monotonic disarm at the original lifecycle's delivery
        # cut. It must never throw after that lifecycle has installed the slot.
        self._import_delivered = True

    def _on_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise TranscriptWriterError("conflict")
        claimed = self._writer.claimed_owner
        if claimed is not self and not (self._internal_writer and claimed is None):
            raise TranscriptWriterError("closed")

    async def create(self) -> AgentTranscriptLifecycleSession[ProductT]:
        return await self._join("create")

    async def restore(self) -> AgentTranscriptLifecycleSession[ProductT]:
        if (self._create_root or self._records or self._leaf is not None or not self._defer or self._initial_blobs
                or (self._store_admission is not None and self._store_admission._create)):
            raise TranscriptWriterError("invalid")
        return await self._join("restore")

    async def _join(self, mode: str) -> AgentTranscriptLifecycleSession[ProductT]:
        self._on_loop()
        if self._closing:
            raise TranscriptWriterError("closed")
        if self._mode is not None and self._mode != mode:
            raise TranscriptWriterError("conflict")
        if self._driver is None:
            self._mode = mode
            self._driver = _task(self._build(mode))
        result = await asyncio.shield(self._driver)
        if self._closing or result.ownership_state != "root_owned":
            raise TranscriptWriterError("closed")
        return result

    async def _build(self, mode: str) -> AgentTranscriptLifecycleSession[ProductT]:
        context = self._context
        assert context.session_file is not None
        if self._internal_writer:
            await settled_io(self._acquire_writer)
        await settled_io(self._writer.check, product_id=self._product, conversation_id=context.header.conversation_id)
        if self._blob_writer is not None:
            await settled_io(self._acquire_blob_writer)
        if self._import_create_operation is not None:
            await settled_io(self._require_fresh_import_path)
        if self._initial_blobs:
            async with self._operation_scope(str(context.session_dir)):
                self._publication = SessionBlobStore(
                    context.session_dir.parent, context.header.conversation_id, file_io=self._blob_file_io,
                ).import_blobs(self._initial_blobs, require_new_authority=True)
        if mode == "restore":
            header = (
                await settled_io(load_agent_transcript_header, context.session_file, read_only=True, file_io=self._file_io)
                if self._file_io is not None else
                await settled_io(self._lifecycle._header_loader, context.session_file)
            )
            if header != context.header:
                raise TranscriptWriterError("conflict")
        self._binding_started = True
        if self._lifecycle._bind_runtime_owned is None:
            self._runtime = await self._lifecycle._bind_runtime(context, self._input)
        else:
            self._retain_open = True
            try:
                self._runtime = await self._lifecycle._bind_runtime_owned(context, self._input, self._binding_owner)
            finally:
                self._retain_open = False
            if self._retained_disposer is not self._runtime.dispose:
                # Keep both receipts; conflicting authorities cannot prove release.
                self._unknown = True
                raise TranscriptWriterError("conflict")
        expected = ConversationKey(str(context.session_dir), context.header.conversation_id)
        if self._runtime.key != expected:
            raise TranscriptWriterError("conflict")
        if self._import_create_operation is not None:
            if not isinstance(self._runtime.store, FileConversationStore):
                raise StoreDataError("import rollback requires the original rooted FileStore")
            self._runtime.store.retain_creation_identity(self._runtime.key, self._import_create_operation)
        if mode == "create":
            try:
                transcript = await AgentTranscriptUnitOfWork.create(
                    self._runtime.store, self._runtime.key, context.header, records=self._records,
                    leaf_id=self._leaf, id_factory=self._lifecycle._id_factory, profile=self._runtime.profile,
                    defer_materialization=self._defer and not self._records and not self._initial_blobs,
                    create_operation_id=self._import_create_operation,
                )
            except StoreCommitOutcomeUnknown:
                self._preserve_publication = True
                if self._import_create_operation is not None:
                    self._import_unknown = True
                raise
            else:
                self._preserve_publication = True
                if self._import_create_operation is not None:
                    self._import_revision = transcript.revision
                    try:
                        assert isinstance(self._runtime.store, FileConversationStore)
                        self._import_identity = self._runtime.store.created_file_identity(
                            self._runtime.key, self._import_create_operation,
                        )
                    except BaseException:
                        self._import_unknown = True
                        raise
        else:
            transcript = await AgentTranscriptUnitOfWork.load(
                self._runtime.store, self._runtime.key, id_factory=self._lifecycle._id_factory,
                profile=self._runtime.profile,
            )
            if transcript.header != context.header:
                raise TranscriptWriterError("conflict")
        async with self._operation_scope(expected):
            session = _lifecycle_session(context, transcript, self._runtime, blob_file_io=self._blob_file_io)
            session._writer_owner = self
            self._session = session
        return session

    def _acquire_writer(self) -> None:
        """Acquire only the lease exclusively constructed by this preparation."""
        assert self._internal_writer
        if self._store_admission is not None:
            try:
                binding = self._store_admission.open()
            except BaseException as error:
                try:
                    self._store_admission.close()
                except BaseException as cleanup_error:
                    error.add_note(f"store admission cleanup retained: {type(cleanup_error).__name__}")
                raise
            else:
                self._writer._expected_root_identity = binding.root_identity
                self._writer._expected_parent_identity = binding.parent_identity
                if self._blob_writer is not None:
                    self._blob_writer._expected_root_identity = binding.parent_identity
                    if binding.shared_identities is not None:
                        self._blob_writer._expected_directory_identity = binding.shared_identities[2]
                # The store lock never covers Session runtime construction or
                # lifetime; all later IO is guarded by the original writers.
                self._store_admission.release_locks()
        self._writer.acquire()
        if self._lifecycle._bind_runtime_owned is not None:
            self._file_io = self._writer._borrow_file_io(
                root=self._context.session_dir, product_id=self._product,
                conversation_id=self._context.header.conversation_id,
            )
        self._writer._claim(
            self, root=self._context.session_dir, product_id=self._product,
            conversation_id=self._context.header.conversation_id,
        )
        self._binding_owner = AgentTranscriptBindingOwner(self._retain_disposer, self._operation_scope, self._file_io)

    def _close_writer(self) -> None:
        if self._store_admission is not None:
            self._store_admission.close()
        claimed = self._writer.claimed_owner
        if claimed is self:
            self._writer._close_claimed(self)
        elif self._internal_writer and claimed is None:
            self._writer.close()
        else:
            raise TranscriptWriterError("conflict")

    def _acquire_blob_writer(self) -> None:
        assert self._blob_writer is not None
        self._blob_writer.acquire()
        directories: tuple[tuple[tuple[int, int], str, tuple[int, int]], ...] = ()
        if self._store_admission is not None:
            binding = self._store_admission._binding
            if binding is not None and binding.shared_identities is not None:
                assets, locks, _ = binding.shared_identities
                directories = ((binding.parent_identity, "session-assets", assets), (assets, ".locks", locks))
        self._blob_file_io = self._blob_writer.borrow_file_io(
            data_root=self._context.session_dir.parent,
            owner_id=self._product, session_id=self._context.header.conversation_id,
            directory_bindings=directories,
        )
        self._blob_writer._claim_binding(
            self, root=self._context.session_dir.parent,
            owner_id=self._product, authority_id=self._blob_writer._authority_id,
        )

    def _check_writers(self) -> None:
        self._writer.check(product_id=self._product, conversation_id=self._context.header.conversation_id)
        if self._blob_writer is not None:
            self._blob_writer.check(owner_id=self._product, session_id=self._context.header.conversation_id)

    def _close_blob_writer(self) -> None:
        assert self._blob_writer is not None
        if self._blob_writer.claimed_owner is self:
            self._blob_writer._close_claimed(self)
        else:
            # A failed acquisition may precede claim; this is still the same
            # exclusively constructed lease, never an externally supplied one.
            self._blob_writer.close()

    def _retain_disposer(self, disposer: AsyncDisposer) -> None:
        self._on_loop()
        if asyncio.current_task() is not self._driver:
            raise TranscriptWriterError("closed")
        if not self._retain_open or self._retained_disposer is not None:
            raise TranscriptWriterError("closed")
        if not callable(disposer):
            raise TranscriptWriterError("invalid")
        self._retained_disposer = disposer

    @contextmanager
    def _admission_scope(self, target: ConversationKey | str) -> Iterator[None]:
        self._on_loop()
        cleanup_admission = (
            type(target) is ConversationKey and self._import_delete_task is not None
            and asyncio.current_task() is self._import_delete_task
        )
        if self._closing and not cleanup_admission:
            raise TranscriptWriterError("closed")
        expected = ConversationKey(str(self._context.session_dir), self._context.header.conversation_id)
        if ((type(target) is ConversationKey and target != expected)
                or (type(target) is str and target != expected.namespace)
                or type(target) not in (ConversationKey, str)):
            raise TranscriptWriterError("conflict")
        self._active_io += 1
        self._io_drained.clear()
        try:
            yield
        finally:
            self._active_io -= 1
            if self._active_io == 0:
                self._io_drained.set()

    @asynccontextmanager
    async def _operation_scope(self, target: ConversationKey | str) -> AsyncIterator[None]:
        with self._admission_scope(target):
            await settled_io(self._check_writers)
            yield

    @contextmanager
    def _sync_operation_scope(self, target: ConversationKey | str) -> Iterator[None]:
        """Admit existing synchronous consumers on the owning event loop only."""
        with self._admission_scope(target):
            self._check_writers()
            yield

    def _fence_unpublished(self) -> None:
        """Let the retaining factory stop every undelivered construction first."""
        self._on_loop()
        if self._session is not None and self._session.ownership_state != "root_owned":
            raise TranscriptWriterError("conflict")
        self._closing = True

    async def dispose(self) -> None:
        self._on_loop()
        if self._session is not None:
            await self._session.dispose()  # Graph ownership is authoritative; no root fence first.
            return
        self._closing = True
        if self._driver is not None:
            try:
                await asyncio.shield(self._driver)
            except asyncio.CancelledError:
                if not self._driver.cancelled():
                    raise
                self._unknown = True
            except Exception:
                pass  # Binding, if returned, is retained below for explicit cleanup.
        if self._session is not None:
            await self._session.dispose()
        else:
            await self._dispose_bound_resources()

    async def _dispose_bound_resources(self) -> None:
        self._on_loop()
        self._closing = True
        async with self._cleanup_lock:
            await self._io_drained.wait()
            await self._dispose_stages()

    async def _dispose_runtime(self) -> None:
        if self._retained_disposer is not None:
            await self._retained_disposer()
        else:
            assert self._runtime is not None
            await self._runtime.dispose()

    def _rollback_import(self) -> None:
        publication = self._publication
        assert publication is not None and not self._preserve_publication
        if publication.rollback_delegated:
            assert self._blob_file_io is not None
            self._blob_file_io.cleanup()
            if not publication.rollback_complete:
                raise TranscriptWriterError("unavailable")
        elif not publication.rollback():
            raise TranscriptWriterError("conflict")

    def _check_import_target(self) -> None:
        self._check_writers()
        assert self._file_io is not None and self._context.session_file is not None
        status = self._file_io.stat(self._context.session_file)
        if (status.st_dev, status.st_ino) != self._import_identity:
            raise TranscriptWriterError("conflict")

    def _require_fresh_import_path(self) -> None:
        assert self._file_io is not None and self._context.session_file is not None
        try:
            self._file_io.stat(self._context.session_file)
        except FileNotFoundError:
            pass
        else:
            raise StoreAlreadyExistsError("import destination already exists")
        layout = AgentTranscriptFileLayout(self._context.session_dir, file_io=self._file_io)
        scan = layout.scan_candidate_path_snapshot(layout.namespace, raise_on_error=True)
        if not scan.complete:
            raise TranscriptWriterError("conflict")
        for path in scan.paths:
            header = load_agent_transcript_header(path, read_only=True, file_io=self._file_io)
            if header.conversation_id == self._context.header.conversation_id:
                raise StoreAlreadyExistsError("import conversation identity already exists")

    async def _delete_unpublished_import(self) -> None:
        assert self._runtime is not None and self._import_revision is not None
        assert self._import_delete_operation is not None
        assert self._import_identity is not None
        try:
            store = self._runtime.store
            if not isinstance(store, FileConversationStore):
                raise StoreDataError("import rollback requires the original rooted FileStore")
            await settled_io(self._check_import_target)
            receipt = await store.delete(
                self._runtime.key, expected_revision=self._import_revision,
                operation_id=self._import_delete_operation,
                expected_file_identity=self._import_identity,
            )
            if (type(receipt) is not DeletionReceipt
                    or receipt.operation_id != self._import_delete_operation
                    or receipt.revision != self._import_revision):
                raise StoreCommitOutcomeUnknown("import rollback deletion receipt is invalid")
        except StoreDataError:
            # The original Store classifies pre-commit data failures separately
            # from unknown commits. Only this known failure can retry its op.
            raise
        except BaseException:
            self._import_unknown = True
            raise
        self._import_delete_receipt = receipt
        self._preserve_publication = False

    async def _settle_import_rollback(self) -> None:
        if self._import_create_operation is None or self._import_delivered:
            return
        if self._import_unknown:
            raise TranscriptWriterError("unavailable")
        if self._import_revision is None or self._import_delete_receipt is not None:
            return
        task = self._import_delete_task
        if task is not None and task.cancelled():
            self._import_unknown = True
            raise TranscriptWriterError("unavailable")
        if task is None or (task.done() and task.exception() is not None):
            self._import_delete_task = _task(self._delete_unpublished_import())
        assert self._import_delete_task is not None
        await asyncio.shield(self._import_delete_task)

    async def _dispose_stages(self) -> None:
        if self._binding_started and self._runtime is None and self._retained_disposer is None:
            self._unknown = True
        if self._unknown:
            raise TranscriptWriterError("unavailable")
        if (self._runtime is not None or self._retained_disposer is not None) and not self._runtime_done:
            if self._runtime_task is not None and self._runtime_task.cancelled():
                self._unknown = True
                raise TranscriptWriterError("unavailable")
            if self._runtime_task is None or (self._runtime_task.done() and self._runtime_task.exception() is not None):
                self._runtime_task = _task(self._dispose_runtime())
            await asyncio.shield(self._runtime_task)
            self._runtime_done = True
        await self._settle_import_rollback()
        if ((self._publication is not None and not self._preserve_publication)
                or self._publication_rollback_task is not None):
            if self._publication_rollback_task is not None and self._publication_rollback_task.cancelled():
                self._unknown = True
                raise TranscriptWriterError("unavailable")
            if (self._publication_rollback_task is None
                    or (self._publication_rollback_task.done() and self._publication_rollback_task.exception() is not None)):
                self._publication_rollback_task = _task(settled_io(self._rollback_import))
            await asyncio.shield(self._publication_rollback_task)
            self._publication = None
        if self._file_io is not None:
            if self._io_cleanup_task is not None and self._io_cleanup_task.cancelled():
                self._unknown = True
                raise TranscriptWriterError("unavailable")
            if (self._io_cleanup_task is None
                    or (self._io_cleanup_task.done() and self._io_cleanup_task.exception() is not None)):
                self._io_cleanup_task = _task(settled_io(self._file_io.cleanup))
            await asyncio.shield(self._io_cleanup_task)
            if self._file_io.cleanup_pending:
                raise TranscriptWriterError("unavailable")
        if self._blob_file_io is not None:
            if self._blob_io_cleanup_task is not None and self._blob_io_cleanup_task.cancelled():
                self._unknown = True
                raise TranscriptWriterError("unavailable")
            if (self._blob_io_cleanup_task is None or
                    (self._blob_io_cleanup_task.done() and self._blob_io_cleanup_task.exception() is not None)):
                self._blob_io_cleanup_task = _task(settled_io(self._blob_file_io.cleanup))
            await asyncio.shield(self._blob_io_cleanup_task)
            if self._blob_file_io.cleanup_pending:
                raise TranscriptWriterError("unavailable")
        if self._blob_writer is not None:
            if self._store_admission is not None:
                if self._admission_cleanup_task is not None and self._admission_cleanup_task.cancelled():
                    self._unknown = True
                    raise TranscriptWriterError("unavailable")
                if (self._admission_cleanup_task is None or
                        (self._admission_cleanup_task.done() and self._admission_cleanup_task.exception() is not None)):
                    self._admission_cleanup_task = _task(settled_io(self._store_admission.close))
                await asyncio.shield(self._admission_cleanup_task)
            if self._blob_close_task is not None and self._blob_close_task.cancelled():
                self._unknown = True
                raise TranscriptWriterError("unavailable")
            if (self._blob_close_task is None or
                    (self._blob_close_task.done() and self._blob_close_task.exception() is not None)):
                self._blob_close_task = _task(settled_io(self._close_blob_writer))
            await asyncio.shield(self._blob_close_task)
        if self._close_task is not None and self._close_task.cancelled():
            self._unknown = True
            raise TranscriptWriterError("unavailable")
        if self._close_task is None or (self._close_task.done() and self._close_task.exception() is not None):
            self._close_task = _task(settled_io(self._close_writer))
        await asyncio.shield(self._close_task)


def _task(work: Coroutine[object, object, TaskT]) -> asyncio.Task[TaskT]:
    gate = asyncio.get_running_loop().create_future()

    async def invoke() -> TaskT:
        await gate
        return await work

    invocation = invoke()
    try:
        task = asyncio.create_task(invocation)
    except BaseException:
        gate.cancel()
        invocation.close()
        work.close()
        raise

    def finished(task: asyncio.Task[TaskT]) -> None:
        work.close()
        if not task.cancelled():
            task.exception()

    task.add_done_callback(finished)
    gate.set_result(None)
    return task
