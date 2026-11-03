"""Developer CLI for inert Plugin validation and explicit execution conformance."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.plugin._coding_data_scaffold import create_coding_data_scaffold
from loushang.plugin._coding_data_skill_wheel import (
    write_coding_data_prompt_wheel,
    write_coding_data_skill_wheel,
    write_coding_data_theme_wheel,
)
from loushang.plugin._coding_data_wheel_validation import validate_coding_data_wheel
from loushang.plugin._coding_local_worker_wheel import (
    write_coding_local_worker_candidate_wheel,
)
from loushang.plugin._conformance import (
    PluginExecutionConformanceError,
    run_execution_conformance,
)
from loushang.plugin._validation import validate_package


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="loushang-plugin",
        description=(
            "Build or validate inert Plugin artifacts, or explicitly run execution "
            "conformance. Product admission and Session use require separate checks."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate_parser = commands.add_parser(
        "validate", help="validate a Plugin package without Product admission"
    )
    validate_parser.add_argument("path")
    wheel_validate_parser = commands.add_parser(
        "validate-coding-wheel",
        help="inertly validate one Coding Skill or Prompt Wheel without Product admission",
    )
    wheel_validate_parser.add_argument("path")
    conformance_parser = commands.add_parser(
        "conformance", help="run explicitly approved execution conformance"
    )
    conformance_parser.add_argument("path")
    conformance_parser.add_argument("--approve-execution", action="store_true")
    for kind in ("skill", "prompt", "theme"):
        init_parser = commands.add_parser(
            f"init-coding-{kind}",
            help=f"create one editable Coding data {kind.title()} source tree",
        )
        init_parser.add_argument("destination")
        init_parser.add_argument("--plugin-id", help="defaults to destination name")
        init_parser.add_argument("--resource-name", help="defaults to Plugin ID")
        init_parser.add_argument("--version", default="1")
    build_parser = commands.add_parser(
        "build-coding-skill",
        help="build one Coding data Skill wheel",
        description="Build one data Skill wheel; Product install and Session use are separate checks.",
    )
    build_parser.add_argument(
        "skill_file", help="Markdown SKILL.md; name defaults to its parent directory"
    )
    build_parser.add_argument(
        "--plugin-id",
        required=True,
        help="lowercase letters and digits, starting with a letter",
    )
    build_parser.add_argument(
        "--version", required=True, help="numeric version: 1, 1.2, or 1.2.3"
    )
    build_parser.add_argument(
        "--skill-name", help="kebab-case Resource name; defaults to parent directory"
    )
    build_parser.add_argument(
        "--contribution-id", help="defaults to <skill-name>-skill"
    )
    build_parser.add_argument(
        "--output-dir", default="dist", help="wheel directory (default: dist)"
    )
    prompt_parser = commands.add_parser(
        "build-coding-prompt",
        help="build one Coding data Prompt wheel",
        description="Build one data Prompt wheel; Product install and Session use are separate checks.",
    )
    prompt_parser.add_argument(
        "prompt_file", help="Markdown .md file; name defaults to filename stem"
    )
    prompt_parser.add_argument(
        "--plugin-id",
        required=True,
        help="lowercase letters and digits, starting with a letter",
    )
    prompt_parser.add_argument(
        "--version", required=True, help="numeric version: 1, 1.2, or 1.2.3"
    )
    prompt_parser.add_argument(
        "--prompt-name", help="kebab-case Resource name; defaults to filename stem"
    )
    prompt_parser.add_argument(
        "--contribution-id", help="defaults to <prompt-name>-prompt"
    )
    prompt_parser.add_argument(
        "--output-dir", default="dist", help="wheel directory (default: dist)"
    )
    theme_parser = commands.add_parser(
        "build-coding-theme",
        help="build one Coding Screen Theme candidate wheel; Product rollout remains gated",
        description="Build one Coding Screen Theme candidate wheel; Product rollout remains gated.",
    )
    theme_parser.add_argument(
        "theme_file", help="bounded Theme JSON file; name defaults to filename stem"
    )
    theme_parser.add_argument(
        "--plugin-id",
        required=True,
        help="lowercase letters and digits, starting with a letter",
    )
    theme_parser.add_argument(
        "--version", required=True, help="numeric version: 1, 1.2, or 1.2.3"
    )
    theme_parser.add_argument(
        "--theme-name", help="kebab-case Resource name; defaults to filename stem"
    )
    theme_parser.add_argument(
        "--contribution-id", help="defaults to <theme-name>-theme"
    )
    theme_parser.add_argument(
        "--output-dir", default="dist", help="wheel directory (default: dist)"
    )
    worker_parser = commands.add_parser(
        "build-coding-worker-candidate",
        help="package a default-dark native Worker candidate without activating it",
        description="Package a native Worker candidate; Product admission and activation remain gated.",
    )
    worker_parser.add_argument("executable_file")
    worker_parser.add_argument("--plugin-id", required=True)
    worker_parser.add_argument("--version", required=True)
    worker_parser.add_argument("--contribution-id", required=True)
    worker_parser.add_argument("--owner-id", required=True)
    worker_parser.add_argument(
        "--native-platform", choices=("linux-x86_64", "windows-amd64"), required=True
    )
    worker_parser.add_argument("--wheel-tag")
    worker_parser.add_argument(
        "--dependency",
        action="append",
        default=[],
        help="exact project==version candidate dependency (up to three)",
    )
    worker_parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args(argv)
    if args.command in {"init-coding-skill", "init-coding-prompt", "init-coding-theme"}:
        scaffold_kind: Literal["skill", "prompt", "theme"] = args.command.removeprefix(
            "init-coding-"
        )
        try:
            scaffold = create_coding_data_scaffold(
                args.destination,
                kind=scaffold_kind,
                plugin_id=args.plugin_id,
                resource_name=args.resource_name,
                version=args.version,
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        report: dict[str, object] = {
            "buildCommand": list(scaffold.build_command),
            "disposableSmoke": "not_checked",
            "smokeCommand": list(scaffold.smoke_command),
            "profile": f"coding-data-{scaffold_kind}-v1",
            "productAdmission": "not_checked",
            "productSelection": "not_checked",
            "productUse": "not_checked",
            "sourcePath": str(scaffold.source_path),
            "validationResult": "not_checked",
        }
        if scaffold_kind in {"skill", "prompt"}:
            report["validationCommand"] = [
                "loushang-plugin",
                "validate-coding-wheel",
                scaffold.smoke_command[1],
            ]
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
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
                    "productAdmission": "not_checked",
                    "productSelection": "not_checked",
                    "productUse": "not_checked",
                    "valid": result.valid,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result.valid else 1
    if args.command == "validate-coding-wheel":
        validation_report = validate_coding_data_wheel(args.path)
        print(json.dumps(validation_report, ensure_ascii=False, sort_keys=True))
        return 0 if validation_report["valid"] else 1
    if args.command in {
        "build-coding-skill",
        "build-coding-prompt",
        "build-coding-theme",
    }:
        is_skill = args.command == "build-coding-skill"
        is_prompt = args.command == "build-coding-prompt"
        source = Path(
            args.skill_file
            if is_skill
            else args.prompt_file
            if is_prompt
            else args.theme_file
        )
        kind = "Skill" if is_skill else "Prompt" if is_prompt else "Theme"
        try:
            source_stat = source.lstat()
            if (
                not stat.S_ISREG(source_stat.st_mode)
                or source_stat.st_size > 1024 * 1024
            ):
                raise ValueError(f"{kind} source must be a regular file within 1 MiB")
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            with os.fdopen(os.open(source, flags), "rb") as input_file:
                opened_stat = os.fstat(input_file.fileno())
                if not stat.S_ISREG(opened_stat.st_mode) or (
                    opened_stat.st_dev,
                    opened_stat.st_ino,
                ) != (source_stat.st_dev, source_stat.st_ino):
                    raise ValueError(f"{kind} source must remain a regular file")
                body = input_file.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError(f"{kind} source exceeds 1 MiB")
            if is_skill:
                skill_name = args.skill_name or source.parent.name
                wheel_path = write_coding_data_skill_wheel(
                    args.output_dir,
                    plugin_id=args.plugin_id,
                    version=args.version,
                    contribution_id=args.contribution_id or f"{skill_name}-skill",
                    skill_name=skill_name,
                    skill_document=body,
                )
            elif is_prompt:
                prompt_name = args.prompt_name or source.stem
                wheel_path = write_coding_data_prompt_wheel(
                    args.output_dir,
                    plugin_id=args.plugin_id,
                    version=args.version,
                    contribution_id=args.contribution_id or f"{prompt_name}-prompt",
                    prompt_name=prompt_name,
                    prompt_document=body,
                )
            else:
                theme_name = args.theme_name or source.stem
                wheel_path = write_coding_data_theme_wheel(
                    args.output_dir,
                    plugin_id=args.plugin_id,
                    version=args.version,
                    contribution_id=args.contribution_id or f"{theme_name}-theme",
                    theme_name=theme_name,
                    theme_document=body,
                )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        artifact_sha256 = sha256(wheel_path.read_bytes()).hexdigest()
        report = {
            "artifactPath": str(wheel_path),
            "artifactSha256": artifact_sha256,
            "disposableSmoke": "not_checked",
            "profile": (
                "coding-data-skill-v1"
                if is_skill
                else "coding-data-prompt-v1"
                if is_prompt
                else "coding-data-theme-v1"
            ),
            "productAdmission": "not_checked",
            "productSelection": "not_checked",
            "productUse": "not_checked",
            "sha256": artifact_sha256,
            "sourcePath": str(source.absolute()),
        }
        if is_skill or is_prompt:
            validation = validate_coding_data_wheel(wheel_path)
            report["validationResult"] = (
                "passed" if validation["valid"] else "failed"
            )
            report["validationDiagnostics"] = validation["diagnostics"]
            report["validationCommand"] = [
                "loushang-plugin",
                "validate-coding-wheel",
                str(wheel_path),
            ]
            report["targetInstallCommand"] = [
                "loushang",
                "--install-package",
                str(wheel_path.absolute()),
                "--package-scope",
                "project",
            ]
        else:
            report["validationResult"] = "candidate_not_checked"
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "build-coding-worker-candidate":
        source = Path(args.executable_file)
        try:
            executable = _read_worker_candidate_source(source)
            wheel_tag = args.wheel_tag or (
                "py3-none-manylinux_2_17_x86_64"
                if args.native_platform == "linux-x86_64"
                else "py3-none-win_amd64"
            )
            wheel_path = write_coding_local_worker_candidate_wheel(
                args.output_dir,
                plugin_id=args.plugin_id,
                version=args.version,
                contribution_id=args.contribution_id,
                owner_id=args.owner_id,
                native_platform=args.native_platform,
                wheel_tag=wheel_tag,
                executable=executable,
                dependencies=tuple(args.dependency),
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(
            json.dumps(
                {
                    "artifactPath": str(wheel_path),
                    "profile": "coding-local-worker-candidate-v1",
                    "productAdmission": "not_checked",
                    "productSelection": "not_checked",
                    "productUse": "not_checked",
                    "sha256": sha256(wheel_path.read_bytes()).hexdigest(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
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


def _read_worker_candidate_source(source: Path) -> bytes:
    """Read one bounded, unchanged regular author file without executing it."""

    maximum = 16 * 1024 * 1024
    visible_before = source.lstat()
    if (
        not stat.S_ISREG(visible_before.st_mode)
        or not 0 < visible_before.st_size <= maximum
    ):
        raise ValueError(
            "Worker executable source must be a regular file within 16 MiB"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(source, flags), "rb") as input_file:
        opened = os.fstat(input_file.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (visible_before.st_dev, visible_before.st_ino)
            or opened.st_size != visible_before.st_size
        ):
            raise ValueError("Worker executable source changed during open")
        body = input_file.read(maximum + 1)
        after = os.fstat(input_file.fileno())
    visible_after = source.lstat()
    if (
        not 0 < len(body) <= maximum
        or len(body) != opened.st_size
        or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        or (visible_after.st_dev, visible_after.st_ino)
        != (opened.st_dev, opened.st_ino)
    ):
        raise ValueError("Worker executable source changed during read")
    return body


if __name__ == "__main__":
    raise SystemExit(main())
