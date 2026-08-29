"""Coding's Product adapter for the Harness Continuity contracts."""

from __future__ import annotations

import asyncio
import os
import secrets
import stat
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.harness.capabilities.owner_component_host import (
    CapabilityOwnerComponentHost,
)
from loushang.harness.continuity import (
    CallbackPreparedActivationLease,
    ContinuityActivationPayload,
    ContinuityArtifactReference,
    ContinuityDeletionRecoveryAuthority,
    ContinuityDiagnostic,
    ContinuityHub,
    ContinuityPreview,
    ContinuityPreviewSection,
    ContinuityProviderDescriptor,
    ContinuityProviderPack,
    ContinuityProviderSourceDescriptor,
    ContinuitySummary,
    ContinuityTarget,
    ExperienceComposition,
    ExperienceDescriptor,
    ProviderPage,
    ProviderPageItem,
    ProviderQuery,
    build_continuity_hub,
    compose_experience_continuity,
)
from loushang.harness.continuity.plugin_runtime import (
    ContinuityPluginGeneration,
    ContinuityPluginGenerationAuthority,
    ContinuityPluginInstanceFamilyAuthority,
    ContinuityPluginLifecycleError,
    ContinuityPluginPendingCleanup,
    ContinuityPluginPublication,
    ResolvedContinuityPluginSelection,
    construct_continuity_plugin_generation,
    publish_continuity_plugin_generation,
    publish_continuity_plugin_generation_with_mutations,
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
    SessionAssetHealthSummary,
    SessionIndexPage,
    SessionQuery,
    SessionSummary,
    same_agent_transcript_session_path,
    session_summary_authority_is_current,
    session_summary_revision,
)

CODING_CONTINUITY_PROVIDER_ID = "coding.sessions"
CODING_CONTINUITY_IMPLEMENTATION = "coding.session_continuity"
CODING_CONTINUITY_IMPLEMENTATION_VERSION = 1
CODING_EXPERIENCE_ID = "coding"

_MAX_PREVIEW_CACHE = 256
_MAX_CODING_CONTINUITY_IMPORT_BYTES = 64 * 1024 * 1024
_RUNTIME_BINDING_ATTRIBUTE = "_loushang_coding_continuity"

T = TypeVar("T")


class CodingContinuityRuntimePort(Protocol):
    session_dir: Path

    def try_query_session_index_page(
        self,
        query: SessionQuery | None = None,
        *,
        cursor: str | None = None,
        limit: int = 25,
        ignore_authority: str | Path | None = None,
    ) -> SessionIndexPage: ...

    def request_session_index_refresh(self, *, all_sessions: bool = False) -> None: ...

    def request_session_index_repair(self) -> None: ...

    def request_bounded_session_index_refresh(self) -> None: ...

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

    async def close(self) -> None: ...


