"""Private Product composer for Coding's first-party Capability Plugins."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from loushang.coding._base_plugin import CodingBasePluginAssembly
from loushang.coding._cleanup import run_cleanup_steps
from loushang.coding._resource_catalog_shadow import (
    complete_coding_package_plugin_selection_seed,
)
from loushang.coding.arch._plugin_tool_owner import CodingArchToolOwner
from loushang.coding.arch._provider_api import (
    CODING_ARCH_CAPABILITY_DEFINITION,
    CodingArchPluginConfigV1,
)
from loushang.coding.lsp._plugin_tool_owner import CodingLspToolOwner
from loushang.coding.lsp._provider_api import (
    CODING_LSP_CAPABILITY_DEFINITION,
    CodingLspPluginConfigV1,
)
from loushang.coding.plugin_dependency_grants import (
    coding_arch_default_plugin_root,
    coding_lsp_default_plugin_root,
    coding_plugin_distribution_evidence_resolver,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.approval.plugin_activation import (
    ContributionActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationDecisionRecordV1,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginApprovalDecisionRecordV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.component_host import CapabilityComponentHost
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionPolicy,
    OwnerContributionSnapshot,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionRecord,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
    CapabilityProviderOwnerSnapshot,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.plugin_authoring.evaluator import PluginDefinitionEvaluator
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginPreflightDeniedOutcome,
    PluginPreflightPendingApprovalOutcome,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import PluginSource
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    SessionCapabilityOwnerAuthorityGate,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCapabilityProviderOwnerBinding,
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
    ProductPluginCompositionAssembly,
    ProductPluginCompositionAssemblyRequest,
    ProductPluginCompositionPreparation,
    ProductPluginPlanSeed,
    ProductPluginSelectionSeed,
    prepare_product_plugin_composition,
)

_BASE_PLUGIN_ID = "coding.base"
_TOOL_OWNER_ID = "coding.tools"
_LSP_PLUGIN_ID = "coding.lsp.default"
_LSP_PROVIDER_ID = "coding.lsp.default"
_LSP_TOOL_CATALOG_ID = "coding.lsp.tools"
_LSP_PROVIDER_CONTRIBUTION_ID = "coding-lsp-default"
_LSP_TOOL_CONTRIBUTION_ID = "coding-lsp-tools"
_ARCH_PLUGIN_ID = "coding.arch.default"
_ARCH_PROVIDER_ID = "coding.arch.default"
_ARCH_TOOL_CATALOG_ID = "coding.arch.tools"
_ARCH_PROVIDER_CONTRIBUTION_ID = "coding-arch-default"
_ARCH_TOOL_CONTRIBUTION_ID = "coding-arch-tools"
_PRODUCT_POLICY_REVISION = "coding-capability-plugins-2"
_SOURCE_TRUST_CLASS = "host-equivalent-local"
_SOURCE_TRUST_POLICY_REVISION = "coding-capability-plugin-source-trust-2"
_LSP_PROVIDER_OWNER_POLICY_REVISION = "coding-lsp-owner-1"
_ARCH_PROVIDER_OWNER_POLICY_REVISION = "coding-arch-owner-1"
_TOOL_OWNER_POLICY_REVISION = "coding-capability-tools-owner-2"
_DEFAULT_APPROVAL_ACTOR_ID = "product:coding"
_DEFAULT_APPROVAL_SOURCE = "coding-capability-plugin-product-policy"
# Keep Product-issued activation authority live for the full default Provider
# admission window. Both remain bounded; the Session still has to recompose once
# the 300-second admission expires.
_DEFAULT_APPROVAL_TTL_MS = 300_000
_DEFAULT_DEFINITION_ENTRYPOINT = "definition.py:declare"
_PLUGIN_IDS = frozenset({_LSP_PLUGIN_ID, _ARCH_PLUGIN_ID})


class CodingCapabilityPluginApprovalOwner(Protocol):
    """Sole issuer ports retained by one Product-owned composition request."""

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1: ...

    def approve_activation(
        self,
        *,
        journal: PluginActivationDecisionJournal,
        subject: ContributionActivationApprovalSubject,
    ) -> PluginActivationDecisionRecordV1: ...


class CodingCapabilityPluginCompositionError(RuntimeError):
    """Stable fail-closed Product error before Session composition exists."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingCapabilityPluginCompositionRequest:
    """Product request carrying approval issuance, never authority facts."""

    approval_owner: CodingCapabilityPluginApprovalOwner = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not all(
            callable(getattr(self.approval_owner, member, None))
            for member in ("approve_definition", "approve_activation")
        ):
            raise TypeError("Coding Capability composition requires an Approval owner")


@dataclass(frozen=True, slots=True)
class _CodingDefaultCapabilityPluginApprovalOwner:
    """Approve only Coding's selected checked-in Capability Plugin closure."""

    clock: Callable[[], int] = field(repr=False, compare=False)
    plugin_ids: frozenset[str]
    approval_source: str = _DEFAULT_APPROVAL_SOURCE
    product_policy_revision: str = _PRODUCT_POLICY_REVISION

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1:
        _validate_default_definition_subject(
            subject,
            plugin_ids=self.plugin_ids,
            product_policy_revision=self.product_policy_revision,
        )
        now = _read_clock(self.clock)
        return journal.issue_execution_decision(
            subject,
            disposition="approved",
            authorization=_default_approval_authorization(self.approval_source),
            revocation_epoch=0,
            issued_at_unix_ms=now,
            expires_at_unix_ms=now + _DEFAULT_APPROVAL_TTL_MS,
            expected_journal_revision=journal.snapshot().journal_revision,
        )

    def approve_activation(
        self,
        *,
        journal: PluginActivationDecisionJournal,
        subject: ContributionActivationApprovalSubject,
    ) -> PluginActivationDecisionRecordV1:
        _validate_default_activation_subject(
            subject,
            plugin_ids=self.plugin_ids,
            product_policy_revision=self.product_policy_revision,
        )
        now = _read_clock(self.clock)
        return journal.issue_activation_decision(
            subject,
            disposition="approved",
            authorization=_default_approval_authorization(self.approval_source),
            issued_at_unix_ms=now,
            expires_at_unix_ms=now + _DEFAULT_APPROVAL_TTL_MS,
            expected_journal_revision=journal.snapshot().journal_revision,
        )


