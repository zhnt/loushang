# Loushang Coding Diagnostics Service V1 Design

**Date:** 2026-05-18

## Goal

Add a `DiagnosticsService` that gives `loushang-coding` a unified diagnostics model and query surface across startup, resource loading, and runtime failures.

## Architecture

`DiagnosticsService` is an independent support component. Producers record structured `DiagnosticRecord` values into the service, and callers query recent diagnostics or the latest error report. The service does not own recovery, presentation, or exit behavior.

## Data Model

### `DiagnosticRecord`

Single normalized diagnostic fact.

Fields:

- `type`: `info | warning | error`
- `code`
- `message`
- `phase`: `startup | resource_loading | runtime`
- `source`: `bootstrap | loader | extensions | session | policy | exec | tool`
- `timestamp`
- `session_id`
- `entry_id`
- `source_path`
- `details`

### `ErrorReport`

Derived query view over diagnostics, anchored by the latest error.

Fields:

- `primary`
- `related`

## Service Surface

`DiagnosticsService` exposes:

- `record(...)`
- `record_many(...)`
- `normalize_diagnostic(...)`
- `normalize_exception(...)`
- `get_last_diagnostics(limit=50)`
- `get_diagnostics(phase=None, source=None, type=None)`
- `get_last_error_report()`
- `clear_runtime_diagnostics()`

## Initial Producers

V1 integrates:

- `bootstrap`
- `loader`
- `extensions`
- `session`

`policy` and `exec` remain supported by the data model but are not required for the first implementation slice.

## Integration Strategy

### Startup / Resource Loading

- `create_services()` creates a `DiagnosticsService`
- `create_agent_session()` records:
  - loader diagnostics as `source="loader"`, `phase="resource_loading"`
  - extension loader / resource discovery diagnostics as `source="extensions"`, `phase="resource_loading"`
  - extension tool conflict diagnostics as `source="bootstrap"`, `phase="resource_loading"`

### Runtime

`AgentSession` receives the service and records:

- compaction failures
- branch summary failures
- retry terminal failures

`AgentSession` also syncs new extension runner diagnostics after runtime hooks and completed agent turns so runtime extension failures appear in the unified diagnostics stream.

## Non-Goals

V1 does not include:

- diagnostics persistence in session files
- mode-specific formatting
- CLI printing policy
- recovery strategy ownership
- plugin diagnostics

## Testing Scope

The first implementation must cover:

1. service normalization and query behavior
2. bootstrap/resource diagnostics recording
3. session runtime failure recording
4. runtime extension diagnostics synchronization
