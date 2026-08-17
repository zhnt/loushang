from __future__ import annotations

from loushang.harness.policy import PolicyDecision
from loushang.harness.resources.packages import PackageSecurityPolicy


def test_package_security_policy_is_reusable_for_product_source_rules() -> None:
    policy = PackageSecurityPolicy(trusted_hosts=("packages.example.invalid",))

    allowed = policy.evaluate_package_source(
        "https://packages.example.invalid/repo.git"
    )
    denied = policy.evaluate_package_source("https://untrusted.example/repo.git")

    assert allowed == PolicyDecision.allow()
    assert denied.disposition == "deny"
