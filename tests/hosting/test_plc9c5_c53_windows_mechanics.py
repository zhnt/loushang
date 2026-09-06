from __future__ import annotations

import ntpath
import os
import platform
from pathlib import Path

import pytest

from loushang.hosting._win32_process import _CtypesWin32Api
from tests.harness.worker import test_native_profile_bridge as c52_evidence
from tests.harness.worker import test_product_activation as c51_evidence
from tests.hosting import test_child_session_host as session_evidence
from tests.hosting import test_windows_launch_preparation as preparation_evidence
from tests.hosting import (
    test_windows_launch_preparation_native as native_evidence,
)
from tests.hosting import test_windows_process as process_evidence

pytestmark = [
    pytest.mark.skipif(
        os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"},
        reason="PLC9C5 C5.3 requires Windows AMD64 native mechanics",
    ),
    pytest.mark.skipif(
        os.environ.get("LOUSHANG_PLC9C5_C53_REPORT") != "1",
        reason="PLC9C5 C5.3 retained report runs only in its explicit gate",
    ),
]

PLC9C5_C53_CASES = (
    "C53-REQUIRED-CONTAINMENT-REJECT",
    "C53-LOCKED-IDENTITY-SUBSTITUTION",
    "C53-TRUSTED-SYSTEMROOT",
    "C53-AMBIENT-SYSTEMROOT-POISONING",
    "C53-CALLER-ENVIRONMENT-REJECT",
    "C53-DISCARDED-STDERR",
    "C53-RESTRICTED-TOKEN",
    "C53-JOB-TREE-CLEANUP",
    "C53-HANDLE-SUBSTITUTION",
    "C53-CANCEL-PRE-POST-EFFECT",
    "C53-RESTART-UNCERTAINTY",
    "C53-SENTINEL-REDACTION",
)

@pytest.mark.parametrize("case_id", PLC9C5_C53_CASES, ids=PLC9C5_C53_CASES)
def test_plc9c5_c53_windows_mechanics_case(
    case_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if case_id == "C53-REQUIRED-CONTAINMENT-REJECT":
        c52_evidence.test_windows_mechanics_profile_is_rejected_for_product_required_containment(
            tmp_path
        )

    elif case_id == "C53-LOCKED-IDENTITY-SUBSTITUTION":
        preparation_evidence.test_windows_restricted_builder_identity_substitution_fails_capture(
            monkeypatch
        )

    elif case_id == "C53-TRUSTED-SYSTEMROOT":
        system_root = _CtypesWin32Api().canonical_system_root()
        drive, tail = ntpath.splitdrive(system_root)
        assert len(drive) == 2 and drive.endswith(":")
        assert tail.startswith("\\")
        assert ntpath.isabs(system_root)
        assert ntpath.normpath(system_root) == system_root

    elif case_id == "C53-AMBIENT-SYSTEMROOT-POISONING":
        sentinel = r"Z:\poisoned-secret"
        monkeypatch.setenv("SystemRoot", sentinel)
        system_root = _CtypesWin32Api().canonical_system_root()
        assert ntpath.normcase(system_root) != ntpath.normcase(sentinel)
        preparation_evidence.test_windows_restricted_builder_ignores_ambient_system_root(
            monkeypatch
        )

    elif case_id == "C53-CALLER-ENVIRONMENT-REJECT":
        preparation_evidence.test_windows_restricted_builder_rejects_caller_environment_before_acquisition()

    elif case_id == "C53-DISCARDED-STDERR":
        preparation_evidence.test_windows_restricted_builder_uses_only_os_owned_facts()
        preparation_evidence.test_windows_restricted_builder_rejects_non_discarded_stderr()

    elif case_id == "C53-RESTRICTED-TOKEN":
        preparation_evidence.test_win32_restricted_token_uses_the_exact_profile_flags()

    elif case_id == "C53-JOB-TREE-CLEANUP":
        native_evidence.test_windows_restricted_native_job_reclaims_descendant(tmp_path)

    elif case_id == "C53-HANDLE-SUBSTITUTION":
        preparation_evidence.test_windows_restricted_handle_collision_fails_before_effect(
            monkeypatch
        )

    elif case_id == "C53-CANCEL-PRE-POST-EFFECT":
        session_evidence.test_managed_launch_final_fence_cancellation_prevents_spawn()
        process_evidence.test_windows_spawn_cancellation_waits_for_attachment_and_reclamation(
            tmp_path
        )

    elif case_id == "C53-RESTART-UNCERTAINTY":
        c51_evidence.test_c51_registered_orphan_recovery_is_exact_idempotent_and_frees_cap(
            "C51-REGISTERED-RECOVERY",
            monkeypatch,
        )

    elif case_id == "C53-SENTINEL-REDACTION":
        preparation_evidence.test_windows_restricted_builder_redacts_native_failure_details()

    else:  # pragma: no cover - manifest and architecture guards fix this set
        raise AssertionError(f"Unhandled PLC9C5 C5.3 case {case_id}")