def create_coding_capability_plugin_composition_request(
    *,
    clock: Callable[[], int],
    plugin_ids: frozenset[str],
    approval_source: str = _DEFAULT_APPROVAL_SOURCE,
    product_policy_revision: str = _PRODUCT_POLICY_REVISION,
) -> CodingCapabilityPluginCompositionRequest:
    """Create Coding's exact-policy request for selected checked-in Plugins."""

    if not callable(clock):
        raise TypeError("Coding Capability Plugin Approval clock is invalid")
    if not plugin_ids or not plugin_ids.issubset(_PLUGIN_IDS):
        raise ValueError("Coding Capability Plugin selection is invalid")
    if not isinstance(approval_source, str) or not approval_source:
        raise ValueError("Coding Capability Plugin Approval source is invalid")
    if not isinstance(product_policy_revision, str) or not product_policy_revision:
        raise ValueError("Coding Capability Product policy revision is invalid")
    return CodingCapabilityPluginCompositionRequest(
        approval_owner=_CodingDefaultCapabilityPluginApprovalOwner(
            clock=clock,
            plugin_ids=plugin_ids,
            approval_source=approval_source,
            product_policy_revision=product_policy_revision,
        )
    )


@dataclass(slots=True)
class CodingCapabilityPluginCompositionAssembly:
    """Approved Product closure awaiting bootstrap and Graph ownership transfer."""

    runtime: PluginRuntimeResolution = field(repr=False)
    selection: PluginSelection
    plugin_assembly: ProductPluginCompositionAssembly
    component_host: CapabilityComponentHost = field(repr=False)
    session_inputs: SessionCapabilityCompositionInputs
    lsp_tool_owner: CodingLspToolOwner | None = field(repr=False)
    arch_tool_owner: CodingArchToolOwner | None = field(repr=False)
    provider_owner_authorities: Mapping[str, CapabilityProviderOwnerAuthority] = field(
        repr=False
    )
    tool_owner_authority: OwnerContributionAuthority = field(repr=False)
    scope_id: str
    state_root: Path
    state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    private_state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _runtime_closed: bool = field(default=False, init=False, repr=False)
    _state_cleaned: bool = field(default=False, init=False, repr=False)
    _private_state_cleaned: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def tool_owner(self) -> CodingLspToolOwner:
        """Compatibility view for the original LSP-only Product adapter."""

        if self.lsp_tool_owner is None:
            raise RuntimeError("Coding LSP Tool owner is not selected")
        return self.lsp_tool_owner

    @property
    def provider_owner_authority(self) -> CapabilityProviderOwnerAuthority:
        """Compatibility view for the original LSP-only Product adapter."""

        return self.provider_owner_authorities[
            CODING_LSP_CAPABILITY_DEFINITION.capability_id
        ]

    def close(self) -> None:
        """Release verified revision handles before ownership transfers to Session."""

        if self._closed:
            return
        steps = []
        if not self._runtime_closed:

            def close_runtime() -> None:
                self.runtime.close()
                self._runtime_closed = True

            steps.append(("Coding LSP runtime cleanup", close_runtime))
        if not self._state_cleaned:

            def clean_state() -> None:
                if self.state_cleanup is not None:
                    self.state_cleanup()
                self._state_cleaned = True

            steps.append(("Coding LSP state cleanup", clean_state))
        primary_error = run_cleanup_steps(None, steps)
        self._closed = self._runtime_closed and self._state_cleaned
        if primary_error is not None:
            raise primary_error

    def cleanup_private_state(self) -> None:
        """Delete disposable private data only after Provider retirement."""

        if self._private_state_cleaned:
            return
        if self.private_state_cleanup is not None:
            self.private_state_cleanup()
        self._private_state_cleaned = True


