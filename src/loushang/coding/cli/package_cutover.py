"""Explicit offline first-B cutover for a fresh Coding workspace."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
    reopen_coding_package_cutover,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    bootstrap_coding_builtin_product_plugins,
)
from loushang.harness.config.agent import SettingsManager


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-package-cutover")
    parser.add_argument("--workspace", default=".", help="existing Coding workspace")
    args = parser.parse_args(argv)
    try:
        workspace = Path(args.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Coding workspace must be a directory")
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
        epoch = resolve_coding_package_epoch_layout(lifecycle)
        namespace_id = sha256(
            b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
        ).hexdigest()
        settings = SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(workspace),
        )
        runtime_version = version("loushang")
        try:
            (epoch.control_root / "epoch.jsonl").lstat()
        except FileNotFoundError:
            has_fence = False
        else:
            has_fence = True
        if has_fence:
            result = reopen_coding_package_cutover(lifecycle)
            if (
                result.switch_receipt is None
                or result.switch_receipt.namespace_id != namespace_id
            ):
                raise RuntimeError("Coding Product fence belongs to another cutover")
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


if __name__ == "__main__":
    raise SystemExit(main())
