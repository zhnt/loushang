"""Exact, read-only Capability-domain adapter for one admitted Worker session."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256

from .supervisor import WorkerSupervisor

CAPABILITY_WORKER_AUTHORITY_VERSION = 1
CAPABILITY_WORKER_BINDING_VERSION = 1
CAPABILITY_WORKER_ADMISSION_VERSION = 1
CAPABILITY_WORKER_DESCRIPTOR_VERSION = 1
CAPABILITY_WORKER_FACET_GRANT_VERSION = 1
MAX_CAPABILITY_WORKER_DESCRIPTORS = 128
MAX_CAPABILITY_WORKER_FACETS_PER_DESCRIPTOR = 64
MAX_CAPABILITY_WORKER_IDENTIFIER_LENGTH = 128
MAX_CAPABILITY_WORKER_FACET_PAYLOAD_BYTES = 16 * 1024

_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_OPAQUE_SCOPE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?")
_CAPABILITY_WORKER_ACTIVATION = object()


class CapabilityWorkerAdapterError(RuntimeError):
    """Stable refusal from the exact read-only Capability adapter."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CapabilityWorkerAuthorityV1:
    plugin_revision_digest: str
    declaration_fingerprint: str
    owner_generation: int
    product_policy_revision: str
    owner_policy_revision: str
    revocation_epoch: int
    authority_version: int = CAPABILITY_WORKER_AUTHORITY_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.plugin_revision_digest, name="Plugin revision digest")
        _require_sha256(
            self.declaration_fingerprint,
            name="declaration fingerprint",
        )
        _require_positive_integer(self.owner_generation, name="owner generation")
        _require_identifier(
            self.product_policy_revision,
            name="Product policy revision",
        )
        _require_identifier(
            self.owner_policy_revision,
            name="owner policy revision",
        )
        _require_nonnegative_integer(self.revocation_epoch, name="revocation epoch")
        _require_version(
            self.authority_version,
            CAPABILITY_WORKER_AUTHORITY_VERSION,
            "Capability Worker authority",
        )

    @property
    def fingerprint(self) -> str:
        return _digest("loushang.capability-worker-authority/v1", self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "authorityVersion": self.authority_version,
            "declarationFingerprint": self.declaration_fingerprint,
            "ownerGeneration": self.owner_generation,
            "ownerPolicyRevision": self.owner_policy_revision,
            "pluginRevisionDigest": self.plugin_revision_digest,
            "productPolicyRevision": self.product_policy_revision,
            "revocationEpoch": self.revocation_epoch,
        }


