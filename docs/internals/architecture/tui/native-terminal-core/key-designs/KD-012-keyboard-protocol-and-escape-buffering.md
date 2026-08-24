# KD-012: Keyboard Protocol And Escape Buffering

## Purpose

Define how native terminal input preserves complete key sequences before routing
them to editor, command, and surface logic.

This design exists to prevent split terminal escape sequences from leaking into
the composer as ordinary text. A common failure mode is receiving `ESC` in one
stdin chunk and `[A` or `[B` in the next chunk. The UI must interpret the full
sequence as an arrow key, not as a standalone Escape followed by typed text.

## Design Goals

- Keep terminal input responsive while preserving complete escape sequences.
- Treat Escape disambiguation as a buffered state-machine concern, not as an
  arbitrary sleep in the input loop.
- Prefer explicit keyboard protocols when the terminal supports them.
- Keep product routers independent from raw terminal protocol details.
- Preserve standalone Escape behavior for cancellation and surface close.

## Layer Responsibilities

### TerminalInputMode

`TerminalInputMode` owns the shared setup and teardown sequence:

- bracketed paste enable and disable
- focus event enable and disable
- keyboard protocol query and cleanup writes
- input drain on exit

Native mode mutation is delegated through a platform mode lease. The POSIX
backend owns cbreak/`termios` capture and restoration. On Windows, console
flags are owned by the session-local `WindowsConsoleMode` selected as the
`NativeConsoleMode`; the Windows input-mode lease is deliberately a no-op so
that two objects never compete to restore the same console flags.

It should not decide whether a partial `ESC` is a key, a prefix of a CSI
sequence, or a prefix of an Alt-modified key. That decision belongs to the input
assembler.

### Native Platform Boundary

Operating-system input transport is isolated below the shared input semantics:

| Owner | Responsibility | Must not own |
| --- | --- | --- |
| `terminal_input.py` | protocol orchestration, TTY gate, async scheduling | `msvcrt`, `termios`, `select`, UTF-16 decoding |
| `terminal_backends/__init__.py` | neutral protocols and lazy platform selection | concrete OS calls or product policy |
| `terminal_backends/windows.py` | `msvcrt` reads, extended keys, UTF-16 surrogate normalization, Win32 console flags | composer, conversation, escape-sequence assembly |
| `terminal_backends/posix.py` | file-descriptor reads, UTF-8 scalar boundaries, cbreak state lease | composer, conversation, escape-sequence assembly |
| `terminal_backends/darwin.py` | Quartz/native Shift-key probing | input routing or product shortcuts |
| `terminal_platform.py` | stable adapter protocol and delegation facade | `ctypes`, `msvcrt`, `termios`, Quartz calls |

Platform composition uses two small ports, `NativeConsoleMode` and
`NativeModifierKeys`, rather than one cross-platform interface containing every
operating-system operation. Windows implements only the console-mode port,
Darwin implements only the modifier-key port, and neutral no-op ports fill the
unsupported capability. The public adapter retains its compatibility methods
while the concrete implementations remain cohesive. `TerminalSession` consumes
the neutral ports directly; a caller-provided legacy `TerminalPlatformAdapter`
is converted once by `adapt_terminal_platform_adapter` at the session boundary.

The dependency direction is one-way: shared input code selects a backend by
platform name; a backend does not import the shared input orchestrator or any
product layer. Concrete backends are imported lazily so importing
`loushang.tui` on Windows never imports POSIX terminal modules, and importing it
on POSIX never imports Windows console code.

Windows Terminal exposes VT input through `msvcrt.getwch()` one UTF-16 unit at
a time. The Windows transport may therefore retain a short, bounded burst after
an initial `ESC` and forward that burst as one chunk. This is transport-level
coalescing, not a second escape parser: the backend does not classify focus,
paste, mouse, or keyboard sequences, and `InputReader` remains their only
semantic owner.

### Keyboard Protocol Controller

Keyboard protocol negotiation is a small runtime state machine. It may live in
`terminal_input` or as a dedicated helper, but its contract is separate from key
parsing.

Startup sequence:

1. Send Kitty keyboard protocol query `\x1b[?u`.
2. If a Kitty protocol response is observed, mark Kitty active and enable flags
   with `\x1b[>7u`.
3. If no Kitty response is observed before the startup fallback deadline, enable
   xterm modifyOtherKeys mode 2 with `\x1b[>4;2m`.
4. On shutdown, disable only the protocol modes that were actually enabled.

The controller consumes protocol response signals. It must not route those
responses to the composer as text.

### Raw Input Reader

The raw stdin reader is a transport layer. It reads available bytes or decoded
text from stdin and forwards chunks to the input assembler.

It may protect UTF-8 character boundaries. It should not implement Escape key
semantics, Alt-key semantics, or CSI completeness rules. Those rules must be
centralized in `InputReader`.

### InputReader

`InputReader` is the authoritative escape sequence assembler.

It accepts arbitrary input chunks and emits normalized `InputEvent` instances
only when a complete sequence is available. Incomplete escape sequences remain
buffered until one of two things happens:

