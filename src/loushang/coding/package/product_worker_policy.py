"""Default-dark Product policy derivation from one selected Worker Wheel.

This module returns an authority-free Worker policy. It cannot issue an
activation receipt, reserve a native profile, or publish a Capability owner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import partial
from hashlib import sha256

from loushang.coding.hosted._worker_canary import (
    CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID,
    CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
    coding_product_worker_session_fingerprint,
)
from loushang.harness.package_product._worker_product_authority import (
    _derive_product_selected_worker_policy,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    ProductWorkerNativeClosureFacts,
    ProductWorkerOptInFacts,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.worker.product_activation import ProductWorkerActivationPolicyV1

_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TEXT = 128
_NATIVE_PROFILES = {
    "linux-x86_64": CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID,
    "windows-amd64": CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
}


class CodingWorkerPolicySelectionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodingWorkerNativeClosureReadError(RuntimeError):
    """The Product-bound native closure is unavailable or changed."""


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInV1(ProductWorkerOptInFacts):
    """An exact per-install decision input; this record grants no authority."""

    plugin_id: str
    contribution_id: str
    owner_id: str
    artifact_digest: str
    native_platform: str
    owner_selection_generation: int
    kill_switch_generation: int
    require_worker: bool

    def __post_init__(self) -> None:
        self._validate_opt_in(
            max_text=_MAX_TEXT,
            identifier=_IDENTIFIER,
            digest=_DIGEST,
            native_profiles=_NATIVE_PROFILES,
            label="Coding Worker",
        )

    def to_dict(self) -> dict[str, object]:
        return _OPT_IN_ENCODE_SCHEMA.encode(self)

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerOptInV1:
        if type(value) is not dict or set(value) != _OPT_IN_SCHEMA.keys:
            raise ValueError("Coding Worker opt-in record is invalid")
        return _OPT_IN_SCHEMA.decode(cls, value)


_OPT_IN_SCHEMA = RecordSchema.for_dataclass(CodingWorkerOptInV1, lambda value: value)
_OPT_IN_ENCODE_SCHEMA = RecordSchema(
    _OPT_IN_SCHEMA.text_decoder,
    tuple(sorted(_OPT_IN_SCHEMA.fields, key=lambda item: item.wire_key)),
)


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeClosureV1(ProductWorkerNativeClosureFacts):
    """Authority-free native facts supplied by a separate Product owner."""

    native_platform: str
    native_profile_catalog_revision: str
    containment_launcher_digest: str
    containment_profile_digest: str

    def __post_init__(self) -> None:
        self._validate_native_closure(
            max_text=_MAX_TEXT,
            opaque=_OPAQUE,
            digest=_DIGEST,
            native_profiles=_NATIVE_PROFILES,
            label="Coding Worker",
        )

    def to_dict(self) -> dict[str, object]:
        return _NATIVE_CLOSURE_SCHEMA.encode(self)


_NATIVE_CLOSURE_SCHEMA = RecordSchema.for_dataclass(
    CodingWorkerNativeClosureV1, lambda value: value
)


def coding_worker_session_scope_id(session_id: str) -> str:
    """Derive the exact Worker scope carried by a Product Session receipt."""

    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Coding Worker Session identity is invalid")
    return (
        "session."
        + sha256(
            b"loushang.coding-worker-session-scope/v1\0" + session_id.encode("utf-8")
        ).hexdigest()
    )


_DERIVE_SELECTED_WORKER_POLICY = partial(
    _derive_product_selected_worker_policy,
    product_id="coding",
    source_trust_class="local-worker-candidate",
    opt_in_type=CodingWorkerOptInV1,
    native_closure_type=CodingWorkerNativeClosureV1,
    native_profiles=_NATIVE_PROFILES,
    session_scope_id=coding_worker_session_scope_id,
    session_fingerprint=coding_product_worker_session_fingerprint,
    activation_policy=partial(
        ProductWorkerActivationPolicyV1,
        product_id="coding",
        enabled=True,
        allowed_product_ids=("coding",),
        requested_owner="hosting",
        no_fallback=True,
    ),
    error_type=CodingWorkerPolicySelectionError,
    error_prefix="coding_worker_",
)


def derive_coding_selected_worker_policy(
    *,
    runtime: PackageProductRuntimeBindingV1,
    product_policy: PackageProductLocalWheelPolicy,
    selected: PackageProductSelectedPluginManifestV1,
    session_id: str,
    product_runtime_id: str,
    opt_in: CodingWorkerOptInV1 | None,
    native_closure: CodingWorkerNativeClosureV1 | None = None,
    session_discovery: SessionDiscoveryMetadata | None = None,
) -> ProductWorkerActivationPolicyV1 | None:
    """Recheck Product selection and derive one explicit, authority-free policy."""

    return _DERIVE_SELECTED_WORKER_POLICY(
        runtime=runtime,
        product_policy=product_policy,
        selected=selected,
        session_id=session_id,
        product_runtime_id=product_runtime_id,
        opt_in=opt_in,
        native_closure=native_closure,
        session_discovery=session_discovery,
    )


__all__ = [
    "CodingWorkerOptInV1",
    "CodingWorkerNativeClosureV1",
    "CodingWorkerPolicySelectionError",
    "coding_worker_session_scope_id",
    "derive_coding_selected_worker_policy",
]
