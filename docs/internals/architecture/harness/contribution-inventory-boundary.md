# Harness Contribution Inventory Boundary

## Status

Status: accepted for `lane/harness`.

This document defines product-neutral contribution descriptors, inventory
indexing, and duplicate-key reporting as `loushang.harness.contributions`
responsibilities. The later
[Extension Runtime Core Boundary](extension-runtime-core-boundary.md) expands
Harness ownership to extension manifest projection, loading, registration,
conflict resolution, and generic dispatch while preserving product policy.

## Decision

`loushang.harness.contributions` owns:

- `ContributionType` and its accepted extension-surface alias;
- `ContributionDescriptor` and `ExtensionSurfaceDescriptor`;
- `ContributionRegistry` and `ExtensionInventory`;
- `DuplicateContributionKeyError` and its extension-surface alias.

The generic and extension-shaped names refer to the same harness-owned classes.
This preserves existing class identity while giving non-coding consumers a
neutral import path.

The descriptor records contribution kind, name, opaque contributor identity,
source path, activation state, priority, permission requirements, diagnostics,
and metadata. Harness stores and indexes those values but does not interpret
them. In particular, `extension_id` remains an opaque contributor identifier;
it does not make Harness responsible for loading or trusting an extension.

The registry preserves insertion order and indexes contributions by type,
contributor, and `(type, name)` key. Multiple matching keys remain observable.
`get()` raises the duplicate-key error rather than choosing a winner. Product
adapters decide applicability, precedence, activation, override, and conflict
remediation.

## Coding Adapter

`surfaces_from_loaded_extension`, `contributions_from_loaded_extension`, and
manifest/runtime projection live in
`loushang.harness.extensions.contributions`. The legacy
`loushang.coding.extensions.contributions` module is removed; Coding imports
the Harness owner directly.

## Canonical Imports And Compatibility

The removed Coding Extension package does not expose compatibility aliases.
Consumers import the Harness owner directly:

```python
from loushang.harness.contributions import ExtensionInventory
from loushang.harness.contributions import ExtensionSurfaceDescriptor
from loushang.harness.contributions import ContributionRegistry
```

The generic contribution names and Extension-shaped names refer to the same
Harness-owned classes. They keep their Harness `__module__`; no Product defines
a second implementation or legacy submodule import path.

Existing constructor fields, registry methods, insertion ordering, duplicate
visibility, exception attributes, and error text remain unchanged. No broad
contribution symbols are added to top-level `loushang.harness.__all__`.

## Coding-Owned Behavior

The combined contribution and extension-runtime migrations do not move or
redesign:

- extension search-root selection, trust, approval, or product activation;
- permission enforcement, enablement defaults, or OEM override policy;
- concrete command, tool, prompt, skill, UI, or provider handlers;
- product runtime bindings and rich extension contexts;
- session events, controller behavior, resource refresh, or diagnostics display;
- tool contribution resolution already owned by
  `loushang.harness.tools.contribution`.

Specialized session, system-prompt, model/provider, Agent tool-call, compaction,
and UI result reducers remain product-owned.

## Dependency Direction

The target direction is:

```text
coding extension/session adapter
  -> loushang.harness.extensions
  -> loushang.harness.contributions
  -> loushang.harness.resources.diagnostics
```

`loushang.harness.contributions` must not import coding, method, work, TUI, AI,
agent runtime, provider, or product packages. The extension runtime also must
not import product packages, but may depend on stable agent tool value
primitives and neutral Harness resource, tool, and contribution contracts.

## Validation

The migration must prove:

- descriptor values and frozen-record behavior remain unchanged;
- registry insertion order and all indexes remain unchanged;
- duplicate keys remain visible and `get()` preserves its exception contract;
- generic and Extension-shaped Harness names share class identity;
- `LoadedExtension` projection produces Harness-owned records;
- Coding internal consumers import the Harness owner directly;
- extension runtime behavior and focused Coding tests remain unchanged;
- Harness import boundaries and top-level export discipline still pass.
