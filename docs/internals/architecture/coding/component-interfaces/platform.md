# `platform`

## Role

- Coding-owned host policy and projections used by CLI/TUI/runtime surfaces
- thin boundary for version, changelog, and footer behavior

## Owns

- changelog/version lookup helpers
- footer data provider projection helpers

## Depends On

- `loushang.harness.workspace.git` for repository metadata
- host OS and filesystem services used by the remaining Coding policy

## Queries

- `check_for_new_loushang_version(...)`
- `parse_changelog(...)`
- `footer_snapshot_to_mapping(...)`

## Events

- no stable external event surface

## Key Data

- `ChangelogEntry`
- `FooterSnapshot`
- `FooterDataProvider`

## Out Of Scope

- mode lifecycle
- structured stdout protection, owned by `loushang.harness.host.stdout_guard`
- TUI rendering policy
- text clipboard copying, owned by `loushang.tui.clipboard`
- clipboard-image acquisition, MIME normalization, and attachment adaptation
- Git repository discovery, owned by `loushang.harness.workspace.git`
- filesystem permission policy
- session state

## Reference Implementation Alignment

- Keeps Coding platform policy outside session/runtime business logic.
- Internal callers import shared Git and clipboard capabilities directly from
  their canonical Harness or TUI owners.
- The retired Coding Git and clipboard paths have no compatibility aliases.
