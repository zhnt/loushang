# ARD-003: AppHost Top-Level Placement And Contract Boundary

## Status

- Scope: `apphost`
- Parent: `loushang`
- Authority: normative — accepted cross-scope AppHost placement decision
- Design status: accepted
- Implementation status: partial
- Owner: Loushang architecture and AppHost architecture
- Date: 2026-09-05
- Accepted: 2026-09-05 after A0.0 parent and neighboring-scope review

## Context

Product-specific entrypoints currently assemble Product selection, Harness
runtime construction, presentation, and final disposal. The Product glossary
already names one logical Platform Host, but no physical owner provides a
cross-Product catalog, explicit routing, scoped Product Runtime lifetime, or
deployment-profile composition. Placing that responsibility in Harness would
make the reusable execution substrate own Product topology. Placing it in
Coding would make peer Products depend on the first Product.

Hosting H0--H6.4 now supplies Product-neutral local process and child-session
mechanics. It deliberately does not select Products, interpret Sessions, or
own application protocol. AppServer and AppService remain separate proposed
siblings for transport and hosted semantic coordination. The missing owner is
therefore a process-local Product composition root, not another execution,
transport, persistence, or OS-hosting subsystem.

## Decision

### 1. Establish `apphost` as a top-level Architecture Scope

AppHost is the physical owner of the existing logical Platform Host role. It
owns an admitted immutable Product catalog, explicit Product routing,
canonical per-Session Product Runtime bindings, deployment-profile selection,
and process-level shutdown ordering.

```text
Product packages -> AppHost contracts
AppHost -> Harness public Product/runtime mechanisms
AppHost core -/-> concrete Products / AppServer / Hosting / UI frameworks

optional apphost.hosted -> AppServer structural Product ports
optional apphost.launcher -> Hosting serialized process contracts
```

Every create, open, resume, or migration request reaching AppHost identifies a
Product explicitly. OEM or client configuration may choose that value before
the call; AppHost has no implicit Product fallback.

### 2. Keep Product identity orthogonal to delivery profile

A Product descriptor/factory identifies domain semantics. A Host/Presentation
Profile Plugin identifies an admitted delivery form such as embedded TUI,
desktop, WebUI, or remote client. Several profiles may bind one Product and one
profile may support several Products without changing Product identity.

### 3. Reuse the canonical Session and Harness owners

AppHost consumes a path-free, bounded Session identity/catalog port. The
canonical Session owner atomically persists a generic Session Identity
Envelope; Harness discovery adapters select cwd and user-global sources and
retain their exact revisions. AppHost neither derives roots nor opens Session
files. For create, the canonical Session owner mints and atomically establishes
the generic identity from an explicit Product request. For create or resume, a
Product-owned candidate validator receives only a finally claimed opaque
candidate before its factory runs. Legacy import is explicit, copy-first,
Product-owned, and never mutates its source.

### 4. Own one canonical live binding, not Product internals

The future live registry owns one scoped Product Runtime binding per
`(product_id, continuity_id, session_id)`. Concurrent profile or named-mux
attachments share it through leases. AppHost does not rebuild Capability,
Plugin, Resource, Transcript, Work, or Product runtime graphs; the Product
factory composes established owners and returns a narrow scoped handle.

### 5. Keep optional hosted and process edges outside core

AppHost core imports neither AppServer nor Hosting. A hosted binder may consume
AppServer structural Product ports, and an outer launcher may consume only
serialized Hosting contracts. Python factories, runtime handles, Session
locators, and AppService objects never cross a process boundary.

### 6. Enter implementation through A0 slices

- A0.1 implements only the standard-library Contract Model and immutable
  catalog input validation.
- A0.2 may add catalog/router, exact subject-bound admission-pin verification,
  idempotent create and injected Session candidate routing, and explicit
  importer behavior over unrelated fakes.
- A0.3 may add the canonical live-binding lifecycle and embedded profile.
- A0.4/A0.5 hosted and launcher adapters remain separately accepted optional
  edges.

No A0 slice activates the PLC9C5 native Worker route. Product/native Worker
activation remains an independently reviewed Product/Harness decision and all
new AppHost paths remain uncomposed until their own exit gate passes.

## Alternatives Considered

### Place AppHost in `loushang.harness`

Rejected. Harness owns reusable single-Product mechanisms, not the
cross-Product catalog, OEM admission topology, or deployment profile.

### Create `loushang.harnesshost`

Rejected. It collides with `loushang.harness.host` and still assigns Product
topology to the wrong owner.

### Place it in Coding or another Product

Rejected. Coding, PPT, Design, Research, Cowork, and OEM Products are peers.

### Merge it with AppServer or AppService

Rejected. Product routing/runtime lifetime, transport/connection lifetime, and
hosted semantic coordination have distinct actors, failure modes, and
dependencies. Optional adapters may compose them without collapsing ownership.

### Merge it with Hosting

Rejected. Hosting owns local OS mechanism facts; AppHost owns Product meaning
and application-process composition. The target process can also run directly
without a Hosting controller.

## Consequences

### Positive

- one neutral owner can route multiple Product packages without importing them;
- embedded use does not acquire AppServer or Hosting dependencies;
- Session resume chooses Product before invoking Product-specific parsing;
- profile and named-mux attachment cannot duplicate Product Runtime ownership;
- optional hosted and launcher edges remain replaceable boundary adapters.

### Costs and risks

- a new top-level package and architecture scope must be maintained;
- catalog generation, candidate revision, attachment, and shutdown races need
  explicit lifecycle evidence before A0.2/A0.3;
- Product registration is trusted process-local composition, not import-time
  discovery, so outer composition remains responsible for admission;
- AppHost cannot infer successful Product cleanup from process exit or infer
  process containment from Product readiness.

## Acceptance And Supersession

This decision accepts the top-level placement, the A0 Contract Model boundary,
and the dependency direction above. It supersedes the placement status of the
draft AppHost proposal but retains that document and component-discovery record
as supporting design history.

Acceptance does not claim that catalog/router, live-binding lifecycle,
AppServer, AppService, hosted profiles, launchers, or PLC9C5 activation are
implemented. A0.1 is the only accepted implementation entry slice.

## References

- [AppHost Scope](../apphost/README.md)
- [A0 Contract Model](../apphost/contract-model-a0.md)
- [Hosted Product Runtime V1 Plan](../drafts/hosted-product-runtime-v1-plan.md)
- [AppHost Component Discovery](../drafts/apphost-component-discovery-a0.md)
- [Hosting Placement](ARD-002-hosting-top-level-placement.md)
- [Product And Platform Host Glossary](../../glossary/loushang-product.md)
