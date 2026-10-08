import pytest

from ._lmux_product_frames import (
    approval_details_visible,
    approval_pending_visible,
    assert_no_completed_reply,
    denied_tool_reply_completed,
    reply_completed,
    reply_streaming,
    target_state_visible,
    tool_reply_completed,
)
from .test_lmux_completion_witness import frame

EXPECTED = "LMUX_REPLY_" + "a" * 32
STATUS = "Hosted | FirstUse | idle | cwd / user_home; /help"
FOOTER = "perf | *1 | /help /detach"


@pytest.mark.parametrize("kind", ["reply", "tool", "denial"])
def test_completed_reply_accepts_exact_bare_idle_not_unknown_or_stale(kind):
    text, predicate = {
        "reply": (EXPECTED, lambda output, after: reply_completed(output, EXPECTED, after=after)),
        "tool": ("LMUX_TOOL_COMPLETED", lambda output, after: tool_reply_completed(output, after=after)),
        "denial": ("Tool lmux_evidence requires approval", lambda output, after: denied_tool_reply_completed(output, after=after)),
    }[kind]
    status = "Hosted | FirstUse | idle"
    output = frame("* " + text, ">", status, FOOTER)
    assert predicate(output, 0)
    assert not predicate(output, len(output))
    for wrong in (status + " | request_unknown", status.replace("idle", "running"),
                  status.replace("FirstUse", "Other")):
        assert not predicate(frame("* " + text, ">", wrong, FOOTER), 0)
    assert not predicate(frame("* " + text, ">", status, FOOTER.replace("*1", "*2")), 0)


@pytest.mark.parametrize("hint", ["cwd / user_home; /help", "cwd / user_home: /new <scope>; /help"])
def test_reply_acknowledgement_accepts_both_exact_help_variants(hint):
    status = "Hosted | FirstUse | idle | submit: request_acknowledged; " + hint
    output = frame("* " + EXPECTED, ">", status, FOOTER)
    assert reply_completed(output, EXPECTED, after=0)
    for receipt in ("request_pending", "request_unknown", "request_failed"):
        assert not reply_completed(frame("* " + EXPECTED, ">",
            status.replace("request_acknowledged", receipt), FOOTER), EXPECTED, after=0)


def test_denied_tool_reply_is_not_approval_pending_or_success():
    text = "* Tool lmux_evidence requires approval"
    assert denied_tool_reply_completed(frame(text, ">", STATUS, FOOTER), after=0)
    for status in (STATUS.replace("idle", "running"), STATUS.replace("FirstUse", "Other"),
                   STATUS.replace("cwd /", "submit: request_pending; cwd /")):
        assert not denied_tool_reply_completed(frame(text, ">", status, FOOTER), after=0)
    assert not denied_tool_reply_completed(frame("* LMUX_TOOL_COMPLETED", ">", STATUS, FOOTER), after=0)
    assert not tool_reply_completed(frame(text, ">", STATUS, FOOTER), after=0)


@pytest.mark.parametrize("receipt_state", ["request_pending", "request_acknowledged", "request_unknown", "request_failed"])
def test_pending_approval_can_coexist_with_submit_receipt(receipt_state):
    status = ("Hosted | FirstUse | running | submit: " + receipt_state
              + "; Approval pending: F2 details; /approve /deny")
    output = frame(">", status, FOOTER.replace("*1", "*1!"))
    # The acknowledged variant exceeds this fixed 100-column fixture; it is
    # not a fully presented single-line status and must not prove readiness.
    assert approval_pending_visible(output, after=0) is (receipt_state == "request_pending")
    assert not tool_reply_completed(output, after=0)
    assert not approval_pending_visible(output, after=len(output))
    assert not approval_pending_visible(frame(">", status, FOOTER), after=0)
    assert not approval_pending_visible(frame(">", status.replace("FirstUse", "Other"),
                                              FOOTER.replace("*1", "*1!")), after=0)


def test_approval_and_tool_reply_require_distinct_current_states():
    pending = frame(">", "Hosted | FirstUse | running | Approval pending: F2 details; /approve /deny",
                    FOOTER.replace("*1", "*1!"))
    assert approval_pending_visible(pending, after=0)
    assert not approval_pending_visible(pending, after=len(pending))
    assert not tool_reply_completed(pending, after=0)
    complete = frame("* LMUX_TOOL_COMPLETED", ">", STATUS, FOOTER)
    assert tool_reply_completed(complete, after=0)
    assert not tool_reply_completed(frame("* LMUX_TOOL_COMPLETED", ">", STATUS.replace("idle", "running"),
                                        FOOTER.replace("*1", "*1!")), after=0)
    assert not tool_reply_completed(frame("* LMUX_TOOL_COMPLETED", ">", STATUS.replace("FirstUse", "Other"),
                                        FOOTER), after=0)


