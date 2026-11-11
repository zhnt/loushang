# Product Transcript Session Boundary

## Status

Implemented on `harness/session-adapter-collapse`.

## Purpose

`loushang.harness.transcript.ProductTranscriptSession` is the reusable
Product-facing wrapper around a bound `AgentTranscriptLifecycleSession`. It
owns the repetitive session surface shared by Coding, Research, Design, PPT,
and OEM-defined Products:

- create, open, load, recent-resume, in-memory, and selected-path fork;
- current transcript metadata, records, context, tree, labels, diagnostics,
  catalog queries, index refresh, rename, and delete; and
- disposal of the Product runtime binding after the transcript operation ends.

It delegates Native file assembly to `AgentTranscriptSessionFactory` and does
not introduce another repository, store, replay, or transcript schema.

## Product Binding

A Product subclass supplies exactly two decisions:

1. its bound `AgentTranscriptSessionFactory`; and
2. the immutable binding input used when a selected transcript path is forked.

The Harness class has no model registry, auth, prompts, tool policy, extension
policy, UI, or Coding import. Products retain those choices in their runtime
profile and session assembly.

Coding's `SessionManager` selects the Coding runtime/capability profile,
validates restored headers, exposes Coding runtime capabilities, and retains
Coding wire, Plan/composition and current-admission policy. Its local continuation
program now selects the private opt-in Transcript profile described below;
that profile inherits the same `ProductTranscriptSession`. This bounded change
does not make every remaining Coding adapter a thin or completed migration.

## Standard Session Contract

The active Coding session and runtime use snake_case APIs. The core no longer
provides Pi SDK aliases such as `getAllTools`, `newSession`, `switchSession`,
or `sendMessage`. Equivalent capabilities remain available through
`get_all_tool_infos`, `new_session`, `restore_session`, `send_message`, and
the explicit `*_operation` methods that return a Harness
`SessionOperationResult` when replacement callbacks are required.

This is an intentional source compatibility break. Coding RPC remains a
Product transport projection and may keep its existing wire fields. TUI UI
namespace naming is a separate presentation-contract migration and is not
changed by this boundary.

## Verification

- Harness tests exercise a Product subclass through create, append, context,
  catalog/index, fork, rename, and runtime-binding disposal.
- Coding `SessionManager` and session/runtime tests exercise the same path
  through the Coding profile binding.
- Architecture tests require `ProductTranscriptSession` to have no Coding
  import and require `SessionManager` to adopt it.


## Opt-in Resume Continuation Profile

The internal [continuation profile](../../../../src/loushang/harness/transcript/_resume_continuation.py)
owns the fixed local intent/stage/commit/unknown/publication-fence and historical
guard program on the original Product Session object. It uses the same lifecycle,
TranscriptCommitter, artifact-aware prebuilt-message commit and authoritative
lookup. It creates no Writer, journal, queue, task or proof cache alongside the
original state. The standard `ProductTranscriptSession` defaults and physical
commit/lookup implementation remain unchanged.

A Product explicitly supplies message/record codecs, its existing history
classifier, the actual pending-record class and error/label bindings. Logical
views borrow original identities and opaque Plan fingerprints; they are not
Transcript wire schemas and confer no current owner admission, execution
readiness, effect settlement or retry permission. Code retains exact V1/V2
types, canonical metadata/hash namespaces, binding identity checks, Plan/source/
owner/composition policy, neutral-record classification and runtime publication.
The ordinary-input policy runs after staged-input dispatch and the unsettled
guard, before ordinary append, at the original point.

Coding keeps its original public class and real dataclasses/fields/slots. Ten
non-dataclass private default states are defined only in the opt-in profile and
use the original instance attributes; private own-annotations, defining method
module and MRO change. The original imported `ProductTranscriptSession` class
binding remains available for compatibility and fault probes, with the actual
Core class identity. No alias replaces a Code data class.

The bounded implementation and exact checks are recorded in
[KD009 §19](key-designs/startup-session-assembly-convergence.md#19-a58恢复首输入提交与发布边界的完整候选).
Finite recovery regressions do not prove every cancellation interleaving,
physical failure, private reflection/method-pickle ABI or performance bound.
