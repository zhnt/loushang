"""Product-bound standard operations for current Agent transcript sessions.

``AgentTranscriptSessionFactory`` owns Conversation JSONL create, restore, and fork
assembly.  This module owns the repeated Product-facing wrapper around those
results: session metadata, catalog/index access, standard transcript records,
and file-level rename/delete maintenance.  Products provide only their factory
and the binding input to reuse for a fork.
"""

from __future__ import annotations

import builtins
import sys
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Self, TypeVar, cast

from loushang.agent.types import AgentMessage
from loushang.ai.types import AssistantMessage, ToolResultMessage, UserMessage
from loushang.foundation.json import JSONValue, require_json_value
from loushang.harness.artifacts import (
    SessionBlobStore,
    resolve_session_blob_data_root,
)
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.runtime import RuntimeProfileSnapshot
from loushang.harness.transcript.capability_candidate import (
    AgentTranscriptCapabilityCandidate,
)
from loushang.harness.transcript.committer import CommitResult
from loushang.harness.transcript.compaction import (
    TURN_AWARE_SUMMARY_IMPLEMENTATION,
    TURN_AWARE_SUMMARY_VERSION,
    AgentTranscriptCompactionCapability,
    create_agent_transcript_compaction_capability,
)
from loushang.harness.transcript.jsonl_file import (
    load_agent_transcript_file,
    load_agent_transcript_header,
    publish_owned_transcript_projection,
)
from loushang.harness.transcript.lifecycle import (
    AgentTranscriptLifecycleSession,
    TranscriptDeletionOwner,
    delete_agent_transcript_jsonl,
)
from loushang.harness.transcript.model_input_blobs import SessionModelInputBlobCodec
from loushang.harness.transcript.session import AgentTranscriptSession
from loushang.harness.transcript.session_artifacts import (
    collect_agent_transcript_session_blobs,
    delete_agent_transcript_session_blobs,
)
from loushang.harness.transcript.session_catalog import (
    _MAX_PATH_SUMMARY_TOTAL_BYTES,
    AgentTranscriptSessionCatalog,
    SessionMetadata,
    SessionQuery,
    SessionRecord,
    SessionSummary,
    SessionTreeNode,
    _status_fingerprint,
    agent_transcript_header_parent_session,
    build_agent_transcript_session_context,
    build_agent_transcript_session_tree,
    find_all_agent_transcript_session_summaries,
    find_all_indexed_agent_transcript_session_summaries,
    list_all_agent_transcript_session_summaries,
    list_all_indexed_agent_transcript_session_summaries,
    load_agent_transcript_session_metadata,
    project_agent_transcript_session_summary,
    refresh_all_agent_transcript_session_indexes,
    same_agent_transcript_session_path,
)
from loushang.harness.transcript.session_factory import (
    AgentTranscriptSessionFactory,
)
from loushang.harness.transcript.session_images import (
    SessionImageHydrationContext,
    externalize_session_message_images,
    hydrate_session_message_images,
    rollback_externalized_session_images,
)
from loushang.harness.transcript.types import (
    AgentTranscriptContext,
    AgentTranscriptRecord,
    ApplicationMessage,
)

BindingInputT = TypeVar("BindingInputT")
ProductBindingT = TypeVar("ProductBindingT")

if TYPE_CHECKING:
    from loushang.harness.journal._rooted_io import RootedFileIO


