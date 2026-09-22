from ._g18_native_probe import managed_completion_frame


def frame(*lines, completed=True):
    output = "\x1b[?2026h\x1b[2J\x1b[H"
    for index, line in enumerate(lines, 1):
        output += f"\x1b[{index};1H{line}"
    return output + ("\x1b[?2026l" if completed else "")


def test_managed_completion_requires_new_complete_frame_and_suggestion_row():
    valid = frame("> /he", "  /help", "dev | /help /detach")
    assert managed_completion_frame(valid, after=0)
    assert not managed_completion_frame(valid, after=len(valid))
    assert not managed_completion_frame(frame("> /he", "  /help", completed=False), after=0)
    assert not managed_completion_frame(frame("> /he", "dev | /help /detach"), after=0)
    assert not managed_completion_frame(frame("> /help", "  /help"), after=0)


def test_managed_completion_does_not_match_old_frame_cleared_from_viewport():
    old = frame("> /he", "  /help")
    current = old + frame("> /he", "dev | /help /detach")
    assert not managed_completion_frame(current, after=len(old))
