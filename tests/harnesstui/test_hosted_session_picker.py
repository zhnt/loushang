from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxSelectorV1,
    SessionAvailabilityV1,
    SessionCompatibilityV1,
    SessionDiscoveryCandidateV1,
    SessionIdentityV1,
    SessionListResultV1,
    SessionScopeV1,
)
from loushang.harnesstui.mux.shell import HostedMuxShellV1
from loushang.tui.core import RenderConstraints
from loushang.tui.input import InputEvent

from .test_hosted_mux_profile import FINGERPRINT, _Client


def _key(shell, key):
    shell.handle(InputEvent(kind="key", key=key))


def _text(shell, text):
    shell.handle(InputEvent(kind="text", text=text))


def _page(request, *, title="Saved Session", continuation=None):
    number = 1 if request.scope is SessionScopeV1.CWD else 2
    return SessionListResultV1(
        request.product_id,
        request.scope,
        request.scope_fingerprint,
        "snapshot-1",
        (
            SessionDiscoveryCandidateV1(
                SessionIdentityV1(
                    "coding",
                    f"continuity-{number}",
                    f"session-{number}",
                    request.scope,
                    request.scope_fingerprint,
                ),
                title,
                SessionCompatibilityV1.COMPATIBLE,
                SessionAvailabilityV1.AVAILABLE,
            ),
        ),
        True,
        continuation,
    )


class _Discovery:
    def __init__(self):
        self.requests = []

    async def list_sessions(self, request):
        self.requests.append(request)
        return _page(request)


def _shell(discovery, client=None):
    return HostedMuxShellV1(
        client or _Client(),
        selector=MuxSelectorV1(name="dev"),
        product_id="coding",
        scopes=(
            (SessionScopeV1.CWD, FINGERPRINT),
            (SessionScopeV1.USER_HOME, FINGERPRINT),
        ),
        discovery_client=discovery,
    )


async def _settle(shell):
    async with asyncio.timeout(2):
        while shell.pending_actions:
            await asyncio.sleep(0)


def _render(shell, width=80, height=20):
    constraints = RenderConstraints(width=width, max_height=height)
    result = shell.screen.render(constraints)
    result.validate(constraints)
    return "\n".join(line.text for line in result.lines)