class CodingContinuityActivationBridge:
    """Import portable bytes through Coding's canonical Session lifecycle."""

    def __init__(
        self,
        runtime: CodingContinuityRuntimePort,
        *,
        temporary_root: str | Path | None = None,
        fallback_cwd: str | Path | None = None,
        max_bytes: int = _MAX_CODING_CONTINUITY_IMPORT_BYTES,
    ) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise TypeError("Coding continuity import limit must be an integer")
        if not 1 <= max_bytes <= _MAX_CODING_CONTINUITY_IMPORT_BYTES:
            raise ValueError("Coding continuity import limit is invalid")
        self._runtime = runtime
        temporary_path = Path(
            temporary_root
            if temporary_root is not None
            else resolve_platform_paths().temporary / "continuity-import"
        ).expanduser()
        absolute = Path(os.path.abspath(temporary_path))
        self._temporary_root = absolute.parent.resolve(strict=False) / absolute.name
        self._fallback_cwd = (
            None
            if fallback_cwd is None
            else str(Path(fallback_cwd).expanduser().resolve(strict=False))
        )
        self._max_bytes = max_bytes

    async def prepare(
        self,
        target: ContinuityTarget,
        payload: ContinuityActivationPayload,
        source: ContinuityProviderSourceDescriptor,
    ) -> CallbackPreparedActivationLease:
        if not isinstance(target, ContinuityTarget):
            raise TypeError("Coding continuity activation target is invalid")
        if not isinstance(payload, ContinuityActivationPayload):
            raise TypeError("Coding continuity activation payload is invalid")
        if not isinstance(source, ContinuityProviderSourceDescriptor):
            raise TypeError("Coding continuity activation source is invalid")
        if source.provider_id != target.provider_id:
            raise ValueError("Coding continuity activation source does not own target")
        if payload.byte_size > self._max_bytes:
            raise ValueError("Coding continuity activation exceeds Product limit")
        staged = await _write_private_continuity_payload_atomic(
            self._temporary_root,
            payload,
        )
        try:
            prepared = await self._runtime.prepare_restore_session_operation(
                staged.path,
                fallback_cwd=self._fallback_cwd,
                missing_cwd="fallback" if self._fallback_cwd is not None else "error",
            )
        except BaseException as operation_error:
            try:
                await _remove_private_continuity_payload_atomic(staged)
            except BaseException as cleanup_error:
                operation_error.add_note(
                    "Coding continuity temporary cleanup also failed: "
                    f"{cleanup_error!r}"
                )
            raise
        try:
            await _remove_private_continuity_payload_atomic(staged)
        except BaseException as cleanup_error:
            try:
                abort_task = asyncio.create_task(prepared.abort())
                await _await_owned_task_cancellation_atomic(abort_task)
            except BaseException as abort_error:
                cleanup_error.add_note(
                    "Coding continuity prepared-operation abort also failed: "
                    f"{abort_error!r}"
                )
            raise
        settlement = _CodingPreparedSessionSettlement(prepared)
        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=settlement.consume,
            abort=settlement.abort,
        )


class StaleContinuityTargetError(RuntimeError):
    """Raised when a selected summary no longer matches transcript authority."""


class ConflictedContinuityTargetError(RuntimeError):
    """Raised when one Session identity has different discovered authorities."""


