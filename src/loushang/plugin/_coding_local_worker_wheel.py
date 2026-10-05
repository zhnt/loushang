"""Offline author recipe for a default-dark local Worker Wheel candidate.

This builder creates inert bytes. A Product must separately authorize
the Source, admit the Wheel, select its revision, and issue a Worker receipt.
"""

from __future__ import annotations

import csv
import io
import json
import re
import stat
import zipfile
from base64 import urlsafe_b64encode
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.plugins.declarations import (
    PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
    PluginContributionIndex,
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
    PluginDeclarationSource,
    PluginLocalWorkerConfiguration,
)
from loushang.harness.resources.plugins.engine import required_plugin_engine_features
from loushang.harness.worker.native_executable_format import (
    WorkerNativeExecutablePlatform,
    verify_worker_native_executable_format,
)

_PLUGIN_ID = re.compile(r"[a-z][a-z0-9]*\Z")
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}\Z")
_DEPENDENCY_PIN = re.compile(
    r"(?P<name>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)==(?P<version>[0-9]+(?:\.[0-9]+){0,2})\Z"
)
_LINUX_TAG = re.compile(r"py3-none-(?:linux|manylinux_[0-9]+_[0-9]+)_x86_64\Z")
_WINDOWS_TAG = "py3-none-win_amd64"
_MAX_TREE_BYTES = 16 * 1024 * 1024
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_FILENAME = 180


def coding_local_worker_candidate_wheel_filename(
    *, plugin_id: str, version: str, wheel_tag: str
) -> str:
    """Return the exact Wheel filename after bounded author-input validation."""

    if not isinstance(plugin_id, str) or _PLUGIN_ID.fullmatch(plugin_id) is None:
        raise ValueError("Coding Worker Plugin ID must be simple lowercase ASCII")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ValueError("Coding Worker version must be numeric")
    if not isinstance(wheel_tag, str) or not wheel_tag:
        raise ValueError("Coding Worker Wheel tag is invalid")
    filename = f"{plugin_id}-{version}-{wheel_tag}.whl"
    if len(filename) > _MAX_FILENAME:
        raise ValueError("Coding Worker Wheel filename exceeds Product limit")
    return filename


def build_coding_local_worker_candidate_wheel(
    *,
    plugin_id: str,
    version: str,
    contribution_id: str,
    owner_id: str,
    native_platform: WorkerNativeExecutablePlatform,
    wheel_tag: str,
    executable: bytes,
    dependency: str | None = None,
    dependencies: tuple[str, ...] = (),
) -> bytes:
    """Build one inert Capability Worker candidate with bounded exact pins."""

    coding_local_worker_candidate_wheel_filename(
        plugin_id=plugin_id, version=version, wheel_tag=wheel_tag
    )
    if native_platform == "linux-x86_64":
        if _LINUX_TAG.fullmatch(wheel_tag) is None:
            raise ValueError("Coding Worker Linux Wheel tag is unsupported")
    elif native_platform == "windows-amd64":
        if wheel_tag != _WINDOWS_TAG:
            raise ValueError("Coding Worker Windows Wheel tag is unsupported")
    else:
        raise ValueError("Coding Worker native platform is unsupported")
    if type(dependencies) is not tuple or (
        dependency is not None and dependencies
    ):
        raise ValueError("Coding Worker dependency inputs conflict")
    pins = (dependency,) if dependency is not None else dependencies
    if len(pins) > 3 or any(type(pin) is not str for pin in pins):
        raise ValueError("Coding Worker dependency pins exceed Product limit")
    names: set[str] = set()
    for pin in pins:
        match = _DEPENDENCY_PIN.fullmatch(pin)
        if match is None or match["name"] == plugin_id or match["name"] in names:
            raise ValueError("Coding Worker dependencies need distinct exact pins")
        names.add(match["name"])
    pins = tuple(sorted(pins))
    verify_worker_native_executable_format(executable, platform=native_platform)
    configuration = PluginLocalWorkerConfiguration(
        entrypoint="worker/bin/query-worker",
        protocol="capability.query",
        protocol_version=1,
    )
    reservation = PluginContributionReservation(
        contribution_id=contribution_id,
        kind="capability_provider",
        owner=owner_id,
        declaration_source=PluginDeclarationSource.document(
            "declarations/providers.json",
            schema_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
        ),
        contribution_execution_model="local_worker",
        requested_authorities=(),
        worker_configuration=configuration,
        index_version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    )
    index = PluginContributionIndex(
        items=(reservation,), version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION
    )
    declaration = PluginDeclaration(
        plugin_id=plugin_id,
        contribution_id=contribution_id,
        kind="capability_provider",
        owner=owner_id,
        reservation_fingerprint=reservation.fingerprint,
        source_descriptor_fingerprint=reservation.source_descriptor_fingerprint,
        source_kind="document",
        payload={"querySchema": "loushang.capability-query/read-only/v1"},
        ir_version=PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
        contribution_execution_model="local_worker",
        worker_configuration=configuration,
    )
    dist_info = f"{plugin_id}-{version}.dist-info"
    files = {
        f"{plugin_id}/plugin.json": json.dumps(
            {
                "contributionIndex": index.to_dict(),
                "engine": {
                    "apiVersion": 1,
                    "declarationIrVersion": 3,
                    "requiredFeatures": sorted(required_plugin_engine_features(index)),
                },
                "manifestVersion": 1,
                "name": plugin_id,
                "packageRoot": ".",
                "version": version,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
        f"{plugin_id}/declarations/providers.json": PluginDeclarationDocumentCodec.encode_bytes(
            PluginDeclarationDocument(
                declarations=(declaration,),
                document_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
            )
        ),
        f"{plugin_id}/{configuration.entrypoint}": executable,
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {plugin_id}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {pin}\n" for pin in pins)
            + "\n"
        ).encode("ascii"),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: loushang-worker-candidate\n"
            f"Root-Is-Purelib: false\nTag: {wheel_tag}\n\n"
        ).encode("ascii"),
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    files[f"{dist_info}/RECORD"] = record.getvalue().encode("utf-8")
    if sum(len(body) for body in files.values()) > _MAX_TREE_BYTES:
        raise ValueError("Coding Worker extracted tree exceeds Product limit")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, body)
    wheel = output.getvalue()
    if len(wheel) > _MAX_WHEEL_BYTES:
        raise ValueError("Coding Worker Wheel exceeds current Product Source limit")
    return wheel


def write_coding_local_worker_candidate_wheel(
    directory: str | Path,
    *,
    plugin_id: str,
    version: str,
    contribution_id: str,
    owner_id: str,
    native_platform: WorkerNativeExecutablePlatform,
    wheel_tag: str,
    executable: bytes,
    dependency: str | None = None,
    dependencies: tuple[str, ...] = (),
) -> Path:
    """Write a new candidate Wheel without replacing an existing artifact."""

    wheel = build_coding_local_worker_candidate_wheel(
        plugin_id=plugin_id,
        version=version,
        contribution_id=contribution_id,
        owner_id=owner_id,
        native_platform=native_platform,
        wheel_tag=wheel_tag,
        executable=executable,
        dependency=dependency,
        dependencies=dependencies,
    )
    target = Path(directory) / coding_local_worker_candidate_wheel_filename(
        plugin_id=plugin_id, version=version, wheel_tag=wheel_tag
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(wheel)
    return target


__all__ = [
    "build_coding_local_worker_candidate_wheel",
    "coding_local_worker_candidate_wheel_filename",
    "write_coding_local_worker_candidate_wheel",
]
