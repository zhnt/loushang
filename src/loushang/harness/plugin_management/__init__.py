"""Internal, inert Plugin management contracts.

This package is intentionally absent from the public Plugin authoring surface.
"""

from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateLedger,
    PluginDesiredStateSnapshotV1,
    PluginLifecycleError,
)
from loushang.harness.plugin_management.records import (
    PLUGIN_DESIRED_SELECTION_VERSION,
    PLUGIN_DESIRED_STATE_MUTATION_VERSION,
    PLUGIN_DESIRED_STATE_TRANSITION_VERSION,
    PLUGIN_INSTALLATION_KEY_VERSION,
    PLUGIN_INSTALLATION_STATE_VERSION,
    PLUGIN_PACKAGE_REVISION_REF_VERSION,
    PluginDesiredSelectionV1,
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)

__all__ = [
    "PLUGIN_DESIRED_SELECTION_VERSION",
    "PLUGIN_DESIRED_STATE_MUTATION_VERSION",
    "PLUGIN_DESIRED_STATE_TRANSITION_VERSION",
    "PLUGIN_INSTALLATION_KEY_VERSION",
    "PLUGIN_INSTALLATION_STATE_VERSION",
    "PLUGIN_PACKAGE_REVISION_REF_VERSION",
    "PluginDesiredStateLedger",
    "PluginDesiredSelectionV1",
    "PluginDesiredStateSnapshotV1",
    "PluginDesiredStateMutationV1",
    "PluginDesiredStateTransitionV1",
    "PluginInstallationKeyV1",
    "PluginInstallationStateV1",
    "PluginLifecycleError",
    "PluginPackageRevisionRefV1",
]
