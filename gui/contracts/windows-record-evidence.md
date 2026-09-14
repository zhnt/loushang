# Windows private-file admission experiment

Status: partial C1 native evidence, 2026-09-14; not a complete G16 service-record
reader or a connected GUI. This supersedes the statement that native file
admission has no Rust implementation, but not the remaining B2 prerequisites.

## Implemented

The isolated `record_probe` binary follows the handle admission behavior in
`src/loushang/appserver/_windows_local_record.py` and the bounded read behavior
in `_local_record_files.py`. Its command accepts an explicit local-drive root
and reads only the fixed synthetic filename `fixture-record`; it neither
discovers endpoints nor accepts a record name supplied by the WebView.
The subsequent [record-decoding composition](record-values-evidence.md) adds an
explicit `--decode-record` probe mode using endpoint-derived filenames; this is
not exposed as a native GUI operation.

- Open directory/file with `FILE_FLAG_OPEN_REPARSE_POINT`; keep the directory
  handle open without delete sharing. Reject reparse points, wrong object kinds
  and file link counts other than one.
- Obtain the current process user SID. Inspect owner and DACL through the
  acquired handle. Require current-user ownership, a present, non-null,
  protected, non-defaulted DACL and exactly the expected explicit full-access
  allow ACEs for current user and SYSTEM. Check SID bounds within each ACE.
- Read at most 8,193 bytes through the already-admitted file handle, admitting
  at most 8,192. Compare size/write time before and after reading; recheck file
  and directory identities/security using retained and newly opened handles.
- Reject non-local-drive roots and parent traversal. Fail with a fixed message,
  without exposing file paths or bytes. The test binary's successful output is
  only fixture length/digest for comparison with the Python oracle.

The new Windows bindings are restricted to the standalone probe crate; the
Tauri application receives no added capabilities or dependencies.

## Native evidence and reproduction

```text
pnpm --dir gui run check:record-contract
```

This opt-in Windows-only command builds with locked offline dependencies, then
creates disposable synthetic files with the existing Python native private-file
adapter. Both the Python reader and independent Rust binary must agree.

Eleven Windows scenarios passed: normal Unicode contents, exactly 8 KiB,
oversized file, hardlink, and world-readable/null/unprotected DACL on both root
and record, plus a root directory junction. These use actual Windows ACL/file
operations, not mocked security responses. The runner restores mutated fixture
ACLs and removes the junction itself before cleaning its temporary directory;
it does not modify any existing service record or user permissions.

## Still pending

The original file-only mode still accepts synthetic payloads that need not be
JSON. Closed record fields, canonical digest and endpoint/profile validation
now have [separate and composed evidence](record-values-evidence.md), including
four additional Windows cases (15 total). Production connection remains pending.

The implementation has post-read identity checks, but this experiment does not
yet inject concurrent replacement or ownership changes to prove all race paths.
The current account's owner check is exercised by valid fixtures; rejection of
a different owner has not been demonstrated with a native fixture. Native close
failure reporting and sensitive-buffer cleanup remain production-adapter work;
RAII cleanup here does not claim those stronger failure guarantees.

Do not promote this test binary to a GUI command. Production async connection,
timeouts/cancellation, authentication integration, attachment and initial
snapshot publication remain pending under [the connection plan](connection-plan.md).
No default CI or TUI/Harness gate is added.
