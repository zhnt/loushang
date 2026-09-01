"""Pure PLC9B3 closure-v2 verification over already-proved artifact evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, NoReturn, cast

from packaging.markers import InvalidMarker, Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
    canonicalize_source_identity,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
)

PACKAGE_RESOLUTION_ENVIRONMENT_VERSION = 1
NORMALIZED_PACKAGE_REQUIREMENT_VERSION = 1
RESOLVED_PACKAGE_REQUIREMENT_VERSION = 1
PACKAGE_CLOSURE_CANDIDATE_VERSION = 2
PACKAGE_CLOSURE_BUDGET_VERSION = 1
PACKAGE_CLOSURE_VERIFICATION_REQUEST_VERSION = 2
VERIFIED_CLOSURE_PLAN_NODE_VERSION = 2
VERIFIED_CLOSURE_PLAN_VERSION = 2

PackageClosureArtifactRole = Literal["root", "dependency"]
PackageClosureLimitDimension = Literal["graph", "solver", "requests"]

_ROLES = frozenset({"root", "dependency"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_NODE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_MARKER_ENVIRONMENT_KEYS = frozenset(
    {
        "implementation_name",
        "implementation_version",
        "os_name",
        "platform_machine",
        "platform_python_implementation",
        "platform_release",
        "platform_system",
        "platform_version",
        "python_full_version",
        "python_version",
        "sys_platform",
    }
)


class PackageClosureVerificationError(RuntimeError):
    """Stable fail-closed result from the pure closure verifier."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        dimension: PackageClosureLimitDimension | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = "resolving_closure"
        self.dimension = dimension


