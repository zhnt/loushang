"""Inert causal context shared by original Resume effect owners.

These values identify committed parent intent. They grant no native authority,
prove no operation started or completed, and own no journal or lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

RESUME_EFFECT_PARENT_CONTEXT_VERSION = 1
RESUME_EFFECT_PARENT_CONTEXT_MAX_BYTES = 2048
_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CONTEXT_DOMAIN = b"loushang.harness.resume-parent-context/v1\0"
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


__all__ = [
    "RESUME_EFFECT_PARENT_CONTEXT_MAX_BYTES",
    "RESUME_EFFECT_PARENT_CONTEXT_VERSION",
    "ResumeEffectParentContextV1",
]
