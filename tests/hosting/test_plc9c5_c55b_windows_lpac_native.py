from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

from tests.hosting import test_child_session_host as session_evidence
from tests.hosting import test_windows_lpac_preparation as deterministic_evidence
from tests.hosting import test_windows_process as process_evidence
from tests.hosting.test_windows_lpac_preparation_native import (
    _WindowsLpacNativeEvidence,
)

pytest_plugins = ("tests.hosting.test_windows_lpac_preparation_native",)

pytestmark = [
    pytest.mark.skipif(
        os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"},
        reason="PLC9C5 C5.5b requires Windows AMD64 LPAC containment",
    ),
    pytest.mark.skipif(
        os.environ.get("LOUSHANG_PLC9C5_C55B_REPORT") != "1",
        reason="PLC9C5 C5.5b report runs only in its explicit native gate",
    ),
]

PLC9C5_C55B_CASES = (
    "C55B-PROFILE-CREATE",
    "C55B-CLEANUP-REPLAY",
    "C55B-FOREIGN-PROFILE-REJECT",
    "C55B-PROFILE-SID",
    "C55B-ZERO-CAPABILITIES",
    "C55B-LPAC-OPTOUT",
    "C55B-RUNTIME-RX",
    "C55B-RUNTIME-WRITE-DENY",
    "C55B-PRIVATE-FS-SCRATCH",
    "C55B-PRIVATE-REGISTRY-SCRATCH",
    "C55B-UNRELATED-FS-DENY",
    "C55B-PROCESS-MUTATION-DENY",
    "C55B-NETWORK-DENY",
    "C55B-EXEC-CWD-IDENTITY",
    "C55B-DACL-SUBSTITUTION",
    "C55B-PROFILE-SUBSTITUTION",
    "C55B-NO-AMBIENT-ENV",
    "C55B-HANDLE-LIST",
    "C55B-HANDLE-ALIAS-REJECT",
    "C55B-CANCEL-PRE-POST-EFFECT",
    "C55B-TOKEN-VERIFY-BEFORE-RESUME",
    "C55B-JOB-TREE-CLEANUP",
    "C55B-CONTAINMENT-CLEANUP-DEBT",
    "C55B-SENTINEL-REDACTION",
)

_FIELD_BY_CASE = {
    "C55B-PROFILE-CREATE": "profile_create",
    "C55B-CLEANUP-REPLAY": "cleanup_replay",
    "C55B-FOREIGN-PROFILE-REJECT": "foreign_profile_reject",
    "C55B-PROFILE-SID": "profile_sid",
    "C55B-ZERO-CAPABILITIES": "zero_capabilities",
    "C55B-LPAC-OPTOUT": "lpac_optout",
    "C55B-RUNTIME-RX": "runtime_rx",
    "C55B-RUNTIME-WRITE-DENY": "runtime_write_deny",
    "C55B-PRIVATE-FS-SCRATCH": "private_fs_scratch",
    "C55B-PRIVATE-REGISTRY-SCRATCH": "private_registry_scratch",
    "C55B-UNRELATED-FS-DENY": "unrelated_fs_deny",
    "C55B-PROCESS-MUTATION-DENY": "process_mutation_deny",
    "C55B-NETWORK-DENY": "network_deny",
    "C55B-EXEC-CWD-IDENTITY": "exec_cwd_identity",
    "C55B-DACL-SUBSTITUTION": "dacl_substitution",
    "C55B-PROFILE-SUBSTITUTION": "profile_substitution",
    "C55B-NO-AMBIENT-ENV": "no_ambient_env",
    "C55B-HANDLE-LIST": "handle_list",
    "C55B-HANDLE-ALIAS-REJECT": "handle_alias_reject",
    "C55B-CANCEL-PRE-POST-EFFECT": "cancel_pre_post_effect",
    "C55B-TOKEN-VERIFY-BEFORE-RESUME": "token_verify_before_resume",
    "C55B-JOB-TREE-CLEANUP": "job_tree_cleanup",
    "C55B-CONTAINMENT-CLEANUP-DEBT": "containment_cleanup_debt",
    "C55B-SENTINEL-REDACTION": "sentinel_redaction",
}


@pytest.mark.parametrize("case_id", PLC9C5_C55B_CASES, ids=PLC9C5_C55B_CASES)
def test_plc9c5_c55b_windows_lpac_native_case(
    case_id: str,
    windows_lpac_native_evidence: _WindowsLpacNativeEvidence,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert getattr(windows_lpac_native_evidence, _FIELD_BY_CASE[case_id])

    if case_id == "C55B-HANDLE-ALIAS-REJECT":
        deterministic_evidence.test_win32_lpac_handle_alias_fails_before_effect()
    elif case_id == "C55B-CANCEL-PRE-POST-EFFECT":
        session_evidence.test_managed_launch_final_fence_cancellation_prevents_spawn()
        process_evidence.test_windows_spawn_cancellation_waits_for_attachment_and_reclamation(
            tmp_path
        )
    elif case_id == "C55B-SENTINEL-REDACTION":
        deterministic_evidence.test_windows_lpac_native_failures_redact_paths_and_sentinels(
            monkeypatch
        )