@dataclass(frozen=True, slots=True)
class CapabilityWorkerBindingV1:
    plugin_id: str
    contribution_id: str
    product_id: str
    scope_id: str
    owner_id: str
    allowed_capability_ids: tuple[str, ...]
    authority: CapabilityWorkerAuthorityV1
    binding_version: int = CAPABILITY_WORKER_BINDING_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("Plugin id", self.plugin_id),
            ("contribution id", self.contribution_id),
            ("Product id", self.product_id),
            ("Capability owner id", self.owner_id),
        ):
            _require_identifier(value, name=name)
        _require_scope_id(self.scope_id)
        capabilities = tuple(self.allowed_capability_ids)
        if not capabilities:
            raise ValueError("Capability Worker allowlist must not be empty")
        if len(capabilities) > MAX_CAPABILITY_WORKER_DESCRIPTORS:
            raise ValueError("Capability Worker allowlist exceeds its bound")
        for capability_id in capabilities:
            _require_identifier(capability_id, name="allowed Capability id")
        if capabilities != tuple(sorted(set(capabilities))):
            raise ValueError("Capability Worker allowlist must be sorted and unique")
        if not isinstance(self.authority, CapabilityWorkerAuthorityV1):
            raise TypeError("Capability Worker binding requires authority evidence")
        _require_version(
            self.binding_version,
            CAPABILITY_WORKER_BINDING_VERSION,
            "Capability Worker binding",
        )
        object.__setattr__(self, "allowed_capability_ids", capabilities)

    @property
    def fingerprint(self) -> str:
        return _digest("loushang.capability-worker-binding/v1", self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "allowedCapabilityIds": list(self.allowed_capability_ids),
            "authority": self.authority.to_dict(),
            "bindingVersion": self.binding_version,
            "contributionId": self.contribution_id,
            "ownerId": self.owner_id,
            "pluginId": self.plugin_id,
            "productId": self.product_id,
            "scopeId": self.scope_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilityWorkerAdmissionV1:
    binding_fingerprint: str
    authority_fingerprint: str
    worker_identity_fingerprint: str
    worker_attempt_id: str
    worker_supervisor_epoch: int
    admission_version: int = CAPABILITY_WORKER_ADMISSION_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("Capability Worker binding fingerprint", self.binding_fingerprint),
            ("Capability Worker authority fingerprint", self.authority_fingerprint),
            ("Worker identity fingerprint", self.worker_identity_fingerprint),
        ):
            _require_sha256(value, name=name)
        _require_hex(self.worker_attempt_id, length=32, name="Worker attempt id")
        _require_positive_integer(
            self.worker_supervisor_epoch,
            name="Worker supervisor epoch",
        )
        _require_version(
            self.admission_version,
            CAPABILITY_WORKER_ADMISSION_VERSION,
            "Capability Worker admission",
        )

    @property
    def fingerprint(self) -> str:
        return _digest("loushang.capability-worker-admission/v1", self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionVersion": self.admission_version,
            "authorityFingerprint": self.authority_fingerprint,
            "bindingFingerprint": self.binding_fingerprint,
            "workerAttemptId": self.worker_attempt_id,
            "workerIdentityFingerprint": self.worker_identity_fingerprint,
            "workerSupervisorEpoch": self.worker_supervisor_epoch,
        }


@dataclass(frozen=True, slots=True)
class CapabilityWorkerDescriptorV1:
    capability_id: str
    facet_ids: tuple[str, ...]
    descriptor_version: int = CAPABILITY_WORKER_DESCRIPTOR_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.capability_id, name="Capability id")
        facets = tuple(self.facet_ids)
        if len(facets) > MAX_CAPABILITY_WORKER_FACETS_PER_DESCRIPTOR:
            raise ValueError("Capability Worker facet list exceeds its bound")
        for facet_id in facets:
            _require_identifier(facet_id, name="Capability facet id")
        if facets != tuple(sorted(set(facets))):
            raise ValueError("Capability facet ids must be sorted and unique")
        _require_version(
            self.descriptor_version,
            CAPABILITY_WORKER_DESCRIPTOR_VERSION,
            "Capability Worker descriptor",
        )
        object.__setattr__(self, "facet_ids", facets)

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "descriptorVersion": self.descriptor_version,
            "facetIds": list(self.facet_ids),
        }


@dataclass(frozen=True, slots=True)
class CapabilityWorkerFacetGrantV1:
    """Capability-owner permission for one callable, read-only Worker facet."""

    capability_id: str
    facet_id: str
    binding_fingerprint: str
    authority_fingerprint: str
    owner_policy_revision: str
    grant_version: int = CAPABILITY_WORKER_FACET_GRANT_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.capability_id, name="Capability id")
        _require_identifier(self.facet_id, name="Capability facet id")
        _require_sha256(self.binding_fingerprint, name="Capability binding fingerprint")
        _require_sha256(
            self.authority_fingerprint, name="Capability authority fingerprint"
        )
        _require_identifier(self.owner_policy_revision, name="owner policy revision")
        _require_version(
            self.grant_version,
            CAPABILITY_WORKER_FACET_GRANT_VERSION,
            "Capability Worker facet grant",
        )

    @property
    def fingerprint(self) -> str:
        return _digest("loushang.capability-worker-facet-grant/v1", self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "authorityFingerprint": self.authority_fingerprint,
            "bindingFingerprint": self.binding_fingerprint,
            "capabilityId": self.capability_id,
            "facetId": self.facet_id,
            "grantVersion": self.grant_version,
            "ownerPolicyRevision": self.owner_policy_revision,
        }


