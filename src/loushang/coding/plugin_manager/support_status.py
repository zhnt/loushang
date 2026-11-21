"""One read-only Coding presentation of Plugin owner evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from loushang.coding.harness.plugin_management import support_evidence as _programs
from loushang.coding.plugin_manager.operation_guidance import (
    coding_desired_repair_command as coding_desired_repair_command,
)
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint as plugin_package_revision_fingerprint,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.plugin_management.records import (
    PluginPackageRevisionRefV1 as PluginPackageRevisionRefV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef as PluginInstanceRevisionRef,
)

_RUNTIME_PROGRAM_VALUES = {
    "value_001": "coding",
    "value_002": "Plugin support owner projection version is unsupported",
    "value_003": "Plugin support requires Coding's partial Product preview",
    "value_004": "Plugin support Desired State revision is invalid",
    "value_005": "Plugin support owner fields are invalid",
    "value_006": "Plugin support scope is invalid",
    "value_007": "Plugin support Catalog receipt is invalid",
    "value_008": "Plugin support Product disposition is invalid",
    "value_009": "Plugin support Catalog selection is invalid",
    "value_010": "Plugin support Catalog selection changed Product scope",
    "value_011": "Plugin support admission is invalid",
    "value_012": "Plugin support Installation is invalid",
    "value_013": "Plugin support Installation changed Product scope",
    "value_014": "Plugin support Management operations are invalid",
    "value_015": "Plugin support Management operation is invalid",
    "value_016": "Plugin support Instance revision is invalid",
    "value_017": "Plugin support Package revision is invalid",
}


def project_coding_plugin_support_status(
    management: dict[str, object],
    preview: dict[str, object],
    *,
    correlation_id: str,
) -> dict[str, object]:
    """Join existing owner reads without claiming a live Session consumer."""

    return _programs.project_support_evidence(
        management, preview, correlation_id=correlation_id
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="loushang-coding-plugin-status",
        description="Read partial Plugin support stages from the fenced Coding Product.",
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--composition-set", default="coding-standard")
    args = parser.parse_args(argv)
    from loushang.coding.plugin_manager.read_sdk import (
        open_coding_plugin_management_read_client,
    )

    try:
        document = open_coding_plugin_management_read_client(
            Path(args.workspace)
        ).support_status(
            correlation_id="coding:cli:plugin-status",
            composition_set_id=args.composition_set,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Error: {getattr(exc, 'code', 'plugin_support_unavailable')}\n")
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = ["main", "project_coding_plugin_support_status"]
