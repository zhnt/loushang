"""Explicit offline first-B cutover and reviewed old-workspace adoption."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from typing import Literal, cast, overload

from loushang.coding.control.settings_store import open_coding_workspace_settings
from loushang.coding.package.cutover_backup import inspect_coding_package_cutover_backup
from loushang.coding.package.epoch_layout import (
    CodingPackageEpochLayoutV1,
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
    resolve_coding_package_pre_b_store_members,
)
from loushang.coding.package.legacy_builtin_adoption import (
    adopt_coding_first_b_builtin_only,
)
from loushang.coding.package.legacy_builtin_review import (
    admit_coding_builtin_only_snapshot,
    review_coding_first_b_builtin_only,
)
from loushang.coding.package.legacy_disabled_review import (
    review_coding_first_b_disabled_only,
)
from loushang.coding.package.legacy_local_adoption import (
    adopt_coding_legacy_local_data_review,
    replay_coding_posix_legacy_product_cutover,
)
from loushang.coding.package.legacy_removed_adoption import (
    adopt_coding_first_b_removed_local,
)
from loushang.coding.package.legacy_removed_review import (
    admit_coding_removed_local_snapshot,
    review_coding_first_b_removed_local,
)
from loushang.coding.package.legacy_review import (
    review_coding_legacy_installed_local_source,
)
from loushang.coding.package.legacy_skill_cutover_admission import (
    admit_coding_single_legacy_skill_snapshot,
    require_coding_fenced_single_legacy_data,
)
from loushang.coding.package.pre_b_snapshot import (
    CodingCutoverSnapshotAdmission,
    cutover_and_bootstrap_coding_package_product,
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
    reopen_coding_package_cutover,
)
from loushang.coding.package.product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION,
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    _fresh_coding_product_namespace_id,
    bootstrap_coding_accepted_disabled_only_product_plugins,
    bootstrap_coding_builtin_product_plugins,
    is_coding_fresh_first_b_snapshot,
    require_fresh_coding_product_inputs_without_writes,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.cli.package_lifecycle import (
    package_operator_workspace,
    write_package_operator_result,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_runtime import (
    inspect_fresh_product_epoch,
    legacy_product_fence_exists,
    open_native_fenced_product_epoch,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

_WINDOWS_CANDIDATE_ROUTE_ADMITTED = True


_LegacyResourceKind = Literal["skill", "prompt", "theme"]
_LEGACY_DATA_ROUTES: tuple[tuple[_LegacyResourceKind, str], ...] = (
    ("skill", "Skill"),
    ("prompt", "Prompt"),
    ("theme", "Theme"),
)


@overload
def _selected_local_action(
    args: argparse.Namespace, action: Literal["prepare"]
) -> tuple[_LegacyResourceKind, str] | None: ...


@overload
def _selected_local_action(
    args: argparse.Namespace, action: Literal["adopt"]
) -> tuple[_LegacyResourceKind, list[str]] | None: ...


def _selected_local_action(
    args: argparse.Namespace, action: Literal["prepare", "adopt"]
) -> tuple[_LegacyResourceKind, str | list[str]] | None:
    for kind, _ in _LEGACY_DATA_ROUTES:
        selection = getattr(args, f"{action}_legacy_local_{kind}_review")
        if selection is not None:
            return kind, selection
    return None


def main(argv: Sequence[str] | None = None) -> int:
    review_routes = (
        (
            "disabled",
            (
                "read the first-B snapshot's scoped disabled-only migration review",
                "commit the offline first-B fence and return a disabled-only review",
                "accept exactly one reviewed snapshot and seed Product Desired State",
            ),
            review_coding_first_b_disabled_only,
            None,
            bootstrap_coding_accepted_disabled_only_product_plugins,
        ),
        (
            "builtin",
            (
                "read a fenced old builtin Desired State review",
                "fence an eligible builtin-only old Desired State and return its review",
                "accept one reviewed old builtin Desired State into Product",
            ),
            review_coding_first_b_builtin_only,
            admit_coding_builtin_only_snapshot,
            adopt_coding_first_b_builtin_only,
        ),
        (
            "removed",
            (
                "read a fenced old local Plugin removal review",
                "fence an eligible old local removal set and return its review",
                "accept one reviewed old local removal set into Product",
            ),
            review_coding_first_b_removed_local,
            admit_coding_removed_local_snapshot,
            adopt_coding_first_b_removed_local,
        ),
    )
    parser = argparse.ArgumentParser(prog="loushang-package-cutover")
    parser.add_argument("--workspace", default=".", help="existing Coding workspace")
    parser.add_argument(
        "--windows-candidate",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    read_actions = parser.add_mutually_exclusive_group()
    read_actions.add_argument(
        "--backup-status",
        action="store_true",
        help="read the current cutover snapshot owner's verified status",
    )
    for kind, (read_help, _, _), *_handlers in review_routes:
        read_actions.add_argument(
            f"--review-legacy-{kind}-only", action="store_true", help=read_help,
        )
    read_actions.add_argument(
        "--review-legacy-local-plugin",
        metavar="PLUGIN_ID",
        help="read one installed local Plugin review under an existing first-B fence",
    )
    for kind, (_, prepare_help, _), *_handlers in review_routes:
        read_actions.add_argument(
            f"--prepare-legacy-{kind}-review", action="store_true", help=prepare_help,
        )
    for kind, label in _LEGACY_DATA_ROUTES:
        read_actions.add_argument(
            f"--prepare-legacy-local-{kind}-review",
            metavar="PLUGIN_ID",
            help=f"fence eligible old local {label}s and review one Plugin",
        )
    for kind, (_, _, adopt_help), *_handlers in review_routes:
        read_actions.add_argument(
            f"--adopt-legacy-{kind}-review", metavar="REVIEW_ID", help=adopt_help,
        )
    for kind, label in _LEGACY_DATA_ROUTES:
        read_actions.add_argument(
            f"--adopt-legacy-local-{kind}-review",
            nargs=2,
            metavar=("PLUGIN_ID", "REVIEW_ID"),
            help=f"accept a reviewed old local {label} and complete its Product adoption",
        )
    args = parser.parse_args(argv)
    try:
        workspace = package_operator_workspace(
            args.workspace, not_directory="Coding workspace must be a directory"
        )
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
        epoch = resolve_coding_package_epoch_layout(lifecycle)
        if args.backup_status:
            document = inspect_coding_package_cutover_backup(lifecycle).to_dict()
            return write_package_operator_result(document)
        windows = os.name == "nt"
        local_prepare = _selected_local_action(args, "prepare")
        local_adopt = _selected_local_action(args, "adopt")
        if windows:
            if (
                not args.windows_candidate
                or not _WINDOWS_CANDIDATE_ROUTE_ADMITTED
                or args.review_legacy_local_plugin is not None
                or local_prepare is not None
                or local_adopt is not None
                or any(
                    getattr(args, f"review_legacy_{kind}_only")
                    or getattr(args, f"prepare_legacy_{kind}_review")
                    or getattr(args, f"adopt_legacy_{kind}_review") is not None
                    for kind, *_ in review_routes if kind != "builtin"
                )
            ):
                raise RuntimeError(
                    "Windows Coding Product write CLI requires an admitted candidate"
                )
        elif args.windows_candidate:
            raise ValueError("Windows Product candidate requires Windows")
        for kind, _, project_review, admit_snapshot, _adopt in reversed(review_routes):
            read_review = getattr(args, f"review_legacy_{kind}_only")
            prepare_review = getattr(args, f"prepare_legacy_{kind}_review")
            if not (read_review or prepare_review):
                continue
            settings = open_coding_workspace_settings(workspace)
            if prepare_review:
                _prepare_review_cutover(
                    lifecycle,
                    settings,
                    epoch,
                    _fresh_coding_product_namespace_id(epoch.store_id),
                    snapshot_admission=(
                        partial(admit_snapshot, lifecycle)
                        if admit_snapshot is not None
                        else None
                    ),
                    before_prepare=(
                        partial(_require_disabled_only_preflight, lifecycle, settings)
                        if admit_snapshot is None
                        else None
                    ),
                )
            with closing(open_native_fenced_product_epoch(
                windows=windows, posix_read_only=True, **epoch.fenced_runtime_open_kwargs()
            )) as owner:
                # The Windows gate admits only the cross-platform builtin reviewer.
                review = project_review(
                    lifecycle, cast(PackageProductPosixFencedRuntimeOwner, owner),
                    settings_manager=settings,
                )
                if windows:
                    document = review.to_dict()
            return write_package_operator_result(document if windows else review.to_dict())

        prepare_kind, review_plugin_id = (
            local_prepare
            if local_prepare is not None
            else (None, args.review_legacy_local_plugin)
        )
        if review_plugin_id:
            if prepare_kind is not None:
                _prepare_review_cutover(
                    lifecycle,
                    open_coding_workspace_settings(workspace),
                    epoch,
                    _fresh_coding_product_namespace_id(epoch.store_id),
                    snapshot_admission=partial(
                        admit_coding_single_legacy_skill_snapshot,
                        lifecycle,
                        plugin_id=review_plugin_id,
                        resource_kind=prepare_kind,
                    ),
                )
            with PackageProductPosixFencedRuntimeOwner.open(
                **epoch.fenced_runtime_open_kwargs(), read_only=True
            ) as owner:
                if prepare_kind is not None:
                    require_coding_fenced_single_legacy_data(
                        lifecycle, owner, plugin_id=review_plugin_id, resource_kind=prepare_kind
                    )
                local_review = review_coding_legacy_installed_local_source(
                    lifecycle,
                    owner,
                    plugin_id=review_plugin_id,
                    policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
                )
            return write_package_operator_result(local_review.to_dict())

        for kind, _, _review, _admission, adopt_review in review_routes:
            accepted_review_id = getattr(args, f"adopt_legacy_{kind}_review")
            if accepted_review_id is None or (not windows and not accepted_review_id):
                continue
            if windows:
                # The Windows gate admits only builtin adoption.
                adopt_review = partial(adopt_coding_first_b_builtin_only, windows_candidate=True)
            receipt = adopt_review(
                lifecycle,
                open_coding_workspace_settings(workspace),
                workspace=workspace,
                accepted_review_id=accepted_review_id,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            )
            return write_package_operator_result(
                {
                    "disposition": "adopted",
                    "acceptanceId": receipt.acceptance_id,
                    "reviewId": receipt.review.review_id,
                },
            )
        if local_adopt is not None:
            resource_kind, selected_ids = local_adopt
            plugin_id, review_id = selected_ids
            adopted = adopt_coding_legacy_local_data_review(
                lifecycle,
                workspace=workspace,
                plugin_id=plugin_id,
                accepted_review_id=review_id,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                resource_kind=resource_kind,
            )
            return write_package_operator_result(
                {
                    "disposition": "adopted",
                    "pluginId": plugin_id,
                    "reviewId": review_id,
                    "acceptanceId": adopted.acceptance.acceptance_id,
                    "installOperationId": adopted.installation.operation_id,
                    "enableOperationId": (
                        None
                        if adopted.enablement is None
                        else adopted.enablement.enable_operation_id
                    ),
                },
            )
        namespace_id = _fresh_coding_product_namespace_id(epoch.store_id)
        has_fence = legacy_product_fence_exists(epoch.control_root)
        if not has_fence:
            require_fresh_coding_product_inputs_without_writes(
                lifecycle, workspace=workspace
            )
        settings = open_coding_workspace_settings(workspace)
        if has_fence:
            # Preserve the POSIX version lookup before opening the existing fence.
            if not windows:
                runtime_version = version("loushang")
            result = reopen_coding_package_cutover(
                lifecycle, expected_namespace=namespace_id
            )
        if has_fence and windows:
            if not inspect_fresh_product_epoch(
                epoch.fenced_runtime_open_kwargs(),
                windows=True,
                verify_snapshot=partial(is_coding_fresh_first_b_snapshot, lifecycle),
            ):
                raise RuntimeError("Coding Product fence is not a fresh cutover")
            if result.disposition != "fenced":
                raise RuntimeError("Coding Product fence was not committed")
            bootstrap_coding_builtin_product_plugins(
                lifecycle,
                settings,
                workspace=workspace,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                windows_candidate=True,
            )
        elif has_fence:
            replay_coding_posix_legacy_product_cutover(
                lifecycle,
                lambda: settings,
                roots=epoch.fenced_runtime_open_kwargs(),
                workspace=workspace,
                runtime_version=runtime_version,
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            )
        else:
            cutover = cutover_and_bootstrap_coding_package_product(
                lifecycle,
                settings,
                workspace=workspace,
                namespace_id=namespace_id,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                windows_candidate=windows,
            )
            result = cutover.attempt.result
        if result.disposition != "fenced":
            raise RuntimeError("Coding Product fence was not committed")
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        sys.stderr.write(f"Coding Package Product cutover refused: {error}\n")
        return 1
    return write_package_operator_result(
        {
            "disposition": "fenced",
            "namespaceId": namespace_id,
            "storeId": epoch.store_id,
        },
    )


def _prepare_review_cutover(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings: SettingsManager,
    epoch: CodingPackageEpochLayoutV1,
    namespace_id: str,
    *,
    snapshot_admission: CodingCutoverSnapshotAdmission | None = None,
    before_prepare: Callable[[], None] | None = None,
) -> None:
    """Prepare a missing review fence or verify its existing namespace.

    Admission remains the original cutover owner's Product callback. Existing
    fences do not run admission or a new preparation.
    """
    if not legacy_product_fence_exists(epoch.control_root):
        if before_prepare is not None:
            before_prepare()
        prepared = prepare_and_cutover_coding_package_store_from_legacy(
            lifecycle,
            settings,
            namespace_id=namespace_id,
            minimum_runtime_version=version("loushang"),
            minimum_runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            snapshot_admission=snapshot_admission,
        )
        if prepared.attempt.result.disposition != "fenced":
            raise RuntimeError("Coding Product fence was not committed")
    else:
        reopen_coding_package_cutover(lifecycle, expected_namespace=namespace_id)


def _require_disabled_only_preflight(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings: SettingsManager,
) -> None:
    """Avoid known incompatible inputs before the irreversible first fence."""

    prepare_coding_package_cutover_roots(lifecycle)
    with settings.transaction():
        patches = (
            settings.get_global_settings(),
            settings.get_project_settings(),
        )
        if not any(patch.get("disabled_plugins") for patch in patches):
            raise RuntimeError("Coding workspace has no legacy disabled Plugins")
        if any(
            patch.get(key)
            for patch in patches
            for key in (
                "plugin_sources",
                "package_roots",
                "package_sources",
                "packages",
            )
        ):
            raise RuntimeError("Coding configured Sources need a separate migration")
        if settings.get_session_settings():
            raise RuntimeError("Coding session settings cannot enter offline cutover")
    state = resolve_coding_lifecycle_pre_b_members(lifecycle)
    package = resolve_coding_package_pre_b_store_members(lifecycle)
    if any(state.domain_members().values()) or any(package.domain_members().values()):
        raise RuntimeError("Coding old Plugin state needs a separate migration")


if __name__ == "__main__":
    raise SystemExit(main())
