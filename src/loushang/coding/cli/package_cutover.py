"""Explicit offline first-B cutover and reviewed old-workspace adoption."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.package_cutover_backup import (
    inspect_coding_package_cutover_backup,
)
from loushang.coding.package_epoch_layout import (
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
    resolve_coding_package_pre_b_store_members,
)
from loushang.coding.package_legacy_builtin_acceptance import (
    read_coding_first_b_builtin_only_acceptance,
)
from loushang.coding.package_legacy_builtin_adoption import (
    adopt_coding_first_b_builtin_only,
)
from loushang.coding.package_legacy_builtin_review import (
    admit_coding_builtin_only_snapshot,
    review_coding_first_b_builtin_only,
)
from loushang.coding.package_legacy_disabled_acceptance import (
    read_coding_first_b_disabled_only_acceptance,
)
from loushang.coding.package_legacy_disabled_review import (
    review_coding_first_b_disabled_only,
)
from loushang.coding.package_legacy_installation_inventory import (
    read_coding_legacy_installation_inventory,
)
from loushang.coding.package_legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance,
)
from loushang.coding.package_legacy_local_adoption import (
    adopt_coding_legacy_local_data_review,
)
from loushang.coding.package_legacy_local_adoption_read import (
    coding_legacy_local_data_adoption_settled,
)
from loushang.coding.package_legacy_removed_acceptance import (
    read_coding_first_b_removed_local_acceptance,
)
from loushang.coding.package_legacy_removed_adoption import (
    adopt_coding_first_b_removed_local,
)
from loushang.coding.package_legacy_removed_review import (
    admit_coding_removed_local_snapshot,
    review_coding_first_b_removed_local,
)
from loushang.coding.package_legacy_review import (
    review_coding_legacy_installed_local_source,
)
from loushang.coding.package_legacy_skill_cutover_admission import (
    admit_coding_single_legacy_skill_snapshot,
    require_coding_fenced_single_legacy_data,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
    reopen_coding_package_cutover,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION,
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    bootstrap_coding_accepted_disabled_only_product_plugins,
    bootstrap_coding_builtin_product_plugins,
    is_coding_fresh_first_b_snapshot,
    require_fresh_coding_product_inputs_without_writes,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
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
        workspace = Path(args.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Coding workspace must be a directory")
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
        epoch = resolve_coding_package_epoch_layout(lifecycle)
        if args.backup_status:
            document = inspect_coding_package_cutover_backup(lifecycle).to_dict()
            sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")
            return 0
        if os.name == "nt":
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
            if (
                args.review_legacy_builtin_only
                or args.prepare_legacy_builtin_review
                or args.adopt_legacy_builtin_review is not None
            ):
                document = _run_windows_builtin_candidate(
                    lifecycle,
                    workspace=workspace,
                    prepare_review=args.prepare_legacy_builtin_review,
                    accepted_review_id=args.adopt_legacy_builtin_review,
                )
            else:
                document = _run_windows_fresh_candidate(lifecycle, workspace=workspace)
            sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")
            return 0
        if args.windows_candidate:
            raise ValueError("Windows Product candidate requires Windows")
        if args.review_legacy_removed_only or args.prepare_legacy_removed_review:
            settings = SettingsManager(
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
            namespace_id = sha256(
                b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
            ).hexdigest()
            if args.prepare_legacy_removed_review:
                try:
                    (epoch.control_root / "epoch.jsonl").lstat()
                except FileNotFoundError:
                    prepared = prepare_and_cutover_coding_package_store_from_legacy(
                        lifecycle,
                        settings,
                        namespace_id=namespace_id,
                        minimum_runtime_version=version("loushang"),
                        minimum_runtime_protocol_epoch=(
                            CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH
                        ),
                        snapshot_admission=lambda preparation, snapshot: (
                            admit_coding_removed_local_snapshot(
                                lifecycle, preparation, snapshot
                            )
                        ),
                    )
                    if prepared.attempt.result.disposition != "fenced":
                        raise RuntimeError("Coding Product fence was not committed")
                else:
                    reopened = reopen_coding_package_cutover(lifecycle)
                    if (
                        reopened.switch_receipt is None
                        or reopened.switch_receipt.namespace_id != namespace_id
                    ):
                        raise RuntimeError(
                            "Coding Product fence belongs to another cutover"
                        )
            owner = PackageProductPosixFencedRuntimeOwner.open(
                authority_root=epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                epochs_root_name=epoch.epochs_root_name,
                read_only=True,
            )
            try:
                removed_review = review_coding_first_b_removed_local(
                    lifecycle, owner, settings_manager=settings
                )
            finally:
                owner.close()
            sys.stdout.write(
                json.dumps(removed_review.to_dict(), sort_keys=True) + "\n"
            )
            return 0
        if args.review_legacy_builtin_only or args.prepare_legacy_builtin_review:
            settings = SettingsManager(
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
            namespace_id = sha256(
                b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
            ).hexdigest()
            if args.prepare_legacy_builtin_review:
                try:
                    (epoch.control_root / "epoch.jsonl").lstat()
                except FileNotFoundError:
                    prepared = prepare_and_cutover_coding_package_store_from_legacy(
                        lifecycle,
                        settings,
                        namespace_id=namespace_id,
                        minimum_runtime_version=version("loushang"),
                        minimum_runtime_protocol_epoch=(
                            CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH
                        ),
                        snapshot_admission=lambda preparation, snapshot: (
                            admit_coding_builtin_only_snapshot(
                                lifecycle, preparation, snapshot
                            )
                        ),
                    )
                    if prepared.attempt.result.disposition != "fenced":
                        raise RuntimeError("Coding Product fence was not committed")
                else:
                    reopened = reopen_coding_package_cutover(lifecycle)
                    if (
                        reopened.switch_receipt is None
                        or reopened.switch_receipt.namespace_id != namespace_id
                    ):
                        raise RuntimeError(
                            "Coding Product fence belongs to another cutover"
                        )
            owner = PackageProductPosixFencedRuntimeOwner.open(
                authority_root=epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                epochs_root_name=epoch.epochs_root_name,
                read_only=True,
            )
            try:
                builtin_review = review_coding_first_b_builtin_only(
                    lifecycle, owner, settings_manager=settings
                )
            finally:
                owner.close()
            sys.stdout.write(
                json.dumps(builtin_review.to_dict(), sort_keys=True) + "\n"
            )
            return 0
        if args.review_legacy_local_plugin:
            owner = PackageProductPosixFencedRuntimeOwner.open(
                authority_root=epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                epochs_root_name=epoch.epochs_root_name,
                read_only=True,
            )
            try:
                local_review = review_coding_legacy_installed_local_source(
                    lifecycle,
                    owner,
                    plugin_id=args.review_legacy_local_plugin,
                    policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
                )
            finally:
                owner.close()
            sys.stdout.write(json.dumps(local_review.to_dict(), sort_keys=True) + "\n")
            return 0
        if (
            args.prepare_legacy_local_skill_review
            or args.prepare_legacy_local_prompt_review
            or args.prepare_legacy_local_theme_review
        ):
            resource_kind: Literal["skill", "prompt", "theme"] = (
                "theme"
                if args.prepare_legacy_local_theme_review
                else "prompt"
                if args.prepare_legacy_local_prompt_review
                else "skill"
            )
            plugin_id = (
                args.prepare_legacy_local_theme_review
                or args.prepare_legacy_local_prompt_review
                or args.prepare_legacy_local_skill_review
            )
            settings = SettingsManager(
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
            namespace_id = sha256(
                b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
            ).hexdigest()
            try:
                (epoch.control_root / "epoch.jsonl").lstat()
            except FileNotFoundError:
                prepared = prepare_and_cutover_coding_package_store_from_legacy(
                    lifecycle,
                    settings,
                    namespace_id=namespace_id,
                    minimum_runtime_version=version("loushang"),
                    minimum_runtime_protocol_epoch=(
                        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH
                    ),
                    snapshot_admission=lambda preparation, snapshot: (
                        admit_coding_single_legacy_skill_snapshot(
                            lifecycle,
                            preparation,
                            snapshot,
                            plugin_id=plugin_id,
                            resource_kind=resource_kind,
                        )
                    ),
                )
                if prepared.attempt.result.disposition != "fenced":
                    raise RuntimeError("Coding Product fence was not committed")
            else:
                reopened = reopen_coding_package_cutover(lifecycle)
                if (
                    reopened.switch_receipt is None
                    or reopened.switch_receipt.namespace_id != namespace_id
                ):
                    raise RuntimeError(
                        "Coding Product fence belongs to another cutover"
                    )
            owner = PackageProductPosixFencedRuntimeOwner.open(
                authority_root=epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                epochs_root_name=epoch.epochs_root_name,
                read_only=True,
            )
            try:
                require_coding_fenced_single_legacy_data(
                    lifecycle,
                    owner,
                    plugin_id=plugin_id,
                    resource_kind=resource_kind,
                )
                local_skill_review = review_coding_legacy_installed_local_source(
                    lifecycle,
                    owner,
                    plugin_id=plugin_id,
                    policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
                )
            finally:
                owner.close()
            sys.stdout.write(
                json.dumps(local_skill_review.to_dict(), sort_keys=True) + "\n"
            )
            return 0
        if args.review_legacy_disabled_only or args.prepare_legacy_disabled_review:
            settings = SettingsManager(
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
            if args.prepare_legacy_disabled_review:
                namespace_id = sha256(
                    b"loushang.coding-fresh-product-epoch/v1\0"
                    + epoch.store_id.encode()
                ).hexdigest()
                try:
                    (epoch.control_root / "epoch.jsonl").lstat()
                except FileNotFoundError:
                    _require_disabled_only_preflight(lifecycle, settings)
                    prepared = prepare_and_cutover_coding_package_store_from_legacy(
                        lifecycle,
                        settings,
                        namespace_id=namespace_id,
                        minimum_runtime_version=version("loushang"),
                        minimum_runtime_protocol_epoch=(
                            CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH
                        ),
                    )
                    if prepared.attempt.result.disposition != "fenced":
                        raise RuntimeError("Coding Product fence was not committed")
                else:
                    reopened = reopen_coding_package_cutover(lifecycle)
                    if (
                        reopened.switch_receipt is None
                        or reopened.switch_receipt.namespace_id != namespace_id
                    ):
                        raise RuntimeError(
                            "Coding Product fence belongs to another cutover"
                        )
            owner = PackageProductPosixFencedRuntimeOwner.open(
                authority_root=epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                epochs_root_name=epoch.epochs_root_name,
                read_only=True,
            )
            try:
                review = review_coding_first_b_disabled_only(
                    lifecycle, owner, settings_manager=settings
                )
            finally:
                owner.close()
            sys.stdout.write(json.dumps(review.to_dict(), sort_keys=True) + "\n")
            return 0
        if args.adopt_legacy_disabled_review:
            settings = SettingsManager(
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
            receipt = bootstrap_coding_accepted_disabled_only_product_plugins(
                lifecycle,
                settings,
                workspace=workspace,
                accepted_review_id=args.adopt_legacy_disabled_review,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            )
            sys.stdout.write(
                json.dumps(
                    {
                        "disposition": "adopted",
                        "acceptanceId": receipt.acceptance_id,
                        "reviewId": receipt.review.review_id,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            return 0
        if args.adopt_legacy_builtin_review:
            settings = SettingsManager(
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
            builtin_receipt = adopt_coding_first_b_builtin_only(
                lifecycle,
                settings,
                workspace=workspace,
                accepted_review_id=args.adopt_legacy_builtin_review,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            )
            sys.stdout.write(
                json.dumps(
                    {
                        "disposition": "adopted",
                        "acceptanceId": builtin_receipt.acceptance_id,
                        "reviewId": builtin_receipt.review.review_id,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            return 0
        if args.adopt_legacy_removed_review:
            settings = SettingsManager(
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
            removed_receipt = adopt_coding_first_b_removed_local(
                lifecycle,
                settings,
                workspace=workspace,
                accepted_review_id=args.adopt_legacy_removed_review,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            )
            sys.stdout.write(
                json.dumps(
                    {
                        "disposition": "adopted",
                        "acceptanceId": removed_receipt.acceptance_id,
                        "reviewId": removed_receipt.review.review_id,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            return 0
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
            sys.stdout.write(
                json.dumps(
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
                    sort_keys=True,
                )
                + "\n"
            )
            return 0
        namespace_id = sha256(
            b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
        ).hexdigest()
        try:
            (epoch.control_root / "epoch.jsonl").lstat()
        except FileNotFoundError:
            has_fence = False
        else:
            has_fence = True
        if not has_fence:
            require_fresh_coding_product_inputs_without_writes(
                lifecycle, workspace=workspace
            )
        settings = SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(workspace),
        )
        runtime_version = version("loushang")
        if has_fence:
            result = reopen_coding_package_cutover(lifecycle)
            if (
                result.switch_receipt is None
                or result.switch_receipt.namespace_id != namespace_id
            ):
                raise RuntimeError("Coding Product fence belongs to another cutover")
            read_owner = PackageProductPosixFencedRuntimeOwner.open(
                authority_root=epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                epochs_root_name=epoch.epochs_root_name,
                read_only=True,
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
            if local:
                if legacy_inventory.unselected_source_identities:
                    if removed_acceptance is None:
                        raise RuntimeError(
                            "Coding old local removals need explicit adoption or retry"
                        )
                    adopt_coding_first_b_removed_local(
                        lifecycle,
                        settings,
                        workspace=workspace,
                        accepted_review_id=removed_acceptance.review.review_id,
                        runtime_version=runtime_version,
                        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                    )
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
            elif removed_acceptance is not None:
                adopt_coding_first_b_removed_local(
                    lifecycle,
                    settings,
                    workspace=workspace,
                    accepted_review_id=removed_acceptance.review.review_id,
                    runtime_version=runtime_version,
                    runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                )
            elif legacy_inventory.unselected_source_identities:
                raise RuntimeError(
                    "Coding old local removals need explicit adoption or retry"
                )
            elif builtin_acceptance is not None:
                adopt_coding_first_b_builtin_only(
                    lifecycle,
                    settings,
                    workspace=workspace,
                    accepted_review_id=builtin_acceptance.review.review_id,
                    runtime_version=runtime_version,
                    runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                )
            elif acceptance is None:
                bootstrap_coding_builtin_product_plugins(
                    lifecycle,
                    settings,
                    workspace=workspace,
                    runtime_version=runtime_version,
                    runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                )
            else:
                bootstrap_coding_accepted_disabled_only_product_plugins(
                    lifecycle,
                    settings,
                    workspace=workspace,
                    accepted_review_id=acceptance.review.review_id,
                    runtime_version=runtime_version,
                    runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                )
        else:
            cutover = cutover_and_bootstrap_coding_package_product(
                lifecycle,
                settings,
                workspace=workspace,
                namespace_id=namespace_id,
                runtime_version=runtime_version,
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            )
            result = cutover.attempt.result
        if result.disposition != "fenced":
            raise RuntimeError("Coding Product fence was not committed")
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        sys.stderr.write(f"Coding Package Product cutover refused: {error}\n")
        return 1
    sys.stdout.write(
        json.dumps(
            {
                "disposition": "fenced",
                "namespaceId": namespace_id,
                "storeId": epoch.store_id,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


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


def _run_windows_builtin_candidate(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    prepare_review: bool,
    accepted_review_id: str | None,
) -> dict[str, object]:
    """Exercise the reviewed builtin-only Windows migration behind its gate."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    settings = SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(workspace),
    )
    if accepted_review_id is not None:
        receipt = adopt_coding_first_b_builtin_only(
            lifecycle,
            settings,
            workspace=workspace,
            accepted_review_id=accepted_review_id,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            windows_candidate=True,
        )
        return {
            "disposition": "adopted",
            "acceptanceId": receipt.acceptance_id,
            "reviewId": receipt.review.review_id,
        }
    if prepare_review:
        namespace_id = sha256(
            b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
        ).hexdigest()
        try:
            (epoch.control_root / "epoch.jsonl").lstat()
        except FileNotFoundError:
            prepared = prepare_and_cutover_coding_package_store_from_legacy(
                lifecycle,
                settings,
                namespace_id=namespace_id,
                minimum_runtime_version=version("loushang"),
                minimum_runtime_protocol_epoch=(
                    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH
                ),
                snapshot_admission=lambda preparation, snapshot: (
                    admit_coding_builtin_only_snapshot(lifecycle, preparation, snapshot)
                ),
            )
            if prepared.attempt.result.disposition != "fenced":
                raise RuntimeError("Coding Product fence was not committed")
        else:
            reopened = reopen_coding_package_cutover(lifecycle)
            if (
                reopened.switch_receipt is None
                or reopened.switch_receipt.namespace_id != namespace_id
            ):
                raise RuntimeError("Coding Product fence belongs to another cutover")
    owner = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        review = review_coding_first_b_builtin_only(
            lifecycle, owner, settings_manager=settings
        )
        return review.to_dict()
    finally:
        owner.close()


