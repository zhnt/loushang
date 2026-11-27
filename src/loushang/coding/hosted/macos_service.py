"""Cut over existing macOS installations to the managed local AppHost."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from loushang.apphost.managed._files import ManagedStorageError
from loushang.appservice.continuity import ApplicationContinuityRecordV1
from loushang.appservice.continuity_file import JsonFileApplicationContinuityStoreV1
from loushang.coding.hosted.managed.service import ServiceControlError
from loushang.hosting.service_launchd import LaunchdJobError, LaunchdUserJob


def require_legacy_job_stopped(home: Path) -> None:
    if not (home / "state/macos-host/host.plist").exists():
        return
    label = "ai.loushang.host." + sha256(str(home).encode()).hexdigest()[:20]
    try:
        job_state = LaunchdUserJob(label).observe()
    except LaunchdJobError as error:
        raise ServiceControlError(str(error)) from error
    if job_state != "not_running":
        raise ServiceControlError("legacy_service_active")


def legacy_application_root(home: Path, managed_root: Path) -> Path | None:
    # Workspace scope and Session store IDs depend on these absolute paths.
    state = home / "state/macos-host"
    if not (state / "host.plist").exists():
        return None
    legacy = state / "application"
    if not (legacy.exists() or legacy.is_symlink()):
        return None
    if legacy != legacy.resolve() or not legacy.is_dir():
        raise ManagedStorageError("unavailable")
    continuity = managed_root / "coding.default.json"
    if continuity.exists() or continuity.is_symlink():
        raise ManagedStorageError("conflict")
    return legacy


async def import_legacy_continuity(
    root: Path, import_record: Callable[[ApplicationContinuityRecordV1], ApplicationContinuityRecordV1], *,
    application_id: str, service_id: str, attempt_id: str,
) -> None:
    lease = await JsonFileApplicationContinuityStoreV1(root).acquire(
        application_id=application_id, owner_epoch=attempt_id,
    )
    try:
        record = await lease.load()
        if record is None or record.managed_service_id == service_id:
            return
        if record.managed_service_id != sha256(str(root).encode()).hexdigest():
            raise ManagedStorageError("conflict")
        migrated = await asyncio.to_thread(import_record, record)
        await lease.commit(expected_revision=record.record_revision, record=migrated)
    finally:
        await lease.close()
