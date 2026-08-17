from loushang.harness.continuity import ContinuityTarget
from loushang.harnesstui.continuity import (
    DeleteContinuityConfirmation,
    build_delete_continuity_confirmation_surface,
)
from loushang.tui import RenderConstraints, strip_control_sequences


def test_delete_confirmation_uses_compact_danger_copy() -> None:
    target = ContinuityTarget(
        provider_id="coding.sessions",
        opaque_id="session-1",
        revision="1",
    )
    view = build_delete_continuity_confirmation_surface(
        target=target,
        title="Review the parser",
    )
    content = view.content

    assert isinstance(content, DeleteContinuityConfirmation)
    rendered = strip_control_sequences(
        "\n".join(
            line.text
            for line in content.render(RenderConstraints(width=80, max_height=10)).lines
        )
    )
    assert view.subtitle == "Permanently delete the selected session"
    assert "Permanently delete this session?" not in rendered
    assert "Review the parser" in rendered
    assert "Enter delete permanently · Esc cancel" in rendered
