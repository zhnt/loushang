# Screen-first session startup

Status: design and implementation approved by three independent views; Linux
scoped validation complete (see the review record for checks and exclusions).
Tracking: G18 #578. Base: `harness/g18-startup-performance`, `7f84e91c`.

## Objective and scope

Display the actual embedded Coding conversation screen before creating runtime,
resolving session, preparing model selection, completion or resumed history.
Keep that screen and its composer alive when the prepared session is attached.
This is an explicitly authorized successor to G18's import-only optimization;
the original G18 no-readiness-reordering acceptance claims do not cover it.

First delivery targets ordinary embedded interactive launches, including an
explicit session reference and continue. Non-TTY, help/version, command/listing,
prompt/workflow, RPC/channel, hosted/mux and injected custom TUI runners retain
their existing path. Bare `--resume` retains its existing standalone selection
screen in this delivery: do not nest its terminal owner under a conversation
screen. Integrating that picker is a later, separately tested surface change.
Invalid static argument combinations must fail before taking the terminal.

First-frame improvement is not equivalent to faster session readiness. Imports
needed to reach Coding's application binding remain measurable startup cost;
this delivery does not promise removing that import chain or constant input
latency during synchronous Python bootstrap. No background-thread migration of
Session/runtime, import threads, daemon or IPC protocol is introduced.

## Current boundary and proposed ownership

Today `CliApplicationRuntime.run` prepares services, runtime and session before
`run_host`; Coding TUI then prepares continuity, startup view, completion and
history before calling the screen runner. Merely moving `ScreenCodingTuiApp()`
does not render a frame.

| Owner | Responsibility | Must not own |
| --- | --- | --- |
| Coding CLI / UI adapter | Select eligible route; create one Product screen; run existing application lifecycle; prepare and attach session-backed UI | Terminal polling or a second Session lifecycle |
| HarnessTUI startup host | Loading/ready/failed/closing presentation; late-bound interaction callbacks and router; own/join initialization task | Session, model, permission or plugin policy |
| HarnessTUI screen runner | One terminal/input stream/render loop, first-frame scheduling hook, lifecycle settlement before terminal release | Runtime or Session construction |
| Existing Harness/Product lifecycle | Resources, session activation, admission, cleanup, plugin fences | Loading-screen UI |

No new dependency from Harness to HarnessTUI or Coding. Existing fully prepared
screen hosts remain supported. New startup ports carry screen callbacks and
opaque preparation continuations, never a Session/runtime object.

## Sequence and interaction contract

```text
normal route validation → create Product screen with provisional labels
 → acquire terminal once → flush first frame (loading)
 → start existing CLI application as an owned asynchronous task
 → prepare runtime/session/UI → attach callbacks/router to SAME screen
 → ready → ordinary existing interaction → settle → release terminal
```

States: `loading → ready | failed → closing → closed`; loading can also close
directly. No retries, auto-submit, hidden queued prompts, or re-entry in v1.

- Loading: editor text/paste, cursor/edit keys and resize work locally. Enter
  leaves draft intact and displays "Session is loading"; it does not execute
  or queue anything. Ctrl-C / EOF exits. Session-dependent commands, image
  clipboard staging, completion and approval actions are unavailable. Text
  paste remains supported; image staging stays disabled until its runtime
  resource owner and selected input policy are installed.
- Provisional header must not claim an actual model, session, branch or
  permission profile. Show the known cwd and explicit loading status only.
- Ready: atomically install prepared history, labels, completion, policy,
  presenter/event bindings and actual input router before opening submission.
  Preserve composer identity, draft, cursor, selection and pending paste parser;
  do not synthesize a second welcome screen or reset terminal modes.
- Failed: show a concise error in the same screen, preserve draft, keep submit
  disabled and allow exit. No silent fallback to another session. Return the
  original nonzero failure code after exit. Expected early successful completion
  closes with its original code instead of presenting a bogus ready screen.
  Read the bounded diagnostic summary from both explicit stdout and stderr:
  existing non-verbose TUI launch errors are emitted to stdout.
- Ctrl-C/EOF during loading cancels and joins the initialization task. During
  ready, finish ordinary interaction and release the prepared binding normally.
  Terminal restoration occurs after initialization/binding cleanup is settled.
  Cleanup failure must be observable and must not report a successful exit.

## Implementation seams

1. A neutral late-bound startup host keeps forwarding handlers and a router
   behind the normal screen runner. Before attachment it uses an editing-only
   router. After attachment it uses the Product-selected router and keybindings.
2. The runner gains an optional owned lifecycle hook: start after first render,
   wake/check completion, and settle in `finally` while the terminal is owned.
   Existing callers without the hook keep their behavior. No second terminal
   reader and no busy-poll loop.
3. The Product runs the canonical CLI bootstrap inside that owned task. Its TUI
   callback prepares the existing application host with the already visible app;
   its injected screen runner attaches handlers then awaits screen completion.
   Existing context managers remain alive until that continuation is released.