def test_G17_PICKER_f3_scope_select_and_return_preserve_full_editor():
    async def scenario():
        discovery, client = _Discovery(), _Client()
        shell = _shell(discovery, client)
        await shell.start()
        try:
            _text(shell, "original draft")
            editor = shell.screen.composer
            editor.set_selection(0, 8)
            _key(shell, "f3")
            await _settle(shell)
            assert "Saved Session" in _render(shell)
            _key(shell, "tab")  # Modal scope switch, not a member switch.
            assert shell.state.active_window.member_id == "member-1"
            await _settle(shell)
            assert discovery.requests[-1].scope is SessionScopeV1.USER_HOME
            _key(shell, "enter")
            await _settle(shell)
            request = next(
                request for name, request in client.calls if name == "open_member"
            )
            assert request.session.session_id == "session-2"
            assert request.session.scope is SessionScopeV1.USER_HOME
            assert shell.state.active_window.member_id == "member-2"
            _key(shell, "shift+tab")
            assert shell.screen.composer is editor
            assert editor.selected_range == (0, 8)
            _text(shell, "changed")
            assert editor.value == "changed draft"
            _key(shell, "alt+u")
            assert editor.value == "original draft"
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_G17_PICKER_serializes_coalesces_and_fences_dismissed_response():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        discovery = _Discovery()

        async def query(request):
            discovery.requests.append(request)
            if len(discovery.requests) == 1:
                entered.set()
                await release.wait()
            return _page(request, title=request.scope.value)

        discovery.list_sessions = query
        shell = _shell(discovery)
        await shell.start()
        try:
            _text(shell, "kept")
            _key(shell, "f3")
            await asyncio.wait_for(entered.wait(), 1)
            for _ in range(9):
                _key(shell, "tab")
            assert len(discovery.requests) == 1
            assert shell.pending_actions == 1
            _key(shell, "escape")
            release.set()
            await _settle(shell)
            assert not shell.picker.visible
            assert shell.picker.page is None
            assert len(discovery.requests) == 1
            assert shell.screen.composer.value == "kept"
            _key(shell, "f3")
            await _settle(shell)
            assert shell.picker.page.scope is SessionScopeV1.USER_HOME
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_G17_PICKER_global_alias_pagination_expiry_and_explicit_refresh():
    async def scenario():
        discovery = _Discovery()

        async def query(request):
            discovery.requests.append(request)
            if request.continuation:
                raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
            return _page(request, continuation="page-2")

        discovery.list_sessions = query
        shell = _shell(discovery)
        await shell.start()
        try:
            _text(shell, "/sessions global")
            _key(shell, "enter")
            await _settle(shell)
            assert discovery.requests[0].scope is SessionScopeV1.USER_HOME
            _text(shell, "n")
            await _settle(shell)
            assert discovery.requests[-1].continuation == "page-2"
            assert "snapshot_required" in _render(shell)
            _key(shell, "enter")
            assert len(discovery.requests) == 2
            _text(shell, "r")
            await _settle(shell)
            assert len(discovery.requests) == 3
            assert discovery.requests[-1].continuation is None
        finally:
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode", ["absent", "empty", "partial", "unsupported", "unavailable"]
)
def test_G17_PICKER_unselectable_states_never_open(mode):
    async def scenario():
        discovery, client = _Discovery(), _Client()

        async def query(request):
            page = _page(request)
            if mode == "empty":
                return replace(page, candidates=())
            row = replace(
                page.candidates[0],
                availability=SessionAvailabilityV1.UNVERIFIED
                if mode == "partial"
                else SessionAvailabilityV1.UNAVAILABLE,
                compatibility=SessionCompatibilityV1.UNSUPPORTED
                if mode == "unsupported"
                else SessionCompatibilityV1.COMPATIBLE,
            )
            return replace(
                page,
                candidates=(row,),
                complete=mode != "partial",
                omitted_count_exact=mode != "partial",
            )

        discovery.list_sessions = query
        shell = _shell(None if mode == "absent" else discovery, client)
        await shell.start()
        try:
            _key(shell, "f3")
            await _settle(shell)
            assert {
                "absent": "discovery_unavailable",
                "empty": "empty",
                "partial": "incomplete",
                "unsupported": "unsupported",
                "unavailable": "unavailable",
            }[mode] in _render(shell)
            _key(shell, "enter")
            await _settle(shell)
            assert not any(name == "open_member" for name, _ in client.calls)
        finally:
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("width,height", [(1, 1), (8, 3), (30, 12), (80, 24)])
def test_G17_PICKER_sanitizes_titles_and_bounds_terminal_output(width, height):
    async def scenario():
        discovery = _Discovery()

        async def query(request):
            return _page(request, title="\x1b[2Junsafe\x07\n中" * 8)

        discovery.list_sessions = query
        shell = _shell(discovery)
        await shell.start()
        try:
            _key(shell, "f3")
            await _settle(shell)
            text = _render(shell, width, height)
            assert "\x1b[2J" not in text and "\x07" not in text
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_G17_PICKER_loading_controls_and_cancel_resistant_query_remain_owned():
    async def scenario():
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        discovery, client = _Discovery(), _Client()

        async def query(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            return _page(request)

        discovery.list_sessions = query
        shell = _shell(discovery, client)
        shell._timeout = 0.03
        await shell.start()
        _text(shell, "kept")
        editor = shell.screen.composer
        _key(shell, "f3")
        await asyncio.wait_for(entered.wait(), 1)
        _key(shell, "ctrl+c")
        async with asyncio.timeout(1):
            while not any(name == "interrupt" for name, _ in client.calls):
                await asyncio.sleep(0)
        window = shell.state.active_window
        window.pending_interaction_id = "question"
        window.pending_interaction_text = "Inspect this action"
        _key(shell, "f2")
        assert not shell.picker.visible
        assert "Inspect this action" in _render(shell)
        assert shell.screen.composer is editor and editor.value == "kept"
        with pytest.raises(AppServiceError) as debt:
            await shell.close()
        assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        deadline = shell._deadline
        assert cancelled.is_set() and shell.cleanup_pending
        assert shell.pending_actions == 1
        assert not any(name == "detach" for name, _ in client.calls)
        release.set()
        await _settle(shell)
        assert shell.picker.page is None and not shell.picker.visible
        await shell.close()
        assert shell._deadline == deadline and not shell.cleanup_pending
        assert [name for name, _ in client.calls].count("detach") == 1

    asyncio.run(scenario())


def test_G17_PICKER_scope_changes_publish_only_latest_and_saturation_starts_no_query():
    async def scenario():
        discovery = _Discovery()
        entered, release = asyncio.Event(), asyncio.Event()

        async def query(request):
            discovery.requests.append(request)
            if len(discovery.requests) == 1:
                entered.set()
                await release.wait()
            return _page(request)

        discovery.list_sessions = query
        shell = _shell(discovery)
        await shell.start()
        try:
            _key(shell, "f3")
            await asyncio.wait_for(entered.wait(), 1)
            for _ in range(9):
                _key(shell, "tab")
            release.set()
            await _settle(shell)
            assert len(discovery.requests) == 2
            assert shell.picker.page.scope is SessionScopeV1.USER_HOME
            _key(shell, "escape")
            for _ in range(56):
                shell._actions.submit(asyncio.Event().wait)
            _key(shell, "f3")
            assert shell.notice == "action_queue_full"
            assert shell.picker.page is None
            assert len(discovery.requests) == 2
            _key(shell, "ctrl+c")
            assert shell.pending_actions == 57  # The reserved control remains usable.
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_G17_PICKER_stale_membership_rejects_selection_without_open_or_retry():
    async def scenario():
        client = _Client()
        shell = _shell(_Discovery(), client)
        await shell.start()
        try:
            _key(shell, "f3")
            await _settle(shell)
            shell.state.snapshot_required = True
            _key(shell, "enter")
            assert shell.notice == "snapshot_required"
            assert "snapshot_required" in _render(shell)
            assert shell.picker.visible
            assert not any(name == "open_member" for name, _ in client.calls)
        finally:
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "command,scope",
    [
        ("/resume", SessionScopeV1.CWD),
        ("/resume cwd", SessionScopeV1.CWD),
        ("/resume global", SessionScopeV1.USER_HOME),
    ],
)
def test_G17_PICKER_resume_without_identity_opens_exact_scope(command, scope):
    async def scenario():
        discovery = _Discovery()
        shell = _shell(discovery)
        await shell.start()
        try:
            _text(shell, command)
            _key(shell, "enter")
            await _settle(shell)
            assert shell.picker.visible
            assert discovery.requests[0].scope is scope
            assert shell.screen.composer.value == ""
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_G17_PICKER_legacy_explicit_resume_global_never_requires_discovery():
    async def scenario():
        client = _Client()
        shell = _shell(None, client)
        await shell.start()
        try:
            _text(shell, "/resume global continuity-2 session-2")
            _key(shell, "enter")
            await _settle(shell)
            requests = [
                request.session
                for name, request in client.calls
                if name == "open_member"
            ]
            assert len(requests) == 1 and requests[0].scope is SessionScopeV1.USER_HOME
            assert requests[0].session_id == "session-2"
            assert not shell.picker.visible
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_G17_PICKER_next_page_selects_new_identity_once_while_membership_is_pending():
    async def scenario():
        discovery, client = _Discovery(), _Client()
        entered, release = asyncio.Event(), asyncio.Event()
        original = client.open_member

        async def query(request):
            discovery.requests.append(request)
            if request.continuation is None:
                return _page(request, continuation="page-2")
            page = _page(request)
            row = page.candidates[0]
            row = replace(
                row,
                identity=replace(
                    row.identity, continuity_id="continuity-2", session_id="session-2"
                ),
            )
            return replace(page, candidates=(row,))

        async def open_member(request):
            entered.set()
            await release.wait()
            return await original(request)

        discovery.list_sessions, client.open_member = query, open_member
        shell = _shell(discovery, client)
        await shell.start()
        try:
            _key(shell, "f3")
            await _settle(shell)
            _text(shell, "n")
            await _settle(shell)
            assert discovery.requests[-1].continuation == "page-2"
            _key(shell, "enter")
            await asyncio.wait_for(entered.wait(), 1)
            _key(shell, "enter")
            release.set()
            await _settle(shell)
            requests = [
                request.session
                for name, request in client.calls
                if name == "open_member"
            ]
            assert len(requests) == 1
            assert requests[0].session_id == "session-2"
        finally:
            release.set()
            await shell.close()

    asyncio.run(scenario())


