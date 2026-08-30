"""Private live Resource-owner registry for Catalog-managed Skill actions."""

from __future__ import annotations

import hmac
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from secrets import token_bytes


def _owner_credential_seal_functions() -> tuple[
    Callable[[bytes], bytes],
    Callable[[bytes, bytes], bool],
]:
    key = token_bytes(32)

    def seal(payload: bytes) -> bytes:
        return hmac.digest(key, payload, "sha256")

    def verify(payload: bytes, evidence: bytes) -> bool:
        return hmac.compare_digest(seal(payload), evidence)

    return seal, verify


_seal_owner_credential, _verify_owner_credential = _owner_credential_seal_functions()


@dataclass(frozen=True, slots=True, init=False)
class _CatalogActionOwnerCredential:
    """One-shot Resource-owner credential bound to one exact action object."""

    action_identity: int
    owner_identity: object
    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    binding_source_fingerprint: str
    skill_root_identity: tuple[int, int]
    _owner_seal: bytes

    def __init__(self) -> None:
        raise TypeError("Catalog action owner credentials are Resource-owner-minted")

    def _payload(self) -> bytes:
        device, inode = self.skill_root_identity
        return (
            f"{self.action_identity}\0{id(self.owner_identity)}"
            f"\0{self.catalog_generation}"
            f"\0{self.catalog_snapshot_fingerprint}"
            f"\0{self.candidate_fingerprint}"
            f"\0{self.binding_source_fingerprint}\0{device}\0{inode}"
        ).encode()


@dataclass(frozen=True, slots=True)
class _CatalogActionRegistration:
    action_ref: weakref.ReferenceType[object]
    owner_credential: _CatalogActionOwnerCredential


_REGISTRATIONS: dict[int, _CatalogActionRegistration] = {}


def _mint_catalog_action_owner_credential(
    action: object,
    *,
    owner_identity: object,
    catalog_generation: int,
    catalog_snapshot_fingerprint: str,
    candidate_fingerprint: str,
    binding_source_fingerprint: str,
    skill_root_identity: tuple[int, int],
) -> _CatalogActionOwnerCredential:
    """Mint action-bound authority; only the Catalog consumer owns this path."""

    if type(owner_identity) is not object:
        raise TypeError("Catalog action owner identity is invalid")
    credential = object.__new__(_CatalogActionOwnerCredential)
    for name, value in (
        ("action_identity", id(action)),
        ("owner_identity", owner_identity),
        ("catalog_generation", catalog_generation),
        ("catalog_snapshot_fingerprint", catalog_snapshot_fingerprint),
        ("candidate_fingerprint", candidate_fingerprint),
        ("binding_source_fingerprint", binding_source_fingerprint),
        ("skill_root_identity", skill_root_identity),
    ):
        object.__setattr__(credential, name, value)
    object.__setattr__(
        credential,
        "_owner_seal",
        _seal_owner_credential(credential._payload()),
    )
    return credential


def _register_catalog_managed_skill_action(
    action: object,
    *,
    owner_credential: _CatalogActionOwnerCredential,
) -> None:
    """Register one exact action outside its caller-constructible evidence graph."""

    _verify_action_owner_credential(action, owner_credential)
    action_id = id(action)
    if action_id in _REGISTRATIONS:
        raise RuntimeError("Catalog action identity is already registered")

    def discard(reference: weakref.ReferenceType[object]) -> None:
        current = _REGISTRATIONS.get(action_id)
        if current is not None and current.action_ref is reference:
            _REGISTRATIONS.pop(action_id, None)

    reference = weakref.ref(action, discard)
    _REGISTRATIONS[action_id] = _CatalogActionRegistration(
        action_ref=reference,
        owner_credential=owner_credential,
    )


def _verify_catalog_managed_skill_action(action: object) -> None:
    """Require a live exact registration minted by the Resource owner."""

    registration = _REGISTRATIONS.get(id(action))
    selection = getattr(action, "selection", None)
    credential = registration.owner_credential if registration is not None else None
    if (
        registration is None
        or registration.action_ref() is not action
        or type(credential) is not _CatalogActionOwnerCredential
        or not _owner_credential_matches_action(action, credential)
        or getattr(action, "_owner_identity", None) is not credential.owner_identity
        or getattr(selection, "_owner_identity", None) is not credential.owner_identity
        or getattr(selection, "catalog_generation", None)
        != credential.catalog_generation
        or getattr(selection, "catalog_snapshot_fingerprint", None)
        != credential.catalog_snapshot_fingerprint
        or getattr(selection, "candidate_fingerprint", None)
        != credential.candidate_fingerprint
        or getattr(action, "binding_source_fingerprint", None)
        != credential.binding_source_fingerprint
        or getattr(action, "_skill_root_identity", None)
        != credential.skill_root_identity
    ):
        raise ValueError("Catalog action is not live Resource-owner evidence")


def _verify_action_owner_credential(
    action: object,
    credential: _CatalogActionOwnerCredential,
) -> None:
    if type(credential) is not _CatalogActionOwnerCredential:
        raise TypeError("Catalog action registration requires an owner credential")
    if not _owner_credential_matches_action(action, credential):
        raise ValueError("Catalog action owner credential does not match the action")


def _owner_credential_matches_action(
    action: object,
    credential: _CatalogActionOwnerCredential,
) -> bool:
    selection = getattr(action, "selection", None)
    return (
        credential.action_identity == id(action)
        and type(credential.owner_identity) is object
        and _verify_owner_credential(
            credential._payload(),
            credential._owner_seal,
        )
        and getattr(action, "_owner_identity", None) is credential.owner_identity
        and getattr(selection, "_owner_identity", None) is credential.owner_identity
        and getattr(selection, "catalog_generation", None)
        == credential.catalog_generation
        and getattr(selection, "catalog_snapshot_fingerprint", None)
        == credential.catalog_snapshot_fingerprint
        and getattr(selection, "candidate_fingerprint", None)
        == credential.candidate_fingerprint
        and getattr(action, "binding_source_fingerprint", None)
        == credential.binding_source_fingerprint
        and getattr(action, "_skill_root_identity", None)
        == credential.skill_root_identity
    )


__all__: list[str] = []
