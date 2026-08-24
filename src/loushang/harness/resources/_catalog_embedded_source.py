"""Immutable embedded/OEM ``resource.source`` adapter for RCP3 shadow use."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import resources as importlib_resources
from importlib.resources.abc import Traversable
from pathlib import PurePosixPath
from types import MappingProxyType

from loushang.harness.resources._catalog_records import (
    NO_BODY_MEDIA_TYPE,
    EmbeddedOemOrigin,
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
from loushang.harness.resources._resource_item_projection import project_catalog_item
from loushang.harness.resources.builtin import BuiltInResourcePackage


class EmbeddedResourceSourceError(RuntimeError):
    """Finite owner-visible failure from an immutable embedded collection."""

    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True, slots=True, init=False)
class EmbeddedResourceCollectionHandle:
    """Host-minted lease over one eagerly captured immutable file collection."""

    collection_id: str
    embedded_revision: str
    collection_content_digest: str
    source_root_order: int
    handle_id: str
    _owned_files: dict[str, bytes] = field(repr=False, compare=False)
    _files: Mapping[str, bytes] = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("Embedded Resource collection handles are Host-minted")

    @property
    def closed(self) -> bool:
        return self._closed

    def policy_payload(self) -> dict[str, object]:
        return {
            "collectionContentDigest": self.collection_content_digest,
            "collectionId": self.collection_id,
            "embeddedRevision": self.embedded_revision,
            "handleId": self.handle_id,
            "sourceRootOrder": self.source_root_order,
        }

    def read_bytes(self, relative_path: str | PurePosixPath) -> bytes:
        if self._closed:
            _raise_stale("collection_handle_closed")
        path = _canonical_relative_path(relative_path)
        try:
            return self._files[path.as_posix()]
        except KeyError as exc:
            raise EmbeddedResourceSourceError(
                code="resource_body_read_failed",
                reason="unknown_embedded_locator",
            ) from exc

    def file_paths(self) -> tuple[str, ...]:
        if self._closed:
            _raise_stale("collection_handle_closed")
        return tuple(self._files)

    def close(self) -> None:
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        self._owned_files.clear()


def mint_embedded_resource_collection_handle(
    *,
    collection_id: str,
    embedded_revision: str,
    files: Mapping[str, bytes],
    source_root_order: int = 0,
) -> EmbeddedResourceCollectionHandle:
    """Copy Product-selected package bytes into a path-free immutable authority."""

    if not isinstance(collection_id, str) or not collection_id.strip():
        raise ValueError("Embedded collection id must not be empty")
    if not isinstance(embedded_revision, str) or not embedded_revision.strip():
        raise ValueError("Embedded revision must not be empty")
    if isinstance(source_root_order, bool) or not isinstance(source_root_order, int):
        raise TypeError("Embedded source root order must be an integer")
    if source_root_order < 0:
        raise ValueError("Embedded source root order cannot be negative")
    normalized: dict[str, bytes] = {}
    for raw_path, raw_body in files.items():
        path = _canonical_relative_path(raw_path).as_posix()
        if not isinstance(raw_body, bytes):
            raise TypeError("Embedded Resource bodies must be immutable bytes")
        if path in normalized:
            raise ValueError("Embedded Resource paths must not repeat")
        normalized[path] = bytes(raw_body)
    ordered = dict(sorted(normalized.items()))
    digest = fingerprint_catalog_value(
        "loushang.embedded-resource-collection/v1",
        {
            "collectionId": collection_id,
            "embeddedRevision": embedded_revision,
            "files": [
                {
                    "contentDigest": hashlib.sha256(body).hexdigest(),
                    "contentLength": len(body),
                    "relativePath": path,
                }
                for path, body in ordered.items()
            ],
        },
    )
    handle = object.__new__(EmbeddedResourceCollectionHandle)
    object.__setattr__(handle, "collection_id", collection_id)
    object.__setattr__(handle, "embedded_revision", embedded_revision)
    object.__setattr__(handle, "collection_content_digest", digest)
    object.__setattr__(handle, "source_root_order", source_root_order)
    object.__setattr__(
        handle,
        "handle_id",
        fingerprint_catalog_value(
            "loushang.embedded-resource-handle/v1",
            {
                "collectionContentDigest": digest,
                "collectionId": collection_id,
                "embeddedRevision": embedded_revision,
                "sourceRootOrder": source_root_order,
            },
        ),
    )
    object.__setattr__(handle, "_owned_files", ordered)
    object.__setattr__(handle, "_files", MappingProxyType(ordered))
    object.__setattr__(handle, "_closed", False)
    return handle


def capture_built_in_resource_package(
    package: BuiltInResourcePackage,
    *,
    embedded_revision: str,
    source_root_order: int = 0,
) -> EmbeddedResourceCollectionHandle:
    """Capture import-package bytes once; discovery never reopens the import path."""

    if not isinstance(package, BuiltInResourcePackage):
        raise TypeError("Embedded capture requires a built-in Resource package")
    try:
        root = importlib_resources.files(package.package)
        captured: dict[str, bytes] = {}
        _capture_traversable(root, prefix=PurePosixPath(), captured=captured)
    except (ModuleNotFoundError, OSError) as exc:
        raise ValueError("Built-in Resource package could not be captured") from exc
    return mint_embedded_resource_collection_handle(
        collection_id=package.name,
        embedded_revision=embedded_revision,
        files=captured,
        source_root_order=source_root_order,
    )


def _capture_traversable(
    current: Traversable,
    *,
    prefix: PurePosixPath,
    captured: dict[str, bytes],
) -> None:
    for entry in sorted(current.iterdir(), key=lambda item: item.name):
        if entry.name == "__pycache__":
            continue
        relative = prefix / entry.name
        if entry.is_dir():
            _capture_traversable(entry, prefix=relative, captured=captured)
        elif entry.is_file():
            captured[relative.as_posix()] = entry.read_bytes()


@dataclass(frozen=True, slots=True)
class EmbeddedResourceDiscoveryBudget:
    maximum_items: int = 4096
    maximum_metadata_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for name, value in (
            ("items", self.maximum_items),
            ("metadata bytes", self.maximum_metadata_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Embedded discovery {name} must be an integer")
            if value < 1:
                raise ValueError(f"Embedded discovery {name} must be positive")

    def to_payload(self) -> dict[str, int]:
        return {
            "maximumItems": self.maximum_items,
            "maximumMetadataBytes": self.maximum_metadata_bytes,
        }


@dataclass(frozen=True, slots=True)
class EmbeddedResourceDiscoveryRequest:
    product_id: str
    source_generation_ref: ResourceSourceGenerationRef
    collection_handle_ids: tuple[str, ...]
    budget: EmbeddedResourceDiscoveryBudget
    request_fingerprint: str
    deadline_monotonic_ns: int | None = field(default=None, repr=False, compare=False)
    cancellation_probe: Callable[[], bool] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.product_id.strip():
            raise ValueError("Embedded discovery Product id must not be empty")
        if not isinstance(self.source_generation_ref, ResourceSourceGenerationRef):
            raise TypeError("Embedded discovery requires a source generation ref")
        if tuple(sorted(set(self.collection_handle_ids))) != self.collection_handle_ids:
            raise ValueError("Embedded collection handles must be canonical")
        if not isinstance(self.budget, EmbeddedResourceDiscoveryBudget):
            raise TypeError("Embedded discovery requires a typed budget")
        expected = _request_fingerprint(
            product_id=self.product_id,
            source_generation_ref=self.source_generation_ref,
            collection_handle_ids=self.collection_handle_ids,
            budget=self.budget,
        )
        if self.request_fingerprint != expected:
            raise ValueError("Embedded discovery request fingerprint is invalid")
        if self.deadline_monotonic_ns is not None and (
            isinstance(self.deadline_monotonic_ns, bool)
            or not isinstance(self.deadline_monotonic_ns, int)
            or self.deadline_monotonic_ns < 0
        ):
            raise ValueError(
                "Embedded discovery deadline must be monotonic nanoseconds"
            )
        if self.cancellation_probe is not None and not callable(
            self.cancellation_probe
        ):
            raise TypeError("Embedded discovery cancellation probe must be callable")


def build_embedded_resource_discovery_request(
    *,
    product_id: str,
    source_generation_ref: ResourceSourceGenerationRef,
    collection_handle_ids: tuple[str, ...],
    budget: EmbeddedResourceDiscoveryBudget | None = None,
    deadline_monotonic_ns: int | None = None,
    cancellation_probe: Callable[[], bool] | None = None,
) -> EmbeddedResourceDiscoveryRequest:
    effective_budget = budget or EmbeddedResourceDiscoveryBudget()
    canonical = tuple(sorted(set(collection_handle_ids)))
    return EmbeddedResourceDiscoveryRequest(
        product_id=product_id,
        source_generation_ref=source_generation_ref,
        collection_handle_ids=canonical,
        budget=effective_budget,
        request_fingerprint=_request_fingerprint(
            product_id=product_id,
            source_generation_ref=source_generation_ref,
            collection_handle_ids=canonical,
            budget=effective_budget,
        ),
        deadline_monotonic_ns=deadline_monotonic_ns,
        cancellation_probe=cancellation_probe,
    )


@dataclass(frozen=True, slots=True)
class _EmbeddedItem:
    resource_kind: str
    logical_path: PurePosixPath
    body_path: PurePosixPath | None
    fallback_public_id: str
    media_type: str


@dataclass(frozen=True, slots=True)
class _EmbeddedBody:
    body: bytes
    candidate_fingerprint: str
    content_digest: str


@dataclass(slots=True)
class _DiscoveryControl:
    request: EmbeddedResourceDiscoveryRequest
    item_count: int = 0
    metadata_bytes: int = 0

    def consume(self, *, metadata_bytes: int) -> None:
        probe = self.request.cancellation_probe
        if probe is not None and probe():
            raise asyncio.CancelledError
        deadline = self.request.deadline_monotonic_ns
        if deadline is not None and time.monotonic_ns() >= deadline:
            _raise_budget("deadline_exceeded")
        self.item_count += 1
        if self.item_count > self.request.budget.maximum_items:
            _raise_budget("item_count_exceeded")
        if (
            self.metadata_bytes + metadata_bytes
            > self.request.budget.maximum_metadata_bytes
        ):
            _raise_budget("metadata_bytes_exceeded")
        self.metadata_bytes += metadata_bytes


class EmbeddedOemResourceSource:
    """One disposable generation over immutable embedded collection handles."""

    def __init__(
        self,
        *,
        source_generation_ref: ResourceSourceGenerationRef,
        collections: tuple[EmbeddedResourceCollectionHandle, ...],
    ) -> None:
        if not isinstance(source_generation_ref, ResourceSourceGenerationRef):
            raise TypeError("Embedded source requires a source generation ref")
        if any(
            not isinstance(item, EmbeddedResourceCollectionHandle)
            for item in collections
        ):
            raise TypeError("Embedded source requires collection handles")
        ordered = tuple(sorted(collections, key=lambda item: item.handle_id))
        handle_ids = tuple(item.handle_id for item in ordered)
        if len(set(handle_ids)) != len(handle_ids):
            raise ValueError("Embedded collection handles must not repeat")
        if any(item.closed for item in ordered):
            raise ValueError("Embedded collection handles must be live")
        self._source_generation_ref = source_generation_ref
        self._collections = {item.handle_id: item for item in ordered}
        self._snapshot: ResourceSourceSnapshot | None = None
        self._bodies: dict[str, _EmbeddedBody] = {}
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
        if not isinstance(request, EmbeddedResourceDiscoveryRequest):
            raise TypeError("Embedded source discovery requires a typed request")
        if (
            request.product_id != self._source_generation_ref.product_id
            or request.source_generation_ref != self._source_generation_ref
        ):
            _raise_stale("foreign_source_generation")
        if request.collection_handle_ids != tuple(sorted(self._collections)):
            raise EmbeddedResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="collection_set_mismatch",
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
        bodies: dict[str, _EmbeddedBody] = {}
        for handle_id in request.collection_handle_ids:
            collection = self._collections[handle_id]
            for item in _collection_items(collection):
                body = (
                    collection.read_bytes(item.body_path)
                    if item.body_path is not None
                    else None
                )
                metadata_length = (
                    len(body)
                    if body is not None and item.resource_kind in {"prompt", "skill"}
                    else 0
                )
                control.consume(metadata_bytes=metadata_length)
                projection = project_catalog_item(
                    resource_kind=item.resource_kind,
                    logical_path=item.logical_path,
                    body=body,
                    fallback_public_id=item.fallback_public_id,
                    source_kind="built_in",
                    source_scope="builtin",
                    source_label="immutable_embedded",
                    source_root_order=collection.source_root_order,
                )
                if projection is None or not projection.valid:
                    diagnostics.extend(
                        _embedded_diagnostics(
                            collection=collection,
                            logical_path=item.logical_path,
                            reasons=(
                                projection.diagnostic_reasons
                                if projection is not None
                                else ("missing_resource_body",)
                            ),
                            source_generation_ref=self._source_generation_ref,
                        )
                    )
                    continue
                identity = ResourceIdentity(
                    resource_kind=item.resource_kind,
                    schema_id=f"loushang.resource.{item.resource_kind}",
                    schema_version=1,
                    public_id=projection.public_id,
                )
                digest = hashlib.sha256(body).hexdigest() if body is not None else None
                length = len(body) if body is not None else None
                opaque_locator = f"{collection.handle_id}/{item.logical_path}"
                candidate = build_candidate_summary(
                    identity=identity,
                    canonical_name=projection.canonical_name,
                    description=projection.description,
                    media_type=item.media_type
                    if body is not None
                    else NO_BODY_MEDIA_TYPE,
                    invocation_policy=ResourceInvocationPolicy(
                        enabled=True,
                        model_invocable=projection.model_invocable,
                        reason="immutable_embedded_resource",
                    ),
                    source_generation_ref=self._source_generation_ref,
                    source_class="built_in",
                    scope_id="builtin",
                    source_root_order=collection.source_root_order,
                    content_origin=EmbeddedOemOrigin(
                        embedded_collection_id=collection.collection_id,
                        embedded_revision=collection.embedded_revision,
                        collection_content_digest=collection.collection_content_digest,
                    ),
                    opaque_locator=opaque_locator,
                    discovery_fingerprint=fingerprint_catalog_value(
                        "loushang.embedded-resource-discovery/v1",
                        {
                            "bodyDigest": digest,
                            "bodyLength": length,
                            "collectionContentDigest": collection.collection_content_digest,
                            "discoveryRequestFingerprint": request.request_fingerprint,
                            "identity": identity.to_payload(),
                            "opaqueLocator": opaque_locator,
                        },
                    ),
                    expected_content_digest=digest,
                    expected_content_length=length,
                    diagnostics=_embedded_diagnostics(
                        collection=collection,
                        logical_path=item.logical_path,
                        reasons=projection.diagnostic_reasons,
                        source_generation_ref=self._source_generation_ref,
                        identity=identity,
                    ),
                )
                candidates.append(candidate)
                if body is not None:
                    assert digest is not None
                    bodies[opaque_locator] = _EmbeddedBody(
                        body=body,
                        candidate_fingerprint=candidate.candidate_fingerprint,
                        content_digest=digest,
                    )
        try:
            snapshot = build_source_snapshot(
                source_generation_ref=self._source_generation_ref,
                discovery_request_fingerprint=request.request_fingerprint,
                candidate_summaries=candidates,
                diagnostics=diagnostics,
            )
        except (TypeError, ValueError) as exc:
            raise EmbeddedResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="snapshot_validation_failed",
            ) from exc
        self._snapshot = snapshot
        self._bodies = bodies
        return snapshot

    def load(self, handle: ResourceLoadHandle) -> ResourceBodyRead:
        if self._disposed:
            _raise_stale("source_disposed")
        if not isinstance(handle, ResourceLoadHandle):
            raise TypeError("Embedded source load requires a Resource load handle")
        if handle.source_generation_ref != self._source_generation_ref:
            _raise_stale("foreign_source_generation")
        cached = self._bodies.get(handle.opaque_locator)
        if cached is None:
            raise EmbeddedResourceSourceError(
                code="resource_body_read_failed",
                reason="unknown_opaque_locator",
            )
        if (
            cached.candidate_fingerprint != handle.candidate_fingerprint
            or cached.content_digest != handle.expected_content_digest
            or len(cached.body) != handle.expected_content_length
        ):
            raise EmbeddedResourceSourceError(
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
        if self._disposed:
            return
        self._disposed = True
        for collection in self._collections.values():
            collection.close()
        self._collections.clear()
        self._bodies.clear()
        self._snapshot = None


def embedded_source_policy_fingerprint(
    *,
    product_id: str,
    component_binding_fingerprint: str,
    collections: tuple[EmbeddedResourceCollectionHandle, ...],
) -> str:
    return fingerprint_catalog_value(
        "loushang.embedded-resource-source-policy/v1",
        {
            "collections": [
                item.policy_payload()
                for item in sorted(collections, key=lambda value: value.handle_id)
            ],
            "componentBindingFingerprint": component_binding_fingerprint,
            "productId": product_id,
        },
    )


def build_embedded_source_generation_ref(
    *,
    source_id: str,
    product_id: str,
    runtime_id: str,
    owner_generation: int,
    producer: ResourceComponentProducer,
    component_binding_fingerprint: str,
    collections: tuple[EmbeddedResourceCollectionHandle, ...],
) -> ResourceSourceGenerationRef:
    return ResourceSourceGenerationRef(
        source_id=source_id,
        product_id=product_id,
        generation=f"{runtime_id}:{owner_generation}",
        source_policy_fingerprint=embedded_source_policy_fingerprint(
            product_id=product_id,
            component_binding_fingerprint=component_binding_fingerprint,
            collections=collections,
        ),
        producer=producer,
    )


def _collection_items(
    collection: EmbeddedResourceCollectionHandle,
) -> tuple[_EmbeddedItem, ...]:
    paths = tuple(PurePosixPath(item) for item in collection.file_paths())
    path_set = set(paths)
    items: list[_EmbeddedItem] = []
    for path in paths:
        parts = path.parts
        if len(parts) == 2 and parts[0] == "prompts" and path.suffix == ".md":
            items.append(
                _EmbeddedItem("prompt", path, path, path.stem, "text/markdown")
            )
        elif len(parts) == 3 and parts[0] == "skills" and path.name == "SKILL.md":
            items.append(
                _EmbeddedItem("skill", path, path, path.parent.name, "text/markdown")
            )
        elif len(parts) == 2 and parts[0] == "themes":
            items.append(
                _EmbeddedItem("theme", path, path, path.stem, "application/json")
            )
        elif len(parts) == 2 and parts[0] == "extensions" and path.suffix == ".py":
            items.append(
                _EmbeddedItem("extension", path, None, path.stem, NO_BODY_MEDIA_TYPE)
            )
        elif (
            len(parts) == 3
            and parts[0] == "extensions"
            and path.name in {"extension.py", "__init__.py"}
            and (
                path.name == "extension.py"
                or path.parent / "extension.py" not in path_set
            )
        ):
            items.append(
                _EmbeddedItem(
                    "extension", path, None, path.parent.name, NO_BODY_MEDIA_TYPE
                )
            )
    return tuple(items)


def _request_fingerprint(
    *,
    product_id: str,
    source_generation_ref: ResourceSourceGenerationRef,
    collection_handle_ids: tuple[str, ...],
    budget: EmbeddedResourceDiscoveryBudget,
) -> str:
    return fingerprint_catalog_value(
        "loushang.embedded-resource-discovery-request/v1",
        {
            "budget": budget.to_payload(),
            "collectionHandleIds": list(collection_handle_ids),
            "productId": product_id,
            "sourceGenerationRef": source_generation_ref.to_payload(),
        },
    )


def _embedded_diagnostics(
    *,
    collection: EmbeddedResourceCollectionHandle,
    logical_path: PurePosixPath,
    reasons: tuple[str, ...],
    source_generation_ref: ResourceSourceGenerationRef,
    identity: ResourceIdentity | None = None,
) -> tuple[ResourceCatalogDiagnostic, ...]:
    return tuple(
        sorted(
            (
                ResourceCatalogDiagnostic(
                    code="resource_source_discovery_failed",
                    reason=reason,
                    identity=identity,
                    source_id=source_generation_ref.source_id,
                    details=(
                        ("collection_id", collection.collection_id),
                        ("logical_path", logical_path.as_posix()),
                    ),
                )
                for reason in reasons
            ),
            key=lambda item: item.canonical_sort_key(),
        )
    )


def _canonical_relative_path(value: str | PurePosixPath) -> PurePosixPath:
    if not isinstance(value, str | PurePosixPath):
        raise TypeError("Embedded Resource path must be text")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Embedded Resource path must be contained and relative")
    return path


def _raise_budget(reason: str) -> None:
    raise EmbeddedResourceSourceError(
        code="resource_source_discovery_budget_exceeded",
        reason=reason,
    )


def _raise_stale(reason: str) -> None:
    raise EmbeddedResourceSourceError(
        code="resource_catalog_generation_stale",
        reason=reason,
    )


__all__ = [
    "EmbeddedOemResourceSource",
    "EmbeddedResourceCollectionHandle",
    "EmbeddedResourceDiscoveryBudget",
    "EmbeddedResourceDiscoveryRequest",
    "EmbeddedResourceSourceError",
    "build_embedded_resource_discovery_request",
    "build_embedded_source_generation_ref",
    "capture_built_in_resource_package",
    "mint_embedded_resource_collection_handle",
]
