"""Explicit Linux operator actions for Worker candidates and native release."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from functools import partial
from pathlib import Path

from loushang.coding.package.product_preview import (
    CodingFencedProductReadOnlyPreviewOwner,
)
from loushang.coding.package.product_runtime import (
    _open_installed_product,
    admit_coding_external_worker_wheel,
)
from loushang.coding.package.product_worker_installed_native import (
    _product_native_release_custody,
)
from loushang.coding.package.product_worker_native_approval import (
    CodingWorkerNativeApprovalJournal,
)
from loushang.coding.package.product_worker_operator_query import (
    query_coding_product_worker,
)
from loushang.coding.package.product_worker_opt_in_owner import (
    CodingWorkerProductOptInOwner,
)
from loushang.coding.package.product_worker_registered_recovery import (
    _recovery_bindings,
)
from loushang.coding.package.product_worker_start_gate_recovery import (
    _GATED_RECOVERY,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.cli.worker_candidate import (
    NativeWorkerCandidateOperator,
    add_native_worker_review_commands,
    add_worker_candidate_commands,
    add_worker_candidate_opt_in_commands,
    execute_linux_worker_release_action,
    read_worker_candidate_status,
)
from loushang.harness.cli.worker_recovery import (
    add_posix_worker_recovery_commands,
    execute_posix_worker_recovery_action,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_worker_candidate import (
    NativeWorkerReleaseInput,
)

_RELEASE_INPUT = NativeWorkerReleaseInput(
    "Coding Worker native Wheel", 4 * 1024 * 1024, "linux-x86_64"
)


class CodingWorkerNativeCandidateCommandError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_CANDIDATE_OPERATOR = NativeWorkerCandidateOperator(
    product_id="coding",
    native_platform="linux-x86_64",
    label="Coding Worker",
    error_type=CodingWorkerNativeCandidateCommandError,
    error_prefix="coding_worker",
    not_directory="Coding workspace is not a directory",
    refused="Coding Worker native command refused",
    failure_code="coding_worker_native_command_unavailable",
    ordinary_session_routing="python_sdk_explicit_linux",
    compact=True,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-worker-native")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    actions = parser.add_subparsers(dest="action", required=True)
    add_worker_candidate_commands(
        actions,
        help_text={
            "candidate-capture": "capture one inert Product Worker Wheel candidate",
            "candidate-install": "install one captured Worker candidate disabled",
            "candidate-update": "update one installed Worker from an exact revision",
            "candidate-enable": "enable one exact installed Worker candidate",
            "candidate-disable": "disable one exact installed Worker candidate",
            "candidate-remove": "remove one Worker candidate from Desired State",
        },
        native_platform_option=_CANDIDATE_OPERATOR.native_platform,
    )
    actions.add_parser("status", help="read the current Product approval decision")
    add_native_worker_review_commands(
        actions,
        review_help="verify and review one native Wheel",
        approve_help="approve one unchanged review",
    )
    revoke = actions.add_parser("revoke", help="revoke the current release approval")
    revoke.add_argument("--operation-id", required=True)
    revoke.add_argument("--expected-generation", type=int, required=True)
    add_worker_candidate_opt_in_commands(
        actions,
        help_text={
            "candidate-status": "read one explicit Product Worker opt-in decision",
            "candidate-allow": "allow one selected Worker candidate, without routing Sessions",
            "candidate-revoke": "revoke one Product Worker candidate opt-in",
        },
    )
    query = actions.add_parser(
        "query", help="query an installed, selected Worker in an existing Session"
    )
    query.add_argument("--plugin-id", required=True)
    query.add_argument("--session-file", required=True)
    query.add_argument("--symbol", required=True)
    install = actions.add_parser("install", help="install the approved native Wheel")
    install.add_argument("--wheel", required=True)
    actions.add_parser("repair-install", help="finish one complete staged install")
    add_posix_worker_recovery_commands(actions)
    args = parser.parse_args(argv)

    return _CANDIDATE_OPERATOR.run(
        args,
        resolve_layout=resolve_coding_plugin_lifecycle_state_layout,
        admit=lambda layout: partial(admit_coding_external_worker_wheel, layout),
        execute=_run_product_action,
        platform_unavailable="platform_unsupported",
    )


def _run_product_action(
    lifecycle: CodingPluginLifecycleStateLayout,
    workspace: Path,
    args: argparse.Namespace,
) -> dict[str, object]:
    if args.action == "candidate-status":
        with CodingFencedProductReadOnlyPreviewOwner.open(
            lifecycle, worker_candidates=True
        ) as read_owner:
            return _read_candidate_status_document(read_owner, args.plugin_id)
    application = _open_installed_product(
        lifecycle,
        workspace=workspace,
        worker_candidates=True,
    )
    with _CANDIDATE_OPERATOR.hold_installed_product(
        application, PosixLocalWheelProductSessionOwner,
        unavailable="Coding Worker native Product owner is unsupported",
    ) as product:
        return _execute(product, args)


def _read_candidate_status_document(
    owner: CodingFencedProductReadOnlyPreviewOwner, plugin_id: str
) -> dict[str, object]:
    return read_worker_candidate_status(
        owner,
        plugin_id,
        ordinary_session_routing=_CANDIDATE_OPERATOR.ordinary_session_routing,
    )


def _execute(
    product: PosixLocalWheelProductSessionOwner,
    args: argparse.Namespace,
) -> dict[str, object]:
    candidate_result = _CANDIDATE_OPERATOR.execute_candidate_action(
        product, args, opt_in_owner=lambda: CodingWorkerProductOptInOwner(product)
    )
    if candidate_result is not None:
        return candidate_result
    if args.action == "query":
        answer = asyncio.run(
            query_coding_product_worker(
                product=product,
                workspace=product.workspace,
                plugin_id=args.plugin_id,
                session_file=Path(args.session_file).expanduser(),
                symbol=args.symbol,
            )
        )
        return {"workerQuery": {"text": answer}}
    recovered = execute_posix_worker_recovery_action(
        product,
        args,
        gated_recovery=_GATED_RECOVERY,
        recovery_bindings=_recovery_bindings,
    )
    if recovered is not None:
        return recovered
    return execute_linux_worker_release_action(
        product, args, _RELEASE_INPUT, _product_native_release_custody(),
        CodingWorkerNativeApprovalJournal(product), label=_CANDIDATE_OPERATOR.label,
    )


if __name__ == "__main__":
    raise SystemExit(main())
