# `package`

## Status

Superseded as a Coding-owned component. Product-neutral Resource Package
materialization and lifecycle now belong to
[Harness Platform Resource Layout](../../harness/platform-resource-layout-boundary.md).
The definitions below are retained for compatibility history.

## Role

- Resource Package lifecycle and source-materialization boundary; Plugin
  identity, registration, and enablement are separate
- resource distribution unit bridge for local, remote, and Python package sources

## Owns

- `PackageMaterializer`
- `PackageMaterializerBackend`
- `PackageMaterializationRecord`
- `PackageMaterializationLifecycle`
- `PackageSourcePolicy`
- `PackageSourceConfig`
- `PackageSourceIdentity`
- package source resolution and identity merging

## Depends On

- `control` / settings for configured sources
- filesystem/package cache roots
- optional materializer backend for remote or Python package sources
- `plugin` for manifest-backed source projection
- `resources` for resource root projection

## Commands

- `materialize_package(...)`
- `update_package(...)`
- `update_packages(...)`
- `check_package_updates(...)`
- `remove_package(...)`
- `resolve_package_resource_roots(...)`

## Queries

- `configured_package_sources(...)`
- `package_source_scopes(...)`
- `collect_package_entries(...)`
- `remote_package_entry(...)`

## Events

- `PackageProgressEvent`
- no session-level event protocol; CLI/RPC project package lifecycle records instead

## Key Data

- `PackageMaterializationRecord`
- `PackageMaterializationLifecycle`
- `PackageProgressEvent`
- `PackageSourcePolicy`
- `PackageSourceConfig`
- `PackageSourceIdentity`
- `ResolvedPackageResourceRoots`

## Out Of Scope

- extension hook dispatch
- session runtime orchestration
- prompt assembly
- approval UI and optional signature verification

## Reference Implementation Alignment

- Aligns with reference package-manager lifecycle semantics without adopting an npm-only backend.
- Python package sources use Python package install/update semantics.
- Project package sources override user package sources by package identity, not by raw source string.
- Package lifecycle records are visible to CLI/RPC clients even when materialization is pending, failed, or denied.
