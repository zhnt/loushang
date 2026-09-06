# PLC9C5 C5.4 Linux Coding Product Canary

## Status

- ID: `PLC9C5-C5.4-LINUX-PRODUCT`
- Scope: one explicit Coding Product `capability_provider` Worker canary
- Parent: `PLC9C5-C5.0`
- Authority: normative implemented slice
- Design status: accepted
- Implementation status: implemented
- Activation status: Linux x86_64 excluding WSL only, behind an exact Product
  policy and receipt
- Production default: Current
- Parent gate: G7 remains open until a separate Windows required-containment
  profile is accepted
- Owner: Coding Product policy over Product-neutral Harness Worker and Hosting
  capabilities

## Boundary

`bind_coding_product_worker_canary` is the only Product composition introduced
by C5.4. Coding validates the exact Product, receipt, persisted Product profile,
stable Session locator, Worker request, Capability authority, and injected
machine host/boot identities. It imports the public Harness Worker facade plus
the two exact reviewed Worker friend seams: the C5.1 activation coordinator and
the C5.2 native-profile binder. It does not import Hosting, construct a
platform capture specification, inspect native handles, or accept an
environment-derived activation flag.

The embedding composition supplies durable Product authority/state ports,
trusted cleanup-evidence identity, trusted launcher/profile digests, and a
Product-neutral Hosting capability. The Coding root constructs the real C5.1
coordinator and asks the sole C5.2 friend binder for an opaque,
receipt/request-bound `ProductWorkerNativeProfilePort`. Harness' existing
adapter preserves the private H6 managed-capture seam. This keeps the
dependency direction:

```text
Coding Product policy
  -> exact Harness Worker coordinator + native-profile friend binder
     -> opaque ProductWorkerNativeProfilePort + Hosting capability
        -> Hosting-owned process, endpoint, and native resources
```

No receipt or disabled policy returns Current without constructing Hosting,
native, process, protocol, or Capability state. An invalid required route is
unavailable; an independently optional route may become degraded only after
owned state is reclaimed. Neither path retries Current in the same attempt.
Pure native-profile identity/closure validation precedes construction of the
coordinator that initializes durable activation state.

## Session And Entrypoint Join

Selected Sessions require Coding's existing Product-profile validator plus a
resumable `SessionDiscoveryMetadata`. The receipt fixes an opaque fingerprint
of the exact source, locator, revision, mode, origin, aliases, and conflicts.
Canonical global and cwd/home compatibility projections are accepted when
unambiguous; a foreign Product profile, conflict, changed revision, or changed
locator fingerprint is rejected before acquisition. Machine-local paths are
hashed and never appear in status.

CLI, TUI, and the shared Product construction path retrieve the same immutable
receipt object from one canary composition. Early-dispatch LSP, workspace,
multi-agent, package-management, and other non-Session routes remain unable to
activate it.

## Publication And Failure

The serialized admission lease registers first effect before the selected
Hosting owner starts. Worker handshake must become healthy, the read-only
Capability adapter must admit the exact authority, and the activation
coordinator must recheck native-policy closure before the Capability domain may
publish. A publication call is treated as possibly effectful: an exception or
cancellation after it begins triggers conservative fence, revoke/drain,
termination, retirement, and settlement.

Status is versioned, bounded, and pathless. It carries stable codes plus only
receipt/attempt/generation fingerprints. Arbitrary exception text, paths,
secrets, environment values, file descriptors, and handles do not cross the
Product boundary.

## Rollback And Recovery

Rollback uses the fixed C5 order: latch future Hosting closed; fence exact
attempts; revoke/drain exact Capability generations; terminate complete trees;
record settlement or debt; settle Product readiness; only then issue a new
Current selection. The existing router remains sticky for an in-flight owner,
and a rollback never changes the owner of that same attempt.

Recovery accepts only the full ordered V1–V6 evidence vector: prior absent,
exact reaped, same-boot unknown debt, changed-boot absence, exhausted budget,
and host-restart reconstruction. The Product composition delegates each fact
to its owning durable port and rejects an incomplete or reordered vector.
Adoption remains forbidden.

## Required Evidence

`PLC9C5-C5.4-LINUX-PRODUCT` is retained at
`.artifacts/plc9c5-c54-linux-product.xml`. Its exact 25 case ids cover Product,
Session, required/optional readiness, closure freshness, handshake-before-
publication, unsupported hosts, rollback, recovery, shared entrypoints, and
sentinel redaction. The report must contain zero skips, failures, and errors.

## Retained Fences

- Current remains the default and is retained for future rollback attempts;
- Windows restricted mechanics remain rejected as Product required
  containment, and G7 remains open;
- WSL, macOS, non-x86 Linux, and every unlisted profile fail closed;
- no same-attempt fallback, ambient activation flag, raw native authority,
  effectful Worker domain, public author-SDK owner, or `remote_service` route;
- no generic AppHost pre-routing Session identity claim; and
- no Current owner or Capability generation owner deletion before G9 evidence.

## Exit Gate

C5.4 is complete only when the 25-row report is mandatory in Linux CI, the
manifest verifier rejects missing/skipped/failing evidence, architecture tests
prove the single Product root and exact dependency direction, earlier C5.1–C5.3
reports stay implemented, and the inventory names the retained Current and
Windows gaps honestly.
