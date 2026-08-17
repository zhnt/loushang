"""Coding's additive CLI grammar.

Shared options come from ``harness.standard``.  Only Method/Work workflow
selection remains a Coding grammar extension; handlers and output are still
owned by the Coding application.
"""

from __future__ import annotations

from loushang.coding.capabilities import parse_capability_mount
from loushang.harness.cli import STANDARD_CLI_PROFILE, CliArgumentSpec, CliProfile

CODING_CLI_PROFILE: CliProfile = STANDARD_CLI_PROFILE.augment(
    profile_id="coding",
    root_arguments=(
        CliArgumentSpec(
            "coding.capability",
            ("--capability",),
            "capability",
            owner="product",
            action="append",
            type=parse_capability_mount,
            default=[],
            metavar="CAPABILITY=MODE",
            help=("Set a Product capability mount to disabled, on_demand, or always."),
        ),
        CliArgumentSpec(
            "coding.method",
            ("--method",),
            "method",
            owner="product",
            help="Guide one coding turn with a discovered method.",
        ),
        CliArgumentSpec(
            "coding.no_method",
            ("--no-method",),
            "no_method",
            owner="product",
            action="store_true",
            help="Run one coding turn without method guidance.",
        ),
        CliArgumentSpec(
            "coding.prompt_steps",
            ("--prompt-steps", "-ps"),
            "prompt_steps",
            owner="product",
            help="Run a prompt workflow file against a coding session.",
        ),
        CliArgumentSpec("coding.work_log", ("--work-log",), "work_log", owner="product"),
        CliArgumentSpec(
            "coding.work_log_inspect",
            ("--work-log-inspect",),
            "work_log_inspect",
            owner="product",
            metavar="PATH",
        ),
        CliArgumentSpec(
            "coding.work_log_run",
            ("--work-log-run",),
            "work_log_run",
            owner="product",
        ),
        CliArgumentSpec(
            "coding.work_log_inspect_format",
            ("--work-log-inspect-format",),
            "work_log_inspect_format",
            owner="product",
            choices=("text", "json", "plans", "plans-json"),
            default="text",
        ),
        CliArgumentSpec(
            "coding.list_methods",
            ("--list-methods",),
            "list_methods",
            owner="product",
            action="store_true",
        ),
        CliArgumentSpec(
            "coding.list_methods_format",
            ("--list-methods-format",),
            "list_methods_format",
            owner="product",
            choices=("tsv", "json"),
            default="tsv",
        ),
        CliArgumentSpec(
            "coding.show_method",
            ("--show-method",),
            "show_method",
            owner="product",
        ),
        CliArgumentSpec(
            "coding.show_method_format",
            ("--show-method-format",),
            "show_method_format",
            owner="product",
            choices=("text", "json"),
            default="text",
        ),
        CliArgumentSpec(
            "coding.show_method_plan",
            ("--show-method-plan",),
            "show_method_plan",
            owner="product",
        ),
        CliArgumentSpec(
            "coding.show_method_plan_format",
            ("--show-method-plan-format",),
            "show_method_plan_format",
            owner="product",
            choices=("text", "json"),
            default="text",
        ),
    ),
)


__all__ = ["CODING_CLI_PROFILE"]