def _run_windows_fresh_candidate(
    lifecycle: CodingPluginLifecycleStateLayout, *, workspace: Path
) -> dict[str, object]:
    """Retry the exact fresh first-B Product route under explicit selection."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    namespace_id = sha256(
        b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
    ).hexdigest()
    try:
        (epoch.control_root / "epoch.jsonl").lstat()
    except FileNotFoundError:
        bootstrap_complete = True
        require_fresh_coding_product_inputs_without_writes(
            lifecycle, workspace=workspace
        )
        settings = SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(workspace),
        )
        prepared = cutover_and_bootstrap_coding_package_product(
            lifecycle,
            settings,
            workspace=workspace,
            namespace_id=namespace_id,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            windows_candidate=True,
        )
        result = prepared.attempt.result
    else:
        bootstrap_complete = False
        settings = SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(workspace),
        )
        result = reopen_coding_package_cutover(lifecycle)
        if (
            result.switch_receipt is None
            or result.switch_receipt.namespace_id != namespace_id
        ):
            raise RuntimeError("Coding Product fence belongs to another cutover")
        first_b = PackageProductWindowsFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
        )
        try:
            if not is_coding_fresh_first_b_snapshot(lifecycle, first_b):
                raise RuntimeError("Coding Product fence is not a fresh cutover")
        finally:
            first_b.close()
    if result.disposition != "fenced":
        raise RuntimeError("Coding Product fence was not committed")
    if not bootstrap_complete:
        bootstrap_coding_builtin_product_plugins(
            lifecycle,
            settings,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            windows_candidate=True,
        )
    return {
        "disposition": "fenced",
        "namespaceId": namespace_id,
        "storeId": epoch.store_id,
    }


if __name__ == "__main__":
    raise SystemExit(main())
