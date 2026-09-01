"""Dark recursive acquisition owner feeding the pure PLC9B closure verifier."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import NoReturn, Protocol

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageAuthenticatedSourceEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    PackageClosureArtifactCandidateV2,
    PackageClosureArtifactRole,
    PackageClosureBudgetV1,
    PackageClosureLimitDimension,
    PackageClosureVerificationError,
    PackageClosureVerificationRequestV2,
    PackageClosureVerifier,
    PackageResolutionEnvironmentV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
    PackageArtifactEvidenceJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
    canonicalize_source_identity,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
    VerifiedWheelCandidate,
)

PACKAGE_DEPENDENCY_SELECTION_REQUEST_VERSION = 1
PACKAGE_DEPENDENCY_SELECTION_VERSION = 1
PACKAGE_RECURSIVE_CLOSURE_REQUEST_VERSION = 2

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class PackageDependencyResolutionError(RuntimeError):
    """Stable, secret-free refusal from the dependency selection boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = "resolving_closure"


@dataclass(frozen=True, slots=True)
class PackageDependencySelectionRequestV1:
    operation_id: str
    attempt_epoch: int
    parent_node_id: str
    request_fingerprint: str
    resolution_environment_fingerprint: str
    requirement: NormalizedPackageRequirementV1
    request_version: int = PACKAGE_DEPENDENCY_SELECTION_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_safe_id(self.operation_id, name="operation id")
        _require_positive(self.attempt_epoch, name="attempt epoch")
        _require_safe_id(self.parent_node_id, name="parent node id")
        _require_sha256(self.request_fingerprint, name="request fingerprint")
        _require_sha256(
            self.resolution_environment_fingerprint,
            name="resolution environment fingerprint",
        )
        if not isinstance(self.requirement, NormalizedPackageRequirementV1):
            raise TypeError("Normalized Package requirement is required")
        if self.request_version != PACKAGE_DEPENDENCY_SELECTION_REQUEST_VERSION:
            raise ValueError("Unsupported dependency selection request")

    @property
    def requirement_fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self.requirement.to_dict())).hexdigest()

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "operationId": self.operation_id,
            "parentNodeId": self.parent_node_id,
            "requestFingerprint": self.request_fingerprint,
            "requestVersion": self.request_version,
            "requirement": self.requirement.to_dict(),
            "resolutionEnvironmentFingerprint": (
                self.resolution_environment_fingerprint
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencySelectionRequestV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "operationId",
                "parentNodeId",
                "requestFingerprint",
                "requestVersion",
                "requirement",
                "resolutionEnvironmentFingerprint",
            },
            name="dependency selection request",
        )
        return cls(
            operation_id=_wire_string(document["operationId"], name="operation id"),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            parent_node_id=_wire_string(
                document["parentNodeId"], name="parent node id"
            ),
            request_fingerprint=_wire_string(
                document["requestFingerprint"], name="request fingerprint"
            ),
            resolution_environment_fingerprint=_wire_string(
                document["resolutionEnvironmentFingerprint"],
                name="resolution environment fingerprint",
            ),
            requirement=NormalizedPackageRequirementV1.from_dict(
                document["requirement"]
            ),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageDependencySelectionV1:
    operation_id: str
    attempt_epoch: int
    parent_node_id: str
    request_fingerprint: str
    resolution_environment_fingerprint: str
    requirement_fingerprint: str
    project_name: str
    version: str
    canonical_source_identity: str
    wheel_filename: str
    expected_artifact_digest: str
    resolver_id: str
    resolver_revision: str
    selection_version: int = PACKAGE_DEPENDENCY_SELECTION_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "operation id"),
            (self.parent_node_id, "parent node id"),
            (self.resolver_id, "resolver id"),
            (self.resolver_revision, "resolver revision"),
        ):
            _require_safe_id(value, name=name)
        _require_positive(self.attempt_epoch, name="attempt epoch")
        for value, name in (
            (self.request_fingerprint, "request fingerprint"),
            (
                self.resolution_environment_fingerprint,
                "resolution environment fingerprint",
            ),
            (self.requirement_fingerprint, "requirement fingerprint"),
            (self.expected_artifact_digest, "expected artifact digest"),
        ):
            _require_sha256(value, name=name)
        if self.project_name != _canonical_distribution(self.project_name):
            raise ValueError("Selected dependency name must be canonical")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("Selected dependency version is required")
        if canonicalize_source_identity(self.canonical_source_identity) != (
            self.canonical_source_identity
        ):
            raise ValueError("Selected dependency Source identity is not canonical")
        if (
            not isinstance(self.wheel_filename, str)
            or not self.wheel_filename.endswith(".whl")
            or self.wheel_filename != os.path.basename(self.wheel_filename)
            or "/" in self.wheel_filename
            or "\\" in self.wheel_filename
        ):
            raise ValueError("Selected dependency wheel filename is invalid")
        if self.selection_version != PACKAGE_DEPENDENCY_SELECTION_VERSION:
            raise ValueError("Unsupported dependency selection")

    @property
    def node_id(self) -> str:
        digest = sha256(self.project_name.encode("utf-8")).hexdigest()
        return f"dependency-{digest}"

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self.to_dict())).hexdigest()

    def matches(self, request: PackageDependencySelectionRequestV1) -> bool:
        return (
            self.operation_id == request.operation_id
            and self.attempt_epoch == request.attempt_epoch
            and self.parent_node_id == request.parent_node_id
            and self.request_fingerprint == request.request_fingerprint
            and self.resolution_environment_fingerprint
            == request.resolution_environment_fingerprint
            and self.requirement_fingerprint == request.requirement_fingerprint
            and self.project_name == request.requirement.project_name
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "canonicalSourceIdentity": self.canonical_source_identity,
            "expectedArtifactDigest": self.expected_artifact_digest,
            "operationId": self.operation_id,
            "parentNodeId": self.parent_node_id,
            "projectName": self.project_name,
            "requestFingerprint": self.request_fingerprint,
            "requirementFingerprint": self.requirement_fingerprint,
            "resolutionEnvironmentFingerprint": (
                self.resolution_environment_fingerprint
            ),
            "resolverId": self.resolver_id,
            "resolverRevision": self.resolver_revision,
            "selectionVersion": self.selection_version,
            "version": self.version,
            "wheelFilename": self.wheel_filename,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencySelectionV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "canonicalSourceIdentity",
                "expectedArtifactDigest",
                "operationId",
                "parentNodeId",
                "projectName",
                "requestFingerprint",
                "requirementFingerprint",
                "resolutionEnvironmentFingerprint",
                "resolverId",
                "resolverRevision",
                "selectionVersion",
                "version",
                "wheelFilename",
            },
            name="dependency selection",
        )
        return cls(
            operation_id=_wire_string(document["operationId"], name="operation id"),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            parent_node_id=_wire_string(
                document["parentNodeId"], name="parent node id"
            ),
            request_fingerprint=_wire_string(
                document["requestFingerprint"], name="request fingerprint"
            ),
            resolution_environment_fingerprint=_wire_string(
                document["resolutionEnvironmentFingerprint"],
                name="resolution environment fingerprint",
            ),
            requirement_fingerprint=_wire_string(
                document["requirementFingerprint"], name="requirement fingerprint"
            ),
            project_name=_wire_string(document["projectName"], name="project name"),
            version=_wire_string(document["version"], name="version"),
            canonical_source_identity=_wire_string(
                document["canonicalSourceIdentity"], name="Source identity"
            ),
            wheel_filename=_wire_string(
                document["wheelFilename"], name="wheel filename"
            ),
            expected_artifact_digest=_wire_string(
                document["expectedArtifactDigest"],
                name="expected artifact digest",
            ),
            resolver_id=_wire_string(document["resolverId"], name="resolver id"),
            resolver_revision=_wire_string(
                document["resolverRevision"], name="resolver revision"
            ),
            selection_version=_wire_int(
                document["selectionVersion"], name="selection version"
            ),
        )