class CodingContinuityProvider:
    """Adapt Agent transcript summaries without leaking Coding UI or Git facts."""

    def __init__(
        self,
        runtime: CodingContinuityRuntimePort,
        *,
        cwd: str | Path | None = None,
        all_sessions: bool = False,
    ) -> None:
        self._runtime = runtime
        self._cwd = (
            str(Path(cwd).expanduser().resolve(strict=False))
            if cwd is not None
            else None
        )
        self._all_sessions = all_sessions
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
        current_reference = self._runtime.get_current_session_ref()
        page = await asyncio.to_thread(
            self._runtime.try_query_session_index_page,
            SessionQuery(
                cwd=None if self._all_sessions else self._query_cwd(),
                text=request.text or None,
                sort_by="created" if request.sort_id == "created" else "recent",
                has_messages=True,
                source_mode=(
                    "canonical" if "delete" in request.required_actions else None
                ),
                exclude_session_file=current_reference,
            ),
            cursor=request.cursor,
            limit=request.limit,
            ignore_authority=current_reference,
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
        diagnostics = [
            ContinuityDiagnostic(
                code=f"coding_session_discovery_{issue.code}",
                message=(f"Ignored Session source {issue.source_id}: {issue.detail}."),
                provider_id=CODING_CONTINUITY_PROVIDER_ID,
            )
            for issue in page.discovery_issues
        ]
        if page.restart_required:
            diagnostics.append(
                ContinuityDiagnostic(
                    code="coding_continuity_snapshot_expired",
                    message="The Coding session index traversal expired; restart search.",
                    provider_id=CODING_CONTINUITY_PROVIDER_ID,
                )
            )
        elif page.index_state != "fresh":
            if not self._index_refresh_requested:
                if page.bounded_fallback:
                    self._runtime.request_bounded_session_index_refresh()
                else:
                    self._runtime.request_session_index_repair()
                self._index_refresh_requested = True
            diagnostics.append(
                ContinuityDiagnostic(
                    code=(
                        "coding_continuity_bounded_catalog"
                        if page.bounded_fallback
                        else "coding_continuity_index_not_ready"
                    ),
                    message=(
                        "Showing recent Coding sessions from bounded transcript "
                        "previews."
                        if page.bounded_fallback
                        else "Coding session history is being indexed."
                    ),
                    provider_id=CODING_CONTINUITY_PROVIDER_ID,
                )
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
            diagnostics=tuple(diagnostics),
        )

    def _query_cwd(self) -> str | None:
        if self._cwd is not None:
            return self._cwd
        try:
            value = getattr(self._runtime, "cwd", None)
        except Exception:
            return None
        if not isinstance(value, str) or not value:
            return None
        return str(Path(value).expanduser().resolve(strict=False))

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        indexed = self._cached_target(target)
        summary = indexed.projection
        rows = [
            ("Workspace", summary.cwd or "Unknown"),
            (
                "Messages",
                str(summary.message_count)
                if summary.counts_exact
                else f"at least {summary.message_count}",
            ),
            (
                "Entries",
                str(summary.entry_count)
                if summary.counts_exact
                else f"at least {summary.entry_count}",
            ),
        ]
        discovery = summary.discovery
        if discovery is not None:
            rows.extend(
                (
                    ("Storage", _session_storage_label(summary)),
                    ("Health", _session_health_label(summary)),
                )
            )
            if discovery.aliases:
                rows.append(("Compatible copies", str(len(discovery.aliases))))
            if discovery.conflicts:
                rows.append(("Conflicting copies", str(len(discovery.conflicts))))
        inspect_assets = getattr(
            self._runtime,
            "inspect_discovered_session_assets",
            None,
        )
        if callable(inspect_assets) and summary.session_file is not None:
            try:
                asset_health = await asyncio.to_thread(
                    inspect_assets,
                    summary.session_file,
                )
            except (OSError, ValueError):
                asset_health = SessionAssetHealthSummary(state="unavailable")
            if isinstance(asset_health, SessionAssetHealthSummary):
                rows.append(("Assets", _asset_health_label(asset_health)))
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
            revision=session_summary_revision(summary, indexed.source_revision),
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
            stale=(
                session_summary_revision(summary, indexed.source_revision)
                != target.revision
            ),
        )

    async def prepare(
        self,
        target: ContinuityTarget,
    ) -> CallbackPreparedActivationLease:
        indexed = self._cached_target(target)
        summary = indexed.projection
        _require_unconflicted_summary(summary)
        expected_revision = session_summary_revision(
            summary,
            indexed.source_revision,
        )
        if target.revision != expected_revision:
            raise StaleContinuityTargetError(
                "The selected Coding session summary is stale."
            )
        # Index rows are advisory projections. Resolve their raw identity against
        # fresh path-level discovery so a same-source duplicate cannot be activated
        # through a stale collapsed index entry.
        reference: str | Path = (
            summary.session_id
            if summary.discovery is not None
            else summary.session_file or summary.session_id
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
        if summary.authority_fingerprint is not None:
            if not session_summary_authority_is_current(summary):
                raise StaleContinuityTargetError(
                    "The selected Coding session changed after it was listed."
                )
        else:
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
        if (
            summary.authority_fingerprint is not None
            and not session_summary_authority_is_current(summary)
        ):
            await candidate.abort()
            raise StaleContinuityTargetError(
                "The selected Coding session changed while it was being prepared."
            )
        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=candidate.consume,
            abort=candidate.abort,
        )

    async def delete(self, target: ContinuityTarget) -> bool:
        indexed = self._cached_target(target)
        summary = indexed.projection
        _require_unconflicted_summary(summary)
        if summary.discovery is not None and summary.discovery.mode != "canonical":
            raise RuntimeError(
                "Compatibility Sessions are read-only; resume them before deletion."
            )
        expected_revision = session_summary_revision(
            summary,
            indexed.source_revision,
        )
        if target.revision != expected_revision:
            raise StaleContinuityTargetError(
                "The selected Coding session summary is stale."
            )
        reference: str | Path = (
            summary.session_id
            if summary.discovery is not None
            else summary.session_file or summary.session_id
        )
        if _same_session_reference(
            self._runtime.get_current_session_ref(),
            reference,
        ):
            raise ValueError("Cannot delete the currently active session")
        if summary.authority_fingerprint is not None:
            if not session_summary_authority_is_current(summary):
                raise StaleContinuityTargetError(
                    "The selected Coding session changed after it was listed."
                )
        else:
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
    plugin_publication: ContinuityPluginPublication | None = None
    owned_cleanup: Callable[[], None] | None = None
    runtime_owned: bool = False
    _core_shutdown: bool = False
    _owned_cleanup_complete: bool = False
    _shutdown: bool = False

    async def dispose(self) -> None:
        """Release a caller view; the process-scoped runtime remains bound."""

        if not self.runtime_owned:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Close the authority, then dispose the process-scoped binding.

        Close-then-record: shutdown completion is recorded only after the hub
        has staled references, aborted outstanding activation leases, joined
        in-flight operations, and the binding has been disposed.  A failed or
        cancelled close leaves the composition unrecorded and retryable.
        """

        if self._shutdown:
            return
        if not self._core_shutdown:
            if self.plugin_publication is None:
                await self.hub.close()
            else:
                await self.plugin_publication.shutdown()
            await self.binder.dispose(self.binding)
            self._core_shutdown = True
        if not self._owned_cleanup_complete:
            if self.owned_cleanup is not None:
                self.owned_cleanup()
            self._owned_cleanup_complete = True
        self._shutdown = True


@dataclass
class _CodingContinuityBindingReservation:
    binder: RuntimeProfileBinder | None = None
    binding: RuntimeProfileBinding | None = None
    generation: ContinuityPluginGeneration | None = None
    construction_cleanup: ContinuityPluginPendingCleanup | None = None
    generation_authority: ContinuityPluginGenerationAuthority | None = None

    async def retry_cleanup(self) -> tuple[str, ...]:
        codes: list[str] = []
        construction_cleanup = self.construction_cleanup
        if construction_cleanup is not None:
            try:
                await construction_cleanup.retry()
            except BaseException:
                codes.append("continuity_provider_construction_cleanup_retryable")
            else:
                self.construction_cleanup = None
        generation = self.generation
        if generation is not None:
            try:
                await generation.dispose()
            except BaseException:
                codes.append("continuity_provider_generation_cleanup_retryable")
            else:
                self.generation = None
        if self.binder is not None and self.binding is not None:
            try:
                await self.binder.dispose(self.binding)
            except BaseException:
                codes.append("coding_continuity_base_cleanup_retryable")
            else:
                self.binder = None
                self.binding = None
        return tuple(codes)


def bind_coding_continuity(
    runtime: CodingContinuityRuntimePort,
    *,
    cwd: str | Path | None = None,
    all_sessions: bool = False,
    layers: Iterable[RuntimeProfileLayer] = (),
    grants: Iterable[RuntimeProfileLayerGrant] = (),
    implementations: Iterable[RuntimeCapabilityImplementation] = (),
) -> CodingContinuityComposition:
    """Bind Product/OEM continuity packs once for one Coding runtime."""

    layer_values = tuple(layers)
    grant_values = tuple(grants)
    implementation_values = tuple(implementations)
    if any(layer.source == "extension" for layer in layer_values):
        raise ValueError("Coding continuity does not admit direct extension layers")
    cached = getattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, None)
    if isinstance(cached, CodingContinuityComposition):
        if layer_values or grant_values or implementation_values:
            raise RuntimeError(
                "Coding continuity is already sealed for this Product runtime"
            )
        return cached
    if cached is not None:
        raise RuntimeError("Coding continuity binding or cleanup is already pending")

    binder, binding, composition = _compose_coding_continuity_base(
        runtime,
        cwd=cwd,
        all_sessions=all_sessions,
        layers=layer_values,
        grants=grant_values,
        implementations=implementation_values,
    )
    result = CodingContinuityComposition(
        binding=binding,
        binder=binder,
        hub=build_continuity_hub(composition),
    )
    _retain_coding_continuity(runtime, result)
    return result


async def bind_coding_plugin_continuity(
    runtime: CodingContinuityRuntimePort,
    *,
    resolved_plugins: ResolvedContinuityPluginSelection,
    component_host: CapabilityOwnerComponentHost,
    activation_decision_ids: Mapping[str, str],
    instance_family_authority: ContinuityPluginInstanceFamilyAuthority,
    runtime_id: str,
    deletion_authority: ContinuityDeletionRecoveryAuthority | None = None,
    owned_cleanup: Callable[[], None] | None = None,
    cwd: str | Path | None = None,
    all_sessions: bool = False,
    temporary_root: str | Path | None = None,
    fallback_cwd: str | Path | None = None,
    layers: Iterable[RuntimeProfileLayer] = (),
    grants: Iterable[RuntimeProfileLayerGrant] = (),
    implementations: Iterable[RuntimeCapabilityImplementation] = (),
) -> CodingContinuityComposition:
    """Bind Coding's canonical Provider with one approved Plugin generation."""

    existing = getattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, None)
    if existing is not None:
        raise RuntimeError(
            "Coding continuity is already sealed for this Product runtime"
        )
    layer_values = tuple(layers)
    if any(layer.source == "extension" for layer in layer_values):
        raise ValueError("Coding continuity does not admit direct extension layers")
    generation_authority = ContinuityPluginGenerationAuthority(
        product_id=CODING_EXPERIENCE_ID,
        runtime_id=runtime_id,
    )
    reservation = _CodingContinuityBindingReservation(
        generation_authority=generation_authority,
    )
    try:
        setattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, reservation)
    except (AttributeError, TypeError) as exc:
        raise RuntimeError(
            "Plugin continuity runtime must retain its sealed binding"
        ) from exc
    generation = None
    try:
        binder, binding, base = _compose_coding_continuity_base(
            runtime,
            cwd=cwd,
            all_sessions=all_sessions,
            layers=layer_values,
            grants=tuple(grants),
            implementations=tuple(implementations),
        )
        reservation.binder = binder
        reservation.binding = binding
        generation = await construct_continuity_plugin_generation(
            resolved_plugins,
            component_host=component_host,
            activation_decision_ids=activation_decision_ids,
            instance_family_authority=instance_family_authority,
            generation_authority=generation_authority,
        )
        reservation.generation = generation
        activation_bridge = CodingContinuityActivationBridge(
            runtime,
            temporary_root=temporary_root,
            fallback_cwd=fallback_cwd,
        )
        if deletion_authority is None:
            publication = publish_continuity_plugin_generation(
                base,
                generation,
                activation_bridge=activation_bridge,
            )
        else:
            publication = await publish_continuity_plugin_generation_with_mutations(
                base,
                generation,
                activation_bridge=activation_bridge,
                deletion_authority=deletion_authority,
            )
    except BaseException as error:
        if (
            isinstance(error, ContinuityPluginLifecycleError)
            and error.pending_cleanup is not None
        ):
            reservation.construction_cleanup = error.pending_cleanup
        cleanup_task = asyncio.create_task(reservation.retry_cleanup())
        cleanup_codes = await _await_owned_task_cancellation_atomic(cleanup_task)
        if cleanup_codes:
            cleanup_error = ContinuityPluginLifecycleError(
                "Coding continuity binding cleanup remains retryable.",
                code="coding_continuity_binding_cleanup_retryable",
            )
            for code in cleanup_codes:
                cleanup_error.add_note(code)
            raise cleanup_error from error
        _delete_runtime_binding_if(runtime, reservation)
        raise
    result = CodingContinuityComposition(
        binding=binding,
        binder=binder,
        hub=publication.hub,
        plugin_publication=publication,
        owned_cleanup=owned_cleanup,
    )
    if getattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, None) is not reservation:
        raise RuntimeError("Coding continuity binding reservation was replaced")
    setattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, result)
    result.runtime_owned = True
    return result


