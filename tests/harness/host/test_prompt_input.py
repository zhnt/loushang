from __future__ import annotations

from io import StringIO

from loushang.harness.host.prompt_input import resolve_prompt_input


def test_resolve_prompt_input_combines_stdin_file_prompt_and_followups(
    tmp_path,
) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("file context", encoding="utf-8")

    result = resolve_prompt_input(
        prompt="final request",
        messages=("additional",),
        message_prompts=("next", "last"),
        file_args=(f"@{notes.name}",),
        stdin=StringIO("stdin context"),
        cwd=tmp_path,
    )

    assert result.user_input is not None
    assert "stdin context" in result.user_input
    assert "file context" in result.user_input
    assert result.user_input.endswith("final requestadditional")
    assert result.images is None
    assert result.follow_up_messages == ("next", "last")


def test_resolve_prompt_input_promotes_first_followup_when_prompt_is_empty(
    tmp_path,
) -> None:
    result = resolve_prompt_input(
        prompt=None,
        messages=(),
        message_prompts=("first", "second"),
        file_args=(),
        stdin=StringIO(""),
        cwd=tmp_path,
    )

    assert result.user_input == "first"
    assert result.follow_up_messages == ("second",)


def test_resolve_prompt_input_uses_shared_image_payload_detection(tmp_path) -> None:
    image = tmp_path / "tiny.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x03\x00\x00\x00\x05"
    )

    result = resolve_prompt_input(
        prompt=None,
        messages=(),
        message_prompts=(),
        file_args=(f"@{image.name}",),
        stdin=StringIO(""),
        cwd=tmp_path,
    )

    assert result.images is not None
    assert len(result.images) == 1
    assert result.images[0].mime_type == "image/png"
    assert result.user_input == f'<file name="{image}"></file>'