class PackageDependencyResolverPort(Protocol):
    def resolve(
        self,
        request: PackageDependencySelectionRequestV1,
    ) -> PackageDependencySelectionV1: ...


@dataclass(frozen=True, slots=True)
class PackageRecursiveClosureRequestV2:
    operation_id: str
    attempt_epoch: int
    request_fingerprint: str
    policy_revision: str
    resolution_environment: PackageResolutionEnvironmentV1
    budgets: PackageClosureBudgetV1
    root_extras: tuple[str, ...] = ()
    credential_reference: str | None = field(default=None, repr=False, compare=False)
    request_version: int = PACKAGE_RECURSIVE_CLOSURE_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_safe_id(self.operation_id, name="operation id")
        _require_positive(self.attempt_epoch, name="attempt epoch")
        _require_sha256(self.request_fingerprint, name="request fingerprint")
        _require_safe_id(self.policy_revision, name="policy revision")
        if not isinstance(self.resolution_environment, PackageResolutionEnvironmentV1):
            raise TypeError("Package resolution environment is required")
        if not isinstance(self.budgets, PackageClosureBudgetV1):
            raise TypeError("Package closure budgets are required")
        if self.root_extras != tuple(sorted(set(self.root_extras))) or any(
            extra != _canonical_distribution(extra) for extra in self.root_extras
        ):
            raise ValueError("Root Package extras must be canonical and unique")
        if self.credential_reference is not None and not self.credential_reference:
            raise ValueError("Credential reference cannot be empty")
        if self.request_version != PACKAGE_RECURSIVE_CLOSURE_REQUEST_VERSION:
            raise ValueError("Unsupported recursive closure request")


