# Harness Session Lifecycle Runtime Boundary

## Status

Status: implementation complete for integration into `lane/harness`.

## Purpose

`loushang.harness.session.lifecycle.SessionLifecycleRuntime` owns the generic
transaction that replaces one active Product session with another. It is
separate from `AgentTranscriptLifecycle`: the transcript lifecycle binds one
durable transcript, while this runtime coordinates which already-bound Product
session is active.

The runtime supports new, restore, fork, staged file import, externally built
replacement, and disposal. It composes the existing `SessionTransitionHost`
and `SessionOperationCoordinator`; it does not introduce a second lock,
replacement protocol, or transcript repository.

`AgentTranscriptSessionRuntime` is the optional Agent-transcript profile
facade above that transaction runtime. It joins `SessionLifecycleRuntime` with
`AgentTranscriptDirectoryRuntime`, exposing the standard active-session
operations and current session-reference resolution. It does not choose a
store, transcript binding, Product hooks, fork interpretation, or presentation.

## Harness Ownership

Harness owns:

- `SessionLifecycleTransition`, the neutral request context passed to Product
  hooks. It carries a lifecycle reason, opaque metadata, source/target session
  references, and fork request facts without interpreting Product payloads.
- `SessionLifecycleStore`, the Product-provided port for create, restore, fork,
  cwd/session references, and current leaf selection.
- `SessionLifecycleRuntime`, which serializes pre-transition cancellation,
  candidate construction, candidate preparation, release, activation,
  replacement callbacks, rollback, failure reporting, and final disposal.
- staged file import ownership and cleanup through the shared runtime staging
  helper.
- a conservative default `ForkProfile`: its default position is `at` and it
  supports only `at`.
- configurable `ForkProfile` and `ForkTargetResolver` injection. A Product can
  add positions and resolve them against its own tree/payload semantics.
- `resolve_fork_target`, which owns the reusable `at`/`before` grammar and
  parent-target selection while a Product supplies only its boundary predicate,
  parent accessor, and optional payload projection.
- the common missing-cwd decision shape: error by default, or a
  Product-selected fallback cwd when that policy is requested.
- one restore-candidate path shared by immediate restore and staged restore;
  cwd validation, fallback retry, and disposal of an invalid first candidate
  therefore cannot drift between the two publication modes.
- `PreparedSessionLifecycleOperation`, an unpublished-candidate lease whose
  abort is idempotent and whose consume succeeds at most once.
- `AgentTranscriptSessionRuntime`, which composes an already-configured
  lifecycle transaction with transcript directory/index operations. It owns no
  additional replacement state or lifecycle lock.

The default fork resolver merely selects the supplied record. It never reads a
message role, prompt, summary, branch, or Product tree payload.

## Product Binding Contract

A Product supplies a `SessionLifecycleStore` and `SessionLifecycleHooks` when
it assembles its runtime. The store can bind a file, database, remote, or
hybrid transcript/session provider; Harness owns no root, database connection,
Redis client, filename convention, or retention policy.

Hooks retain all Product effects:

- before-transition events and cancellation decisions;
- candidate preparation and runtime activation;
- shutdown events and Product-specific cleanup;
- post-commit callbacks, index updates, diagnostics, and UI/channel projection.

`metadata` is opaque to Harness. It lets a Product carry callback options,
diagnostic details, or channel-specific annotations without growing a shared
field for every Product concern.

Coding is the first profile. It configures:

```text
default fork position: before
supported positions:  before, at
```

Its resolver interprets `before` as “fork before a user-message record”,
returns the selected user text for Coding presentation, and rejects other
payload kinds. That interpretation, Coding extension events, session headers,
cwd/path policy, index policy, and JSON/RPC/TUI projection remain Coding code.
The normal Coding `fork_session`/clone APIs can still pass `at` explicitly.

## Ordering And Failure Rules

For a replace operation the runtime executes:

```text
lock
  -> Product before-transition decision
  -> Product store candidate
  -> Product candidate preparation
  -> Product before-release
  -> invalidate/dispose previous
  -> activate/rebind candidate
  -> Product after-commit effects
```

Fork target lookup, position validation, and target resolution happen while
the same transition lock is held. An overlapping new/restore/fork operation
cannot observe a cleared active slot or fork an entry selected by a different
transition.

Cancellation occurs before candidate creation. Candidate preparation or
replacement failure disposes the uncommitted candidate and cleans a copied
import file. A Product can report phase-aware failures through `on_failure`.
After-commit failure propagates after the new session is current, matching the
existing session-operation contract.

A prepared restore releases the transition lock after staging without
publishing its candidate. Consumption reacquires the same transaction lock and
commits only if the active session is still the session observed during
preparation. If another transition won first, the staged candidate is disposed
and consumption fails; repeated consume or abort calls cannot publish or
dispose it twice.

Unknown Product records and transcript replay are not lifecycle concerns; they
remain with `harness.conversation` and optional transcript profiles.

## Dependency Rules

`harness.session.lifecycle` may import Harness runtime primitives only. It
must not import Agent, AI, Coding, another Product, storage implementations,
extensions, Work, Method, or UI. It is therefore suitable for a Product whose
session object is not an Agent session.

`harness.session.transcript_lifecycle` may depend on the neutral lifecycle
runtime and the optional Agent transcript directory profile, but must not
depend on Coding or another Product. The facade is deliberately not placed in
`harness.transcript`: directory/catalog ownership alone does not imply
ownership of active-session replacement.

`loushang.harness.session` remains an optional profile package and is not
exported from top-level `loushang.harness.__all__`.

## Verification

Harness tests use opaque fake sessions to prove the default `at` profile,
Product-supplied `before` profile/resolver, cancellation, cwd fallback, and
failure isolation. They also lock the prepare/release/activate/commit order,
staged-restore cancellation, stale-candidate rollback, and one-shot consume
state. Coding characterization tests cover the configured
`before`/`at` behavior, extension cancellation/events, import races, cwd
fallback, callback order, diagnostics, and serialized replacements.

The migration is complete only while `harness.session.lifecycle` has no
Product import, `harness.session.transcript_lifecycle` has no Coding import,
Coding delegates active-session transactions and directory-backed operations
to these runtimes, and focused plus full non-live tests pass.
