"""Coding's Product adapter for the Harness Continuity contracts."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol

from loushang.ai.types import AssistantMessage, UserMessage
from loushang.coding.resume.history import (
    read_coding_resume_header as read_coding_resume_header,
)
from loushang.coding.resume.history import (
    read_coding_resume_recent_page as read_coding_resume_recent_page,
)
from loushang.coding.resume.history import (
    read_coding_resume_snapshot as read_coding_resume_snapshot,
)
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
    build_continuity_hub,
    compose_experience_continuity,
)
from loushang.harness.continuity._binding_lifetime import (
    _ContinuityBindingReservationLifetime,
    _ContinuityCompositionLifetime,
    delete_runtime_binding_if,
    retry_bound_continuity_reservation,
    shutdown_bound_continuity,
)
from loushang.harness.continuity._payload_staging import (
    _ContinuityPayloadStaging,
)
from loushang.harness.continuity._payload_staging import (
    _PrivateContinuityPayload as _PrivateContinuityPayload,
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
from loushang.harness.journal._owned_io import settled_io
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
)
from loushang.harness.session._continuity_index import (
    _IndexedSessionContinuity,
    _IndexedSessionRuntime,
    _PreparedIndexedSession,
    canonical_session_directory,
)
from loushang.harness.transcript import (
    SessionAssetHealthSummary,
    SessionIndexPage,
    SessionSummary,
    assistant_message_text,
    session_summary_authority_is_current,
    session_summary_revision,
    user_message_text,
)
from loushang.harness.transcript.jsonl_file import AgentTranscriptFileError

if TYPE_CHECKING:
    from loushang.coding.resume.history import (
        CodingResumeHeaderPreview,
        CodingResumeHistoryPreview,
        CodingResumeRecentPage,
    )


CODING_CONTINUITY_PROVIDER_ID = "coding.sessions"
CODING_CONTINUITY_IMPLEMENTATION = "coding.session_continuity"
CODING_CONTINUITY_IMPLEMENTATION_VERSION = 1
CODING_EXPERIENCE_ID = "coding"

_MAX_PREVIEW_CACHE = 256
_INDEX_REQUIRES_MESSAGES = True
_INDEX_STATUS_DIAGNOSTICS = {
    "expired": (
        "coding_continuity_snapshot_expired",
        "The Coding session index traversal expired; restart search.",
    ),
    "bounded": (
        "coding_continuity_bounded_catalog",
        "Showing recent Coding sessions from bounded transcript previews.",
    ),
    "unavailable": (
        "coding_continuity_index_not_ready",
        "Coding session history is being indexed.",
    ),
}
_MAX_CODING_CONTINUITY_IMPORT_BYTES = 64 * 1024 * 1024
_RUNTIME_BINDING_ATTRIBUTE = "_loushang_coding_continuity"


class CodingContinuityRuntimePort(_IndexedSessionRuntime, Protocol):
    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        *,
        fallback_cwd: str | Path | None = None,
        missing_cwd: str = "error",
    ) -> CodingPreparedSessionOperation: ...


class CodingPreparedSessionOperation(_PreparedIndexedSession, Protocol):
    pass



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
        return await CallbackPreparedActivationLease._from_staged_payload(
            target=target,
            payload=payload,
            staging=_CONTINUITY_PAYLOAD_STAGING,
            root=self._temporary_root,
            prepare=lambda path: self._runtime.prepare_restore_session_operation(
                path,
                fallback_cwd=self._fallback_cwd,
                missing_cwd="fallback" if self._fallback_cwd is not None else "error",
            ),
            settlement_error_label="Coding prepared Session",
        )


class StaleContinuityTargetError(RuntimeError):
    """Raised when a selected summary no longer matches transcript authority."""


class ConflictedContinuityTargetError(RuntimeError):
    """Raised when one Session identity has different discovered authorities."""


class CodingContinuityProvider(_IndexedSessionContinuity):
    """Adapt Agent transcript summaries without leaking Coding UI or Git facts."""

    _provider_id = CODING_CONTINUITY_PROVIDER_ID
    _product_label = "Coding"
    _max_preview_cache = _MAX_PREVIEW_CACHE
    _requires_messages = _INDEX_REQUIRES_MESSAGES
    _stale_target_error = StaleContinuityTargetError
    _index_status_diagnostics = _INDEX_STATUS_DIAGNOSTICS

    def __init__(
        self,
        runtime: CodingContinuityRuntimePort,
        *,
        cwd: str | Path | None = None,
        all_sessions: bool = False,
    ) -> None:
        super().__init__(
            runtime,
            cwd=cwd,
            all_sessions=all_sessions,
        )

    def _summarize(self, indexed: IndexedProjection[SessionSummary]) -> ContinuitySummary:
        return _continuity_summary(indexed)

    def _discovery_diagnostics(self, page: SessionIndexPage) -> list[ContinuityDiagnostic]:
        return _session_index_discovery_diagnostics(page)

    def _require_summary_allowed(self, summary: SessionSummary, *, deleting: bool) -> None:
        _require_unconflicted_summary(summary, deleting=deleting)

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

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        indexed = self._cached_target(target)
        summary = indexed.projection
        history_changed = False
        history_text: str | None = None
        rows = [
            ("Session ID", summary.session_id),
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
        if summary.session_file is not None:
            observed = await _read_history_preview(
                self._runtime,
                summary.session_file,
                session_id=summary.session_id,
                authority_fingerprint=summary.authority_fingerprint,
                max_bytes=1024 * 1024,
            )
            history_changed = observed.changed
            history = observed.header
            if history is None:
                rows.append(
                    (
                        "History identity",
                        "Changed; refresh" if history_changed else "Unavailable",
                    )
                )
            else:
                rows.append(
                    (
                        "History identity",
                        "Coding"
                        if history.product_identity == "coding"
                        else "Unverified",
                    )
                )
                rows.append(
                    (
                        "Historical composition",
                        history.composition.set_id
                        if history.composition is not None
                        else "Legacy unknown",
                    )
                )
                if observed.snapshot is not None:
                    history_text = _readonly_history_text(
                        observed.snapshot.selected_records
                    )
                    start_planning = getattr(
                        self._runtime, "start_configured_resume_planning", None
                    )
                    if callable(start_planning):
                        try:
                            planning_started = await start_planning(observed.snapshot)
                        except (OSError, RuntimeError, TypeError, ValueError):
                            rows.append(("Resume preparation", "Unavailable"))
                        else:
                            if planning_started is True:
                                rows.append(("Resume preparation", "In progress"))
                elif observed.recent is not None:
                    history_text = _readonly_history_text(observed.recent.records)
                    rows.append(("Recent history", "Unverified tail preview"))
                elif not history_changed:
                    rows.append(("Recent history", "Bounded preview unavailable"))
        inspect_assets = getattr(
            self._runtime,
            "inspect_discovered_session_assets",
            None,
        )
        if callable(inspect_assets) and summary.session_file is not None:
            try:
                asset_health = await settled_io(
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
        if summary.authority_fingerprint is not None:
            history_changed = (
                not session_summary_authority_is_current(summary) or history_changed
            )
        if history_changed:
            history_text = None
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
        revision = session_summary_revision(summary, indexed.source_revision)
        return ContinuityPreview(
            target=target,
            revision=revision,
            heading=_summary_title(summary),
            sections=(
                ContinuityPreviewSection(
                    kind="text",
                    text=(
                        "History changed; refresh"
                        if history_changed
                        else history_text
                        or summary.last_message_preview
                        or summary.first_message
                    ),
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
            stale=revision != target.revision or history_changed,
        )


@dataclass
class CodingContinuityComposition(_ContinuityCompositionLifetime):
    binding: RuntimeProfileBinding
    binder: RuntimeProfileBinder
    hub: ContinuityHub
    plugin_publication: ContinuityPluginPublication | None = None
    owned_cleanup: Callable[[], None] | None = None
    runtime_owned: bool = False
    binding_cwd: str | None = None
    all_sessions: bool = False
    configured_request_fingerprint: str | None = None
    _core_shutdown: bool = False
    _owned_cleanup_complete: bool = False
    _shutdown: bool = False


async def resolve_coding_continuity_history_source(
    composition: CodingContinuityComposition,
    target: ContinuityTarget,
) -> str | Path:
    """Resolve an admitted native Coding target for history-first Resume."""

    if not isinstance(composition, CodingContinuityComposition):
        raise TypeError("Coding continuity composition is invalid")
    if not isinstance(target, ContinuityTarget):
        raise TypeError("Coding continuity target is invalid")
    if target.provider_id != CODING_CONTINUITY_PROVIDER_ID:
        raise RuntimeError(
            "History-first Resume requires a native Coding session target"
        )
    providers = tuple(
        bound.provider
        for bound in composition.hub.composition.continuity_providers
        if bound.provider.descriptor.provider_id == CODING_CONTINUITY_PROVIDER_ID
    )
    if len(providers) != 1 or type(providers[0]) is not CodingContinuityProvider:
        raise RuntimeError("Native Coding continuity authority is unavailable")
    return await providers[0].resolve_history_source(target)


@dataclass
class _CodingContinuityBindingReservation(_ContinuityBindingReservationLifetime):
    _base_cleanup_code: ClassVar[str] = "coding_continuity_base_cleanup_retryable"
    binder: RuntimeProfileBinder | None = None
    binding: RuntimeProfileBinding | None = None
    generation: ContinuityPluginGeneration | None = None
    construction_cleanup: ContinuityPluginPendingCleanup | None = None
    generation_authority: ContinuityPluginGenerationAuthority | None = None


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
        binding_cwd=canonical_session_directory(cwd),
        all_sessions=all_sessions,
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
        cleanup_codes = await _retry_coding_continuity_reservation_atomic(
            runtime,
            reservation,
        )
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
        binding_cwd=canonical_session_directory(cwd),
        all_sessions=all_sessions,
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


_CONTINUITY_PAYLOAD_STAGING = _ContinuityPayloadStaging(label="Coding continuity")
_write_private_continuity_payload = _CONTINUITY_PAYLOAD_STAGING.write
_remove_private_continuity_payload = _CONTINUITY_PAYLOAD_STAGING.remove
_write_private_continuity_payload_atomic = _CONTINUITY_PAYLOAD_STAGING.write_atomic
_remove_private_continuity_payload_atomic = _CONTINUITY_PAYLOAD_STAGING.remove_atomic
_supports_continuity_directory_handles = (
    _CONTINUITY_PAYLOAD_STAGING.supports_directory_handles
)


async def _retry_coding_continuity_reservation_atomic(
    runtime: object,
    reservation: _CodingContinuityBindingReservation,
) -> tuple[str, ...]:
    return await retry_bound_continuity_reservation(
        runtime, reservation, binding_attribute=_RUNTIME_BINDING_ATTRIBUTE
    )


async def shutdown_coding_continuity(runtime: object) -> None:
    await shutdown_bound_continuity(
        runtime,
        binding_attribute=_RUNTIME_BINDING_ATTRIBUTE,
        composition_type=CodingContinuityComposition,
        reservation_type=_CodingContinuityBindingReservation,
        cleanup_error_message="Coding continuity binding cleanup remains retryable.",
        cleanup_error_code="coding_continuity_binding_cleanup_retryable",
    )


def get_coding_continuity_composition(
    runtime: object,
) -> CodingContinuityComposition | None:
    """Return the process-sealed composition without recomposing another scope."""

    composition = getattr(runtime, _RUNTIME_BINDING_ATTRIBUTE, None)
    return composition if isinstance(composition, CodingContinuityComposition) else None


def supports_coding_continuity_secure_staging() -> bool:
    """Report whether portable Plugin payloads can be staged safely."""

    return _supports_continuity_directory_handles()


def _delete_runtime_binding_if(runtime: object, expected: object) -> None:
    delete_runtime_binding_if(
        runtime, expected, binding_attribute=_RUNTIME_BINDING_ATTRIBUTE
    )


def _require_runtime(value: object | None) -> CodingContinuityRuntimePort:
    if value is None:
        raise TypeError("Coding continuity requires a Product session runtime")
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class _HistoryPreview:
    header: CodingResumeHeaderPreview | None = None
    snapshot: CodingResumeHistoryPreview | None = None
    recent: CodingResumeRecentPage | None = None
    changed: bool = False


async def _read_history_preview(
    runtime: object,
    path: Path,
    *,
    session_id: str,
    authority_fingerprint: str | None,
    max_bytes: int,
) -> _HistoryPreview:
    # Keep each native read owned through completion even if the preview is cancelled.
    try:
        header = await settled_io(read_coding_resume_header, path)
    except (OSError, ValueError):
        return _HistoryPreview()
    if header.header.conversation_id != session_id:
        return _HistoryPreview(changed=True)

    def matches(evidence: CodingResumeHistoryPreview | CodingResumeRecentPage) -> bool:
        return evidence.header_preview.header == header.header and (
            authority_fingerprint is None
            or evidence.source_fingerprint == authority_fingerprint
        )

    try:
        from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime

        if isinstance(runtime, AgentSessionRuntime):
            snapshot = await AgentSessionRuntime.preview_resume_history(
                runtime, path, max_bytes=max_bytes
            )
        else:
            snapshot = await settled_io(
                read_coding_resume_snapshot, path, max_bytes=max_bytes
            )
    except AgentTranscriptFileError as error:
        if error.code != "session_file_too_large":
            return _HistoryPreview(header=header)
        try:
            if isinstance(runtime, AgentSessionRuntime):
                recent = await AgentSessionRuntime.preview_resume_recent_page(
                    runtime, path
                )
            else:
                recent = await settled_io(read_coding_resume_recent_page, path)
        except (OSError, ValueError):
            return _HistoryPreview(header=header)
        if not recent.records:
            return _HistoryPreview(header=header)
        if not matches(recent):
            return _HistoryPreview(header=header, changed=True)
        return _HistoryPreview(header=header, recent=recent)
    except (OSError, ValueError):
        return _HistoryPreview(header=header)
    if not matches(snapshot):
        return _HistoryPreview(header=header, changed=True)
    return _HistoryPreview(header=header, snapshot=snapshot)


def _session_index_discovery_diagnostics(
    page: SessionIndexPage,
) -> list[ContinuityDiagnostic]:
    return [
        ContinuityDiagnostic(
            code=f"coding_session_discovery_{issue.code}",
            message=f"Ignored Session source {issue.source_id}: {issue.detail}.",
            provider_id=CODING_CONTINUITY_PROVIDER_ID,
        )
        for issue in page.discovery_issues
    ]


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


def _readonly_history_text(records: Iterable[object]) -> str | None:
    """Show a few selected-path messages without activating their Session."""

    recent: list[str] = []
    for record in reversed(tuple(records)):
        payload = getattr(record, "payload", None)
        text: str | None
        if isinstance(payload, UserMessage):
            label, text = "You", user_message_text(payload)
        elif isinstance(payload, AssistantMessage):
            label, text = "Assistant", assistant_message_text(payload)
        else:
            continue
        normalized = " ".join(text.split()) if text else ""
        if not normalized:
            continue
        recent.append(f"{label}: {normalized[:160]}")
        if len(recent) == 3:
            break
    return "\n".join(reversed(recent)) if recent else None


def _require_unconflicted_summary(
    summary: SessionSummary, *, deleting: bool = False
) -> None:
    discovery = summary.discovery
    if discovery is not None and not discovery.resumable:
        raise ConflictedContinuityTargetError(
            "This Session ID has different transcripts in multiple discovery "
            "sources. Select an exact path or resolve the conflict before resume."
        )

    if deleting and summary.discovery is not None and summary.discovery.mode != "canonical":
        raise RuntimeError(
            "Compatibility Sessions are read-only; resume them before deletion."
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
    "get_coding_continuity_composition",
    "resolve_coding_continuity_history_source",
    "shutdown_coding_continuity",
    "supports_coding_continuity_secure_staging",
]
