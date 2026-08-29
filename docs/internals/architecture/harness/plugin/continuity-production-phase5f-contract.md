# Continuity Production Composition and Operations (Phase 5F)

## Status and scope

Phase 5F makes the Phase 5C–5E installed Continuity lifecycle reachable from
the real Coding Product. The implementation lives at the Product composition
edge in `loushang.coding.continuity_bootstrap`; reusable selection, approval,
Instance, mutation, recovery, and Hub mechanisms remain in Harness.

The phase covers five production obligations:

1. configured-source resolution and exact Product policy;
2. durable installed-state and Instance binding;
3. pre-session `--resume` and in-session TUI composition;
4. startup recovery, finite redacted status, and explicit retry;
5. shutdown ownership and end-to-end tests over a real Plugin package.

## Authority and dependency direction

An enabled `plugin_sources` entry is Coding's explicit Product opt-in. It does
not register a callback or become a Provider directly. A source containing a
`continuity_provider` contribution traverses the complete chain:

```text
Coding settings
  -> inspect mutable source
  -> publish immutable Plugin revision and durable source binding
  -> PluginManagementService desired state
  -> PluginInstanceRuntimeLedger ACTIVE revision
  -> finalized PluginSelection
  -> Product-owned definition approval
  -> Continuity owner admission and selection
  -> Product-owned activation approval
  -> exact Instance owner-generation family
  -> stable semantic recovery binding
  -> deletion recovery publication barrier
  -> stable Continuity Hub reference
```

Harness never reads Coding settings or chooses Product policy. Coding never
constructs a Provider from a raw module or bypasses owner admission.
`continuity_bootstrap` is the sole Coding module allowed to mount the private
owner-component foundation; architecture tests keep that exception explicit
and prevent it from spreading through Product code.

Only `network.read` and `continuity.delete` are in the Phase 5F authority
ceiling. A configured Continuity declaration outside that ceiling fails closed.
Disabled Plugins and packages without Continuity contributions remain outside
this owner. For a mixed Plugin package, this edge projects only
`continuity_provider` contributions; optional sibling tool, prompt, resource,
command, or capability contributions remain inert until their own Product
owner selects them. A package that marks a cross-owner sibling required is
rejected by exact preflight instead of letting the Continuity edge approve or
execute it.

## Durable layout

Product state is machine state, not user data, CWD scratch, or a Session file:

```text
<platform.state>/plugins/coding/continuity/workspaces/<sha256(canonical-cwd)>
  desired-state.jsonl
  management-operations.jsonl
  retirement-intents.jsonl
  retirement-sets.jsonl
  instance-runtime.jsonl
  instance-runtime.continuity-deletions.jsonl
  instance-runtime.security-acceptances.jsonl
  package-lifecycle.jsonl
  definition-decisions.jsonl
  activation-decisions.jsonl
```

The directory name does not disclose the workspace path. Every
application-owned state ancestor from the platform state/home boundary through
the workspace root is created or tightened to `0700`, with owner, identity, and
symlink checks at each component. `plugins.state` is visible in
machine-resource status, but generic cleanup never owns it; only Plugin
lifecycle authorities may retire its records or packages.

Portable activation payloads are staged separately under the workspace-hashed
`<platform.temporary>/continuity-import/` namespace. Coding tightens the
application-owned runtime and temporary roots to `0700`; the payload never
enters durable state or the workspace. Phase 5F portable staging requires the
POSIX directory-handle operations used by the secure importer. A platform that
cannot provide them fails during bootstrap with the finite
`coding_continuity_secure_staging_unsupported` code, before Plugin import or a
user selection; it does not defer an unavoidable failure to activation time.

Remote configured sources are never fetched as a resume side effect. They are
eligible only after the existing Package materializer has an installed record.

## Publication, recovery, and retry

Definition and activation approval occur before Plugin code is published as a
Provider. Owner admission and executable activation decisions are short-lived;
cross-process recovery relies on the stable semantic recovery fingerprint, not
an artificially permanent admission. Installed deletion recovery remains the
asynchronous publication barrier from Phase 5E: an accepted deletion must
settle before any Hub reference is observable.

Bootstrap failure publishes no replacement Hub. Durable ACTIVE Instance roots
remain retryable state rather than being rolled back as process leases. The
Product records only a stable code, finite counts, state, and retryability; it
omits source paths, journal contents, Plugin exceptions, payloads, and
credentials. The same bind operation is the manual retry boundary and is
exported as `retry_coding_continuity_bootstrap`. A clean failure closes immutable
revision handles before returning. Diagnostic publication is best effort and
cannot turn a successfully published composition into a startup failure.

## Resume and TUI ownership

Pre-session `--resume` binds the configured composition before listing
sessions, so Product and installed Provider sessions appear through one Hub.
The interactive screen path performs the same asynchronous bootstrap when no
pre-session picker ran. A process-sealed composition carries a redacted digest
of its exact source, disabled-set, workspace, listing-scope, and Product-policy
request. Exact reentry is idempotent; a different request is rejected instead
of silently reusing it. After pre-session activation, the main TUI reuses that
process composition even when the restored session changes the active CWD.
`ScreenSurfaceManager` receives a stable reference; it does not resolve
Plugins, recover journals, or construct a Hub synchronously.

The screen host owns and releases its reference. The Coding session runtime
owns the process composition. Runtime disposal closes the Hub/generation,
joins work, releases exact owner-generation families, disposes the base Runtime
Profile binding, and finally closes immutable revision handles. The durable
direct-host family remains the installed ACTIVE Instance root until Plugin
retirement; it is not a per-process bootstrap lease. Cleanup is idempotent and
retryable after partial failure.

## Deliberate non-goals

Phase 5F does not add background retry, automatic remote installation, hot
replacement, cross-process Provider execution, archive/rename/sync mutations,
or generic deletion of Plugin state. A changed configured revision is rejected
as `coding_continuity_plugin_revision_not_selected` and is not retryable until
the source is restored to the selected immutable revision. Accepting a new
revision requires a later Plugin Management Product projection; Phase 5F does
not advertise a CLI, RPC, TUI, or SDK update operation, and process restart
alone does not mutate desired state.

## Exit gate

The phase is complete when tests prove canonical/redacted layout, base-only
compatibility, real configured Plugin query/preview/activation/delete,
pre-session and TUI reference injection, recovery before publication, retry
after failure, shutdown/revision cleanup, secure-staging capability failure,
mixed-package owner isolation, exact reentry, private state ancestors, and
stable redacted best-effort diagnostics; the full non-live repository gate must
pass.