4. Product-selected runtime scope / clipboard ownership is installed at attach,
   not fabricated during loading. Its cleanup follows router disposal and occurs
   before leaving the terminal. One attach only; reject foreign app or repeated
   attachment. Close wins over late completion; late results cannot reopen UI.
5. Errors/output produced during initialization are captured in bounded local
   stream adapters, not written over the live frame. Pass explicit adapters to
   the existing CLI; do not globally redirect process streams across awaits.
   Do not persist captured diagnostics or user input in measurement artifacts.

### Review-required ownership and context details

The canonical CLI does **not** currently provide an acquisition-to-exit runtime
`finally`. The new Coding startup adapter must register a unique runtime cleanup
owner immediately when its runtime builder returns. The owner remains in the
Product initialization task until normal exit, early return, error or cancellation;
it invokes the actual `dispose_session_runtime` contract once, not the generic
`dispose` fallback (which is not the Coding runtime's lifecycle contract).
The embedded screen does not receive ownership of that runtime. Builders remain
responsible for rolling back partial acquisitions before they return. Existing
injected/custom runners are excluded from automatic startup-route adoption.

Closing is an ordered handshake, not two tasks awaiting each other:

```text
closing fence → settle active interaction → dispose attached input router
 → release prepared-screen continuation(exit code)
 → join CLI / prepared bindings / runtime cleanup → restore terminal
```

For an unattached startup, set the closing fence then cancel and join the owned
task. A task already in cleanup must not receive another cancellation from the
host. External/repeated cancellation is deferred while an owned settlement task
is joined with shielding; cancellation still propagates after settlement.
Nested cleanup `finally` blocks must attempt later releases even if an earlier
one raises. Preserve the original failure with cleanup diagnostics, and never
report cleanup failure as success. Router disposal for this new route occurs
inside terminal ownership; do not rely on the legacy runner's outer `finally`.

Attaching also captures the current `contextvars.Context`, after interaction
and runtime-scope contexts are entered. The ready router executes synchronously
in a copy of that context. Prompt, local, surface, steer, follow-up and abort callbacks run
in awaited tasks created with that context; merely constructing a coroutine
under `Context.run` is insufficient. Preparation and cleanup retain their owning
task's context. Loading has no session context. Test router, prompt, local/surface
and cleanup context values, and outer-context non-leakage.

Explicit output adapters preserve the original streams' `isatty()` and encoding
metadata so the canonical second route decision remains interactive. Only the
outer renderer owns real terminal writes. Capture Product output through ready
and closing too, including `on_clean_exit` resume hints and cleanup diagnostics.
After terminal restoration, drain bounded captured text once to its original
stdout/stderr channel, with an explicit truncation marker. Screen error summaries
do not re-enqueue the same diagnostics. No process-global stream redirect across
awaits; third-party raw file-descriptor output is not made safe by these adapters.
Test ordinary TTY routing with capture adapters, and restore-before-hint ordering.

Synchronous setup can still temporarily block the event loop after first frame.
Measure this honestly; moving small safe blocking metadata reads is subsequent
work, not blanket `to_thread` around Product bootstrap.

## Verification and acceptance

Run focused pre-change baselines outside the sandbox, then deterministic tests:

- First rendered frame precedes service/runtime/session factory calls.
- One terminal enter/exit and one screen/composer through successful attach.
- Deliberately suspended bootstrap: text/paste/resize continue; Enter preserves
  draft and makes zero backend calls; image paste causes no artifact allocation.
- Successful attach installs selected keybindings/router; first post-ready
  submission executes exactly once, including resumed history initialization.
- Failure before/after resource acquisition, EOF/Ctrl-C, attach/close race,
  cancellation during initialization and cleanup; no orphan task or double close.
- Exact successful/failing CLI exit codes; no second picker/terminal, stdout
  pollution, model calls or session writes after cancellation has settled.
- Negative routing for non-TTY, help/version, malformed/static-conflicting args,
  listing, prompt, RPC/channel, custom runner, hosted/mux and bare resume picker.
- Existing screen runner / input / application-host and Coding CLI regressions.

Linux PTY/fake-terminal validation is primary. Record spawn→first-frame,
first-frame→key echo, spawn→session-ready, first submitted turn and cleanup
separately; no relaxed timeout, hidden first-use regression or percentage claim
from injected/suspended fixtures. Mac/Windows require subsequent machine runs.
Native/G18 embedded test predicates now distinguish the loading welcome from
the actual session status bar. Historical G18 measurements remain immutable;
changed observer/source provenance requires fresh evidence, not continuation of
an old frozen collection. No new measured performance percentage is claimed.

## Design gate

Three independent read-only reviews: architecture/ownership, interaction and
compatibility, lifecycle/failure/testability. Resolve blocking findings in this
document and obtain approval before changing implementation. Record findings,
revisions and explicit remaining scope in a sibling review record.