def test_G17_PICKER_terminal_byte_playback_resumes_and_restores_old_cursor():
    from io import StringIO

    from loushang.harnesstui.mux.terminal import run_hosted_mux_shell
    from loushang.tui.terminal import FakeTerminalPort, TerminalSize
    from loushang.tui.terminal_session import TerminalSession

    async def scenario():
        client = _Client()
        shell = _shell(_Discovery(), client)
        chunks = iter(
            (
                "original draft",
                "\x1b[D",
                "\x1bOR",
                "\t",
                "\r",
                "\x1b[Z",
                "!",
                "\x02",
                "d",
            )
        )
        modes = []

        class Mode:
            def __enter__(self):
                modes.append("entered")

            def __exit__(self, *args):
                modes.append("restored")

        async def read(stream):
            await _settle(shell)
            return next(chunks, "")

        stdin, stdout = StringIO(), StringIO()
        terminal = FakeTerminalPort(size=TerminalSize(columns=80, rows=24))
        code = await run_hosted_mux_shell(
            shell,
            stdin=stdin,
            stdout=stdout,
            input_chunk_reader=read,
            terminal=terminal,
            session=TerminalSession(stdin, stdout, mode_factory=lambda *args: Mode()),
        )
        assert code == 0 and modes == ["entered", "restored"]
        frames = "\n".join(frame.serialized_output for frame in terminal.frames)
        assert "Sessions |" in frames and "original draf!t" in frames
        assert [
            request.session.session_id
            for name, request in client.calls
            if name == "open_member"
        ] == ["session-2"]
        assert not shell.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("chunks", [("rr",), ("r", "r"), ("nr",), ("n", "r")])
def test_G17_PICKER_text_commands_do_not_depend_on_input_chunk_boundaries(chunks):
    from loushang.tui.input import InputReader

    async def scenario():
        discovery = _Discovery()

        async def query(request):
            discovery.requests.append(request)
            return _page(request, continuation="page-2")

        discovery.list_sessions = query
        shell = _shell(discovery)
        await shell.start()
        try:
            _key(shell, "f3")
            await _settle(shell)
            reader = InputReader()
            for chunk in chunks:
                for event in reader.feed(chunk):
                    shell.handle(event)
            await _settle(shell)
            assert len(discovery.requests) == 2
            assert discovery.requests[-1].continuation is None
            for event in reader.feed("\x1b[200~rrnr\x1b[201~"):
                shell.handle(event)
            await _settle(shell)
            assert len(discovery.requests) == 2  # Pasted text is not a command.
        finally:
            await shell.close()

    asyncio.run(scenario())
