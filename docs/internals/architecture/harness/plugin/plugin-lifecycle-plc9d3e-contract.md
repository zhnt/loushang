# PLC9D3e Durable GC Result And Retry Debt

## Status

- Tracking: PLC9 `#509`. This is a dark result journal, not an executable
  Product GC route or PLC9D completion.
- The journal does not perform deletion and cannot independently attest that
  a caller's typed Store result came from a physical mutation.

## Attempt Evidence

`PluginPackageGcResultJournal` records one versioned attempt for a settlement
listed in an irreversible `deletion_started` event. An attempt contains exact
reservation/start/settlement and operation/idempotency identities. A Store
result gives `succeeded`; a stable error code gives `retryable_failure` or,
for a non-retryable Store identity/collision refusal, `terminal_failure`.
Changed operation/key reuse, a different start for the same reservation, a
second reservation for one physical settlement, and another attempt after
success or terminal failure are refused. Restart replay retains failures and
terminal success;
an interrupted deletion with no result remains unsettled and can be retried
by a future coordinator. A retry can settle `already_absent` when the Store
completed deletion before the first result append.

The append requires the exact Store settlement record, not just its ID. A
typed success with a different Store identity, stable ref, or tree identity
is refused as `plugin_package_gc_result_mismatch`. A regression first showed
that the previous ID-only append accepted a validly shaped result naming a
different Store. This binds the accounting entry to its target; it still
cannot prove that physical deletion happened.

A POSIX regression replaces one recorded file with a symlink to an outside
file. The rooted Store refuses deletion without touching the outside file;
the result ledger records its non-retryable code as terminal debt and rejects
a later attempt without a separate repair decision. This is not a repair or
permission to delete the altered tree. Older result readers reject the new
terminal disposition rather than silently retrying it.

The future executor must hold the Product reservation gate while resolving
the target, recording the deletion start, fencing the committed set and Store,
calling the exact Store owner, and appending this result or debt. The journal
alone is not a GC acceptance receipt. Product ingress, operator recovery,
shared dependency GC, separate private-data confirmation, and backup
retention projection remain open.

The PLC9B architecture guard lists the three exact internal GC modules that
import Package lifecycle evidence: the handoff crosswalk, root target checker,
and result journal. No Package owner-kernel import or public facade export is
added.
