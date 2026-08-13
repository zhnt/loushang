from __future__ import annotations

from tests.tui.terminal_process_support.query_responder import (
    TerminalQueryResponder,
)


def test_responder_handles_split_dsr_and_ignores_ordinary_vt() -> None:
    responder = TerminalQueryResponder(rows=24, columns=80)

    assert responder.feed("ordinary\x1b[31m\x1b[") == ()
    assert responder.feed("5n") == ("\x1b[0n",)
    assert responder.feed("\x1b[6") == ()
    assert responder.feed("n") == ("\x1b[1;1R",)
    assert responder.unknown_queries == []


def test_responder_answers_conpty_device_attributes_query() -> None:
    responder = TerminalQueryResponder(rows=24, columns=80)

    assert responder.feed("\x1b[c") == ("\x1b[?1;0c",)


def test_responder_does_not_claim_kitty_and_cell_size_has_explicit_profiles() -> None:
    baseline = TerminalQueryResponder(rows=31, columns=103)
    enabled = TerminalQueryResponder(
        rows=31, columns=103, respond_to_cell_size=True
    )

    assert baseline.feed("\x1b[?u\x1b[16t") == ()
    assert enabled.feed("\x1b[16t") == ("\x1b[6;31;103t",)


def test_responder_records_unknown_blocking_query_for_fail_closed_driver() -> None:
    responder = TerminalQueryResponder(rows=24, columns=80)

    assert responder.feed("\x1b[99n") == ()
    assert responder.unknown_queries == ["\x1b[99n"]
