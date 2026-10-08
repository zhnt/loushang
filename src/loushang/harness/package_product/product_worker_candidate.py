"""Read-only join between a Product-selected root and a Worker candidate."""

from __future__ import annotations

from loushang.harness.worker.native_executable_format import (
    WorkerNativeExecutableFormatError,
    WorkerNativeExecutablePlatform,
    verify_worker_native_executable_format,
)
from loushang.harness.worker.package_candidate import (
    WorkerPackageCandidateError,
    WorkerPackageCandidateV1,
    verify_worker_package_candidate,
)

from .product_local_wheel_runtime import PackageProductSelectedPluginManifestV1


def verify_product_selected_worker_candidate(
    selected: PackageProductSelectedPluginManifestV1,
    *,
    contribution_id: str,
    native_platform: WorkerNativeExecutablePlatform,
) -> WorkerPackageCandidateV1:
    """Rejoin one selected root to inert Worker bytes without granting execution.

    Product selection and Store verification belong to the owner that captured
    ``selected``. It must recheck the selected root before issuing a receipt.
    """

    if not isinstance(selected, PackageProductSelectedPluginManifestV1):
        raise WorkerPackageCandidateError("worker_candidate_selection_invalid")
    try:
        manifest = selected.verified_manifest()
        root = manifest.root_relative_path.as_posix()
        manifest_path = "plugin.json" if root == "." else f"{root}/plugin.json"
        members = dict(selected.snapshot.files)
        candidate = verify_worker_package_candidate(
            members,
            manifest_logical_path=manifest_path,
            contribution_id=contribution_id,
        )
        configuration = manifest.contribution_index.items[0].worker_configuration
        assert configuration is not None
        prefix = "" if root == "." else f"{root}/"
        verify_worker_native_executable_format(
            members[f"{prefix}{configuration.entrypoint}"],
            platform=native_platform,
        )
    except WorkerNativeExecutableFormatError as exc:
        raise WorkerPackageCandidateError(
            "worker_candidate_executable_format_invalid"
        ) from exc
    except (TypeError, ValueError, KeyError) as exc:
        raise WorkerPackageCandidateError("worker_candidate_selection_invalid") from exc
    if (
        candidate.plugin_id != selected.snapshot.installation_key.plugin_id
        or candidate.plugin_version != selected.snapshot.root_ref.version
        or candidate.manifest_digest != selected.manifest.manifest_digest
    ):
        raise WorkerPackageCandidateError("worker_candidate_selection_mismatch")
    return candidate


__all__ = ["verify_product_selected_worker_candidate"]