class CapabilityQueryWorkerAdapter:
    """Query one fixed Capability allowlist; owns no publication or retirement."""

    def __init__(
        self,
        *,
        supervisor: WorkerSupervisor,
        binding: CapabilityWorkerBindingV1,
        authority_reader: Callable[[], CapabilityWorkerAuthorityV1],
        _activation: object | None = None,
    ) -> None:
        if _activation is not _CAPABILITY_WORKER_ACTIVATION:
            raise CapabilityWorkerAdapterError(
                "Capability Worker adapter is disabled by policy",
                code="worker_disabled_by_policy",
            )
        if not isinstance(supervisor, WorkerSupervisor):
            raise TypeError("Capability Worker adapter requires a Worker supervisor")
        if not isinstance(binding, CapabilityWorkerBindingV1):
            raise TypeError("Capability Worker adapter requires a typed binding")
        if not callable(authority_reader):
            raise TypeError("Capability Worker adapter requires an authority reader")
        identity = supervisor.identity
        if (
            identity.plugin_id != binding.plugin_id
            or identity.contribution_id != binding.contribution_id
            or identity.product_id != binding.product_id
            or identity.scope_id != binding.scope_id
            or identity.owner_id != binding.owner_id
            or identity.plugin_revision_digest
            != binding.authority.plugin_revision_digest
            or identity.declaration_fingerprint
            != binding.authority.declaration_fingerprint
            or identity.owner_generation != binding.authority.owner_generation
        ):
            raise CapabilityWorkerAdapterError(
                "Capability Worker binding does not match the supervised identity",
                code="worker_capability_binding_mismatch",
            )
        self._supervisor = supervisor
        self._binding = binding
        self._authority_reader = authority_reader
        self._admission: CapabilityWorkerAdmissionV1 | None = None
        self._descriptors: tuple[CapabilityWorkerDescriptorV1, ...] | None = None

    @property
    def admission(self) -> CapabilityWorkerAdmissionV1 | None:
        return self._admission

    @property
    def descriptors(self) -> tuple[CapabilityWorkerDescriptorV1, ...] | None:
        """Return only descriptors verified for this admitted attempt."""

        return self._descriptors

    @property
    def binding(self) -> CapabilityWorkerBindingV1:
        return self._binding

    def assert_admitted_current(self, admission: CapabilityWorkerAdmissionV1) -> None:
        """Verify the exact attempt, supervisor, and owner before publication."""

        self._validate_admission(admission)

    async def fence(self, *, code: str) -> None:
        """Stop this exact supervised attempt after an owner-side refusal."""

        await self._supervisor.fence(code=code)

    def admit(self) -> CapabilityWorkerAdmissionV1:
        self._validate_current()
        if self._supervisor.status.state != "healthy":
            raise CapabilityWorkerAdapterError(
                "Capability Worker protocol is not healthy",
                code="worker_capability_protocol_not_healthy",
            )
        identity = self._supervisor.identity
        admission = CapabilityWorkerAdmissionV1(
            binding_fingerprint=self._binding.fingerprint,
            authority_fingerprint=self._binding.authority.fingerprint,
            worker_identity_fingerprint=identity.fingerprint,
            worker_attempt_id=identity.attempt_id,
            worker_supervisor_epoch=identity.supervisor_epoch,
        )
        self._admission = admission
        return admission

    async def describe(self) -> tuple[CapabilityWorkerDescriptorV1, ...]:
        admission = self._admission
        if admission is None:
            raise CapabilityWorkerAdapterError(
                "Capability Worker has not passed domain admission",
                code="worker_capability_not_admitted",
            )
        try:
            self._validate_admission(admission)
        except CapabilityWorkerAdapterError as exc:
            await self._supervisor.fence(code=exc.code)
            raise
        response = await self._supervisor.query(
            {
                "admissionFingerprint": admission.fingerprint,
                "allowedCapabilityIds": list(self._binding.allowed_capability_ids),
                "operation": "describe",
                "queryVersion": 1,
            }
        )
        try:
            descriptors = _decode_descriptors(response)
            identities = tuple(item.capability_id for item in descriptors)
            if any(
                capability_id not in self._binding.allowed_capability_ids
                for capability_id in identities
            ):
                raise ValueError("Worker returned a Capability outside its allowlist")
        except (TypeError, ValueError) as exc:
            await self._supervisor.fence(code="worker_capability_payload_invalid")
            raise CapabilityWorkerAdapterError(
                "Capability Worker returned an invalid read-only descriptor",
                code="worker_capability_payload_invalid",
            ) from exc
        try:
            self._validate_admission(admission)
        except CapabilityWorkerAdapterError as exc:
            await self._supervisor.fence(code=exc.code)
            raise
        self._descriptors = descriptors
        return descriptors

    async def invoke_read_only_facet(
        self,
        *,
        grant: CapabilityWorkerFacetGrantV1,
        request: Mapping[str, object],
        decode_result: Callable[[object], object],
    ) -> object:
        """Call one described facet under a separate owner grant and codec."""

        admission = self._admission
        descriptors = self._descriptors
        if admission is None or descriptors is None:
            raise CapabilityWorkerAdapterError(
                "Capability Worker facet has not passed domain admission",
                code="worker_capability_not_admitted",
            )
        if (
            not isinstance(grant, CapabilityWorkerFacetGrantV1)
            or grant.binding_fingerprint != self._binding.fingerprint
            or grant.authority_fingerprint != self._binding.authority.fingerprint
            or grant.owner_policy_revision
            != self._binding.authority.owner_policy_revision
            or grant.capability_id not in self._binding.allowed_capability_ids
            or not any(
                item.capability_id == grant.capability_id
                and grant.facet_id in item.facet_ids
                for item in descriptors
            )
            or not callable(decode_result)
        ):
            raise CapabilityWorkerAdapterError(
                "Capability Worker facet grant is invalid",
                code="worker_capability_facet_grant_invalid",
            )
        try:
            payload = _bounded_facet_payload(request)
            self._validate_admission(admission)
        except CapabilityWorkerAdapterError as exc:
            await self._supervisor.fence(code=exc.code)
            raise
        response = await self._supervisor.query(
            {
                "admissionFingerprint": admission.fingerprint,
                "capabilityId": grant.capability_id,
                "facetGrantFingerprint": grant.fingerprint,
                "facetId": grant.facet_id,
                "operation": "invokeReadOnlyFacet",
                "queryVersion": 1,
                "request": payload,
            }
        )
        try:
            value = _bounded_facet_result(response)
            decoded = decode_result(value)
        except Exception as exc:
            await self._supervisor.fence(code="worker_capability_facet_result_invalid")
            raise CapabilityWorkerAdapterError(
                "Capability Worker facet result is invalid",
                code="worker_capability_facet_result_invalid",
            ) from exc
        try:
            self._validate_admission(admission)
        except CapabilityWorkerAdapterError as exc:
            await self._supervisor.fence(code=exc.code)
            raise
        return decoded

    def _validate_admission(self, admission: CapabilityWorkerAdmissionV1) -> None:
        identity = self._supervisor.identity
        if (
            admission != self._admission
            or admission.binding_fingerprint != self._binding.fingerprint
            or admission.authority_fingerprint != self._binding.authority.fingerprint
            or admission.worker_identity_fingerprint != identity.fingerprint
            or admission.worker_attempt_id != identity.attempt_id
            or admission.worker_supervisor_epoch != identity.supervisor_epoch
            or self._supervisor.status.state != "healthy"
        ):
            raise CapabilityWorkerAdapterError(
                "Capability Worker admission is stale",
                code="worker_capability_admission_stale",
            )
        self._validate_current()

    def _validate_current(self) -> None:
        try:
            current = self._authority_reader()
        except Exception as exc:
            raise CapabilityWorkerAdapterError(
                "Capability Worker authority is unavailable",
                code="worker_capability_authority_unavailable",
            ) from exc
        if not isinstance(current, CapabilityWorkerAuthorityV1):
            raise CapabilityWorkerAdapterError(
                "Capability Worker authority reader returned invalid evidence",
                code="worker_capability_authority_invalid",
            )
        if current != self._binding.authority:
            raise CapabilityWorkerAdapterError(
                "Capability Worker authority changed",
                code="worker_capability_authority_stale",
            )


