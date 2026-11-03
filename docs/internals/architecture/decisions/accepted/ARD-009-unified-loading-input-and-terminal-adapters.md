# ARD-009: Unify Loading Input Behind Terminal Adapters

## Status

- ID: ARD-009
- Scope: Loushang — Coding, HarnessTUI and TUI
- Authority: normative — loading input and terminal ownership contract
- Design status: accepted
- Implementation status: partial — Linux validation; native macOS/Windows validation pending
- Owner: Loushang architecture, HarnessTUI and TUI
- Method consultation: clean local archmethod `master`, commit
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Problem And Options

Coding selected an independent loading input/render owner only on Linux.
macOS and Windows used the main preparation loop. Synchronous preparation could
delay input processing and application echo while the screen said “you can
type”. Terminal ECHO is disabled while the application owns input.

The required behavior is responsive draft editing during synchronous Session
preparation, with submission disabled, followed by lossless exclusive handoff.
Session preparation and Product binding must remain on the main thread.

| Option | Behavior and cost |
| --- | --- |
| Retain platform-specific startup branches | Preserves delayed input/echo on platforms using the main loop |
| Move Product preparation to a worker | Changes callback, ContextVar and Session ownership; substantially widens the change |
| Share the loading owner and adapt terminal input | Selected; preserves Product ownership and limits native differences to TUI |

## Accepted Contract

`LOAD-INPUT-001`: Native terminal startup uses one sequence on every OS:
enter one terminal lease; start the independent loading input/render owner;
observe its first frame; prepare the Product on main; request transfer; cancel
and join the last read and loading worker; bind the Product UI; consume backlog
under loading policy until an empty input boundary; arm submission.

`LOAD-INPUT-002`: TUI owns `NativeTerminalInputReader` and native backend
selection. A reader is exclusive, cancellable, and transferable only after its
previous read has joined. Cancellation retains incomplete decoding and native
key state. Boundary inspection consumes nothing and rejects active reads.
No loop-bound task or blocking native read may survive transfer.

Linux and macOS share the POSIX incremental UTF-8 reader. Windows polls Win32
input records directly: `PeekConsoleInputW` establishes availability before the
exclusive owner calls `ReadConsoleInputW`. It preserves VT characters with zero
virtual-key/scan codes, translates native extended keys and repeats, and retains
UTF-16 and VT-burst state. Non-text records do not prevent admission. Cancellation
leaves no helper thread reading the console. Existing mode adapters own native
setup/restoration. The [Win32 input contract](https://learn.microsoft.com/en-us/windows/console/low-level-console-input-functions)
defines non-consuming immediate peeks and available-record reads.

`LOAD-INPUT-003`: HarnessTUI owns loading policy, rendering, parser/draft
transfer, joined cleanup and submission arming. It depends on the reader port,
never on native implementations. Coding owns Product preparation and binding;
native versus injected file-like input is a capability distinction.

The worker never runs Product actions. Loading text remains an unsent draft;
loading Enter cannot become an implicit ready submit. The lease is restored
after input and Product cleanup settle, including cancellation/failure.
Injected streams retain the asynchronous runner. Hosted/mux/RPC routing and
workspace/Session formats are unchanged.

## Review, Acceptance And Evidence

The implementing Codex agent reviewed and accepted the contract above on
2026-10-15 under delegated Loushang architecture, HarnessTUI and TUI
responsibilities. Review covered dependency direction, main-thread Product
ownership, retained decoding state, cancellation settlement and backlog
admission. No blocking design findings remain. No CI trigger, matrix or gate
is added. The acceptance concerns design; native platform validation remains
explicitly incomplete.

- [POSIX reader tests](../../../../../tests/tui/test_terminal_input_reader_handoff.py)
  cover UTF-8, cancellation, exclusive ownership and admission boundaries.
- [Windows reader tests](../../../../../tests/tui/test_terminal_input_windows_handoff.py)
  cover UTF-16 and VT state across cancellation/new loops, native record decoding,
  zero-VK terminal replies, repeats, modifiers and non-consuming boundaries.
- [Loading adapter tests](../../../../../tests/harnesstui/conversation/test_loading_terminal_adapter.py)
  exercise Windows-adapter echo during synchronous preparation, joined binding,
  blocked loading Enter and explicit ready submission; native POSIX PTY cases
  cover echo and mode restoration on success/quit.
- [Loading owner tests](../../../../../tests/harnesstui/conversation/test_loading_surface.py),
  [coordinator tests](../../../../../tests/harnesstui/conversation/test_threaded_startup.py)
  and [Coding entry tests](../../../../../tests/coding/test_screen_first_startup.py)
  retain resize, parser/draft transfer, repeated cancellation, failure and output
  ordering evidence.

## Remaining Delta And Reconsideration

Linux validation on 2026-10-15 passed 2,213 offline TUI, HarnessTUI and Coding
startup/boundary tests, with 123 existing marker exclusions. This includes real
POSIX PTY input/mode restoration and simulated Windows-adapter startup. Ruff,
changed-source mypy (seven files), generated dependency freshness and nine
documentation invariants passed. Broader mypy checked 229 source files and
reported one existing return-type error in `tui/mouse_backends/tmux.py:30`;
that file is unchanged from the implementation baseline `31faeaac`.

The first PR #793 ConPTY run passed 107 input and 24 platform cases but exposed
two real CLI readiness timeouts. The reader was changed from CRT `getwch`
polling to the Win32 record adapter above so native consumption does not rely
on CRT filtering. The shared CLI contract then passed, while the Windows-only
15-second readiness prerequisite still timed out. Child thread diagnostics
showed Product preparation opening a native journal lock at ten seconds; the
loading loop remained alive in its event poll. The Windows restoration test now
uses the shared contract's existing 30-second admission prerequisite. Its quit
and restoration assertions, terminal backend and triggers are unchanged.
The follow-up native CI run determines the disposition of the remaining timeout.
The follow-up local regression passed 125 reader/startup cases, and the seven
affected source files passed mypy.

Linux runs and simulated Windows input do not establish native macOS/Windows
loading behavior. Native loading echo, quit, draft handoff and mode restoration remain
validation work for those hosts. No cross-platform latency bound is claimed;
native extensions holding the GIL can delay the worker.

Reconsider if a console cannot provide cancellable available-unit reads, or
preparation accesses the shared app before joined handoff. Rollback restores
the previous native selection and reader binding without storage migration.
