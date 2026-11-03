"""Inert verification of one Worker contribution in a verified file set.

The caller must supply bytes from a Package-owned regular-file snapshot. This
module grants no Product selection, Worker receipt, or executable authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationCodecError,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)

_MAX_FILES = 64
_MAX_TOTAL_BYTES = 16 * 1024 * 1024


class WorkerPackageCandidateError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorkerPackageCandidateV1:
    plugin_id: str
    plugin_version: str
    contribution_id: str
    owner_id: str
    declared_required: bool
    manifest_digest: str
    reservation_fingerprint: str
    declaration_fingerprint: str
    worker_configuration_fingerprint: str
    executable_digest: str
    executable_size: int


def verify_worker_package_candidate(
    files: Mapping[str, bytes],
    *,
    manifest_logical_path: str,
    contribution_id: str,
) -> WorkerPackageCandidateV1:
    """Rejoin exact v3 reservation, declaration, and executable bytes."""

    if (
        not isinstance(files, Mapping)
        or not 0 < len(files) <= _MAX_FILES
        or not isinstance(contribution_id, str)
        or not contribution_id
    ):
        raise WorkerPackageCandidateError("worker_candidate_invalid")
    members: dict[str, bytes] = {}
    total = 0
    for path, body in files.items():
        if not isinstance(path, str) or not isinstance(body, bytes):
            raise WorkerPackageCandidateError("worker_candidate_invalid")
        try:
            canonical = canonical_plugin_relative_path(path).as_posix()
        except ValueError as exc:
            raise WorkerPackageCandidateError("worker_candidate_invalid") from exc
        if canonical != path or path in members:
            raise WorkerPackageCandidateError("worker_candidate_invalid")
        total += len(body)
        if total > _MAX_TOTAL_BYTES:
            raise WorkerPackageCandidateError("worker_candidate_too_large")
        members[path] = body
    try:
        manifest = PluginManifestParser().parse_file_set(
            members, manifest_logical_path=manifest_logical_path
        )
    except (PluginManifestError, ValueError, TypeError) as exc:
        raise WorkerPackageCandidateError("worker_candidate_manifest_invalid") from exc
    reservations = manifest.contribution_index.items
    if len(reservations) != 1 or reservations[0].contribution_id != contribution_id:
        raise WorkerPackageCandidateError("worker_candidate_topology_unsupported")
    reservation = reservations[0]
    configuration = reservation.worker_configuration
    if (
        reservation.kind != "capability_provider"
        or reservation.contribution_execution_model != "local_worker"
        or reservation.declaration_source.kind != "document"
        or reservation.requested_authorities
        or configuration is None
    ):
        raise WorkerPackageCandidateError("worker_candidate_topology_unsupported")
    prefix = (
        ""
        if manifest.root_relative_path.as_posix() == "."
        else f"{manifest.root_relative_path.as_posix()}/"
    )
    declaration_path = (
        f"{prefix}{reservation.declaration_source.relative_path.as_posix()}"
    )
    try:
        document = PluginDeclarationDocumentCodec.decode_bytes(
            members[declaration_path]
        )
    except (KeyError, PluginDeclarationCodecError) as exc:
        raise WorkerPackageCandidateError("worker_candidate_declaration_invalid") from exc
    if len(document.declarations) != 1:
        raise WorkerPackageCandidateError("worker_candidate_declaration_invalid")
    declaration = document.declarations[0]
    if (
        declaration.plugin_id != manifest.name
        or declaration.contribution_id != reservation.contribution_id
        or declaration.kind != reservation.kind
        or declaration.owner != reservation.owner
        or declaration.reservation_fingerprint != reservation.fingerprint
        or declaration.source_descriptor_fingerprint
        != reservation.source_descriptor_fingerprint
        or declaration.source_kind != "document"
        or declaration.contribution_execution_model != "local_worker"
        or declaration.worker_configuration != configuration
    ):
        raise WorkerPackageCandidateError("worker_candidate_declaration_mismatch")
    executable = members.get(f"{prefix}{configuration.entrypoint}")
    if not executable:
        raise WorkerPackageCandidateError("worker_candidate_executable_missing")
    return WorkerPackageCandidateV1(
        plugin_id=manifest.name,
        plugin_version=manifest.version,
        contribution_id=contribution_id,
        owner_id=reservation.owner,
        declared_required=reservation.required,
        manifest_digest=manifest.manifest_digest,
        reservation_fingerprint=reservation.fingerprint,
        declaration_fingerprint=declaration.fingerprint,
        worker_configuration_fingerprint=configuration.fingerprint,
        executable_digest=sha256(executable).hexdigest(),
        executable_size=len(executable),
    )


__all__ = [
    "WorkerPackageCandidateError",
    "WorkerPackageCandidateV1",
    "verify_worker_package_candidate",
]