def bind_capability_query_worker_adapter(
    *,
    supervisor: WorkerSupervisor,
    binding: CapabilityWorkerBindingV1,
    authority_reader: Callable[[], CapabilityWorkerAuthorityV1],
    enabled: bool = False,
) -> CapabilityQueryWorkerAdapter:
    """Explicit dark/canary gate; no Product path enables it implicitly."""

    if type(enabled) is not bool:
        raise TypeError("Capability Worker activation gate must be a bool")
    if not enabled:
        raise CapabilityWorkerAdapterError(
            "Capability Worker adapter is disabled by policy",
            code="worker_disabled_by_policy",
        )
    return CapabilityQueryWorkerAdapter(
        supervisor=supervisor,
        binding=binding,
        authority_reader=authority_reader,
        _activation=_CAPABILITY_WORKER_ACTIVATION,
    )


def _decode_descriptors(
    response: Mapping[str, object],
) -> tuple[CapabilityWorkerDescriptorV1, ...]:
    if set(response) != {"capabilities", "responseVersion"}:
        raise ValueError("Capability Worker response fields are invalid")
    if type(response["responseVersion"]) is not int or response["responseVersion"] != 1:
        raise ValueError("Capability Worker response version is unsupported")
    values = response["capabilities"]
    if not isinstance(values, list) or len(values) > MAX_CAPABILITY_WORKER_DESCRIPTORS:
        raise ValueError("Capability Worker descriptor count is invalid")
    descriptors: list[CapabilityWorkerDescriptorV1] = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "capabilityId",
            "descriptorVersion",
            "facetIds",
        }:
            raise ValueError("Capability Worker descriptor fields are invalid")
        facets = value["facetIds"]
        if not isinstance(facets, list) or any(
            not isinstance(item, str) for item in facets
        ):
            raise TypeError("Capability Worker facet ids must be strings")
        descriptors.append(
            CapabilityWorkerDescriptorV1(
                capability_id=_require_string(
                    value["capabilityId"], name="Capability id"
                ),
                facet_ids=tuple(facets),
                descriptor_version=_require_integer(
                    value["descriptorVersion"],
                    name="Capability Worker descriptor version",
                ),
            )
        )
    identities = tuple(item.capability_id for item in descriptors)
    if identities != tuple(sorted(set(identities))):
        raise ValueError("Capability Worker descriptors must be sorted and unique")
    return tuple(descriptors)


