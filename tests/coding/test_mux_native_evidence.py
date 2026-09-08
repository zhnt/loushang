"""Exact zero-skip G16 release evidence, reusing the authoritative fault cases."""

from __future__ import annotations

import inspect
import os
import sys
from functools import partial

import pytest

from tests.appserver import test_local as local
from tests.appserver import test_local_auth as auth
from tests.appserver import test_local_record as record
from tests.appserver import test_local_record_native as native
from tests.appservice import test_local_deployment as deployment


def _private_policy(tmp_path, monkeypatch):
    for target in ("root", "record", "lock"):
        if os.name == "nt":
            from tests.appserver import test_local_record_windows as windows

            for kind in ("world", "null"):
                root = tmp_path / f"{target}-{kind}"
                root.mkdir()
                windows.test_G16_PRIVATE_RECORD_windows_rejects_permissive_or_null_dacl_before_read(
                    root,
                    monkeypatch,
                    target,
                    kind,
                )
        else:
            root = tmp_path / target
            root.mkdir()
            native.test_G16_PRIVATE_RECORD_rejects_insecure_modes_without_repair(
                root, target
            )


def _no_follow(tmp_path, monkeypatch):
    if os.name == "nt":
        from tests.appserver import test_local_record_windows as windows

        windows.test_G16_PRIVATE_RECORD_windows_root_junction_is_not_followed(tmp_path)
    else:
        native.test_G16_PRIVATE_RECORD_symlink_is_not_followed(tmp_path, monkeypatch)


_CASES = (
    (
        "G16-PRIVATE-BEFORE-WRITE",
        native.test_G16_PRIVATE_RECORD_created_files_are_private_and_non_inheritable,
    ),
    ("G16-PRIVATE-POLICY", _private_policy),
    ("G16-NO-FOLLOW", _no_follow),
    (
        "G16-HARD-LINK",
        native.test_G16_PRIVATE_RECORD_hard_links_are_rejected_before_read,
    ),
    (
        "G16-RECORD-BOUNDS",
        native.test_G16_PRIVATE_RECORD_oversize_is_rejected_before_read,
    ),
    (
        "G16-RECORD-REPLACEMENT",
        native.test_G16_PRIVATE_RECORD_retire_preserves_identical_foreign_replacement,
    ),
    (
        "G16-READ-REPLACEMENT",
        native.test_G16_PRIVATE_RECORD_read_replacement_race_is_rejected,
    ),
    (
        "G16-LOCK-REPLACEMENT",
        native.test_G16_PRIVATE_RECORD_lock_replacement_fences_publication,
    ),
    (
        "G16-RECORD-CRASH",
        native.test_G16_PRIVATE_RECORD_native_process_crash_releases_lock_and_rotates_credentials,
    ),
    (
        "G16-PUBLICATION-FAILURE",
        partial(
            record.test_G16_PRIVATE_RECORD_failed_publication_retains_and_reclaims_exact_attempt,
            failure="rename_after",
        ),
    ),
    (
        "G16-WRONG-PRODUCT",
        local.test_G16_LOCAL_AUTH_expected_product_is_checked_on_admitted_record_before_io,
    ),
    (
        "G16-REAL-LOCAL-IO",
        local.test_G16_LOCAL_NATIVE_real_authenticated_request_and_client_eof_only_closes_scope,
    ),
    (
        "G16-WRONG-CREDENTIALS",
        local.test_G16_LOCAL_AUTH_wrong_key_never_constructs_semantics,
    ),
    (
        "G16-PENDING-BOUNDS",
        local.test_G16_LOCAL_BOUNDS_pending_authentication_is_reserved_before_tasks,
    ),
    (
        "G16-IDLE-PEER",
        local.test_G16_LOCAL_AUTH_idle_peer_expires_without_scope_admission,
    ),
    (
        "G16-STOP-RESERVE",
        local.test_G16_LOCAL_STOP_reserved_slot_and_reply_barrier_avoid_requester_self_wait,
    ),
    (
        "G16-CLEANUP-DEBT",
        local.test_G16_LOCAL_CLEANUP_debt_keeps_capacity_until_exact_scope_settles,
    ),
    (
        "G16-CANCELLED-START",
        local.test_G16_LOCAL_START_cancelled_bind_keeps_late_server_owner,
    ),
    (
        "G16-LOST-STOP-REPLY",
        local.test_G16_LOCAL_STOP_lost_reply_does_not_lose_admitted_stop,
    ),
    (
        "G16-LISTENER-READY-FENCE",
        partial(
            local.test_G16_LOCAL_READY_settlement_before_start_delivery_cannot_announce_ready,
            kind="listener",
        ),
    ),
    (
        "G16-CLIENT-READY-FENCE",
        partial(
            local.test_G16_LOCAL_READY_settlement_before_start_delivery_cannot_announce_ready,
            kind="client",
        ),
    ),
    (
        "G16-STOP-READY-FENCE",
        partial(
            local.test_G16_LOCAL_READY_settlement_before_start_delivery_cannot_announce_ready,
            kind="stop",
        ),
    ),
    (
        "G16-PROOF-REFLECTION",
        auth.test_G16_LOCAL_AUTH_client_rejects_reflected_client_proof,
    ),
    (
        "G16-PROOF-REPLAY",
        auth.test_G16_LOCAL_AUTH_captured_client_proof_cannot_replay_on_fresh_challenge,
    ),
    (
        "G16-FRAME-REPLAY",
        partial(
            auth.test_G16_PROFILE_frame_replay_fails_within_and_across_connections,
            fresh_channel=False,
        ),
    ),
    (
        "G16-FRAME-NEW-CONNECTION",
        partial(
            auth.test_G16_PROFILE_frame_replay_fails_within_and_across_connections,
            fresh_channel=True,
        ),
    ),
    (
        "G16-FRAME-BOUNDS",
        auth.test_G16_BOUNDS_authenticated_frame_rejects_oversize_before_body_read,
    ),
    (
        "G16-MULTI-MUX-AUTHORITY",
        deployment.test_G16_LOCAL_NATIVE_multi_mux_eof_retains_execution_and_reattach_fences_old_authority,
    ),
    (
        "G16-DISCONNECT-APPROVAL",
        deployment.test_G16_LOCAL_NATIVE_disconnect_denies_old_approval_before_regrant,
    ),
)


@pytest.mark.parametrize(
    "case", [pytest.param(function, id=case_id) for case_id, function in _CASES]
)
def test_G16_native_evidence(case, request, record_testsuite_property):
    assert sys.platform in {"linux", "darwin", "win32"}
    record_testsuite_property("native_platform", sys.platform)
    # Only these statically selected functions receive pytest fixtures; no
    # implementation, platform fault or assertion is replaced by the selector.
    arguments = {
        name: request.getfixturevalue(name)
        for name, parameter in inspect.signature(case).parameters.items()
        if parameter.default is inspect.Parameter.empty
    }
    case(**arguments)