def _compose_coding_continuity_base(
    runtime: CodingContinuityRuntimePort,
    *,
    cwd: str | Path | None,
    all_sessions: bool,
    layers: tuple[RuntimeProfileLayer, ...],
    grants: tuple[RuntimeProfileLayerGrant, ...],
    implementations: tuple[RuntimeCapabilityImplementation, ...],
) -> tuple[RuntimeProfileBinder, RuntimeProfileBinding, ExperienceComposition]:
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
        grants=grants,
        slot_permissions={
            CONTINUITY_PROVIDER_PACKS_SLOT.key: frozenset({"continuity.provider"})
        },
    ).admit(plan, layers)
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
                    providers=(
                        CodingContinuityProvider(
                            _require_runtime(context),
                            cwd=cwd,
                            all_sessions=all_sessions,
                        ),
                    )
                ),
            ),
            *implementations,
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
    return binder, binding, composition


def _retain_coding_continuity(
    runtime: CodingContinuityRuntimePort,
    result: CodingContinuityComposition,
) -> None:
    try:
        setattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, result)
    except (AttributeError, TypeError):
        pass
    else:
        result.runtime_owned = True


@dataclass(slots=True)
class _CodingPreparedSessionSettlement:
    prepared: CodingPreparedSessionOperation
    _abort_complete: bool = False

    async def consume(self) -> object:
        try:
            return await self.prepared.consume()
        except BaseException as operation_error:
            try:
                await self.abort()
            except BaseException as abort_error:
                operation_error.add_note(
                    "Coding prepared Session abort also failed: "
                    f"{type(abort_error).__name__}"
                )
            raise

    async def abort(self) -> None:
        if self._abort_complete:
            return
        abort_task = asyncio.create_task(self.prepared.abort())
        try:
            await _await_owned_task_cancellation_atomic(abort_task)
        except BaseException:
            if _task_completed_successfully(abort_task):
                self._abort_complete = True
            raise
        self._abort_complete = True