@dataclass(frozen=True, slots=True)
class PackageResolutionEnvironmentV1:
    marker_environment: tuple[tuple[str, str], ...]
    supported_tags: tuple[str, ...]
    environment_version: int = PACKAGE_RESOLUTION_ENVIRONMENT_VERSION

    def __post_init__(self) -> None:
        if self.marker_environment != tuple(sorted(self.marker_environment)):
            raise ValueError("Resolution marker environment must be canonical")
        if {key for key, _value in self.marker_environment} != (
            _MARKER_ENVIRONMENT_KEYS
        ):
            raise ValueError("Resolution marker environment fields are incomplete")
        if len({key for key, _value in self.marker_environment}) != len(
            self.marker_environment
        ):
            raise ValueError("Resolution marker environment fields must be unique")
        if any(not value for _key, value in self.marker_environment):
            raise ValueError("Resolution marker environment values cannot be empty")
        if (
            not self.supported_tags
            or self.supported_tags != tuple(sorted(set(self.supported_tags)))
            or any(not isinstance(tag, str) or not tag for tag in self.supported_tags)
        ):
            raise ValueError("Resolution supported tags must be sorted and unique")
        if self.environment_version != PACKAGE_RESOLUTION_ENVIRONMENT_VERSION:
            raise ValueError("Unsupported Package resolution environment")

    @classmethod
    def from_mapping(
        cls,
        marker_environment: Mapping[str, str],
        *,
        supported_tags: tuple[str, ...],
    ) -> PackageResolutionEnvironmentV1:
        if not isinstance(marker_environment, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in marker_environment.items()
        ):
            raise TypeError("Resolution marker environment must contain strings")
        return cls(
            marker_environment=tuple(sorted(marker_environment.items())),
            supported_tags=tuple(sorted(set(supported_tags))),
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())

    def as_marker_mapping(self) -> dict[str, str]:
        return dict(self.marker_environment)

    def to_dict(self) -> dict[str, object]:
        return {
            "environmentVersion": self.environment_version,
            "markerEnvironment": {key: value for key, value in self.marker_environment},
            "supportedTags": list(self.supported_tags),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageResolutionEnvironmentV1:
        document = _exact_dict(
            value,
            fields={"environmentVersion", "markerEnvironment", "supportedTags"},
            name="Package resolution environment",
        )
        marker_environment = document["markerEnvironment"]
        supported_tags = document["supportedTags"]
        if not isinstance(marker_environment, Mapping) or not isinstance(
            supported_tags, list
        ):
            raise TypeError("Package resolution environment fields are invalid")
        result = cls.from_mapping(
            {
                _wire_string(key, name="marker environment key"): _wire_string(
                    item,
                    name="marker environment value",
                )
                for key, item in marker_environment.items()
            },
            supported_tags=tuple(
                _wire_string(item, name="supported tag") for item in supported_tags
            ),
        )
        if (
            _wire_int(
                document["environmentVersion"],
                name="resolution environment version",
            )
            != PACKAGE_RESOLUTION_ENVIRONMENT_VERSION
        ):
            raise ValueError("Unsupported Package resolution environment")
        return result


@dataclass(frozen=True, slots=True)
class NormalizedPackageRequirementV1:
    project_name: str
    extras: tuple[str, ...]
    specifiers: tuple[tuple[str, str], ...]
    marker: str | None
    requirement_version: int = NORMALIZED_PACKAGE_REQUIREMENT_VERSION

    def __post_init__(self) -> None:
        if self.project_name != _canonical_distribution(self.project_name):
            raise ValueError("Requirement project name must be canonical")
        if self.extras != tuple(sorted(set(self.extras))) or any(
            extra != _canonical_distribution(extra) for extra in self.extras
        ):
            raise ValueError("Requirement extras must be canonical and unique")
        if self.specifiers != tuple(sorted(set(self.specifiers))):
            raise ValueError("Requirement specifiers must be canonical and unique")
        try:
            SpecifierSet(self.specifier_text)
        except InvalidSpecifier as exc:
            raise ValueError("Requirement specifiers are invalid") from exc
        if self.marker is not None:
            if not self.marker:
                raise ValueError("Requirement marker cannot be empty")
            try:
                if str(Marker(self.marker)) != self.marker:
                    raise ValueError("Requirement marker must be canonical")
            except InvalidMarker as exc:
                raise ValueError("Requirement marker is invalid") from exc
        if self.requirement_version != NORMALIZED_PACKAGE_REQUIREMENT_VERSION:
            raise ValueError("Unsupported normalized Package requirement")

    @classmethod
    def parse(cls, value: str) -> NormalizedPackageRequirementV1:
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise ValueError("Package requirement must be bounded and non-empty")
        try:
            parsed = Requirement(value)
        except InvalidRequirement as exc:
            raise ValueError("Package requirement is invalid") from exc
        if parsed.url is not None:
            raise ValueError("Package requirement cannot choose its Source origin")
        specifiers = tuple(
            sorted(
                (specifier.operator, specifier.version)
                for specifier in parsed.specifier
            )
        )
        return cls(
            project_name=_canonical_distribution(parsed.name),
            extras=tuple(
                sorted(_canonical_distribution(extra) for extra in parsed.extras)
            ),
            specifiers=specifiers,
            marker=str(parsed.marker) if parsed.marker is not None else None,
        )

    @property
    def specifier_text(self) -> str:
        return ",".join(operator + version for operator, version in self.specifiers)

    @property
    def canonical_text(self) -> str:
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        marker = f"; {self.marker}" if self.marker is not None else ""
        return f"{self.project_name}{extras}{self.specifier_text}{marker}"

    def to_dict(self) -> dict[str, object]:
        return {
            "extras": list(self.extras),
            "marker": self.marker,
            "projectName": self.project_name,
            "requirementVersion": self.requirement_version,
            "specifiers": [
                {"operator": operator, "version": version}
                for operator, version in self.specifiers
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> NormalizedPackageRequirementV1:
        document = _exact_dict(
            value,
            fields={
                "extras",
                "marker",
                "projectName",
                "requirementVersion",
                "specifiers",
            },
            name="normalized Package requirement",
        )
        extras = _wire_list(document["extras"], name="requirement extras")
        specifiers = _wire_list(document["specifiers"], name="requirement specifiers")
        parsed_specifiers: list[tuple[str, str]] = []
        for item in specifiers:
            specifier = _exact_dict(
                item,
                fields={"operator", "version"},
                name="requirement specifier",
            )
            parsed_specifiers.append(
                (
                    _wire_string(specifier["operator"], name="specifier operator"),
                    _wire_string(specifier["version"], name="specifier version"),
                )
            )
        return cls(
            project_name=_wire_string(
                document["projectName"], name="requirement project name"
            ),
            extras=tuple(
                _wire_string(item, name="requirement extra") for item in extras
            ),
            specifiers=tuple(parsed_specifiers),
            marker=_wire_optional_string(document["marker"], name="requirement marker"),
            requirement_version=_wire_int(
                document["requirementVersion"], name="requirement version"
            ),
        )


@dataclass(frozen=True, slots=True)
class ResolvedPackageRequirementV1:
    requirement: NormalizedPackageRequirementV1
    marker_applies: bool
    selected_node_id: str | None
    expected_source_identity: str | None
    expected_artifact_digest: str | None
    resolution_version: int = RESOLVED_PACKAGE_REQUIREMENT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, NormalizedPackageRequirementV1):
            raise TypeError("Normalized Package requirement is required")
        if type(self.marker_applies) is not bool:
            raise TypeError("Requirement marker result must be boolean")
        if self.selected_node_id is not None:
            _require_node_id(self.selected_node_id)
        if self.expected_source_identity is not None and (
            canonicalize_source_identity(self.expected_source_identity)
            != self.expected_source_identity
        ):
            raise ValueError("Expected dependency Source identity is not canonical")
        if self.expected_artifact_digest is not None:
            _require_sha256(
                self.expected_artifact_digest,
                name="expected dependency artifact digest",
            )
        if self.resolution_version != RESOLVED_PACKAGE_REQUIREMENT_VERSION:
            raise ValueError("Unsupported resolved Package requirement")

    @property
    def sort_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.requirement.canonical_text,
            self.selected_node_id or "",
            self.expected_source_identity or "",
            self.expected_artifact_digest or "",
            "1" if self.marker_applies else "0",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "expectedArtifactDigest": self.expected_artifact_digest,
            "expectedSourceIdentity": self.expected_source_identity,
            "markerApplies": self.marker_applies,
            "requirement": self.requirement.to_dict(),
            "resolutionVersion": self.resolution_version,
            "selectedNodeId": self.selected_node_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> ResolvedPackageRequirementV1:
        document = _exact_dict(
            value,
            fields={
                "expectedArtifactDigest",
                "expectedSourceIdentity",
                "markerApplies",
                "requirement",
                "resolutionVersion",
                "selectedNodeId",
            },
            name="resolved Package requirement",
        )
        return cls(
            requirement=NormalizedPackageRequirementV1.from_dict(
                document["requirement"]
            ),
            marker_applies=_wire_bool(
                document["markerApplies"], name="requirement marker result"
            ),
            selected_node_id=_wire_optional_string(
                document["selectedNodeId"], name="selected node id"
            ),
            expected_source_identity=_wire_optional_string(
                document["expectedSourceIdentity"],
                name="expected Source identity",
            ),
            expected_artifact_digest=_wire_optional_string(
                document["expectedArtifactDigest"],
                name="expected artifact digest",
            ),
            resolution_version=_wire_int(
                document["resolutionVersion"], name="resolution version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageClosureArtifactCandidateV2:
    role: PackageClosureArtifactRole
    envelope: AuthenticatedSourceEnvelopeV1
    acquisition: BoundedAcquisitionReceiptV1
    wheel: VerifiedWheelArtifactV1
    requirements: tuple[ResolvedPackageRequirementV1, ...]
    selected_extras: tuple[str, ...] = ()
    candidate_version: int = PACKAGE_CLOSURE_CANDIDATE_VERSION

    def __post_init__(self) -> None:
        if self.role not in _ROLES:
            raise ValueError("Unsupported Package closure artifact role")
        if not isinstance(self.envelope, AuthenticatedSourceEnvelopeV1):
            raise TypeError("Authenticated Source envelope is required")
        if not isinstance(self.acquisition, BoundedAcquisitionReceiptV1):
            raise TypeError("Bounded acquisition receipt is required")
        if not isinstance(self.wheel, VerifiedWheelArtifactV1):
            raise TypeError("Verified wheel artifact is required")
        if any(
            not isinstance(requirement, ResolvedPackageRequirementV1)
            for requirement in self.requirements
        ):
            raise TypeError("Resolved Package requirements are required")
        canonical_requirements = tuple(
            sorted(self.requirements, key=lambda requirement: requirement.sort_key)
        )
        object.__setattr__(self, "requirements", canonical_requirements)
        if self.selected_extras != tuple(sorted(set(self.selected_extras))) or any(
            extra != _canonical_distribution(extra) for extra in self.selected_extras
        ):
            raise ValueError("Selected Package extras must be canonical and unique")
        if self.candidate_version != PACKAGE_CLOSURE_CANDIDATE_VERSION:
            raise ValueError("Unsupported Package closure artifact candidate")

    @property
    def node_id(self) -> str:
        return self.wheel.node_id


@dataclass(frozen=True, slots=True)
class PackageClosureBudgetV1:
    max_nodes: int = 64
    max_edges: int = 256
    max_depth: int = 32
    max_solver_steps: int = 4096
    max_marker_steps: int = 4096
    max_artifacts: int = 64
    max_total_requests: int = 256
    max_total_redirects: int = 128
    budget_version: int = PACKAGE_CLOSURE_BUDGET_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.max_nodes, "closure node budget"),
            (self.max_edges, "closure edge budget"),
            (self.max_depth, "closure depth budget"),
            (self.max_solver_steps, "closure solver-step budget"),
            (self.max_marker_steps, "closure marker-step budget"),
            (self.max_artifacts, "closure artifact budget"),
            (self.max_total_requests, "closure request budget"),
            (self.max_total_redirects, "closure redirect budget"),
        ):
            _require_nonnegative(value, name=name)
        if self.budget_version != PACKAGE_CLOSURE_BUDGET_VERSION:
            raise ValueError("Unsupported Package closure budget")

    def to_dict(self) -> dict[str, object]:
        return {
            "budgetVersion": self.budget_version,
            "maxArtifacts": self.max_artifacts,
            "maxDepth": self.max_depth,
            "maxEdges": self.max_edges,
            "maxMarkerSteps": self.max_marker_steps,
            "maxNodes": self.max_nodes,
            "maxSolverSteps": self.max_solver_steps,
            "maxTotalRedirects": self.max_total_redirects,
            "maxTotalRequests": self.max_total_requests,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageClosureBudgetV1:
        document = _exact_dict(
            value,
            fields={
                "budgetVersion",
                "maxArtifacts",
                "maxDepth",
                "maxEdges",
                "maxMarkerSteps",
                "maxNodes",
                "maxSolverSteps",
                "maxTotalRedirects",
                "maxTotalRequests",
            },
            name="Package closure budget",
        )
        return cls(
            max_nodes=_wire_int(document["maxNodes"], name="node budget"),
            max_edges=_wire_int(document["maxEdges"], name="edge budget"),
            max_depth=_wire_int(document["maxDepth"], name="depth budget"),
            max_solver_steps=_wire_int(
                document["maxSolverSteps"], name="solver-step budget"
            ),
            max_marker_steps=_wire_int(
                document["maxMarkerSteps"], name="marker-step budget"
            ),
            max_artifacts=_wire_int(document["maxArtifacts"], name="artifact budget"),
            max_total_requests=_wire_int(
                document["maxTotalRequests"], name="request budget"
            ),
            max_total_redirects=_wire_int(
                document["maxTotalRedirects"], name="redirect budget"
            ),
            budget_version=_wire_int(
                document["budgetVersion"], name="closure budget version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageClosureVerificationRequestV2:
    root_node_id: str
    candidates: tuple[PackageClosureArtifactCandidateV2, ...]
    resolution_environment: PackageResolutionEnvironmentV1
    budgets: PackageClosureBudgetV1
    root_extras: tuple[str, ...] = ()
    request_version: int = PACKAGE_CLOSURE_VERIFICATION_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_node_id(self.root_node_id)
        if not self.candidates or any(
            not isinstance(candidate, PackageClosureArtifactCandidateV2)
            for candidate in self.candidates
        ):
            raise TypeError("Package closure candidates are required")
        if not isinstance(self.resolution_environment, PackageResolutionEnvironmentV1):
            raise TypeError("Package resolution environment is required")
        if not isinstance(self.budgets, PackageClosureBudgetV1):
            raise TypeError("Package closure budgets are required")
        if self.root_extras != tuple(sorted(set(self.root_extras))) or any(
            extra != _canonical_distribution(extra) for extra in self.root_extras
        ):
            raise ValueError("Root Package extras must be canonical and unique")
        if self.request_version != PACKAGE_CLOSURE_VERIFICATION_REQUEST_VERSION:
            raise ValueError("Unsupported Package closure verification request")


@dataclass(frozen=True, slots=True)
class VerifiedClosurePlanNodeV2:
    node_id: str
    role: PackageClosureArtifactRole
    distribution: str
    version: str
    canonical_source_identity: str
    source_envelope_fingerprint: str
    acquisition_receipt_fingerprint: str
    wheel_evidence_fingerprint: str
    artifact_digest: str
    extraction_tree_digest: str
    selected_extras: tuple[str, ...]
    requirements: tuple[ResolvedPackageRequirementV1, ...]
    selected_edges: tuple[str, ...]
    node_version: int = VERIFIED_CLOSURE_PLAN_NODE_VERSION

    def __post_init__(self) -> None:
        _require_node_id(self.node_id)
        if self.role not in _ROLES:
            raise ValueError("Unsupported verified closure node role")
        if self.distribution != _canonical_distribution(self.distribution):
            raise ValueError("Verified closure distribution must be canonical")
        _require_nonempty(self.version, name="verified closure version")
        if canonicalize_source_identity(self.canonical_source_identity) != (
            self.canonical_source_identity
        ):
            raise ValueError("Verified closure Source identity is not canonical")
        for value, name in (
            (self.source_envelope_fingerprint, "Source envelope fingerprint"),
            (self.acquisition_receipt_fingerprint, "acquisition fingerprint"),
            (self.wheel_evidence_fingerprint, "wheel evidence fingerprint"),
            (self.artifact_digest, "artifact digest"),
            (self.extraction_tree_digest, "extraction tree digest"),
        ):
            _require_sha256(value, name=name)
        if self.selected_extras != tuple(sorted(set(self.selected_extras))) or any(
            extra != _canonical_distribution(extra) for extra in self.selected_extras
        ):
            raise ValueError("Verified closure extras must be canonical and unique")
        if self.requirements != tuple(
            sorted(self.requirements, key=lambda requirement: requirement.sort_key)
        ):
            raise ValueError("Verified closure requirements must be canonical")
        if self.selected_edges != tuple(sorted(set(self.selected_edges))):
            raise ValueError("Verified closure edges must be canonical and unique")
        expected_edges: set[str] = set()
        for requirement in self.requirements:
            if requirement.marker_applies:
                if (
                    requirement.selected_node_id is None
                    or requirement.expected_source_identity is None
                    or requirement.expected_artifact_digest is None
                ):
                    raise ValueError(
                        "Active verified requirement lacks selected evidence"
                    )
                expected_edges.add(requirement.selected_node_id)
            elif any(
                item is not None
                for item in (
                    requirement.selected_node_id,
                    requirement.expected_source_identity,
                    requirement.expected_artifact_digest,
                )
            ):
                raise ValueError("Inactive verified requirement selected an artifact")
        if self.selected_edges != tuple(sorted(expected_edges)):
            raise ValueError("Verified closure edges do not match requirements")
        if self.node_version != VERIFIED_CLOSURE_PLAN_NODE_VERSION:
            raise ValueError("Unsupported verified closure plan node")

    def to_dict(self) -> dict[str, object]:
        return {
            "acquisitionReceiptFingerprint": self.acquisition_receipt_fingerprint,
            "artifactDigest": self.artifact_digest,
            "canonicalSourceIdentity": self.canonical_source_identity,
            "distribution": self.distribution,
            "extractionTreeDigest": self.extraction_tree_digest,
            "nodeId": self.node_id,
            "nodeVersion": self.node_version,
            "requirements": [item.to_dict() for item in self.requirements],
            "role": self.role,
            "selectedEdges": list(self.selected_edges),
            "selectedExtras": list(self.selected_extras),
            "sourceEnvelopeFingerprint": self.source_envelope_fingerprint,
            "version": self.version,
            "wheelEvidenceFingerprint": self.wheel_evidence_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> VerifiedClosurePlanNodeV2:
        document = _exact_dict(
            value,
            fields={
                "acquisitionReceiptFingerprint",
                "artifactDigest",
                "canonicalSourceIdentity",
                "distribution",
                "extractionTreeDigest",
                "nodeId",
                "nodeVersion",
                "requirements",
                "role",
                "selectedEdges",
                "selectedExtras",
                "sourceEnvelopeFingerprint",
                "version",
                "wheelEvidenceFingerprint",
            },
            name="verified closure plan node",
        )
        requirements = _wire_list(
            document["requirements"], name="verified closure requirements"
        )
        edges = _wire_list(document["selectedEdges"], name="selected edges")
        extras = _wire_list(document["selectedExtras"], name="selected extras")
        return cls(
            node_id=_wire_string(document["nodeId"], name="node id"),
            role=cast(
                PackageClosureArtifactRole,
                _wire_string(document["role"], name="closure role"),
            ),
            distribution=_wire_string(document["distribution"], name="distribution"),
            version=_wire_string(document["version"], name="version"),
            canonical_source_identity=_wire_string(
                document["canonicalSourceIdentity"], name="Source identity"
            ),
            source_envelope_fingerprint=_wire_string(
                document["sourceEnvelopeFingerprint"],
                name="Source envelope fingerprint",
            ),
            acquisition_receipt_fingerprint=_wire_string(
                document["acquisitionReceiptFingerprint"],
                name="acquisition fingerprint",
            ),
            wheel_evidence_fingerprint=_wire_string(
                document["wheelEvidenceFingerprint"],
                name="wheel evidence fingerprint",
            ),
            artifact_digest=_wire_string(
                document["artifactDigest"], name="artifact digest"
            ),
            extraction_tree_digest=_wire_string(
                document["extractionTreeDigest"], name="tree digest"
            ),
            selected_extras=tuple(
                _wire_string(item, name="selected extra") for item in extras
            ),
            requirements=tuple(
                ResolvedPackageRequirementV1.from_dict(item) for item in requirements
            ),
            selected_edges=tuple(
                _wire_string(item, name="selected edge") for item in edges
            ),
            node_version=_wire_int(document["nodeVersion"], name="node version"),
        )


@dataclass(frozen=True, slots=True)
class VerifiedClosurePlanV2:
    operation_id: str
    attempt_epoch: int
    root_node_id: str
    resolution_environment_fingerprint: str
    nodes: tuple[VerifiedClosurePlanNodeV2, ...]
    node_count: int
    edge_count: int
    max_depth: int
    graph_digest: str
    plan_version: int = VERIFIED_CLOSURE_PLAN_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.operation_id, name="closure operation id")
        _require_positive(self.attempt_epoch, name="closure attempt epoch")
        _require_node_id(self.root_node_id)
        _require_sha256(
            self.resolution_environment_fingerprint,
            name="resolution environment fingerprint",
        )
        if not self.nodes or self.nodes != tuple(
            sorted(self.nodes, key=lambda node: node.node_id)
        ):
            raise ValueError("Verified closure nodes must be canonical")
        if self.node_count != len(self.nodes):
            raise ValueError("Verified closure node count does not match")
        if self.edge_count != sum(len(node.selected_edges) for node in self.nodes):
            raise ValueError("Verified closure edge count does not match")
        _require_nonnegative(self.max_depth, name="verified closure depth")
        by_id = {node.node_id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("Verified closure nodes must be unique")
        distributions = [node.distribution for node in self.nodes]
        if len(distributions) != len(set(distributions)):
            raise ValueError("Verified closure distributions must be unique")
        root = by_id.get(self.root_node_id)
        if root is None or root.role != "root":
            raise ValueError("Verified closure plan has no designated root")
        if sum(node.role == "root" for node in self.nodes) != 1:
            raise ValueError("Verified closure plan must have exactly one root")
        edges = {node.node_id: set(node.selected_edges) for node in self.nodes}
        if any(child not in by_id for children in edges.values() for child in children):
            raise ValueError("Verified closure plan contains an unknown edge")
        requested_extras: dict[str, set[str]] = {
            node.node_id: set() for node in self.nodes
        }
        for node in self.nodes:
            for resolution in node.requirements:
                if not resolution.marker_applies:
                    continue
                selected_id = cast(str, resolution.selected_node_id)
                target = by_id[selected_id]
                if target.role != "dependency":
                    raise ValueError("Verified closure edge targets the root")
                if target.distribution != resolution.requirement.project_name:
                    raise ValueError("Verified closure edge name does not match")
                try:
                    selected_version = Version(target.version)
                    specifier = SpecifierSet(resolution.requirement.specifier_text)
                except (InvalidVersion, InvalidSpecifier) as exc:
                    raise ValueError(
                        "Verified closure edge version is invalid"
                    ) from exc
                if specifier and not specifier.contains(
                    selected_version,
                    prereleases=True,
                ):
                    raise ValueError("Verified closure edge version does not satisfy")
                if (
                    target.canonical_source_identity
                    != resolution.expected_source_identity
                    or target.artifact_digest != resolution.expected_artifact_digest
                ):
                    raise ValueError("Verified closure edge evidence does not match")
                requested_extras[selected_id].update(resolution.requirement.extras)
        for node in self.nodes:
            if node.role == "dependency" and node.selected_extras != tuple(
                sorted(requested_extras[node.node_id])
            ):
                raise ValueError("Verified closure extras do not match incoming edges")
        try:
            observed_depth, visited = _verify_acyclic_reachable(
                root_node_id=self.root_node_id,
                selected_edges=edges,
                max_depth=self.max_depth,
            )
        except PackageClosureVerificationError as exc:
            raise ValueError("Verified closure plan graph is invalid") from exc
        if observed_depth != self.max_depth or visited != set(by_id):
            raise ValueError("Verified closure plan graph facts do not match")
        _require_sha256(self.graph_digest, name="closure graph digest")
        if (
            self.graph_digest
            != sha256(self.canonical_graph_json.encode("utf-8")).hexdigest()
        ):
            raise ValueError("Verified closure graph digest does not match")
        if self.plan_version != VERIFIED_CLOSURE_PLAN_VERSION:
            raise ValueError("Unsupported verified closure plan")

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        attempt_epoch: int,
        root_node_id: str,
        resolution_environment_fingerprint: str,
        nodes: tuple[VerifiedClosurePlanNodeV2, ...],
        max_depth: int,
    ) -> VerifiedClosurePlanV2:
        canonical_nodes = tuple(sorted(nodes, key=lambda node: node.node_id))
        graph = _graph_document(
            root_node_id=root_node_id,
            resolution_environment_fingerprint=(resolution_environment_fingerprint),
            nodes=canonical_nodes,
        )
        return cls(
            operation_id=operation_id,
            attempt_epoch=attempt_epoch,
            root_node_id=root_node_id,
            resolution_environment_fingerprint=resolution_environment_fingerprint,
            nodes=canonical_nodes,
            node_count=len(canonical_nodes),
            edge_count=sum(len(node.selected_edges) for node in canonical_nodes),
            max_depth=max_depth,
            graph_digest=sha256(canonical_json_bytes(graph)).hexdigest(),
        )

    @property
    def canonical_graph_json(self) -> str:
        return canonical_json_bytes(
            _graph_document(
                root_node_id=self.root_node_id,
                resolution_environment_fingerprint=(
                    self.resolution_environment_fingerprint
                ),
                nodes=self.nodes,
            )
        ).decode("utf-8")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "edgeCount": self.edge_count,
            "graphDigest": self.graph_digest,
            "maxDepth": self.max_depth,
            "nodeCount": self.node_count,
            "nodes": [node.to_dict() for node in self.nodes],
            "operationId": self.operation_id,
            "planVersion": self.plan_version,
            "resolutionEnvironmentFingerprint": (
                self.resolution_environment_fingerprint
            ),
            "rootNodeId": self.root_node_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> VerifiedClosurePlanV2:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "edgeCount",
                "graphDigest",
                "maxDepth",
                "nodeCount",
                "nodes",
                "operationId",
                "planVersion",
                "resolutionEnvironmentFingerprint",
                "rootNodeId",
            },
            name="verified closure plan",
        )
        nodes = _wire_list(document["nodes"], name="verified closure nodes")
        return cls(
            operation_id=_wire_string(
                document["operationId"], name="closure operation id"
            ),
            attempt_epoch=_wire_int(
                document["attemptEpoch"], name="closure attempt epoch"
            ),
            root_node_id=_wire_string(document["rootNodeId"], name="root node id"),
            resolution_environment_fingerprint=_wire_string(
                document["resolutionEnvironmentFingerprint"],
                name="resolution environment fingerprint",
            ),
            nodes=tuple(VerifiedClosurePlanNodeV2.from_dict(item) for item in nodes),
            node_count=_wire_int(document["nodeCount"], name="node count"),
            edge_count=_wire_int(document["edgeCount"], name="edge count"),
            max_depth=_wire_int(document["maxDepth"], name="maximum depth"),
            graph_digest=_wire_string(
                document["graphDigest"], name="closure graph digest"
            ),
            plan_version=_wire_int(
                document["planVersion"], name="closure plan version"
            ),
        )


class PackageClosureVerifier:
    """Validate a complete artifact graph without I/O or publication authority."""

    def verify(self, value: object) -> VerifiedClosurePlanV2:
        if not isinstance(value, PackageClosureVerificationRequestV2):
            raise PackageClosureVerificationError(
                "Package closure evidence version is unsupported",
                code="package_closure_evidence_unsupported",
            )
        candidates = tuple(sorted(value.candidates, key=lambda item: item.node_id))
        budgets = value.budgets
        if (
            len(candidates) > budgets.max_nodes
            or len(candidates) > budgets.max_artifacts
        ):
            _reject_limit("graph")
        by_id = {candidate.node_id: candidate for candidate in candidates}
        if len(by_id) != len(candidates):
            _reject_conflict("Package closure contains duplicate node identities")
        root = by_id.get(value.root_node_id)
        if root is None or root.role != "root":
            _reject_invalid("Package closure has no designated root")
        if sum(candidate.role == "root" for candidate in candidates) != 1:
            _reject_conflict("Package closure has multiple designated roots")
        if root.selected_extras != value.root_extras:
            _reject_conflict("Root Package extras changed during resolution")

        operations = {candidate.wheel.operation_id for candidate in candidates}
        attempts = {candidate.wheel.attempt_epoch for candidate in candidates}
        if len(operations) != 1 or len(attempts) != 1:
            _reject_invalid("Package closure evidence crosses operation identity")
        for candidate in candidates:
            if _SAFE_NODE_ID.fullmatch(candidate.node_id) is None:
                _reject_invalid("Package closure node identity is invalid")
            self._verify_evidence_chain(candidate, value.resolution_environment)

        distributions = [candidate.wheel.distribution for candidate in candidates]
        if len(distributions) != len(set(distributions)):
            _reject_conflict("Package closure contains duplicate distributions")

        total_requests = sum(
            candidate.acquisition.request_count for candidate in candidates
        )
        total_redirects = sum(
            candidate.acquisition.redirect_count for candidate in candidates
        )
        if (
            total_requests > budgets.max_total_requests
            or total_redirects > budgets.max_total_redirects
        ):
            _reject_limit("requests")

        selected_edges: dict[str, set[str]] = {
            candidate.node_id: set() for candidate in candidates
        }
        requested_extras: dict[str, set[str]] = {
            candidate.node_id: set() for candidate in candidates
        }
        solver_steps = 0
        marker_steps = 0
        marker_environment = value.resolution_environment.as_marker_mapping()
        for candidate in candidates:
            for resolution in candidate.requirements:
                solver_steps += 1
                if solver_steps > budgets.max_solver_steps:
                    _reject_limit("solver")
                applies = True
                marker = resolution.requirement.marker
                if marker is not None:
                    marker_steps += 1
                    if marker_steps > budgets.max_marker_steps:
                        _reject_limit("solver")
                    try:
                        extras = candidate.selected_extras or ("",)
                        applies = any(
                            Marker(marker).evaluate(
                                marker_environment | {"extra": extra},
                                context="metadata",
                            )
                            for extra in extras
                        )
                    except (InvalidMarker, KeyError, TypeError, ValueError):
                        _reject_conflict(
                            "Package dependency marker is not reproducible"
                        )
                if applies != resolution.marker_applies:
                    _reject_conflict("Package dependency marker evidence changed")
                if not applies:
                    if any(
                        item is not None
                        for item in (
                            resolution.selected_node_id,
                            resolution.expected_source_identity,
                            resolution.expected_artifact_digest,
                        )
                    ):
                        _reject_conflict(
                            "Inactive Package requirement selected an artifact"
                        )
                    continue
                selected_id = resolution.selected_node_id
                if selected_id is None:
                    _reject_invalid("Package closure is missing a dependency")
                target = by_id.get(selected_id)
                if target is None:
                    _reject_invalid("Package closure is missing a dependency")
                if target.role != "dependency":
                    _reject_conflict("Package dependency selected the root artifact")
                if target.wheel.distribution != resolution.requirement.project_name:
                    _reject_conflict("Package dependency name does not match selection")
                try:
                    version = Version(target.wheel.version)
                    specifier = SpecifierSet(resolution.requirement.specifier_text)
                except (InvalidVersion, InvalidSpecifier):
                    _reject_invalid("Package dependency version is invalid")
                if specifier and not specifier.contains(version, prereleases=True):
                    _reject_conflict("Package dependency version does not satisfy")
                if (
                    resolution.expected_source_identity is None
                    or resolution.expected_source_identity
                    != target.envelope.canonical_source_identity
                ):
                    _reject_invalid("Package dependency origin is unauthorized")
                if (
                    resolution.expected_artifact_digest is None
                    or resolution.expected_artifact_digest
                    != target.wheel.artifact_digest
                ):
                    _reject_invalid("Package dependency digest does not match")
                selected_edges[candidate.node_id].add(selected_id)
                requested_extras[selected_id].update(resolution.requirement.extras)

        for candidate in candidates:
            if candidate.role == "dependency" and candidate.selected_extras != tuple(
                sorted(requested_extras[candidate.node_id])
            ):
                _reject_conflict("Selected Package extras do not match incoming edges")

        if sum(map(len, selected_edges.values())) > budgets.max_edges:
            _reject_limit("graph")
        max_depth, visited = _verify_acyclic_reachable(
            root_node_id=value.root_node_id,
            selected_edges=selected_edges,
            max_depth=budgets.max_depth,
        )
        if visited != set(by_id):
            _reject_conflict("Package closure contains unreachable artifacts")

        plan_nodes = tuple(
            VerifiedClosurePlanNodeV2(
                node_id=candidate.node_id,
                role=candidate.role,
                distribution=candidate.wheel.distribution,
                version=candidate.wheel.version,
                canonical_source_identity=(
                    candidate.envelope.canonical_source_identity
                ),
                source_envelope_fingerprint=candidate.envelope.fingerprint,
                acquisition_receipt_fingerprint=candidate.acquisition.fingerprint,
                wheel_evidence_fingerprint=candidate.wheel.fingerprint,
                artifact_digest=candidate.wheel.artifact_digest,
                extraction_tree_digest=candidate.wheel.extraction_tree_digest,
                selected_extras=candidate.selected_extras,
                requirements=candidate.requirements,
                selected_edges=tuple(sorted(selected_edges[candidate.node_id])),
            )
            for candidate in candidates
        )
        return VerifiedClosurePlanV2.create(
            operation_id=next(iter(operations)),
            attempt_epoch=next(iter(attempts)),
            root_node_id=value.root_node_id,
            resolution_environment_fingerprint=(
                value.resolution_environment.fingerprint
            ),
            nodes=plan_nodes,
            max_depth=max_depth,
        )

    @staticmethod
    def _verify_evidence_chain(
        candidate: PackageClosureArtifactCandidateV2,
        environment: PackageResolutionEnvironmentV1,
    ) -> None:
        envelope = candidate.envelope
        receipt = candidate.acquisition
        wheel = candidate.wheel
        if envelope.authentication_decision != "authorized":
            _reject_invalid("Package closure Source was not authorized")
        identity = (wheel.operation_id, wheel.attempt_epoch, wheel.node_id)
        if (
            (envelope.operation_id, wheel.node_id)
            != (
                wheel.operation_id,
                envelope.node_id,
            )
            or (receipt.operation_id, receipt.attempt_epoch, receipt.node_id)
            != identity
            or receipt.envelope_fingerprint != envelope.fingerprint
            or receipt.actual_byte_digest != wheel.artifact_digest
            or receipt.actual_byte_count != wheel.artifact_size
            or (
                envelope.expected_artifact_digest is not None
                and envelope.expected_artifact_digest != wheel.artifact_digest
            )
            or not set(wheel.compatible_tags).intersection(environment.supported_tags)
        ):
            _reject_invalid("Package closure artifact evidence does not match")


def _verify_acyclic_reachable(
    *,
    root_node_id: str,
    selected_edges: Mapping[str, set[str]],
    max_depth: int,
) -> tuple[int, set[str]]:
    visiting: set[str] = set()
    visited: set[str] = set()
    heights: dict[str, int] = {}

    def height(node_id: str) -> int:
        if node_id in visiting:
            _reject_conflict("Package closure contains a dependency cycle")
        if node_id in heights:
            return heights[node_id]
        visiting.add(node_id)
        child_heights = tuple(height(child) for child in selected_edges[node_id])
        visiting.remove(node_id)
        visited.add(node_id)
        result = 0 if not child_heights else 1 + max(child_heights)
        heights[node_id] = result
        return result

    observed_max_depth = height(root_node_id)
    if observed_max_depth > max_depth:
        _reject_limit("graph")
    return observed_max_depth, visited


def _graph_document(
    *,
    root_node_id: str,
    resolution_environment_fingerprint: str,
    nodes: tuple[VerifiedClosurePlanNodeV2, ...],
) -> dict[str, object]:
    return {
        "nodes": [node.to_dict() for node in nodes],
        "resolutionEnvironmentFingerprint": resolution_environment_fingerprint,
        "rootNodeId": root_node_id,
    }


def _reject_invalid(message: str) -> NoReturn:
    raise PackageClosureVerificationError(
        message,
        code="package_closure_artifact_invalid",
    )


def _reject_conflict(message: str) -> NoReturn:
    raise PackageClosureVerificationError(
        message,
        code="package_closure_conflict",
    )


def _reject_limit(dimension: PackageClosureLimitDimension) -> NoReturn:
    raise PackageClosureVerificationError(
        "Package closure exceeded a resource budget",
        code="package_resource_limit_exceeded",
        dimension=dimension,
    )


def _canonical_distribution(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Package distribution name must be a string")
    result = re.sub(r"[-_.]+", "-", value.strip()).lower()
    if not result or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result):
        raise ValueError("Package distribution name is invalid")
    return result


def _require_node_id(value: str) -> None:
    if not isinstance(value, str) or _SAFE_NODE_ID.fullmatch(value) is None:
        raise ValueError("Package closure node id is invalid")


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase hexadecimal SHA-256")


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be positive")


def _require_nonnegative(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be non-negative")


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _exact_dict(
    value: object,
    *,
    fields: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    document = dict(value)
    if set(document) != fields:
        raise ValueError(f"{name} fields do not match the versioned schema")
    return cast(dict[str, object], document)


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be boolean")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_list(value: object, *, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return value


__all__ = [
    "NormalizedPackageRequirementV1",
    "PackageClosureArtifactCandidateV2",
    "PackageClosureBudgetV1",
    "PackageClosureVerificationError",
    "PackageClosureVerificationRequestV2",
    "PackageClosureVerifier",
    "PackageResolutionEnvironmentV1",
    "ResolvedPackageRequirementV1",
    "VerifiedClosurePlanNodeV2",
    "VerifiedClosurePlanV2",
]
