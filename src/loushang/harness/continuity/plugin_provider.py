"""Continuity-owned runtime gate and adapter for installed Plugin Providers."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field, replace
from typing import Protocol

from loushang.harness.continuity.activation import ActivationLeaseStateError
from loushang.harness.continuity.composition import (
    PluginContinuityProviderProvenance,
    plugin_continuity_provider_source,
)
from loushang.harness.continuity.import_provider import (
    ContinuityActivationBridge,
    ContinuityActivationPayload,
    ContinuityImportProvider,
    PreparedContinuityImport,
)
from loushang.harness.continuity.mutation import (
    AcceptedContinuityDeletion,
    AuthorizedContinuityDeletionLease,
    ContinuityDeletionAuthority,
    ContinuityDeletionPlanV1,
    ContinuityDeletionReceiptV1,
    ContinuityDeletionRecoveryAuthority,
    ContinuityMutationLifecycleError,
    ContinuityMutationPendingCleanup,
    prepare_authorized_continuity_deletion,
)
from loushang.harness.continuity.provider import PreparedActivationLease
from loushang.harness.continuity.types import (
    ActivationDisposition,
    ContinuityDiagnostic,
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
    ProviderPage,
    ProviderQuery,
)
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic


class ContinuityPluginGenerationClosingError(RuntimeError):
    """Stable rejection after graceful or security close linearizes."""

    code = "continuity_plugin_generation_closing"


class ContinuityPluginGenerationQuiesceError(RuntimeError):
    """A poisoned in-process generation did not quiesce within its budget."""

    code = "continuity_plugin_generation_quiesce_timeout"


class ContinuityPluginMutationRecoveryError(RuntimeError):
    """Fail-closed installed mutation recovery failure."""

    code = "continuity_plugin_mutation_recovery_failed"


class ContinuityPluginProviderCallError(RuntimeError):
    """Redacted failure at the untrusted Provider call boundary."""

    def __init__(self, operation: str) -> None:
        self.code = f"continuity_plugin_provider_{operation}_failed"
        self.pending_cleanup: (
            ContinuityPluginPreparePendingCleanup
            | ContinuityPluginMutationPendingCleanup
            | None
        ) = None
        self.pending_mutation: ContinuityPluginMutationPendingSettlement | None = None
        super().__init__(f"Continuity Plugin Provider {operation} failed.")


class _GenerationLease(Protocol):
    async def abort(self) -> None: ...


class _GenerationPendingCleanup(Protocol):
    async def retry(self) -> None: ...


@dataclass(slots=True, eq=False)
class ContinuityPluginPreparePendingCleanup:
    """A caller view over generation-owned unpublished prepare cleanup."""

    product_lease: PreparedActivationLease | None
    source_lease: PreparedContinuityImport | None
    _gate: ContinuityPluginGenerationGate = field(repr=False)
    _cleanup_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _closed: bool = False

    async def retry(self) -> None:
        if self._closed:
            return
        task = self._cleanup_task
        if task is None:
            task = asyncio.create_task(self._run_cleanup())
            self._cleanup_task = task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # The generation owns the cleanup task.  A caller may stop
            # waiting, but shutdown/security quiesce can still join it.
            raise
        except BaseException:
            if self._cleanup_task is task:
                self._cleanup_task = None
            raise

    async def _run_cleanup(self) -> None:
        await _abort_prepare_leases(self.product_lease, self.source_lease)
        self.product_lease = None
        self.source_lease = None
        self._closed = True
        self._gate._unregister_pending_cleanup(self)


@dataclass(slots=True, eq=False)
class ContinuityPluginMutationPendingCleanup:
    """Generation-owned view over a failed mutation preparation cleanup."""

    _inner: ContinuityMutationPendingCleanup = field(repr=False)
    _gate: ContinuityPluginGenerationGate = field(repr=False)
    _cleanup_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _closed: bool = False

    async def retry(self) -> None:
        if self._closed:
            return
        task = self._cleanup_task
        if task is None:
            task = asyncio.create_task(self._run_cleanup())
            self._cleanup_task = task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except BaseException:
            if self._cleanup_task is task:
                self._cleanup_task = None
            raise

    async def _run_cleanup(self) -> None:
        await self._inner.retry()
        self._closed = True
        self._gate._unregister_pending_cleanup(self)


class _GenerationCall:
    def __init__(self, gate: ContinuityPluginGenerationGate) -> None:
        self._gate = gate
        self._completed = False

    def complete(self) -> None:
        if self._completed:
            return
        self._completed = True
        self._gate._complete_call()


class ContinuityPluginGenerationGate:
    """One synchronous-admit gate shared by a sealed owner generation."""

    def __init__(self) -> None:
        self._closing = False
        self._security_closing = False
        self._in_flight = 0
        self._drained = asyncio.Event()
        self._drained.set()
        self._leases: set[_GenerationLease] = set()
        self._pending_cleanups: set[_GenerationPendingCleanup] = set()

    @property
    def closing(self) -> bool:
        return self._closing

    @property
    def security_closing(self) -> bool:
        return self._security_closing

    def admit(self) -> _GenerationCall:
        """Linearize one Provider call before its first await."""

        if self._closing:
            raise ContinuityPluginGenerationClosingError(
                "Continuity Plugin generation is closing."
            )
        self._in_flight += 1
        self._drained.clear()
        return _GenerationCall(self)

    def begin_close(self, *, security: bool) -> None:
        """Poison the generation synchronously before any shutdown await."""

        if not isinstance(security, bool):
            raise TypeError("Continuity generation close mode must be a bool")
        self._closing = True
        self._security_closing = self._security_closing or security

    async def quiesce(self, *, timeout: float | None) -> None:
        """Abort unpublished leases and join calls admitted before close."""

        if not self._closing:
            raise RuntimeError("Continuity generation must close before quiesce")

        async def settle() -> None:
            while True:
                failures: list[BaseException] = []
                for lease in tuple(self._leases):
                    try:
                        await lease.abort()
                    except Exception as exc:
                        failures.append(exc)
                for pending in tuple(self._pending_cleanups):
                    try:
                        await pending.retry()
                    except Exception as exc:
                        failures.append(exc)
                await self._drained.wait()
                if failures:
                    error = RuntimeError(
                        "Continuity Plugin generation lease cleanup failed."
                    )
                    for failure in failures:
                        error.add_note(type(failure).__name__)
                    raise error
                # A prepare admitted before close can add its failed reverse
                # cleanup after the first inventory snapshot.  Re-check only
                # after all admitted calls have drained.
                if not self._leases and not self._pending_cleanups:
                    return

        try:
            if timeout is None:
                await settle()
            else:
                if timeout <= 0:
                    raise ValueError("Continuity quiesce timeout must be positive")
                async with asyncio.timeout(timeout):
                    await settle()
        except TimeoutError as exc:
            raise ContinuityPluginGenerationQuiesceError(
                "Continuity Plugin generation did not quiesce."
            ) from exc

    def _complete_call(self) -> None:
        if self._in_flight < 1:
            raise RuntimeError("Continuity generation call accounting is corrupt")
        self._in_flight -= 1
        if self._in_flight == 0:
            self._drained.set()

    def _register_lease(self, lease: _GenerationLease) -> bool:
        if self._closing:
            return False
        self._leases.add(lease)
        return True

    def _unregister_lease(self, lease: _GenerationLease) -> None:
        self._leases.discard(lease)

    def _retain_closing_lease(self, lease: _GenerationLease) -> None:
        """Keep a close-race lease in the shutdown inventory until settled."""

        self._leases.add(lease)

    def _register_pending_cleanup(
        self,
        cleanup: _GenerationPendingCleanup,
    ) -> None:
        # The corresponding call was admitted before close, so even a late
        # failed cleanup belongs to this generation's quiesce inventory.
        self._pending_cleanups.add(cleanup)

    def _unregister_pending_cleanup(
        self,
        cleanup: _GenerationPendingCleanup,
    ) -> None:
        self._pending_cleanups.discard(cleanup)


class PluginContinuityProvider:
    """Read-only import Provider adapted to Product activation authority."""

    def __init__(
        self,
        provider: ContinuityImportProvider,
        *,
        bridge: ContinuityActivationBridge,
        provenance: PluginContinuityProviderProvenance,
        gate: ContinuityPluginGenerationGate,
        deletion_authority: ContinuityDeletionAuthority | None = None,
    ) -> None:
        if not isinstance(provider, ContinuityImportProvider):
            raise TypeError("Continuity Plugin payload contains an invalid Provider")
        if not callable(getattr(bridge, "prepare", None)):
            raise TypeError("Continuity Plugin Provider requires a Product bridge")
        if not isinstance(gate, ContinuityPluginGenerationGate):
            raise TypeError("Continuity Plugin Provider requires its generation gate")
        descriptor = provider.descriptor
        if not isinstance(descriptor, ContinuityProviderDescriptor):
            raise TypeError("Continuity Plugin Provider descriptor is invalid")
        if descriptor.supported_actions != provenance.supported_actions:
            raise ValueError(
                "Continuity Plugin Provider actions exceed its admitted declaration"
            )
        if descriptor.supported_actions not in {
            ("activate",),
            ("activate", "delete"),
        }:
            raise ValueError("Continuity Plugin Provider exposes unsupported actions")
        if "delete" in descriptor.supported_actions:
            if deletion_authority is None or not isinstance(
                deletion_authority,
                ContinuityDeletionAuthority,
            ):
                raise TypeError(
                    "Continuity Plugin mutation requires a Product authority"
                )
            try:
                inspect.getattr_static(provider, "prepare_delete")
            except AttributeError as exc:
                raise TypeError(
                    "Continuity Plugin delete Provider lacks prepare_delete"
                ) from exc
        self._provider = provider
        self._bridge = bridge
        self._deletion_authority = deletion_authority
        self._provenance = provenance
        self._gate = gate
        self._descriptor = replace(
            descriptor,
            supported_actions=descriptor.supported_actions,
        )
        self._source = plugin_continuity_provider_source(
            provider_id=descriptor.provider_id,
            implementation_version=descriptor.implementation_version,
            provenance=provenance,
        )

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return self._descriptor

    async def query(self, request: ProviderQuery) -> ProviderPage:
        call = self._gate.admit()
        try:
            page = await self._provider.query(request)
            if not isinstance(page, ProviderPage):
                raise TypeError("Continuity Plugin Provider returned an invalid page")
            if page.diagnostics:
                page = replace(
                    page,
                    diagnostics=tuple(
                        ContinuityDiagnostic(
                            code="continuity_plugin_provider_reported",
                            message=(
                                "Continuity Plugin Provider reported a diagnostic."
                            ),
                            provider_id=self._descriptor.provider_id,
                        )
                        for _diagnostic in page.diagnostics
                    ),
                )
            return page
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ContinuityPluginProviderCallError("query") from None
        finally:
            call.complete()

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        self._validate_target(target)
        call = self._gate.admit()
        try:
            preview = await self._provider.preview(target)
            if not isinstance(preview, ContinuityPreview):
                raise TypeError(
                    "Continuity Plugin Provider returned an invalid preview"
                )
            if preview.target != target:
                raise ValueError(
                    "Continuity Plugin Provider preview targets another item"
                )
            return preview
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ContinuityPluginProviderCallError("preview") from None
        finally:
            call.complete()

    async def prepare(
        self,
        target: ContinuityTarget,
    ) -> PreparedActivationLease:
        self._validate_target(target)
        call = self._gate.admit()
        source_lease: PreparedContinuityImport | None = None
        product_lease: PreparedActivationLease | None = None
        try:
            raw_source_lease = await self._provider.prepare_import(target)
            if not isinstance(raw_source_lease, PreparedContinuityImport):
                raise TypeError(
                    "Continuity Plugin Provider returned an invalid import lease"
                )
            source_lease = raw_source_lease
            if source_lease.target != target:
                raise ValueError("Continuity Plugin import lease targets another item")
            payload = source_lease.payload
            if not isinstance(payload, ContinuityActivationPayload):
                raise TypeError(
                    "Continuity Plugin import lease returned an invalid payload"
                )
            raw_product_lease = await self._bridge.prepare(
                target,
                payload,
                self._source,
            )
            if not isinstance(raw_product_lease, PreparedActivationLease):
                raise TypeError(
                    "Product continuity bridge returned an invalid activation lease"
                )
            product_lease = raw_product_lease
            if product_lease.target != target:
                raise ValueError("Product continuity bridge prepared another target")
            await source_lease.close()
            source_lease = None
            lease = _GenerationActivationLease(product_lease, self._gate)
            if not self._gate._register_lease(lease):
                closing = ContinuityPluginGenerationClosingError(
                    "Continuity Plugin generation closed during activation prepare."
                )
                try:
                    await lease.abort()
                except BaseException as abort_error:
                    closing.add_note(
                        "Continuity Plugin close-race cleanup failed: "
                        f"{type(abort_error).__name__}"
                    )
                    raise closing from None
                raise closing
            product_lease = None
            return lease
        except BaseException as error:
            cleanup = asyncio.create_task(
                _abort_prepare_leases(product_lease, source_lease)
            )
            cleanup_error: BaseException | None = None
            try:
                await _await_cancellation_atomic(cleanup)
            except BaseException as caught_cleanup_error:
                cleanup_error = caught_cleanup_error
                error.add_note(
                    "Continuity Plugin prepare cleanup failed: "
                    f"{type(caught_cleanup_error).__name__}"
                )
            if cleanup_error is None and isinstance(
                error,
                (asyncio.CancelledError, ContinuityPluginGenerationClosingError),
            ):
                raise
            failure = ContinuityPluginProviderCallError("prepare")
            if cleanup_error is not None:
                pending = ContinuityPluginPreparePendingCleanup(
                    product_lease=product_lease,
                    source_lease=source_lease,
                    _gate=self._gate,
                )
                self._gate._register_pending_cleanup(pending)
                failure.pending_cleanup = pending
            raise failure from None
        finally:
            call.complete()

    async def delete(self, target: ContinuityTarget) -> bool:
        """Execute one Product-authorized exact deletion after UI confirmation."""

        lease = await self._prepare_delete(target)
        try:
            receipt = await lease.consume()
        except asyncio.CancelledError:
            raise
        except ContinuityPluginGenerationClosingError:
            # Shutdown owns the still-registered accepted lease and will
            # cancel or finish it while quiescing this exact generation.
            raise
        except Exception:
            failure = ContinuityPluginProviderCallError("delete")
            failure.pending_mutation = (
                ContinuityPluginMutationPendingSettlement._create(lease)
            )
            raise failure from None
        return receipt.disposition == "applied"

    async def _prepare_delete(
        self,
        target: ContinuityTarget,
        *,
        recovery_source: object | None = None,
        expected_plan: ContinuityDeletionPlanV1 | None = None,
    ) -> _GenerationDeletionLease:
        self._validate_target(target)
        if "delete" not in self._descriptor.supported_actions:
            raise RuntimeError("Continuity Plugin Provider does not support deletion")
        authority = self._deletion_authority
        if authority is None:
            raise RuntimeError("Continuity Plugin deletion authority is unavailable")
        source = self._source
        if recovery_source is not None:
            if not _recovery_source_matches(source, recovery_source):
                raise ContinuityPluginMutationRecoveryError(
                    "Continuity deletion recovery source does not match generation."
                )
            assert type(recovery_source) is ContinuityProviderSourceDescriptor
            source = recovery_source
        call = self._gate.admit()
        try:
            prepare_delete = getattr(self._provider, "prepare_delete")
            candidate = await prepare_delete(target)
            if expected_plan is not None:
                try:
                    candidate_plan = candidate.plan
                    candidate_target = candidate.target
                except BaseException:
                    candidate_plan = None
                    candidate_target = None
                if (
                    type(candidate_plan) is not ContinuityDeletionPlanV1
                    or type(candidate_target) is not ContinuityTarget
                    or candidate_target != candidate_plan.target
                    or candidate_plan != expected_plan
                ):
                    pending = ContinuityMutationPendingCleanup._create(
                        candidate=candidate,
                        authority=authority,
                        authorization=None,
                    )
                    await _await_cancellation_atomic(
                        asyncio.create_task(pending.retry())
                    )
                    raise ContinuityPluginMutationRecoveryError(
                        "Continuity deletion recovery candidate changed its plan."
                    )
            inner = await prepare_authorized_continuity_deletion(
                candidate,
                source=source,
                authority=authority,
            )
            lease = _GenerationDeletionLease(inner, self._gate)
            if not self._gate._register_lease(lease):
                self._gate._retain_closing_lease(lease)
                closing = ContinuityPluginGenerationClosingError(
                    "Continuity Plugin generation closed during deletion prepare."
                )
                try:
                    await lease.abort()
                except BaseException as abort_error:
                    closing.add_note(
                        "Continuity Plugin deletion close-race cleanup failed: "
                        f"{type(abort_error).__name__}"
                    )
                raise closing
            return lease
        except BaseException as error:
            if isinstance(error, ContinuityMutationLifecycleError):
                raw_cleanup = error.pending_cleanup
                if raw_cleanup is not None:
                    wrapped = ContinuityPluginMutationPendingCleanup(
                        _inner=raw_cleanup,
                        _gate=self._gate,
                    )
                    self._gate._register_pending_cleanup(wrapped)
                    failure = ContinuityPluginProviderCallError("delete_prepare")
                    failure.pending_cleanup = wrapped
                    raise failure from None
            if isinstance(
                error,
                (
                    asyncio.CancelledError,
                    ContinuityPluginGenerationClosingError,
                    ContinuityPluginMutationRecoveryError,
                ),
            ):
                raise
            raise ContinuityPluginProviderCallError("delete_prepare") from None
        finally:
            call.complete()

    def _validate_target(self, target: ContinuityTarget) -> None:
        if not isinstance(target, ContinuityTarget):
            raise TypeError("Continuity Plugin target is invalid")
        if target.provider_id != self._descriptor.provider_id:
            raise ValueError("Continuity Plugin target belongs to another Provider")


class _GenerationActivationLease:
    """Keep consume under generation authority after copy-first prepare."""

    def __init__(
        self,
        inner: PreparedActivationLease,
        gate: ContinuityPluginGenerationGate,
    ) -> None:
        self._inner = inner
        self._gate = gate
        self._consuming = False
        self._consume_done = asyncio.Event()
        self._consume_done.set()
        self._consumed = False
        self._consume_attempted = False
        self._abort_requested = False
        self._closed = False
        self._abort_task: asyncio.Task[None] | None = None

    @property
    def target(self) -> ContinuityTarget:
        return self._inner.target

    @property
    def disposition(self) -> ActivationDisposition:
        return self._inner.disposition

    @property
    def consumed(self) -> bool:
        return self._inner.consumed

    async def consume(self) -> object:
        if self._closed or self._abort_requested:
            raise ActivationLeaseStateError("activation lease is closed")
        if self._consume_attempted or self._consuming:
            raise ActivationLeaseStateError(
                "activation lease has already been consumed"
            )
        call = self._gate.admit()
        # Linearize consume before the first await.  Failed consume remains in
        # the gate inventory so the Product candidate can still be aborted.
        self._consuming = True
        self._consume_attempted = True
        self._consume_done.clear()
        try:
            result = await self._inner.consume()
            self._consumed = True
            self._closed = True
            self._gate._unregister_lease(self)
            return result
        finally:
            self._consuming = False
            self._consume_done.set()
            call.complete()

    async def abort(self) -> None:
        if self._closed:
            return
        self._abort_requested = True
        if self._consuming:
            await asyncio.shield(self._consume_done.wait())
        if self._closed:
            return
        if self._consumed:
            self._closed = True
            self._gate._unregister_lease(self)
            return
        task = self._abort_task
        if task is None:
            task = asyncio.create_task(self._run_abort())
            self._abort_task = task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except BaseException:
            if self._abort_task is task:
                self._abort_task = None
            raise

    async def _run_abort(self) -> None:
        await self._inner.abort()
        self._closed = True
        self._gate._unregister_lease(self)

    async def close(self) -> None:
        await self.abort()


class _GenerationDeletionLease:
    """Keep an authorized mutation pinned to its exact owner generation."""

    def __init__(
        self,
        inner: AuthorizedContinuityDeletionLease,
        gate: ContinuityPluginGenerationGate,
    ) -> None:
        self._inner = inner
        self._gate = gate

    @property
    def target(self) -> ContinuityTarget:
        return self._inner.target

    @property
    def plan(self) -> ContinuityDeletionPlanV1:
        return self._inner.plan

    async def consume(self) -> ContinuityDeletionReceiptV1:
        call = self._gate.admit()
        try:
            return await self._inner.consume()
        finally:
            if self._inner.closed:
                self._gate._unregister_lease(self)
            call.complete()

    async def abort(self) -> None:
        try:
            await self._inner.abort()
        finally:
            if self._inner.closed:
                self._gate._unregister_lease(self)

    async def close(self) -> None:
        await self.abort()


class ContinuityPluginMutationPendingSettlement:
    """Narrow caller retry handle for a generation-owned mutation lease."""

    _lease: _GenerationDeletionLease

    def __init__(self) -> None:
        raise TypeError("Continuity Plugin mutation retry is owner-constructed")

    @classmethod
    def _create(
        cls,
        lease: _GenerationDeletionLease,
    ) -> ContinuityPluginMutationPendingSettlement:
        pending = object.__new__(cls)
        pending._lease = lease
        return pending

    async def retry(self) -> bool:
        receipt = await self._lease.consume()
        return receipt.disposition == "applied"


async def recover_continuity_plugin_deletions(
    providers: tuple[PluginContinuityProvider, ...],
    *,
    authority: ContinuityDeletionRecoveryAuthority,
) -> None:
    """Settle durable accepted operations before publishing their generation."""

    if not isinstance(authority, ContinuityDeletionRecoveryAuthority):
        raise TypeError("Continuity Plugin recovery requires a recovery authority")
    current_providers: list[PluginContinuityProvider] = []
    for provider in providers:
        if not isinstance(provider, PluginContinuityProvider):
            raise TypeError("Continuity Plugin recovery contains an invalid Provider")
        current_providers.append(provider)
    try:
        pending = await authority.pending_deletions()
        _validate_pending_deletions(pending)
        for operation in pending:
            matches = tuple(
                provider
                for provider in current_providers
                if _recovery_source_matches(provider._source, operation.source)
            )
            if (
                len(matches) != 1
                or "delete" not in matches[0].descriptor.supported_actions
            ):
                raise ContinuityPluginMutationRecoveryError(
                    "Accepted Continuity deletion has no exact live generation owner."
                )
            lease = await matches[0]._prepare_delete(
                operation.plan.target,
                recovery_source=operation.source,
                expected_plan=operation.plan,
            )
            await lease.consume()
        remaining = await authority.pending_deletions()
        _validate_pending_deletions(remaining)
        if remaining:
            raise ContinuityPluginMutationRecoveryError(
                "Continuity deletion recovery did not reach a fixed point."
            )
    except ContinuityPluginMutationRecoveryError:
        raise
    except asyncio.CancelledError:
        raise
    except BaseException:
        raise ContinuityPluginMutationRecoveryError(
            "Continuity Plugin mutation recovery failed."
        ) from None


def _validate_pending_deletions(
    pending: tuple[AcceptedContinuityDeletion, ...],
) -> None:
    if type(pending) is not tuple or any(
        type(item) is not AcceptedContinuityDeletion for item in pending
    ):
        raise ContinuityPluginMutationRecoveryError(
            "Continuity deletion recovery returned invalid operations."
        )
    identities = tuple((item.plan.fingerprint, item.source) for item in pending)
    if len(identities) != len(set(identities)):
        raise ContinuityPluginMutationRecoveryError(
            "Continuity deletion recovery repeated an operation."
        )


def _recovery_source_matches(current: object, accepted: object) -> bool:
    if (
        type(current) is not ContinuityProviderSourceDescriptor
        or type(accepted) is not ContinuityProviderSourceDescriptor
        or current.source != "plugin"
        or accepted.source != "plugin"
    ):
        return False
    if accepted.owner_recovery_fingerprint is None:
        # A Phase 5E record has no process-stable semantic identity. Preserve
        # its original fail-closed rule: only the exact attempt binding may
        # recover it (source_id is the generation-local projection).
        return (
            replace(
                current,
                source_id=accepted.source_id,
                owner_recovery_fingerprint=None,
            )
            == accepted
        )
    if current.owner_recovery_fingerprint is None:
        return False
    return (
        current.owner_recovery_fingerprint == accepted.owner_recovery_fingerprint
        and replace(
            current,
            source_id=accepted.source_id,
            owner_binding_fingerprint=accepted.owner_binding_fingerprint,
        )
        == accepted
    )


async def _abort_prepare_leases(
    product_lease: PreparedActivationLease | None,
    source_lease: PreparedContinuityImport | None,
) -> None:
    failures: list[BaseException] = []
    for pending in (product_lease, source_lease):
        if pending is None:
            continue
        try:
            await pending.abort()
        except BaseException as exc:
            failures.append(exc)
    if failures:
        error = RuntimeError("Continuity Plugin prepare cleanup failed.")
        for failure in failures:
            error.add_note(type(failure).__name__)
        raise error


__all__ = [
    "ContinuityPluginGenerationClosingError",
    "ContinuityPluginGenerationGate",
    "ContinuityPluginGenerationQuiesceError",
    "ContinuityPluginProviderCallError",
    "ContinuityPluginMutationPendingCleanup",
    "ContinuityPluginMutationPendingSettlement",
    "ContinuityPluginMutationRecoveryError",
    "ContinuityPluginPreparePendingCleanup",
    "PluginContinuityProvider",
    "recover_continuity_plugin_deletions",
]
