# Internal Architecture And Design Notes

[Public docs](../) | [English](../en/) | [中文](../zh-CN/)

This directory keeps historical and contributor-facing material that used to live at the top level of `docs/`.

## Contents

- [Architecture](./architecture/) - accepted architecture, subsystem boundaries, component notes, and design decisions.
- [Architecture Method](./architecture-method/) - reusable architecture process, artifact model, component methods, templates, and method history.
- [Strategy](./strategy/) - product strategy, roadmap thinking, and product surface notes.
- [Glossary](./glossary/) - terminology drafts and internal vocabulary.
- [Specs](./specs/) - iteration design specs.
- [Plans](./plans/) - implementation plans, including archived plans moved from the former `docs/superpowers/plans/`.
- [Experimental](./experimental/) - research and methodology experiments.
- [Testing](./testing/) - internal testing notes.
- [Legacy](./legacy/) - older root-level documents kept for continuity.

These documents may describe target architecture, historical design decisions, or implementation plans. For current user-facing behavior, start with the public documentation and the code/tests.

## Reading Rule

Internal docs are not all live architecture.

- `architecture-method/` defines how architecture is designed and governed; it
  does not describe Loushang Current or Target architecture.
- `architecture/` root and accepted ARDs are the primary Loushang architecture
  sources. Its governance profile binds the reusable method to this repository.
- `architecture/drafts/` records exploratory architecture and unresolved design options.
- `specs/` records dated implementation designs; use them for rationale, not as current API truth.
- `plans/archive/` records completed or abandoned execution plans.
- `experimental/` records research inputs and methodology experiments.
- `legacy/` preserves older position papers and boundary notes.

When these documents conflict, prefer current code/tests and the live architecture
docs. Historical terms such as `loushang-methods`, `methods/**`, Textual, or old
`docs/architecture/...` paths may be preserved in historical files and should not
be read as current implementation status.
