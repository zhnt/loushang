# `loushang.ai` authentication

Authentication lifecycle ownership lives in `loushang.ai.auth`. Agent, coding,
TUI, CLI, and other application layers may display authentication state and
open authorization URLs, but they do not parse tokens, exchange OAuth codes, or
refresh credentials themselves.

## Public flow boundary

The public API separates acquiring authentication from using existing
authentication:

- `await auth.login(model)` starts a configured OAuth flow and returns an
  `OAuthLoginSession`. It does not open a browser, wait for the user, or call a
  model.
- `await auth.get_auth(model)` resolves existing authentication into
  `ApiKeyAuth` or `OAuthBearerAuth`. It may load and refresh an eligible
  credential, but it never starts login or opens a browser.
- `await auth.status(model)` reports whether the model is authenticated and
  which actions an application can offer. It performs no login or refresh.
- `await auth.logout(model)` revokes a stored credential when a matching OAuth
  adapter supports it, then removes that model's credential from the Loushang
  store. It does not delete credentials owned by an external source.

The resolved request object is passed explicitly to the model call:

```python
import loushang.ai as ai

model = ai.get_model("moonshot", "openai-completions", "kimi-k2.6")
request_auth = await ai.auth.get_auth(model)
message = await ai.complete(model, context, auth=request_auth)
```

`CallOptions(auth=request_auth)` remains equivalent when an application already
builds a `CallOptions` value. Do not pass both forms in one call.

## API keys

For API-key models, `get_auth()` reads the model catalog's `auth.apiKeyEnv` and
`auth.apiKeyEnvs` declarations. Missing configuration raises
`AuthenticationRequiredError` with `reason="missing_credential"` and the
`configure_api_key` action. `status()` exposes the same state without raising.

## Config-driven OAuth

Standard OAuth authorization-code flows are model configuration, not Python
provider classes:

```json
{
  "auth": {
    "kind": "oauth",
    "provider": "company-oauth",
    "oauth": {
      "client_id": "authorized-public-client",
      "authorization_endpoint": "https://login.example/authorize",
      "token_endpoint": "https://login.example/token",
      "scopes": ["model.invoke"]
    }
  }
}
```

Optional OAuth fields are `redirect_uri`, `revocation_endpoint`, and
`token_endpoint_auth_method`. Without `redirect_uri`, the generic client binds
an ephemeral HTTP loopback callback. The flow uses state validation and PKCE.
There are no `KimiOAuthProvider`, `GitHubOAuthProvider`, or
`OpenAIOAuthProvider` classes for standard flows.

### Application-owned interaction

The application decides how to present the authorization URL:

```python
import webbrowser
import loushang.ai as ai

session = await ai.auth.login(model)
webbrowser.open(session.authorization_url)
credential = await session.wait()
```

`login()` starts the loopback callback listener and returns immediately. The
application may use a browser, print the URL, or present it in another UI.
`session.wait()` exchanges the callback code and saves the resulting
`OAuthCredential` in `FileCredentialStore`. The auth package never imports or
calls `webbrowser`.

The resulting credential closes the normal request loop:

```python
request_auth = await ai.auth.get_auth(model)
message = await ai.complete(model, context, auth=request_auth)
```

## Status and recovery actions

`status()` returns `AuthStatus`, including `authenticated`, `auth_kind`,
`actions`, and lifecycle/source metadata:

```python
current = await ai.auth.status(model)
if not current.authenticated and "login" in current.actions:
    session = await ai.auth.login(model)
```

A missing generic OAuth credential exposes `login`. A missing external
credential source exposes `external_credential`. An API-key model exposes
`configure_api_key`. `AuthStatus.to_dict()` returns JSON-ready action lists.

`get_auth()` raises `AuthenticationRequiredError` when no usable credential
exists. Its structured details include:

```json
{
  "reason": "missing_credential",
  "available_actions": ["login"]
}
```

It never calls `login()` automatically.

`logout(model)` resolves the credential owner from the model declaration. The
legacy `logout(provider)` form remains supported for registered OAuth provider
adapters.

## Credentials and refresh

`OAuthCredential` is persisted lifecycle state. `OAuthBearerAuth` is
request-level state. Model protocol adapters receive only request-level auth and
resolved headers, never lifecycle credentials or their sources.

Within the model's declared auth kind, resolution order remains:

1. Explicit request auth.
2. An explicitly supplied `OAuthCredential`.
3. An explicit credential file.
4. The default `FileCredentialStore`.
5. A registered external `CredentialSource`.
6. Model-configured API-key environment variables.

Provider-managed or generic OAuth credentials can refresh through the model's
generic OAuth configuration. Updated Loushang credential files and default
store credentials are written atomically.

An imported credential is refresh-eligible only when its `CredentialSource`
declares `supports_refresh = True`; a compatible registered refresh extension
still performs the protocol operation. A source that does not opt in raises
`CredentialExpiredError` when its token is expired or within the refresh
window.

## Auth extension registry

Special authentication capabilities use `AuthExtensionRegistry`. The registry
currently supports `CredentialSource` extensions:

```python
from loushang.ai.auth import AuthExtensionRegistry

extensions = AuthExtensionRegistry([company_source])
request_auth = await auth.get_auth(model, extensions=extensions)
```

Module-level `register_credential_source()` registers a source in the default
registry. Resolver logic looks up the model's declared auth provider in the
registry; it contains no provider-ID or base-URL branches.

A credential source defines:

- `id`
- `description`
- `recovery_hint`
- `experimental`
- `supports_refresh`
- `matches(model)`
- `load()` and `load_file()`

It imports authentication created by another application. It must not implement
OAuth login, refresh, revocation, model calls, or UI behavior.

## OpenAI Codex external credential

`OpenAICodexCredentialSource` is an experimental credential importer, not an
OAuth login provider. It can read a file-backed Codex ChatGPT login from
`~/.codex/auth.json` and convert it to `OAuthCredential`. Its metadata is:

```text
id = "openai-codex"
description = "Use existing Codex CLI login"
recovery_hint = "Run codex login"
experimental = True
supports_refresh = False
```

Loushang does not own an OpenAI OAuth client, does not expose
`auth.login(codex_model)`, and does not overwrite or refresh this source.
OpenAI Codex support currently imports existing Codex CLI credentials. It does
not perform ChatGPT OAuth login.
Codex owns browser login and automatic token refresh; run `codex login` to
establish or repair it. Codex may store credentials in an OS credential store,
in which case experimental file import is unavailable. Treat `auth.json` like a
password.

## Credential storage

`FileCredentialStore` defaults to
`~/.loushang/auth/{provider}-auth.json`. It writes UTF-8 JSON with atomic replace,
creates directories with mode `0700`, and uses file mode `0600` where POSIX
permissions are available. Tokens are excluded from ordinary object reprs and
must never be logged.

## Errors

Lifecycle failures are structured authentication errors:

- `AuthenticationRequiredError`: no usable authentication; inspect `reason`
  and `available_actions`.
- `CredentialExpiredError`: no permitted refresh path exists.
- `RefreshFailedError`: a configured generic or registered refresh operation
  failed.
- `InvalidCredentialError`: credential data is malformed or incompatible.
- `OAuthProviderNotConfiguredError`: generic OAuth client configuration or its
  loopback redirect is invalid.

These failures occur before the provider request, so applications do not infer
authentication state from a generic HTTP 401.

Runnable upper-application examples are in [`examples/auth`](../../examples/auth/README.md).