def _task_completed_successfully(task: asyncio.Task[object]) -> bool:
    return task.done() and not task.cancelled() and task.exception() is None


@dataclass(frozen=True, slots=True)
class _PrivateContinuityPayload:
    path: Path
    file_identity: tuple[int, int]
    root_identity: tuple[int, int]
    root_descriptor: int


def _write_private_continuity_payload(
    root: Path,
    payload: ContinuityActivationPayload,
) -> _PrivateContinuityPayload:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _validate_private_continuity_path_chain(root)
    if not _supports_continuity_directory_handles():
        raise OSError(
            "Secure directory-relative Continuity staging is unavailable "
            "on this platform"
        )
    return _write_private_continuity_payload_at(root, payload)


def _write_private_continuity_payload_at(
    root: Path,
    payload: ContinuityActivationPayload,
) -> _PrivateContinuityPayload:
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    root_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    root_descriptor = os.open(root, root_flags)
    descriptor = -1
    name = ""
    try:
        root_status = os.fstat(root_descriptor)
        path_status = root.lstat()
        _validate_private_continuity_root(root, root_status)
        if not os.path.samestat(root_status, path_status):
            raise OSError("Coding continuity temporary root identity changed")
        os.fchmod(root_descriptor, 0o700)
        root_identity = (root_status.st_dev, root_status.st_ino)
        suffix = _continuity_payload_suffix(payload)
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        file_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        for _attempt in range(128):
            name = f"continuity-{secrets.token_hex(16)}{suffix}"
            try:
                descriptor = os.open(
                    name,
                    file_flags,
                    0o600,
                    dir_fd=root_descriptor,
                )
            except FileExistsError:
                continue
            break
        else:
            raise FileExistsError("Coding continuity temporary namespace is exhausted")
        os.fchmod(descriptor, 0o600)
        _write_continuity_payload_bytes(descriptor, payload.data)
        status = os.fstat(descriptor)
        file_identity = (status.st_dev, status.st_ino)
        os.close(descriptor)
        descriptor = -1
        return _PrivateContinuityPayload(
            path=root / name,
            file_identity=file_identity,
            root_identity=root_identity,
            root_descriptor=root_descriptor,
        )
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if name:
            with suppress(OSError):
                os.unlink(name, dir_fd=root_descriptor)
        os.close(root_descriptor)
        raise


