from __future__ import annotations

from loushang.harnesstui.conversation.runtime_view import (
    stable_string_queue_reader,
)


def test_stable_string_queue_reader_uses_only_an_explicit_source() -> None:
    reader = stable_string_queue_reader(lambda: ["first", 7, None, "last"])

    assert reader() == ("first", "last")
    assert stable_string_queue_reader(None)() == ()


def test_stable_string_queue_reader_is_fail_soft() -> None:
    def broken_source() -> object:
        raise RuntimeError("queue unavailable")

    assert stable_string_queue_reader(broken_source)() == ()
    assert stable_string_queue_reader(lambda: "not a queue")() == ()