@dataclass(slots=True)
class CodingCapabilityPluginCompositionPreparation:
    """Definition-approved closure compiled before host Provider construction."""

    request: CodingCapabilityPluginCompositionRequest = field(repr=False)
    runtime: PluginRuntimeResolution = field(repr=False)
    selection: PluginSelection
    product: ProductPluginCompositionPreparation
    provider_owner_authorities: Mapping[str, CapabilityProviderOwnerAuthority] = field(
        repr=False
    )
    tool_owner_authority: OwnerContributionAuthority = field(repr=False)
    scope_id: str
    state_root: Path
    state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    private_state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _runtime_closed: bool = field(default=False, init=False, repr=False)
    _state_cleaned: bool = field(default=False, init=False, repr=False)
    _private_state_cleaned: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _transferred: bool = field(default=False, init=False, repr=False)

    @property
    def product_composition(self):
        return self.product.product_composition

    def bind_workspace(
        self,
        workspace_binding: CapabilityBundleProviderBinding,
        *,
        host_boot_id: str,
        tool_modes: Mapping[str, CapabilityMountMode] | None = None,
        tool_mode: CapabilityMountMode | None = None,
        clock: Callable[[], int],
    ) -> CodingCapabilityPluginCompositionAssembly:
        if self._closed or self._transferred:
            raise RuntimeError(
                "Coding Capability Plugin preparation is no longer available"
            )
        resolved_tool_modes = tool_modes
        if resolved_tool_modes is None:
            if (
                tool_mode is None
                or frozenset(self.provider_owner_authorities)
                != frozenset({CODING_LSP_CAPABILITY_DEFINITION.capability_id})
            ):
                raise ValueError("Coding Capability Tool modes are unavailable")
            resolved_tool_modes = {
                CODING_LSP_CAPABILITY_DEFINITION.capability_id: tool_mode
            }
        elif tool_mode is not None:
            raise ValueError("Coding Capability Tool modes were supplied twice")
        _validate_workspace_binding(
            workspace_binding,
            host_boot_id=host_boot_id,
            tool_modes=resolved_tool_modes,
            selected_capability_ids=frozenset(
                self.provider_owner_authorities.keys()
            ),
            clock=clock,
        )
        try:
            plugin_assembly = self.product.bind_host_providers(
                (workspace_binding.provider,)
            )
            component_host, session_inputs = _approve_activation_and_bind_inputs(
                self.selection,
                plugin_assembly,
                request=self.request,
                provider_authorities=self.provider_owner_authorities,
                scope_id=self.scope_id,
                state_root=self.state_root,
                host_boot_id=host_boot_id,
                clock=clock,
            )
            lsp_tool_owner, arch_tool_owner = _build_tool_owners(
                self.selection,
                plugin_assembly,
                authority=self.tool_owner_authority,
                scope_id=self.scope_id,
                tool_modes=resolved_tool_modes,
                clock=clock,
            )
        except BaseException as error:
            run_cleanup_steps(
                error,
                (("Coding Capability Plugin preparation cleanup", self.close),),
            )
            raise
        self._transferred = True
        return CodingCapabilityPluginCompositionAssembly(
            runtime=self.runtime,
            selection=self.selection,
            plugin_assembly=plugin_assembly,
            component_host=component_host,
            session_inputs=session_inputs,
            lsp_tool_owner=lsp_tool_owner,
            arch_tool_owner=arch_tool_owner,
            provider_owner_authorities=self.provider_owner_authorities,
            tool_owner_authority=self.tool_owner_authority,
            scope_id=self.scope_id,
            state_root=self.state_root,
            state_cleanup=self.state_cleanup,
            private_state_cleanup=self.private_state_cleanup,
        )

    def close(self) -> None:
        if self._closed or self._transferred:
            return
        steps = []
        if not self._runtime_closed:

            def close_runtime() -> None:
                self.runtime.close()
                self._runtime_closed = True

            steps.append(("Coding Capability Plugin runtime cleanup", close_runtime))
        if not self._state_cleaned:

            def clean_state() -> None:
                if self.state_cleanup is not None:
                    self.state_cleanup()
                self._state_cleaned = True

            steps.append(("Coding Capability Plugin state cleanup", clean_state))
        if not self._private_state_cleaned:

            def clean_private_state() -> None:
                if self.private_state_cleanup is not None:
                    self.private_state_cleanup()
                self._private_state_cleaned = True

            steps.append(
                ("Coding Capability Plugin private-state cleanup", clean_private_state)
            )
        primary_error = run_cleanup_steps(None, steps)
        self._closed = (
            self._runtime_closed
            and self._state_cleaned
            and self._private_state_cleaned
        )
        if primary_error is not None:
            raise primary_error


def prepare_coding_capability_plugin_composition(
    request: CodingCapabilityPluginCompositionRequest,
    *,
    session_id: str,
    configurations: Mapping[str, CodingLspPluginConfigV1 | CodingArchPluginConfigV1],
    package_materializer: CodingPackageMaterializer,
    state_root: str | Path,
    clock: Callable[[], int],
    coding_base_plugin_assembly: CodingBasePluginAssembly | None = None,
    coding_product_plan_seed: ProductPluginPlanSeed | None = None,
    state_cleanup: Callable[[], None] | None = None,
    private_state_cleanup: Callable[[], None] | None = None,
) -> CodingCapabilityPluginCompositionPreparation:
    """Resolve, approve and compile once without constructing host Providers."""

    _validate_preparation_inputs(
        request,
        session_id=session_id,
        configurations=configurations,
        package_materializer=package_materializer,
        clock=clock,
        coding_base_plugin_assembly=coding_base_plugin_assembly,
        coding_product_plan_seed=coding_product_plan_seed,
    )
    _read_clock(clock)
    if state_cleanup is not None and not callable(state_cleanup):
        raise TypeError("Coding Capability Plugin state cleanup is invalid")
    if private_state_cleanup is not None and not callable(private_state_cleanup):
        raise TypeError("Coding Capability Plugin private-state cleanup is invalid")
    resolved_state_root = Path(state_root).expanduser().resolve()
    scope_id = f"session:{session_id.strip()}"

    try:
        resolved_state_root.mkdir(parents=True, exist_ok=True)
        authority = PluginResolutionAuthority()
        roots = {
            _LSP_PLUGIN_ID: coding_lsp_default_plugin_root,
            _ARCH_PLUGIN_ID: coding_arch_default_plugin_root,
        }
        inspections = tuple(
            authority.inspect(PluginSource(path=roots[plugin_id]()))
            for plugin_id in sorted(configurations)
        )
        runtime = authority.publish_runtime(
            inspections,
            binding_store=package_materializer,
        )
    except BaseException as error:
        if state_cleanup is not None:
            try:
                state_cleanup()
            except BaseException as cleanup_error:
                error.add_note(
                    "Coding Capability Plugin state cleanup also failed: "
                    f"{cleanup_error}"
                )
        if private_state_cleanup is not None:
            try:
                private_state_cleanup()
            except BaseException as cleanup_error:
                error.add_note(
                    "Coding Capability Plugin private-state cleanup also failed: "
                    f"{cleanup_error}"
                )
        raise
    try:
        resolved_product_seed = coding_product_plan_seed or (
            coding_base_plugin_assembly.plan_seed
            if coding_base_plugin_assembly is not None
            else None
        )
        tool_authority = _tool_owner_authority(frozenset(configurations))
        plan_seed = _prepare_selection_plan_seed(
            runtime,
            scope_id=scope_id,
            configurations=configurations,
            coding_product_plan_seed=resolved_product_seed,
            tool_authority=tool_authority,
        )
        selection = _finalize_selection(
            plan_seed,
            request=request,
            scope_id=scope_id,
            state_root=resolved_state_root,
            clock=clock,
        )
        selection_seed = complete_coding_package_plugin_selection_seed(
            plan_seed,
            selection=selection,
        )
        provider_authorities = _provider_owner_authorities(
            frozenset(configurations)
        )
        product = prepare_product_plugin_composition(
            _assembly_request(
                selection_seed,
                provider_authorities=provider_authorities,
            ),
            evaluated_at=_read_clock(clock),
        )
        return CodingCapabilityPluginCompositionPreparation(
            request=request,
            runtime=runtime,
            selection=selection,
            product=product,
            provider_owner_authorities=provider_authorities,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=resolved_state_root,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )
    except BaseException as error:
        try:
            runtime.close()
        except BaseException as cleanup_error:
            error.add_note(
                "Coding Capability Plugin revision cleanup also failed: "
                f"{cleanup_error}"
            )
        if state_cleanup is not None:
            try:
                state_cleanup()
            except BaseException as cleanup_error:
                error.add_note(
                    "Coding Capability Plugin state cleanup also failed: "
                    f"{cleanup_error}"
                )
        if private_state_cleanup is not None:
            try:
                private_state_cleanup()
            except BaseException as cleanup_error:
                error.add_note(
                    "Coding Capability Plugin private-state cleanup also failed: "
                    f"{cleanup_error}"
                )
        raise


