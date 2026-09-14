# Windows loopback connection lifecycle experiment

Status: partial C1/B2 preparation, 2026-09-14. Not a production GUI port,
AppHost integration, attachment or session snapshot acceptance.

The isolated Rust `connection_probe` now composes native file admission, closed
record decoding/selection, loopback TCP, mutual authentication, authenticated
APP mode and execution hello negotiation. It then closes its borrowed socket.
The probe never sends STOP mode, starts an application or submits work.

The existing file/auth mechanics were extracted into `record_native.rs` and
`transport_auth.rs` and are shared by the earlier probes, not copied again.
The loopback experiment uses temporary records published by Python's existing
`LocalConnectionDirectoryV1` and a test listener using the existing Python
authenticator and execution hello codec. These are real sockets/private records,
but belong exclusively to this test, not an existing user's service.

## Lifecycle behavior implemented in the experiment

- One absolute startup deadline bounds TCP connect and subsequent auth/hello
  IO. Remaining time is reapplied to each read/write, so fragmented or slow
  traffic cannot refresh the startup allowance.
- The cancellation experiment owns a socket clone and shuts down both
  directions to wake blocked IO. Its worker is joined on all exits; no detached
  cancellation worker survives a completed attempt.
- Failed startup drops all owned stream handles. Success verifies and echoes
  canonical execution hello, then explicitly shuts down the connection.
- Authentication record instance and AppService serviceInstanceId remain
  distinct. Hello service identity is validated and retained, not incorrectly
  equated to the endpoint reservation's authentication instance.
- Errors are fixed/redacted. No keys or private record bodies are printed or
  exposed through Tauri/WebView commands.

## Evidence

```text
pnpm --dir gui run check:connection-contract
```

Windows-only and opt-in, with locked offline build dependencies. Eight scenarios
exercise 16 connections: normal operation, auth stall, hello stall, cancellation
during auth/hello, slow header/body, mismatched profile and noncanonical hello.
After every scenario a fresh client completes a handshake against the same
listener. The listener remains active and observes connection closure.

The deadline/cancellation scenarios use short test deadlines; the Python
supervisor's longer timeout is only a runaway-process safety net. These tests
now exercise Rust/socket cancellation rather than relying solely on killing a
pipe subprocess. Previously passing auth/file probes were rerun after extraction.
No default check, CI or TUI/Harness gate was added.

## Remaining production work

This binary still runs blocking IO on its own process, with a test-triggered
cancel timer. A real GUI adapter needs an explicit owner/worker interface and
user cancellation handle, stale-attempt isolation, ongoing reader/writer and
bounded pending requests. The synchronous native record-admission phase cannot
yet be interrupted; the deadline is checked after it returns. Cancellation
during TCP connect, close-failure reporting and sensitive-buffer cleanup do not
have production guarantees from this experiment.

The original hello-only mode closes immediately. The subsequent
[attachment mode](attachment-lifecycle-evidence.md) adds sequential member
snapshots and detach with a scripted peer. An ongoing request dispatcher,
native GUI port and shared AppHost integration remain pending. Do not expose
a Send button or label the fixture UI live based on these tests alone.
