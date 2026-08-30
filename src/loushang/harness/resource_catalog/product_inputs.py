"""Private Product preparation for one initial Resource Catalog Session."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, TypeVar

from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    ResourceContributionSpec,
)
from loushang.harness.resource_catalog.bootstrap_projection import (
    prepare_resource_catalog_bootstrap_projection,
)
from loushang.harness.resource_catalog.inputs import (
    AdmittedPackageResource,
    acquire_admitted_package_resource,
)
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
from loushang.harness.resources._catalog_package_source import (
    PackageResourceDiscoveryBudget,
)
from loushang.harness.resources._catalog_records import (
    ResourceIdentity,
    build_activation_policy_snapshot,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)
from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle
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
class ProductAdmittedPackageResourceSpec:
    """One owner admission plus the Product-held verified revision lease."""

    admission: OwnerContributionAdmissionRecord = field(repr=False)
    revision_handle: VerifiedRevisionHandle = field(repr=False, compare=False)
    source_root_order: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.admission, OwnerContributionAdmissionRecord):
            raise TypeError("Product package Resource admission is invalid")
        contribution = self.admission.candidate.contribution
        if self.admission.contribution_kind != "resource_item" or not isinstance(
            contribution,
            ResourceContributionSpec,
        ):
            raise ValueError(
                "Product package Resource requires resource_item admission"
            )
        if self.admission.owner_id != f"resources.{contribution.resource_kind}":
            raise ValueError("Product package Resource admission owner is invalid")
        if not isinstance(self.revision_handle, VerifiedRevisionHandle):
            raise TypeError("Product package Resource revision handle is invalid")
        if self.revision_handle.closed:
            raise ValueError("Product package Resource revision handle must be live")
        if (
            self.admission.candidate.package_content_digest
            != self.revision_handle.content_digest
        ):
            raise ValueError("Product package Resource admission must match revision")
        if isinstance(self.source_root_order, bool) or not isinstance(
            self.source_root_order,
            int,
        ):
            raise TypeError("Product package Resource root order must be an integer")
        if self.source_root_order < 0:
            raise ValueError("Product package Resource root order cannot be negative")


@dataclass(frozen=True, slots=True)
class InitialResourceCatalogProductSelection:
    """Exact native/package/embedded selection admitted by one Product."""

    product_policy_revision: str
    product_composition: ProductCompositionCompilation | None = field(
        default=None,
        repr=False,
    )
    native_roots: tuple[ProductNativeResourceRootSpec, ...] = ()
    package_resources: tuple[ProductAdmittedPackageResourceSpec, ...] = ()
    embedded_collections: tuple[ProductEmbeddedResourceCollectionSpec, ...] = ()
    source_disposition: Literal["selected", "intentionally_empty"] = "selected"
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES
    native_discovery_budget: NativeResourceDiscoveryBudget | None = None
    package_discovery_budget: PackageResourceDiscoveryBudget | None = None
    embedded_discovery_budget: EmbeddedResourceDiscoveryBudget | None = None
    disabled_skill_selectors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_policy_revision, str)
            or not self.product_policy_revision.strip()
        ):
            raise ValueError("Product Resource policy revision must not be empty")
        native_roots = tuple(self.native_roots)
        package_resources = tuple(self.package_resources)
        embedded_collections = tuple(self.embedded_collections)
        product_composition = self.product_composition
        if product_composition is not None and not isinstance(
            product_composition,
            ProductCompositionCompilation,
        ):
            raise TypeError("Product Resource composition is invalid")
        if any(
            not isinstance(item, ProductNativeResourceRootSpec) for item in native_roots
        ):
            raise TypeError("Product native Resource root specifications are invalid")
        if any(
            not isinstance(item, ProductAdmittedPackageResourceSpec)
            for item in package_resources
        ):
            raise TypeError("Product package Resource specifications are invalid")
        if any(
            not isinstance(item, ProductEmbeddedResourceCollectionSpec)
            for item in embedded_collections
        ):
            raise TypeError("Product embedded Resource specifications are invalid")
        if self.source_disposition not in {"selected", "intentionally_empty"}:
            raise ValueError("Product Resource source disposition is invalid")
        has_sources = bool(native_roots or package_resources or embedded_collections)
        if not has_sources and self.source_disposition != "intentionally_empty":
            raise ValueError("Product Resource selection must contain a source")
        if has_sources and self.source_disposition == "intentionally_empty":
            raise ValueError(
                "Product Resource selection cannot mark selected sources as empty"
            )
        if len({item.handle_id for item in native_roots}) != len(native_roots):
            raise ValueError("Product native root ids must not repeat")
        if len({item.admission.fingerprint for item in package_resources}) != len(
            package_resources
        ):
            raise ValueError("Product package Resource admissions must not repeat")
        composition_resources = (
            tuple(product_composition.resource_admissions)
            if product_composition is not None
            else ()
        )
        if any(
            not isinstance(item, OwnerContributionAdmissionRecord)
            for item in composition_resources
        ):
            raise TypeError("Product composition Resource admissions are invalid")
        if len({item.fingerprint for item in composition_resources}) != len(
            composition_resources
        ):
            raise ValueError("Product composition Resource admissions must be unique")
        package_admission_fingerprints = {
            item.admission.fingerprint for item in package_resources
        }
        composition_admission_fingerprints = {
            item.fingerprint for item in composition_resources
        }
        if package_admission_fingerprints != composition_admission_fingerprints:
            raise ValueError(
                "Product package Resources must exact-match Product composition"
            )
        if product_composition is not None and (
            product_composition.authority_context.product_policy_revision
            != self.product_policy_revision
        ):
            raise ValueError("Product Resource composition policy is stale")
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
        if self.package_discovery_budget is not None and not isinstance(
            self.package_discovery_budget,
            PackageResourceDiscoveryBudget,
        ):
            raise TypeError("Product package Resource discovery budget is invalid")
        if self.embedded_discovery_budget is not None and not isinstance(
            self.embedded_discovery_budget,
            EmbeddedResourceDiscoveryBudget,
        ):
            raise TypeError("Product embedded Resource discovery budget is invalid")
        disabled_skill_selectors = tuple(self.disabled_skill_selectors)
        if any(
            not isinstance(item, str) or not item.strip()
            for item in disabled_skill_selectors
        ):
            raise ValueError("Product disabled Skill selectors must not be empty")
        if len(set(disabled_skill_selectors)) != len(disabled_skill_selectors):
            raise ValueError("Product disabled Skill selectors must not repeat")
        object.__setattr__(self, "native_roots", native_roots)
        object.__setattr__(self, "package_resources", package_resources)
        object.__setattr__(self, "embedded_collections", embedded_collections)
        object.__setattr__(self, "context_file_names", context_file_names)
        object.__setattr__(
            self,
            "disabled_skill_selectors",
            disabled_skill_selectors,
        )


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
            catalog_generation=1,
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

    def prepare_bootstrap_projection(
        self,
        *,
        product_id: str,
        session_id: str,
        cwd: Path,
    ) -> ResourceBundle:
        """Produce the Catalog-owned synchronous seed for Extension bootstrap."""

        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("initial Resource Catalog Product id must not be empty")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("initial Resource Catalog Session id must not be empty")
        if not isinstance(cwd, Path):
            raise TypeError("initial Resource Catalog cwd must be a Path")
        now = self.clock()
        if isinstance(now, bool) or not isinstance(now, int):
            raise TypeError("initial Resource Catalog Product clock must return an int")
        self._validate_product_selection(product_id=product_id, now=now)
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
        package_resources: list[AdmittedPackageResource] = []
        embedded_handles: list[EmbeddedResourceCollectionHandle] = []
        try:
            for package_spec in selection.package_resources:
                package_resources.append(
                    acquire_admitted_package_resource(
                        admission=package_spec.admission,
                        revision_handle=package_spec.revision_handle,
                        source_root_order=package_spec.source_root_order,
                    )
                )
            for embedded_spec in selection.embedded_collections:
                embedded_handles.append(
                    mint_embedded_resource_collection_handle(
                        collection_id=embedded_spec.collection_id,
                        embedded_revision=embedded_spec.embedded_revision,
                        files=embedded_spec.files,
                        source_root_order=embedded_spec.source_root_order,
                    )
                )
            return prepare_resource_catalog_bootstrap_projection(
                product_id=product_id,
                runtime_id=f"resource-bootstrap:{session_id}",
                product_policy_revision=selection.product_policy_revision,
                cwd=cwd,
                root_handles=root_handles,
                package_resources=tuple(package_resources),
                embedded_collections=tuple(embedded_handles),
                context_file_names=selection.context_file_names,
                disabled_skill_selectors=selection.disabled_skill_selectors,
            )
        except BaseException as preparation_error:
            for handle in reversed(embedded_handles):
                if not handle.closed:
                    try:
                        handle.close()
                    except BaseException as cleanup_error:
                        preparation_error.add_note(
                            "Catalog bootstrap embedded cleanup also failed: "
                            f"{cleanup_error!r}"
                        )
            for resource in reversed(package_resources):
                if not resource.revision_handle.closed:
                    try:
                        resource.close()
                    except BaseException as cleanup_error:
                        preparation_error.add_note(
                            "Catalog bootstrap package cleanup also failed: "
                            f"{cleanup_error!r}"
                        )
            raise

    def prepare_session_bootstrap(
        self,
        *,
        product_id: str,
        session_id: str,
        base_resource_bundle: ResourceBundle,
        catalog_generation: int,
    ) -> InitialSessionResourceCatalogBootstrap:
        """Mint one exact next-generation bootstrap without constructing a Session."""

        return self._mint_bootstrap(
            product_id=product_id,
            session_id=session_id,
            base_resource_bundle=base_resource_bundle,
            catalog_generation=catalog_generation,
        )

    def _mint_bootstrap(
        self,
        *,
        product_id: str,
        session_id: str,
        base_resource_bundle: ResourceBundle,
        catalog_generation: int,
    ) -> InitialSessionResourceCatalogBootstrap:
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("initial Resource Catalog Product id must not be empty")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("initial Resource Catalog Session id must not be empty")
        if not isinstance(base_resource_bundle, ResourceBundle):
            raise TypeError("initial Resource Catalog requires a base ResourceBundle")
        if (
            isinstance(catalog_generation, bool)
            or not isinstance(catalog_generation, int)
            or catalog_generation < 1
        ):
            raise ValueError("Session Resource Catalog generation must be positive")
        now = self.clock()
        if isinstance(now, bool) or not isinstance(now, int):
            raise TypeError("initial Resource Catalog Product clock must return an int")

        self._validate_product_selection(product_id=product_id, now=now)
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
        package_resources: list[AdmittedPackageResource] = []
        embedded_handles: list[EmbeddedResourceCollectionHandle] = []
        disabled_skill_identities = tuple(
            ResourceIdentity(
                resource_kind="skill",
                schema_id="loushang.resource.skill",
                schema_version=1,
                public_id=skill.id or skill.name,
            )
            for skill in base_resource_bundle.skills
            if _skill_matches_selectors(
                skill,
                selection.disabled_skill_selectors,
            )
        )
        try:
            for package_spec in selection.package_resources:
                package_resources.append(
                    acquire_admitted_package_resource(
                        admission=package_spec.admission,
                        revision_handle=package_spec.revision_handle,
                        source_root_order=package_spec.source_root_order,
                    )
                )
            for embedded_spec in selection.embedded_collections:
                embedded_handles.append(
                    mint_embedded_resource_collection_handle(
                        collection_id=embedded_spec.collection_id,
                        embedded_revision=embedded_spec.embedded_revision,
                        files=embedded_spec.files,
                        source_root_order=embedded_spec.source_root_order,
                    )
                )
            return InitialSessionResourceCatalogBootstrap(
                InitialSessionResourceCatalogInputs(
                    product_id=product_id,
                    scope_id=f"session:{session_id}",
                    resource_runtime_id=(
                        f"resource-owner:{session_id}:catalog:{catalog_generation}"
                    ),
                    product_policy_revision=selection.product_policy_revision,
                    catalog_generation=catalog_generation,
                    root_handles=root_handles,
                    package_resources=tuple(package_resources),
                    embedded_collections=tuple(embedded_handles),
                    issued_at=now,
                    expires_at=now + _INITIAL_ADMISSION_TTL_SECONDS,
                    now=now,
                    base_resource_bundle=base_resource_bundle,
                    discovery_budget=selection.native_discovery_budget,
                    package_discovery_budget=(selection.package_discovery_budget),
                    embedded_discovery_budget=(selection.embedded_discovery_budget),
                    context_file_names=selection.context_file_names,
                    activation_policy=build_activation_policy_snapshot(
                        policy_revision=(
                            f"{selection.product_policy_revision}:skill-activation"
                        ),
                        disabled_identities=disabled_skill_identities,
                    ),
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
            for resource in reversed(package_resources):
                try:
                    resource.close()
                except BaseException as cleanup_error:
                    preparation_error.add_note(
                        "Partial Product package Resource cleanup also failed: "
                        f"{cleanup_error!r}"
                    )
            raise

    def _validate_product_selection(self, *, product_id: str, now: int) -> None:
        selection = self.selection
        product_composition = selection.product_composition
        if (
            product_composition is not None
            and product_composition.authority_context.product_id != product_id
        ):
            raise ValueError("Product Resource composition belongs elsewhere")
        for spec in selection.package_resources:
            admission = spec.admission
            if admission.product_id != product_id:
                raise ValueError("Product package Resource admission belongs elsewhere")
            if (
                admission.candidate.product_policy_revision
                != selection.product_policy_revision
            ):
                raise ValueError("Product package Resource admission policy is stale")
            if (
                admission.consumer_scope != "session"
                or admission.consumer_refresh_boundary != "sealed"
            ):
                raise ValueError(
                    "Initial Product package Resource admission must be Session-sealed"
                )
            if not admission.issued_at <= now < admission.expires_at:
                raise ValueError("Product package Resource admission is not active")


def _skill_matches_selectors(
    skill: object,
    selectors: tuple[str, ...],
) -> bool:
    if not selectors:
        return False
    return bool(
        set(selectors)
        & {
            str(getattr(skill, "name", "")),
            str(getattr(skill, "id", "")),
            str(getattr(skill, "canonical_name", "")),
            str(getattr(skill, "source_path", "")),
        }
    )


__all__ = [
    "InitialResourceCatalogProductAdapter",
    "InitialResourceCatalogProductSelection",
    "ProductAdmittedPackageResourceSpec",
    "ProductEmbeddedResourceCollectionSpec",
    "ProductNativeResourceRootSpec",
]
