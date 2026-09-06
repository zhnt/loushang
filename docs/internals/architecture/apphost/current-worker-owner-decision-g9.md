# G9.3 Current Worker Owner Decision

[Architecture](../README.md) ·
[AppHost](README.md) ·
[G9 V1 Closure](hosted-product-v1-closure-g9.md) ·
[Entrypoint Inventory](hosted-product-g9-entrypoint-inventory.json)

## Status

- ID: `HOSTED-PRODUCT-G9-CURRENT-OWNER`
- Scope: `loushang / AppHost / Product / Harness Worker`
- Parent: `HOSTED-PRODUCT-G9`
- Authority: normative accepted decision
- Design status: accepted
- Implementation status: implemented
- Conclusion: `RETAIN`
- Activation status: unchanged — omitted Worker owner remains Current
- Effect: retention and promotion policy only; no runtime activation or source
  deletion
- Owner: Loushang architecture with AppHost, Product, Harness, and Hosting
  boundary review

## Decision

The G9.3 conclusion is exactly `RETAIN`.

Current remains the compatibility owner and the omitted-owner default. The
explicit Coding/AppHost composition remains available only to a typed caller;
no installed CLI, TUI, SDK, AppServer, hosted, or mux entrypoint selects it.
This is a successful G9 decision and permits the separately controlled G9.4
capability promotion to `main`.

The conclusion follows the accepted fail-closed rule: a `DELETE` conclusion is
admissible only when all eight deletion conditions are proven on the deletion
change. At least one false or unknown condition requires `RETAIN`; several are
currently false.

## Source-Backed Entrypoint Disposition

The canonical machine-readable inventory is
[`hosted-product-g9-entrypoint-inventory.json`](hosted-product-g9-entrypoint-inventory.json).
It is checked against `pyproject.toml`, the named source modules, AST imports,
and the absence of AppServer, hosted, and mux runtime launchers.

| Surface | Current disposition | Consequence |
| --- | --- | --- |
| installed Coding CLI | Current-only | omission still constructs the existing Coding bootstrap |
| installed Coding TUI | Current-only | delegates to the same Current CLI composition |
| public Coding SDK | Current-only | exports the existing bootstrap/session constructors |
| explicit G9 composition | typed explicit Hosting library seam | not imported by any installed or supported Product entrypoint |
| Plugin and Coding architecture CLIs | non-Product tools | neither owns nor selects a Product Worker |
| AppServer | contract-only package | no listener, runtime, launcher, or Product selection entrypoint exists |
| hosted AppHost adapter | binder-only library seam | no hosted application entrypoint exists |
| named mux | accepted design-only disposition | no runtime source or installed entrypoint exists |

## Deletion Admission Audit

Every condition below is evaluated independently. `NOT MET` is retained as an
explicit gap rather than being inferred from a green G9 suite.

| # | Accepted deletion condition | Result | Evidence and retained gap |
| --- | --- | --- | --- |
| 1 | zero production Current-owner consumers outside an explicit deletion allowlist | `NOT MET` | Coding bootstrap, installed CLI/TUI, and public SDK remain Current consumers. |
| 2 | every supported entrypoint is disposed and no omission semantics depend on Current | `NOT MET` | The inventory is complete, but Coding CLI/TUI/SDK omission semantics intentionally depend on Current. |
| 3 | retained Linux C5.4, Windows C5.5b/c, G8, and G9 reports match the exact promoted commit | `NOT MET` | G9.2 reports exist, but exact-head G9.4 promotion evidence is produced only on the later immutable promotion head. |
| 4 | the rollback/crash matrix repeatedly settles without orphan, stale publication, leaked pin, or cleanup debt | `NOT MET` | The deterministic G9 matrix passes, but deletion-grade repeated evidence on the future deletion head has not been retained. |
| 5 | a separately accepted replacement for `rollback_to_current` exists | `NOT MET` | No replacement rollback strategy is accepted; deleting Current would invalidate the present kill-switch destination. |
| 6 | persisted Session/envelope compatibility, downgrade/export, and cross-version rollback are decided and tested | `NOT MET` | The generic Session identity envelope remains uncomposed and no deletion/downgrade contract is accepted. |
| 7 | a dedicated deletion PR removes implementation, selection, default, exports, and dead dependencies atomically | `NOT MET` | No deletion PR exists; G9.3 and G9.4 explicitly prohibit opportunistic deletion. |
| 8 | parent/scope docs, generated dependency/public-surface facts, and reverse guards reconcile on that deletion PR | `NOT MET` | No deletion change exists against which this reconciliation can be proved. |

No subset of these conditions authorizes deletion. A future proposal must use
a separate decision and dedicated PR, re-evaluate all eight conditions against
that exact head, and supply an independent rollback plan.

## Consequences

- `WorkerHostingActivationV1()` continues to select `owner="current"`.
- Existing Coding bootstrap, CLI, TUI, and SDK behavior remains unchanged.
- The G9 composition remains default-dark and requires an explicit typed
  activation request; availability, imports, environment, platform, cwd,
  home, Session contents, or installed plugins cannot activate it.
- A selected Hosting attempt never falls back to Current within that attempt.
- G9.4 may promote the capability to `main`; promotion does not activate the
  route, change omission semantics, or authorize Current deletion.
- AppServer runtime, AppService, a hosted launcher, and named mux remain
  separate future scopes.

## Supersession Rule

This record is not changed in place to `DELETE`. A future deletion proposal
must add a successor decision with exact source and retained operational
evidence, link the dedicated deletion PR, and explicitly supersede this record.
Until that successor is accepted and merged, `RETAIN` is authoritative.
