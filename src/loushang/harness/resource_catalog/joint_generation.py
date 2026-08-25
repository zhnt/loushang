"""Unpublished Extension/Resource generation transaction for RCP4."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from loushang.harness.capabilities.composition_runtime import (
    StagedResourceCompositionCandidate,
)
from loushang.harness.extensions.context import ExtensionRuntimeBindings
from loushang.harness.extensions.resources import PreparedExtensionResourceCatalog
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._catalog_records import ResourceCatalogSnapshot
from loushang.harness.resources._catalog_source_contracts import (
    BorrowedResourceSourceGenerationLease,
)
from loushang.harness.resources.types import ResourceBundle

JointGenerationState = Literal[
    "root_owned",
    "graph_owned",
    "published",
    "retiring",
    "disposed",
]


class PrepareResourceGeneration(Protocol):
    def __call__(
        self,
        source_lease: BorrowedResourceSourceGenerationLease,
    ) -> object | Awaitable[object]: ...


class ExtensionGenerationDisposalReport(Protocol):
    @property
    def has_failures(self) -> bool: ...


class ExtensionGenerationRetirementPort(Protocol):
    async def retire(self) -> tuple[ExtensionGenerationDisposalReport, ...]: ...


class ExtensionResourceSourceGenerationView(Protocol):
    @property
    def is_retiring(self) -> bool: ...

    @property
    def is_disposed(self) -> bool: ...


@runtime_checkable
class PreparedExtensionGenerationPort(Protocol):
    @property
    def lifecycle_state(self) -> str: ...

    async def prepare_resource_catalog_generation(
        self,
        bundle: ResourceBundle,
        *,
        product_id: str,
        extension_set_fingerprint: str,
    ) -> PreparedExtensionResourceCatalog: ...

    async def activate(self, bindings: ExtensionRuntimeBindings) -> None: ...

    def publish(
        self,
        commit_resource: Callable[[], object],
    ) -> ExtensionGenerationRetirementPort: ...

    async def rollback(self) -> tuple[ExtensionGenerationDisposalReport, ...]: ...


@dataclass(frozen=True, slots=True)
class JointResourcePublication:
    """Synchronous visible-state transaction used at the linearization point."""

    capture: Callable[[], object]
    commit: Callable[[object, ResourceCatalogProjection], object]
    restore: Callable[[object], object]

    def __post_init__(self) -> None:
        if not all(
            callable(item) for item in (self.capture, self.commit, self.restore)
        ):
            raise TypeError("Joint Resource publication callbacks must be callable")


class JointGenerationDisposalError(RuntimeError):
    """Retryable cleanup debt after a joint candidate failed publication."""

    def __init__(self, diagnostic_codes: tuple[str, ...]) -> None:
        self.diagnostic_codes = tuple(sorted(set(diagnostic_codes)))
        super().__init__(
            "Extension/Resource joint generation disposal failed: "
            + ", ".join(self.diagnostic_codes)
        )


class PreparedExtensionResourceJointGeneration:
    """Root-private pair with one synchronous publication and rollback path."""

    def __init__(
        self,
        *,
        extension_candidate: PreparedExtensionGenerationPort,
        staged_resource_candidate: StagedResourceCompositionCandidate,
        resource_catalog: PreparedExtensionResourceCatalog,
        catalog_projection: ResourceCatalogProjection,
    ) -> None:
        self._extension_candidate = extension_candidate
        self._resource_candidate = staged_resource_candidate
        self._resource_catalog = resource_catalog
        self._catalog_projection = catalog_projection
        self._published = False
        self._retiring = False
        self._disposed = False
        self._rollback_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> JointGenerationState:
        if self._disposed:
            return "disposed"
        if self._retiring:
            return "retiring"
        if self._published:
            return "published"
        if self._resource_candidate.ownership_state == "graph_owned":
            return "graph_owned"
        return "root_owned"

    @property
    def projection(self) -> ResourceCatalogProjection:
        """Return the immutable view derived from exact Catalog authority."""

        return self._catalog_projection

    @property
    def extension_source_generation(self) -> ExtensionResourceSourceGenerationView:
        return self._resource_catalog.source_generation

    def publish(
        self,
        publication: JointResourcePublication,
    ) -> ExtensionGenerationRetirementPort:
        """Publish Extension and root-private Catalog/view references without await."""

        if not isinstance(publication, JointResourcePublication):
            raise TypeError("Joint generation requires a Resource publication port")
        if self._published:
            raise RuntimeError("Joint generation is already published")
        if self._retiring or self._disposed:
            raise RuntimeError("Joint generation is retiring or disposed")
        if self._resource_candidate.ownership_state != "graph_owned":
            raise RuntimeError("Resource generation must be graph-owned before publish")
        if (
            self._resource_catalog.source_generation.is_retiring
            or self._resource_catalog.source_generation.is_disposed
        ):
            raise RuntimeError(
                "Extension Resource source generation is not publishable"
            )
        catalog_snapshot = self._resource_candidate.resource_catalog_snapshot
        if not isinstance(catalog_snapshot, ResourceCatalogSnapshot):
            raise TypeError("Joint Resource Catalog snapshot is invalid")
        if (
            self._catalog_projection.catalog_generation
            != catalog_snapshot.catalog_generation
            or self._catalog_projection.catalog_snapshot_fingerprint
            != catalog_snapshot.snapshot_fingerprint
        ):
            raise RuntimeError(
                "Joint Resource projection targets another Catalog generation"
            )
        previous = _require_synchronous_result(
            publication.capture(),
            name="Joint Resource publication capture",
        )
        commit_started = False

        def commit_resource() -> None:
            nonlocal commit_started
            commit_started = True
            result = _require_synchronous_result(
                publication.commit(
                    catalog_snapshot,
                    self._catalog_projection,
                ),
                name="Joint Resource publication commit",
            )
            if result is not None:
                raise TypeError("Joint Resource publication commit must return None")

        try:
            retirement = self._extension_candidate.publish(commit_resource)
        except BaseException as publication_error:
            if commit_started:
                try:
                    restored = _require_synchronous_result(
                        publication.restore(previous),
                        name="Joint Resource publication restore",
                    )
                    if restored is not None:
                        raise TypeError(
                            "Joint Resource publication restore must return None"
                        )
                except BaseException as restoration_error:
                    publication_error.add_note(
                        "Joint Resource publication restoration failed: "
                        f"{restoration_error!r}"
                    )
            raise
        self._published = True
        return retirement

    async def rollback(
        self,
        *,
        dispose_graph: Callable[[], Awaitable[tuple[str, ...]]] | None = None,
    ) -> None:
        """Reverse graph/root custody, Extension activation, and source borrow."""

        if self._published:
            raise RuntimeError("Published joint generation cannot be rolled back")
        if self._disposed:
            return
        task = self._rollback_task
        if task is None:
            task = asyncio.create_task(self._rollback_once(dispose_graph=dispose_graph))
            self._rollback_task = task
        await _join_cleanup(task)

    async def _rollback_once(
        self,
        *,
        dispose_graph: Callable[[], Awaitable[tuple[str, ...]]] | None,
    ) -> None:
        self._retiring = True
        diagnostic_codes: list[str] = []
        ownership = self._resource_candidate.ownership_state
        if ownership in {"graph_owned", "retiring"}:
            if dispose_graph is None:
                self._rollback_task = None
                raise RuntimeError(
                    "Graph-owned joint generation requires its Graph disposer"
                )
            try:
                graph_codes = await dispose_graph()
                if not isinstance(graph_codes, tuple) or any(
                    not isinstance(code, str) or not code for code in graph_codes
                ):
                    raise TypeError(
                        "Joint Graph disposer must return diagnostic-code tuple"
                    )
                diagnostic_codes.extend(graph_codes)
            except BaseException as exc:
                diagnostic_codes.append("joint_graph_disposal_failed")
                graph_error: BaseException | None = exc
            else:
                graph_error = None
        else:
            graph_error = None

        extension_reports: tuple[ExtensionGenerationDisposalReport, ...] = ()
        try:
            # rollback() is also the Extension candidate's retry entry point after
            # its first pass marks lifecycle_state="rolled_back" with debt.
            extension_reports = await self._extension_candidate.rollback()
        except BaseException as exc:
            diagnostic_codes.append("joint_extension_rollback_failed")
            if graph_error is None:
                graph_error = exc
        if any(report.has_failures for report in extension_reports):
            diagnostic_codes.append("joint_extension_retirement_pending")

        ownership = self._resource_candidate.ownership_state
        if ownership == "root_owned":
            try:
                await self._resource_candidate.dispose_root_owned()
            except BaseException as exc:
                diagnostic_codes.append("joint_resource_root_disposal_failed")
                if graph_error is None:
                    graph_error = exc

        if self._resource_candidate.ownership_state != "disposed":
            diagnostic_codes.append("joint_resource_retirement_pending")
        if not self._resource_catalog.source_generation.is_disposed:
            diagnostic_codes.append("joint_extension_source_retirement_pending")

        if diagnostic_codes:
            self._rollback_task = None
            error = JointGenerationDisposalError(tuple(diagnostic_codes))
            if graph_error is not None:
                raise error from graph_error
            raise error
        self._disposed = True
        self._retiring = False


async def prepare_extension_resource_joint_generation(
    *,
    extension_candidate: PreparedExtensionGenerationPort,
    staged_resource_candidate: StagedResourceCompositionCandidate,
    base_resource_bundle: ResourceBundle,
    bindings: ExtensionRuntimeBindings,
    product_id: str,
    extension_set_fingerprint: str,
    prepare_resource_generation: PrepareResourceGeneration,
) -> PreparedExtensionResourceJointGeneration:
    """Prepare one Extension source, Resource generation, and staged activation."""

    if not isinstance(extension_candidate, PreparedExtensionGenerationPort):
        raise TypeError("Joint generation requires a prepared Extension candidate")
    if not isinstance(staged_resource_candidate, StagedResourceCompositionCandidate):
        raise TypeError("Joint generation requires a staged Resource candidate")
    if not isinstance(base_resource_bundle, ResourceBundle):
        raise TypeError("Joint generation requires a base ResourceBundle")
    if staged_resource_candidate.ownership_state != "root_owned":
        raise RuntimeError("Joint Resource candidate must start root-owned")
    if staged_resource_candidate.has_prepared_owner_generation:
        raise RuntimeError("Joint Resource candidate already has an owner generation")

    resource_catalog = await extension_candidate.prepare_resource_catalog_generation(
        base_resource_bundle,
        product_id=product_id,
        extension_set_fingerprint=extension_set_fingerprint,
    )
    source_lease = resource_catalog.source_generation.borrow()
    try:
        prepared = prepare_resource_generation(source_lease)
        if inspect.isawaitable(prepared):
            prepared = await prepared
        if prepared is not None:
            raise TypeError("Resource generation preparation must return None")
        if not staged_resource_candidate.has_prepared_owner_generation:
            raise RuntimeError(
                "Resource preparation did not attach one owner generation"
            )
        if not staged_resource_candidate._borrows_prepared_extension_source_lease(
            source_lease
        ):
            raise RuntimeError(
                "Resource preparation did not claim the exact Extension source lease"
            )
        if staged_resource_candidate.ownership_state != "root_owned":
            raise RuntimeError("Prepared Resource generation left root custody")
        catalog_projection = staged_resource_candidate.resource_catalog_projection
        if not isinstance(catalog_projection, ResourceCatalogProjection):
            raise TypeError("Resource preparation did not retain a Catalog projection")
        await extension_candidate.activate(bindings)
    except BaseException as preparation_error:
        cleanup = asyncio.create_task(
            _rollback_failed_preparation(
                extension_candidate=extension_candidate,
                staged_resource_candidate=staged_resource_candidate,
                source_lease=source_lease,
            )
        )
        try:
            await _join_cleanup(cleanup)
        except BaseException as cleanup_error:
            preparation_error.add_note(
                f"Joint generation preparation rollback failed: {cleanup_error!r}"
            )
        raise
    return PreparedExtensionResourceJointGeneration(
        extension_candidate=extension_candidate,
        staged_resource_candidate=staged_resource_candidate,
        resource_catalog=resource_catalog,
        catalog_projection=catalog_projection,
    )


async def _rollback_failed_preparation(
    *,
    extension_candidate: PreparedExtensionGenerationPort,
    staged_resource_candidate: StagedResourceCompositionCandidate,
    source_lease: BorrowedResourceSourceGenerationLease,
) -> None:
    diagnostic_codes: list[str] = []
    cleanup_error: BaseException | None = None
    owner_attached = staged_resource_candidate.has_prepared_owner_generation
    ownership = staged_resource_candidate.ownership_state
    owner_borrows_lease = False
    if owner_attached and ownership == "root_owned":
        try:
            owner_borrows_lease = (
                staged_resource_candidate._borrows_prepared_extension_source_lease(
                    source_lease
                )
            )
        except BaseException as exc:
            # Preserve the lease when custody cannot be proven; later owner
            # disposal remains the only safe authority to release it.
            owner_borrows_lease = True
            diagnostic_codes.append("joint_extension_source_identity_check_failed")
            cleanup_error = exc

    try:
        if owner_attached:
            if ownership == "root_owned":
                await staged_resource_candidate.dispose_root_owned()
        else:
            staged_resource_candidate.dispose()
    except BaseException as exc:
        diagnostic_codes.append("joint_resource_root_disposal_failed")
        cleanup_error = exc

    ownership = staged_resource_candidate.ownership_state
    if not source_lease.is_released and (
        not owner_attached or ownership == "disposed" or not owner_borrows_lease
    ) and ownership not in {"graph_constructing", "graph_owned", "retiring"}:
        # A Graph-owned candidate may still be serving through this lease. Never
        # invalidate that borrow merely because its callback violated custody.
        try:
            source_lease.release()
        except BaseException as exc:
            diagnostic_codes.append("joint_extension_source_release_failed")
            if cleanup_error is None:
                cleanup_error = exc

    try:
        extension_reports = await extension_candidate.rollback()
        if any(report.has_failures for report in extension_reports):
            diagnostic_codes.append("joint_extension_retirement_pending")
    except BaseException as exc:
        diagnostic_codes.append("joint_extension_rollback_failed")
        if cleanup_error is None:
            cleanup_error = exc

    if staged_resource_candidate.ownership_state != "disposed":
        diagnostic_codes.append("joint_resource_retirement_pending")
    if not source_lease.is_released:
        diagnostic_codes.append("joint_extension_source_retirement_pending")
    if diagnostic_codes:
        error = JointGenerationDisposalError(tuple(diagnostic_codes))
        if cleanup_error is not None:
            raise error from cleanup_error
        raise error


def _require_synchronous_result(value: object, *, name: str) -> object:
    if not inspect.isawaitable(value):
        return value
    if inspect.iscoroutine(value):
        value.close()
    raise TypeError(f"{name} must be synchronous")


async def _join_cleanup(task: asyncio.Task[None]) -> None:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = exc
    task.result()
    if cancellation is not None:
        raise cancellation


__all__ = [
    "JointGenerationDisposalError",
    "JointGenerationState",
    "JointResourcePublication",
    "PreparedExtensionResourceJointGeneration",
    "prepare_extension_resource_joint_generation",
]