@pytest.mark.parametrize("fault", [None, "partial-page", "wrong-tool", "missing-args", "incomplete-frame", "wrong-mux", "wrong-tab", "missing-footer"])
def test_approval_details_must_be_fully_presented(fault):
    output = frame(
        "Approval details — Esc back, then /approve or /deny",
        "other tool call" if fault == "wrong-tool" else "lmux_evidence tool call",
        "Tool call requires approval",
        "" if fault == "missing-args" else "{}",
        "1-3/4 | PgUp/PgDn | Esc back" if fault == "partial-page" else "1-3/3 | PgUp/PgDn | Esc back",
        "other | *1! | /help /detach" if fault == "wrong-mux" else
        "perf | 1! *2 | /help /detach" if fault == "wrong-tab" else
        "" if fault == "missing-footer" else "perf | *1! | /help /detach",
        completed=fault != "incomplete-frame",
    )
    assert approval_details_visible(output, after=0) is (fault is None)


@pytest.mark.parametrize("running", [False, True])
def test_target_state_requires_current_complete_exact_target(running):
    status = STATUS.replace("idle", "running") if running else STATUS
    footer = FOOTER.replace("*1", "*1~") if running else FOOTER
    output = frame(">", status, footer)
    assert target_state_visible(output, running=running)
    assert not target_state_visible(output, running=not running)
    assert not target_state_visible(output, running=running, after=len(output))
    assert not target_state_visible(frame(">", status, footer, completed=False), running=running)
    assert not target_state_visible(frame(">", status.replace("FirstUse", "Other"), footer), running=running)
    assert not target_state_visible(frame(">", status, footer.replace("*1", "1 *2")), running=running)


@pytest.mark.parametrize("running", [False, True])
def test_settled_bare_status_is_exact_and_requires_fresh_complete_frame(running):
    state = "running" if running else "idle"
    status = f"Hosted | FirstUse | {state}"
    footer = FOOTER.replace("*1", "*1~") if running else FOOTER
    output = frame(">", status, footer)
    assert target_state_visible(output, running=running)
    assert not target_state_visible(output, running=running, after=len(output))
    assert not target_state_visible(frame(">", status, footer, completed=False), running=running)
    for wrong in (status + " | request_unknown", status.replace("FirstUse", "Other")):
        assert not target_state_visible(frame(">", wrong, footer), running=running)
    assert not target_state_visible(frame(">", status, footer.replace("*1", "*2")), running=running)


def test_interrupt_acknowledged_idle_is_not_unknown_or_pending():
    status = "Hosted | FirstUse | idle | interrupt: request_acknowledged; cwd / user_home; /help"
    assert target_state_visible(frame(">", status, FOOTER), running=False)
    for state in ("request_pending", "request_unknown", "request_failed"):
        assert not target_state_visible(frame(">", status.replace("request_acknowledged", state), FOOTER), running=False)


def test_running_reattach_accepts_explicit_partial_output_omission_notice():
    status = "Hosted | FirstUse | running | running; earlier partial output is not in the v1 snapshot"
    output = frame(">", status, FOOTER.replace("*1", "*1~"))
    assert target_state_visible(output, running=True)
    assert not target_state_visible(output, running=False)
    assert not reply_completed(frame("* " + EXPECTED, ">", status, FOOTER.replace("*1", "*1~")), EXPECTED, after=0)
    assert not target_state_visible(frame(">", status.replace("FirstUse", "Other"),
                                          FOOTER.replace("*1", "*1~")), running=True)
    assert not target_state_visible(frame(">", status.replace("| running |", "| idle |"), FOOTER), running=False)


def test_delayed_final_rejects_late_completion_even_if_running_again_at_exit():
    complete = frame("* " + EXPECTED, ">", STATUS, FOOTER)
    running = frame("* " + EXPECTED, ">", STATUS.replace("idle", "running"),
                    FOOTER.replace("*1", "*1~"))
    # An old frame before input is excluded, but every subsequent frame counts.
    assert_no_completed_reply(complete + running, EXPECTED, before_send=complete)
    with pytest.raises(AssertionError, match="blocked final"):
        assert_no_completed_reply(complete + running + complete + running,
                                  EXPECTED, before_send=complete)
    with pytest.raises(AssertionError, match="truncated"):
        assert_no_completed_reply(running, EXPECTED, before_send="lost prefix")