def _validate_private_continuity_root(
    root: Path,
    root_status: os.stat_result,
) -> None:
    if (
        not stat.S_ISDIR(root_status.st_mode)
        or stat.S_ISLNK(root_status.st_mode)
        or bool(getattr(root_status, "st_reparse_tag", 0))
    ):
        raise OSError("Coding continuity temporary root is unsafe")
    getuid = getattr(os, "getuid", None)
    if os.name == "posix" and callable(getuid) and root_status.st_uid != getuid():
        raise PermissionError(
            f"Coding continuity temporary root belongs to another user: {root}"
        )


def _validate_private_continuity_path_chain(root: Path) -> None:
    for directory in (root, *root.parents):
        metadata = directory.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_reparse_tag", 0))
        ):
            raise OSError("Coding continuity temporary path contains an unsafe link")
        if (
            os.name == "posix"
            and metadata.st_mode & 0o022
            and not metadata.st_mode & stat.S_ISVTX
        ):
            raise PermissionError(
                "Coding continuity temporary path has a writable ancestor"
            )


def _continuity_payload_suffix(payload: ContinuityActivationPayload) -> str:
    return (
        ".loushang.zip"
        if payload.media_type.endswith("session-bundle+zip")
        else ".jsonl"
    )


def _write_continuity_payload_bytes(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written < 1:
            raise OSError("Coding continuity temporary write made no progress")
        view = view[written:]
    os.fsync(descriptor)


def _supports_continuity_directory_handles() -> bool:
    supports_dir_fd = getattr(os, "supports_dir_fd", ())
    return (
        os.name == "posix"
        and isinstance(getattr(os, "O_DIRECTORY", None), int)
        and isinstance(getattr(os, "O_NOFOLLOW", None), int)
        and os.open in supports_dir_fd
        and os.stat in supports_dir_fd
        and os.unlink in supports_dir_fd
    )


def _remove_private_continuity_payload(staged: _PrivateContinuityPayload) -> None:
    try:
        root_status = os.fstat(staged.root_descriptor)
        if (root_status.st_dev, root_status.st_ino) != staged.root_identity:
            raise OSError("Coding continuity temporary root identity changed")
        try:
            status = os.stat(
                staged.path.name,
                dir_fd=staged.root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        if (
            stat.S_ISLNK(status.st_mode)
            or bool(getattr(status, "st_reparse_tag", 0))
            or (status.st_dev, status.st_ino) != staged.file_identity
        ):
            raise OSError("Coding continuity temporary file identity changed")
        os.unlink(staged.path.name, dir_fd=staged.root_descriptor)
    finally:
        os.close(staged.root_descriptor)


async def _remove_private_continuity_payload_atomic(
    staged: _PrivateContinuityPayload,
) -> None:
    task = asyncio.create_task(
        asyncio.to_thread(_remove_private_continuity_payload, staged)
    )
    await _await_owned_task_cancellation_atomic(task)


async def _write_private_continuity_payload_atomic(
    root: Path,
    payload: ContinuityActivationPayload,
) -> _PrivateContinuityPayload:
    task = asyncio.create_task(
        asyncio.to_thread(_write_private_continuity_payload, root, payload)
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as first_cancellation:
        cancellation = first_cancellation
        caller = asyncio.current_task()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as repeated:
                if caller is None or caller.cancelling() == 0:
                    return task.result()
                cancellation = repeated
        try:
            staged = task.result()
        except BaseException as write_error:
            cancellation.add_note(
                "Coding continuity temporary write also failed: "
                f"{type(write_error).__name__}"
            )
            raise cancellation
        try:
            await _remove_private_continuity_payload_atomic(staged)
        except BaseException as cleanup_error:
            cancellation.add_note(
                "Coding continuity cancelled-write cleanup also failed: "
                f"{type(cleanup_error).__name__}"
            )
        raise cancellation


async def _await_owned_task_cancellation_atomic(
    task: asyncio.Task[T],
) -> T:
    """Join an owned cleanup task before propagating caller cancellation."""

    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = exc
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


async def shutdown_coding_continuity(runtime: object) -> None:
    composition = getattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, None)
    if isinstance(composition, _CodingContinuityBindingReservation):
        codes = await composition.retry_cleanup()
        if codes:
            error = ContinuityPluginLifecycleError(
                "Coding continuity binding cleanup remains retryable.",
                code="coding_continuity_binding_cleanup_retryable",
            )
            for code in codes:
                error.add_note(code)
            raise error
        _delete_runtime_binding_if(runtime, composition)
        return
    if not isinstance(composition, CodingContinuityComposition):
        return
    await composition.shutdown()
    _delete_runtime_binding_if(runtime, composition)


def _delete_runtime_binding_if(runtime: object, expected: object) -> None:
    if getattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, None) is not expected:
        return
    with suppress(AttributeError):
        delattr(runtime, _RUNTIME_BINDING_ATTRIBUTE)


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
            revision=session_summary_revision(summary, indexed.source_revision),
        ),
        domain_ids=("coding",),
        primary_domain_id="coding",
        title=_summary_title(summary),
        updated_at=summary.updated_at,
        created_at=summary.created_at,
        subtitle=_session_subtitle(summary),
        excerpt=summary.last_message_preview or summary.first_message,
        status=_session_status(summary),
        actions=(
            ("activate", "delete")
            if summary.discovery is None or summary.discovery.mode == "canonical"
            else ("activate",)
        ),
    )


