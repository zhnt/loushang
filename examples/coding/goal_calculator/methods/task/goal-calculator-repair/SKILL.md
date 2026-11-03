---
name: goal-calculator-repair
description: Repair the fixed integer calculator using current failure evidence.
type: task
domain: coding
version: "1"
plan_mode: fixed
steps:
  - inspect
  - repair
step_titles:
  inspect: Inspect the current requirements and failure evidence
  repair: Apply a minimal source repair
step_guidance:
  inspect: Read calculator.py and the fixed tests. Identify the current failing requirements without changing files.
  repair: Change only calculator.py to satisfy the agreed cases. Preserve the complete project contract and supported pure-function syntax.
---

Use the current requirement revision and the most recent actual validation
failure supplied in this Work batch. Do not infer success from an older report.
Read the project files with the existing Coding file tools. Do not invoke a
second executor, modify tests or Method, or claim that your reply completes the
Goal. Preserve both fixed function signatures and use only the admitted syntax.

The Product performs independent validation after this repair Work. Describe
what changed and any unresolved requirement; if the evidence or permitted
capabilities are insufficient, report that instead of changing the contract.
