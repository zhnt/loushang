# GUI / Web shared Host adapter

Status: implemented on `feature/gui-web-host`; integration validation below.
Scope: browser/native connection adapters and Host-owned client navigation state.

The ordinary desktop and Vite browser entrypoints share one persistent Web
adapter per `LOUSHANG_HOME`. AppHost permits one controller attachment per mux;
the adapter owns that attachment and fans out authoritative snapshots to clients.
It delegates execution and lifecycle to existing AppClient/ExecutionClient and
managed Host APIs. It never owns a second Product execution runtime.

## Tray integration contract

TypeScript entry: `sharedSettings<T>(request)` from `gui/src/client/hostApi.ts`.
Native entry: `invoke("client_settings", { request })`. Python owner:
`loushang.coding.client_settings.settings_request`.
No result includes provider credentials or server access tokens.

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
but never starts a managed execution Host. Remote requests require a configured
credential and HTTPS except for explicit loopback URLs.

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
calls keep credentials in the Python helper; browser requests use the same-origin
Vite proxy or the standalone server's HttpOnly session cookie.

## Storage

Existing `models/`, model `auth/*-auth.json`, `coding/settings.json`, `data/`,
`state/`, and `lmux/` retain their owners. New files:

- `connections.json`: version 1, `servers`, optional `defaultConnection` and
  `defaultWorkspace`; no inline credentials.
- `host.json`: optional `web` listener settings.
- `auth/connections/<id>.json`: native remote connection token.
- `auth/server/web-token`: server access token.
- `data/client-preferences.sqlite3`: atomic pin/unpin/visit operations per mux.
- `state/web/`: adapter discovery, startup/owner locks and service log.

Display preferences remain localStorage. Open-window selection and drafts stay
local; persisted last-visited session is only a recovery default. This is a
single-user operator profile, not a newly implemented account system.

## Review and acceptance

Implementing agent owns the delegated cross-scope integration review under the
repository governance profile. Design decision: reuse accepted execution APIs,
keep the sole controller in the shared adapter, separate browser access tokens
from provider authentication, and store navigation operations under AppHost.
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
Standalone authentication, origin rejection and remote-client transport were
tested on loopback. Packaged installer acceptance and remote TLS deployment on a
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
