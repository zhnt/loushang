from __future__ import annotations

from io import StringIO

from loushang.harnesstui.conversation.resume import (
    ConversationResumeHint,
    render_conversation_resume_hint,
    write_clean_exit_resume_hint,
)


class _FlushRecordingStringIO(StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


def test_render_conversation_resume_hint_quotes_prepared_command() -> None:
    hint = ConversationResumeHint(
        heading="Continue later:",
        command=("example", "--resume", "/tmp/a session.jsonl"),
    )

    assert render_conversation_resume_hint(hint) == (
        "\nContinue later:\nexample --resume '/tmp/a session.jsonl'\n"
    )


def test_write_clean_exit_resume_hint_writes_and_flushes_once() -> None:
    stdout = _FlushRecordingStringIO()
    hint = ConversationResumeHint(heading="Continue:", command=("example", "id"))

    write_clean_exit_resume_hint(stdout=stdout, exit_code=0, hint=hint)

    assert stdout.getvalue() == "\nContinue:\nexample id\n"
    assert stdout.flush_count == 1


def test_write_clean_exit_resume_hint_suppresses_failure_and_missing_hint() -> None:
    stdout = _FlushRecordingStringIO()
    hint = ConversationResumeHint(heading="Continue:", command=("example", "id"))

    write_clean_exit_resume_hint(stdout=stdout, exit_code=1, hint=hint)
    write_clean_exit_resume_hint(stdout=stdout, exit_code=0, hint=None)

    assert stdout.getvalue() == ""
    assert stdout.flush_count == 0
