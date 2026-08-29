"""Coding-owned Product composition-set policy.

The records in this module are inert Product requests.  They neither mutate
Plugin desired state nor resolve, admit, mount, publish, or retire a Plugin.
Those effects remain with the existing management, selection, owner, Catalog,
and Session Graph authorities.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, cast

from loushang.coding.capabilities import (
    CODING_ARCH_CAPABILITY,
    CODING_LSP_CAPABILITY,
)
from loushang.harness.config.agent import CapabilityMountMode

CODING_COMPOSITION_SET_PLAN_VERSION = 1
CODING_KERNEL_PROMPT_REVISION = "coding-kernel-prompt-v1"

CodingCompositionSetId = Literal[
    "coding-minimal",
    "coding-standard",
    "coding-architecture",
]
CodingCompositionPluginKind = Literal["resource", "capability_provider"]

_COMPOSITION_SET_IDS = frozenset(
    {"coding-minimal", "coding-standard", "coding-architecture"}
)
_PLUGIN_KINDS = frozenset({"resource", "capability_provider"})


@dataclass(frozen=True, order=True, slots=True)
class CodingCompositionPluginRequest:
    """One inert first-party Plugin request from a Coding composition set."""

    plugin_id: str
    plugin_kind: CodingCompositionPluginKind
    required: bool
    capability_id: str | None = None
    mount_mode: CapabilityMountMode | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.plugin_id, name="Coding composition Plugin id")
        if self.plugin_kind not in _PLUGIN_KINDS:
            raise ValueError("Unsupported Coding composition Plugin kind")
        if type(self.required) is not bool:
            raise TypeError("Coding composition Plugin required must be a bool")
        if self.plugin_kind == "resource":
            if self.capability_id is not None or self.mount_mode is not None:
                raise ValueError(
                    "Coding Resource Plugin cannot declare a Capability mount"
                )
            return
        if self.capability_id is None or self.mount_mode is None:
            raise ValueError(
                "Coding Capability Provider request requires a Capability mount"
            )
        _require_nonempty(
            self.capability_id,
            name="Coding composition Capability id",
        )
        if self.mount_mode not in {"disabled", "on_demand", "always"}:
            raise ValueError("Unsupported Coding composition Capability mount mode")
        if self.mount_mode == "disabled":
            raise ValueError(
                "Disabled Capability Providers must be absent from the composition set"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "mountMode": self.mount_mode,
            "pluginId": self.plugin_id,
            "pluginKind": self.plugin_kind,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class CodingCompositionSetPlan:
    """Canonical, flattened Product request with set-expansion provenance."""

    set_id: CodingCompositionSetId
    composition_chain: tuple[CodingCompositionSetId, ...]
    plugin_requests: tuple[CodingCompositionPluginRequest, ...]
    kernel_prompt_revision: str = CODING_KERNEL_PROMPT_REVISION
    plan_version: int = CODING_COMPOSITION_SET_PLAN_VERSION

    def __post_init__(self) -> None:
        if self.set_id not in _COMPOSITION_SET_IDS:
            raise ValueError("Unsupported Coding composition set")
        chain = tuple(self.composition_chain)
        if not chain or chain[0] != "coding-minimal" or chain[-1] != self.set_id:
            raise ValueError(
                "Coding composition chain must run from minimal to the selected set"
            )
        if len(chain) != len(set(chain)):
            raise ValueError("Coding composition chain must not repeat a set")
        requests = tuple(self.plugin_requests)
        if any(
            not isinstance(item, CodingCompositionPluginRequest) for item in requests
        ):
            raise TypeError("Coding composition Plugin requests have invalid type")
        if requests != tuple(sorted(requests, key=lambda item: item.plugin_id)):
            raise ValueError("Coding composition Plugin requests must be id-sorted")
        plugin_ids = tuple(item.plugin_id for item in requests)
        if len(plugin_ids) != len(set(plugin_ids)):
            raise ValueError("Coding composition Plugin requests must be unique")
        capability_ids = tuple(
            item.capability_id for item in requests if item.capability_id is not None
        )
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("Coding composition Capability requests must be unique")
        _require_nonempty(
            self.kernel_prompt_revision,
            name="Coding Kernel Prompt revision",
        )
        if self.plan_version != CODING_COMPOSITION_SET_PLAN_VERSION:
            raise ValueError("Unsupported Coding composition-set plan version")
        object.__setattr__(self, "composition_chain", chain)
        object.__setattr__(self, "plugin_requests", requests)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(include_fingerprint=False),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(
            b"loushang.coding-composition-set-plan/v1\0" + payload
        ).hexdigest()

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        document: dict[str, object] = {
            "compositionChain": list(self.composition_chain),
            "kernelPromptRevision": self.kernel_prompt_revision,
            "planVersion": self.plan_version,
            "pluginRequests": [item.to_dict() for item in self.plugin_requests],
            "setId": self.set_id,
        }
        if include_fingerprint:
            document["fingerprint"] = self.fingerprint
        return document


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty normalized string")


_CODING_BASE = CodingCompositionPluginRequest(
    plugin_id="coding.base",
    plugin_kind="resource",
    required=True,
)
_CODING_LSP = CodingCompositionPluginRequest(
    plugin_id="coding.lsp.default",
    plugin_kind="capability_provider",
    required=False,
    capability_id=CODING_LSP_CAPABILITY,
    mount_mode="on_demand",
)
_CODING_ARCH = CodingCompositionPluginRequest(
    plugin_id="coding.arch.default",
    plugin_kind="capability_provider",
    required=False,
    capability_id=CODING_ARCH_CAPABILITY,
    mount_mode="on_demand",
)

_PLANS: dict[CodingCompositionSetId, CodingCompositionSetPlan] = {
    "coding-minimal": CodingCompositionSetPlan(
        set_id="coding-minimal",
        composition_chain=("coding-minimal",),
        plugin_requests=(),
    ),
    "coding-standard": CodingCompositionSetPlan(
        set_id="coding-standard",
        composition_chain=("coding-minimal", "coding-standard"),
        plugin_requests=tuple(sorted((_CODING_BASE, _CODING_LSP))),
    ),
    "coding-architecture": CodingCompositionSetPlan(
        set_id="coding-architecture",
        composition_chain=(
            "coding-minimal",
            "coding-standard",
            "coding-architecture",
        ),
        plugin_requests=tuple(sorted((_CODING_BASE, _CODING_LSP, _CODING_ARCH))),
    ),
}


def resolve_coding_composition_set(
    set_id: str = "coding-standard",
) -> CodingCompositionSetPlan:
    """Resolve one exact Product-authored set without performing live effects."""

    if not isinstance(set_id, str):
        raise TypeError("Coding composition set id must be a string")
    normalized = set_id.strip()
    try:
        return _PLANS[cast(CodingCompositionSetId, normalized)]
    except KeyError as exc:
        raise ValueError(f"Unsupported Coding composition set: {set_id!r}") from exc


__all__ = [
    "CODING_COMPOSITION_SET_PLAN_VERSION",
    "CODING_KERNEL_PROMPT_REVISION",
    "CodingCompositionPluginRequest",
    "CodingCompositionSetId",
    "CodingCompositionSetPlan",
    "resolve_coding_composition_set",
]
