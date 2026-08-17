from __future__ import annotations

import asyncio

import pytest

from loushang.harness.cli import (
    STANDARD_CLI_PROFILE,
    CliArgumentSpec,
    CliCommandSpec,
    CliOperationRuntime,
    CliOperationSequence,
    CliOperationSpec,
    CliOperationStage,
    CliProfileError,
    parse_args,
)


def test_product_additions_keep_standard_values_separate() -> None:
    design = STANDARD_CLI_PROFILE.augment(
        profile_id="design",
        root_arguments=(
            CliArgumentSpec(
                "design.slides",
                ("--slides",),
                "slides",
                owner="product",
                type=int,
            ),
        ),
    )

    invocation = parse_args(
        ["--model", "fast", "--slides", "12", "draft"],
        design,
    )

    assert invocation.standard_values["model"] == "fast"
    assert invocation.product_values["slides"] == 12
    assert invocation.positionals == ("draft",)


def test_append_arguments_apply_their_declared_value_parser() -> None:
    profile = STANDARD_CLI_PROFILE.augment(
        profile_id="typed-append",
        root_arguments=(
            CliArgumentSpec(
                "example.number",
                ("--number",),
                "numbers",
                owner="product",
                action="append",
                type=int,
                default=[],
            ),
        ),
    )

    invocation = parse_args(["--number", "1", "--number", "2"], profile)

    assert invocation.product_values["numbers"] == [1, 2]


def test_product_commands_and_command_arguments_are_additive() -> None:
    design = STANDARD_CLI_PROFILE.augment(
        profile_id="design",
        commands=(
            CliCommandSpec(
                "design.export",
                ("export-slides", "slides-export"),
            ),
        ),
        command_argument_extensions={
            "design.export": (
                CliArgumentSpec(
                    "design.format",
                    ("--format",),
                    "format",
                    owner="product",
                    choices=("pdf", "png"),
                ),
            ),
        },
    )

    invocation = parse_args(["slides-export", "--format", "pdf", "deck"], design)

    assert invocation.command_id == "design.export"
    assert invocation.product_values["format"] == "pdf"
    assert invocation.positionals == ("deck",)


def test_duplicate_standard_flag_is_rejected_instead_of_overridden() -> None:
    with pytest.raises(CliProfileError, match="duplicate CLI flag"):
        STANDARD_CLI_PROFILE.augment(
            root_arguments=(
                CliArgumentSpec(
                    "design.model",
                    ("--model",),
                    "design_model",
                    owner="product",
                ),
            )
        )


def test_unknown_command_extension_is_rejected() -> None:
    with pytest.raises(CliProfileError, match="unknown command"):
        STANDARD_CLI_PROFILE.augment(
            command_argument_extensions={
                "design.export": (
                    CliArgumentSpec("design.format", ("--format",), "format"),
                )
            }
        )


def test_allow_unknown_preserves_unowned_flags_for_product_boundary() -> None:
    invocation = parse_args(
        ["--future-flag", "value", "message"],
        STANDARD_CLI_PROFILE,
        allow_unknown=True,
    )

    assert invocation.unknown == ("--future-flag",)
    assert invocation.positionals == ("value", "message")


def test_operation_runtime_dispatches_sync_and_async_product_handlers() -> None:
    profile = STANDARD_CLI_PROFILE.augment(
        commands=(CliCommandSpec("design.export", ("export",)),)
    )
    invocation = parse_args(["export", "deck"], profile)
    runtime = CliOperationRuntime(
        {
            "design.export": CliOperationSpec(
                "design.export", lambda value: {"positionals": value.positionals}
            )
        }
    )

    result = asyncio.run(runtime.dispatch(invocation))

    assert result == {"positionals": ("deck",)}


def test_operation_sequence_stops_after_first_handled_stage() -> None:
    calls: list[str] = []

    async def handled() -> int:
        calls.append("handled")
        return 4

    result = asyncio.run(
        CliOperationSequence(
            (
                CliOperationStage(
                    "skipped",
                    lambda: calls.append("skipped"),
                ),
                CliOperationStage("handled", handled),
                CliOperationStage(
                    "not_reached",
                    lambda: calls.append("not_reached"),
                ),
            )
        ).run()
    )

    assert result == 4
    assert calls == ["skipped", "handled"]
