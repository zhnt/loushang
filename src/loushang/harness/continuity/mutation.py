"""Product-authorized lifecycle for portable Continuity deletion proposals."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeVar, runtime_checkable

from loushang.foundation.json import JsonValueError, require_json_mapping
from loushang.harness.continuity.types import (
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
)

ContinuityDeletionDisposition = Literal["applied", "not_found"]

MAX_CONTINUITY_MUTATION_IDENTITY_LENGTH = 512

_TaskResult = TypeVar("_TaskResult")


class ContinuityMutationLifecycleError(RuntimeError):
    """Fail-closed mutation failure carrying one stable diagnostic code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
        self.pending_cleanup: ContinuityMutationPendingCleanup | None = None


class ContinuityMutationCodecError(ValueError):
    """Strict portable mutation-record decoding failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ContinuityDeletionPlanV1:
    """A bounded proposal to delete one exact Provider-owned revision."""

    target: ContinuityTarget
    plan_version: int = 1

    def __post_init__(self) -> None:
        _validate_exact_target(self.target, record="plan")
        if type(self.plan_version) is not int or self.plan_version != 1:
            raise ValueError("Unsupported Continuity deletion plan version")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            "loushang.continuity-deletion-plan/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "mutationKind": "delete",
            "planVersion": self.plan_version,
            "target": _target_dict(self.target),
        }

    @classmethod
    def from_dict(cls, value: object) -> ContinuityDeletionPlanV1:
        document = _wire_mapping(value, name="Continuity deletion plan")
        _wire_exact_fields(
            document,
            fields={"mutationKind", "planVersion", "target"},
            name="Continuity deletion plan",
        )
        if document["mutationKind"] != "delete":
            raise _codec_error(
                "Continuity deletion plan mutation kind is unsupported",
                code="continuity_mutation_record_kind_unsupported",
            )
        _wire_version(document["planVersion"], name="plan", expected=1)
        try:
            return cls(target=_wire_target(document["target"]))
        except ContinuityMutationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _codec_error(
                str(exc),
                code="continuity_mutation_record_invalid",
            ) from exc


@dataclass(frozen=True, slots=True)
class ContinuityDeletionReceiptV1:
    """Source result bound to the exact accepted deletion plan."""

    target: ContinuityTarget
    plan_fingerprint: str
    disposition: ContinuityDeletionDisposition
    receipt_version: int = 1

    def __post_init__(self) -> None:
        _validate_exact_target(self.target, record="receipt")
        _require_sha256(self.plan_fingerprint, name="deletion plan fingerprint")
        if type(self.disposition) is not str or self.disposition not in {
            "applied",
            "not_found",
        }:
            raise ValueError("Unsupported Continuity deletion disposition")
        if type(self.receipt_version) is not int or self.receipt_version != 1:
            raise ValueError("Unsupported Continuity deletion receipt version")

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "planFingerprint": self.plan_fingerprint,
            "receiptVersion": self.receipt_version,
            "target": _target_dict(self.target),
        }

    @classmethod
    def from_dict(cls, value: object) -> ContinuityDeletionReceiptV1:
        document = _wire_mapping(value, name="Continuity deletion receipt")
        _wire_exact_fields(
            document,
            fields={
                "disposition",
                "planFingerprint",
                "receiptVersion",
                "target",
            },
            name="Continuity deletion receipt",
        )
        _wire_version(document["receiptVersion"], name="receipt", expected=1)
        raw_disposition = document["disposition"]
        if raw_disposition == "applied":
            disposition: ContinuityDeletionDisposition = "applied"
        elif raw_disposition == "not_found":
            disposition = "not_found"
        else:
            raise _codec_error(
                "Continuity deletion receipt disposition is unsupported",
                code="continuity_mutation_record_disposition_unsupported",
            )
        try:
            return cls(
                target=_wire_target(document["target"]),
                plan_fingerprint=_wire_string(
                    document["planFingerprint"],
                    name="plan fingerprint",
                ),
                disposition=disposition,
            )
        except ContinuityMutationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _codec_error(
                str(exc),
                code="continuity_mutation_record_invalid",
            ) from exc


class PreparedContinuityDeletion(Protocol):
    """Source-owned, idempotent, unpublished deletion candidate."""

    @property
    def target(self) -> ContinuityTarget: ...

    @property
    def plan(self) -> ContinuityDeletionPlanV1: ...

    async def commit(
        self,
        plan: ContinuityDeletionPlanV1,
    ) -> ContinuityDeletionReceiptV1: ...

    async def abort(self) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class ContinuityDeletionAuthority(Protocol):
    """Product authority for durable authorization and result settlement."""

    async def authorize_delete(
        self,
        plan: ContinuityDeletionPlanV1,
        source: ContinuityProviderSourceDescriptor,
    ) -> ContinuityDeletionAuthorization: ...

    async def complete_delete(
        self,
        authorization: ContinuityDeletionAuthorization,
        receipt: ContinuityDeletionReceiptV1,
    ) -> None: ...

    async def cancel_delete(
        self,
        authorization: ContinuityDeletionAuthorization,
    ) -> None: ...


@dataclass(frozen=True, slots=True, init=False)
class ContinuityDeletionAuthorization:
    """Opaque exact-plan evidence issued by one Product authority."""

    authorization_id: str
    plan_fingerprint: str
    source_fingerprint: str
    _authority: object = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("Continuity deletion authorization is authority-issued")

    @classmethod
    def _issue(
        cls,
        authority: ContinuityDeletionAuthority,
        *,
        authorization_id: str,
        plan: ContinuityDeletionPlanV1,
        source: ContinuityProviderSourceDescriptor,
    ) -> ContinuityDeletionAuthorization:
        if not isinstance(authority, ContinuityDeletionAuthority):
            raise TypeError("Continuity deletion authorization requires its authority")
        _require_sha256(authorization_id, name="deletion authorization id")
        if type(plan) is not ContinuityDeletionPlanV1:
            raise TypeError("Continuity deletion authorization requires its plan")
        if type(source) is not ContinuityProviderSourceDescriptor:
            raise TypeError("Continuity deletion authorization requires its source")
        evidence = object.__new__(cls)
        object.__setattr__(evidence, "authorization_id", authorization_id)
        object.__setattr__(evidence, "plan_fingerprint", plan.fingerprint)
        object.__setattr__(
            evidence,
            "source_fingerprint",
            _source_fingerprint(source),
        )
        object.__setattr__(evidence, "_authority", authority)
        return evidence


@dataclass(slots=True, init=False, eq=False)
class ContinuityMutationPendingCleanup:
    """Opaque retry handle retained when authorization cleanup cannot settle."""

    _candidate: PreparedContinuityDeletion = field(repr=False)
    _authority: ContinuityDeletionAuthority = field(repr=False)
    _authorization: ContinuityDeletionAuthorization | None = field(
        default=None,
        repr=False,
    )
    _cleanup_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _cancelled: bool = False
    _aborted: bool = False
    _released: bool = False
    _completed: bool = False

    def __init__(self) -> None:
        raise TypeError("Continuity mutation cleanup is owner-constructed")

    @classmethod
    def _create(
        cls,
        *,
        candidate: PreparedContinuityDeletion,
        authority: ContinuityDeletionAuthority,
        authorization: ContinuityDeletionAuthorization | None,
    ) -> ContinuityMutationPendingCleanup:
        cleanup = object.__new__(cls)
        cleanup._candidate = candidate
        cleanup._authority = authority
        cleanup._authorization = authorization
        cleanup._cleanup_task = None
        cleanup._cancelled = False
        cleanup._aborted = False
        cleanup._released = False
        cleanup._completed = False
        return cleanup

    async def retry(self) -> None:
        if self._completed:
            return
        task = self._cleanup_task
        if task is None:
            task = asyncio.create_task(self._run())
            self._cleanup_task = task
        try:
            _result, cancellation = await _join_owned_task(task)
        except BaseException:
            if self._cleanup_task is task and not self._completed:
                self._cleanup_task = None
            raise
        if cancellation is not None:
            raise cancellation

    async def _run(self) -> None:
        if self._authorization is not None and not self._cancelled:
            try:
                await self._authority.cancel_delete(self._authorization)
            except BaseException:
                raise _lifecycle_error(
                    "Continuity mutation Product cancellation remains retryable.",
                    code="continuity_mutation_cleanup_retryable",
                    pending_cleanup=self,
                ) from None
            self._cancelled = True
        if not self._aborted:
            try:
                await self._candidate.abort()
            except BaseException:
                raise _lifecycle_error(
                    "Continuity mutation source abort remains retryable.",
                    code="continuity_mutation_cleanup_retryable",
                    pending_cleanup=self,
                ) from None
            self._aborted = True
        if not self._released:
            try:
                await self._candidate.close()
            except BaseException:
                raise _lifecycle_error(
                    "Continuity mutation source release remains retryable.",
                    code="continuity_mutation_cleanup_retryable",
                    pending_cleanup=self,
                ) from None
            self._released = True
        self._completed = True


class AuthorizedContinuityDeletionLease:
    """One Product-authorized, retryable deletion transaction."""

    _candidate: PreparedContinuityDeletion
    _plan: ContinuityDeletionPlanV1
    _target: ContinuityTarget
    _source: ContinuityProviderSourceDescriptor
    _authority: ContinuityDeletionAuthority
    _authorization: ContinuityDeletionAuthorization
    _receipt: ContinuityDeletionReceiptV1 | None
    _commit_task: asyncio.Task[ContinuityDeletionReceiptV1] | None
    _abort_task: asyncio.Task[None] | None
    _commit_started: bool
    _abort_requested: bool
    _settled: bool
    _cancelled: bool
    _source_aborted: bool
    _released: bool
    _closed: bool

    def __init__(self) -> None:
        raise TypeError("Continuity deletion lease is owner-constructed")

    @classmethod
    def _create(
        cls,
        *,
        candidate: PreparedContinuityDeletion,
        plan: ContinuityDeletionPlanV1,
        target: ContinuityTarget,
        source: ContinuityProviderSourceDescriptor,
        authority: ContinuityDeletionAuthority,
        authorization: ContinuityDeletionAuthorization,
    ) -> AuthorizedContinuityDeletionLease:
        _validate_candidate_snapshot(candidate, plan=plan, target=target)
        if target.provider_id != source.provider_id:
            raise ContinuityMutationLifecycleError(
                "Continuity deletion source does not own the target.",
                code="continuity_mutation_source_mismatch",
            )
        _validate_authorization(
            authorization,
            authority=authority,
            plan=plan,
            source=source,
        )
        lease = object.__new__(cls)
        lease._candidate = candidate
        lease._plan = plan
        lease._target = target
        lease._source = source
        lease._authority = authority
        lease._authorization = authorization
        lease._receipt = None
        lease._commit_task = None
        lease._abort_task = None
        lease._commit_started = False
        lease._abort_requested = False
        lease._settled = False
        lease._cancelled = False
        lease._source_aborted = False
        lease._released = False
        lease._closed = False
        return lease

    @property
    def target(self) -> ContinuityTarget:
        return self._target

    @property
    def plan(self) -> ContinuityDeletionPlanV1:
        return self._plan

    @property
    def source(self) -> ContinuityProviderSourceDescriptor:
        return self._source

    @property
    def authorization_id(self) -> str:
        return self._authorization.authorization_id

    @property
    def consumed(self) -> bool:
        return self._settled

    async def consume(self) -> ContinuityDeletionReceiptV1:
        if self._closed and self._settled:
            assert self._receipt is not None
            return self._receipt
        if self._closed or self._abort_requested:
            raise ContinuityMutationLifecycleError(
                "Continuity deletion lease is closed.",
                code="continuity_mutation_lease_closed",
            )
        if not self._commit_started:
            _validate_candidate_snapshot(
                self._candidate,
                plan=self._plan,
                target=self._target,
            )
            # Intent never rolls back: after this assignment abort/close may
            # only drive the idempotent commit transaction to settlement.
            self._commit_started = True
        task = self._start_commit_task()
        try:
            receipt, cancellation = await _join_owned_task(task)
        except BaseException:
            if self._commit_task is task and not self._closed:
                self._commit_task = None
            raise
        if cancellation is not None:
            raise cancellation
        return receipt

    def _start_commit_task(self) -> asyncio.Task[ContinuityDeletionReceiptV1]:
        task = self._commit_task
        if task is None:
            task = asyncio.create_task(self._commit_complete_and_release())
            self._commit_task = task
        return task

    async def _commit_complete_and_release(self) -> ContinuityDeletionReceiptV1:
        receipt = self._receipt
        if receipt is None:
            try:
                receipt = await self._candidate.commit(self._plan)
            except BaseException:
                raise _lifecycle_error(
                    "Continuity mutation source commit remains retryable.",
                    code="continuity_mutation_source_commit_retryable",
                ) from None
            _validate_receipt(receipt, plan=self._plan, target=self._target)
            self._receipt = receipt
        if not self._settled:
            try:
                await self._authority.complete_delete(self._authorization, receipt)
            except BaseException:
                raise _lifecycle_error(
                    "Continuity mutation Product completion remains retryable.",
                    code="continuity_mutation_completion_retryable",
                ) from None
            self._settled = True
        await self._release_candidate()
        self._closed = True
        return receipt

    async def abort(self) -> None:
        if self._closed:
            return
        # Abort intent is recorded before the first await.  It permanently
        # prevents a future commit from starting.
        self._abort_requested = True
        task = self._commit_task
        if task is not None:
            try:
                _receipt, cancellation = await _join_owned_task(task)
            except BaseException:
                if self._commit_task is task and not self._closed:
                    self._commit_task = None
                # Settlement failure outranks caller cancellation and remains
                # retryable through a subsequent abort/close call.
                raise
            else:
                if cancellation is not None:
                    raise cancellation
                return
        if self._commit_started:
            await self._finish_started_commit()
            return
        cleanup = self._abort_task
        if cleanup is None:
            cleanup = asyncio.create_task(self._cancel_abort_and_release())
            self._abort_task = cleanup
        try:
            _result, cancellation = await _join_owned_task(cleanup)
        except BaseException:
            if self._abort_task is cleanup:
                self._abort_task = None
            raise
        if cancellation is not None:
            raise cancellation

    async def _finish_started_commit(self) -> None:
        task = self._start_commit_task()
        try:
            _receipt, cancellation = await _join_owned_task(task)
        except BaseException:
            if self._commit_task is task and not self._closed:
                self._commit_task = None
            raise
        if cancellation is not None:
            raise cancellation

    async def _cancel_abort_and_release(self) -> None:
        if not self._cancelled:
            try:
                await self._authority.cancel_delete(self._authorization)
            except BaseException:
                raise _lifecycle_error(
                    "Continuity mutation Product cancellation remains retryable.",
                    code="continuity_mutation_cleanup_retryable",
                ) from None
            self._cancelled = True
        if not self._source_aborted:
            try:
                await self._candidate.abort()
            except BaseException:
                raise _lifecycle_error(
                    "Continuity mutation source abort remains retryable.",
                    code="continuity_mutation_cleanup_retryable",
                ) from None
            self._source_aborted = True
        await self._release_candidate()
        self._closed = True

    async def _release_candidate(self) -> None:
        if self._released:
            return
        try:
            await self._candidate.close()
        except BaseException:
            raise _lifecycle_error(
                "Continuity mutation source release remains retryable.",
                code="continuity_mutation_release_retryable",
            ) from None
        self._released = True

    async def close(self) -> None:
        await self.abort()

    async def __aenter__(self) -> AuthorizedContinuityDeletionLease:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()


async def prepare_authorized_continuity_deletion(
    candidate: PreparedContinuityDeletion,
    *,
    source: ContinuityProviderSourceDescriptor,
    authority: ContinuityDeletionAuthority,
) -> AuthorizedContinuityDeletionLease:
    """Authorize one exact source candidate before exposing a mutation lease."""

    if not _has_static_candidate_contract(candidate):
        raise TypeError("Continuity deletion requires a prepared source candidate")
    if type(source) is not ContinuityProviderSourceDescriptor:
        raise TypeError("Continuity deletion requires typed source provenance")
    if not isinstance(authority, ContinuityDeletionAuthority):
        raise TypeError("Continuity deletion requires a Product authority")

    authorization: ContinuityDeletionAuthorization | None = None
    try:
        plan, target = _candidate_snapshot(candidate)
        if target.provider_id != source.provider_id:
            raise ContinuityMutationLifecycleError(
                "Continuity deletion source does not own the target.",
                code="continuity_mutation_source_mismatch",
            )
        task = asyncio.create_task(authority.authorize_delete(plan, source))
        issued, cancellation = await _join_owned_task(task)
        if isinstance(issued, ContinuityDeletionAuthorization):
            # The authority that returned evidence remains responsible for
            # cancelling it even when its bindings fail validation below.
            authorization = issued
        _validate_candidate_snapshot(candidate, plan=plan, target=target)
        _validate_authorization(
            issued,
            authority=authority,
            plan=plan,
            source=source,
        )
        assert isinstance(issued, ContinuityDeletionAuthorization)
        if cancellation is not None:
            raise cancellation
        return AuthorizedContinuityDeletionLease._create(
            candidate=candidate,
            plan=plan,
            target=target,
            source=source,
            authority=authority,
            authorization=issued,
        )
    except BaseException as error:
        pending = ContinuityMutationPendingCleanup._create(
            candidate=candidate,
            authority=authority,
            authorization=authorization,
        )
        cleanup = asyncio.create_task(pending.retry())
        try:
            _result, cleanup_cancellation = await _join_owned_task(cleanup)
        except BaseException as cleanup_error:
            failure = ContinuityMutationLifecycleError(
                "Continuity mutation preparation cleanup remains retryable.",
                code="continuity_mutation_preparation_cleanup_retryable",
            )
            failure.pending_cleanup = pending
            failure.add_note(
                "Mutation preparation cleanup failed: "
                f"{type(cleanup_error).__name__}"
            )
            raise failure from None
        if cleanup_cancellation is not None and isinstance(
            error,
            asyncio.CancelledError,
        ):
            raise cleanup_cancellation
        # If cleanup settled after a later cancellation, the original
        # structural failure outranks it; there is no pending work to report.
        if isinstance(error, asyncio.CancelledError):
            raise error
        if isinstance(error, ContinuityMutationLifecycleError):
            raise error
        raise _lifecycle_error(
            "Continuity mutation Product authorization failed.",
            code="continuity_mutation_authorization_failed",
        ) from None


async def consume_authorized_continuity_deletion(
    lease: AuthorizedContinuityDeletionLease,
) -> ContinuityDeletionReceiptV1:
    """Consume a Product-authorized mutation and settle only after completion."""

    if not isinstance(lease, AuthorizedContinuityDeletionLease):
        raise TypeError("Continuity deletion consume requires an authorized lease")
    return await lease.consume()


def _validate_authorization(
    authorization: object,
    *,
    authority: ContinuityDeletionAuthority,
    plan: ContinuityDeletionPlanV1,
    source: ContinuityProviderSourceDescriptor,
) -> None:
    if (
        type(authorization) is not ContinuityDeletionAuthorization
        or authorization._authority is not authority
        or authorization.plan_fingerprint != plan.fingerprint
        or authorization.source_fingerprint != _source_fingerprint(source)
    ):
        raise ContinuityMutationLifecycleError(
            "Continuity deletion authorization does not match the exact plan.",
            code="continuity_mutation_authorization_mismatch",
        )


def _validate_receipt(
    receipt: object,
    *,
    plan: ContinuityDeletionPlanV1,
    target: ContinuityTarget,
) -> None:
    if (
        type(receipt) is not ContinuityDeletionReceiptV1
        or type(receipt.target) is not ContinuityTarget
        or receipt.target != target
        or receipt.plan_fingerprint != plan.fingerprint
    ):
        raise ContinuityMutationLifecycleError(
            "Continuity deletion receipt does not match the exact plan.",
            code="continuity_mutation_receipt_mismatch",
        )


def _candidate_snapshot(
    candidate: PreparedContinuityDeletion,
) -> tuple[ContinuityDeletionPlanV1, ContinuityTarget]:
    try:
        plan = candidate.plan
        target = candidate.target
    except BaseException:
        raise _lifecycle_error(
            "Prepared Continuity deletion candidate is invalid.",
            code="continuity_mutation_candidate_mismatch",
        ) from None
    if (
        type(plan) is not ContinuityDeletionPlanV1
        or type(target) is not ContinuityTarget
        or target != plan.target
    ):
        raise ContinuityMutationLifecycleError(
            "Prepared Continuity deletion does not match its plan.",
            code="continuity_mutation_candidate_mismatch",
        )
    return plan, target


def _has_static_candidate_contract(candidate: object) -> bool:
    """Check shape without executing untrusted descriptors or properties."""

    for name in ("target", "plan", "commit", "abort", "close"):
        try:
            inspect.getattr_static(candidate, name)
        except AttributeError:
            return False
    return True


def _validate_candidate_snapshot(
    candidate: PreparedContinuityDeletion,
    *,
    plan: ContinuityDeletionPlanV1,
    target: ContinuityTarget,
) -> None:
    current_plan, current_target = _candidate_snapshot(candidate)
    if current_plan != plan or current_target != target:
        raise ContinuityMutationLifecycleError(
            "Prepared Continuity deletion changed after authorization.",
            code="continuity_mutation_candidate_mismatch",
        )


async def _join_owned_task(
    task: asyncio.Task[_TaskResult],
) -> tuple[_TaskResult, asyncio.CancelledError | None]:
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            return result, cancellation
        except asyncio.CancelledError as exc:
            cancellation = exc
            if task.done():
                return task.result(), cancellation


def _source_fingerprint(source: ContinuityProviderSourceDescriptor) -> str:
    return _fingerprint(
        "loushang.continuity-provider-source/v1",
        source.to_dict(),
    )


def _target_dict(target: ContinuityTarget) -> dict[str, object]:
    return {
        "opaqueId": target.opaque_id,
        "providerId": target.provider_id,
        "revision": target.revision,
    }


def _validate_exact_target(target: object, *, record: str) -> None:
    if type(target) is not ContinuityTarget:
        raise TypeError(f"Continuity deletion {record} requires a typed target")
    if target.revision is None:
        raise ValueError("Continuity deletion requires an exact target revision")
    for value, name in (
        (target.provider_id, "Provider id"),
        (target.opaque_id, "opaque target id"),
        (target.revision, "target revision"),
    ):
        if type(value) is not str:
            raise TypeError(
                f"Continuity deletion {name} must be a built-in string"
            )
        if len(value) > MAX_CONTINUITY_MUTATION_IDENTITY_LENGTH:
            raise ValueError(f"Continuity deletion {name} exceeds its hard limit")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(
                f"Continuity deletion {name} must be valid UTF-8"
            ) from exc


def _lifecycle_error(
    message: str,
    *,
    code: str,
    pending_cleanup: ContinuityMutationPendingCleanup | None = None,
) -> ContinuityMutationLifecycleError:
    error = ContinuityMutationLifecycleError(message, code=code)
    error.pending_cleanup = pending_cleanup
    return error


def _wire_target(value: object) -> ContinuityTarget:
    document = _wire_mapping(value, name="Continuity deletion target")
    _wire_exact_fields(
        document,
        fields={"opaqueId", "providerId", "revision"},
        name="Continuity deletion target",
    )
    return ContinuityTarget(
        provider_id=_wire_string(document["providerId"], name="provider id"),
        opaque_id=_wire_string(document["opaqueId"], name="opaque id"),
        revision=_wire_string(document["revision"], name="revision"),
    )


def _wire_mapping(value: object, *, name: str) -> dict[str, object]:
    try:
        return dict(require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise _codec_error(
            f"{name} must be a strict JSON object",
            code="continuity_mutation_record_invalid",
        ) from exc


def _wire_exact_fields(
    value: dict[str, object],
    *,
    fields: set[str],
    name: str,
) -> None:
    if set(value) != fields:
        raise _codec_error(
            f"{name} fields do not match its V1 schema",
            code="continuity_mutation_record_fields_mismatch",
        )


def _wire_version(value: object, *, name: str, expected: int) -> None:
    if type(value) is not int or value != expected:
        raise _codec_error(
            f"Continuity deletion {name} version is unsupported",
            code="continuity_mutation_record_version_unsupported",
        )


def _wire_string(value: object, *, name: str) -> str:
    if type(value) is not str:
        raise _codec_error(
            f"Continuity deletion {name} must be a string",
            code="continuity_mutation_record_invalid",
        )
    return value


def _codec_error(message: str, *, code: str) -> ContinuityMutationCodecError:
    return ContinuityMutationCodecError(message, code=code)


def _fingerprint(domain: str, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + payload).hexdigest()


def _require_sha256(value: object, *, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Continuity {name} must be lowercase SHA-256 hex")


__all__ = [
    "AuthorizedContinuityDeletionLease",
    "ContinuityDeletionAuthorization",
    "ContinuityDeletionAuthority",
    "ContinuityDeletionDisposition",
    "ContinuityDeletionPlanV1",
    "ContinuityDeletionReceiptV1",
    "ContinuityMutationLifecycleError",
    "ContinuityMutationCodecError",
    "ContinuityMutationPendingCleanup",
    "MAX_CONTINUITY_MUTATION_IDENTITY_LENGTH",
    "PreparedContinuityDeletion",
    "consume_authorized_continuity_deletion",
    "prepare_authorized_continuity_deletion",
]
