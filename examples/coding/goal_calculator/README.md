# Integer calculator repair fixture

This is an intentionally defective, self-contained Python project for the
proposed G-GOAL-MIN-01 acceptance scenario. No Goal implementation runs here.

Required behavior:

- `subtract(a, b)` returns the integer difference `a - b`.
- `clamp(value, lower, upper)` returns the nearest integer in the closed
  interval `[lower, upper]`; inputs always satisfy `lower <= upper`.
- Only the content of `calculator.py` may change. Preserve every other file,
  including `TESTS.json` and the selected Method. Do not add, remove, rename,
  retype or link project files.
- Use the bounded pure-function source domain described in architecture R2.
  No imports, calls, assignments, decorators, defaults, annotations, loops or
  external dependencies are required for this project.

The authoritative acceptance cases are the fixed bytes of `TESTS.json`.
Passing a changed or reduced set does not meet the requirements. Actual Goal
acceptance additionally needs original Work/Blob associations, current-version
checks and the complete project constraint checks; running these cases alone
does not establish Goal completion.
