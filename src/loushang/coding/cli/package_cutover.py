"""Explicit offline first-B cutover and reviewed old-workspace adoption."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.package.cutover_backup import inspect_coding_package_cutover_backup
from loushang.coding.package.epoch_layout import (
    CodingPackageEpochLayoutV1,
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
    resolve_coding_package_pre_b_store_members,
)
from loushang.coding.package.legacy_builtin_acceptance import (
    read_coding_first_b_builtin_only_acceptance,
)
from loushang.coding.package.legacy_builtin_adoption import (
    adopt_coding_first_b_builtin_only,
)
from loushang.coding.package.legacy_builtin_review import (
    admit_coding_builtin_only_snapshot,
    review_coding_first_b_builtin_only,
)
from loushang.coding.package.legacy_disabled_acceptance import (
    read_coding_first_b_disabled_only_acceptance,
)
from loushang.coding.package.legacy_disabled_review import (
    review_coding_first_b_disabled_only,
)
from loushang.coding.package.legacy_installation_inventory import (
    read_coding_legacy_installation_inventory,
)
from loushang.coding.package.legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance,
)
from loushang.coding.package.legacy_local_adoption import (
    adopt_coding_legacy_local_data_review,
)
from loushang.coding.package.legacy_local_adoption_read import (
    coding_legacy_local_data_adoption_settled,
)
from loushang.coding.package.legacy_removed_acceptance import (
    read_coding_first_b_removed_local_acceptance,
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
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackagePosixEpochCutoverResultV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

_WINDOWS_CANDIDATE_ROUTE_ADMITTED = True


def main(argv: Sequence[str] | None = None) -> int:
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
    read_actions.add_argument(
        "--review-legacy-disabled-only",
        action="store_true",
        help="read the first-B snapshot's scoped disabled-only migration review",
    )
    read_actions.add_argument(
        "--review-legacy-builtin-only",
        action="store_true",
        help="read a fenced old builtin Desired State review",
    )
    read_actions.add_argument(
        "--review-legacy-removed-only",
        action="store_true",
        help="read a fenced old local Plugin removal review",
    )
    read_actions.add_argument(
        "--review-legacy-local-plugin",
        metavar="PLUGIN_ID",
        help="read one installed local Plugin review under an existing first-B fence",
    )
    read_actions.add_argument(
        "--prepare-legacy-disabled-review",
        action="store_true",
        help="commit the offline first-B fence and return a disabled-only review",
    )
    read_actions.add_argument(
        "--prepare-legacy-builtin-review",
        action="store_true",
        help="fence an eligible builtin-only old Desired State and return its review",
    )
    read_actions.add_argument(
        "--prepare-legacy-removed-review",
        action="store_true",
        help="fence an eligible old local removal set and return its review",
    )
    read_actions.add_argument(
        "--prepare-legacy-local-skill-review",
        metavar="PLUGIN_ID",
        help="fence eligible old local Skills and review one Plugin",
    )
    read_actions.add_argument(
        "--prepare-legacy-local-prompt-review",
        metavar="PLUGIN_ID",
        help="fence eligible old local Prompts and review one Plugin",
    )
    read_actions.add_argument(
        "--prepare-legacy-local-theme-review",
        metavar="PLUGIN_ID",
        help="fence eligible old local Themes and review one Plugin",
    )
    read_actions.add_argument(
        "--adopt-legacy-disabled-review",
        metavar="REVIEW_ID",
        help="accept exactly one reviewed snapshot and seed Product Desired State",
    )
    read_actions.add_argument(
        "--adopt-legacy-builtin-review",
        metavar="REVIEW_ID",
        help="accept one reviewed old builtin Desired State into Product",
    )
    read_actions.add_argument(
        "--adopt-legacy-removed-review",
        metavar="REVIEW_ID",
        help="accept one reviewed old local removal set into Product",
    )
    read_actions.add_argument(
        "--adopt-legacy-local-skill-review",
        nargs=2,
        metavar=("PLUGIN_ID", "REVIEW_ID"),
        help="accept a reviewed old local Skill and complete its Product adoption",
    )
    read_actions.add_argument(
        "--adopt-legacy-local-prompt-review",
        nargs=2,
        metavar=("PLUGIN_ID", "REVIEW_ID"),
        help="accept a reviewed old local Prompt and complete its Product adoption",
    )
    read_actions.add_argument(
        "--adopt-legacy-local-theme-review",
        nargs=2,
        metavar=("PLUGIN_ID", "REVIEW_ID"),
        help="accept a reviewed old local Theme and complete its Product adoption",
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
        if windows:
            if (
                not args.windows_candidate
                or not _WINDOWS_CANDIDATE_ROUTE_ADMITTED
                or any(
                    (
                        args.review_legacy_disabled_only,
                        args.review_legacy_removed_only,
                        args.review_legacy_local_plugin is not None,
                        args.prepare_legacy_disabled_review,
                        args.prepare_legacy_removed_review,
                        args.prepare_legacy_local_skill_review is not None,
                        args.prepare_legacy_local_prompt_review is not None,
                        args.prepare_legacy_local_theme_review is not None,
                        args.adopt_legacy_disabled_review is not None,
                        args.adopt_legacy_removed_review is not None,
                        args.adopt_legacy_local_skill_review is not None,
                        args.adopt_legacy_local_prompt_review is not None,
                        args.adopt_legacy_local_theme_review is not None,
                    )
                )
            ):
                raise RuntimeError(
                    "Windows Coding Product write CLI requires an admitted candidate"
                )
        elif args.windows_candidate:
            raise ValueError("Windows Product candidate requires Windows")
        review_routes = (
            (
                args.review_legacy_removed_only,
                args.prepare_legacy_removed_review,
                review_coding_first_b_removed_local,
                admit_coding_removed_local_snapshot,
            ),
            (
                args.review_legacy_builtin_only,
                args.prepare_legacy_builtin_review,
                review_coding_first_b_builtin_only,
                admit_coding_builtin_only_snapshot,
            ),
            (
                args.review_legacy_disabled_only,
                args.prepare_legacy_disabled_review,
                review_coding_first_b_disabled_only,
                None,
            ),
        )
        for read_review, prepare_review, project_review, admit_snapshot in review_routes:
            if not (read_review or prepare_review):
                continue
            settings = _cutover_settings(workspace)
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
            if windows:
                # The Windows gate admits only the builtin review route.
                with closing(open_native_fenced_product_epoch(
                    windows=True, **epoch.fenced_runtime_open_kwargs()
                )) as windows_owner:
                    document = review_coding_first_b_builtin_only(
                        lifecycle, windows_owner, settings_manager=settings
                    ).to_dict()
                return write_package_operator_result(document)
            with PackageProductPosixFencedRuntimeOwner.open(
                **epoch.fenced_runtime_open_kwargs(), read_only=True
            ) as owner:
                review = project_review(lifecycle, owner, settings_manager=settings)
            return write_package_operator_result(review.to_dict())

        review_plugin_id = args.review_legacy_local_plugin
        prepare_kind: Literal["skill", "prompt", "theme"] | None = None
        if args.prepare_legacy_local_theme_review:
            review_plugin_id = args.prepare_legacy_local_theme_review
            prepare_kind = "theme"
        elif args.prepare_legacy_local_prompt_review:
            review_plugin_id = args.prepare_legacy_local_prompt_review
            prepare_kind = "prompt"
        elif args.prepare_legacy_local_skill_review:
            review_plugin_id = args.prepare_legacy_local_skill_review
            prepare_kind = "skill"
        if review_plugin_id:
            if prepare_kind is not None:
                _prepare_review_cutover(
                    lifecycle,
                    _cutover_settings(workspace),
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

        adoption_routes = (
            (
                args.adopt_legacy_disabled_review,
                bootstrap_coding_accepted_disabled_only_product_plugins,
            ),
            (
                args.adopt_legacy_builtin_review,
                partial(adopt_coding_first_b_builtin_only, windows_candidate=True)
                if windows else adopt_coding_first_b_builtin_only,
            ),
            (args.adopt_legacy_removed_review, adopt_coding_first_b_removed_local),
        )
        for accepted_review_id, adopt_review in adoption_routes:
            if accepted_review_id is None or (not windows and not accepted_review_id):
                continue
            receipt = adopt_review(
                lifecycle,
                _cutover_settings(workspace),
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
        if (
            args.adopt_legacy_local_skill_review
            or args.adopt_legacy_local_prompt_review
            or args.adopt_legacy_local_theme_review
        ):
            plugin_id, review_id = (
                args.adopt_legacy_local_theme_review
                or args.adopt_legacy_local_prompt_review
                or args.adopt_legacy_local_skill_review
            )
            adopted = adopt_coding_legacy_local_data_review(
                lifecycle,
                workspace=workspace,
                plugin_id=plugin_id,
                accepted_review_id=review_id,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                resource_kind=(
                    "theme"
                    if args.adopt_legacy_local_theme_review
                    else "prompt"
                    if args.adopt_legacy_local_prompt_review
                    else "skill"
                ),
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
        settings = _cutover_settings(workspace)
        if has_fence and windows:
            result = reopen_coding_package_cutover(lifecycle)
            _require_cutover_namespace(result, namespace_id)
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
            runtime_version = version("loushang")
            result = reopen_coding_package_cutover(lifecycle)
            _require_cutover_namespace(result, namespace_id)
            read_owner = PackageProductPosixFencedRuntimeOwner.open(
                **epoch.fenced_runtime_open_kwargs(), read_only=True
            )
            try:
                legacy_inventory = read_coding_legacy_installation_inventory(
                    lifecycle, read_owner
                ).inventory
                local = legacy_inventory.active_local
                accepted_kinds = {
                    item.binding.plugin_id: accepted.resource_kind
                    for item in local
                    if (
                        accepted := reopen_coding_legacy_installed_local_acceptance(
                            lifecycle,
                            read_owner,
                            plugin_id=item.binding.plugin_id,
                            policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
                        )
                    )
                    is not None
                }
                acceptance = (
                    None
                    if local
                    else read_coding_first_b_disabled_only_acceptance(
                        lifecycle,
                        read_owner,
                        settings_manager=settings,
                    )
                )
                builtin_acceptance = (
                    None
                    if local
                    else read_coding_first_b_builtin_only_acceptance(
                        lifecycle,
                        read_owner,
                        settings_manager=settings,
                    )
                )
                removed_acceptance = read_coding_first_b_removed_local_acceptance(
                    lifecycle,
                    read_owner,
                    settings_manager=settings,
                )
            finally:
                read_owner.close()
            pending_removals = bool(legacy_inventory.unselected_source_identities)
            if pending_removals and removed_acceptance is None:
                raise RuntimeError(
                    "Coding old local removals need explicit adoption or retry"
                )
            if removed_acceptance is not None and (pending_removals or not local):
                adopt_coding_first_b_removed_local(
                    lifecycle,
                    settings,
                    workspace=workspace,
                    accepted_review_id=removed_acceptance.review.review_id,
                    runtime_version=runtime_version,
                    runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                )
            if local:
                if not all(
                    coding_legacy_local_data_adoption_settled(
                        lifecycle,
                        plugin_id=item.binding.plugin_id,
                        workspace=workspace,
                        resource_kind=accepted_kinds.get(
                            item.binding.plugin_id, "skill"
                        ),
                    )
                    for item in local
                ):
                    raise RuntimeError(
                        "Coding old local Skills need explicit adoption or retry"
                    )
            elif removed_acceptance is None:
                if builtin_acceptance is not None:
                    adopt_coding_first_b_builtin_only(
                        lifecycle,
                        settings,
                        workspace=workspace,
                        accepted_review_id=builtin_acceptance.review.review_id,
                        runtime_version=runtime_version,
                        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                    )
                elif acceptance is not None:
                    bootstrap_coding_accepted_disabled_only_product_plugins(
                        lifecycle,
                        settings,
                        workspace=workspace,
                        accepted_review_id=acceptance.review.review_id,
                        runtime_version=runtime_version,
                        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                    )
                else:
                    bootstrap_coding_builtin_product_plugins(
                        lifecycle,
                        settings,
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


def _cutover_settings(workspace: Path) -> SettingsManager:
    return SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(workspace),
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
        reopened = reopen_coding_package_cutover(lifecycle)
        _require_cutover_namespace(reopened, namespace_id)


def _require_cutover_namespace(
    result: PackagePosixEpochCutoverResultV1, namespace_id: str
) -> None:
    if (
        result.switch_receipt is None
        or result.switch_receipt.namespace_id != namespace_id
    ):
        raise RuntimeError("Coding Product fence belongs to another cutover")


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
