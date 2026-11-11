# GUI / Web shared Host adapter

Status: implemented on `feature/gui-web-host`; integration validation below.
Scope: browser/native connection adapters and Host-owned client navigation state.

The ordinary desktop and Vite browser entrypoints share one persistent GUI Rust
Web service (`gui/web`) per `LOUSHANG_HOME`. AppHost permits one controller attachment per mux;
the adapter owns that attachment and fans out authoritative snapshots to clients.
It delegates execution and lifecycle to existing AppClient/ExecutionClient and
managed Host APIs. It never owns a second Product execution runtime.

## Tray integration contract

TypeScript entry: `sharedSettings<T>(request)` from `gui/src/client/hostApi.ts`.
Native entry: `invoke("client_settings", { request })`. Rust owner:
`gui/src-tauri/src/client_settings.rs`; it uses the GUI Rust Web service.
No result includes provider credentials. Local Web access requires no login token.

### List saved connections

Request: `{"operation":"connections/list"}`.

Response:

```json
{"selectedId":"local","connections":[{"id":"local","name":"Local","kind":"local","selected":true,"webUrl":"http://127.0.0.1:1422","workspace":"/workspace"},{"id":"office","name":"Office","kind":"remote","selected":false,"webUrl":"https://host.example","workspace":""}]}
```

`local` is reserved. It always represents this machine. Listing does not start a
Host or adapter. A configured dynamic local port can have `webUrl: null` until
adapter startup publishes `state/web/endpoint.json`. A saved workspace is not
proof of current connectivity. Tray code should localize the local display name.

### Select a connection

Request: `{"operation":"connections/select","connectionId":"office"}`.
Returns the updated list. Only selects an existing entry in `connections.json`;
it does not stop the previous Host or start the selected Host. Recreate the UI
client after selection; do not reuse a client tied to the previous connection.

### Query/manage a specific Host without selecting it

```json
{"operation":"host/request","connectionId":"office","request":{"operation":"environment"}}
```

The environment response includes `supported`, `workspace`, and `connections`.
For lifecycle operations:

```json
{"operation":"host/request","connectionId":"office","request":{"operation":"manage","action":"status","workspace":"/server/workspace"}}
```

Actions: `status`, `connect`, `start`, `stop`, `restart`. Stop/restart require
`instanceId` from the last status response; do not invent or reuse a stale ID.
Result: existing `gui-local-host/v1` public fields (`state`, `errorCode`,
`workspace`, `instanceId`, `serviceInstanceId`, `pid`, etc.). Private record paths
and mux authentication never leave the adapter. `status` may start the adapter,
but never starts a managed execution Host. Remote deployment and account authentication are deferred.

### Normal selected connection

`environment`, `preferences`, `remember-workspace` go through `sharedSettings`.
The environment response has `remote: true` to select the HTTP adapter even when
its execution Host is local. This flag currently means adapter transport, not
physical machine location; use connection `kind` for presentation.

`createWebLiveClient(workspace, connectionId?)` binds an instance to a saved
connection ID. The environment response from the native/Vite proxy includes
`connectionId`; pass it when constructing the client. `webRequest(request,
connectionId?)` wraps bound calls in `host/request`, so changing the selected
connection cannot redirect an old client's in-flight operations. Snapshot source
metadata carries that ID so navigation writes use the same Host. A directly
hosted browser uses its same-origin server and can omit the ID. Unsubscribe old
clients before switching; already accepted executions remain owned by their Host.

`webRequest` transports `manage` and `live` to the selected connection. Native
calls use the Rust transport; browser requests use the same-origin Vite proxy or
local standalone server directly, without a login page or access token.

## Storage

Existing `models/`, model `auth/*-auth.json`, `coding/settings.json`, `data/`,
`state/`, and `lmux/` retain their owners. New files:

- `connections.json`: version 1, `servers`, optional `defaultConnection` and
  `defaultWorkspace`; no inline credentials.
- `host.json`: optional `web` listener settings.
- `data/client-preferences.sqlite3`: atomic pin/unpin/visit operations per mux.
- `state/web/`: adapter discovery, startup/owner locks and service log.

Display preferences remain localStorage. Open-window selection and drafts stay
local; persisted last-visited session is only a recovery default. This is a
single-user operator profile, not a newly implemented account system.

## Review and acceptance

Implementing agent owns the delegated cross-scope integration review under the
repository governance profile. Design decision: reuse accepted execution APIs,
keep the sole controller in the shared adapter, keep provider authentication
internal, and store navigation operations under AppHost. Local HTTP access now
requires no token; request-origin validation remains in place. Account design is
deferred to the open-questions document.
Reviewed ownership: `client_preferences` is an optional AppHost storage module;
`coding.client_settings` is its application composition consumer. Neither extends
the AppHost core dependency graph. Connection IDs bind both requests and frontend
navigation caches; the persisted scope remains the Host's mux identity.

Validation completed: GUI typecheck and 107 unit/playback cases; native Rust
format, Clippy and checks for default/fixture configurations; 27 browser layout
cases; Web production build; 4,207 Coding cases; real local Host session creation,
streaming execution, idempotency and interrupt using the existing test provider
without external model requests. Real Chromium windows shared one live session
catalog and pins. Restarting the shared adapter preserved the managed Host.
The original token-based access was superseded by direct local access;
local HTTP access and origin rejection are covered by regression tests. Packaged installer acceptance and remote TLS deployment on a
second machine were not performed by this task.

AppHost regression completed with 3,119 passes and 13 platform skips; its five
inventory failures were resolved by registering the new optional module and
consumers, then rerunning the affected architecture files. G8/G9/G10 evidence
and the installed G10 canary passed. The broad optional Rust probe build exposed
an existing non-exhaustive `ControlResult::Submitted` match in `control_probe`;
the required `snapshot_probe` builds successfully. This task does not change
that separate probe or claim that every optional probe builds.
Scoped Host-runtime checks passed 35 cases with 12 platform skips; the remaining
desktop lifecycle case passed after building its required `snapshot_probe`.

The implementing agent accepts the execution/storage ownership boundaries within
the delegated task scope. This is not a user acceptance statement.
No new CI route, required check, runner or blocking condition is introduced.

Local-access follow-up: nine focused Web tests passed, including a real adapter
process serving a page without credentials, persisting navigation through HTTP,
and retaining it across adapter restart without creating authentication files.
Source dependency facts, Ruff and documentation checks passed. This follow-up
accepts local operation only; remote/account scope remains an open design topic.

## Listener ownership (2026-11-11)

`gui/web` owns HTTP parsing, limits, origin checks, static assets, listener startup,
endpoint discovery and lifetime. It is Rust code and runs without a desktop window.
`coding.web_gateway` remains a private stdio Host adapter; it has no HTTP listener
or Web subprocess startup. `coding.web_server` and `coding.web_endpoint` were removed.
The existing AppHost/AppServer contracts still own sessions and execution.
This scope covers local Web only and adds no account or remote deployment design.
