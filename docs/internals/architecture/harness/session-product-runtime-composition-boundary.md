# Session Product Runtime Composition Boundary

## Status

Implementation complete for integration into `lane/harness`.

## Purpose

`harness.session.ProductSessionRuntime` is the common composition adapter for
Agent-like Products that need one active transcript-backed session. It joins
the existing `SessionLifecycleRuntime`, `AgentTranscriptSessionRuntime`, and
`SessionLifecycleOperationAdapter`; it does not create a second session
engine, lifecycle lock, transcript repository, or operation grammar.

The adapter makes the ownership transfer explicit. A Product supplies a
`ProductSessionRuntimePorts` value and keeps only the policy and effects that
cannot be made neutral.

## Harness Ownership

Harness owns the composition and delegation for:

- new, restore, fork, import, replacement, and disposal operation wiring;
- transcript directory/index access supplied by the existing Agent transcript
  profile;
- common operation results, lifecycle phases, callback ordering, and failure
  routing;
- generic session rename/delete delegation when a Product exposes those
  transcript operations;
- common after-commit index scheduling, replacement callbacks, and
  restore/import failure routing;
- the standard `ProductTranscriptSession` create/open/fork/dispose binding,
  without selecting a concrete Product transcript subclass;
- current-session, session-reference, cwd, and leaf-entry lookup through
  typed Product ports;
- generic `resolve_fork_target` position grammar and parent-target selection,
  with Product-supplied boundary and payload callbacks;
- reflection-only helpers for invoking an optional lifecycle event, resolving
  an import cwd, emitting shutdown, and disposing a bound session.

All algorithms remain in the established lifecycle, transcript, and operation
runtimes. `ProductSessionRuntime` is a thin owner boundary, not a replacement
for any of them.

## Product Binding Contract

`ProductSessionRuntimePorts` supplies transcript create/restore/fork/dispose
callbacks, the Product session builder and optional validator, transcript-to-
session identity/cwd/reference/leaf lookup, a fork profile and target
resolver, lifecycle hooks, optional diagnostics/index callbacks, optional
rename/delete callbacks, and Product import-cwd/error translation.

The ports contain no Coding, UI, provider, or wire-schema concepts. A file,
database, remote, or hybrid transcript store can implement them without
changing the Harness runtime. A Product may select a different fork profile,
lifecycle policy, diagnostics scope, or presentation adapter.

Fork, transcript lifecycle, cwd handling, diagnostics, and extension
lifecycle are all reusable capabilities. Harness owns their algorithms and
contracts. `ProductTranscriptSessionBinding` adapts a Product-selected
transcript subclass to the existing lifecycle store, while
`build_agent_session_lifecycle_hooks` binds the existing Agent session adapter
to approval, extension, shutdown, and disposal effects. Neither introduces a
new runtime or transaction owner.

Coding now supplies only its transcript subclass, fork default profile,
public missing-cwd error adapter, session factory event, diagnostic service,
model/auth policy, and Product presentation. Standard Agent message fork
projection, lifecycle effects, and diagnostic routing are shared behavior.

## Dependency Rules

`harness.session.product_runtime` may import Harness session/runtime modules
and the optional Agent transcript profile. It must not import Coding, another
Product, UI, Channel, Work, or Method. The profile is generic over the Product
session, transcript, and fork payload types.

Products may depend on this adapter and on lower-level Harness contracts. They
must not retain a parallel lifecycle or transcript-directory engine once the
adapter is adopted.

## Verification

`tests/harness/session/test_product_runtime.py` composes the adapter with
opaque fake Product types and verifies create, fork, current-session, and
dispose behavior. Coding characterization tests cover the existing manager,
cwd, fork, diagnostics, extension, import, and index behavior after binding
the adapter. Architecture tests require Coding to import
`ProductSessionRuntime`/`ProductSessionRuntimePorts` and prohibit the old
direct-base ownership assertion.
