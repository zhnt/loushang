"""CLI arguments and lifecycle commands for explicitly selected Worker Wheels."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable, Mapping
from typing import Literal, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_worker_candidate import (
    _capture_worker_candidate_installations,
    _change_worker_candidate_lifecycle,
    _install_worker_candidate,
    _update_worker_candidate,
    _worker_candidate_revision_matches,
)

_CHANGE_ACTIONS = (
    "candidate-install",
    "candidate-update",
    "candidate-enable",
    "candidate-disable",
    "candidate-remove",
)
WORKER_CANDIDATE_CHANGE_ACTIONS = frozenset(_CHANGE_ACTIONS)


def add_worker_candidate_commands(
    actions: _SubParsersAction[ArgumentParser],
    *,
    help_text: Mapping[str, str],
    native_platform_option: str | None = None,
) -> None:
    capture = actions.add_parser(
        "candidate-capture", help=help_text["candidate-capture"]
    )
    capture.add_argument("--wheel", required=True)
    capture.add_argument("--contribution-id", required=True)
    capture.add_argument("--owner-id", required=True)
    if native_platform_option is not None:
        capture.add_argument(
            "--native-platform", choices=(native_platform_option,), required=True
        )
    for action in _CHANGE_ACTIONS:
        command = actions.add_parser(action, help=help_text[action])
        command.add_argument("--plugin-id", required=True)
        if action == "candidate-update":
            command.add_argument("--from-artifact-digest", required=True)
        command.add_argument("--artifact-digest", required=True)
        command.add_argument("--operation-id", required=True)
        if action != "candidate-install":
            command.add_argument(
                "--expected-inventory-revision", type=int, required=True
            )


def execute_worker_candidate_change(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    args: Namespace,
    *,
    product_id: str,
    native_platform: Literal["linux-x86_64", "windows-amd64"],
    label: str,
    require_revoked: Callable[[], None],
    error_type: Callable[[str, str], Exception],
    stale_update_code: str,
) -> dict[str, object]:
    """Run the existing lifecycle with the platform's operator contract."""
    windows = native_platform == "windows-amd64"
    if args.action not in WORKER_CANDIDATE_CHANGE_ACTIONS:
        raise ValueError(f"{label} candidate action is unsupported")
    binding, snapshot, installed = _capture_worker_candidate_installations(
        product,
        args.plugin_id,
        args.artifact_digest,
        product_id=product_id,
        label=label,
    )
    if (
        windows
        and args.action in {"candidate-update", "candidate-disable", "candidate-remove"}
        and len(installed) != 1
    ):
        raise ValueError(f"{label} candidate installation changed")
    if len(installed) > 1:
        raise ValueError(f"{label} candidate installation is ambiguous")
    selected = installed[0] if installed else None
    revision = None if selected is None else selected.selection.package_revision
    document: dict[str, object] = (
        {}
        if windows
        else {"productSelection": "not_checked", "productUse": "not_checked"}
    )
    if args.action == "candidate-install":
        lifecycle, inventory_revision, already_installed = _install_worker_candidate(
            product,
            binding,
            snapshot,
            selected,
            product_id=product_id,
            plugin_id=args.plugin_id,
            operation_id=args.operation_id,
            label=label,
            reinstall_removed=not windows,
            refresh_inventory=windows,
        )
        install_result = {
            "pluginId": args.plugin_id,
            "artifactDigest": args.artifact_digest,
            "inventoryRevision": inventory_revision,
            "alreadyInstalled": already_installed,
        }
        if not windows:
            install_result["lifecycle"] = lifecycle
            document["productAdmission"] = "installed"
        return {"candidateInstall": install_result, **document}
    if args.action == "candidate-update":
        lifecycle, inventory_revision, already_updated = _update_worker_candidate(
            product,
            binding,
            snapshot,
            selected,
            args,
            product_id=product_id,
            label=label,
            require_revoked=require_revoked,
            error_type=error_type,
            error_code=stale_update_code,
            post_selection_error_type=None if windows else error_type,
        )
        update_result = {
            "pluginId": args.plugin_id,
            "fromArtifactDigest": args.from_artifact_digest,
            "artifactDigest": args.artifact_digest,
            "inventoryRevision": inventory_revision,
            "alreadyUpdated": already_updated,
        }
        if not windows:
            update_result["lifecycle"] = lifecycle
            document["productAdmission"] = "installed"
        return {"candidateUpdate": update_result, **document}

    action = cast(
        Literal["enable", "disable", "remove"], args.action.removeprefix("candidate-")
    )
    if windows and action == "enable" and revision is None:
        raise ValueError(f"{label} candidate is not installed")
    if windows and action == "remove":
        require_revoked()
    if revision is not None and not _worker_candidate_revision_matches(
        revision, binding
    ):
        changed = "selection" if windows and action == "enable" else "installation"
        raise ValueError(f"{label} candidate {changed} changed")
    if not windows and action == "remove":
        require_revoked()
    if selected is None:
        raise ValueError(f"{label} candidate installation changed")
    operation, inventory_revision = _change_worker_candidate_lifecycle(
        product,
        binding,
        snapshot,
        selected,
        action=action,
        operation_id=args.operation_id,
        expected_inventory_revision=args.expected_inventory_revision,
        label=label,
        unsettled_message=(
            f"{label} candidate change did not settle"
            if windows and action != "enable"
            else f"{label} candidate enable did not settle"
        ),
    )
    if action == "remove":
        document["packageRetirement"] = "not_checked"
    return {
        "candidateManagementOperation": operation,
        "inventoryRevision": inventory_revision,
        **document,
    }
