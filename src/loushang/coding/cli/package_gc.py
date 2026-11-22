"""Explicit offline Package Store GC for a fenced Coding Product workspace."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from contextlib import closing
from importlib.metadata import version
from pathlib import Path

from loushang.coding.package.product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package.product_worker_posix_gc_history import (
    CodingPosixWorkerGcHistoryAuthority,
)
from loushang.coding.package.product_worker_windows_gc_history import (
    CodingWindowsWorkerGcHistoryAuthority,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.cli.package_gc import PackageGcOperator, add_package_gc_commands
from loushang.harness.cli.package_lifecycle import run_package_operator_command
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    open_posix_local_wheel_product_root_gc,
    open_windows_local_wheel_product_root_gc,
)
from loushang.harness.plugin_management.package_gc_dependencies import (
    PackageDependencyGcTargetV1,
)
from loushang.harness.plugin_management.package_gc_dependency_review import (
    PackageDependencyGcRepairReviewV1,
)

_GC_REPAIR_ACTOR = "coding:package-gc-cli"
_GC_REPAIR_POLICY = "coding:package-gc-repair-v1"
_WINDOWS_CANDIDATE_ROUTE_ADMITTED = True
_GC_OPERATOR = PackageGcOperator(
    repair_actor=_GC_REPAIR_ACTOR,
    repair_policy=_GC_REPAIR_POLICY,
    operation_domain=b"loushang.coding-package-root-gc/v1",
    operation_prefix="coding-package-gc",
)
_operation_identity = _GC_OPERATOR.operation_identity
_run = _GC_OPERATOR.execute


class _CodingPackageGcRepairAuthority:
    def authorizes(
        self,
        review: PackageDependencyGcRepairReviewV1,
        target: PackageDependencyGcTargetV1,
    ) -> bool:
        return (
            review.actor_id == _GC_REPAIR_ACTOR
            and review.policy_revision == _GC_REPAIR_POLICY
            and review.settlement_id == target.settlement_id
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-package-gc")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    parser.add_argument(
        "--windows-candidate",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--worker-candidates",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    add_package_gc_commands(parser)
    args = parser.parse_args(argv)

    if (
        os.name == "nt"
        and (not args.windows_candidate or not _WINDOWS_CANDIDATE_ROUTE_ADMITTED)
    ) or (
        os.name != "nt"
        and (not sys.platform.startswith("linux") or args.windows_candidate)
    ):
        sys.stderr.write("Coding Package GC refused: package_gc_platform_unsupported\n")
        return 1

    def execute(workspace: Path) -> dict[str, object]:
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
        application = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            windows_candidate=args.windows_candidate,
            worker_candidates=args.worker_candidates,
        )
        with closing(application) as owner:
            product = owner.runtime_owner.product_owner
            gc = (
                open_windows_local_wheel_product_root_gc(
                    product,
                    repair_authority=_CodingPackageGcRepairAuthority(),
                    worker_history_authority=CodingWindowsWorkerGcHistoryAuthority(
                        product
                    ),
                )
                if isinstance(product, WindowsLocalWheelProductSessionOwner)
                else open_posix_local_wheel_product_root_gc(
                    product,
                    repair_authority=_CodingPackageGcRepairAuthority(),
                    worker_history_authority=CodingPosixWorkerGcHistoryAuthority(
                        product
                    ),
                )
            )
            return _run(gc, args)

    return run_package_operator_command(
        args.workspace,
        execute,
        not_directory="Coding workspace must be a directory",
        refused="Coding Package GC refused",
        failure_reason=lambda error: getattr(error, "code", None) or str(error),
    )


if __name__ == "__main__":
    raise SystemExit(main())
