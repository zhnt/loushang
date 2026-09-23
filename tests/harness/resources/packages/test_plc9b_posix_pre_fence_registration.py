from __future__ import annotations

import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistry,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_coordination import (
    PackagePosixEpochCutoverCoordination,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackagePosixEpochCutoverOwner,
    PackagePosixEpochCutoverRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_pre_fence_registration import (
    PackagePosixPreFenceRegistrationError,
    PackagePosixPreFenceRegistrationOwner,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux directory flock authority"
)

_STORE_ID = "package-store:pre-fence-test"


def _fixture(
    tmp_path: Path,
) -> tuple[Path, PackageEpochFenceJournal, PackagePosixPreFenceRegistrationOwner]:
    authority = tmp_path / "authority"
    legacy = authority / "legacy"
    epochs = authority / "epochs"
    for directory in (authority, legacy, epochs):
        directory.mkdir(mode=0o700)
    fences = PackageEpochFenceJournal(tmp_path / "epoch.jsonl")
    pre_fence = PackagePosixPreFenceRegistrationOwner(
        authority, store_id=_STORE_ID, fences=fences
    )
    return authority, fences, pre_fence


def test_live_legacy_registration_rejects_native_cutover_before_snapshot(
    tmp_path: Path,
) -> None:
    authority, fences, pre_fence = _fixture(tmp_path)
    control = tmp_path
    root_fd = os.open(
        control, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    io = RootedFileIO(control, root_fd)
    try:
        leases = PackageEpochRuntimeLeaseRegistry(
            path=control / "runtime-leases.jsonl",
            coordination_lock=control / "coordination",
            file_io=io,
            fences=fences,
            store_id=_STORE_ID,
        )

        class NoSnapshot:
            def capture(self, **_kwargs: object) -> object:
                pytest.fail("live old process reached snapshot capture")

        cutover = PackagePosixEpochCutoverOwner(
            authority,
            store_id=_STORE_ID,
            epoch_journal=fences,
            coordination=PackagePosixEpochCutoverCoordination(
                leases=leases, pre_fence=pre_fence
            ),
            snapshots=NoSnapshot(),
        )
        request = PackagePosixEpochCutoverRequestV1.create(
            store_id=_STORE_ID,
            prior_fence=None,
            expected_legacy_root_identity=cutover.current_root_identity(),
            namespace_id="a" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
        )
        with pre_fence.register(startup_id="legacy:live") as live:
            result = cutover.cutover(request)
            assert result.disposition == "rejected"
            assert result.failure is not None
            assert result.failure.barrier == "pre_fence"
            assert result.failure.evidence_ref == live.registration_id
            assert fences.current(_STORE_ID) is None
            assert not (authority / "epochs" / request.namespace_id).exists()
            with pre_fence.exclusive_quiescence(store_id=_STORE_ID) as proof:
                assert proof.active_registration_ids == (live.registration_id,)
                with pytest.raises(PackagePosixPreFenceRegistrationError) as busy:
                    pre_fence.register(startup_id="legacy:late")
                assert busy.value.code == "package_pre_fence_launch_busy"
        with pre_fence.exclusive_quiescence(store_id=_STORE_ID) as empty:
            assert empty.active_registration_ids == ()
    finally:
        io.cleanup()
        os.close(root_fd)


def test_cross_process_registration_is_visible_until_process_exits(
    tmp_path: Path,
) -> None:
    authority, _fences, pre_fence = _fixture(tmp_path)
    child_code = """
import sys
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import PackageEpochFenceJournal
from loushang.harness.resources.packages.plugin_lifecycle.posix_pre_fence_registration import PackagePosixPreFenceRegistrationOwner
from pathlib import Path
root = Path(sys.argv[1])
owner = PackagePosixPreFenceRegistrationOwner(root, store_id=sys.argv[2], fences=PackageEpochFenceJournal(Path(sys.argv[3])))
with owner.register(startup_id="legacy:child") as handle:
    print(handle.registration_id, flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_code,
            str(authority),
            _STORE_ID,
            str(tmp_path / "epoch.jsonl"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "legacy child did not register"
        registration_id = process.stdout.readline().strip()
        assert len(registration_id) == 64
        with pre_fence.exclusive_quiescence(store_id=_STORE_ID) as live:
            assert live.active_registration_ids == (registration_id,)
        assert process.stdin is not None
        process.stdin.write("\n")
        process.stdin.flush()
        assert process.wait(timeout=10) == 0
        with pre_fence.exclusive_quiescence(store_id=_STORE_ID) as empty:
            assert empty.active_registration_ids == ()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.communicate()


def test_in_flight_launch_barrier_refuses_cutover_scope_without_waiting(
    tmp_path: Path,
) -> None:
    import fcntl

    authority, _fences, pre_fence = _fixture(tmp_path)
    descriptor = os.open(
        authority, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(PackagePosixPreFenceRegistrationError) as busy:
            with pre_fence.exclusive_quiescence(store_id=_STORE_ID):
                pytest.fail("cutover entered while a launch held the barrier")
        assert busy.value.code == "package_pre_fence_launch_busy"
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
