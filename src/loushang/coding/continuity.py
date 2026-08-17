"""Coding's Product adapter for the Harness Continuity contracts."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.harness.continuity import (
    CallbackPreparedActivationLease,
    ContinuityArtifactReference,
    ContinuityDiagnostic,
    ContinuityHub,
    ContinuityPreview,
    ContinuityPreviewSection,
    ContinuityProviderDescriptor,
    ContinuityProviderPack,
    ContinuitySummary,
    ContinuityTarget,
    ExperienceDescriptor,
    ProviderPage,
    ProviderPageItem,
    ProviderQuery,
    compose_experience_continuity,
)
from loushang.harness.conversation import IndexedProjection
from loushang.harness.runtime import (
    CONTINUITY_PROVIDER_PACKS_SLOT,
    ProductRuntimePlan,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeCapabilitySelection,
    RuntimeProfileAdmissionPolicy,
    RuntimeProfileBinder,
    RuntimeProfileBinding,
    RuntimeProfileLayer,
    RuntimeProfileLayerGrant,
    RuntimeProfileResolver,
    SessionOperationResult,
)
from loushang.harness.transcript import (
    AgentTranscriptSessionCatalog,
    SessionIndexPage,
    SessionQuery,
    SessionSummary,
    same_agent_transcript_session_path,
)

CODING_CONTINUITY_PROVIDER_ID = "coding.sessions"
CODING_CONTINUITY_IMPLEMENTATION = "coding.session_continuity"
CODING_CONTINUITY_IMPLEMENTATION_VERSION = 1
CODING_EXPERIENCE_ID = "coding"

_MAX_PREVIEW_CACHE = 256
_RUNTIME_BINDING_ATTRIBUTE = "_loushang_coding_continuity"


class CodingContinuityRuntimePort(Protocol):
    session_dir: Path

    def try_query_session_index_page(
        self,
        query: SessionQuery | None = None,
        *,
        cursor: str | None = None,
        limit: int = 25,
    ) -> SessionIndexPage: ...

    def request_session_index_refresh(self, *, all_sessions: bool = False) -> None: ...

    def request_session_index_repair(self) -> None: ...

    def get_current_session(self) -> object | None: ...

    def get_current_session_ref(self) -> str | None: ...

    async def delete_session(self, session_id: str | Path) -> bool: ...

    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        *,
        fallback_cwd: str | Path | None = None,
        missing_cwd: str = "error",
    ) -> CodingPreparedSessionOperation: ...


class CodingPreparedSessionOperation(Protocol):
    async def consume(self) -> object: ...

    async def abort(self) -> None: ...


class StaleContinuityTargetError(RuntimeError):
    """Raised when a selected summary no longer matches transcript authority."""


class CodingContinuityProvider:
    """Adapt Agent transcript summaries without leaking Coding UI or Git facts."""

    def __init__(self, runtime: CodingContinuityRuntimePort) -> None:
        self._runtime = runtime
        self._index_refresh_requested = False
        self._preview_items: OrderedDict[str, IndexedProjection[SessionSummary]] = (
            OrderedDict()
        )

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return ContinuityProviderDescriptor(
            provider_id=CODING_CONTINUITY_PROVIDER_ID,
            experience_id=CODING_EXPERIENCE_ID,
            domain_ids=("coding",),
            primary_domain_id="coding",
            label="Coding sessions",
            supported_sorts=("updated", "created"),
            supports_startup=True,
            supports_in_place=True,
            implementation_version=CODING_CONTINUITY_IMPLEMENTATION_VERSION,
            profile_version=1,
        )

    async def query(self, request: ProviderQuery) -> ProviderPage:
        page = await asyncio.to_thread(
            self._runtime.try_query_session_index_page,
            SessionQuery(
                text=request.text or None,
                sort_by="created" if request.sort_id == "created" else "recent",
                has_messages=True,
            ),
            cursor=request.cursor,
            limit=request.limit,
        )
        items: list[ProviderPageItem] = []
        for page_item in page.items:
            indexed = page_item.item
            self._remember(indexed)
            items.append(
                ProviderPageItem(
                    summary=_continuity_summary(indexed),
                    after_cursor=page_item.after_cursor,
                )
            )
        diagnostics: tuple[ContinuityDiagnostic, ...] = ()
        if page.restart_required:
            diagnostics = (
                ContinuityDiagnostic(
                    code="coding_continuity_snapshot_expired",
                    message="The Coding session index traversal expired; restart search.",
                    provider_id=CODING_CONTINUITY_PROVIDER_ID,
                ),
            )
        elif page.index_state != "fresh":
            if not self._index_refresh_requested:
                self._runtime.request_session_index_repair()
                self._index_refresh_requested = True
            diagnostics = (
                ContinuityDiagnostic(
                    code="coding_continuity_index_not_ready",
                    message="Coding session history is being indexed.",
                    provider_id=CODING_CONTINUITY_PROVIDER_ID,
                ),
            )
        else:
            self._index_refresh_requested = False
        return ProviderPage(
            items=tuple(items),
            has_more=page.has_more,
            index_state=(
                "rebuilding" if page.index_state == "unavailable" else page.index_state
            ),
            index_generation=page.index_generation,
            query_snapshot=page.query_snapshot,
            diagnostics=diagnostics,
        )

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        indexed = self._cached_target(target)
        summary = indexed.projection
        rows = [
            ("Workspace", summary.cwd or "Unknown"),
            ("Messages", str(summary.message_count)),
            ("Entries", str(summary.entry_count)),
        ]
        if summary.model:
            provider = summary.model.get("provider")
            model_id = summary.model.get("model_id")
            if provider and model_id:
                rows.append(("Model", f"{provider}/{model_id}"))
        artifacts = (
            (
                ContinuityArtifactReference(
                    label="Transcript",
                    reference=str(summary.session_file),
                ),
            )
            if summary.session_file is not None
            else ()
        )
        return ContinuityPreview(
            target=target,
            revision=str(indexed.source_revision),
            heading=_summary_title(summary),
            sections=(
                ContinuityPreviewSection(
                    kind="text",
                    text=summary.last_message_preview or summary.first_message,
                ),
                ContinuityPreviewSection(
                    kind="key_value",
                    title="Coding session",
                    rows=tuple(rows),
                ),
                ContinuityPreviewSection(
                    kind="artifacts",
                    artifacts=artifacts,
                ),
            ),
            stale=str(indexed.source_revision) != target.revision,
        )

    async def prepare(
        self,
        target: ContinuityTarget,
    ) -> CallbackPreparedActivationLease:
        indexed = self._cached_target(target)
        expected_revision = str(indexed.source_revision)
        if target.revision != expected_revision:
            raise StaleContinuityTargetError(
                "The selected Coding session summary is stale."
            )
        reference: str | Path = (
            indexed.projection.session_file or indexed.projection.session_id
        )
        current = self._runtime.get_current_session()
        if current is not None and _same_session_reference(
            self._runtime.get_current_session_ref(),
            reference,
        ):
            return CallbackPreparedActivationLease(
                target=target,
                disposition="in_place",
                consume=lambda: SessionOperationResult(
                    previous=current,
                    current=current,
                    payload=None,
                    cancelled=False,
                ),
            )
        current_revision = await asyncio.to_thread(
            AgentTranscriptSessionCatalog(
                self._runtime.session_dir
            ).load_authoritative_revision,
            indexed.locator,
        )
        if current_revision != indexed.source_revision:
            raise StaleContinuityTargetError(
                "The selected Coding session changed after it was listed."
            )
        candidate = await self._runtime.prepare_restore_session_operation(reference)
        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=candidate.consume,
            abort=candidate.abort,
        )

    async def delete(self, target: ContinuityTarget) -> bool:
        indexed = self._cached_target(target)
        expected_revision = str(indexed.source_revision)
        if target.revision != expected_revision:
            raise StaleContinuityTargetError(
                "The selected Coding session summary is stale."
            )
        reference: str | Path = (
            indexed.projection.session_file or indexed.projection.session_id
        )
        if _same_session_reference(
            self._runtime.get_current_session_ref(),
            reference,
        ):
            raise ValueError("Cannot delete the currently active session")
        current_revision = await asyncio.to_thread(
            AgentTranscriptSessionCatalog(
                self._runtime.session_dir
            ).load_authoritative_revision,
            indexed.locator,
        )
        if current_revision != indexed.source_revision:
            raise StaleContinuityTargetError(
                "The selected Coding session changed after it was listed."
            )
        deleted = await self._runtime.delete_session(reference)
        if deleted:
            self._preview_items.pop(target.opaque_id, None)
        return deleted

    def _cached_target(
        self,
        target: ContinuityTarget,
    ) -> IndexedProjection[SessionSummary]:
        if target.provider_id != CODING_CONTINUITY_PROVIDER_ID:
            raise ValueError("continuity target belongs to another Provider")
        try:
            item = self._preview_items[target.opaque_id]
        except KeyError as exc:
            raise StaleContinuityTargetError(
                "The selected Coding session is no longer in this query snapshot."
            ) from exc
        self._preview_items.move_to_end(target.opaque_id)
        return item

    def _remember(self, item: IndexedProjection[SessionSummary]) -> None:
        self._preview_items[item.projection.session_id] = item
        self._preview_items.move_to_end(item.projection.session_id)
        while len(self._preview_items) > _MAX_PREVIEW_CACHE:
            self._preview_items.popitem(last=False)


def _same_session_reference(
    current: str | None,
    target: str | Path,
) -> bool:
    if current is None:
        return False
    target_text = str(target)
    if current == target_text:
        return True
    return same_agent_transcript_session_path(
        Path(current).expanduser(),
        Path(target_text).expanduser(),
    )


@dataclass
class CodingContinuityComposition:
    binding: RuntimeProfileBinding
    binder: RuntimeProfileBinder
    hub: ContinuityHub
    runtime_owned: bool = False
    _shutdown: bool = False

    async def dispose(self) -> None:
        """Release a caller view; the process-scoped runtime remains bound."""

        if not self.runtime_owned:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Dispose the process-scoped binding at Product runtime shutdown."""

        if self._shutdown:
            return
        self._shutdown = True
        await self.binder.dispose(self.binding)