def _build_tool_owners(
    selection: PluginSelection,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    authority: OwnerContributionAuthority,
    scope_id: str,
    tool_modes: Mapping[str, CapabilityMountMode],
    clock: Callable[[], int],
) -> tuple[CodingLspToolOwner | None, CodingArchToolOwner | None]:
    trust_snapshots = selection.plan.source_trust_snapshots

    def read_owner(
        owner_id: str,
        contribution_kind: str,
        product_id: str,
    ) -> OwnerContributionSnapshot:
        policy = authority.policy
        if (
            owner_id != policy.owner_id
            or contribution_kind != policy.contribution_kind
            or product_id != policy.product_id
        ):
            raise ValueError("Coding Tool owner reader received another owner")
        return authority.snapshot()

    def read_trust(
        plugin_id: str,
        source_identity: str,
    ) -> PluginSourceTrustSnapshotV1:
        matches = tuple(
            item
            for item in trust_snapshots
            if item.plugin_id == plugin_id
            and item.package_source_identity == source_identity
        )
        if len(matches) != 1:
            raise ValueError("Coding Tool owner requires one trust snapshot")
        return matches[0]

    def read_product_policy(product_id: str, requested_scope_id: str) -> str:
        if product_id != CODING_PRODUCT_ID or requested_scope_id != scope_id:
            raise ValueError("Coding Tool owner received another Product scope")
        return selection.plan.context.policy_revision

    gate = SessionCapabilityOwnerAuthorityGate(
        authority_context=(plugin_assembly.product_composition.authority_context),
        owner_snapshot_reader=read_owner,
        trust_snapshot_reader=read_trust,
        product_policy_revision_reader=read_product_policy,
        clock=clock,
    )
    admissions = plugin_assembly.product_composition.catalog_admissions

    def exact_admission(plugin_id: str, contribution_id: str):
        matches = tuple(
            item
            for item in admissions
            if item.plugin_id == plugin_id
            and item.contribution_id == contribution_id
            and item.owner_id == _TOOL_OWNER_ID
            and item.contribution_kind == "tool_pack"
        )
        if len(matches) != 1:
            raise ValueError(
                f"Coding Tool owner requires one exact admission for {plugin_id}"
            )
        return matches[0]

    lsp_owner = (
        CodingLspToolOwner(
            admission=exact_admission(
                _LSP_PLUGIN_ID,
                _LSP_TOOL_CONTRIBUTION_ID,
            ),
            authority_gate=gate,
            mode=tool_modes[CODING_LSP_CAPABILITY_DEFINITION.capability_id],
            scope_id=scope_id,
        )
        if _LSP_PLUGIN_ID in selection.plan.selected_plugin_ids
        else None
    )
    arch_owner = (
        CodingArchToolOwner(
            admission=exact_admission(
                _ARCH_PLUGIN_ID,
                _ARCH_TOOL_CONTRIBUTION_ID,
            ),
            authority_gate=gate,
            mode=tool_modes[CODING_ARCH_CAPABILITY_DEFINITION.capability_id],
            scope_id=scope_id,
        )
        if _ARCH_PLUGIN_ID in selection.plan.selected_plugin_ids
        else None
    )
    return lsp_owner, arch_owner


