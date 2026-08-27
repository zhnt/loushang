# Plugin Ecosystem Design History

## Status

- Authority: retired design history; non-normative.
- Superseded by: [Harness Plugin Architecture V2](../../harness/plugin/architecture.md).
- Delivery authority: [Plugin Lifecycle And Coding Pluginization Plan](../../harness/plugin/plugin-lifecycle-coding-pluginization-plan.md).
- Implementation status: not applicable. Current source, tests, and exact
  contracts under `harness/plugin/` remain authoritative.

## Purpose

This package preserves the broader proposals and independent review evidence
that informed Plugin Architecture V2. It is no longer an active architecture
package, acceptance candidate, SDK contract, or competing PLC8/PLC9 plan.

The incorporated conclusions were independently restated in the active
architecture candidate:

- artifact, Plugin identity, contribution, Capability, execution topology,
  trust, lifetime, and placement are orthogonal;
- a Skill is Resource content while its catalog/parser can be a Plugin
  component;
- Skill scripts are supported only through an exact managed execution action;
- separate process execution is topology, not sufficient containment;
- long-lived Workers use supervised mechanics plus owner-specific protocols;
- built-in and embedded authoring stays simple without creating a second
  runtime; and
- Loushang has no universal Plugin context or Terraform-style Plugin-wide
  `plan/apply` state machine.

Where any document below conflicts with Plugin Architecture V2 or a frozen
incremental contract, the active architecture or exact contract wins.

## Historical Documents

- [Unified Product, Package, And Plugin Architecture](unified-product-package-plugin-architecture.md)
- [Plugin Management And Isolated Execution Improvement Plan](plugin-management-and-isolated-execution-improvement-plan.md)
- [Client Plugin SDK And Embedded Authoring Experience](client-plugin-sdk-and-embedded-authoring-experience.md)
- [Independent review evidence](reviews/README.md)

These files intentionally retain proposal-era vocabulary, rejected alternatives,
and line-relative citations from the reviewed revisions. Do not update those
citations to make them appear current; use Git history when reconstructing an
old review finding.

## Current Reading Path

1. [Plugin Architecture Hub](../../harness/plugin/README.md)
2. [Plugin Architecture V2](../../harness/plugin/architecture.md)
3. [Lifecycle Plan](../../harness/plugin/plugin-lifecycle-coding-pluginization-plan.md)
4. the exact owner and contract documents linked by the Hub
