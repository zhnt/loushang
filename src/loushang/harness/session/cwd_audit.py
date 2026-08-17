"""Generic checks for services accidentally bound to another session cwd."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticLevel


@dataclass(frozen=True)
class CwdBoundServicesAuditIssue:
    code: str
    message: str
    details: dict[str, object]
    level: DiagnosticLevel = "warning"


@dataclass(frozen=True)
class CwdBoundServicesAudit:
    session_cwd: str
    issues: list[CwdBoundServicesAuditIssue]

    @property
    def ok(self) -> bool:
        return not self.issues


def audit_cwd_bound_services(
    *,
    session_cwd: str | Path,
    project_root: str | Path | None = None,
    resource_cwd: str | Path | None = None,
) -> CwdBoundServicesAudit:
    """Check project settings and resource bundles against a session cwd."""

    resolved_session_cwd = _resolve(session_cwd)
    issues: list[CwdBoundServicesAuditIssue] = []
    if project_root is not None:
        resolved_project_root = _resolve(project_root)
        if not _is_at_or_under(resolved_session_cwd, resolved_project_root):
            issues.append(
                CwdBoundServicesAuditIssue(
                    code="settings_project_cwd_mismatch",
                    message=(
                        "Project-scoped settings are bound to a different project "
                        "root than the session cwd."
                    ),
                    details={
                        "project_root": str(resolved_project_root),
                        "session_cwd": str(resolved_session_cwd),
                    },
                )
            )
    if resource_cwd is not None:
        resolved_resource_cwd = _resolve(resource_cwd)
        if resolved_resource_cwd != resolved_session_cwd:
            issues.append(
                CwdBoundServicesAuditIssue(
                    code="resource_bundle_cwd_mismatch",
                    message="Resource bundle cwd does not match the session cwd.",
                    details={
                        "resource_cwd": str(resolved_resource_cwd),
                        "session_cwd": str(resolved_session_cwd),
                    },
                )
            )
    return CwdBoundServicesAudit(
        session_cwd=str(resolved_session_cwd),
        issues=issues,
    )


def record_cwd_bound_services_audit(
    audit: CwdBoundServicesAudit,
    *,
    diagnostics_service: DiagnosticsService,
    session_id: str | None = None,
) -> None:
    """Record a cwd audit with the standard startup diagnostic scope."""

    for issue in audit.issues:
        diagnostics_service.capture_failure(
            code=issue.code,
            error=issue.message,
            phase="startup",
            source="bootstrap",
            level=issue.level,
            session_id=session_id,
            details=issue.details,
        )


def project_root_from_settings_base(
    project_base_dir: str | Path | None,
) -> Path | None:
    """Resolve a settings base directory to its bound project root."""

    if project_base_dir is None:
        return None
    resolved = _resolve(project_base_dir)
    return resolved.parent if resolved.name == ".loushang" else resolved


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_at_or_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


__all__ = [
    "CwdBoundServicesAudit",
    "CwdBoundServicesAuditIssue",
    "audit_cwd_bound_services",
    "project_root_from_settings_base",
    "record_cwd_bound_services_audit",
]