class VerifiedPackageClosureCandidate:
    """Opaque complete closure capability; every node is still quarantined."""

    def __init__(
        self,
        *,
        plan: VerifiedClosurePlanV2,
        candidates: tuple[VerifiedWheelCandidate, ...],
    ) -> None:
        self.plan = plan
        self._candidates = candidates
        self._closed = False

    def __repr__(self) -> str:
        return (
            "VerifiedPackageClosureCandidate("
            f"operation_id={self.plan.operation_id!r}, "
            f"graph_digest={self.plan.graph_digest!r}, "
            f"node_count={self.plan.node_count})"
        )

    @property
    def candidates(self) -> tuple[VerifiedWheelCandidate, ...]:
        return self._candidates

    def cleanup(self) -> None:
        if self._closed:
            return
        for candidate in reversed(self._candidates):
            candidate.cleanup()
        self._closed = True

    def suspend_for_recovery(self) -> None:
        if self._closed:
            return
        for candidate in reversed(self._candidates):
            candidate.suspend_for_recovery()
        self._closed = True


@dataclass(slots=True)
class _NodeState:
    candidate: VerifiedWheelCandidate
    selected_extras: set[str]
    requirements: tuple[ResolvedPackageRequirementV1, ...] = ()
    processed_extras: tuple[str, ...] | None = None


