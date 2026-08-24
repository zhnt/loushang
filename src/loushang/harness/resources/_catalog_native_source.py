"""Bounded native-filesystem ``resource.source`` component for RCP2 shadow use.

The source receives Host-minted root handles rather than arbitrary paths.  It
performs synchronous, no-follow discovery, retains the exact discovered bytes,
and serves only load handles for its still-live source generation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, TypeAlias

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._catalog_records import (
    NO_BODY_MEDIA_TYPE,
    NativeHostOrigin,
    ResourceBodyRead,
    ResourceCandidateSummary,
    ResourceCatalogDiagnostic,
    ResourceComponentProducer,
    ResourceIdentity,
    ResourceInvocationPolicy,
    ResourceLoadHandle,
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
    build_candidate_summary,
    build_source_snapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources._catalog_source_contracts import (
    ResourceDiscoveryRequest,
)
from loushang.harness.resources._descriptor_parsing import (
    _prompt_descriptor_from_text,
    _skill_descriptor_from_text,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
    IGNORE_FILE_NAMES,
    SOURCE_LABEL,
)
from loushang.harness.resources._skill_ignore import (
    is_skill_path_ignored,
    normalize_skill_ignore_pattern,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSourceScope,
    SkillDescriptor,
    ThemeDescriptor,
)

NativeResourceSourceClass = Literal[
    "project_local",
    "user_global",
    "temporary",
]
NativeResourceRootKind = Literal["context", "standard", "combined"]
NativeDescriptor: TypeAlias = (
    PromptFragmentDescriptor | SkillDescriptor | ExtensionDescriptor | ThemeDescriptor
)

_HANDLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_NATIVE_SCOPE: dict[NativeResourceSourceClass, ResourceSourceScope] = {
    "project_local": "project",
    "user_global": "user",
    "temporary": "temporary",
}
_ORIGIN_SCOPE: dict[NativeResourceSourceClass, str] = {
    "project_local": "workspace",
    "user_global": "user",
    "temporary": "temporary",
}


class NativeResourceSourceError(RuntimeError):
    """Stable owner-visible failure class with a finite structured reason."""

    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True, slots=True, init=False)
class NativeResourceRootHandle:
    """Opaque authority to one exact native directory identity."""

    handle_id: str
    source_class: NativeResourceSourceClass
    scope_id: ResourceSourceScope
    source_root_order: int
    root_kind: NativeResourceRootKind
    root_policy_fingerprint: str
    _root: Path = field(repr=False, compare=False)
    _device: int = field(repr=False, compare=False)
    _inode: int = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("Native Resource root handles are Host-minted")

    def policy_payload(self) -> dict[str, object]:
        return {
            "handleId": self.handle_id,
            "rootPolicyFingerprint": self.root_policy_fingerprint,
            "rootKind": self.root_kind,
            "scopeId": self.scope_id,
            "sourceClass": self.source_class,
            "sourceRootOrder": self.source_root_order,
        }

    def _verify_live_root(self) -> None:
        try:
            current = self._root.stat(follow_symlinks=False)
        except OSError as exc:
            raise NativeResourceSourceError(
                code="resource_source_discovery_failed",
                reason="root_unavailable",
            ) from exc
        if (
            not stat.S_ISDIR(current.st_mode)
            or current.st_dev != self._device
            or current.st_ino != self._inode
        ):
            raise NativeResourceSourceError(
                code="resource_source_discovery_failed",
                reason="root_identity_changed",
            )


def mint_native_resource_root_handle(
    *,
    handle_id: str,
    root: Path,
    source_class: NativeResourceSourceClass,
    root_kind: NativeResourceRootKind,
    source_root_order: int = 0,
) -> NativeResourceRootHandle:
    """Mint a contained-read handle without exposing the absolute path payload."""

    if not isinstance(handle_id, str) or not _HANDLE_ID_PATTERN.fullmatch(handle_id):
        raise ValueError("Native Resource root handle id must be opaque and path-free")
    if source_class not in _NATIVE_SCOPE:
        raise ValueError("Native Resource root source class is unsupported")
    if root_kind not in {"context", "standard", "combined"}:
        raise ValueError("Native Resource root kind is unsupported")
    if isinstance(source_root_order, bool) or not isinstance(source_root_order, int):
        raise TypeError("Native Resource root order must be an integer")
    if source_root_order < 0:
        raise ValueError("Native Resource root order cannot be negative")
    supplied = Path(root)
    if supplied.is_symlink():
        raise ValueError("Native Resource root must not be a symlink")
    try:
        resolved = supplied.resolve(strict=True)
        identity = resolved.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError("Native Resource root must be an existing directory") from exc
    if not stat.S_ISDIR(identity.st_mode):
        raise ValueError("Native Resource root must be an existing directory")
    scope_id = _NATIVE_SCOPE[source_class]
    root_identity_fingerprint = fingerprint_catalog_value(
        "loushang.native-resource-root-identity/v1",
        {
            "device": identity.st_dev,
            "inode": identity.st_ino,
            "resolvedPath": str(resolved),
        },
    )
    policy_fingerprint = fingerprint_catalog_value(
        "loushang.native-resource-root-policy/v1",
        {
            "handleId": handle_id,
            "rootIdentityFingerprint": root_identity_fingerprint,
            "rootKind": root_kind,
            "scopeId": scope_id,
            "sourceClass": source_class,
            "sourceRootOrder": source_root_order,
        },
    )
    handle = object.__new__(NativeResourceRootHandle)
    object.__setattr__(handle, "handle_id", handle_id)
    object.__setattr__(handle, "source_class", source_class)
    object.__setattr__(handle, "scope_id", scope_id)
    object.__setattr__(handle, "source_root_order", source_root_order)
    object.__setattr__(handle, "root_kind", root_kind)
    object.__setattr__(handle, "root_policy_fingerprint", policy_fingerprint)
    object.__setattr__(handle, "_root", resolved)
    object.__setattr__(handle, "_device", identity.st_dev)
    object.__setattr__(handle, "_inode", identity.st_ino)
    return handle


@dataclass(frozen=True, slots=True)
class NativeResourceDiscoveryBudget:
    maximum_entries: int = 4096
    maximum_depth: int = 8
    maximum_metadata_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for name, value in (
            ("maximum entries", self.maximum_entries),
            ("maximum depth", self.maximum_depth),
            ("maximum metadata bytes", self.maximum_metadata_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Native discovery {name} must be an integer")
            if value < 1:
                raise ValueError(f"Native discovery {name} must be positive")

    def to_payload(self) -> dict[str, int]:
        return {
            "maximumDepth": self.maximum_depth,
            "maximumEntries": self.maximum_entries,
            "maximumMetadataBytes": self.maximum_metadata_bytes,
        }


@dataclass(frozen=True, slots=True)
class NativeResourceDiscoveryRequest:
    product_id: str
    source_generation_ref: ResourceSourceGenerationRef
    root_handle_ids: tuple[str, ...]
    context_file_names: tuple[str, ...]
    budget: NativeResourceDiscoveryBudget
    request_fingerprint: str
    deadline_monotonic_ns: int | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    cancellation_probe: Callable[[], bool] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.product_id.strip():
            raise ValueError("Native discovery Product id must not be empty")
        if not isinstance(self.source_generation_ref, ResourceSourceGenerationRef):
            raise TypeError("Native discovery requires a source generation ref")
        if tuple(sorted(set(self.root_handle_ids))) != self.root_handle_ids:
            raise ValueError("Native discovery root handle ids must be canonical")
        if any(not _HANDLE_ID_PATTERN.fullmatch(item) for item in self.root_handle_ids):
            raise ValueError("Native discovery root handle id is invalid")
        if not self.context_file_names or any(
            not item or "/" in item or "\\" in item or item in {".", ".."}
            for item in self.context_file_names
        ):
            raise ValueError("Native discovery context names must be plain filenames")
        if len(set(self.context_file_names)) != len(self.context_file_names):
            raise ValueError("Native discovery context names must not repeat")
        if not isinstance(self.budget, NativeResourceDiscoveryBudget):
            raise TypeError("Native discovery requires a typed budget")
        expected = _discovery_request_fingerprint(
            product_id=self.product_id,
            source_generation_ref=self.source_generation_ref,
            root_handle_ids=self.root_handle_ids,
            context_file_names=self.context_file_names,
            budget=self.budget,
        )
        if self.request_fingerprint != expected:
            raise ValueError("Native discovery request fingerprint is invalid")
        if self.deadline_monotonic_ns is not None and (
            isinstance(self.deadline_monotonic_ns, bool)
            or not isinstance(self.deadline_monotonic_ns, int)
            or self.deadline_monotonic_ns < 0
        ):
            raise ValueError("Native discovery deadline must be monotonic nanoseconds")
        if self.cancellation_probe is not None and not callable(
            self.cancellation_probe
        ):
            raise TypeError("Native discovery cancellation probe must be callable")


def build_native_resource_discovery_request(
    *,
    product_id: str,
    source_generation_ref: ResourceSourceGenerationRef,
    root_handle_ids: tuple[str, ...],
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES,
    budget: NativeResourceDiscoveryBudget | None = None,
    deadline_monotonic_ns: int | None = None,
    cancellation_probe: Callable[[], bool] | None = None,
) -> NativeResourceDiscoveryRequest:
    effective_budget = budget or NativeResourceDiscoveryBudget()
    canonical_ids = tuple(sorted(set(root_handle_ids)))
    return NativeResourceDiscoveryRequest(
        product_id=product_id,
        source_generation_ref=source_generation_ref,
        root_handle_ids=canonical_ids,
        context_file_names=tuple(context_file_names),
        budget=effective_budget,
        request_fingerprint=_discovery_request_fingerprint(
            product_id=product_id,
            source_generation_ref=source_generation_ref,
            root_handle_ids=canonical_ids,
            context_file_names=tuple(context_file_names),
            budget=effective_budget,
        ),
        deadline_monotonic_ns=deadline_monotonic_ns,
        cancellation_probe=cancellation_probe,
    )


def _discovery_request_fingerprint(
    *,
    product_id: str,
    source_generation_ref: ResourceSourceGenerationRef,
    root_handle_ids: tuple[str, ...],
    context_file_names: tuple[str, ...],
    budget: NativeResourceDiscoveryBudget,
) -> str:
    return fingerprint_catalog_value(
        "loushang.native-resource-discovery-request/v1",
        {
            "budget": budget.to_payload(),
            "contextFileNames": list(context_file_names),
            "productId": product_id,
            "rootHandleIds": list(root_handle_ids),
            "sourceGenerationRef": source_generation_ref.to_payload(),
        },
    )


@dataclass(slots=True)
class _DiscoveryControl:
    request: NativeResourceDiscoveryRequest
    entries: int = 0
    metadata_bytes: int = 0

    def check(self, *, depth: int | None = None) -> None:
        probe = self.request.cancellation_probe
        if probe is not None and probe():
            raise asyncio.CancelledError
        deadline = self.request.deadline_monotonic_ns
        if deadline is not None and time.monotonic_ns() >= deadline:
            raise NativeResourceSourceError(
                code="resource_source_discovery_budget_exceeded",
                reason="deadline_exceeded",
            )
        if depth is not None and depth > self.request.budget.maximum_depth:
            raise NativeResourceSourceError(
                code="resource_source_discovery_budget_exceeded",
                reason="depth_exceeded",
            )

    def consume_entry(self, *, depth: int) -> None:
        self.check(depth=depth)
        self.entries += 1
        if self.entries > self.request.budget.maximum_entries:
            raise NativeResourceSourceError(
                code="resource_source_discovery_budget_exceeded",
                reason="entry_count_exceeded",
            )

    def reserve_bytes(self, length: int) -> None:
        self.check()
        if self.metadata_bytes + length > self.request.budget.maximum_metadata_bytes:
            raise NativeResourceSourceError(
                code="resource_source_discovery_budget_exceeded",
                reason="metadata_bytes_exceeded",
            )
        self.metadata_bytes += length


@dataclass(frozen=True, slots=True)
class _CachedBody:
    candidate_fingerprint: str
    content_digest: str
    body: bytes


class NativeFilesystemResourceSource:
    """One exact-generation, bounded and disposable native source payload."""

    def __init__(
        self,
        *,
        source_generation_ref: ResourceSourceGenerationRef,
        root_handles: tuple[NativeResourceRootHandle, ...],
    ) -> None:
        if not isinstance(source_generation_ref, ResourceSourceGenerationRef):
            raise TypeError("Native source requires a source generation ref")
        if any(not isinstance(item, NativeResourceRootHandle) for item in root_handles):
            raise TypeError("Native source requires Host-minted root handles")
        ids = tuple(item.handle_id for item in root_handles)
        if len(set(ids)) != len(ids):
            raise ValueError("Native source root handles must not repeat")
        self._source_generation_ref = source_generation_ref
        self._roots = {item.handle_id: item for item in root_handles}
        self._snapshot: ResourceSourceSnapshot | None = None
        self._body_cache: dict[str, _CachedBody] = {}
        self._disposed = False

    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef:
        return self._source_generation_ref

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    def discover_initial(
        self,
        request: ResourceDiscoveryRequest,
    ) -> ResourceSourceSnapshot:
        if self._disposed:
            _raise_stale("source_disposed")
        if not isinstance(request, NativeResourceDiscoveryRequest):
            raise TypeError("Native source discovery requires a typed request")
        if (
            request.product_id != self._source_generation_ref.product_id
            or request.source_generation_ref != self._source_generation_ref
        ):
            _raise_stale("foreign_source_generation")
        if set(request.root_handle_ids) - set(self._roots):
            raise NativeResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="foreign_root_handle",
            )
        if self._snapshot is not None:
            if (
                self._snapshot.discovery_request_fingerprint
                != request.request_fingerprint
            ):
                _raise_stale("discovery_request_changed")
            return self._snapshot

        control = _DiscoveryControl(request)
        candidates: list[ResourceCandidateSummary] = []
        diagnostics: list[ResourceCatalogDiagnostic] = []
        staged_bodies: dict[str, _CachedBody] = {}
        for handle_id in request.root_handle_ids:
            control.check()
            root = self._roots[handle_id]
            root._verify_live_root()
            root_candidates, root_diagnostics, root_bodies = _discover_root(
                root,
                request=request,
                control=control,
                source_generation_ref=self._source_generation_ref,
            )
            candidates.extend(root_candidates)
            diagnostics.extend(root_diagnostics)
            for locator, body in root_bodies.items():
                if locator in staged_bodies:
                    raise NativeResourceSourceError(
                        code="resource_source_snapshot_invalid",
                        reason="duplicate_opaque_locator",
                    )
                staged_bodies[locator] = body

        try:
            snapshot = build_source_snapshot(
                source_generation_ref=self._source_generation_ref,
                discovery_request_fingerprint=request.request_fingerprint,
                candidate_summaries=candidates,
                diagnostics=diagnostics,
            )
        except (TypeError, ValueError) as exc:
            raise NativeResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="snapshot_validation_failed",
            ) from exc
        self._body_cache = staged_bodies
        self._snapshot = snapshot
        return snapshot

    def load(self, handle: ResourceLoadHandle) -> ResourceBodyRead:
        if self._disposed:
            _raise_stale("source_disposed")
        if not isinstance(handle, ResourceLoadHandle):
            raise TypeError("Native source load requires a Resource load handle")
        if handle.source_generation_ref != self._source_generation_ref:
            _raise_stale("foreign_source_generation")
        cached = self._body_cache.get(handle.opaque_locator)
        if cached is None:
            raise NativeResourceSourceError(
                code="resource_body_read_failed",
                reason="unknown_opaque_locator",
            )
        if (
            cached.candidate_fingerprint != handle.candidate_fingerprint
            or cached.content_digest != handle.expected_content_digest
            or len(cached.body) != handle.expected_content_length
        ):
            raise NativeResourceSourceError(
                code="resource_body_identity_mismatch",
                reason="load_handle_identity_mismatch",
            )
        return ResourceBodyRead(
            source_generation_ref=self._source_generation_ref,
            opaque_locator=handle.opaque_locator,
            body=cached.body,
            observed_content_digest=cached.content_digest,
            observed_content_length=len(cached.body),
        )

    def dispose(self) -> None:
        self._disposed = True
        self._snapshot = None
        self._body_cache.clear()


def native_source_policy_fingerprint(
    *,
    product_id: str,
    component_binding_fingerprint: str,
    root_handles: tuple[NativeResourceRootHandle, ...],
) -> str:
    return fingerprint_catalog_value(
        "loushang.native-resource-source-policy/v1",
        {
            "componentBindingFingerprint": component_binding_fingerprint,
            "productId": product_id,
            "rootHandles": [
                handle.policy_payload()
                for handle in sorted(root_handles, key=lambda item: item.handle_id)
            ],
        },
    )


def build_native_source_generation_ref(
    *,
    source_id: str,
    product_id: str,
    runtime_id: str,
    owner_generation: int,
    producer: ResourceComponentProducer,
    component_binding_fingerprint: str,
    root_handles: tuple[NativeResourceRootHandle, ...],
) -> ResourceSourceGenerationRef:
    return ResourceSourceGenerationRef(
        source_id=source_id,
        product_id=product_id,
        generation=f"{runtime_id}:{owner_generation}",
        source_policy_fingerprint=native_source_policy_fingerprint(
            product_id=product_id,
            component_binding_fingerprint=component_binding_fingerprint,
            root_handles=root_handles,
        ),
        producer=producer,
    )


def _discover_root(
    root: NativeResourceRootHandle,
    *,
    request: NativeResourceDiscoveryRequest,
    control: _DiscoveryControl,
    source_generation_ref: ResourceSourceGenerationRef,
) -> tuple[
    list[ResourceCandidateSummary],
    list[ResourceCatalogDiagnostic],
    dict[str, _CachedBody],
]:
    discovered: list[tuple[str, NativeDescriptor, bytes | None, str]] = []
    diagnostics: list[ResourceCatalogDiagnostic] = []
    if root.root_kind in {"context", "combined"}:
        _discover_contexts(root, request, control, discovered, diagnostics)
    if root.root_kind in {"standard", "combined"}:
        _discover_prompts(root, control, discovered, diagnostics)
        _discover_skills(root, control, discovered, diagnostics)
        _discover_extensions(root, control, discovered, diagnostics)
        _discover_themes(root, control, discovered, diagnostics)
    diagnostics = [
        replace(item, source_id=source_generation_ref.source_id) for item in diagnostics
    ]

    candidates: list[ResourceCandidateSummary] = []
    bodies: dict[str, _CachedBody] = {}
    for resource_kind, descriptor, body, relative_path in discovered:
        candidate = _build_native_candidate(
            resource_kind=resource_kind,
            descriptor=descriptor,
            body=body,
            relative_path=relative_path,
            root=root,
            request=request,
            source_generation_ref=source_generation_ref,
        )
        candidates.append(candidate)
        if body is not None:
            assert candidate.expected_content_digest is not None
            bodies[candidate.opaque_locator] = _CachedBody(
                candidate_fingerprint=candidate.candidate_fingerprint,
                content_digest=candidate.expected_content_digest,
                body=body,
            )
    return candidates, diagnostics, bodies


def _discover_contexts(
    root: NativeResourceRootHandle,
    request: NativeResourceDiscoveryRequest,
    control: _DiscoveryControl,
    discovered: list[tuple[str, NativeDescriptor, bytes | None, str]],
    diagnostics: list[ResourceCatalogDiagnostic],
) -> None:
    for filename in request.context_file_names:
        path = root._root / filename
        if path.is_symlink():
            _raise_discovery("symlink_not_allowed")
        if not _is_regular_file(path, root=root):
            continue
        control.consume_entry(depth=0)
        body = _stable_read(path, root=root, control=control)
        try:
            text = body.decode("utf-8").strip()
        except UnicodeDecodeError:
            diagnostics.append(_source_diagnostic(root, "invalid_context_encoding"))
            return
        prompt_kind = "agents_md" if filename.upper() == "AGENTS.MD" else "claude_md"
        source_prefix = "user" if root.source_class == "user_global" else "project"
        context_name = "agents" if prompt_kind == "agents_md" else "claude"
        discovered.append(
            (
                "context",
                PromptFragmentDescriptor(
                    name=filename,
                    source_path=path,
                    text=text,
                    id=f"{source_prefix}.{context_name}",
                    canonical_name=filename,
                    prompt_kind=prompt_kind,
                    source_kind=root.source_class,
                    source_scope=root.scope_id,
                    source=SOURCE_LABEL[root.source_class],
                    source_root=root._root,
                    source_root_order=root.source_root_order,
                ),
                body,
                filename,
            )
        )
        return


def _discover_prompts(
    root: NativeResourceRootHandle,
    control: _DiscoveryControl,
    discovered: list[tuple[str, NativeDescriptor, bytes | None, str]],
    diagnostics: list[ResourceCatalogDiagnostic],
) -> None:
    directory = root._root / "prompts"
    for entry in _directory_entries(directory, root=root, control=control, depth=1):
        relative = entry.relative_to(root._root).as_posix()
        if not _is_regular_file(entry, root=root) or entry.suffix != ".md":
            diagnostics.append(_source_diagnostic(root, "unsupported_prompt_entry"))
            continue
        body = _stable_read(entry, root=root, control=control)
        try:
            text = body.decode("utf-8").strip()
        except UnicodeDecodeError:
            diagnostics.append(_source_diagnostic(root, "invalid_prompt_encoding"))
            continue
        descriptor, drafts = _prompt_descriptor_from_text(
            name=entry.stem,
            source_path=entry,
            text=text,
            canonical_name=entry.name,
            source_kind=root.source_class,
            source_scope=root.scope_id,
            source=SOURCE_LABEL[root.source_class],
            source_root=directory,
            source_root_order=root.source_root_order,
        )
        if descriptor is None:
            diagnostics.extend(_draft_diagnostics(root, drafts))
            continue
        if drafts:
            descriptor = replace(descriptor, diagnostics=tuple(drafts))
        discovered.append(("prompt", descriptor, body, relative))


def _discover_skills(
    root: NativeResourceRootHandle,
    control: _DiscoveryControl,
    discovered: list[tuple[str, NativeDescriptor, bytes | None, str]],
    diagnostics: list[ResourceCatalogDiagnostic],
) -> None:
    skills_root = root._root / "skills"
    if skills_root.is_symlink():
        _raise_discovery("symlink_not_allowed")
    if not _is_contained_directory(skills_root, root=root):
        return
    _discover_skill_directory(
        skills_root,
        skills_root=skills_root,
        root=root,
        control=control,
        depth=1,
        ignore_patterns=(),
        discovered=discovered,
        diagnostics=diagnostics,
    )


def _discover_skill_directory(
    current: Path,
    *,
    skills_root: Path,
    root: NativeResourceRootHandle,
    control: _DiscoveryControl,
    depth: int,
    ignore_patterns: tuple[str, ...],
    discovered: list[tuple[str, NativeDescriptor, bytes | None, str]],
    diagnostics: list[ResourceCatalogDiagnostic],
) -> None:
    control.check(depth=depth)
    entries = _directory_entries(current, root=root, control=control, depth=depth)
    active_ignore_patterns = (
        *ignore_patterns,
        *_read_native_skill_ignore_patterns(
            entries,
            current=current,
            skills_root=skills_root,
            root=root,
            control=control,
            diagnostics=diagnostics,
        ),
    )
    skill_file = next(
        (
            entry
            for entry in entries
            if entry.name == "SKILL.md" and _is_regular_file(entry, root=root)
        ),
        None,
    )
    if skill_file is not None:
        body = _stable_read(skill_file, root=root, control=control)
        try:
            content = body.decode("utf-8").strip()
        except UnicodeDecodeError:
            diagnostics.append(_source_diagnostic(root, "invalid_skill_encoding"))
            return
        descriptor, drafts = _skill_descriptor_from_text(
            parent_name=current.name,
            source_path=skill_file,
            content=content,
            canonical_name=skill_file.relative_to(skills_root).as_posix(),
            source_kind=root.source_class,
            source_scope=root.scope_id,
            source=SOURCE_LABEL[root.source_class],
            source_root=skills_root,
            source_root_order=root.source_root_order,
        )
        if descriptor is None:
            diagnostics.extend(_draft_diagnostics(root, drafts))
            return
        if drafts:
            descriptor = replace(descriptor, diagnostics=tuple(drafts))
        discovered.append(
            (
                "skill",
                descriptor,
                body,
                skill_file.relative_to(root._root).as_posix(),
            )
        )
        return

    for entry in entries:
        if entry.is_file() and current == skills_root:
            if entry.name not in IGNORE_FILE_NAMES:
                diagnostics.append(_source_diagnostic(root, "unsupported_skill_entry"))
            continue
        if (
            not _is_contained_directory(entry, root=root)
            or entry.name.startswith(".")
            or entry.name == "node_modules"
        ):
            continue
        if is_skill_path_ignored(
            entry,
            root_dir=skills_root,
            patterns=active_ignore_patterns,
        ):
            continue
        _discover_skill_directory(
            entry,
            skills_root=skills_root,
            root=root,
            control=control,
            depth=depth + 1,
            ignore_patterns=active_ignore_patterns,
            discovered=discovered,
            diagnostics=diagnostics,
        )


def _read_native_skill_ignore_patterns(
    entries: tuple[Path, ...],
    *,
    current: Path,
    skills_root: Path,
    root: NativeResourceRootHandle,
    control: _DiscoveryControl,
    diagnostics: list[ResourceCatalogDiagnostic],
) -> tuple[str, ...]:
    relative_prefix = current.relative_to(skills_root).as_posix()
    prefix = "" if relative_prefix == "." else relative_prefix
    patterns: list[str] = []
    for ignore_file in entries:
        if ignore_file.name not in IGNORE_FILE_NAMES or not _is_regular_file(
            ignore_file,
            root=root,
        ):
            continue
        body = _stable_read(ignore_file, root=root, control=control)
        try:
            lines = body.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            diagnostics.append(
                _source_diagnostic(root, "invalid_skill_ignore_encoding")
            )
            continue
        for raw_line in lines:
            pattern = normalize_skill_ignore_pattern(raw_line, prefix=prefix)
            if pattern is not None:
                patterns.append(pattern)
    return tuple(patterns)


def _discover_extensions(
    root: NativeResourceRootHandle,
    control: _DiscoveryControl,
    discovered: list[tuple[str, NativeDescriptor, bytes | None, str]],
    diagnostics: list[ResourceCatalogDiagnostic],
) -> None:
    directory = root._root / "extensions"
    for entry in _directory_entries(directory, root=root, control=control, depth=1):
        entry_path: Path | None = None
        if _is_regular_file(entry, root=root) and entry.suffix == ".py":
            entry_path = entry
        elif _is_contained_directory(entry, root=root):
            for filename in ("extension.py", "__init__.py"):
                candidate = entry / filename
                if _is_regular_file(candidate, root=root):
                    control.consume_entry(depth=2)
                    entry_path = candidate
                    break
            if entry_path is None:
                diagnostics.append(_source_diagnostic(root, "missing_extension_entry"))
                continue
        else:
            diagnostics.append(_source_diagnostic(root, "unsupported_extension_entry"))
            continue
        discovered.append(
            (
                "extension",
                ExtensionDescriptor(
                    name=entry.stem if entry.is_file() else entry.name,
                    source_path=entry,
                    entry_path=entry_path,
                    canonical_name=entry.name,
                    source_kind=root.source_class,
                    source_scope=root.scope_id,
                    source=SOURCE_LABEL[root.source_class],
                    source_root=directory,
                    source_root_order=root.source_root_order,
                ),
                None,
                entry.relative_to(root._root).as_posix(),
            )
        )


def _discover_themes(
    root: NativeResourceRootHandle,
    control: _DiscoveryControl,
    discovered: list[tuple[str, NativeDescriptor, bytes | None, str]],
    diagnostics: list[ResourceCatalogDiagnostic],
) -> None:
    directory = root._root / "themes"
    for entry in _directory_entries(directory, root=root, control=control, depth=1):
        relative = entry.relative_to(root._root).as_posix()
        if _is_contained_directory(entry, root=root):
            discovered.append(
                (
                    "theme",
                    ThemeDescriptor(
                        name=entry.name,
                        source_path=entry,
                        canonical_name=entry.name,
                        source_kind=root.source_class,
                        source_scope=root.scope_id,
                        source=SOURCE_LABEL[root.source_class],
                        source_root=directory,
                        source_root_order=root.source_root_order,
                    ),
                    None,
                    relative,
                )
            )
            continue
        if not _is_regular_file(entry, root=root) or entry.suffix != ".json":
            diagnostics.append(_source_diagnostic(root, "unsupported_theme_entry"))
            continue
        body = _stable_read(entry, root=root, control=control)
        try:
            content = body.decode("utf-8")
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            diagnostics.append(_source_diagnostic(root, "invalid_theme_json"))
            continue
        if not isinstance(payload, dict):
            diagnostics.append(_source_diagnostic(root, "invalid_theme_schema"))
            continue
        discovered.append(
            (
                "theme",
                ThemeDescriptor(
                    name=entry.stem,
                    content=content,
                    source_path=entry,
                    canonical_name=entry.name,
                    source_kind=root.source_class,
                    source_scope=root.scope_id,
                    source=SOURCE_LABEL[root.source_class],
                    source_root=directory,
                    source_root_order=root.source_root_order,
                ),
                body,
                relative,
            )
        )


def _directory_entries(
    directory: Path,
    *,
    root: NativeResourceRootHandle,
    control: _DiscoveryControl,
    depth: int,
) -> tuple[Path, ...]:
    control.check(depth=depth)
    if directory.is_symlink():
        _raise_discovery("symlink_not_allowed")
    if not _is_contained_directory(directory, root=root):
        return ()
    root._verify_live_root()
    try:
        resolved = directory.resolve(strict=True)
        resolved.relative_to(root._root)
        if resolved != directory:
            _raise_discovery("symlink_not_allowed")
        before = directory.stat(follow_symlinks=False)
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        after = directory.stat(follow_symlinks=False)
    except OSError as exc:
        raise NativeResourceSourceError(
            code="resource_source_discovery_failed",
            reason="directory_scan_failed",
        ) from exc
    except ValueError:
        _raise_discovery("locator_escape")
    if (
        not stat.S_ISDIR(before.st_mode)
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        _raise_discovery("directory_changed_during_discovery")
    paths: list[Path] = []
    for entry in entries:
        control.consume_entry(depth=depth)
        if entry.is_symlink():
            _raise_discovery("symlink_not_allowed")
        paths.append(Path(entry.path))
    return tuple(paths)


def _stable_read(
    path: Path,
    *,
    root: NativeResourceRootHandle,
    control: _DiscoveryControl,
) -> bytes:
    root._verify_live_root()
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root._root)
    except (OSError, ValueError) as exc:
        raise NativeResourceSourceError(
            code="resource_source_discovery_failed",
            reason="locator_escape",
        ) from exc
    if resolved != path:
        raise NativeResourceSourceError(
            code="resource_source_discovery_failed",
            reason="symlink_not_allowed",
        )
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise NativeResourceSourceError(
                    code="resource_source_discovery_failed",
                    reason="body_not_regular_file",
                )
            control.reserve_bytes(before.st_size)
            chunks: list[bytes] = []
            remaining = before.st_size + 1
            while remaining:
                control.check()
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            body = b"".join(chunks)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except NativeResourceSourceError:
        raise
    except OSError as exc:
        raise NativeResourceSourceError(
            code="resource_source_discovery_failed",
            reason="stable_read_failed",
        ) from exc
    if (
        len(body) != before.st_size
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise NativeResourceSourceError(
            code="resource_source_discovery_failed",
            reason="body_changed_during_discovery",
        )
    return body


def _is_regular_file(path: Path, *, root: NativeResourceRootHandle) -> bool:
    try:
        path.relative_to(root._root)
        value = path.stat(follow_symlinks=False)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(value.st_mode)


def _is_contained_directory(path: Path, *, root: NativeResourceRootHandle) -> bool:
    try:
        path.relative_to(root._root)
        value = path.stat(follow_symlinks=False)
    except (OSError, ValueError):
        return False
    return stat.S_ISDIR(value.st_mode)


def _build_native_candidate(
    *,
    resource_kind: str,
    descriptor: NativeDescriptor,
    body: bytes | None,
    relative_path: str,
    root: NativeResourceRootHandle,
    request: NativeResourceDiscoveryRequest,
    source_generation_ref: ResourceSourceGenerationRef,
) -> ResourceCandidateSummary:
    identity = ResourceIdentity(
        resource_kind=resource_kind,
        schema_id=f"loushang.resource.{resource_kind}",
        schema_version=1,
        public_id=descriptor.id or descriptor.name,
    )
    locator = f"{root.handle_id}/{relative_path}"
    digest = hashlib.sha256(body).hexdigest() if body is not None else None
    length = len(body) if body is not None else None
    media_type = (
        NO_BODY_MEDIA_TYPE
        if body is None
        else "application/json"
        if resource_kind == "theme"
        else "text/markdown"
    )
    diagnostics = tuple(
        sorted(
            (
                ResourceCatalogDiagnostic(
                    code="resource_source_discovery_failed",
                    reason=draft.code,
                    identity=identity,
                    source_id=source_generation_ref.source_id,
                )
                for draft in descriptor.diagnostics
            ),
            key=lambda item: item.canonical_sort_key(),
        )
    )
    model_invocable = not isinstance(
        descriptor, ExtensionDescriptor | ThemeDescriptor
    ) and not (
        isinstance(descriptor, SkillDescriptor) and descriptor.disable_model_invocation
    )
    return build_candidate_summary(
        identity=identity,
        canonical_name=descriptor.canonical_name or descriptor.name,
        description=getattr(descriptor, "description", None),
        media_type=media_type,
        invocation_policy=ResourceInvocationPolicy(
            enabled=descriptor.enabled,
            model_invocable=model_invocable,
            reason="native_source_discovery",
        ),
        source_generation_ref=source_generation_ref,
        source_class=root.source_class,
        scope_id=root.scope_id,
        source_root_order=root.source_root_order,
        content_origin=NativeHostOrigin(
            host_root_handle_id=root.handle_id,
            root_policy_fingerprint=root.root_policy_fingerprint,
            workspace_or_user_scope=_ORIGIN_SCOPE[root.source_class],
        ),
        opaque_locator=locator,
        discovery_fingerprint=fingerprint_catalog_value(
            "loushang.native-resource-discovery/v1",
            {
                "bodyDigest": digest,
                "bodyLength": length,
                "discoveryRequestFingerprint": request.request_fingerprint,
                "identity": identity.to_payload(),
                "opaqueLocator": locator,
                "rootPolicyFingerprint": root.root_policy_fingerprint,
            },
        ),
        expected_content_digest=digest,
        expected_content_length=length,
        diagnostics=diagnostics,
    )


def _source_diagnostic(
    root: NativeResourceRootHandle,
    reason: str,
) -> ResourceCatalogDiagnostic:
    return ResourceCatalogDiagnostic(
        code="resource_source_discovery_failed",
        reason=reason,
        source_id=None,
        details=(("root_handle_id", root.handle_id),),
    )


def _draft_diagnostics(
    root: NativeResourceRootHandle,
    drafts: list[DiagnosticDraft],
) -> list[ResourceCatalogDiagnostic]:
    return [_source_diagnostic(root, draft.code) for draft in drafts]


def _raise_stale(reason: str) -> None:
    raise NativeResourceSourceError(
        code="resource_catalog_generation_stale",
        reason=reason,
    )


def _raise_discovery(reason: str) -> None:
    raise NativeResourceSourceError(
        code="resource_source_discovery_failed",
        reason=reason,
    )


__all__ = [
    "NativeFilesystemResourceSource",
    "NativeResourceDiscoveryBudget",
    "NativeResourceDiscoveryRequest",
    "NativeResourceRootHandle",
    "NativeResourceRootKind",
    "NativeResourceSourceClass",
    "NativeResourceSourceError",
    "build_native_resource_discovery_request",
    "build_native_source_generation_ref",
    "mint_native_resource_root_handle",
    "native_source_policy_fingerprint",
]
