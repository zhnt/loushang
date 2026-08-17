from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from loushang.harness.policy import PolicyDecision
from loushang.harness.resources.packages.source import (
    PackageSourceIdentity,
    is_remote_package_source,
)


@dataclass(frozen=True)
class PackageSourceSecurityReport:
    source: str
    source_type: str
    identity_key: str
    host: str | None
    path: str | None
    pinned: bool
    decision: PolicyDecision

    @property
    def ok(self) -> bool:
        return self.decision.disposition == "allow"

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "identity_key": self.identity_key,
            "host": self.host,
            "path": self.path,
            "pinned": self.pinned,
            "decision": {
                "disposition": self.decision.disposition,
                "reason": self.decision.reason,
                "code": self.decision.code,
            },
        }


@dataclass(frozen=True)
class PackageSecurityPolicy:
    allow_insecure_remote_sources: bool = False
    trusted_hosts: tuple[str, ...] = ()
    trusted_sources: tuple[str, ...] = ()

    def evaluate_package_source(self, source: str | Path) -> PolicyDecision:
        if not is_remote_package_source(source):
            return PolicyDecision.allow()
        text = str(source)
        if text.strip().startswith("pypi:"):
            return PolicyDecision.allow()
        trusted_identities = {PackageSourceIdentity.parse(trusted_source).identity_key for trusted_source in self.trusted_sources}
        if text in self.trusted_sources or PackageSourceIdentity.parse(text).identity_key in trusted_identities:
            return PolicyDecision.allow()
        scheme = urlparse(text).scheme
        if scheme == "http" and not self.allow_insecure_remote_sources:
            return PolicyDecision.deny(f"insecure remote package source requires HTTPS: {text}")
        parsed = urlparse(text.removeprefix("git+"))
        if self.trusted_hosts and parsed.hostname not in self.trusted_hosts:
            return PolicyDecision.deny(f"untrusted remote package host: {parsed.hostname}")
        if scheme in {"https", "git+https", "git+ssh", "git+file", "ssh", "file"}:
            return PolicyDecision.allow()
        return PolicyDecision.deny(f"unsupported remote package source scheme: {scheme}")

    def explain_package_source(self, source: str | Path) -> PackageSourceSecurityReport:
        identity = PackageSourceIdentity.parse(source)
        return PackageSourceSecurityReport(
            source=str(source),
            source_type=identity.source_type,
            identity_key=identity.identity_key,
            host=identity.host,
            path=identity.path,
            pinned=identity.pinned,
            decision=self.evaluate_package_source(source),
        )

    def evaluate_plugin_source(self, source: str | Path) -> PolicyDecision:
        return self.evaluate_package_source(source)
