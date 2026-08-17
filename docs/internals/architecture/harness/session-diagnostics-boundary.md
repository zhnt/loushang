# Session Diagnostics Runtime Boundary

## Decision

`loushang.harness.session.SessionDiagnosticsRuntime` owns common
session-correlated diagnostic reads and Agent/Tool failure projection. It uses
the Harness diagnostics service and only receives a current
`SessionDiagnosticScope` plus an optional `ExtensionDiagnosticsPort` from the
Product.

The runtime provides:

- session-filtered diagnostic records, summaries, and latest error reports;
- correlation of runtime exceptions, failed assistant responses, and failed
  tool executions to the current session and transcript entry;
- policy-denial diagnostics projected from tool event details; and
- once-only synchronization of extension resource diagnostics.

It does not own diagnostic storage, extension loading, transcript persistence,
Product diagnostic wording, command/resource diagnostics, or UI/RPC payload
projection.

## Product Binding

A Product supplies a scope provider that reads its active transcript's stable
session and leaf entry identifiers. It may supply an extension diagnostics
port; no particular extension runner class is required. Products also choose
which product-specific failures to record and how to render or serialize
diagnostic records.

## Coding Binding

Coding `AgentSession` binds its current transcript header/leaf as the scope
and its extension runner as the optional diagnostics port. Coding retains
model/auth, command, resource, package, extension-hook, and presentation
diagnostics. The former `coding.session.session_diagnostics_bridge` is removed;
there is no parallel Coding session-diagnostics implementation.

## Dependency Rule

`harness.session.diagnostics` may depend on Harness diagnostics/resources,
stable Agent tool-result projection, and AI assistant message values. It must
not import Coding, a Product transcript/store type, a concrete extension
runner, Product configuration, or UI/RPC/HTML types. Products bind those
objects through the scope and diagnostics ports.

## Verification

- Independent Harness tests bind synthetic scopes and extension diagnostics,
  proving no Coding runtime is necessary.
- Coding AgentSession regressions retain its public session diagnostics API.
- Architecture tests forbid Coding imports in the runtime, require the Coding
  binding, and forbid reintroducing the old Coding bridge.
