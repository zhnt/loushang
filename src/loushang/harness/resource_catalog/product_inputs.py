"""Private Product preparation for one initial Resource Catalog Session."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar

from loushang.harness.resource_catalog.session_bootstrap import (
    InitialSessionResourceCatalogBootstrap,
    InitialSessionResourceCatalogInputs,
)
from loushang.harness.resources._catalog_embedded_source import (
    EmbeddedResourceCollectionHandle,
    EmbeddedResourceDiscoveryBudget,
    mint_embedded_resource_collection_handle,
)
from loushang.harness.resources._catalog_native_source import (
    NativeResourceDiscoveryBudget,
    NativeResourceRootKind,
    NativeResourceSourceClass,
    mint_native_resource_root_handle,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)
from loushang.harness.resources.types import ResourceBundle

SessionT = TypeVar("SessionT")
ProductInputClock = Callable[[], int]
_INITIAL_ADMISSION_TTL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ProductNativeResourceRootSpec:
    """Product-approved native path before conversion to an opaque handle."""

    handle_id: str
    root: Path
    source_class: NativeResourceSourceClass
    root_kind: NativeResourceRootKind
    source_root_order: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.handle_id, str) or not self.handle_id.strip():
            raise ValueError("Product native Resource root id must not be empty")
        object.__setattr__(self, "root", Path(self.root))
        if self.source_class not in {
            "project_local",
            "user_global",
            "temporary",
        }:
            raise ValueError("Product native Resource source class is unsupported")
        if self.root_kind not in {"context", "standard", "combined"}:
            raise ValueError("Product native Resource root kind is unsupported")
        if isinstance(self.source_root_order, bool) or not isinstance(
            self.source_root_order, int
        ):
            raise TypeError("Product native Resource root order must be an integer")
        if self.source_root_order < 0:
            raise ValueError("Product native Resource root order cannot be negative")


@dataclass(frozen=True, slots=True)
class ProductEmbeddedResourceCollectionSpec:
    """Finite Product-owned embedded bytes before handle custody begins."""

    collection_id: str
    embedded_revision: str
    files: Mapping[str, bytes] = field(repr=False)
    source_root_order: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.collection_id, str) or not self.collection_id.strip():
            raise ValueError("Product embedded collection id must not be empty")
        if (
            not isinstance(self.embedded_revision, str)
            or not self.embedded_revision.strip()
        ):
            raise ValueError("Product embedded revision must not be empty")
        if not isinstance(self.files, Mapping):
            raise TypeError("Product embedded Resource files must be a mapping")
        copied: dict[str, bytes] = {}
        for path, body in self.files.items():
            if not isinstance(path, str):
                raise TypeError("Product embedded Resource paths must be strings")
            if not isinstance(body, bytes):
                raise TypeError("Product embedded Resource bodies must be bytes")
            copied[path] = bytes(body)
        object.__setattr__(self, "files", MappingProxyType(copied))
        if isinstance(self.source_root_order, bool) or not isinstance(
            self.source_root_order, int
        ):
            raise TypeError("Product embedded root order must be an integer")
        if self.source_root_order < 0:
            raise ValueError("Product embedded root order cannot be negative")


@dataclass(frozen=True, slots=True)
class InitialResourceCatalogProductSelection:
    """Exact native/embedded selection explicitly admitted by one Product."""

    product_policy_revision: str
    native_roots: tuple[ProductNativeResourceRootSpec, ...] = ()
    embedded_collections: tuple[ProductEmbeddedResourceCollectionSpec, ...] = ()
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES
    native_discovery_budget: NativeResourceDiscoveryBudget | None = None
    embedded_discovery_budget: EmbeddedResourceDiscoveryBudget | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_policy_revision, str)
            or not self.product_policy_revision.strip()
        ):
            raise ValueError("Product Resource policy revision must not be empty")
        native_roots = tuple(self.native_roots)
        embedded_collections = tuple(self.embedded_collections)
        if any(
            not isinstance(item, ProductNativeResourceRootSpec) for item in native_roots
        ):
            raise TypeError("Product native Resource root specifications are invalid")
        if any(
            not isinstance(item, ProductEmbeddedResourceCollectionSpec)
            for item in embedded_collections
        ):
            raise TypeError("Product embedded Resource specifications are invalid")
        if not native_roots and not embedded_collections:
            raise ValueError("Product Resource selection must contain a source")
        if len({item.handle_id for item in native_roots}) != len(native_roots):
            raise ValueError("Product native root ids must not repeat")
        if len({item.collection_id for item in embedded_collections}) != len(
            embedded_collections
        ):
            raise ValueError("Product embedded collection ids must not repeat")
        context_file_names = tuple(self.context_file_names)
        if any(
            not isinstance(item, str) or not item.strip() for item in context_file_names
        ):
            raise ValueError("Product context file names must not be empty")
        if len(set(context_file_names)) != len(context_file_names):
            raise ValueError("Product context file names must not repeat")
        if self.native_discovery_budget is not None and not isinstance(
            self.native_discovery_budget, NativeResourceDiscoveryBudget
        ):
            raise TypeError("Product native Resource discovery budget is invalid")
        if self.embedded_discovery_budget is not None and not isinstance(
            self.embedded_discovery_budget,
            EmbeddedResourceDiscoveryBudget,
        ):
            raise TypeError("Product embedded Resource discovery budget is invalid")
        object.__setattr__(self, "native_roots", native_roots)
        object.__setattr__(self, "embedded_collections", embedded_collections)
        object.__setattr__(self, "context_file_names", context_file_names)


@dataclass(frozen=True, slots=True)
class InitialResourceCatalogProductAdapter:
    """Mint exact inputs and transfer them only through Session construction."""

    selection: InitialResourceCatalogProductSelection
    clock: ProductInputClock = field(
        default=lambda: int(time.time()),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.selection, InitialResourceCatalogProductSelection):
            raise TypeError("initial Resource Catalog Product selection is invalid")
        if not callable(self.clock):
            raise TypeError("initial Resource Catalog Product clock must be callable")

    def construct_session(
        self,
        *,
        product_id: str,
        session_id: str,
        base_resource_bundle: ResourceBundle,
        construct: Callable[[InitialSessionResourceCatalogBootstrap], SessionT],
    ) -> SessionT:
        """Construct synchronously and transfer one bootstrap only on success."""

        if not callable(construct):
            raise TypeError("initial Resource Catalog Session constructor is invalid")
        bootstrap = self._mint_bootstrap(
            product_id=product_id,
            session_id=session_id,
            base_resource_bundle=base_resource_bundle,
        )
        try:
            session = construct(bootstrap)
            if inspect.isawaitable(session):
                close = getattr(session, "close", None)
                if callable(close):
                    close()
                raise TypeError(
                    "initial Resource Catalog Session construction must be synchronous"
                )
        except BaseException as construction_error:
            try:
                bootstrap.close_unprepared()
            except BaseException as cleanup_error:
                construction_error.add_note(
                    "Initial Product Resource input cleanup also failed: "
                    f"{cleanup_error!r}"
                )
            raise
        return session

    def _mint_bootstrap(
        self,
        *,
        product_id: str,
        session_id: str,
        base_resource_bundle: ResourceBundle,
    ) -> InitialSessionResourceCatalogBootstrap:
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("initial Resource Catalog Product id must not be empty")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("initial Resource Catalog Session id must not be empty")
        if not isinstance(base_resource_bundle, ResourceBundle):
            raise TypeError("initial Resource Catalog requires a base ResourceBundle")
        now = self.clock()
        if isinstance(now, bool) or not isinstance(now, int):
            raise TypeError("initial Resource Catalog Product clock must return an int")

        selection = self.selection
        root_handles = tuple(
            mint_native_resource_root_handle(
                handle_id=spec.handle_id,
                root=spec.root,
                source_class=spec.source_class,
                root_kind=spec.root_kind,
                source_root_order=spec.source_root_order,
            )
            for spec in selection.native_roots
        )
        embedded_handles: list[EmbeddedResourceCollectionHandle] = []
        try:
            for spec in selection.embedded_collections:
                embedded_handles.append(
                    mint_embedded_resource_collection_handle(
                        collection_id=spec.collection_id,
                        embedded_revision=spec.embedded_revision,
                        files=spec.files,
                        source_root_order=spec.source_root_order,
                    )
                )
            return InitialSessionResourceCatalogBootstrap(
                InitialSessionResourceCatalogInputs(
                    product_id=product_id,
                    scope_id=f"session:{session_id}",
                    resource_runtime_id=f"resource-owner:{session_id}",
                    product_policy_revision=selection.product_policy_revision,
                    root_handles=root_handles,
                    embedded_collections=tuple(embedded_handles),
                    issued_at=now,
                    expires_at=now + _INITIAL_ADMISSION_TTL_SECONDS,
                    now=now,
                    base_resource_bundle=base_resource_bundle,
                    discovery_budget=selection.native_discovery_budget,
                    embedded_discovery_budget=(selection.embedded_discovery_budget),
                    context_file_names=selection.context_file_names,
                )
            )
        except BaseException as preparation_error:
            for handle in reversed(embedded_handles):
                try:
                    handle.close()
                except BaseException as cleanup_error:
                    preparation_error.add_note(
                        "Partial Product embedded Resource cleanup also failed: "
                        f"{cleanup_error!r}"
                    )
            raise


__all__ = [
    "InitialResourceCatalogProductAdapter",
    "InitialResourceCatalogProductSelection",
    "ProductEmbeddedResourceCollectionSpec",
    "ProductNativeResourceRootSpec",
]
