"""Dark typed publication records for the PLC9B Package transaction owner."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, cast

from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

VERIFIED_ARTIFACT_REF_VERSION = 1
PLUGIN_REVISION_REF_VERSION = 1
DEPENDENCY_CLOSURE_NODE_VERSION = 2
DEPENDENCY_CLOSURE_LOCK_VERSION = 2
COMMITTED_PACKAGE_SET_REF_VERSION = 1

StableRefKind = Literal["verified_artifact", "plugin_revision"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


@dataclass(frozen=True, slots=True)
class VerifiedArtifactRefV1:
    """Store-issued stable ref whose type can only represent a dependency."""

    ref_id: str
    store_identity: str
    store_revision: str
    distribution: str
    version: str
    artifact_digest: str
    extraction_tree_digest: str
    ref_version: int = VERIFIED_ARTIFACT_REF_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.ref_id, name="verified artifact ref id")
        _require_safe_id(self.store_identity, name="artifact store identity")
        _require_safe_id(self.store_revision, name="artifact store revision")
        _require_distribution(self.distribution)
        _require_nonempty(self.version, name="artifact version")
        _require_sha256(self.artifact_digest, name="artifact digest")
        _require_sha256(self.extraction_tree_digest, name="extraction tree digest")
        if self.ref_version != VERIFIED_ARTIFACT_REF_VERSION:
            raise ValueError("Unsupported verified artifact ref")
        if self.ref_id != _fingerprint(self._identity_dict()):
            raise ValueError("Verified artifact ref id does not match")

    @classmethod
    def create(
        cls,
        *,
        store_identity: str,
        store_revision: str,
        distribution: str,
        version: str,
        artifact_digest: str,
        extraction_tree_digest: str,
    ) -> VerifiedArtifactRefV1:
        values = {
            "artifactDigest": artifact_digest,
            "distribution": distribution,
            "extractionTreeDigest": extraction_tree_digest,
            "refVersion": VERIFIED_ARTIFACT_REF_VERSION,
            "storeIdentity": store_identity,
            "storeRevision": store_revision,
            "version": version,
        }
        return cls(
            ref_id=_fingerprint(values),
            store_identity=store_identity,
            store_revision=store_revision,
            distribution=distribution,
            version=version,
            artifact_digest=artifact_digest,
            extraction_tree_digest=extraction_tree_digest,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "artifactDigest": self.artifact_digest,
            "distribution": self.distribution,
            "extractionTreeDigest": self.extraction_tree_digest,
            "refVersion": self.ref_version,
            "storeIdentity": self.store_identity,
            "storeRevision": self.store_revision,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, object]:
        return {"refId": self.ref_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> VerifiedArtifactRefV1:
        document = _exact_dict(
            value,
            fields={
                "artifactDigest",
                "distribution",
                "extractionTreeDigest",
                "refId",
                "refVersion",
                "storeIdentity",
                "storeRevision",
                "version",
            },
            name="verified artifact ref",
        )
        return cls(
            ref_id=_wire_string(document["refId"], name="ref id"),
            store_identity=_wire_string(
                document["storeIdentity"], name="store identity"
            ),
            store_revision=_wire_string(
                document["storeRevision"], name="store revision"
            ),
            distribution=_wire_string(document["distribution"], name="distribution"),
            version=_wire_string(document["version"], name="version"),
            artifact_digest=_wire_string(
                document["artifactDigest"], name="artifact digest"
            ),
            extraction_tree_digest=_wire_string(
                document["extractionTreeDigest"], name="extraction tree digest"
            ),
            ref_version=_wire_int(document["refVersion"], name="ref version"),
        )


@dataclass(frozen=True, slots=True)
class PluginRevisionRefV1:
    """Store-issued physical ref for the one designated Plugin root."""

    ref_id: str
    store_identity: str
    store_revision: str
    installation_id: str
    plugin_id: str
    distribution: str
    version: str
    artifact_digest: str
    extraction_tree_digest: str
    ref_version: int = PLUGIN_REVISION_REF_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.ref_id, name="Plugin revision ref id")
        for value, name in (
            (self.store_identity, "Plugin revision store identity"),
            (self.store_revision, "Plugin revision store revision"),
            (self.installation_id, "Installation identity"),
            (self.plugin_id, "Plugin identity"),
        ):
            _require_safe_id(value, name=name)
        _require_distribution(self.distribution)
        _require_nonempty(self.version, name="Plugin revision version")
        _require_sha256(self.artifact_digest, name="Plugin artifact digest")
        _require_sha256(
            self.extraction_tree_digest,
            name="Plugin extraction tree digest",
        )
        if self.ref_version != PLUGIN_REVISION_REF_VERSION:
            raise ValueError("Unsupported Plugin revision ref")
        if self.ref_id != _fingerprint(self._identity_dict()):
            raise ValueError("Plugin revision ref id does not match")

    @classmethod
    def create(
        cls,
        *,
        store_identity: str,
        store_revision: str,
        installation_id: str,
        plugin_id: str,
        distribution: str,
        version: str,
        artifact_digest: str,
        extraction_tree_digest: str,
    ) -> PluginRevisionRefV1:
        values = {
            "artifactDigest": artifact_digest,
            "distribution": distribution,
            "extractionTreeDigest": extraction_tree_digest,
            "installationId": installation_id,
            "pluginId": plugin_id,
            "refVersion": PLUGIN_REVISION_REF_VERSION,
            "storeIdentity": store_identity,
            "storeRevision": store_revision,
            "version": version,
        }
        return cls(
            ref_id=_fingerprint(values),
            store_identity=store_identity,
            store_revision=store_revision,
            installation_id=installation_id,
            plugin_id=plugin_id,
            distribution=distribution,
            version=version,
            artifact_digest=artifact_digest,
            extraction_tree_digest=extraction_tree_digest,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "artifactDigest": self.artifact_digest,
            "distribution": self.distribution,
            "extractionTreeDigest": self.extraction_tree_digest,
            "installationId": self.installation_id,
            "pluginId": self.plugin_id,
            "refVersion": self.ref_version,
            "storeIdentity": self.store_identity,
            "storeRevision": self.store_revision,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, object]:
        return {"refId": self.ref_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PluginRevisionRefV1:
        document = _exact_dict(
            value,
            fields={
                "artifactDigest",
                "distribution",
                "extractionTreeDigest",
                "installationId",
                "pluginId",
                "refId",
                "refVersion",
                "storeIdentity",
                "storeRevision",
                "version",
            },
            name="Plugin revision ref",
        )
        return cls(
            ref_id=_wire_string(document["refId"], name="ref id"),
            store_identity=_wire_string(
                document["storeIdentity"], name="store identity"
            ),
            store_revision=_wire_string(
                document["storeRevision"], name="store revision"
            ),
            installation_id=_wire_string(
                document["installationId"], name="Installation identity"
            ),
            plugin_id=_wire_string(document["pluginId"], name="Plugin identity"),
            distribution=_wire_string(document["distribution"], name="distribution"),
            version=_wire_string(document["version"], name="version"),
            artifact_digest=_wire_string(
                document["artifactDigest"], name="artifact digest"
            ),
            extraction_tree_digest=_wire_string(
                document["extractionTreeDigest"], name="extraction tree digest"
            ),
            ref_version=_wire_int(document["refVersion"], name="ref version"),
        )


PackageStableRefV1 = VerifiedArtifactRefV1 | PluginRevisionRefV1


@dataclass(frozen=True, slots=True)
class DependencyClosureNodeV2:
    """One verified plan node paired with exactly one role-safe stable ref."""

    plan_node: VerifiedClosurePlanNodeV2
    stable_ref: PackageStableRefV1
    node_version: int = DEPENDENCY_CLOSURE_NODE_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.plan_node, VerifiedClosurePlanNodeV2):
            raise TypeError("Verified closure plan node is required")
        if self.plan_node.role == "root":
            if not isinstance(self.stable_ref, PluginRevisionRefV1):
                raise ValueError("Package root requires a Plugin revision ref")
        elif not isinstance(self.stable_ref, VerifiedArtifactRefV1):
            raise ValueError("Package dependency requires a verified artifact ref")
        if (
            self.plan_node.distribution != self.stable_ref.distribution
            or self.plan_node.version != self.stable_ref.version
            or self.plan_node.artifact_digest != self.stable_ref.artifact_digest
            or self.plan_node.extraction_tree_digest
            != self.stable_ref.extraction_tree_digest
        ):
            raise ValueError("Stable ref does not match its verified closure node")
        if self.node_version != DEPENDENCY_CLOSURE_NODE_VERSION:
            raise ValueError("Unsupported dependency closure node")

    @property
    def node_id(self) -> str:
        return self.plan_node.node_id

    def to_dict(self) -> dict[str, object]:
        kind: StableRefKind = (
            "plugin_revision"
            if isinstance(self.stable_ref, PluginRevisionRefV1)
            else "verified_artifact"
        )
        return {
            "nodeVersion": self.node_version,
            "planNode": self.plan_node.to_dict(),
            "stableRef": {"kind": kind, "value": self.stable_ref.to_dict()},
        }

    @classmethod
    def from_dict(cls, value: object) -> DependencyClosureNodeV2:
        document = _exact_dict(
            value,
            fields={"nodeVersion", "planNode", "stableRef"},
            name="dependency closure node",
        )
        stable_document = _exact_dict(
            document["stableRef"],
            fields={"kind", "value"},
            name="dependency closure stable ref",
        )
        kind = _wire_string(stable_document["kind"], name="stable ref kind")
        if kind == "plugin_revision":
            stable_ref: PackageStableRefV1 = PluginRevisionRefV1.from_dict(
                stable_document["value"]
            )
        elif kind == "verified_artifact":
            stable_ref = VerifiedArtifactRefV1.from_dict(stable_document["value"])
        else:
            raise ValueError("Unsupported dependency closure stable ref")
        return cls(
            plan_node=VerifiedClosurePlanNodeV2.from_dict(document["planNode"]),
            stable_ref=stable_ref,
            node_version=_wire_int(document["nodeVersion"], name="node version"),
        )


@dataclass(frozen=True, slots=True)
class DependencyClosureLockV2:
    """Immutable post-staging closure constructed once from a verified plan."""

    operation_id: str
    attempt_epoch: int
    root_node_id: str
    resolution_environment_fingerprint: str
    verified_plan_fingerprint: str
    prepublication_graph_digest: str
    nodes: tuple[DependencyClosureNodeV2, ...]
    node_count: int
    edge_count: int
    max_depth: int
    lock_digest: str
    lock_version: int = DEPENDENCY_CLOSURE_LOCK_VERSION

    def __post_init__(self) -> None:
        _require_safe_id(self.operation_id, name="closure operation identity")
        _require_positive(self.attempt_epoch, name="closure attempt epoch")
        _require_safe_id(self.root_node_id, name="closure root node identity")
        for value, name in (
            (
                self.resolution_environment_fingerprint,
                "resolution environment fingerprint",
            ),
            (self.verified_plan_fingerprint, "verified plan fingerprint"),
            (self.prepublication_graph_digest, "prepublication graph digest"),
            (self.lock_digest, "dependency closure lock digest"),
        ):
            _require_sha256(value, name=name)
        if not self.nodes or self.nodes != tuple(
            sorted(self.nodes, key=lambda node: node.node_id)
        ):
            raise ValueError("Dependency closure nodes must be canonical")
        if len({node.node_id for node in self.nodes}) != len(self.nodes):
            raise ValueError("Dependency closure nodes must be unique")
        roots = tuple(node for node in self.nodes if node.plan_node.role == "root")
        if len(roots) != 1 or roots[0].node_id != self.root_node_id:
            raise ValueError("Dependency closure has no exact designated root")
        if self.node_count != len(self.nodes):
            raise ValueError("Dependency closure node count does not match")
        if self.edge_count != sum(
            len(node.plan_node.selected_edges) for node in self.nodes
        ):
            raise ValueError("Dependency closure edge count does not match")
        _require_nonnegative(self.max_depth, name="dependency closure depth")
        try:
            plan = VerifiedClosurePlanV2(
                operation_id=self.operation_id,
                attempt_epoch=self.attempt_epoch,
                root_node_id=self.root_node_id,
                resolution_environment_fingerprint=(
                    self.resolution_environment_fingerprint
                ),
                nodes=tuple(node.plan_node for node in self.nodes),
                node_count=self.node_count,
                edge_count=self.edge_count,
                max_depth=self.max_depth,
                graph_digest=self.prepublication_graph_digest,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Dependency closure plan evidence is invalid") from exc
        if plan.fingerprint != self.verified_plan_fingerprint:
            raise ValueError("Dependency closure plan fingerprint does not match")
        if self.lock_version != DEPENDENCY_CLOSURE_LOCK_VERSION:
            raise ValueError("Unsupported dependency closure lock")
        if self.lock_digest != _fingerprint(self._identity_dict()):
            raise ValueError("Dependency closure lock digest does not match")

    @classmethod
    def create(
        cls,
        plan: VerifiedClosurePlanV2,
        *,
        stable_refs: Mapping[str, PackageStableRefV1],
    ) -> DependencyClosureLockV2:
        if not isinstance(plan, VerifiedClosurePlanV2):
            raise TypeError("Verified closure plan is required")
        if set(stable_refs) != {node.node_id for node in plan.nodes}:
            raise ValueError("Stable refs do not match the verified closure node set")
        nodes = tuple(
            DependencyClosureNodeV2(
                plan_node=node,
                stable_ref=stable_refs[node.node_id],
            )
            for node in plan.nodes
        )
        values = {
            "attemptEpoch": plan.attempt_epoch,
            "edgeCount": plan.edge_count,
            "lockVersion": DEPENDENCY_CLOSURE_LOCK_VERSION,
            "maxDepth": plan.max_depth,
            "nodeCount": plan.node_count,
            "nodes": [node.to_dict() for node in nodes],
            "operationId": plan.operation_id,
            "prepublicationGraphDigest": plan.graph_digest,
            "resolutionEnvironmentFingerprint": (
                plan.resolution_environment_fingerprint
            ),
            "rootNodeId": plan.root_node_id,
            "verifiedPlanFingerprint": plan.fingerprint,
        }
        return cls(
            operation_id=plan.operation_id,
            attempt_epoch=plan.attempt_epoch,
            root_node_id=plan.root_node_id,
            resolution_environment_fingerprint=(
                plan.resolution_environment_fingerprint
            ),
            verified_plan_fingerprint=plan.fingerprint,
            prepublication_graph_digest=plan.graph_digest,
            nodes=nodes,
            node_count=plan.node_count,
            edge_count=plan.edge_count,
            max_depth=plan.max_depth,
            lock_digest=_fingerprint(values),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "edgeCount": self.edge_count,
            "lockVersion": self.lock_version,
            "maxDepth": self.max_depth,
            "nodeCount": self.node_count,
            "nodes": [node.to_dict() for node in self.nodes],
            "operationId": self.operation_id,
            "prepublicationGraphDigest": self.prepublication_graph_digest,
            "resolutionEnvironmentFingerprint": (
                self.resolution_environment_fingerprint
            ),
            "rootNodeId": self.root_node_id,
            "verifiedPlanFingerprint": self.verified_plan_fingerprint,
        }

    def to_dict(self) -> dict[str, object]:
        return {"lockDigest": self.lock_digest, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> DependencyClosureLockV2:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "edgeCount",
                "lockDigest",
                "lockVersion",
                "maxDepth",
                "nodeCount",
                "nodes",
                "operationId",
                "prepublicationGraphDigest",
                "resolutionEnvironmentFingerprint",
                "rootNodeId",
                "verifiedPlanFingerprint",
            },
            name="dependency closure lock",
        )
        return cls(
            operation_id=_wire_string(
                document["operationId"], name="operation identity"
            ),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            root_node_id=_wire_string(
                document["rootNodeId"], name="root node identity"
            ),
            resolution_environment_fingerprint=_wire_string(
                document["resolutionEnvironmentFingerprint"],
                name="resolution environment fingerprint",
            ),
            verified_plan_fingerprint=_wire_string(
                document["verifiedPlanFingerprint"],
                name="verified plan fingerprint",
            ),
            prepublication_graph_digest=_wire_string(
                document["prepublicationGraphDigest"],
                name="prepublication graph digest",
            ),
            nodes=tuple(
                DependencyClosureNodeV2.from_dict(item)
                for item in _wire_list(document["nodes"], name="closure nodes")
            ),
            node_count=_wire_int(document["nodeCount"], name="node count"),
            edge_count=_wire_int(document["edgeCount"], name="edge count"),
            max_depth=_wire_int(document["maxDepth"], name="maximum depth"),
            lock_digest=_wire_string(
                document["lockDigest"], name="closure lock digest"
            ),
            lock_version=_wire_int(
                document["lockVersion"], name="closure lock version"
            ),
        )


@dataclass(frozen=True, slots=True)
class CommittedPackageSetRefV1:
    """The sole typed ref for an exact root-plus-dependency committed set."""

    set_id: str
    operation_id: str
    attempt_epoch: int
    request_fingerprint: str
    product_id: str
    scope_id: str
    installation_id: str
    plugin_id: str
    classification_fingerprint: str
    closure_lock_digest: str
    prepublication_graph_digest: str
    root_ref: PluginRevisionRefV1
    dependency_refs: tuple[VerifiedArtifactRefV1, ...]
    commit_revision: int
    set_version: int = COMMITTED_PACKAGE_SET_REF_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.set_id, name="committed Package set id")
        for value, name in (
            (self.operation_id, "Package operation identity"),
            (self.product_id, "Product identity"),
            (self.scope_id, "scope identity"),
            (self.installation_id, "Installation identity"),
            (self.plugin_id, "Plugin identity"),
        ):
            _require_safe_id(value, name=name)
        _require_positive(self.attempt_epoch, name="Package attempt epoch")
        _require_positive(self.commit_revision, name="Package commit revision")
        for value, name in (
            (self.request_fingerprint, "request fingerprint"),
            (self.classification_fingerprint, "classification fingerprint"),
            (self.closure_lock_digest, "closure lock digest"),
            (self.prepublication_graph_digest, "prepublication graph digest"),
        ):
            _require_sha256(value, name=name)
        if not isinstance(self.root_ref, PluginRevisionRefV1):
            raise TypeError("Committed Package set root ref is required")
        if (
            self.root_ref.installation_id != self.installation_id
            or self.root_ref.plugin_id != self.plugin_id
        ):
            raise ValueError("Committed Package set root identity changed")
        if self.dependency_refs != tuple(
            sorted(self.dependency_refs, key=lambda ref: ref.ref_id)
        ) or len({ref.ref_id for ref in self.dependency_refs}) != len(
            self.dependency_refs
        ):
            raise ValueError("Committed Package dependency refs must be canonical")
        if self.set_version != COMMITTED_PACKAGE_SET_REF_VERSION:
            raise ValueError("Unsupported committed Package set ref")
        if self.set_id != _fingerprint(self._identity_dict()):
            raise ValueError("Committed Package set id does not match")

    @classmethod
    def create(
        cls,
        lock: DependencyClosureLockV2,
        *,
        request_fingerprint: str,
        product_id: str,
        scope_id: str,
        installation_id: str,
        plugin_id: str,
        classification_fingerprint: str,
        commit_revision: int,
    ) -> CommittedPackageSetRefV1:
        if not isinstance(lock, DependencyClosureLockV2):
            raise TypeError("Dependency closure lock is required")
        root_node = next(
            node for node in lock.nodes if node.node_id == lock.root_node_id
        )
        root_ref = cast(PluginRevisionRefV1, root_node.stable_ref)
        dependencies = tuple(
            sorted(
                (
                    cast(VerifiedArtifactRefV1, node.stable_ref)
                    for node in lock.nodes
                    if node.plan_node.role == "dependency"
                ),
                key=lambda ref: ref.ref_id,
            )
        )
        values = {
            "attemptEpoch": lock.attempt_epoch,
            "classificationFingerprint": classification_fingerprint,
            "closureLockDigest": lock.lock_digest,
            "commitRevision": commit_revision,
            "dependencyRefs": [ref.to_dict() for ref in dependencies],
            "installationId": installation_id,
            "operationId": lock.operation_id,
            "pluginId": plugin_id,
            "prepublicationGraphDigest": lock.prepublication_graph_digest,
            "productId": product_id,
            "requestFingerprint": request_fingerprint,
            "rootRef": root_ref.to_dict(),
            "scopeId": scope_id,
            "setVersion": COMMITTED_PACKAGE_SET_REF_VERSION,
        }
        return cls(
            set_id=_fingerprint(values),
            operation_id=lock.operation_id,
            attempt_epoch=lock.attempt_epoch,
            request_fingerprint=request_fingerprint,
            product_id=product_id,
            scope_id=scope_id,
            installation_id=installation_id,
            plugin_id=plugin_id,
            classification_fingerprint=classification_fingerprint,
            closure_lock_digest=lock.lock_digest,
            prepublication_graph_digest=lock.prepublication_graph_digest,
            root_ref=root_ref,
            dependency_refs=dependencies,
            commit_revision=commit_revision,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "classificationFingerprint": self.classification_fingerprint,
            "closureLockDigest": self.closure_lock_digest,
            "commitRevision": self.commit_revision,
            "dependencyRefs": [ref.to_dict() for ref in self.dependency_refs],
            "installationId": self.installation_id,
            "operationId": self.operation_id,
            "pluginId": self.plugin_id,
            "prepublicationGraphDigest": self.prepublication_graph_digest,
            "productId": self.product_id,
            "requestFingerprint": self.request_fingerprint,
            "rootRef": self.root_ref.to_dict(),
            "scopeId": self.scope_id,
            "setVersion": self.set_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {"setId": self.set_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> CommittedPackageSetRefV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "classificationFingerprint",
                "closureLockDigest",
                "commitRevision",
                "dependencyRefs",
                "installationId",
                "operationId",
                "pluginId",
                "prepublicationGraphDigest",
                "productId",
                "requestFingerprint",
                "rootRef",
                "scopeId",
                "setId",
                "setVersion",
            },
            name="committed Package set ref",
        )
        return cls(
            set_id=_wire_string(document["setId"], name="set id"),
            operation_id=_wire_string(
                document["operationId"], name="operation identity"
            ),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            request_fingerprint=_wire_string(
                document["requestFingerprint"], name="request fingerprint"
            ),
            product_id=_wire_string(document["productId"], name="Product identity"),
            scope_id=_wire_string(document["scopeId"], name="scope identity"),
            installation_id=_wire_string(
                document["installationId"], name="Installation identity"
            ),
            plugin_id=_wire_string(document["pluginId"], name="Plugin identity"),
            classification_fingerprint=_wire_string(
                document["classificationFingerprint"],
                name="classification fingerprint",
            ),
            closure_lock_digest=_wire_string(
                document["closureLockDigest"], name="closure lock digest"
            ),
            prepublication_graph_digest=_wire_string(
                document["prepublicationGraphDigest"],
                name="prepublication graph digest",
            ),
            root_ref=PluginRevisionRefV1.from_dict(document["rootRef"]),
            dependency_refs=tuple(
                VerifiedArtifactRefV1.from_dict(item)
                for item in _wire_list(
                    document["dependencyRefs"], name="dependency refs"
                )
            ),
            commit_revision=_wire_int(
                document["commitRevision"], name="commit revision"
            ),
            set_version=_wire_int(document["setVersion"], name="set version"),
        )


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _require_distribution(value: str) -> None:
    if not isinstance(value, str) or value != _canonical_distribution(value):
        raise ValueError("Package distribution name must be canonical")


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


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase hexadecimal SHA-256")


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be positive")


def _require_nonnegative(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _exact_dict(value: object, *, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} does not match its versioned schema")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_list(value: object, *, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


__all__ = [
    "CommittedPackageSetRefV1",
    "DependencyClosureLockV2",
    "DependencyClosureNodeV2",
    "PackageStableRefV1",
    "PluginRevisionRefV1",
    "VerifiedArtifactRefV1",
]
