"""Product-composed factory for Conversation JSONL Agent transcript sessions.

The factory owns the repeated session assembly sequence: conversation identity,
header construction, Conversation JSONL file context, runtime binding, restore, recent
resume, and branch/fork creation.  Products supply the binding input, their
header metadata, and resume validation without reimplementing that sequence.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Generic, TypeVar
from uuid import uuid4

from loushang.foundation.json import JSONValue
from loushang.harness.artifacts import (
    SessionBlobPublication,
    SessionBlobRef,
    SessionBlobStore,
    resolve_session_blob_data_root,
    session_blob_authority_id,
)
from loushang.harness.conversation import (
    CURRENT_CONVERSATION_FORMAT_VERSION,
    ConversationHeader,
    DeletionReceipt,
    StoreCommitOutcomeUnknown,
)
from loushang.harness.transcript.export.bundle import (
    DEFAULT_TRANSCRIPT_BUNDLE_POLICY,
    AgentTranscriptBundle,
    decode_agent_transcript_bundle,
    read_agent_transcript_bundle,
)
from loushang.harness.transcript.jsonl_file import (
    _read_stable_regular_file,
    decode_agent_transcript_bytes,
    load_agent_transcript_header,
)
from loushang.harness.transcript.lifecycle import (
    AgentTranscriptLifecycle,
    AgentTranscriptLifecycleContext,
    AgentTranscriptLifecycleSession,
)
from loushang.harness.transcript.session_artifacts import (
    clone_agent_transcript_session_blobs,
    collect_agent_transcript_session_blobs,
    replace_agent_transcript_session_blobs,
)
from loushang.harness.transcript.session_catalog import (
    AgentTranscriptSessionCatalog,
    agent_transcript_header_cwd,
    same_agent_transcript_session_path,
)
from loushang.harness.transcript.types import AgentTranscriptRecord

if TYPE_CHECKING:
    from loushang.harness.transcript.writer_lifecycle import TranscriptWriterPreparation

BindingInputT = TypeVar("BindingInputT")
ProductBindingT = TypeVar("ProductBindingT")
SourceProductBindingT = TypeVar("SourceProductBindingT")

BindingInputResolver = Callable[[bool], BindingInputT]
HeaderMetadataFactory = Callable[[BindingInputT], Mapping[str, JSONValue]]
RestoredHeaderValidator = Callable[[ConversationHeader, BindingInputT, bool], None]
SessionFileFactory = Callable[[Path, ConversationHeader], Path | None]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class TranscriptDeletionCleanupPending(RuntimeError):
    """Deletion committed, but its original preparation has not settled."""

    def __init__(self, receipt: DeletionReceipt) -> None:
        self.receipt = receipt
        super().__init__("transcript deletion committed; original cleanup remains pending")


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
        owned_product_id: str | None = None,
        index_writable: bool = True,
        store_state_root: Path | None = None,
        store_root_observed: Event | None = None,
        enroll_legacy_shared_store: bool = False,
    ) -> None:
        if type(index_writable) is not bool:
            raise TypeError("index_writable must be a built-in bool")
        self._index_writable = index_writable and owned_product_id is None
        if type(conversation_version) is not int or conversation_version < 1:
            raise ValueError("conversation version must be a positive integer")
        if owned_product_id is not None and (
            type(owned_product_id) is not str or not owned_product_id.strip()
            or lifecycle._bind_runtime_owned is None
            or lifecycle._header_loader is not load_agent_transcript_header
        ):
            raise ValueError("owned factory requires an explicit Product and rooted runtime binder")
        self._lifecycle = lifecycle
        self._resolve_binding_input = resolve_binding_input
        self._header_metadata = header_metadata
        self._validate_restored_header = validate_restored_header or _validate_nothing
        self._session_file_factory = session_file_factory
        self._conversation_version = conversation_version
        self._clock = clock or _utc_now
        self._conversation_id_factory = conversation_id_factory or _default_id
        self._owned_product_id = owned_product_id
        if type(enroll_legacy_shared_store) is not bool:
            raise TypeError("legacy store enrollment must be a built-in bool")
        if store_state_root is not None and owned_product_id is None:
            raise ValueError("store admission requires an owned persistent factory")
        if enroll_legacy_shared_store and store_state_root is None:
            raise ValueError("legacy store enrollment requires store admission")
        self._store_state_root = store_state_root
        self._store_root_observed = store_root_observed
        self._enroll_legacy_shared_store = enroll_legacy_shared_store
        self._pending: dict[TranscriptWriterPreparation[BindingInputT, ProductBindingT], None] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False

    @property
    def pending_preparations(self) -> tuple[TranscriptWriterPreparation[BindingInputT, ProductBindingT], ...]:
        """Original undelivered/cleanup handles; never a second resource owner."""
        return tuple(self._pending)

    @property
    def owns_persistent_sessions(self) -> bool:
        return self._owned_product_id is not None

    def _on_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("owned factory belongs to another event loop")

    def _accepting(self, *, persist: bool = True) -> None:
        if self._owned_product_id is None:
            return
        self._on_loop()
        if self._closing:
            raise RuntimeError("owned factory is closed")
        if not persist:
            raise ValueError("owned factory transient construction is not yet supported")

    def _reject_unwired(self) -> None:
        self._accepting()
        if self._owned_product_id is not None:
            raise ValueError("owned factory attachment transfer is not yet supported")

    def fence(self) -> None:
        """Stop unpublished construction synchronously before dependent cleanup."""
        if self._owned_product_id is None:
            return
        self._on_loop()
        self._closing = True
        failures: list[Exception] = []
        for owner in tuple(self._pending):
            try:
                owner._fence_unpublished()
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]

    async def close(self) -> None:
        """Fence and settle undelivered constructions, not delivered Sessions."""
        if self._owned_product_id is None:
            return
        self._on_loop()
        failures: list[Exception] = []
        try:
            self.fence()
        except Exception as error:
            failures.append(error)
        for owner in tuple(self._pending):
            try:
                await owner.dispose()
                if owner.cleanup_pending:
                    raise RuntimeError("owned factory cleanup remains pending")
            except Exception as error:
                failures.append(error)
            else:
                self._pending.pop(owner, None)
        if failures:
            raise failures[0]

    def _prepare_owned(
        self, context: AgentTranscriptLifecycleContext, binding_input: BindingInputT, *,
        records: Sequence[AgentTranscriptRecord] = (),
        leaf_id: str | None = None, defer_materialization: bool = True,
        initial_blobs: Sequence[tuple[SessionBlobRef, bytes]] = (),
        create_root: bool = False,
        initialize_store: bool = False,
    ) -> TranscriptWriterPreparation[BindingInputT, ProductBindingT]:
        self._accepting(persist=context.persist)
        assert self._owned_product_id is not None
        owner = self._lifecycle.prepare_owned_writer(
            context, binding_input, product_id=self._owned_product_id, records=records,
            leaf_id=leaf_id, defer_materialization=defer_materialization, manage_blobs=True,
            initial_blobs=initial_blobs,
            create_root=create_root,
            store_state_root=self._store_state_root,
            initialize_store=initialize_store and self._store_state_root is not None,
            store_root_observed=self._store_root_observed,
            enroll_legacy_shared_store=self._enroll_legacy_shared_store,
        )
        self._pending[owner] = None
        return owner

    async def _discard_owned(self, owner: TranscriptWriterPreparation[BindingInputT, ProductBindingT]) -> None:
        await owner.dispose()
        if owner.cleanup_pending:
            raise RuntimeError("owned factory cleanup remains pending")
        self._pending.pop(owner, None)

    async def _discard_failed_owned(
        self, owner: TranscriptWriterPreparation[BindingInputT, ProductBindingT], error: BaseException,
    ) -> None:
        try:
            await self._discard_owned(owner)
        except BaseException as cleanup_error:
            error.add_note(f"owned factory cleanup retained: {type(cleanup_error).__name__}")

    async def _construct_owned(
        self, context: AgentTranscriptLifecycleContext, binding_input: BindingInputT, *,
        restore: bool = False, records: Sequence[AgentTranscriptRecord] = (),
        leaf_id: str | None = None, defer_materialization: bool = True,
        initial_blobs: Sequence[tuple[SessionBlobRef, bytes]] = (),
        create_root: bool = False,
        unpublished_import: bool = False,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        owner = self._prepare_owned(
            context, binding_input, records=records, leaf_id=leaf_id,
            defer_materialization=defer_materialization, initial_blobs=initial_blobs,
            create_root=create_root,
            initialize_store=not restore,
        )
        try:
            if unpublished_import:
                owner._prepare_import_rollback()
            session = await (owner.restore() if restore else owner.create())
            self._accepting()
            if _projection is not None:
                _projection(session)
                self._accepting()
            self._pending.pop(owner)
            return session
        except BaseException as error:
            await self._discard_failed_owned(owner, error)
            raise

    @asynccontextmanager
    async def _owned_source(
        self, context: AgentTranscriptLifecycleContext,
    ) -> AsyncIterator[AgentTranscriptLifecycleSession[ProductBindingT]]:
        binding_input = self._resolve_binding_input(True)
        self._validate_restored_header(context.header, binding_input, True)
        owner = self._prepare_owned(context, binding_input)
        try:
            source = await owner.restore()
            self._accepting()
            yield source
        except BaseException as error:
            await self._discard_failed_owned(owner, error)
            raise
        else:
            # Never deliver this internal source or create a target until its
            # original owner has settled. Failure leaves that owner pending.
            await self._discard_owned(owner)

    def _discover_owned_context(
        self, session_file: str | Path, *, session_dir: str | Path | None = None,
        cwd_override: str | Path | None = None,
    ) -> AgentTranscriptLifecycleContext:
        path = Path(session_file).expanduser().absolute()
        path = path.parent.resolve(strict=False) / path.name
        header = load_agent_transcript_header(path, read_only=True)
        context = self._lifecycle.new_context(
            session_dir=session_dir if session_dir is not None else path.parent,
            cwd=cwd_override if cwd_override is not None else agent_transcript_header_cwd(header),
            persist=True, header=header, session_file=path,
        )
        if context.session_file != path:
            raise ValueError("owned discovery leaf changed during context binding")
        return context

    async def new(
        self,
        *,
        session_dir: str | Path,
        cwd: str | Path,
        persist: bool = True,
        parent_session: str | None = None,
        session_id: str | None = None,
        additional_header_metadata: Mapping[str, JSONValue] | None = None,
        defer_materialization: bool = True,
        create_root: bool = False,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Create one empty transcript with Product-selected runtime metadata."""
        self._accepting(persist=persist)
        if type(create_root) is not bool or (create_root and (not persist or self._owned_product_id is None)):
            raise ValueError("root initialization requires an explicit owned persistent create")
        resolved_session_id = self._resolve_conversation_id(session_id)
        binding_input = self._resolve_binding_input(persist)
        return await self._create(
            session_dir=session_dir,
            cwd=cwd,
            persist=persist,
            binding_input=binding_input,
            conversation_id=resolved_session_id,
            parent_session=parent_session,
            additional_header_metadata=additional_header_metadata,
            defer_materialization=defer_materialization,
            create_root=create_root,
            _projection=_projection,
        )

    async def load(
        self,
        session_file: str | Path,
        *,
        persist: bool = True,
        session_dir: str | Path | None = None,
        cwd_override: str | Path | None = None,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Restore one Conversation JSONL transcript through the selected binding."""
        self._accepting(persist=persist)
        if self._owned_product_id is not None:
            context = self._discover_owned_context(
                session_file, session_dir=session_dir, cwd_override=cwd_override,
            )
            return await self.restore_context(context, _projection=_projection)
        context = self._lifecycle.conversation_jsonl_context(
            session_file,
            persist=persist,
            session_dir=session_dir,
            cwd_override=cwd_override,
        )
        return await self.restore_context(context)

    async def restore_context(
        self,
        context: AgentTranscriptLifecycleContext,
        *, _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Restore an already-bound source without resolving its selected leaf.

        A trusted Product may supply a bounded, verified source context. The
        Product header validator and normal Store acquisition still run here.
        """
        if type(context) is not AgentTranscriptLifecycleContext:
            raise TypeError("invalid transcript lifecycle context")
        self._accepting(persist=context.persist)
        binding_input = self._resolve_binding_input(context.persist)
        self._validate_restored_header(context.header, binding_input, context.persist)
        if self._owned_product_id is not None:
            return await self._construct_owned(context, binding_input, restore=True, _projection=_projection)
        return await self._lifecycle.restore(context, binding_input)

    async def open(
        self,
        session_file: str | Path,
        *,
        session_dir: str | Path | None = None,
        cwd_override: str | Path | None = None,
        persist: bool = True,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Restore a transcript while applying Product-selected path overrides."""

        return await self.load(
            session_file,
            persist=persist,
            session_dir=session_dir,
            cwd_override=cwd_override,
            _projection=_projection,
        )

    async def delete_transcript(
        self, session_file: str | Path, *, current_session_file: str | Path | None = None,
    ) -> bool:
        """Delete through the original retained writer, without deleting blobs.

        The internal source is never delivered: its original preparation stays
        pending through deletion and disposal. Store deletion owns its journal,
        tombstone and projection-index effects. Attachment reclamation requires
        separate uniqueness evidence and is deliberately not implied here.
        """
        self._accepting()
        if self._owned_product_id is None:
            raise ValueError("transcript deletion requires an owned factory")
        target = Path(session_file).expanduser()
        if current_session_file is not None and same_agent_transcript_session_path(
            target, Path(current_session_file).expanduser(),
        ):
            raise ValueError("Cannot delete the currently active session")
        try:
            target.lstat()
        except FileNotFoundError:
            return False
        context = self._discover_owned_context(target)
        receipt = None
        try:
            async with self._owned_source(context) as source:
                async with source.operation_scope():
                    runtime = source.runtime_binding
                    revision = source.transcript.revision
                    operation = f"delete:{runtime.key.namespace}:{runtime.key.conversation_id}:{revision}"
                    result = await runtime.store.delete(
                        runtime.key, expected_revision=revision,
                        operation_id=operation,
                    )
                    if (type(result) is not DeletionReceipt or result.revision != revision
                            or result.operation_id != operation):
                        raise StoreCommitOutcomeUnknown("transcript deletion receipt does not match the request")
                    receipt = result
        except StoreCommitOutcomeUnknown:
            raise  # Preserve the original uncertain commit and its cleanup notes.
        except Exception as error:
            if receipt is not None:
                raise TranscriptDeletionCleanupPending(receipt) from error
            raise
        return True

    async def continue_recent(
        self,
        *,
        session_dir: str | Path,
        cwd: str | Path,
        persist: bool = True,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Resume the most recent Conversation JSONL transcript or create a new one."""
        self._accepting(persist=persist)
        resolved_session_dir = Path(session_dir)
        for summary in AgentTranscriptSessionCatalog(
            resolved_session_dir, index_writable=self._index_writable,
        ).list_summaries():
            if summary.session_file is not None:
                return await self.open(
                    summary.session_file,
                    session_dir=resolved_session_dir,
                    cwd_override=cwd,
                    persist=persist,
                    _projection=_projection,
                )
        return await self.new(
            session_dir=resolved_session_dir,
            cwd=cwd,
            persist=persist,
            _projection=_projection,
        )

    async def in_memory(
        self,
        *,
        cwd: str | Path = ".",
        session_id: str | None = None,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Create a transient transcript without choosing a Product root."""

        return await self.new(
            session_dir=Path(),
            cwd=cwd,
            persist=False,
            session_id=session_id,
            _projection=_projection,
        )

    async def import_bundle(
        self,
        source_file: str | Path,
        *,
        session_dir: str | Path,
        cwd_override: str | Path | None = None,
        persist: bool = True,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Import one portable transcript-and-blob bundle transactionally."""
        self._accepting(persist=persist)
        if self.owns_persistent_sessions:
            raw = _read_stable_regular_file(Path(source_file).expanduser().absolute(), max_bytes=81 * 1024 * 1024)
            bundle = decode_agent_transcript_bundle(raw)
        else:
            bundle = read_agent_transcript_bundle(source_file)
        return await self._import_frozen(
            bundle, session_dir=session_dir, cwd_override=cwd_override,
            persist=persist, _projection=_projection,
        )

    async def import_transcript(
        self,
        source_file: str | Path,
        *,
        session_dir: str | Path,
        cwd_override: str | Path | None = None,
        expected_source_fingerprint: str | None = None,
        _validate_cwd: Callable[[str], None] | None = None,
        _unpublished: bool = False,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Import frozen external JSONL/bundle through the retained writer owner."""
        self._accepting()
        if type(_unpublished) is not bool:
            raise ValueError("invalid unpublished import policy")
        if not self.owns_persistent_sessions:
            raise ValueError("direct transcript import requires an owned factory")
        source = Path(source_file).expanduser().absolute()
        raw = _read_stable_regular_file(
            source, max_bytes=81 * 1024 * 1024,
            expected_source_fingerprint=expected_source_fingerprint,
        )
        if source.suffix.lower() == ".zip":
            bundle = decode_agent_transcript_bundle(raw)
        else:
            header, records = decode_agent_transcript_bytes(raw, source_path=source)
            references = collect_agent_transcript_session_blobs(
                records, expected_session_id=session_blob_authority_id(header.conversation_id),
            )
            policy = DEFAULT_TRANSCRIPT_BUNDLE_POLICY
            if (len(references) > policy.max_blobs
                    or any(ref.size_bytes > policy.max_blob_bytes for ref in references)
                    or sum(ref.size_bytes for ref in references) > policy.max_total_bytes):
                raise ValueError("transcript import exceeds the portable blob budget")
            # Read-only blob readers do not create Session directories or locks.
            blob_store = SessionBlobStore(
                resolve_session_blob_data_root(source.parent), header.conversation_id,
                read_only=True, policy=policy,
            ) if references else None
            blobs = tuple((reference, blob_store.read_bytes(reference)) for reference in references) if blob_store is not None else ()
            bundle = AgentTranscriptBundle(header=header, records=tuple(records), blobs=blobs)
        if _validate_cwd is not None:
            _validate_cwd(str(cwd_override) if cwd_override is not None else str(bundle.header.metadata.get("cwd", ".")))
        return await self._import_frozen(
            bundle, session_dir=session_dir, cwd_override=cwd_override,
            persist=True, _projection=_projection, unpublished_import=_unpublished,
        )

    async def _import_frozen(
        self,
        bundle: AgentTranscriptBundle,
        *,
        session_dir: str | Path,
        cwd_override: str | Path | None,
        persist: bool,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None,
        unpublished_import: bool = False,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        if not persist and bundle.blobs:
            raise ValueError(
                "bundle import with blobs requires persistent session storage"
            )
        binding_input = self._resolve_binding_input(persist)
        self._validate_restored_header(bundle.header, binding_input, persist)
        cwd = (
            str(cwd_override)
            if cwd_override is not None
            else str(bundle.header.metadata.get("cwd", "."))
        )
        context = self._new_context(
            session_dir=session_dir,
            cwd=cwd,
            persist=persist,
            header=bundle.header,
        )
        publication: SessionBlobPublication | None = None
        if self._owned_product_id is not None:
            return await self._construct_owned(
                context, binding_input, records=bundle.records, initial_blobs=bundle.blobs,
                defer_materialization=False,
                unpublished_import=unpublished_import,
                _projection=_projection,
            )
        if persist and bundle.blobs:
            blob_store = SessionBlobStore(
                resolve_session_blob_data_root(context.session_dir),
                bundle.header.conversation_id,
            )
            publication = blob_store.import_blobs(
                bundle.blobs,
                require_new_authority=True,
            )
        try:
            return await self._lifecycle.create(
                context,
                binding_input,
                records=bundle.records,
            )
        except BaseException as error:
            _rollback_publication(publication, error)
            raise

    async def fork_from(
        self,
        source_file: str | Path,
        *,
        target_cwd: str | Path,
        session_dir: str | Path,
        persist: bool = True,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Copy a Conversation JSONL transcript into a new Product-selected session."""
        self._accepting(persist=persist)
        if self._owned_product_id is not None:
            context = self._discover_owned_context(source_file)
            async with self._owned_source(context) as source:
                records, blobs = _freeze_owned_source(source)
            self._accepting(persist=persist)
            return await self._create(
                session_dir=session_dir, cwd=target_cwd, persist=persist,
                binding_input=self._resolve_binding_input(persist),
                parent_conversation_id=context.header.conversation_id,
                parent_session=str(Path(source_file)), records=records, initial_blobs=blobs,
                _projection=_projection,
            )
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
                source_session_dir=source.context.session_dir,
                source_session_id=source.context.header.conversation_id,
            )
        finally:
            await source.dispose()

    async def fork(
        self,
        source: AgentTranscriptLifecycleSession[SourceProductBindingT],
        *,
        leaf_id: str,
        binding_input: BindingInputT,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        """Fork one selected source path using an already selected Product binding."""
        self._accepting()
        frozen = None
        if self._owned_product_id is not None:
            self._accepting(persist=source.context.persist)
            frozen = _freeze_owned_source(source, leaf_id=leaf_id)
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
        if frozen is not None:
            records, blobs = _retarget_frozen_blobs(*frozen, target_session_id=header.conversation_id)
            return await self._construct_owned(
                context, binding_input, records=records, leaf_id=leaf_id, initial_blobs=blobs,
                _projection=_projection,
            )
        records = source.transcript.records_for_fork(leaf_id)
        prepared_records, rollback_store = (
            clone_agent_transcript_session_blobs(
                records,
                source_session_dir=source_context.session_dir,
                source_session_id=source_context.header.conversation_id,
                target_session_dir=context.session_dir,
                target_session_id=header.conversation_id,
            )
            if context.persist
            else (tuple(records), None)
        )
        try:
            return await self._lifecycle.create(
                context,
                binding_input,
                records=prepared_records,
                leaf_id=leaf_id,
            )
        except BaseException as error:
            if rollback_store is not None:
                _rollback_publication(rollback_store, error)
            raise

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
        initial_blobs: Sequence[tuple[SessionBlobRef, bytes]] = (),
        source_session_dir: str | Path | None = None,
        source_session_id: str | None = None,
        additional_header_metadata: Mapping[str, JSONValue] | None = None,
        defer_materialization: bool = True,
        create_root: bool = False,
        _projection: Callable[[AgentTranscriptLifecycleSession[ProductBindingT]], None] | None = None,
    ) -> AgentTranscriptLifecycleSession[ProductBindingT]:
        self._accepting(persist=persist)
        header = self._new_header(
            conversation_id=conversation_id,
            cwd=cwd,
            parent_conversation_id=parent_conversation_id,
            parent_session=parent_session,
            binding_input=binding_input,
            additional_header_metadata=additional_header_metadata,
        )
        context = self._new_context(
            session_dir=session_dir,
            cwd=cwd,
            persist=persist,
            header=header,
        )
        prepared_records: Sequence[AgentTranscriptRecord] = records
        if self._owned_product_id is not None:
            if source_session_dir is not None:
                self._reject_unwired()
            records, initial_blobs = _retarget_frozen_blobs(
                records, initial_blobs, target_session_id=header.conversation_id,
            )
            return await self._construct_owned(
                context, binding_input, records=records, defer_materialization=defer_materialization,
                initial_blobs=initial_blobs,
                create_root=create_root,
                _projection=_projection,
            )
        rollback_store = None
        if persist and records and source_session_dir is not None:
            if source_session_id is None:
                raise ValueError("source Session identity is required to clone blobs")
            prepared_records, rollback_store = clone_agent_transcript_session_blobs(
                records,
                source_session_dir=source_session_dir,
                source_session_id=source_session_id,
                target_session_dir=context.session_dir,
                target_session_id=header.conversation_id,
            )
        try:
            return await self._lifecycle.create(
                context,
                binding_input,
                records=prepared_records,
                defer_materialization=defer_materialization,
            )
        except BaseException as error:
            if rollback_store is not None:
                _rollback_publication(rollback_store, error)
            raise

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
        additional_header_metadata: Mapping[str, JSONValue] | None = None,
    ) -> ConversationHeader:
        metadata: dict[str, JSONValue] = {"cwd": str(cwd)}
        if parent_session is not None:
            metadata["parentSession"] = parent_session
        metadata.update(self._header_metadata(binding_input))
        if additional_header_metadata is not None:
            if not isinstance(additional_header_metadata, Mapping):
                raise TypeError("additional header metadata must be a mapping")
            if {"cwd", "parentSession", *metadata}.intersection(
                additional_header_metadata
            ):
                raise ValueError(
                    "additional metadata overrides reserved header metadata"
                )
            metadata.update(additional_header_metadata)
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


def _freeze_owned_source(
    source: AgentTranscriptLifecycleSession[SourceProductBindingT], *, leaf_id: str | None = None,
) -> tuple[tuple[AgentTranscriptRecord, ...], tuple[tuple[SessionBlobRef, bytes], ...]]:
    if source._writer_owner is None or source.blob_file_io is None:
        raise ValueError("owned fork requires a source with retained transcript and blob ports")
    with source.sync_operation_scope():
        records = deepcopy(tuple(
            source.transcript.records if leaf_id is None else source.transcript.records_for_fork(leaf_id)
        ))
        references = collect_agent_transcript_session_blobs(
            records, expected_session_id=source.context.header.conversation_id,
        )
        if not references:
            return records, ()
        store = SessionBlobStore(
            source.context.session_dir.parent, source.context.header.conversation_id,
            file_io=source.blob_file_io,
        )
        return records, tuple((ref, store.read_bytes(ref)) for ref in references)


def _retarget_frozen_blobs(
    records: Sequence[AgentTranscriptRecord], blobs: Sequence[tuple[SessionBlobRef, bytes]], *,
    target_session_id: str,
) -> tuple[tuple[AgentTranscriptRecord, ...], tuple[tuple[SessionBlobRef, bytes], ...]]:
    replacements = {ref: replace(ref, session_id=session_blob_authority_id(target_session_id)) for ref, _ in blobs}
    return (
        replace_agent_transcript_session_blobs(records, replacements),
        tuple((replacements[ref], data) for ref, data in blobs),
    )


def _validate_nothing(
    header: ConversationHeader,
    binding_input: object,
    persist: bool,
) -> None:
    del header, binding_input, persist


def _rollback_publication(
    publication: SessionBlobPublication | None,
    error: BaseException,
) -> None:
    if publication is None:
        return
    try:
        publication.rollback()
    except BaseException as cleanup_error:
        error.add_note(
            "session blob rollback also failed: "
            f"{cleanup_error.__class__.__name__}: {cleanup_error}"
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _default_id() -> str:
    # User-global authorities need collision resistance across every cwd and
    # long-lived installation, while legacy short IDs remain valid prefixes.
    return uuid4().hex


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
    "TranscriptDeletionCleanupPending",
]