def bind_coding_continuity(
    runtime: CodingContinuityRuntimePort,
    *,
    layers: Iterable[RuntimeProfileLayer] = (),
    grants: Iterable[RuntimeProfileLayerGrant] = (),
    implementations: Iterable[RuntimeCapabilityImplementation] = (),
) -> CodingContinuityComposition:
    """Bind process-scoped Product/OEM packs once, then compose Coding."""

    layer_values = tuple(layers)
    grant_values = tuple(grants)
    implementation_values = tuple(implementations)
    cached = getattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, None)
    if isinstance(cached, CodingContinuityComposition):
        if layer_values or grant_values or implementation_values:
            raise RuntimeError(
                "Coding continuity is already sealed for this Product runtime"
            )
        return cached

    plan = ProductRuntimePlan(
        product_id=CODING_EXPERIENCE_ID,
        slots=(CONTINUITY_PROVIDER_PACKS_SLOT,),
        defaults=(
            RuntimeCapabilitySelection(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation=CODING_CONTINUITY_IMPLEMENTATION,
                implementation_version=CODING_CONTINUITY_IMPLEMENTATION_VERSION,
            ),
        ),
    )
    admitted = RuntimeProfileAdmissionPolicy(
        grants=grant_values,
        slot_permissions={
            CONTINUITY_PROVIDER_PACKS_SLOT.key: frozenset({"continuity.provider"})
        },
    ).admit(plan, layer_values)
    profile = RuntimeProfileResolver().resolve(
        plan,
        layers=admitted.require_valid(),
    )
    registry = RuntimeCapabilityRegistry(
        (
            RuntimeCapabilityImplementation(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation=CODING_CONTINUITY_IMPLEMENTATION,
                implementation_version=CODING_CONTINUITY_IMPLEMENTATION_VERSION,
                create=lambda _selection, context: ContinuityProviderPack(
                    providers=(CodingContinuityProvider(_require_runtime(context)),)
                ),
            ),
            *implementation_values,
        )
    )
    binder = RuntimeProfileBinder(registry)
    binding = binder.bind_sync(profile, context=runtime)
    composition = compose_experience_continuity(
        experience=ExperienceDescriptor(
            experience_id=CODING_EXPERIENCE_ID,
            label="Coding",
            domain_ids=("coding",),
            default_domain_id="coding",
        ),
        binding=binding,
    )
    result = CodingContinuityComposition(
        binding=binding,
        binder=binder,
        hub=ContinuityHub(composition),
    )
    try:
        setattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, result)
    except (AttributeError, TypeError):
        pass
    else:
        result.runtime_owned = True
    return result


