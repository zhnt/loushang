"""Fresh-process operator journey for the Linux Worker native release."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

import pytest

import loushang.coding.package_product_worker_payload as worker_payload_module
from loushang.ai.types import UserMessage
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    admit_coding_external_worker_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_payload import (
    CodingWorkerPayloadDebtPlanV1,
    open_coding_product_worker_supervisor_journal,
    repair_coding_product_worker_unmarked_payload_debt,
    review_coding_product_worker_unmarked_payload_debt,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.worker.contracts import WorkerLaunchIdentityV1
from loushang.plugin._coding_local_worker_wheel import (
    build_coding_local_worker_candidate_wheel,
)
from tests.coding.test_package_worker_candidate_wheel import _QUERY_WORKER_SOURCE

_ROOT = Path(__file__).resolve().parents[2]
_BUILDER = _ROOT / "scripts/dev/build_posix_containment_launcher.py"
_WHEEL_BUILDER = _ROOT / "scripts/dev/build_posix_native_release_wheel.py"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux Product payload custody")
def test_worker_native_cli_repairs_empty_pre_marker_stage_across_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        worker_candidates=True,
    )
    attempt_id = "12" * 16
    try:
        stage = owner.runtime_owner.product_owner.state_root / (
            f"worker-payload-{attempt_id}"
        )
        stage.mkdir(mode=0o700)
    finally:
        owner.close()
    command = (
        sys.executable,
        "-m",
        "loushang.coding.cli.package_worker_native",
        "--workspace",
        str(workspace),
    )

    def run(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            (*command, *args),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            env=os.environ.copy(),
            check=False,
        )

    reviewed = run("review-empty-payload-debt", "--attempt-id", attempt_id)
    assert reviewed.returncode == 0, reviewed.stderr
    plan_id = json.loads(reviewed.stdout)["emptyPayloadDebtReview"]["planId"]
    assert isinstance(plan_id, str) and len(plan_id) == 64
    stale = run(
        "repair-empty-payload-debt",
        "--attempt-id",
        attempt_id,
        "--plan-id",
        "0" * 64,
    )
    assert stale.returncode == 1
    assert b"coding_worker_payload_debt_plan_stale" in stale.stderr
    assert stage.is_dir()
    repaired = run(
        "repair-empty-payload-debt",
        "--attempt-id",
        attempt_id,
        "--plan-id",
        plan_id,
    )
    assert repaired.returncode == 0, repaired.stderr
    assert json.loads(repaired.stdout)["emptyPayloadDebtRepair"] == {
        "attemptId": attempt_id,
        "planId": plan_id,
    }
    assert not stage.exists()
    replay = run(
        "repair-empty-payload-debt",
        "--attempt-id",
        attempt_id,
        "--plan-id",
        plan_id,
    )
    assert replay.returncode == 0, replay.stderr
    assert replay.stdout == repaired.stdout
    stale_replay = run(
        "repair-empty-payload-debt",
        "--attempt-id",
        attempt_id,
        "--plan-id",
        "0" * 64,
    )
    assert stale_replay.returncode == 1
    assert b"coding_worker_payload_debt_plan_stale" in stale_replay.stderr

    unmarked_attempt = "34" * 16
    unmarked_owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        worker_candidates=True,
    )
    try:
        unmarked_stage = (
            unmarked_owner.runtime_owner.product_owner.state_root
            / f"worker-payload-{unmarked_attempt}"
        )
        unmarked_stage.mkdir(mode=0o700)
        (unmarked_stage / "bin").mkdir(mode=0o700)
        (unmarked_stage / "bin" / "worker").write_bytes(b"partial CLI Worker")
        (unmarked_stage / "bin" / "worker").chmod(0o600)
    finally:
        unmarked_owner.close()
    unmarked_reviewed = run(
        "review-unmarked-payload-debt", "--attempt-id", unmarked_attempt
    )
    assert unmarked_reviewed.returncode == 0, unmarked_reviewed.stderr
    unmarked_review = json.loads(unmarked_reviewed.stdout)["unmarkedPayloadDebtReview"]
    assert [item["relativePath"] for item in unmarked_review["members"]] == [
        "bin",
        "bin/worker",
    ]
    unmarked_id = unmarked_review["reviewId"]
    stale_unmarked = run(
        "repair-unmarked-payload-debt",
        "--attempt-id",
        unmarked_attempt,
        "--review-id",
        "0" * 64,
    )
    assert stale_unmarked.returncode == 1
    assert b"coding_worker_payload_debt_plan_stale" in stale_unmarked.stderr
    partial_owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        worker_candidates=True,
    )
    try:
        partial_product = partial_owner.runtime_owner.product_owner
        assert isinstance(partial_product, PosixLocalWheelProductSessionOwner)
        partial_review = review_coding_product_worker_unmarked_payload_debt(
            partial_product, attempt_id=unmarked_attempt
        )
        assert partial_review.fingerprint == unmarked_id

        def interrupt_unmarked_repair(
            root_fd: int,
            stage_fd: int,
            stage_name: str,
            expected: object,
            *,
            allow_partial: bool,
        ) -> None:
            assert stage_name == f"worker-payload-{unmarked_attempt}"
            assert expected == partial_review and allow_partial
            parent_fd = os.open(
                "bin",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=stage_fd,
            )
            try:
                os.unlink("worker", dir_fd=parent_fd)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            raise OSError("injected pre-marker cleanup interruption")

        with monkeypatch.context() as patch:
            patch.setattr(
                worker_payload_module,
                "_remove_unmarked_repair_remainder",
                interrupt_unmarked_repair,
            )
            with pytest.raises(OSError, match="pre-marker cleanup interruption"):
                repair_coding_product_worker_unmarked_payload_debt(
                    partial_product, expected_review=partial_review
                )
    finally:
        partial_owner.close()
    assert (unmarked_stage / "bin").is_dir()
    assert not (unmarked_stage / "bin" / "worker").exists()
    repaired_unmarked = run(
        "repair-unmarked-payload-debt",
        "--attempt-id",
        unmarked_attempt,
        "--review-id",
        unmarked_id,
    )
    assert repaired_unmarked.returncode == 0, repaired_unmarked.stderr
    assert json.loads(repaired_unmarked.stdout)["unmarkedPayloadDebtRepair"] == {
        "attemptId": unmarked_attempt,
        "reviewId": unmarked_id,
    }
    assert not unmarked_stage.exists()
    replay_unmarked = run(
        "repair-unmarked-payload-debt",
        "--attempt-id",
        unmarked_attempt,
        "--review-id",
        unmarked_id,
    )
    assert replay_unmarked.returncode == 0, replay_unmarked.stderr
    assert replay_unmarked.stdout == repaired_unmarked.stdout

    complete_attempt = "9a" * 16
    complete_owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        worker_candidates=True,
    )
    try:
        product = complete_owner.runtime_owner.product_owner
        assert isinstance(product, PosixLocalWheelProductSessionOwner)
        complete_stage = product.state_root / f"worker-payload-{complete_attempt}"
        complete_stage.mkdir(mode=0o700)
        body = b"settled CLI payload fixture"
        stage_fd = os.open(complete_stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            worker_payload_module._write_payload(stage_fd, "bin/worker", body)
            metadata = os.fstat(stage_fd)
            complete_plan = CodingWorkerPayloadDebtPlanV1(
                attempt_id=complete_attempt,
                entrypoint="bin/worker",
                payload_digest=sha256(body).hexdigest(),
                payload_size=len(body),
                receipt_fingerprint="f" * 64,
                stage_device=metadata.st_dev,
                stage_inode=metadata.st_ino,
            )
            worker_payload_module._write_marker(stage_fd, complete_plan)
        finally:
            os.close(stage_fd)
        journal = open_coding_product_worker_supervisor_journal(product)
        identity = WorkerLaunchIdentityV1(
            plugin_id="workerprobe",
            plugin_revision_digest="a" * 64,
            contribution_id="query-provider",
            owner_id="coding.lsp",
            product_id="coding",
            scope_id="test-scope",
            owner_generation=1,
            declaration_fingerprint="b" * 64,
            worker_configuration_fingerprint="c" * 64,
            attempt_id=complete_attempt,
            supervisor_epoch=1,
            session_nonce="d" * 64,
        )
        claimed = journal.claim(identity, max_attempts=1)
        failed = journal.transition(
            complete_attempt,
            expected_phase="claimed",
            next_phase="failed",
            expected_record_revision=claimed.record_revision,
            expected_supervisor_epoch=1,
            failure_code="worker_launch_failed",
        )
        journal.transition(
            complete_attempt,
            expected_phase="failed",
            next_phase="process_settled",
            expected_record_revision=failed.record_revision,
            expected_supervisor_epoch=1,
            failure_code=failed.failure_code,
        )
    finally:
        complete_owner.close()
    complete_repair = run(
        "repair-payload-debt",
        "--attempt-id",
        complete_attempt,
        "--plan-id",
        complete_plan.fingerprint,
    )
    assert complete_repair.returncode == 0, complete_repair.stderr
    assert json.loads(complete_repair.stdout)["payloadDebtRepair"] == {
        "attemptId": complete_attempt,
        "planId": complete_plan.fingerprint,
    }
    assert not complete_stage.exists()
    complete_replay = run(
        "repair-payload-debt",
        "--attempt-id",
        complete_attempt,
        "--plan-id",
        complete_plan.fingerprint,
    )
    assert complete_replay.returncode == 0, complete_replay.stderr
    assert complete_replay.stdout == complete_repair.stdout
    stale_complete_replay = run(
        "repair-payload-debt",
        "--attempt-id",
        complete_attempt,
        "--plan-id",
        "0" * 64,
    )
    assert stale_complete_replay.returncode == 1
    assert b"coding_worker_payload_debt_plan_stale" in stale_complete_replay.stderr


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="Linux native Worker release")
def test_worker_native_operator_cli_reopens_product_across_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    source = tmp_path / "reviewworker-1-py3-none-manylinux_2_17_x86_64.whl"
    compiler = shutil.which("cc")
    assert compiler is not None
    executable = tmp_path / "contained-query-worker"
    built_worker = subprocess.run(
        (
            compiler,
            "-static",
            "-O2",
            "-s",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-o",
            str(executable),
            str(_QUERY_WORKER_SOURCE),
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert built_worker.returncode == 0, built_worker.stderr
    source.write_bytes(
        build_coding_local_worker_candidate_wheel(
            plugin_id="reviewworker",
            version="1",
            contribution_id="query-provider",
            owner_id="coding",
            native_platform="linux-x86_64",
            wheel_tag="py3-none-manylinux_2_17_x86_64",
            executable=executable.read_bytes(),
        )
    )
    admit_coding_external_worker_wheel(
        layout,
        source=source,
        admission=PackageProductLocalWorkerAdmissionV1(
            contribution_id="query-provider",
            owner_id="coding",
            native_platform="linux-x86_64",
        ),
    )
    release = tmp_path / "release"
    built = subprocess.run(
        (sys.executable, str(_BUILDER), "--output-dir", str(release)),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    packaged = subprocess.run(
        (
            sys.executable,
            str(_WHEEL_BUILDER),
            "--release-dir",
            str(release),
            "--wheel-dir",
            str(tmp_path / "native-wheels"),
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert packaged.returncode == 0, packaged.stderr
    native_wheel = Path(packaged.stdout.decode().strip())
    command = (
        sys.executable,
        "-m",
        "loushang.coding.cli.package_worker_native",
        "--workspace",
        str(workspace),
    )

    def run(*args: str) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
        result = subprocess.run(
            (*command, *args),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=90,
            env=os.environ.copy(),
            check=False,
        )
        document = json.loads(result.stdout) if result.stdout else {}
        return result, document

    reviewed, review_output = run("review", "--wheel", str(native_wheel))
    assert reviewed.returncode == 0, reviewed.stderr
    review = review_output["nativeReleaseReview"]
    assert isinstance(review, dict)
    review_id = review["reviewId"]
    assert isinstance(review_id, str) and len(review_id) == 64
    wrong, _ = run(
        "approve",
        "--wheel",
        str(native_wheel),
        "--review-id",
        "0" * 64,
        "--operation-id",
        "native-cli-approve-one",
        "--expected-generation",
        "0",
    )
    assert wrong.returncode == 1
    assert b"coding_worker_native_command_unavailable" in wrong.stderr
    status, status_output = run("status")
    assert status.returncode == 0
    assert status_output == {"approvalDecision": None}
    approved, approved_output = run(
        "approve",
        "--wheel",
        str(native_wheel),
        "--review-id",
        review_id,
        "--operation-id",
        "native-cli-approve-one",
        "--expected-generation",
        "0",
    )
    assert approved.returncode == 0, approved.stderr
    approved_decision = approved_output["approvalDecision"]
    assert isinstance(approved_decision, dict)
    assert approved_decision["generation"] == 1
    installed, installed_output = run("install", "--wheel", str(native_wheel))
    assert installed.returncode == 0, installed.stderr
    installed_closure = installed_output["nativeClosure"]
    assert isinstance(installed_closure, dict)
    installed_revision = installed_closure["nativeProfileCatalogRevision"]
    assert isinstance(installed_revision, str) and installed_revision.endswith(":g1")
    candidate_status, candidate_output = run(
        "candidate-status", "--plugin-id", "reviewworker"
    )
    assert candidate_status.returncode == 0, candidate_status.stderr
    assert candidate_output == {
        "candidateOptInDecision": None,
        "ordinarySessionRouting": "python_sdk_explicit_linux",
        "defaultSessionRouting": "closed",
    }
    before_selection, _ = run(
        "candidate-allow",
        "--plugin-id",
        "reviewworker",
        "--operation-id",
        "candidate-before-selection",
        "--expected-generation",
        "0",
    )
    assert before_selection.returncode == 1
    assert b"coding_worker_opt_in_selection_unavailable" in before_selection.stderr

    selected_owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        worker_candidates=True,
    )
    try:
        product = selected_owner.runtime_owner.product_owner
        gate_history = product.state_root / "worker-start-gates.jsonl"
        (binding,) = tuple(
            item
            for item in product.policy.bindings
            if item.source_trust_class == "local-worker-candidate"
        )
        runtime = product.factory_for_session(
            session_id="candidate-cli-install",
            cwd=workspace,
            runtime_id="candidate-cli-install",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="candidate-cli-install",
                cwd=str(workspace),
            )
        )
        try:
            runtime.activate()
            result = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="candidate-cli-install",
                    action="install",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert result.handled
            assert result.record is not None
            assert result.record.lifecycle == "installed"
            snapshot = product.desired_state.snapshot()
            (installation,) = tuple(
                item
                for item in snapshot.installations
                if item.installation_key.plugin_id == "reviewworker"
            )
            enabled = product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="candidate-cli-enable",
                        idempotency_key="candidate-cli-enable",
                        expected_inventory_revision=snapshot.inventory_revision,
                        installation_key=installation.installation_key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id=product.actor_id,
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert enabled.status == "terminal"
        finally:
            runtime.dispose_runtime()
    finally:
        selected_owner.close()

    allowed, allowed_output = run(
        "candidate-allow",
        "--plugin-id",
        "reviewworker",
        "--operation-id",
        "candidate-cli-allow",
        "--expected-generation",
        "0",
    )
    assert allowed.returncode == 0, allowed.stderr
    decision = allowed_output["candidateOptInDecision"]
    assert allowed_output["ordinarySessionRouting"] == "python_sdk_explicit_linux"
    assert allowed_output["defaultSessionRouting"] == "closed"
    assert isinstance(decision, dict)
    assert decision["action"] == "allow"
    assert decision["generation"] == 1
    opt_in = decision["optIn"]
    assert isinstance(opt_in, dict)
    assert opt_in["pluginId"] == "reviewworker"
    assert not gate_history.exists()
    assert not gate_history.with_name(gate_history.name + ".lock").exists()
    empty_attempts, empty_attempts_output = run("list-gated-attempts")
    assert empty_attempts.returncode == 0, empty_attempts.stderr
    assert empty_attempts_output == {"gatedAttempts": []}
    assert not gate_history.exists()
    assert not gate_history.with_name(gate_history.name + ".lock").exists()
    absent_session, _ = run(
        "query",
        "--plugin-id",
        "reviewworker",
        "--session-file",
        str(tmp_path / "missing-session.jsonl"),
        "--symbol",
        "review",
    )
    assert absent_session.returncode == 1
    assert b"coding_worker_query_session_unavailable" in absent_session.stderr
    transcript_root = tmp_path / "worker-query-transcripts"
    transcript_root.mkdir()
    session = asyncio.run(
        SessionManager.new(
            session_dir=transcript_root,
            cwd=str(workspace),
            session_id="candidate-cli-query",
        )
    )
    asyncio.run(
        session.append_message(
            UserMessage(role="user", content="Worker query", timestamp=1.0)
        )
    )
    session_file = session.get_session_file()
    assert session_file is not None
    invalid_query, _ = run(
        "query",
        "--plugin-id",
        "reviewworker",
        "--session-file",
        str(session_file),
        "--symbol",
        "review;other",
    )
    assert invalid_query.returncode == 1
    assert b"coding_worker_query_symbol_invalid" in invalid_query.stderr
    queried, query_output = run(
        "query",
        "--plugin-id",
        "reviewworker",
        "--session-file",
        str(session_file),
        "--symbol",
        "review",
    )
    assert queried.returncode == 0, queried.stderr
    assert query_output == {"workerQuery": {"text": "Review symbol"}}
    for _ in range(3):
        repeated_query, repeated_output = run(
            "query",
            "--plugin-id",
            "reviewworker",
            "--session-file",
            str(session_file),
            "--symbol",
            "review",
        )
        assert repeated_query.returncode == 0, repeated_query.stderr
        assert repeated_output == query_output
    listed_attempts, listed_attempts_output = run("list-gated-attempts")
    assert listed_attempts.returncode == 0, listed_attempts.stderr
    attempts = listed_attempts_output["gatedAttempts"]
    assert isinstance(attempts, list) and len(attempts) == 4
    assert len({item["attemptId"] for item in attempts}) == 4
    assert all(item["phase"] == "bound" for item in attempts)
    gate_lock = gate_history.with_name(gate_history.name + ".lock")
    hidden_lock = gate_lock.with_name(gate_lock.name + ".held")
    gate_lock.rename(hidden_lock)
    try:
        missing_lock, _ = run("list-gated-attempts")
        assert missing_lock.returncode == 1
        assert b"coding_worker_start_gate_lock_missing" in missing_lock.stderr
    finally:
        hidden_lock.rename(gate_lock)
    replay, replay_output = run(
        "candidate-allow",
        "--plugin-id",
        "reviewworker",
        "--operation-id",
        "candidate-cli-allow",
        "--expected-generation",
        "0",
    )
    assert replay.returncode == 0, replay.stderr
    assert replay_output == allowed_output
    changed_replay, _ = run(
        "candidate-allow",
        "--plugin-id",
        "reviewworker",
        "--operation-id",
        "candidate-cli-allow",
        "--expected-generation",
        "0",
        "--require-worker",
    )
    assert changed_replay.returncode == 1
    assert b"coding_worker_opt_in_operation_conflict" in changed_replay.stderr
    stale, _ = run(
        "candidate-allow",
        "--plugin-id",
        "reviewworker",
        "--operation-id",
        "candidate-cli-stale",
        "--expected-generation",
        "0",
    )
    assert stale.returncode == 1
    assert b"coding_worker_opt_in_stale" in stale.stderr
    status, status_output = run("candidate-status", "--plugin-id", "reviewworker")
    assert status.returncode == 0, status.stderr
    assert status_output == allowed_output
    revoked_candidate, revoked_candidate_output = run(
        "candidate-revoke",
        "--plugin-id",
        "reviewworker",
        "--operation-id",
        "candidate-cli-revoke",
        "--expected-generation",
        "1",
    )
    assert revoked_candidate.returncode == 0, revoked_candidate.stderr
    revoked_decision = revoked_candidate_output["candidateOptInDecision"]
    assert revoked_candidate_output["ordinarySessionRouting"] == "python_sdk_explicit_linux"
    assert revoked_candidate_output["defaultSessionRouting"] == "closed"
    assert isinstance(revoked_decision, dict)
    assert revoked_decision["action"] == "revoke"
    assert revoked_decision["killSwitchGeneration"] == 1
    after_revoke, _ = run(
        "query",
        "--plugin-id",
        "reviewworker",
        "--session-file",
        str(session_file),
        "--symbol",
        "review",
    )
    assert after_revoke.returncode == 1
    assert b"coding_worker_query_not_selected" in after_revoke.stderr
    revoked, revoked_output = run(
        "revoke",
        "--operation-id",
        "native-cli-revoke-two",
        "--expected-generation",
        "1",
    )
    assert revoked.returncode == 0, revoked.stderr
    revoked_approval = revoked_output["approvalDecision"]
    assert isinstance(revoked_approval, dict)
    assert revoked_approval["generation"] == 2
    refused, _ = run("install", "--wheel", str(native_wheel))
    assert refused.returncode == 1
    assert b"coding_worker_native_command_unavailable" in refused.stderr