def _bounded_facet_payload(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise CapabilityWorkerAdapterError(
            "Capability Worker facet request is invalid",
            code="worker_capability_facet_request_invalid",
        )
    try:
        _check_facet_json_budget(value)
        body = json.dumps(
            dict(value),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise CapabilityWorkerAdapterError(
            "Capability Worker facet request is invalid",
            code="worker_capability_facet_request_invalid",
        ) from exc
    if len(body) > MAX_CAPABILITY_WORKER_FACET_PAYLOAD_BYTES:
        raise CapabilityWorkerAdapterError(
            "Capability Worker facet request exceeds its bound",
            code="worker_capability_facet_request_invalid",
        )
    return json.loads(body)


def _bounded_facet_result(response: Mapping[str, object]) -> object:
    if (
        not isinstance(response, Mapping)
        or set(response) != {"responseVersion", "value"}
        or type(response["responseVersion"]) is not int
        or response["responseVersion"] != 1
    ):
        raise ValueError("Capability Worker facet response fields are invalid")
    _check_facet_json_budget(response)
    body = json.dumps(
        dict(response),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(body) > MAX_CAPABILITY_WORKER_FACET_PAYLOAD_BYTES:
        raise ValueError("Capability Worker facet response exceeds its bound")
    return response["value"]


def _check_facet_json_budget(value: object) -> None:
    """Bound nested JSON work before the encoder allocates its output."""

    stack = [(value, 0)]
    nodes = 0
    characters = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > 1024 or depth > 16:
            raise ValueError("Capability Worker facet JSON exceeds its bound")
        if isinstance(item, Mapping):
            if len(item) > 1024:
                raise ValueError("Capability Worker facet JSON exceeds its bound")
            for key, member in item.items():
                if type(key) is not str:
                    raise ValueError("Capability Worker facet JSON key is invalid")
                characters += len(key)
                stack.append((member, depth + 1))
        elif isinstance(item, (list, tuple)):
            if len(item) > 1024:
                raise ValueError("Capability Worker facet JSON exceeds its bound")
            stack.extend((member, depth + 1) for member in item)
        elif isinstance(item, str):
            characters += len(item)
        elif item is None or isinstance(item, bool):
            pass
        elif type(item) is int:
            if item.bit_length() > 4096:
                raise ValueError("Capability Worker facet integer exceeds its bound")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Capability Worker facet number is invalid")
        else:
            raise ValueError("Capability Worker facet JSON value is invalid")
        if characters > MAX_CAPABILITY_WORKER_FACET_PAYLOAD_BYTES:
            raise ValueError("Capability Worker facet JSON exceeds its bound")


def _digest(domain: str, value: object) -> str:
    return sha256(
        json.dumps(
            {"domain": domain, "value": value},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _require_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _require_identifier(value: object, *, name: str) -> str:
    result = _require_string(value, name=name)
    if len(
        result
    ) > MAX_CAPABILITY_WORKER_IDENTIFIER_LENGTH or not _IDENTIFIER.fullmatch(result):
        raise ValueError(f"{name} is invalid")
    return result


def _require_scope_id(value: object) -> str:
    result = _require_string(value, name="scope id")
    if (
        len(result) > MAX_CAPABILITY_WORKER_IDENTIFIER_LENGTH
        or not _OPAQUE_SCOPE.fullmatch(result)
    ):
        raise ValueError("scope id is invalid")
    return result


def _require_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _require_nonnegative_integer(value: object, *, name: str) -> int:
    result = _require_integer(value, name=name)
    if result < 0:
        raise ValueError(f"{name} must not be negative")
    return result


def _require_positive_integer(value: object, *, name: str) -> int:
    result = _require_nonnegative_integer(value, name=name)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result


def _require_hex(value: object, *, length: int, name: str) -> str:
    result = _require_string(value, name=name)
    if len(result) != length or any(char not in "0123456789abcdef" for char in result):
        raise ValueError(f"{name} must be lowercase hexadecimal")
    return result


def _require_sha256(value: object, *, name: str) -> str:
    return _require_hex(value, length=64, name=name)


def _require_version(value: object, supported: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} version must be an integer")
    if value != supported:
        raise ValueError(f"Unsupported {name} version")


__all__ = [
    "CAPABILITY_WORKER_ADMISSION_VERSION",
    "CAPABILITY_WORKER_AUTHORITY_VERSION",
    "CAPABILITY_WORKER_BINDING_VERSION",
    "CAPABILITY_WORKER_DESCRIPTOR_VERSION",
    "CAPABILITY_WORKER_FACET_GRANT_VERSION",
    "MAX_CAPABILITY_WORKER_DESCRIPTORS",
    "MAX_CAPABILITY_WORKER_FACET_PAYLOAD_BYTES",
    "MAX_CAPABILITY_WORKER_FACETS_PER_DESCRIPTOR",
    "MAX_CAPABILITY_WORKER_IDENTIFIER_LENGTH",
    "CapabilityQueryWorkerAdapter",
    "CapabilityWorkerAdapterError",
    "CapabilityWorkerAdmissionV1",
    "CapabilityWorkerAuthorityV1",
    "CapabilityWorkerBindingV1",
    "CapabilityWorkerDescriptorV1",
    "CapabilityWorkerFacetGrantV1",
    "bind_capability_query_worker_adapter",
]