def test_full_text_running_frame_is_not_completion():
    running = frame("* " + EXPECTED, ">", STATUS.replace("idle", "running"),
                    FOOTER.replace("*1", "*1~"))
    assert reply_streaming(running, EXPECTED, after=0)
    assert not reply_completed(running, EXPECTED, after=0)
    assert not reply_streaming(running, EXPECTED, after=len(running))
    complete = frame("* " + EXPECTED, ">", STATUS, FOOTER)
    assert not reply_streaming(complete, EXPECTED, after=0)
    assert reply_completed(complete, EXPECTED, after=0)


def test_pending_request_may_stream_but_cannot_be_completed():
    status = "Hosted | FirstUse | running | submit: request_pending; cwd / user_home; /help"
    output = frame("* " + EXPECTED, ">", status, FOOTER.replace("*1", "*1~"))
    assert reply_streaming(output, EXPECTED, after=0)
    assert not reply_completed(output, EXPECTED, after=0)
    idle = frame("* " + EXPECTED, ">", status.replace("running", "idle"), FOOTER)
    assert not reply_streaming(idle, EXPECTED, after=0)
    assert not reply_completed(idle, EXPECTED, after=0)
    for state in ("request_unknown", "request_failed"):
        assert not reply_streaming(frame("* " + EXPECTED, ">", status.replace("request_pending", state),
                                         FOOTER.replace("*1", "*1~")), EXPECTED, after=0)


@pytest.mark.parametrize("fault", ["missing-text", "wrong-session", "wrong-tab", "incomplete", "wrong-nonce"])
def test_streaming_witness_rejects_unrelated_or_incomplete_frames(fault):
    text = "* " + EXPECTED if fault != "missing-text" else ""
    status = STATUS.replace("idle", "running")
    footer = FOOTER.replace("*1", "*1~")
    if fault == "wrong-session":
        status = status.replace("FirstUse", "Other")
    if fault == "wrong-tab":
        footer = footer.replace("*1~", "1~ *2")
    expected = "LMUX_REPLY_" + "b" * 32 if fault == "wrong-nonce" else EXPECTED
    assert not reply_streaming(frame(text, ">", status, footer, completed=fault != "incomplete"),
                               expected, after=0)


def test_reply_requires_a_new_complete_current_frame():
    valid = frame("* " + EXPECTED, ">", STATUS, FOOTER)
    assert reply_completed(valid, EXPECTED, after=0)
    assert not reply_completed(valid, EXPECTED, after=len(valid))
    assert not reply_completed(frame("* " + EXPECTED, ">", STATUS, FOOTER, completed=False), EXPECTED, after=0)
    cleared = valid + frame(">", STATUS, FOOTER)
    assert not reply_completed(cleared, EXPECTED, after=len(valid))


def test_acknowledged_request_still_requires_idle_and_exact_reply():
    status = "Hosted | FirstUse | idle | submit: request_acknowledged; cwd / user_home; /help"
    assert reply_completed(frame("* " + EXPECTED, ">", status, FOOTER), EXPECTED, after=0)
    assert not reply_completed(frame("* " + EXPECTED, ">", status.replace("idle", "running"),
                                     FOOTER.replace("*1", "*1~")), EXPECTED, after=0)
    for state in ("request_pending", "request_unknown", "request_failed"):
        assert not reply_completed(frame("* " + EXPECTED, ">", status.replace("request_acknowledged", state),
                                         FOOTER), EXPECTED, after=0)


@pytest.mark.parametrize("fault", [
    "running", "approval", "unread", "wrong-tab", "wrong-session", "error",
    "unknown", "snapshot", "stale-reply", "composer-only",
])
def test_full_reply_text_is_insufficient_for_completion(fault):
    text, composer, status, footer = "* " + EXPECTED, ">", STATUS, FOOTER
    if fault in {"running", "approval", "unread"}:
        footer = footer.replace("*1", "*1" + {"running": "~", "approval": "!", "unread": "+"}[fault])
    elif fault == "wrong-tab":
        footer = footer.replace("*1", "1 *2")
    elif fault == "wrong-session":
        status = status.replace("FirstUse", "Other")
    elif fault in {"error", "unknown", "snapshot"}:
        status = "Hosted | FirstUse | idle | " + {
            "error": "invalid_or_unavailable_action", "unknown": "request_unknown",
            "snapshot": "snapshot_required: /refresh",
        }[fault]
    elif fault == "stale-reply":
        text = "* LMUX_REPLY_" + "b" * 32
    else:
        text, composer = "", "> " + EXPECTED
    assert not reply_completed(frame(text, composer, status, footer), EXPECTED, after=0)