def _summary_title(summary: SessionSummary) -> str:
    for value in (summary.name, summary.first_message, summary.session_id[:8]):
        if isinstance(value, str) and (normalized := " ".join(value.split())):
            return normalized[:512]
    return summary.session_id[:8]


def _require_unconflicted_summary(summary: SessionSummary) -> None:
    discovery = summary.discovery
    if discovery is not None and not discovery.resumable:
        raise ConflictedContinuityTargetError(
            "This Session ID has different transcripts in multiple discovery "
            "sources. Select an exact path or resolve the conflict before resume."
        )


def _session_status(summary: SessionSummary) -> str | None:
    discovery = summary.discovery
    if discovery is None:
        return "Needs attention" if summary.has_diagnostics else None
    if discovery.health == "conflict":
        return "Conflict"
    if discovery.health == "needs_attention":
        return "Needs attention"
    if summary.has_diagnostics:
        return "Needs attention"
    if discovery.health == "legacy":
        return f"Legacy · {discovery.origin}"
    return None


def _session_subtitle(summary: SessionSummary) -> str | None:
    discovery = summary.discovery
    if discovery is None or discovery.mode == "canonical":
        return summary.cwd or None
    origin = discovery.origin.capitalize()
    return f"{summary.cwd or 'Unknown workspace'} · {origin} compatibility"


