# ARD-006: Keep Hosted Resume Readiness Inside One Product Binding

## Status

- ID: `ARD-006`
- Scope: Loushang cross-scope Coding, AppHost, AppService, AppServer, and HarnessTUI
- Parent: Loushang architecture
- Authority: normative — accepted Hosted Resume readiness and admission boundary
- Design status: accepted
- Implementation status: not-started
- Owner: Loushang architecture and the affected Product/host/service owners
- Tracking: [Issue #696](https://github.com/zhnt/loushang/issues/696)

## Decision Question And Drivers

How can a Hosted or LMUX client display a persisted Coding Session before its
current execution environment is ready, while two clients, reconnects, and
service restarts continue to use one canonical Session authority?

The [R2.1 design](../../../plans/2026-10-12-resume-compatibility-and-activation-design.md)
requires Embedded and Hosted to share compatibility and continuation semantics
within their identity scope (RES-FR-04), and requires read-only opening to
produce no authority effect (RES-NFR-01). A pending input must retain its
target Session and payload during preparation, failure, switch, and retry.

Current `apphost/runtime.py` owns canonical process-local live bindings;
`appservice/execution_registry.py` owns accepted executions and a bounded
service-instance submission ledger. `appservice/runtime.py` returns `AckV1`
from `start_turn`; Coding's Product turn port currently returns `None` after
the original operation. `coding/hosted_catalog.py` requires canonical Hosted
identity and does not implicitly adopt ordinary Embedded files. These are
source-current facts, not an existing background activation queue.

## Options And Comparison

| Option | Fit against drivers | Costs and risks |
| --- | --- | --- |
| Build a second preparatory registry or queue in AppService | Can expose a preparing state | Splits Session and execution ownership; detach, close, and takeover become ambiguous. |
| Fully activate the Product during discovery | Reuses present binding behavior | Viewing history can import plugin code, acquire resources, or start a Worker. |
| Put a continuity/readiness facade inside the one Product binding | Keeps AppHost identity and existing execution owner | Requires a narrow Product port, old-client negotiation, and durable input lookup before hosted retry. |

## Decision And Exact Scope

Select the third option. AppHost creates
or attaches exactly one canonical live binding for a given Product continuity
identity. A new persisted Session's binding may initially expose Product
identity, read-only history snapshot, readiness status, subscription, and
close, while its execution runtime remains unactivated. Two concurrent clients
await the same scoped factory task. Preparation and later activation are
internal states of that same binding; they do not replace its key, generation,
attachment identity, or final close owner.

AppService consumes a narrow Product projection with history verification,
activation readiness, pending/committed input facts, typed reason codes, and
stable-ID lookup. It retains controller, attachment, and execution admission
ownership and does not import Coding plans, Harness planners, or plugin graph
internals. AppServer owns framing and transport only. Existing live Sessions
attach or reconnect; they do not repeat disk Resume. A client detach does not
itself close the server-side Product Session.

The execution registry retains its `ACCEPTED` and terminal-state ownership.
Preparing is a Product substate, not proof that a message was committed or a
model call started. An Ack-only old client keeps its original operation
completion and error timing; no earlier Ack is reinterpreted as a durable
commit acknowledgement. If a confirmation or retry contract cannot be
represented for that client, admission returns a typed unsupported reason.

The Session snapshot therefore carries a typed submission mode. `legacy` is
the default and retains the original App v1 wire shape; ordinary Sessions keep
their existing `start_turn` path and client-side immediate draft clearing even
when the connection also negotiated execution. A deferred or read-only Resume
binding emits the optional `submissionMode: execution` field only through an
explicit execution profile. A capable client then submits directly through
the stable execution ledger and clears the exact draft only after acceptance.
An older strict decoder fails closed on that new Resume-only snapshot instead
of treating a long-running legacy Ack as stable admission. Platforms outside
the admitted history-first Writer boundary retain their existing legacy same-ID
Hosted recovery and legacy snapshot mode.

New clients generate a stable logical input ID and keep the frozen text until
the Product reports a durable result. Reconnection first queries the Product
authority store for that ID and its model attempt, under current read
authorization. The lookup returns `committed`, `not_committed_verified`,
`unknown`, or `conflict`; service-instance change, missing in-memory ledger,
or unfinished scan cannot imply absence. Only verified absence with unchanged
target ancestry allows re-admission of the same input. Controller takeover
fences mutation by the old controller; the new authorized controller explicitly
queries or settles accepted work.

Client view target and execution target are distinct. Previewing B does not
redirect A's running turn. Pending text belongs to B and remains visibly
unsent; returning to A before B's commit may cancel that pending input under
its lifecycle owner. After B's commit, returning to A changes presentation
only. Snapshot and event projection preserve target Session and generation
fences through A→B→A, detach, reconnect, and failure. A failed `/resume`
candidate keeps the prior active Session and its text ownership.

Hosted same-ID writable continuation requires canonical Hosted identity.
Product-known ordinary Embedded files without that identity may be shown as
readable migration candidates, but this decision does not implicitly adopt
them. Product-unknown or conflicting files are never guessed to be Coding.

## Release Boundary, Validation, And Acceptance

Hosted writable current requires the Embedded continuation safety gates,
canonical continuity facade, negotiated old/new client behavior, Product
durable lookup, controller fencing, and restart recovery together. A
read-only Hosted projection can release separately if it has no Writer,
third-party import, Worker launch, or authority journal write. A mere new
`preparing` label is not the Hosted writable slice.

Required evidence includes two clients sharing one factory/binding, attach
during preparation, detach and final close, generation retirement, controller
takeover, lost Ack, service restart, same-ID retry, A→B→A editor ownership,
and old Ack completion/error timing. The [R2.1 review](../../../plans/2026-10-12-resume-compatibility-and-activation-review.md)
closed the design's Ack wording ambiguity but did not test the protocol or
accept this cross-scope contract.

On 2026-10-12, the project owner explicitly accepted ARD-004, ARD-005, and
ARD-006 in the #696 implementation session with “接受，继续”. This records
the common-parent acceptance for Coding, AppHost, AppService, AppServer, and
HarnessTUI of the one-binding facade, narrow readiness and durable-lookup port,
state vocabulary, unchanged old-Ack timing, and identity-limited release scope
specified here. Concrete port schemas must conform to these boundaries.

Implementation may proceed; Hosted release still requires the Embedded gates,
negotiation, controller, restart, and multi-client evidence listed above.
Neither this acceptance nor the R2.1 design review proves delivery.
