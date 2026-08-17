# Diagnostics Export Boundary

`loushang.harness.diagnostics.export` owns the reusable diagnostics archive
mechanism. It writes a deterministic set of archive members, protects archive
member names, and redacts both text artifacts and JSON values before writing.

The low-level archive writer does not decide a product's storage root, file
name, package identity, README wording, JSON field convention, or artifacts.
The higher-level Loushang Product-family operation supplies a standard
`DiagnosticBundleProfile` that a Product may replace.

## Harness Contract

The Harness export API accepts:

- an explicit output path;
- a product-projected manifest and diagnostic JSON values;
- optional named text artifacts;
- optional clock and redaction functions for tests or stricter deployments.

It always rejects absolute paths and parent traversal in archive member names.
Default redaction applies recursively to structured values whose keys identify
credentials and to common bearer-token text forms. Products may add stricter
redaction, but cannot opt out of the default redactor accidentally.

The writer owns no diagnostics service lookup and no product serialization. A
failed product serializer must be handled by the product before invoking the
writer; it must not fall back to an unrestricted `repr()` in the archive.

## Standard Product Bundle

`loushang.harness.diagnostics.export_diagnostics_bundle` supplies the standard
`.loushang/diagnostics` output default, `loushang-diag-*` name, README,
camelCase manifest, latest debug/trace/session artifacts, and standard
diagnostic serialization. These are shared Loushang host contracts rather than
Coding semantics. Research, Design, PPT, OEM-configured Products, and Extensions
can use the default profile or inject another `DiagnosticBundleProfile`.

The removed `loushang.coding.diag_export` facade is not retained. Coding CLI
calls the Harness operation directly, preserving the existing archive schema.
