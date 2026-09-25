# PLC9D3l Durable Private-Data Confirmation Evidence

## Status

- Tracking: PLC9 `#509`. The confirmation authority is internal and unbound;
  no CLI, RPC, Session, UI, or management command can issue a confirmation or
  delete private data.
- It is separate from Package removal, root GC, and any backup owner.

`PluginPrivateDataConfirmationJournal` records the exact deletion plan,
confirmation identity, actor, policy revision, and monotonic journal revision.
It rejects a reused confirmation ID with another plan or actor and replays the
same accepted record after restart. `is_confirmed` reads that durable evidence
for the D3k coordinator; a caller cannot obtain a successful deletion result
from an unrecorded or mismatched confirmation. Strict record decoding,
revision-chain checks, private parent/file admission, and duplicate-key
rejection refuse inconsistent local evidence.

The focused test proves unconfirmed refusal while the test data survives,
durable confirmation across a new journal instance, exact data-owner deletion
and receipt, idempotent confirmation replay, changed-plan conflict, and
duplicate-key refusal.

A production Product/operator command must authenticate and authorize the
person initiating `record_confirmation`, show the exact plan before issuing
it, bind the journal to its private Product state, and compose a real
data-domain owner that revalidates the plan and durably settles deletion.
These are not delivered by D3l. Backup-owner binding and existing pre-B
workspace adoption remain separate PLC9 work.