def _approve_activation_and_bind_inputs(
    selection: PluginSelection,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    request: CodingCapabilityPluginCompositionRequest,
    provider_authorities: Mapping[str, CapabilityProviderOwnerAuthority],
    scope_id: str,
    state_root: Path,
    host_boot_id: str,
    clock: Callable[[], int],
) -> tuple[CapabilityComponentHost, SessionCapabilityCompositionInputs]:
    legacy_lsp_only = _ARCH_PLUGIN_ID not in selection.plan.selected_plugin_ids
    journal = PluginActivationDecisionJournal(
        state_root / "activation-decisions.jsonl",
        scope_id=scope_id,
        clock=clock,
    )
    trust_snapshots = selection.plan.source_trust_snapshots

    def read_owner(capability_id: str) -> CapabilityProviderOwnerSnapshot:
        try:
            return provider_authorities[capability_id].snapshot()
        except KeyError as exc:
            raise ValueError(
                "Coding owner reader received another Capability"
            ) from exc

    def read_trust(
        plugin_id: str,
        source_identity: str,
    ) -> PluginSourceTrustSnapshotV1:
        matches = tuple(
            item
            for item in trust_snapshots
            if item.plugin_id == plugin_id
            and item.package_source_identity == source_identity
        )
        if len(matches) != 1:
            raise ValueError("Coding trust reader requires one exact snapshot")
        return matches[0]

    def read_product_policy(product_id: str, requested_scope_id: str) -> str:
        if product_id != CODING_PRODUCT_ID or requested_scope_id != scope_id:
            raise ValueError("Coding policy reader received another Product scope")
        return selection.plan.context.policy_revision

    component_host = CapabilityComponentHost(
        decision_journal=journal,
        import_realm=PluginImportRealm(),
        host_boot_id=host_boot_id,
        clock=clock,
        owner_snapshot_reader=read_owner,
        trust_snapshot_reader=read_trust,
        product_policy_revision_reader=read_product_policy,
        distribution_evidence_resolver=(coding_plugin_distribution_evidence_resolver()),
    )
    decision_ids: dict[str, str] = {}
    for candidate in plugin_assembly.component_candidates:
        subject = component_host.activation_subject(
            candidate.resolved,
            owner_snapshot=candidate.owner_snapshot,
            trust_snapshot=candidate.trust_snapshot,
        )
        decision = request.approval_owner.approve_activation(
            journal=journal,
            subject=subject,
        )
        if not isinstance(decision, PluginActivationDecisionRecordV1):
            raise TypeError(
                "Coding Capability Activation Approval owner returned invalid evidence"
            )
        recorded = next(
            (
                item
                for item in journal.snapshot().decisions
                if item.decision_id == decision.decision_id
            ),
            None,
        )
        if recorded != decision or decision.subject_digest != subject.digest:
            raise CodingCapabilityPluginCompositionError(
                "Coding Capability activation approval does not match its Subject.",
                code=(
                    "coding_lsp_plugin_activation_approval_mismatch"
                    if legacy_lsp_only
                    else "coding_capability_plugin_activation_approval_mismatch"
                ),
            )
        if decision.disposition != "approved":
            raise CodingCapabilityPluginCompositionError(
                "Coding Capability Plugin activation was not approved.",
                code=(
                    "coding_lsp_plugin_activation_denied"
                    if legacy_lsp_only
                    else "coding_capability_plugin_activation_denied"
                ),
            )
        if decision.consumption_state != "AVAILABLE":
            raise CodingCapabilityPluginCompositionError(
                "Coding Capability Plugin activation decision is not available.",
                code=(
                    "coding_lsp_plugin_activation_not_available"
                    if legacy_lsp_only
                    else "coding_capability_plugin_activation_not_available"
                ),
            )
        decision_ids[candidate.capability_id] = decision.decision_id
    return (
        component_host,
        plugin_assembly.bind_session_inputs(decision_ids),
    )


def _finalize_selection(
    seed: ProductPluginPlanSeed,
    *,
    request: CodingCapabilityPluginCompositionRequest,
    scope_id: str,
    state_root: Path,
    clock: Callable[[], int],
) -> PluginSelection:
    legacy_lsp_only = _ARCH_PLUGIN_ID not in seed.plan.selected_plugin_ids
    journal = PluginExecutionDecisionJournal(
        state_root / "definition-decisions.jsonl",
        scope_kind="workspace",
        scope_id=scope_id,
        clock=clock,
    )
    host = PluginDeclarationHost(
        execution_evaluator=PluginDefinitionEvaluator(
            decision_journal=journal,
            import_realm=PluginImportRealm(),
            clock=clock,
            distribution_evidence_resolver=(
                coding_plugin_distribution_evidence_resolver()
            ),
        )
    )
    outcome = host.resolve(
        seed.packages,
        bindings=seed.bindings,
        plan=seed.plan,
        decision_lookup=journal,
    )
    if isinstance(outcome, PluginPreflightPendingApprovalOutcome):
        for subject in outcome.subjects:
            decision = request.approval_owner.approve_definition(
                journal=journal,
                subject=subject,
            )
            if not isinstance(decision, PluginApprovalDecisionRecordV1):
                raise TypeError(
                    "Coding Capability Definition Approval owner returned invalid evidence"
                )
            if decision.subject_digest != subject.digest:
                raise CodingCapabilityPluginCompositionError(
                    "Coding Capability Definition approval does not match its Subject.",
                    code=(
                        "coding_lsp_plugin_definition_approval_mismatch"
                        if legacy_lsp_only
                        else "coding_capability_plugin_definition_approval_mismatch"
                    ),
                )
        outcome = host.resolve(
            seed.packages,
            bindings=seed.bindings,
            plan=seed.plan,
            decision_lookup=journal,
        )
    if not isinstance(outcome, PluginSelection):
        disposition = outcome.disposition
        raise CodingCapabilityPluginCompositionError(
            "Coding Capability Plugin Definition was not approved.",
            code=(
                (
                    "coding_lsp_plugin_definition_denied"
                    if legacy_lsp_only
                    else "coding_capability_plugin_definition_denied"
                )
                if isinstance(outcome, PluginPreflightDeniedOutcome)
                else (
                    f"coding_lsp_plugin_definition_{disposition}"
                    if legacy_lsp_only
                    else f"coding_capability_plugin_definition_{disposition}"
                )
            ),
        )
    return outcome