def _session_storage_label(summary: SessionSummary) -> str:
    discovery = summary.discovery
    if discovery is None:
        return "Unknown"
    if discovery.mode == "canonical":
        return f"{discovery.origin.capitalize()} canonical"
    return f"{discovery.origin.capitalize()} compatibility"


def _session_health_label(summary: SessionSummary) -> str:
    discovery = summary.discovery
    if discovery is None:
        return "Unknown"
    return discovery.health.replace("_", " ").title()


def _asset_health_label(health: SessionAssetHealthSummary) -> str:
    if health.state == "none":
        return "None"
    if health.state == "unavailable":
        return "Unavailable (preview budget or read boundary)"
    suffix = f" · {health.object_count} objects · {health.total_bytes} bytes"
    if health.state == "available":
        return f"Available{suffix}"
    if health.state == "partial":
        return f"Present (integrity checked on resume){suffix}"
    return (
        f"{health.state.title()}{suffix} · "
        f"{health.missing} missing · {health.corrupt} corrupt"
    )


__all__ = [
    "CODING_CONTINUITY_IMPLEMENTATION",
    "CODING_CONTINUITY_IMPLEMENTATION_VERSION",
    "CODING_CONTINUITY_PROVIDER_ID",
    "CODING_EXPERIENCE_ID",
    "CodingContinuityComposition",
    "CodingContinuityActivationBridge",
    "CodingContinuityProvider",
    "ConflictedContinuityTargetError",
    "StaleContinuityTargetError",
    "bind_coding_continuity",
    "bind_coding_plugin_continuity",
    "shutdown_coding_continuity",
]
