# PLC9D3c Exact Root GC Target Resolution

## Status

- Tracking: PLC9 `#509`. This is a read-only prerequisite, not executable GC
  or PLC9D completion.
- No new Product command, Store mutation, background job, or author SDK route.

## Resolution Rule

`resolve_plugin_package_gc_root_target()` consumes typed snapshots from the
Product GC binding, PLC9B committed-set, and Store settlement owners. It
returns one exact root settlement only when:

- the logical Package revision has exactly one successful desired handoff;
- the handoff's Product/scope/installation, operation, attempt, request,
  committed-set ID, and root ref match the committed set;
- the logical dependency lock digest and canonical source identity match the
  committed root node;
- no other handoff or committed set names the same physical root ref; and
- exactly one root Store settlement matches that ref, operation, attempt,
  classification, root node, and prepublication graph, with no physical alias.

Missing legacy mappings, duplicate physical settlements, shared roots, and
changed lock/source evidence fail closed with stable blocker codes. The
resolver does not infer a Store path from plugin name, source URL, or content
digest. It does not delete dependencies: a committed set may share dependency
refs with other sets, which needs separate retention accounting.

The input tuples must be captured under the eventual Product reference and
Store owner fences. The resolver itself does not make an atomic snapshot,
reserve a candidate, inspect current filesystem identity, check a tombstone,
or authorize deletion. The POSIX integration regression builds actual
published root/dependency Store refs and a committed set, then proves exact
resolution and missing/ambiguous/alias refusal. Product-wide composition and
a durable result/debt coordinator remain open.
