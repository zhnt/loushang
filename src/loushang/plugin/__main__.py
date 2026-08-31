"""Developer CLI for inert Plugin validation and explicit execution conformance."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from loushang.plugin._conformance import (
    PluginExecutionConformanceError,
    run_execution_conformance,
)
from loushang.plugin._validation import validate_package


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-plugin")
    commands = parser.add_subparsers(dest="command", required=True)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("path")
    conformance_parser = commands.add_parser("conformance")
    conformance_parser.add_argument("path")
    conformance_parser.add_argument("--approve-execution", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "validate":
        result = validate_package(args.path)
        print(
            json.dumps(
                {
                    "diagnostics": [
                        {
                            "code": item.code,
                            "contributionId": item.contribution_id,
                            "message": item.message,
                            "owner": item.owner,
                            "path": item.path,
                        }
                        for item in result.diagnostics
                    ],
                    "manifestPath": result.manifest_path,
                    "pluginId": result.plugin_id,
                    "valid": result.valid,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result.valid else 1
    try:
        conformance_result = run_execution_conformance(
            args.path,
            execution_approved=args.approve_execution,
        )
    except PluginExecutionConformanceError as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "executedSources": conformance_result.executed_sources,
                "pluginId": conformance_result.plugin_id,
                "resolvedEntrypoints": conformance_result.resolved_entrypoints,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
