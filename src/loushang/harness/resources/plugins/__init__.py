from loushang.harness.resources.plugins.authority import (
    PluginBindingStore,
    PluginBindingValidator,
    PluginInspection,
    PluginResolutionAuthority,
    PluginResolutionDiagnostic,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PLUGIN_CONTRIBUTION_INDEX_VERSION,
    PLUGIN_DECLARATION_IR_VERSION,
    PluginContributionIndex,
    PluginContributionReservation,
    PluginDeclaration,
)
from loushang.harness.resources.plugins.dependencies import (
    PLUGIN_DEPENDENCY_LOCK_FORMAT,
    PluginDependencyClosureLock,
    PluginPythonDistributionLock,
    lock_plugin_dependency_closure,
)
from loushang.harness.resources.plugins.lifecycle import (
    is_remote_plugin_source,
    remote_plugin_name,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.plugins.registry import PluginRegistry
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    PluginRevisionStore,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.plugins.selection import (
    PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION,
    PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION,
    PLUGIN_EXECUTION_DECISION_RECORD_VERSION,
    PLUGIN_PREFLIGHT_CONTEXT_VERSION,
    PLUGIN_SELECTION_PLAN_VERSION,
    PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION,
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionCandidate,
    PluginContributionRef,
    PluginDeclarationReservation,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionLookupPort,
    PluginExecutionDecisionLookupResult,
    PluginExecutionDecisionMissing,
    PluginExecutionDecisionRecord,
    PluginInstanceRevisionRef,
    PluginPreflight,
    PluginPreflightAcceptedOutcome,
    PluginPreflightContextV1,
    PluginPreflightDeniedOutcome,
    PluginPreflightDiagnostic,
    PluginPreflightOutcome,
    PluginPreflightPendingApprovalOutcome,
    PluginPreflightRejectedOutcome,
    PluginSelection,
    PluginSelectionError,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
    PluginSourceTrustSnapshotV1,
    build_execution_approval_subject,
)
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginManifest,
    PluginResolvedResources,
    PluginRevisionKind,
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
    ResolvedPluginPackage,
    VerifiedPluginRevision,
)


def project_installed_plugin(plugin: object) -> dict[str, object]:
    """Project plugin identity and activation state for resource listings."""

    manifest = _safe_plugin_getattr(plugin, "manifest", None)
    source = _safe_plugin_getattr(plugin, "source", None)
    source_kind = _safe_plugin_getattr(source, "kind", "local")
    source_value = (
        _safe_plugin_getattr(source, "url", None)
        if source_kind == "remote"
        else _safe_plugin_getattr(source, "path", "")
    )
    return {
        "name": _safe_plugin_string(_safe_plugin_getattr(manifest, "name", "")),
        "version": _safe_plugin_string(_safe_plugin_getattr(manifest, "version", "")),
        "path": "" if source_kind == "remote" else _safe_plugin_string(source_value),
        "source": _safe_plugin_string(source_value),
        "kind": source_kind if isinstance(source_kind, str) else "local",
        "enabled": bool(_safe_plugin_getattr(plugin, "enabled", False)),
    }


def _safe_plugin_getattr(target: object, name: str, default: object) -> object:
    try:
        return getattr(target, name)
    except Exception:
        return default


def _safe_plugin_string(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return ""


__all__ = [
    "InstalledPlugin",
    "PLUGIN_CONTRIBUTION_INDEX_VERSION",
    "PLUGIN_DECLARATION_IR_VERSION",
    "PLUGIN_DEPENDENCY_LOCK_FORMAT",
    "PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION",
    "PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION",
    "PLUGIN_EXECUTION_DECISION_RECORD_VERSION",
    "PLUGIN_PREFLIGHT_CONTEXT_VERSION",
    "PLUGIN_SELECTION_PLAN_VERSION",
    "PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION",
    "PendingOnlyPluginExecutionDecisionLookup",
    "PluginBindingStore",
    "PluginBindingValidator",
    "PluginContributionCandidate",
    "PluginContributionIndex",
    "PluginContributionRef",
    "PluginContributionReservation",
    "PluginDeclaration",
    "PluginDeclarationReservation",
    "PluginDependencyClosureLock",
    "PluginEffectiveConfigurationEntry",
    "PluginEffectiveConfigurationSetV1",
    "PluginInspection",
    "PluginExecutionApprovalSubject",
    "PluginExecutionDecisionCurrent",
    "PluginExecutionDecisionLookupPort",
    "PluginExecutionDecisionLookupResult",
    "PluginExecutionDecisionMissing",
    "PluginExecutionDecisionRecord",
    "PluginInstanceRevisionRef",
    "PluginManifest",
    "PluginManifestError",
    "PluginManifestParser",
    "PluginPythonDistributionLock",
    "PluginPreflight",
    "PluginPreflightAcceptedOutcome",
    "PluginPreflightContextV1",
    "PluginPreflightDeniedOutcome",
    "PluginPreflightDiagnostic",
    "PluginPreflightOutcome",
    "PluginPreflightPendingApprovalOutcome",
    "PluginPreflightRejectedOutcome",
    "PublishedPluginPackage",
    "PluginRegistry",
    "PluginRevisionError",
    "PluginResolvedResources",
    "PluginResolutionAuthority",
    "PluginResolutionDiagnostic",
    "PluginRevisionKind",
    "PluginRevisionStore",
    "PluginSource",
    "PluginSourceBinding",
    "PluginRuntimeResolution",
    "PluginSelection",
    "PluginSelectionError",
    "PluginSelectionPlanV2",
    "PluginSelectionResolver",
    "PluginSourceTrustSnapshotV1",
    "ResolvedPluginPackage",
    "VerifiedPluginRevision",
    "VerifiedRevisionHandle",
    "build_execution_approval_subject",
    "is_remote_plugin_source",
    "lock_plugin_dependency_closure",
    "project_installed_plugin",
    "remote_plugin_name",
]
