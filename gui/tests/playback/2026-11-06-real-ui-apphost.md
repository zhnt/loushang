# Real Linux GUI → standalone AppHost acceptance

Date: 2026-11-06. Implementation tested: `6320e8d84` on
`feature/gui-cross-platform-bridge`, Ubuntu 26.10.

Result: **real UI requests reach the standalone AppHost and provider; successful
model reply acceptance failed because the provider rejected the request for
insufficient quota.** No mock client, synthetic model, direct backend submission,
or Rust submission probe was used for the message test.

## Startup

The installed CLI ran in a separate Python process, with isolated state and an
empty temporary workspace. It used the ordinary saved model/auth configuration:

```sh
uv run loushang-mux \
  --connection-root /tmp/loushang-gui-real-ui/connection \
  --endpoint workspace serve \
  --workspace /tmp/loushang-gui-real-ui/workspace \
  --application-root /tmp/loushang-gui-real-ui/app \
  --application-id gui.real.ui \
  --cwd-sessions /tmp/loushang-gui-real-ui/cwd-sessions \
  --home-sessions /tmp/loushang-gui-real-ui/home-sessions

uv run loushang-mux \
  --connection-root /tmp/loushang-gui-real-ui/connection \
  --endpoint workspace create gui-real-ui

gui/src-tauri/target/release/harness-gui \
  --loushang-app-record-root /tmp/loushang-gui-real-ui/connection \
  --loushang-mux-name gui-real-ui
```

The empty mux exposed a first-use defect: **New Session was enabled but clicking
it did nothing**. `App.tsx::createSession` requires a selected source Session.
To continue testing without disguising that failure, the GUI was closed normally,
one real initial member was created through the public AppHost management API,
and the GUI was reopened. That setup did not submit a prompt or inject a reply.

## Actual UI operations and results

Native controls were located and clicked through Linux AT-SPI. Wayland keyboard
injection did not populate the draft. The same release executable was restarted
with `GDK_BACKEND=x11`; actual X11 keyboard events and clipboard paste were used
to enter the exact prompt. No JavaScript injection or patched Tauri bridge.

1. The UI displayed `Connected`, `Live AppHost · controlled`, and the real
   `gui-real-ui` mux/Session context. The selected model was
   `openai · gpt-6-astra · Reasoning`.
2. The actual message input was filled with
   `Reply only GUI-REAL-1106. Do not use tools.`. Its text and enabled Send state
   were verified through the accessibility tree before clicking **Send**.
3. The prompt appeared in the actual transcript; the GUI then displayed
   `Execution Failed`, `Source Failed`, `Final cursor 3`, and a complete snapshot.
   The connection stayed `Connected`. No assistant reply appeared.
4. Read-only inspection of the resulting real transcript's structured model-call
   outcome identified `providerId=openai`, `modelId=gpt-6-astra`,
   `endpointId=openai-responses`, `disposition=failed`, and
   `providerErrorCode=credit_balance_exhausted` /
   `providerErrorType=insufficient_quota`. No auth secret or raw provider payload
   was included in the evidence.
5. Clicking **New Session** with an existing selected Session succeeded. The UI
   showed two Sessions (Failed and Idle) and
   `New Session created and attached.`.
6. Clicking **Close window** exited the GUI with code 0. The separate
   `loushang-mux ... list` command still succeeded and reported two members.
   Finally `loushang-mux ... stop` stopped this test's AppHost; its process exited
   with code 0. No existing user service was stopped.

The actual native screenshot is retained locally at
`gui/test-results/real-ui/provider-failed.png` (ignored generated evidence).

## Open findings

- Empty-mux bootstrap is incomplete: an enabled New Session button silently
  returns without a source Session. The initial member required management setup.
- Failure presentation is incomplete: despite a terminal failure, the transcript
  still says `Waiting for output…` and does not expose the actionable quota reason.
- Real provider success remains unverified until usable quota/model configuration
  is available and the UI submission is repeated. Do not count a provider
  rejection as successful conversation acceptance.
- Wayland typing automation was unsuccessful; this run's actual Send interaction
  used X11. This does not prove a manual Wayland input defect.

This run records findings only; it does not modify product behavior or CI gates.

## Retry after user changed the model

On 2026-11-06, the saved default model was changed to `openai · gpt-6.1-sol`.
Restarting the previous test service preserved its two members, but the GUI
remained in reconnecting state without a Session; that recovery problem was not
diagnosed or counted as passing. Old state was preserved. A separate real CLI
service and initial member were prepared under `/tmp/loushang-gui-real-ui-retry/`.

The actual GUI model selector confirmed `openai · gpt-6.1-sol · Reasoning`.
The prompt `Reply only GUI-REAL-RETRY-1106. Do not use tools.` was entered using
native clipboard/keyboard interaction, its actual draft text verified, and
the real Send button clicked. The GUI again showed `Execution Failed` without
an assistant response. The resulting structured call record confirmed
`modelId=gpt-6.1-sol`, `endpointId=openai-responses`, and the same
`credit_balance_exhausted` / `insufficient_quota` rejection. Thus the model change
took effect, but did not resolve the provider quota failure.

Screenshot: `gui/test-results/real-ui/provider-retry-failed.png` (local, ignored).
The GUI was closed normally and the isolated retry service was stopped.