async def shutdown_coding_continuity(runtime: object) -> None:
    composition = getattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, None)
    if not isinstance(composition, CodingContinuityComposition):
        return
    with suppress(AttributeError):
        delattr(runtime, _RUNTIME_BINDING_ATTRIBUTE)
    await composition.shutdown()


def _require_runtime(value: object | None) -> CodingContinuityRuntimePort:
    if value is None:
        raise TypeError("Coding continuity requires a Product session runtime")
    return value  # type: ignore[return-value]


def _continuity_summary(
    indexed: IndexedProjection[SessionSummary],
) -> ContinuitySummary:
    summary = indexed.projection
    return ContinuitySummary(
        target=ContinuityTarget(
            provider_id=CODING_CONTINUITY_PROVIDER_ID,
            opaque_id=summary.session_id,
            revision=str(indexed.source_revision),
        ),
        domain_ids=("coding",),
        primary_domain_id="coding",
        title=_summary_title(summary),
        updated_at=summary.updated_at,
        created_at=summary.created_at,
        subtitle=None,
        excerpt=summary.last_message_preview or summary.first_message,
        status="Needs attention" if summary.has_diagnostics else None,
    )


def _summary_title(summary: SessionSummary) -> str:
    for value in (summary.name, summary.first_message, summary.session_id[:8]):
        if isinstance(value, str) and (normalized := " ".join(value.split())):
            return normalized[:512]
    return summary.session_id[:8]


__all__ = [
    "CODING_CONTINUITY_IMPLEMENTATION",
    "CODING_CONTINUITY_IMPLEMENTATION_VERSION",
    "CODING_CONTINUITY_PROVIDER_ID",
    "CODING_EXPERIENCE_ID",
    "CodingContinuityComposition",
    "CodingContinuityProvider",
    "StaleContinuityTargetError",
    "bind_coding_continuity",
    "shutdown_coding_continuity",
]
