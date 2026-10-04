"""Explicit, default-dark Product admission for one local Worker Wheel shape."""

from __future__ import annotations

import platform
import re
import sys
from email.parser import BytesParser
from email.policy import compat32
from hashlib import sha256
from typing import Never

from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductTransactionRoute,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)
from loushang.harness.resources.packages.product_transaction import (
    PackageProductCandidateRejected,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.worker.native_executable_format import (
    WorkerNativeExecutableFormatError,
    verify_worker_native_executable_format,
)
from loushang.harness.worker.package_candidate import (
    WorkerPackageCandidateError,
    verify_worker_package_candidate,
)

_SIMPLE_PLUGIN_ID = re.compile(r"[a-z][a-z0-9-]*\Z")


def admit_explicit_local_worker_wheel_candidate(
    policy: PackageProductLocalWheelPolicy,
    request: PackageProductTransactionRoute,
    closure: VerifiedPackageClosureCandidate,
) -> None:
    """Refuse unsupported Worker bytes before a Package set can be committed.

    Only one explicitly pinned Product binding selects this gate. Successful
    installation remains inert: no Worker receipt, launch, or domain publication
    is granted here.
    """

    bindings = tuple(
        item
        for item in policy.bindings
        if item.source_identity == request.ingress.source_locator
        and item.source_trust_class == "local-worker-candidate"
    )
    if not bindings:
        return

    def reject() -> Never:
        raise PackageProductCandidateRejected(
            "Local Worker Wheel candidate is unsupported"
        )

    if (
        len(bindings) != 1
        or not 1 <= closure.plan.node_count <= 4
        or len(closure.candidates) != closure.plan.node_count
    ):
        reject()
    binding = bindings[0]
    admission = binding.worker_admission
    if admission is None or binding.plugin_manifest_path is None:
        reject()
    machine = platform.machine().lower()
    if admission.native_platform == "linux-x86_64":
        platform_admitted = sys.platform.startswith("linux") and machine in {
            "x86_64",
            "amd64",
        }
    elif admission.native_platform == "windows-amd64":
        platform_admitted = sys.platform == "win32" and machine in {"x86_64", "amd64"}
    else:
        platform_admitted = False
    if not platform_admitted:
        reject()
    roots = tuple(
        item
        for item in closure.candidates
        if item.transfer_manifest.node_id == closure.plan.root_node_id
    )
    if len(roots) != 1:
        reject()
    wheel = roots[0]
    root_plan = next(
        item for item in closure.plan.nodes if item.node_id == closure.plan.root_node_id
    )
    dependencies = tuple(item for item in closure.candidates if item is not wheel)
    dependency_plans = tuple(
        item for item in closure.plan.nodes if item.node_id != root_plan.node_id
    )
    if (
        len(wheel.requires_dist) != len(dependencies)
        or len(dependencies) != len(dependency_plans)
        or root_plan.selected_extras
        or len(root_plan.selected_edges) != len(dependencies)
        or set(root_plan.selected_edges)
        != {item.node_id for item in dependency_plans}
    ):
        reject()
    candidates_by_node = {
        item.transfer_manifest.node_id: item for item in dependencies
    }
    if len(candidates_by_node) != len(dependencies):
        reject()
    for dependency_plan in dependency_plans:
        dependency = candidates_by_node.get(dependency_plan.node_id)
        if dependency is None:
            reject()
        if (
            dependency_plan.role != "dependency"
            or dependency_plan.selected_edges
            or dependency_plan.selected_extras
            or dependency.requires_dist
            or dependency.provides_extra
            or dependency.transfer_manifest.distribution
            != dependency_plan.distribution
            or "py3-none-any" not in dependency.evidence.compatible_tags
            or len(dependency.transfer_manifest.entries) > 16
            or dependency.transfer_manifest.total_byte_count > 1024 * 1024
        ):
            reject()
        dependency_dist_info = (
            dependency_plan.distribution.replace("-", "_")
            + f"-{dependency_plan.version}.dist-info/WHEEL"
        )
        entries = {
            item.logical_path: item
            for item in dependency.transfer_manifest.entries
        }
        dependency_module = dependency_plan.distribution.replace("-", "_") + "/"
        dependency_metadata_paths = {
            dependency_dist_info,
            dependency_dist_info.replace("/WHEEL", "/METADATA"),
            dependency_dist_info.replace("/WHEEL", "/RECORD"),
        }
        if (
            not dependency_metadata_paths <= entries.keys()
            or not any(path.startswith(dependency_module) for path in entries)
            or any(
                path not in dependency_metadata_paths
                and not (
                    path.startswith(dependency_module)
                    and path.endswith((".py", ".pyi"))
                )
                for path in entries
            )
        ):
            reject()
        dependency_metadata = entries.get(dependency_dist_info)
        if dependency_metadata is None or dependency_metadata.byte_count > 4096:
            reject()
        with dependency.open_verified_tree_file(dependency_metadata) as handle:
            metadata_bytes = handle.read(dependency_metadata.byte_count + 1)
        if (
            len(metadata_bytes) != dependency_metadata.byte_count
            or sha256(metadata_bytes).hexdigest()
            != dependency_metadata.content_digest
        ):
            reject()
        dependency_wheel_metadata = BytesParser(policy=compat32).parsebytes(
            metadata_bytes, headersonly=True
        )
        if tuple(
            value.strip().lower()
            for value in dependency_wheel_metadata.get_all("Root-Is-Purelib", [])
        ) != ("true",):
            reject()
    tree = wheel.transfer_manifest
    root = binding.plugin_id.replace("-", "_")
    dist_info = f"{root}-{tree.version}.dist-info"
    metadata_paths = {
        f"{dist_info}/WHEEL",
        f"{dist_info}/METADATA",
        f"{dist_info}/RECORD",
    }
    if admission.native_platform == "windows-amd64":
        wheel_tag_admitted = "py3-none-win_amd64" in wheel.evidence.compatible_tags
    else:
        wheel_tag_admitted = any(
            tag.rsplit("-", 1)[-1].endswith("_x86_64")
            and tag.rsplit("-", 1)[-1].startswith(("manylinux", "linux"))
            for tag in wheel.evidence.compatible_tags
        )
    if (
        _SIMPLE_PLUGIN_ID.fullmatch(binding.plugin_id) is None
        or binding.plugin_manifest_path != f"{root}/plugin.json"
        or tree.node_id != "root"
        or tree.distribution != binding.plugin_id
        or binding.requested_package != f"{binding.plugin_id}=={tree.version}"
        or wheel.evidence.artifact_digest != binding.artifact_digest
        or wheel.provides_extra
        or len(tree.entries) != 6
        or tree.total_byte_count > 16 * 1024 * 1024
        or not wheel_tag_admitted
    ):
        reject()
    files: dict[str, bytes] = {}
    for entry in tree.entries:
        if entry.byte_count > 16 * 1024 * 1024:
            reject()
        with wheel.open_verified_tree_file(entry) as handle:
            body = handle.read(entry.byte_count + 1)
        if (
            len(body) != entry.byte_count
            or sha256(body).hexdigest() != entry.content_digest
        ):
            reject()
        files[entry.logical_path] = body
    if not metadata_paths <= files.keys():
        reject()
    wheel_metadata = BytesParser(policy=compat32).parsebytes(
        files[f"{dist_info}/WHEEL"], headersonly=True
    )
    root_values = wheel_metadata.get_all("Root-Is-Purelib", [])
    if tuple(value.strip().lower() for value in root_values) != ("false",):
        reject()
    try:
        manifest = PluginManifestParser().parse_file_set(
            files, manifest_logical_path=binding.plugin_manifest_path
        )
        candidate = verify_worker_package_candidate(
            files,
            manifest_logical_path=binding.plugin_manifest_path,
            contribution_id=admission.contribution_id,
        )
        reservation = manifest.contribution_index.items[0]
        configuration = reservation.worker_configuration
        if configuration is None:
            reject()
        expected = metadata_paths | {
            binding.plugin_manifest_path,
            f"{root}/{reservation.declaration_source.relative_path.as_posix()}",
            f"{root}/{configuration.entrypoint}",
        }
        if (
            set(files) != expected
            or candidate.plugin_id != binding.plugin_id
            or candidate.plugin_version != tree.version
            or candidate.owner_id != admission.owner_id
        ):
            reject()
        verify_worker_native_executable_format(
            files[f"{root}/{configuration.entrypoint}"],
            platform=admission.native_platform,
        )
    except (
        KeyError,
        ValueError,
        PluginManifestError,
        WorkerPackageCandidateError,
        WorkerNativeExecutableFormatError,
    ) as exc:
        raise PackageProductCandidateRejected(
            "Local Worker Wheel candidate failed exact admission"
        ) from exc


__all__ = ["admit_explicit_local_worker_wheel_candidate"]
