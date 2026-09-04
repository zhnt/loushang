# ARD-002: Hosting Top-Level Placement And Scope

## Status

- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — accepted cross-scope Hosting placement decision
- Design status: accepted
- Implementation status: partial
- Owner: Loushang architecture and Hosting architecture
- Date: 2026-09-04
- Accepted: 2026-09-04 after five-view baseline review and H0 entry review

## Context

Harness currently contains reusable local process mechanics alongside the
Policy, Approval, Authorization, Sandbox, Worker, Plugin, Capability, and
Product-adapter semantics that consume them. PLC9C1–PLC9C4 made the distinction
visible: process lifetime, inherited peer-endpoint lifetime, Worker protocol lifetime,
and domain publication lifetime are separate authorities.

Keeping every OS-facing mechanism inside Harness is viable for the current
single consumer, but it makes the neutral mechanism appear to own Harness
security/domain meaning and makes future trusted hosts depend on Harness for a
process/IPC primitive. Moving it to Foundation would instead place stateful OS
side effects beneath a package intended for small pure foundations.

The decision must separate three questions:

1. What Architecture Scope owns the mechanism?
2. What Python import package carries it?
3. When, if ever, should it become a separately distributed project?

## Decision

### 1. Establish `hosting` as a top-level Architecture Scope

Hosting owns bounded local process, inherited peer endpoint, and joint child-session
lifetime. It is a sibling consumed initially by Harness:

```text
Harness -> Hosting -> local OS
Hosting -/-> Harness
```

The scope qualifies for promotion because it owns independent lifecycle,
state, portability, trust-boundary mechanics, failures, required/provided
ports, several stable components, and a separate conformance surface.

### 2. Use the import package name `loushang.hosting`

`hosting` names the responsibility without claiming that process is the only
resource or that it owns Product runtime semantics.

The names `loushang.plugin`, `loushang.process`, and `loushang.runtime` are not
used:

- `plugin` would confuse OS hosting with Plugin declarations, author SDK, and
  domain publication;
- `process` is too narrow once inherited peer endpoint and atomic child-session
  ownership are included;
- `runtime` collides with several existing runtime owners and suggests a
  universal kernel.

### 3. Keep one distribution initially

H0 adds a top-level import package to the existing `loushang` distribution. It
does not publish `loushang-hosting` as a separate distribution.

Distribution extraction requires a second real independent consumer, a stable
public specification, dependency/versioning evidence, and a separate packaging
ARD. A hypothetical future consumer is not sufficient.

### 4. Keep security and domain authority outside Hosting

Hosting performs the final local OS operation but does not decide whether it is
allowed. Harness retains Policy, Approval, Authorization, Sandbox meaning,
Worker protocol/supervision, Plugin/Capability admission, and domain
publication. Hosting receives exact material and a narrow preparation lease;
its observations never certify those caller-owned meanings.

### 5. Make process plus inherited peer endpoint one atomic optional aggregate

Process hosting remains independently usable. A Child Session Host composes a
process with an inherited peer endpoint when needed and returns both or neither. Worker
protocol is a consumer of that byte channel, not a Hosting component.

### 6. Migrate through compatibility facades

Current Harness process contracts and behavior remain in place while neutral
mechanics move by dependency-safe slices. A native Worker activation is a
later, separate change; extraction alone cannot remove PLC9C default-dark
guards.

## Alternatives Considered

### Keep all mechanics inside Harness

Rejected as the target placement because it obscures the mechanism/meaning
boundary and forces future trusted hosts through Harness. It remains the
Current implementation until migration evidence exists.

### Move mechanics into Foundation

Rejected. Process creation, handle inheritance, cancellation, and cleanup own
mutable OS lifecycle and platform failures; they are not a small pure value or
cross-system utility foundation.

### Put the mechanism in `loushang.plugin`

Rejected. The current package is an author/inspection surface over Plugin
semantics. Giving it process/IPC ownership would blur declaration, authority,
hosting, and publication, and could imply that author code receives a launcher.

### Adopt a generic go-plugin-style client as the boundary

Rejected as the scope definition. The useful lesson is one owner for process,
connection, and cleanup. Stdout address discovery, TCP-first transport,
protocol handshake, magic-cookie checks, and reattach semantics are not
Hosting invariants and do not replace Loushang Policy/Sandbox/domain owners.

### Publish a separate distribution immediately

Rejected until independent demand proves that release cadence, dependency
budget, compatibility surface, and packaging cost are justified.

## Consequences

### Positive

- OS resource truth gains one explicit neutral owner.
- Harness authority remains explicit while reusing a smaller mechanism.
- process, endpoint, protocol, and domain lifetimes can fail independently
  without synthesizing one another's evidence.
- platform conformance and cancellation cleanup become independently testable.
- a future trusted host can reuse the substrate without importing Harness.

### Costs and risks

- migration temporarily requires compatibility facades and two documented
  locations for Current versus Target.
- an early public surface could freeze platform details, so concrete backends
  and raw handles must remain private.
- only Harness currently consumes the mechanics; the accepted scope must keep
  earning its boundary through lifecycle/conformance evidence rather than
  speculative reuse.
- Hosting cannot enforce Harness policy by itself. Security claims remain valid
  only at the Harness composition boundary and must have their own gates.

## Acceptance And Supersession

This decision is accepted for phased implementation. The architecture baseline
received independent architecture/ownership, security/lifecycle,
resources/sessions, process-lifecycle, and documentation/test review before H0.
H0 updates the Loushang AOD, subsystem map, governance scope tree, dependency
gates, and gap ledger while implementing only the standard-library contract
model.

Acceptance does not claim that Process Lifetime Host, Inherited Peer Endpoint
Host, Child Session Host, platform adapters, AppHost, or AppServer are
implemented. Those remain explicit later slices.

No existing accepted Harness decision is superseded by this proposal. The
Harness Process Hosting and PLC9C documents continue to govern Current behavior
until a migration decision explicitly revises them.

## References

- [Hosting Scope](../hosting/README.md)
- [Requirements](../hosting/requirements.md)
- [System Context](../hosting/system-context.md)
- [Component Model](../hosting/component-model.md)
- [Harness Process Hosting Boundary](../harness/process-hosting-boundary.md)
- [PLC9C Local Worker Boundary](../harness/plugin/plugin-lifecycle-plc9c0-baseline.md)
- [HashiCorp go-plugin](https://github.com/hashicorp/go-plugin)
- [Nomad Plugin Authoring](https://developer.hashicorp.com/nomad/plugins/author)