class PackageRecursiveClosureOwner:
    """Acquire every selected dependency, then delegate the full proof."""

    def __init__(
        self,
        *,
        resolver: PackageDependencyResolverPort,
        acquisition_owner: PackageAcquisitionOwner,
        evidence_journal: PackageArtifactEvidenceJournal,
        wheel_verifier: PackageWheelVerifier,
        closure_verifier: PackageClosureVerifier,
        acquisition_budgets: PackageAcquisitionBudgetV1,
        inspection_budgets: PackageInspectionBudgetV1,
    ) -> None:
        if not callable(getattr(resolver, "resolve", None)):
            raise TypeError("Package dependency resolver is required")
        if not isinstance(acquisition_owner, PackageAcquisitionOwner):
            raise TypeError("Package acquisition owner is required")
        if not isinstance(evidence_journal, PackageArtifactEvidenceJournal):
            raise TypeError("Package artifact evidence journal is required")
        if not isinstance(wheel_verifier, PackageWheelVerifier):
            raise TypeError("Package wheel verifier is required")
        if not isinstance(closure_verifier, PackageClosureVerifier):
            raise TypeError("Package closure verifier is required")
        if not isinstance(acquisition_budgets, PackageAcquisitionBudgetV1):
            raise TypeError("Package acquisition budgets are required")
        if not isinstance(inspection_budgets, PackageInspectionBudgetV1):
            raise TypeError("Package inspection budgets are required")
        self._resolver = resolver
        self._acquisition_owner = acquisition_owner
        self._evidence_journal = evidence_journal
        self._wheel_verifier = wheel_verifier
        self._closure_verifier = closure_verifier
        self._acquisition_budgets = acquisition_budgets
        self._inspection_budgets = inspection_budgets

    def build(
        self,
        root: VerifiedWheelCandidate,
        request: PackageRecursiveClosureRequestV2,
    ) -> VerifiedPackageClosureCandidate:
        if not isinstance(root, VerifiedWheelCandidate):
            raise TypeError("Verified root Wheel candidate is required")
        if not isinstance(request, PackageRecursiveClosureRequestV2):
            raise TypeError("Recursive Package closure request is required")
        self._require_root_identity(root, request)
        states = {
            root.evidence.node_id: _NodeState(
                candidate=root,
                selected_extras=set(request.root_extras),
            )
        }
        by_distribution = {root.evidence.distribution: root.evidence.node_id}
        selections: dict[tuple[str, str], PackageDependencySelectionV1] = {}
        queue = [root.evidence.node_id]
        solver_steps = 0
        marker_steps = 0
        selected_edges: set[tuple[str, str]] = set()
        total_requests = root.acquisition_receipt.request_count
        total_redirects = root.acquisition_receipt.redirect_count
        try:
            if request.budgets.max_nodes < 1 or request.budgets.max_artifacts < 1:
                _reject_limit("graph")
            if (
                total_requests > request.budgets.max_total_requests
                or total_redirects > request.budgets.max_total_redirects
            ):
                _reject_limit("requests")
            self._preflight_candidate(
                root,
                role="root",
                selected_extras=request.root_extras,
                environment=request.resolution_environment,
            )
            while queue:
                node_id = queue.pop(0)
                state = states[node_id]
                selected_extras = tuple(sorted(state.selected_extras))
                if state.processed_extras == selected_extras:
                    continue
                state.processed_extras = selected_extras
                requirements = self._parse_requirements(state.candidate)
                resolved: list[ResolvedPackageRequirementV1] = []
                for requirement in requirements:
                    solver_steps += 1
                    if solver_steps > request.budgets.max_solver_steps:
                        _reject_limit("solver")
                    if requirement.marker is not None:
                        marker_steps += 1
                        if marker_steps > request.budgets.max_marker_steps:
                            _reject_limit("solver")
                    try:
                        applies = requirement.marker_applies(
                            request.resolution_environment,
                            selected_extras=selected_extras,
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise PackageClosureVerificationError(
                            "Package dependency marker is not reproducible",
                            code="package_closure_conflict",
                        ) from exc
                    if not applies:
                        resolved.append(
                            ResolvedPackageRequirementV1(
                                requirement=requirement,
                                marker_applies=False,
                                selected_node_id=None,
                                expected_source_identity=None,
                                expected_artifact_digest=None,
                            )
                        )
                        continue
                    selection_request = PackageDependencySelectionRequestV1(
                        operation_id=request.operation_id,
                        attempt_epoch=request.attempt_epoch,
                        parent_node_id=node_id,
                        request_fingerprint=request.request_fingerprint,
                        resolution_environment_fingerprint=(
                            request.resolution_environment.fingerprint
                        ),
                        requirement=requirement,
                    )
                    key = (node_id, selection_request.requirement_fingerprint)
                    selection = selections.get(key)
                    if selection is None:
                        selection = self._resolve(selection_request)
                        selections[key] = selection
                    child_id = by_distribution.get(selection.project_name)
                    selected_id = child_id or selection.node_id
                    if selected_id == root.evidence.node_id:
                        _reject_conflict(
                            "Package dependency selected the root artifact"
                        )
                    proposed_edges = selected_edges | {(node_id, selected_id)}
                    if len(proposed_edges) > request.budgets.max_edges:
                        _reject_limit("graph")
                    _require_incremental_graph(
                        root_node_id=root.evidence.node_id,
                        selected_edges=proposed_edges,
                        max_depth=request.budgets.max_depth,
                    )
                    selected_edges = proposed_edges
                    if child_id is None:
                        if (
                            len(states) >= request.budgets.max_nodes
                            or len(states) >= request.budgets.max_artifacts
                        ):
                            _reject_limit("graph")
                        acquisition_budgets = self._remaining_acquisition_budgets(
                            request.budgets,
                            consumed_requests=total_requests,
                            consumed_redirects=total_redirects,
                        )
                        child = self._acquire_dependency(
                            selection,
                            request,
                            acquisition_budgets=acquisition_budgets,
                        )
                        child_id = child.evidence.node_id
                        try:
                            self._require_selected_candidate(selection, child)
                        except Exception:
                            child.cleanup()
                            raise
                        total_requests += child.acquisition_receipt.request_count
                        total_redirects += child.acquisition_receipt.redirect_count
                        states[child_id] = _NodeState(
                            candidate=child,
                            selected_extras=set(),
                        )
                        by_distribution[selection.project_name] = child_id
                        queue.append(child_id)
                    else:
                        self._require_selected_candidate(
                            selection,
                            states[child_id].candidate,
                        )
                    child_state = states[child_id]
                    before = len(child_state.selected_extras)
                    child_state.selected_extras.update(requirement.extras)
                    self._preflight_candidate(
                        child_state.candidate,
                        role="dependency",
                        selected_extras=tuple(sorted(child_state.selected_extras)),
                        environment=request.resolution_environment,
                    )
                    if len(child_state.selected_extras) != before:
                        queue.append(child_id)
                    resolved.append(
                        ResolvedPackageRequirementV1(
                            requirement=requirement,
                            marker_applies=True,
                            selected_node_id=child_id,
                            expected_source_identity=(
                                selection.canonical_source_identity
                            ),
                            expected_artifact_digest=(
                                selection.expected_artifact_digest
                            ),
                        )
                    )
                state.requirements = tuple(
                    sorted(resolved, key=lambda item: item.sort_key)
                )
            closure_candidates = tuple(
                PackageClosureArtifactCandidateV2(
                    role="root" if node_id == root.evidence.node_id else "dependency",
                    envelope=_require_envelope(state.candidate),
                    acquisition=state.candidate.acquisition_receipt,
                    wheel=state.candidate.evidence,
                    requirements=state.requirements,
                    requires_python=state.candidate.requires_python,
                    declared_extras=state.candidate.provides_extra,
                    selected_extras=tuple(sorted(state.selected_extras)),
                )
                for node_id, state in sorted(states.items())
            )
            plan = self._closure_verifier.verify(
                PackageClosureVerificationRequestV2(
                    root_node_id=root.evidence.node_id,
                    candidates=closure_candidates,
                    resolution_environment=request.resolution_environment,
                    budgets=request.budgets,
                    root_extras=request.root_extras,
                )
            )
            candidates = tuple(states[node.node_id].candidate for node in plan.nodes)
            return VerifiedPackageClosureCandidate(
                plan=plan,
                candidates=candidates,
            )
        except Exception:
            for state in reversed(tuple(states.values())):
                state.candidate.cleanup()
            raise

    @staticmethod
    def _require_root_identity(
        root: VerifiedWheelCandidate,
        request: PackageRecursiveClosureRequestV2,
    ) -> None:
        evidence = root.evidence
        if (
            evidence.operation_id != request.operation_id
            or evidence.attempt_epoch != request.attempt_epoch
            or evidence.node_id != "root"
            or root.authenticated_envelope is None
        ):
            raise PackageClosureVerificationError(
                "Verified root evidence is incomplete",
                code="package_closure_artifact_invalid",
            )

    @staticmethod
    def _parse_requirements(
        candidate: VerifiedWheelCandidate,
    ) -> tuple[NormalizedPackageRequirementV1, ...]:
        try:
            return tuple(
                sorted(
                    (
                        NormalizedPackageRequirementV1.parse(value)
                        for value in candidate.requires_dist
                    ),
                    key=lambda item: item.canonical_text,
                )
            )
        except (TypeError, ValueError) as exc:
            raise PackageClosureVerificationError(
                "Package dependency metadata is invalid",
                code="package_closure_artifact_invalid",
            ) from exc

    def _resolve(
        self,
        request: PackageDependencySelectionRequestV1,
    ) -> PackageDependencySelectionV1:
        try:
            selection = self._resolver.resolve(request)
        except PackageDependencyResolutionError:
            raise
        except Exception:
            raise PackageDependencyResolutionError(
                "Package dependency resolver refused selection",
                code="package_closure_artifact_invalid",
            ) from None
        if not isinstance(selection, PackageDependencySelectionV1):
            raise PackageDependencyResolutionError(
                "Package dependency resolver returned invalid evidence",
                code="package_closure_artifact_invalid",
            )
        if not selection.matches(request):
            raise PackageDependencyResolutionError(
                "Package dependency selection identity changed",
                code="package_closure_conflict",
            )
        try:
            version_matches = request.requirement.matches_version(selection.version)
        except ValueError as exc:
            raise PackageDependencyResolutionError(
                "Package dependency resolver selected an invalid version",
                code="package_closure_artifact_invalid",
            ) from exc
        if not version_matches:
            raise PackageDependencyResolutionError(
                "Package dependency resolver selected an incompatible version",
                code="package_closure_conflict",
            )
        return selection

    def _preflight_candidate(
        self,
        candidate: VerifiedWheelCandidate,
        *,
        role: PackageClosureArtifactRole,
        selected_extras: tuple[str, ...],
        environment: PackageResolutionEnvironmentV1,
    ) -> None:
        self._closure_verifier.verify_artifact_evidence(
            PackageClosureArtifactCandidateV2(
                role=role,
                envelope=_require_envelope(candidate),
                acquisition=candidate.acquisition_receipt,
                wheel=candidate.evidence,
                requirements=(),
                requires_python=candidate.requires_python,
                declared_extras=candidate.provides_extra,
                selected_extras=selected_extras,
            ),
            environment,
        )

    def _acquire_dependency(
        self,
        selection: PackageDependencySelectionV1,
        request: PackageRecursiveClosureRequestV2,
        *,
        acquisition_budgets: PackageAcquisitionBudgetV1,
    ) -> VerifiedWheelCandidate:
        acquisition_request = PackageAcquisitionRequestV1(
            operation_id=request.operation_id,
            attempt_epoch=request.attempt_epoch,
            node_id=selection.node_id,
            canonical_source_identity=selection.canonical_source_identity,
            request_fingerprint=request.request_fingerprint,
            requested_locator_digest=sha256(
                selection.canonical_source_identity.encode("utf-8")
            ).hexdigest(),
            policy_revision=request.policy_revision,
            credential_reference=request.credential_reference,
        )
        authorized = self._acquisition_owner.authorize_source(acquisition_request)
        source_evidence = PackageAuthenticatedSourceEvidenceV1(
            attempt_epoch=request.attempt_epoch,
            envelope=authorized.envelope,
        )
        self._evidence_journal.append(
            request_fingerprint=request.request_fingerprint,
            evidence=source_evidence,
        )
        acquired = self._acquisition_owner.acquire_authorized(
            acquisition_request,
            authorized,
            budgets=acquisition_budgets,
        )
        try:
            self._evidence_journal.append(
                request_fingerprint=request.request_fingerprint,
                evidence=acquired.receipt,
            )
            verified = self._wheel_verifier.verify(
                acquired,
                wheel_filename=selection.wheel_filename,
                supported_tags=frozenset(request.resolution_environment.supported_tags),
                budgets=self._inspection_budgets,
            )
            self._evidence_journal.append(
                request_fingerprint=request.request_fingerprint,
                evidence=verified.evidence,
            )
            return verified
        except PackageArtifactEvidenceJournalError:
            acquired.cleanup()
            raise PackageClosureVerificationError(
                "Package dependency evidence journal changed",
                code="package_closure_artifact_invalid",
            ) from None
        except Exception:
            acquired.cleanup()
            raise

    def _remaining_acquisition_budgets(
        self,
        closure_budgets: PackageClosureBudgetV1,
        *,
        consumed_requests: int,
        consumed_redirects: int,
    ) -> PackageAcquisitionBudgetV1:
        remaining_requests = closure_budgets.max_total_requests - consumed_requests
        remaining_redirects = closure_budgets.max_total_redirects - consumed_redirects
        if remaining_requests < 1 or remaining_redirects < 0:
            _reject_limit("requests")
        return PackageAcquisitionBudgetV1(
            max_transport_bytes=self._acquisition_budgets.max_transport_bytes,
            max_requests=min(
                self._acquisition_budgets.max_requests,
                remaining_requests,
            ),
            max_redirects=min(
                self._acquisition_budgets.max_redirects,
                remaining_redirects,
            ),
            max_wall_time_ms=self._acquisition_budgets.max_wall_time_ms,
        )

    @staticmethod
    def _require_selected_candidate(
        selection: PackageDependencySelectionV1,
        candidate: VerifiedWheelCandidate,
    ) -> None:
        envelope = candidate.authenticated_envelope
        wheel = candidate.evidence
        if (
            envelope is None
            or wheel.node_id != selection.node_id
            or wheel.distribution != selection.project_name
            or wheel.version != selection.version
            or wheel.wheel_filename != selection.wheel_filename
            or wheel.artifact_digest != selection.expected_artifact_digest
            or envelope.canonical_source_identity != selection.canonical_source_identity
        ):
            raise PackageClosureVerificationError(
                "Selected Package dependency evidence does not match",
                code="package_closure_artifact_invalid",
            )


def _require_envelope(
    candidate: VerifiedWheelCandidate,
) -> AuthenticatedSourceEnvelopeV1:
    envelope = candidate.authenticated_envelope
    if envelope is None:
        raise PackageClosureVerificationError(
            "Package closure Source evidence is missing",
            code="package_closure_artifact_invalid",
        )
    return envelope


def _reject_limit(dimension: PackageClosureLimitDimension) -> NoReturn:
    raise PackageClosureVerificationError(
        "Package closure exceeded a resource budget",
        code="package_resource_limit_exceeded",
        dimension=dimension,
    )


def _reject_conflict(message: str) -> NoReturn:
    raise PackageClosureVerificationError(
        message,
        code="package_closure_conflict",
    )


def _require_incremental_graph(
    *,
    root_node_id: str,
    selected_edges: set[tuple[str, str]],
    max_depth: int,
) -> None:
    nodes = {root_node_id}
    nodes.update(parent for parent, _child in selected_edges)
    nodes.update(child for _parent, child in selected_edges)
    children: dict[str, set[str]] = {node: set() for node in nodes}
    indegree = {node: 0 for node in nodes}
    for parent, child in selected_edges:
        if child in children[parent]:
            continue
        children[parent].add(child)
        indegree[child] += 1
    queue = sorted(node for node, count in indegree.items() if count == 0)
    depths = {root_node_id: 0}
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for child in sorted(children[node]):
            depths[child] = max(depths.get(child, 0), depths.get(node, 0) + 1)
            if depths[child] > max_depth:
                _reject_limit("graph")
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    if visited != len(nodes):
        _reject_conflict("Package dependency graph contains a cycle")


def _canonical_distribution(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Package distribution name must be a string")
    result = re.sub(r"[-_.]+", "-", value.strip()).lower()
    if not result or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result) is None:
        raise ValueError("Package distribution name is invalid")
    return result


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be positive")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase hexadecimal SHA-256")


def _exact_dict(
    value: object,
    *,
    fields: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} fields do not match the versioned schema")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


__all__ = [
    "PackageDependencyResolutionError",
    "PackageDependencyResolverPort",
    "PackageDependencySelectionRequestV1",
    "PackageDependencySelectionV1",
    "PackageRecursiveClosureOwner",
    "PackageRecursiveClosureRequestV2",
    "VerifiedPackageClosureCandidate",
]
