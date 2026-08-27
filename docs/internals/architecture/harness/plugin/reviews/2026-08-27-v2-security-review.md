# Plugin Architecture V2 Independent Security Review

## Result

- Date: 2026-08-27
- Reviewer: independent agent `/root/plugin_security_review`
- Final verdict: **PASS**
- Scope: supply chain, trust and Approval, Worker containment and IPC,
  revocation/cleanup, and multi-tenant server isolation.

## Initial Blocking Findings And Disposition

1. Secure materialization started too late. V2 and PLC9 now require bounded
   acquisition/extraction, traversal and special-file rejection, no hooks or
   runtime source builds, digest-pinned dependency closure, immutable atomic
   publication, and quarantine cleanup on failure.
2. A Worker launch risked becoming an open-ended authority grant. Every
   non-host-equivalent local executable now requires non-downgradable proven
   containment; launch Approval authorizes only spawn, while every side-effecting
   IPC request is reconstructed and authorized by the Host. Connection identity,
   nonce, direction, request ID, revision, Instance, owner generation, and
   attempt bind the protocol against replay and confused-deputy use; environment
   and inherited descriptors are deny-by-default.
3. Mutable server state omitted the effective security scope. State, credentials,
   Workers, remote clients, caches, migration, and cleanup now bind the exact
   tenant/deployment/runtime Instance scope, with no cross-tenant sharing by
   default.
4. Preflight now states that Approval cannot grant host-equivalent trust and
   revalidates source, publisher, dependency, revocation, and topology facts.

## Re-Review Correction

The first re-review found one remaining duplicate-writer ambiguity. The final
architecture now makes Package lifecycle/store the sole owner of quarantine,
extraction, dependency verification, tree digest, lease, and atomic revision
publication. Source Authority only authenticates and fetches, then supplies
provenance and bytes through the Package owner's bounded sink. It cannot choose
paths, publish revisions, bind runtimes, or bypass final verification.

The same reviewer re-reviewed that correction and returned **PASS**.