- more input arrives and completes the sequence
- the input loop explicitly flushes the pending sequence after an idle deadline

`InputReader` owns completeness rules for:

- plain `ESC`
- CSI sequences such as `\x1b[A` and `\x1b[1;3A`
- SS3 sequences such as `\x1bOA`
- OSC sequences terminated by BEL or ST
- DCS and APC sequences terminated by ST
- bracketed paste start and end markers
- SGR and X10 mouse sequences
- Kitty keyboard protocol and CSI-u sequences
- xterm modifyOtherKeys sequences

## Escape Disambiguation

Standalone Escape is ambiguous because the same byte starts many terminal
sequences. The runtime handles that ambiguity with a pending-buffer deadline:

1. Feed each raw input chunk to `InputReader.feed(data)`.
2. Route any complete events immediately.
3. If no complete event is emitted and the reader has a pending incomplete
   sequence, keep the sequence buffered.
4. If new input arrives before the idle deadline, feed it into the same reader.
5. If the idle deadline expires with no additional input, flush the pending
   sequence and route the resulting event.

The idle deadline is a last-resort decision for true standalone Escape. It is
not a general delay added to every input event.

The shared native loops currently use a centralized 30ms idle deadline. When a
read and that deadline become ready on the same event-loop turn, the read gets
one final scheduling opportunity before the pending buffer is flushed. This
prevents a completed focus or bracketed-paste tail from being discarded at the
deadline boundary while keeping terminal-runtime wakeups independent.

## Native Loop Contract

The native loop must not immediately call `InputReader.flush()` just because the
current chunk equals `ESC`.

Instead, it should use an explicit pending-input operation:

```text
chunk -> InputReader.feed(chunk) -> complete events
                         |
                         v
              pending incomplete sequence?
                         |
               yes: arm idle flush deadline
                         |
                         v
              deadline expires -> flush pending
```

This keeps split input correct:

```text
chunk 1: ESC        -> no event, pending
chunk 2: [A         -> key: up
```

And it keeps standalone Escape correct:

```text
chunk 1: ESC        -> no event, pending
idle deadline       -> key: escape
```

## Routing Contract

Product and TUI routers receive normalized events only. They should never need
to inspect raw `\x1b` fragments.

Examples:

- `\x1b[A` routes as `key=up`.
- `\x1b[B` routes as `key=down`.
- `\x1b[1;3A` routes as `key=alt+up`.
- `\x1b[1;3B` routes as `key=alt+down`.
- `\x1b[?7u` routes as a `kitty_protocol` signal for negotiation.
- incomplete `\x1b[` does not route until completed or flushed.

When a surface is active, Escape still follows the ordinary focus contract:
the active surface receives the normalized Escape key before global abort logic.

## Timeout Policy

The Escape idle timeout should be short and centralized. Its purpose is to
distinguish a real Escape key press from a delayed escape-sequence tail.

The timeout must be:

- configurable internally for tests
- short enough that pressing Escape feels immediate
- long enough to tolerate common split stdin chunks
- used only for pending incomplete escape sequences

Increasing arbitrary read delays is not an acceptable correctness strategy.

## Failure Handling

If protocol negotiation fails or receives no response, the runtime falls back to
legacy and modifyOtherKeys parsing.

If an incomplete escape sequence times out, the reader flushes it into the best
available normalized event. For a lone `ESC`, that is `key=escape`. For malformed
unknown sequences, the reader may emit inert text or a terminal control signal,
but it must not execute terminal control content.

If shutdown occurs while a partial sequence is buffered, the runtime may discard
it during input drain. It should not write partial terminal responses into the
composer during exit cleanup.

## Implementation Notes

`InputReader` already contains most of the required escape completeness logic.
The main implementation work is to make it the single owner of incomplete
sequence buffering:

- expose whether a pending sequence exists
- expose a targeted pending flush operation
- remove immediate single-`ESC` flushing from the native loop
- move protocol negotiation state out of product routing paths
- keep raw stdin reading focused on transport and UTF-8 safety

The design should avoid adding a second parser with overlapping escape
completeness rules.

## Test Obligations

- split `ESC` then `[A` produces one `up` key event and no text `[A`.
- split `ESC` then `[B` produces one `down` key event and no text `[B`.
- standalone `ESC` produces `escape` only after the pending idle deadline.
- `\x1b[1;3A` produces `alt+up`.
- `\x1b[1;3B` produces `alt+down`.
- Kitty protocol response is consumed as negotiation state and does not appear
  in composer text.
- absence of Kitty response enables modifyOtherKeys fallback.
- bracketed paste remains atomic and is not affected by Escape idle flushing.
- OSC, DCS, APC, mouse, and focus sequences can arrive split across chunks.
- Windows `getwch()` focus and bracketed-paste bursts reach `InputReader`
  without exposing `[I` or `[201~` as composer text.
- screen-loop playback splits focus and bracketed-paste markers across the idle
  boundary and submits only the pasted payload.
- active surfaces receive normalized Escape before global abort handling.
- slash completion closes on Escape without leaking raw escape fragments.
- `/quit` or another exit command leaves no buffered tail that can corrupt the
  shell prompt.