def _prepare_selection_plan_seed(
    runtime: PluginRuntimeResolution,
    *,
    scope_id: str,
    configurations: Mapping[str, CodingLspPluginConfigV1 | CodingArchPluginConfigV1],
    coding_product_plan_seed: ProductPluginPlanSeed | None,
    tool_authority: OwnerContributionAuthority,
) -> ProductPluginPlanSeed:
    package_bindings = tuple(
        zip(runtime.packages, runtime.bindings, strict=True)
    )
    base_plan = coding_product_plan_seed.plan if coding_product_plan_seed else None
    policy_revision = (
        base_plan.context.policy_revision
        if base_plan is not None
        else _PRODUCT_POLICY_REVISION
    )
    base_instance_refs = (
        base_plan.context.instance_revision_refs if base_plan is not None else ()
    )
    base_plugin_ids = base_plan.selected_plugin_ids if base_plan is not None else ()
    base_contributions = (
        base_plan.selected_contributions if base_plan is not None else ()
    )
    base_trust = base_plan.source_trust_snapshots if base_plan is not None else ()
    base_config_entries = (
        base_plan.effective_configuration_set.entries if base_plan is not None else ()
    )
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id=CODING_PRODUCT_ID,
            scope_id=scope_id,
            policy_revision=policy_revision,
            instance_revision_refs=tuple(
                sorted(
                    (
                        *base_instance_refs,
                        *tuple(
                            PluginInstanceRevisionRef(
                                instance_id=f"{plugin_id}@{scope_id}",
                                plugin_id=plugin_id,
                                revision=1,
                            )
                            for plugin_id in sorted(configurations)
                        ),
                    ),
                    key=lambda item: (
                        item.plugin_id,
                        item.instance_id,
                        item.revision,
                    ),
                )
            ),
        ),
        selected_plugin_ids=tuple(
            sorted((*base_plugin_ids, *configurations.keys()))
        ),
        selected_contributions=tuple(
            sorted(
                (
                    *base_contributions,
                    *tuple(
                        PluginContributionRef(
                            package.manifest.name,
                            item.contribution_id,
                        )
                        for package, _binding in package_bindings
                        for item in package.contribution_index.items
                    )
                )
            )
        ),
        source_trust_snapshots=tuple(
            sorted(
                (
                    *base_trust,
                    *tuple(
                        PluginSourceTrustSnapshotV1(
                            plugin_id=package.manifest.name,
                            package_source_identity=binding.source_identity,
                            source_trust_class=_SOURCE_TRUST_CLASS,
                            source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
                            trusted=True,
                        )
                        for package, binding in package_bindings
                    ),
                ),
                key=lambda item: (item.plugin_id, item.package_source_identity),
            )
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                sorted(
                    (
                        *base_config_entries,
                        *tuple(
                            PluginEffectiveConfigurationEntry(
                                plugin_id=package.manifest.name,
                                contribution_id=item.contribution_id,
                                configuration=(
                                    configurations[package.manifest.name].to_dict()
                                    if item.kind == "capability_provider"
                                    else {}
                                ),
                            )
                            for package, _binding in package_bindings
                            for item in package.contribution_index.items
                        ),
                    ),
                    key=lambda item: (item.plugin_id, item.contribution_id),
                )
            )
        ),
        allowed_authority_ceiling=("filesystem", "process"),
    )
    all_package_bindings = tuple(
        sorted(
            (
                *(
                    tuple(
                        zip(
                            coding_product_plan_seed.packages,
                            coding_product_plan_seed.bindings,
                            strict=True,
                        )
                    )
                    if coding_product_plan_seed is not None
                    else ()
                ),
                *package_bindings,
            ),
            key=lambda item: item[0].manifest.name,
        )
    )
    return ProductPluginPlanSeed(
        plan=plan,
        packages=tuple(item[0] for item in all_package_bindings),
        bindings=tuple(item[1] for item in all_package_bindings),
        owner_bindings=(
            *(
                coding_product_plan_seed.owner_bindings
                if coding_product_plan_seed is not None
                else ()
            ),
            ProductContributionOwnerBinding(authority=tool_authority),
        ),
    )


def _assembly_request(
    selection_seed: ProductPluginSelectionSeed,
    *,
    provider_authorities: Mapping[str, CapabilityProviderOwnerAuthority],
) -> ProductPluginCompositionAssemblyRequest:
    def select(
        admissions: tuple[CapabilityProviderAdmissionRecord, ...],
    ) -> tuple[ProductCapabilityProviderChoice, ...]:
        return tuple(
            ProductCapabilityProviderChoice(
                capability_id=item.capability_id,
                provider_id=item.provider.provider_id,
                candidate_fingerprint=item.candidate_fingerprint,
            )
            for item in admissions
            if item.capability_id in provider_authorities
            and item.provider.provider_id
            == provider_authorities[item.capability_id].policy.allowed_provider_ids[0]
        )

    return ProductPluginCompositionAssemblyRequest(
        contribution_request=ProductCompositionAssemblyRequest(
            selection=selection_seed.selection,
            owner_bindings=selection_seed.owner_bindings,
            mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=tuple(
                item
                for item in (
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
                CODING_LSP_CAPABILITY_DEFINITION,
                CODING_ARCH_CAPABILITY_DEFINITION,
                )
                if item.capability_id in provider_authorities
                or item.capability_id
                in {
                    MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
                    WORKSPACE_CAPABILITY_DEFINITION.capability_id,
                }
            ),
        ),
        provider_owner_bindings=tuple(
            ProductCapabilityProviderOwnerBinding(
                authority=authority,
            )
            for _capability_id, authority in sorted(provider_authorities.items())
        ),
        provider_roots=tuple(sorted(provider_authorities)),
        host_capability_ids=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        ),
        select_capability_providers=select,
    )