class ProductTranscriptSession(
    AgentTranscriptSession,
    Generic[BindingInputT, ProductBindingT],
):
    """Product adapter over one standard Agent transcript lifecycle result.

    The adapter intentionally has no knowledge of a Product's model registry,
    prompt, tools, or capability profile.  Subclasses bind a factory and
    provide the immutable binding input used when branching an existing
    transcript.
    """

    def __init__(
        self,
        *,
        lifecycle_session: AgentTranscriptLifecycleSession[ProductBindingT],
    ) -> None:
        self._lifecycle_session = lifecycle_session
        self._creation_factory: AgentTranscriptSessionFactory[BindingInputT, ProductBindingT] | None = None
        self.session_dir = lifecycle_session.context.session_dir
        self.cwd = lifecycle_session.context.cwd
        self.persist = lifecycle_session.context.persist
        self.session_file = lifecycle_session.context.session_file
        self.session_blob_health = lifecycle_session.session_blob_health
        self._published_index_revision: int | None = None
        super().__init__(
            transcript=lifecycle_session.transcript,
            labels_by_target_id=lifecycle_session.labels_by_target_id,
            label_timestamps_by_target_id=(
                lifecycle_session.label_timestamps_by_target_id
            ),
        )

    async def append_message(
        self,
        message: object,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> str:
        """Externalize durable image bytes before committing an Agent message."""

        if not self.persist or not isinstance(
            message, UserMessage | AssistantMessage | ToolResultMessage
        ):
            return await super().append_message(message, metadata=metadata)
        async with self._lifecycle_session.operation_scope():
            externalized = externalize_session_message_images(
                message,
                self._session_blob_store(file_io=self._lifecycle_session.blob_file_io),
            )
            revision = self._transcript.revision
            try:
                return await super().append_message(
                    externalized.message,
                    metadata=metadata,
                )
            except BaseException as error:
                rollback_externalized_session_images(
                    externalized, error,
                    transcript_changed=self._transcript.revision != revision,
                )
                raise

    async def commit_application_message(
        self,
        message: ApplicationMessage,
    ) -> CommitResult:
        """Persist Application images through the same durable boundary."""

        if not self.persist:
            return await super().commit_application_message(message)
        async with self._lifecycle_session.operation_scope():
            externalized = externalize_session_message_images(
                message,
                self._session_blob_store(file_io=self._lifecycle_session.blob_file_io),
                now=message.timestamp,
            )
            revision = self._transcript.revision
            try:
                return await super().commit_application_message(
                    cast(ApplicationMessage, externalized.message)
                )
            except BaseException as error:
                rollback_externalized_session_images(
                    externalized, error,
                    transcript_changed=self._transcript.revision != revision,
                )
                raise

    @classmethod
    def _session_factory(
        cls,
    ) -> AgentTranscriptSessionFactory[BindingInputT, ProductBindingT]:
        raise NotImplementedError("Product transcript sessions must bind a factory")

    @classmethod
    def _factory_for_persistence(
        cls, persist: bool,
    ) -> AgentTranscriptSessionFactory[BindingInputT, ProductBindingT]:
        """Select an application binding without changing legacy factory hooks."""
        return cls._session_factory()

    def _fork_binding_input(self) -> BindingInputT:
        raise NotImplementedError("Product transcript sessions must bind fork input")

    @classmethod
    async def _construct_product(
        cls, factory: AgentTranscriptSessionFactory[BindingInputT, ProductBindingT],
        operation: Callable[..., Awaitable[AgentTranscriptLifecycleSession[ProductBindingT]]],
    ) -> Self:
        if not factory.owns_persistent_sessions:
            return cls(lifecycle_session=await operation())
        projected: Self | None = None

        def project(session: AgentTranscriptLifecycleSession[ProductBindingT]) -> None:
            nonlocal projected
            # Synchronous construction only: do not publish or transfer Graph
            # ownership before the factory completes its original handoff.
            value = cls(lifecycle_session=session)
            value._creation_factory = factory
            projected = value

        await operation(_projection=project)
        assert projected is not None
        return projected

    async def dispose_runtime_profile(self) -> None:
        """Release the Product-owned runtime binding for this session."""

        if self._lifecycle_session.ownership_state != "root_owned":
            # The combined Session Provider owns index publication and release
            # once the transcript trio enters Graph construction. Compatibility
            # disposal must not race or duplicate that owner.
            await self._lifecycle_session.dispose()
            return
        try:
            await self.publish_index_summary()
        finally:
            await self._lifecycle_session.dispose()

    @property
    def runtime_disposed(self) -> bool:
        """True only after the actual Session/Graph disposal owner has settled."""
        return self._lifecycle_session.ownership_state == "disposed"

    def transcript_capability_candidate(self) -> AgentTranscriptCapabilityCandidate:
        """Project the already-bound transcript trio for Session graph adoption."""

        runtime_binding = self._lifecycle_session.runtime_binding
        snapshot = runtime_binding.runtime_profile_snapshot or RuntimeProfileSnapshot(
            product_id="harness.transcript.legacy",
            capabilities=(),
        )
        get_compaction = runtime_binding.get_compaction_capability
        if get_compaction is None:
            legacy_compaction = self._legacy_compaction_capability()

            def resolved_get_compaction() -> AgentTranscriptCompactionCapability:
                return legacy_compaction

        else:
            resolved_get_compaction = get_compaction
        return AgentTranscriptCapabilityCandidate(
            _lifecycle=self._lifecycle_session,
            conversation_id=self.header.conversation_id,
            runtime_profile_snapshot=snapshot,
            _get_compaction_capability=resolved_get_compaction,
            _create_model_input_committer=(
                lambda purpose, logical_input, runtime_references: (
                    self.create_model_input_committer(
                        purpose=purpose,
                        logical_input=logical_input,
                        runtime_references=runtime_references,
                    )
                )
            ),
            _rebuild_model_input=self.rebuild_model_input,
            _publish_index_summary=self.publish_index_summary,
        )

    def _legacy_compaction_capability(
        self,
    ) -> AgentTranscriptCompactionCapability:
        get_runtime_capability = getattr(self, "get_runtime_capability", None)
        if callable(get_runtime_capability):
            selected = get_runtime_capability("context.compaction")
            if isinstance(selected, AgentTranscriptCompactionCapability):
                return selected
        return create_agent_transcript_compaction_capability(
            implementation=TURN_AWARE_SUMMARY_IMPLEMENTATION,
            implementation_version=TURN_AWARE_SUMMARY_VERSION,
            config={
                "enabled": True,
                "compactPercent": 80.0,
                "reserveTokens": 8_192,
                "keepRecentTokens": 32_768,
            },
        )

    async def publish_index_summary(self) -> None:
        """Publish this session's latest summary when a local index exists."""

        if not self.is_persisted() or self.session_file is None:
            return
        revision = len(self.entries)
        if revision == self._published_index_revision:
            return
        catalog = AgentTranscriptSessionCatalog(self.session_dir)
        file_io = self._lifecycle_session.transcript_file_io
        if file_io is not None:
            try:
                async with self._lifecycle_session.operation_scope():
                    if catalog.session_dir is None:
                        raise ValueError("owned publication requires a local catalog")
                    key = self._lifecycle_session.runtime_binding.key
                    header, records = self.header, tuple(self.entries)
                    publication = partial(
                        publish_owned_transcript_projection,
                        file_io=file_io, root=catalog.session_dir, key=key,
                        source_path=self.session_file, header=header, records=records,
                        max_bytes=_MAX_PATH_SUMMARY_TOTAL_BYTES, fingerprint=_status_fingerprint,
                    )
                    changed = await settled_io(
                        catalog.publish_owned_summary,
                        publication=publication,
                        key=key,
                        source_path=self.session_file,
                        header=header, records=records,
                        leaf_id=self.leaf_id,
                    )
                if changed:
                    self._published_index_revision = revision
            except Exception:
                # Cache failure does not roll back committed transcript data.
                # Any unsettled native resources remain on the original port.
                pass
            return
        if not catalog.index_path.exists():
            return
        try:
            await catalog.upsert_summary(
                self._get_session_index_summary(),
                source_revision=revision,
            )
        except Exception:
            # The index is an auxiliary cache; the durable transcript already won.
            return
        self._published_index_revision = revision

    @classmethod
    async def new(
        cls,
        session_dir: Path,
        cwd: str,
        persist: bool = True,
        parent_session: str | None = None,
        session_id: str | None = None,
        additional_header_metadata: Mapping[str, JSONValue] | None = None,
        defer_materialization: bool = True,
    ) -> Self:
        factory = cls._factory_for_persistence(persist)
        return await cls._construct_product(factory, partial(factory.new,
            session_dir=session_dir,
            cwd=cwd,
            persist=persist,
            parent_session=parent_session,
            session_id=session_id,
            additional_header_metadata=additional_header_metadata,
            defer_materialization=defer_materialization,
        ))

    @classmethod
    async def load(cls, session_file: Path, persist: bool = True) -> Self:
        factory = cls._factory_for_persistence(persist)
        return await cls._construct_product(factory, partial(factory.load,
            session_file,
            persist=persist,
        ))

    @classmethod
    async def open(
        cls,
        session_file: str | Path,
        session_dir: str | Path | None = None,
        cwd_override: str | Path | None = None,
        persist: bool = True,
    ) -> Self:
        factory = cls._factory_for_persistence(persist)
        return await cls._construct_product(factory, partial(factory.open,
            session_file,
            session_dir=session_dir,
            cwd_override=cwd_override,
            persist=persist,
        ))

    @classmethod
    async def continue_recent(
        cls,
        session_dir: str | Path,
        cwd: str | Path,
        persist: bool = True,
    ) -> Self:
        factory = cls._factory_for_persistence(persist)
        return await cls._construct_product(factory, partial(factory.continue_recent,
            session_dir=session_dir,
            cwd=cwd,
            persist=persist,
        ))

    @classmethod
    async def in_memory(
        cls,
        cwd: str | Path = ".",
        session_id: str | None = None,
    ) -> Self:
        factory = cls._factory_for_persistence(False)
        return await cls._construct_product(factory, partial(factory.in_memory,
            cwd=cwd,
            session_id=session_id,
        ))

    @classmethod
    async def import_transcript(
        cls,
        source_file: str | Path,
        *,
        session_dir: str | Path,
        cwd_override: str | Path | None = None,
        expected_source_fingerprint: str | None = None,
        _validate_cwd: Callable[[str], None] | None = None,
        _unpublished: bool = False,
    ) -> Self:
        factory = cls._factory_for_persistence(True)
        return await cls._construct_product(factory, partial(
            factory.import_transcript, source_file, session_dir=session_dir,
            cwd_override=cwd_override,
            expected_source_fingerprint=expected_source_fingerprint,
            _validate_cwd=_validate_cwd,
            _unpublished=_unpublished,
        ))

    def _mark_import_delivered(self) -> None:
        self._lifecycle_session._mark_import_delivered()

    @classmethod
    async def import_bundle(
        cls,
        source_file: str | Path,
        *,
        session_dir: str | Path,
        cwd_override: str | Path | None = None,
        persist: bool = True,
    ) -> Self:
        factory = cls._factory_for_persistence(persist)
        return await cls._construct_product(factory, partial(factory.import_bundle,
            source_file,
            session_dir=session_dir,
            cwd_override=cwd_override,
            persist=persist,
        ))

    @classmethod
    async def fork_from(
        cls,
        source_file: str | Path,
        target_cwd: str | Path,
        session_dir: str | Path,
        persist: bool = True,
    ) -> Self:
        factory = cls._factory_for_persistence(persist)
        return await cls._construct_product(factory, partial(factory.fork_from,
            source_file,
            target_cwd=target_cwd,
            session_dir=session_dir,
            persist=persist,
        ))

    def get_session_dir(self) -> Path:
        return self.session_dir

    def get_session_file(self) -> Path | None:
        return self.session_file

    def get_cwd(self) -> str:
        return self.cwd

    def is_persisted(self) -> bool:
        return self.persist and self.session_file is not None and self.is_materialized

    def load_metadata(self) -> SessionMetadata:
        return load_agent_transcript_session_metadata(self.header, self.entries)

    def get_session_record(self) -> SessionRecord:
        return SessionRecord(
            session_id=self.header.conversation_id,
            cwd=self.cwd,
            session_file=self.session_file,
            parent_session=agent_transcript_header_parent_session(self.header),
            leaf_id=self.leaf_id,
            metadata=self.load_metadata(),
        )

    def get_session_summary(self) -> SessionSummary:
        return project_agent_transcript_session_summary(
            self.header,
            self.entries,
            self.leaf_id,
            self.session_file,
        )

    def _get_session_index_summary(self) -> SessionSummary:
        return project_agent_transcript_session_summary(
            self.header,
            self.entries,
            self.leaf_id,
            self.session_file,
            include_all_messages_text=False,
        )

    def get_tree(self) -> list[SessionTreeNode[AgentTranscriptRecord]]:
        return build_agent_transcript_session_tree(
            self._transcript.tree(),
            labels_by_target_id=self.labels_by_target_id,
            label_timestamps_by_target_id=self.label_timestamps_by_target_id,
        )

    async def append_custom_entry(
        self, custom_type: str, data: object | None = None
    ) -> str:
        return await self.append_extension_data(
            custom_type,
            require_json_value(data, name="custom_entry.data"),
        )

    async def append_diagnostic_metadata(
        self,
        *,
        code: str,
        level: str,
        message: str | None = None,
        details: object | None = None,
    ) -> str:
        payload: dict[str, object] = {"code": code, "level": level}
        if message is not None:
            payload["message"] = message
        if details is not None:
            payload["details"] = details
        return await self.append_custom_entry("diagnostic", payload)

    async def append_session_info(self, name: str | None) -> str:
        record_id = await self.append_conversation_name(name)
        await self.publish_index_summary()
        return record_id

    async def fork(self, leaf_id: str) -> Self:
        factory = self._creation_factory if self._creation_factory is not None else self._factory_for_persistence(self.persist)
        return await type(self)._construct_product(factory, partial(factory.fork,
            self._lifecycle_session,
            leaf_id=leaf_id,
            binding_input=self._fork_binding_input(),
        ))

    async def create_branched_session(self, leaf_id: str) -> Path | None:
        return (await self.fork(leaf_id)).session_file

    def build_session_context(self) -> AgentTranscriptContext:
        with self._lifecycle_session.sync_operation_scope():
            return self._build_session_context()

    def _build_session_context(self) -> AgentTranscriptContext:
        context = build_agent_transcript_session_context(self.entries, self.leaf_id)
        if not self.persist:
            return context
        store = self._session_blob_store(file_io=self._lifecycle_session.blob_file_io)
        hydration = SessionImageHydrationContext()
        return AgentTranscriptContext(
            messages=tuple(
                cast(
                    AgentMessage,
                    hydrate_session_message_images(
                        message,
                        store,
                        hydration=hydration,
                    ),
                )
                for message in context.messages
            ),
            state=context.state,
        )

    def _session_blob_store(self, *, file_io: RootedFileIO | None = None) -> SessionBlobStore:
        return SessionBlobStore(
            self.session_dir.parent if file_io is not None else resolve_session_blob_data_root(self.session_dir),
            self.header.conversation_id,
            file_io=file_io,
        )

    def _model_input_binary_codec(
        self,
        *,
        active_only: bool,
    ) -> SessionModelInputBlobCodec | None:
        with self._lifecycle_session.sync_operation_scope():
            return self._build_model_input_binary_codec(active_only=active_only)

    def _build_model_input_binary_codec(
        self, *, active_only: bool,
    ) -> SessionModelInputBlobCodec | None:
        if not self.persist:
            return None
        records = (
            self._transcript.active_path()
            if active_only
            else self._transcript.records
        )
        return SessionModelInputBlobCodec(
            self._session_blob_store(file_io=self._lifecycle_session.blob_file_io),
            operation_scope=self._lifecycle_session.sync_operation_scope,
            references=collect_agent_transcript_session_blobs(
                records,
                expected_session_id=self.header.conversation_id,
            ),
        )

    @classmethod
    async def rename_session(
        cls,
        session_file: str | Path,
        name: str | None,
    ) -> SessionSummary:
        manager = await cls.open(session_file, persist=True)
        try:
            await manager.append_session_info(name)
            summary = manager.get_session_summary()
        finally:
            await manager.dispose_runtime_profile()
        return summary

    @classmethod
    async def delete_session(
        cls,
        session_file: str | Path,
        *,
        current_session_file: str | Path | None = None,
        maintenance_owner: TranscriptDeletionOwner | None = None,
    ) -> bool:
        if maintenance_owner is not None or sys.platform == "linux":
            return await delete_agent_transcript_jsonl(
                session_file, current_session_file=current_session_file,
                maintenance_owner=maintenance_owner,
            )
        target = Path(session_file).expanduser()
        if current_session_file is not None and same_agent_transcript_session_path(
            target,
            Path(current_session_file).expanduser(),
        ):
            raise ValueError("Cannot delete the currently active session")
        if not target.is_file():
            return False
        header, records = load_agent_transcript_file(target)
        references = collect_agent_transcript_session_blobs(
            records,
            expected_session_id=header.conversation_id,
        )
        owns_unique_blob_authority = bool(references) and cls._is_unique_authority(
            target,
            header.conversation_id,
        )
        deleted = await delete_agent_transcript_jsonl(
            target,
            current_session_file=current_session_file,
        )
        if deleted:
            # The transcript authority has already committed deletion.
            # Recoverable asset residue is left for explicit maintenance.
            with suppress(OSError, ValueError):
                if not owns_unique_blob_authority or not cls._is_unique_authority(
                    target,
                    header.conversation_id,
                ):
                    raise ValueError(
                        "Session blob authority still has another transcript owner"
                    )
                delete_agent_transcript_session_blobs(
                    session_dir=target.parent,
                    session_id=header.conversation_id,
                )
            cls._repair_index_if_present(target.parent)
        return deleted

    @staticmethod
    def _is_unique_authority(target: Path, conversation_id: str) -> bool:
        """Fail closed when another transcript claims the same blob authority."""

        for candidate in target.parent.glob("*.jsonl"):
            if same_agent_transcript_session_path(candidate, target):
                continue
            try:
                if load_agent_transcript_header(candidate).conversation_id == conversation_id:
                    return False
            except (OSError, ValueError):
                continue
        return True

    @classmethod
    def _repair_index_if_present(cls, session_dir: Path) -> None:
        if cls.index_file(session_dir).exists():
            try:
                AgentTranscriptSessionCatalog(session_dir).repair_index()
            except Exception:
                # Indexes are auxiliary caches; primary transcript writes won.
                return

    @classmethod
    def list(cls, session_dir: Path) -> builtins.list[SessionRecord]:
        return AgentTranscriptSessionCatalog(session_dir).list_records()

    @classmethod
    def list_summaries(cls, session_dir: Path) -> builtins.list[SessionSummary]:
        return AgentTranscriptSessionCatalog(session_dir).list_summaries()

    @classmethod
    def list_all_summaries(cls, sessions_root: Path) -> builtins.list[SessionSummary]:
        return list_all_agent_transcript_session_summaries(sessions_root)

    @classmethod
    async def load_summary(cls, session_file: Path) -> SessionSummary:
        manager = await cls.load(session_file)
        try:
            return manager.get_session_summary()
        finally:
            await manager.dispose_runtime_profile()

    @classmethod
    def find_sessions(
        cls,
        session_dir: Path,
        query: SessionQuery | None = None,
    ) -> builtins.list[SessionSummary]:
        return AgentTranscriptSessionCatalog(session_dir).find_summaries(query)

    @classmethod
    def find_all_sessions(
        cls,
        sessions_root: Path,
        query: SessionQuery | None = None,
    ) -> builtins.list[SessionSummary]:
        return find_all_agent_transcript_session_summaries(sessions_root, query)

    @classmethod
    def index_file(cls, session_dir: Path) -> Path:
        return AgentTranscriptSessionCatalog(session_dir).index_path

    @classmethod
    def refresh_index(cls, session_dir: Path) -> builtins.list[SessionSummary]:
        return AgentTranscriptSessionCatalog(session_dir).refresh_index()

    @classmethod
    def load_index(cls, session_dir: Path) -> builtins.list[SessionSummary]:
        return AgentTranscriptSessionCatalog(session_dir).load_index()

    @classmethod
    def list_indexed_summaries(
        cls,
        session_dir: Path,
        *,
        refresh: bool = False,
    ) -> builtins.list[SessionSummary]:
        return AgentTranscriptSessionCatalog(session_dir).list_indexed_summaries(
            refresh=refresh
        )

    @classmethod
    def find_indexed_sessions(
        cls,
        session_dir: Path,
        query: SessionQuery | None = None,
    ) -> builtins.list[SessionSummary]:
        return AgentTranscriptSessionCatalog(session_dir).find_indexed_summaries(query)

    @classmethod
    def refresh_all_indexes(
        cls,
        sessions_root: Path,
    ) -> builtins.list[SessionSummary]:
        return refresh_all_agent_transcript_session_indexes(sessions_root)

    @classmethod
    def list_all_indexed_summaries(
        cls,
        sessions_root: Path,
        *,
        refresh: bool = False,
    ) -> builtins.list[SessionSummary]:
        return list_all_indexed_agent_transcript_session_summaries(
            sessions_root,
            refresh=refresh,
        )

    @classmethod
    def find_all_indexed_sessions(
        cls,
        sessions_root: Path,
        query: SessionQuery | None = None,
    ) -> builtins.list[SessionSummary]:
        return find_all_indexed_agent_transcript_session_summaries(sessions_root, query)


__all__ = ["ProductTranscriptSession"]
