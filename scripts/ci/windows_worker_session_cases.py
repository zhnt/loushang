"""Run one balanced shard of the native Windows Worker Session regression."""

from __future__ import annotations

import argparse
import subprocess
import sys

PRE_B = "tests/coding/test_package_windows_pre_b_snapshot.py::"
ACTIVATION = "tests/coding/test_package_product_worker_windows_activation_state.py::"
HOSTED = "tests/coding/test_hosted_session.py::"

CASE_GROUPS = {
    "direct": (
        PRE_B + "test_windows_worker_public_coding_session_reaches_selected_product",
    ),
    "recovery_hosted": (
        PRE_B + "test_windows_worker_public_session_crash_reopens_and_retires_product_attempt[hosted]",
        PRE_B + "test_windows_worker_public_session_disable_fences_pinned_product",
    ),
    "recovery_direct": (
        PRE_B + "test_windows_worker_public_session_crash_reopens_and_retires_product_attempt[direct]",
        PRE_B + "test_windows_worker_hosted_first_session_reaches_selected_product",
    ),
    "lifecycle": (
        ACTIVATION + "test_windows_product_c5_state_reopens_and_refuses_complete_record_loss",
        PRE_B + "test_windows_ordinary_selection_preserves_pre_b_without_writing",
        PRE_B + "test_windows_public_ordinary_session_enters_fresh_b_product",
        PRE_B + "test_windows_public_runtime_session_enters_fresh_b_product",
        PRE_B + "test_windows_ordinary_orphan_repair_refuses_worker_evidence",
        HOSTED + "test_windows_hosted_ordinary_session_enters_fresh_b_product",
        PRE_B + "test_windows_worker_native_normal_exit_c5_cleanup_evidence",
    ),
}
PR_CASES = {
    "query": (
        PRE_B + "test_windows_worker_hosted_first_session_reaches_selected_product",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("group", choices=(*CASE_GROUPS, *PR_CASES))
    group = parser.parse_args().group
    cases = CASE_GROUPS.get(group, PR_CASES.get(group))
    assert cases is not None
    return subprocess.run(
        [
            sys.executable,
            "scripts/dev/run_pytest.py",
            *cases,
            "--maxfail=1",
            "--durations=20",
            "-vv",
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