def _provider_owner_authorities(
    plugin_ids: frozenset[str],
) -> dict[str, CapabilityProviderOwnerAuthority]:
    specs = {
        _LSP_PLUGIN_ID: (
            CODING_LSP_CAPABILITY_DEFINITION,
            _LSP_PROVIDER_ID,
            _LSP_PROVIDER_OWNER_POLICY_REVISION,
        ),
        _ARCH_PLUGIN_ID: (
            CODING_ARCH_CAPABILITY_DEFINITION,
            _ARCH_PROVIDER_ID,
            _ARCH_PROVIDER_OWNER_POLICY_REVISION,
        ),
    }
    return {
        definition.capability_id: CapabilityProviderOwnerAuthority(
            CapabilityProviderOwnerPolicy(
                capability_id=definition.capability_id,
                owner_id=definition.owner_id,
                policy_revision=policy_revision,
                revocation_epoch=0,
                allowed_provider_ids=(provider_id,),
                allowed_source_trust_classes=(_SOURCE_TRUST_CLASS,),
                authority_ceiling=tuple(sorted(definition.authority_ceiling)),
            )
        )
        for plugin_id in sorted(plugin_ids)
        for definition, provider_id, policy_revision in (specs[plugin_id],)
    }


def _tool_owner_authority(plugin_ids: frozenset[str]) -> OwnerContributionAuthority:
    catalogs = {
        _LSP_PLUGIN_ID: _LSP_TOOL_CATALOG_ID,
        _ARCH_PLUGIN_ID: _ARCH_TOOL_CATALOG_ID,
    }
    return OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=_TOOL_OWNER_ID,
            contribution_kind="tool_pack",
            product_id=CODING_PRODUCT_ID,
            policy_revision=_TOOL_OWNER_POLICY_REVISION,
            revocation_epoch=0,
            allowed_source_trust_classes=(_SOURCE_TRUST_CLASS,),
            allowed_collection_ids=tuple(
                sorted(catalogs[plugin_id] for plugin_id in plugin_ids)
            ),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    )


def _validate_default_definition_subject(
    subject: PluginExecutionApprovalSubject,
    *,
    plugin_ids: frozenset[str],
    product_policy_revision: str,
) -> None:
    requested_authorities = {
        _LSP_PLUGIN_ID: ("filesystem", "process"),
        _ARCH_PLUGIN_ID: ("filesystem",),
    }
    if (
        subject.plugin_id not in plugin_ids
        or subject.product_id != CODING_PRODUCT_ID
        or not subject.scope_id.startswith("session:")
        or subject.scope_id == "session:"
        or subject.policy_revision != product_policy_revision
        or subject.entrypoint != _DEFAULT_DEFINITION_ENTRYPOINT
        or subject.source_trust_class != _SOURCE_TRUST_CLASS
        or subject.source_trust_policy_revision != _SOURCE_TRUST_POLICY_REVISION
        or subject.requested_authorities
        != requested_authorities.get(subject.plugin_id)
        or subject.allowed_authority_ceiling != ("filesystem", "process")
        or subject.instance_revision_ref.instance_id
        != f"{subject.plugin_id}@{subject.scope_id}"
        or subject.instance_revision_ref.plugin_id != subject.plugin_id
        or subject.instance_revision_ref.revision != 1
    ):
        raise CodingCapabilityPluginCompositionError(
            "Coding Capability Definition Subject is outside Product policy.",
            code=(
                "coding_lsp_default_definition_subject_rejected"
                if plugin_ids == frozenset({_LSP_PLUGIN_ID})
                else "coding_capability_definition_subject_rejected"
            ),
        )


def _validate_default_activation_subject(
    subject: ContributionActivationApprovalSubject,
    *,
    plugin_ids: frozenset[str],
    product_policy_revision: str,
) -> None:
    specs = {
        _LSP_PLUGIN_ID: (
            CODING_LSP_CAPABILITY_DEFINITION,
            _LSP_PROVIDER_ID,
            _LSP_PROVIDER_CONTRIBUTION_ID,
            _LSP_PROVIDER_OWNER_POLICY_REVISION,
        ),
        _ARCH_PLUGIN_ID: (
            CODING_ARCH_CAPABILITY_DEFINITION,
            _ARCH_PROVIDER_ID,
            _ARCH_PROVIDER_CONTRIBUTION_ID,
            _ARCH_PROVIDER_OWNER_POLICY_REVISION,
        ),
    }
    spec = specs.get(subject.plugin_id)
    if subject.plugin_id not in plugin_ids or spec is None:
        raise CodingCapabilityPluginCompositionError(
            "Coding Capability Activation Subject is outside Product policy.",
            code=(
                "coding_lsp_default_activation_subject_rejected"
                if plugin_ids == frozenset({_LSP_PLUGIN_ID})
                else "coding_capability_activation_subject_rejected"
            ),
        )
    definition, provider_id, contribution_id, owner_policy_revision = spec
    if (
        subject.capability_id != definition.capability_id
        or subject.owner_id != definition.owner_id
        or subject.provider_id != provider_id
        or subject.contribution_id != contribution_id
        or subject.product_id != CODING_PRODUCT_ID
        or not subject.scope_id.startswith("session:")
        or subject.scope_id == "session:"
        or subject.source_trust_class != _SOURCE_TRUST_CLASS
        or subject.source_trust_policy_revision != _SOURCE_TRUST_POLICY_REVISION
        or subject.product_policy_revision != product_policy_revision
        or subject.owner_policy_revision != owner_policy_revision
        or subject.revocation_epoch != 0
        or subject.effective_facets
        != tuple(sorted(definition.facets))
        or subject.effective_authorities
        != tuple(sorted(definition.authority_ceiling))
        or subject.execution_model != "in_process"
        or subject.instance_revision_ref.instance_id
        != f"{subject.plugin_id}@{subject.scope_id}"
        or subject.instance_revision_ref.plugin_id != subject.plugin_id
        or subject.instance_revision_ref.revision != 1
    ):
        raise CodingCapabilityPluginCompositionError(
            "Coding Capability Activation Subject is outside Product policy.",
            code=(
                "coding_lsp_default_activation_subject_rejected"
                if plugin_ids == frozenset({_LSP_PLUGIN_ID})
                else "coding_capability_activation_subject_rejected"
            ),
        )


