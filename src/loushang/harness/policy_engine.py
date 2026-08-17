"""Compatibility shim re-exporting `loushang.harness.policy.engine`.

Kept for the accepted `loushang.harness.policy_engine` import path; new code
should import from `loushang.harness.policy.engine`. Removal is deferred per
docs/internals/architecture/harness/policy-approval-redesign.md section 15.
"""

from loushang.harness.policy.engine import PolicyEngine

__all__ = ["PolicyEngine"]
