"""Inert causal context shared by original Resume effect owners.

These values identify committed parent intent. They grant no native authority,
prove no operation started or completed, and own no journal or lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Self, TypeVar, cast

from loushang.foundation.json import JSONValue

RESUME_EFFECT_PARENT_CONTEXT_VERSION = 1
RESUME_EFFECT_PARENT_CONTEXT_MAX_BYTES = 2048
_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_EFFECT_CODE = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
_CONTEXT_DOMAIN = b"loushang.harness.resume-parent-context/v1\0"
_OWNER_FIELDS = {"ownerId", "scopeDigest", "contractDigest", "phases", "effectClasses"}
_FIELDS = frozenset(
    {
        "contextVersion",
        "productId",
        "sessionId",
        "attemptId",
        "requestId",
        "intentDigest",
        "ownerId",
        "scopeDigest",
        "contractDigest",
    }
)


def valid_resume_effect_codes(value: tuple[str, ...], *, required: bool = False) -> bool:
    return (
        type(value) is tuple
        and len(value) <= 16
        and (not required or bool(value))
        and all(type(code) is str and _EFFECT_CODE.fullmatch(code) is not None for code in value)
        and value == tuple(sorted(set(value)))
    )


class _ResumeEffectOwnerFields:
    """Validation and wire values for a Product's nominal frozen obligation."""

    __slots__ = ()
    _effect_owner_label: ClassVar[str]
    owner_id: str
    scope_digest: str
    contract_digest: str
    phases: tuple[str, ...]
    effect_classes: tuple[str, ...]

    def __post_init__(self) -> None:
        label = self._effect_owner_label
        if type(self.owner_id) is not str or _IDENTIFIER.fullmatch(self.owner_id) is None:
            raise ValueError(f"{label} effect owner id is invalid")
        for value in (self.scope_digest, self.contract_digest):
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise ValueError(f"{label} owner digest is invalid")
        if not valid_resume_effect_codes(self.phases, required=True):
            raise ValueError(f"{label} owner phases must be bounded, sorted and unique")
        if not valid_resume_effect_codes(self.effect_classes):
            raise ValueError(f"{label} owner effect classes must be bounded, sorted and unique")

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.owner_id, self.scope_digest, self.contract_digest

    def to_data(self) -> dict[str, JSONValue]:
        return {
            "ownerId": self.owner_id,
            "scopeDigest": self.scope_digest,
            "contractDigest": self.contract_digest,
            "phases": list(self.phases),
            "effectClasses": list(self.effect_classes),
        }

    @classmethod
    def from_data(cls, raw: object) -> Self:
        label = cls._effect_owner_label
        if type(raw) is not dict or set(raw) != _OWNER_FIELDS:
            raise ValueError(f"{label} effect owner fields are invalid")
        if type(raw["phases"]) is not list or type(raw["effectClasses"]) is not list:
            raise ValueError(f"{label} owner codes require arrays")
        construct = cast(
            Callable[[str, str, str, tuple[str, ...], tuple[str, ...]], Self], cls
        )
        return construct(
            cast(str, raw["ownerId"]),
            cast(str, raw["scopeDigest"]),
            cast(str, raw["contractDigest"]),
            tuple(raw["phases"]),
            tuple(raw["effectClasses"]),
        )


@dataclass(frozen=True, slots=True)
class ResumeEffectParentContextV1:
    """Bounded lookup data, independent of paths, grants and live objects."""

    product_id: str
    session_id: str
    attempt_id: str
    request_id: str
    intent_digest: str
    owner_id: str
    scope_digest: str
    contract_digest: str
    context_version: int = RESUME_EFFECT_PARENT_CONTEXT_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.context_version) is not int
            or self.context_version != RESUME_EFFECT_PARENT_CONTEXT_VERSION
        ):
            raise ValueError("Unsupported Resume parent context version")
        for name in (
            "product_id",
            "session_id",
            "attempt_id",
            "request_id",
            "owner_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"Invalid Resume parent {name}")
        for name in ("intent_digest", "scope_digest", "contract_digest"):
            value = getattr(self, name)
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise ValueError(f"Invalid Resume parent {name}")
        if len(self.canonical_bytes()) > RESUME_EFFECT_PARENT_CONTEXT_MAX_BYTES:
            raise ValueError("Resume parent context exceeds its encoded budget")

    def to_dict(self) -> dict[str, object]:
        return {
            "contextVersion": self.context_version,
            "productId": self.product_id,
            "sessionId": self.session_id,
            "attemptId": self.attempt_id,
            "requestId": self.request_id,
            "intentDigest": self.intent_digest,
            "ownerId": self.owner_id,
            "scopeDigest": self.scope_digest,
            "contractDigest": self.contract_digest,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @property
    def digest(self) -> str:
        return hashlib.sha256(_CONTEXT_DOMAIN + self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> ResumeEffectParentContextV1:
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise ValueError("Resume parent context requires exact fields")
        # Validate native values before serialization; coercion would turn a
        # malformed identity or version into an apparently valid context.
        names = {
            "product_id": "productId",
            "session_id": "sessionId",
            "attempt_id": "attemptId",
            "request_id": "requestId",
            "intent_digest": "intentDigest",
            "owner_id": "ownerId",
            "scope_digest": "scopeDigest",
            "contract_digest": "contractDigest",
        }
        fields: dict[str, str] = {}
        for name, key in names.items():
            item = value[key]
            if type(item) is not str:
                raise ValueError(f"Invalid Resume parent {name}")
            fields[name] = item
        version = value["contextVersion"]
        if type(version) is not int:
            raise ValueError("Unsupported Resume parent context version")
        return cls(**fields, context_version=version)


_NativeOwnerT = TypeVar("_NativeOwnerT", bound=_ResumeEffectOwnerFields)


def select_native_resume_parents(
    effect_owners: tuple[_NativeOwnerT, ...],
    *,
    effect_classes: tuple[str, ...],
    worker_candidate_id: str | None,
    parent: Callable[[_NativeOwnerT], ResumeEffectParentContextV1],
    unsupported: Callable[[], Exception],
) -> tuple[
    tuple[ResumeEffectParentContextV1, ResumeEffectParentContextV1] | None,
    ResumeEffectParentContextV1 | None,
]:
    """Require the exact native journal participants before returning lookup contexts."""
    definition_id = "harness.plugin-execution"
    activation_id = "harness.plugin-activation"
    worker_id = "harness.worker-activation"
    plugin_ids = {definition_id, activation_id}
    owners = {owner.owner_id: owner for owner in effect_owners}
    selected_plugins = plugin_ids & owners.keys()
    supported = plugin_ids | ({worker_id} if worker_candidate_id else set())
    worker = owners.get(worker_id)
    if (
        (selected_plugins and selected_plugins != plugin_ids)
        or owners.keys() - supported
        or effect_classes
        or any(owner.effect_classes for owner in effect_owners)
        or (worker_candidate_id is None) != (worker is None)
    ):
        raise unsupported()
    worker_parent = None
    if worker is not None:
        if worker.phases != ("reservation", "start"):
            raise unsupported()
        worker_parent = parent(worker)
    if not selected_plugins:
        return None, worker_parent
    definition, activation = owners[definition_id], owners[activation_id]
    if definition.phases != ("declaration",) or activation.phases != ("activation",):
        raise unsupported()
    return (parent(definition), parent(activation)), worker_parent


__all__ = [
    "RESUME_EFFECT_PARENT_CONTEXT_MAX_BYTES",
    "RESUME_EFFECT_PARENT_CONTEXT_VERSION",
    "ResumeEffectParentContextV1",
]