def _default_approval_authorization(source: str) -> PluginApprovalAuthorizationV1:
    return PluginApprovalAuthorizationV1.direct(
        actor_id=_DEFAULT_APPROVAL_ACTOR_ID,
        source=source,
    )


def _validate_preparation_inputs(
    request: CodingCapabilityPluginCompositionRequest,
    *,
    session_id: str,
    configurations: Mapping[str, CodingLspPluginConfigV1 | CodingArchPluginConfigV1],
    package_materializer: CodingPackageMaterializer,
    clock: Callable[[], int],
    coding_base_plugin_assembly: CodingBasePluginAssembly | None,
    coding_product_plan_seed: ProductPluginPlanSeed | None,
) -> None:
    if not isinstance(request, CodingCapabilityPluginCompositionRequest):
        raise TypeError("Coding Capability Plugin composition request is invalid")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Coding Capability Plugin Session id must not be empty")
    if not isinstance(configurations, Mapping):
        raise TypeError("Coding Capability Plugin configurations are invalid")
    plugin_ids = frozenset(configurations)
    if not plugin_ids or not plugin_ids.issubset(_PLUGIN_IDS):
        raise ValueError("Coding Capability Plugin configurations are invalid")
    if (
        _LSP_PLUGIN_ID in configurations
        and not isinstance(configurations[_LSP_PLUGIN_ID], CodingLspPluginConfigV1)
    ) or (
        _ARCH_PLUGIN_ID in configurations
        and not isinstance(configurations[_ARCH_PLUGIN_ID], CodingArchPluginConfigV1)
    ):
        raise TypeError("Coding Capability Plugin configuration type is invalid")
    if not isinstance(package_materializer, CodingPackageMaterializer):
        raise TypeError("Coding Capability Plugins require Coding materialization")
    if coding_base_plugin_assembly is not None:
        if not isinstance(coding_base_plugin_assembly, CodingBasePluginAssembly):
            raise TypeError("Coding Capability Plugin base assembly is invalid")
        expected_scope = f"session:{session_id.strip()}"
        if coding_base_plugin_assembly.scope_id != expected_scope:
            raise ValueError("Coding base and Capability Plugin scopes do not match")
        if coding_base_plugin_assembly.package.revision_handle.closed:
            raise RuntimeError("Coding base Plugin revision is unavailable")
    if coding_product_plan_seed is not None:
        if not isinstance(coding_product_plan_seed, ProductPluginPlanSeed):
            raise TypeError("Coding Capability Product plan seed is invalid")
        if (
            coding_base_plugin_assembly is not None
            and _BASE_PLUGIN_ID
            not in coding_product_plan_seed.plan.selected_plugin_ids
        ):
            raise ValueError("Coding Capability Product seed omits coding.base")
    if not callable(clock):
        raise TypeError("Coding Capability Plugin clock is invalid")


def _validate_workspace_binding(
    workspace_binding: CapabilityBundleProviderBinding,
    *,
    host_boot_id: str,
    tool_modes: Mapping[str, CapabilityMountMode],
    selected_capability_ids: frozenset[str],
    clock: Callable[[], int],
) -> None:
    if not isinstance(workspace_binding, CapabilityBundleProviderBinding):
        raise TypeError("Coding Capability Plugin workspace binding is invalid")
    if (
        workspace_binding.provider.capability_id
        != WORKSPACE_CAPABILITY_DEFINITION.capability_id
    ):
        raise ValueError("Coding Capability Plugins require harness.workspace")
    if not isinstance(host_boot_id, str):
        raise TypeError("Coding Capability Plugin Host boot id is invalid")
    if len(host_boot_id) != 32 or any(
        item not in "0123456789abcdefABCDEF" for item in host_boot_id
    ):
        raise ValueError("Coding Capability Plugin Host boot id must be 32 hex digits")
    if frozenset(tool_modes) != selected_capability_ids or any(
        mode not in {"on_demand", "always"} for mode in tool_modes.values()
    ):
        raise ValueError("Coding Capability Plugins require enabled Tool modes")
    if not callable(clock):
        raise TypeError("Coding Capability Plugin clock is invalid")


def _read_clock(clock: Callable[[], int]) -> int:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Coding Capability Plugin clock must return an integer")
    if value < 0:
        raise ValueError("Coding Capability Plugin time cannot be negative")
    return value


__all__ = [
    "CodingCapabilityPluginApprovalOwner",
    "CodingCapabilityPluginCompositionAssembly",
    "CodingCapabilityPluginCompositionError",
    "CodingCapabilityPluginCompositionPreparation",
    "CodingCapabilityPluginCompositionRequest",
    "create_coding_capability_plugin_composition_request",
    "prepare_coding_capability_plugin_composition",
]
