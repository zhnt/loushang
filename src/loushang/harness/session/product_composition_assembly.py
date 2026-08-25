"""Private Product-root assembly from finalized Plugin selection to compilation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from loushang.harness.capabilities.consumer_requirements import (
    ProductCapabilityConsumerRequirementPreview,
    ProductCapabilityOptionalRequirementChoice,
    ProductCompositionAuthorityContext,
    ProductCompositionCompilation,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.contracts import CapabilityDefinition
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
)
from loushang.harness.plugin_authoring.contribution_admission import (
    prepare_owner_contribution_candidate,
)
from loushang.harness.resources.plugins.selection import PluginSelection

ProductOptionalRequirementSelector = Callable[
    [ProductCapabilityConsumerRequirementPreview],
    tuple[ProductCapabilityOptionalRequirementChoice, ...],
]
_EXTERNAL_CONTRIBUTION_KINDS = frozenset({"resource_item", "tool_pack", "command_pack"})


class ProductCompositionAssemblyError(RuntimeError):
    """Stable Product-visible failure before contribution admission completes."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        owner_keys: tuple[tuple[str, str, str], ...] = (),
    ) -> None:
        self.code = code
        self.owner_keys = tuple(sorted(owner_keys))
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ProductContributionOwnerBinding:
    """One explicitly supplied exact owner plus its bounded admission lifetime."""

    authority: OwnerContributionAuthority = field(repr=False, compare=False)
    admission_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if not isinstance(self.authority, OwnerContributionAuthority):
            raise TypeError("Product contribution owner authority is invalid")
        if isinstance(self.admission_ttl_seconds, bool) or not isinstance(
            self.admission_ttl_seconds,
            int,
        ):
            raise TypeError("Product contribution admission TTL must be an integer")
        if self.admission_ttl_seconds < 1:
            raise ValueError("Product contribution admission TTL must be positive")

    @property
    def owner_key(self) -> tuple[str, str, str]:
        policy = self.authority.policy
        return (policy.owner_id, policy.contribution_kind, policy.product_id)

    def admit(
        self,
        candidate: OwnerContributionCandidateEnvelope,
        *,
        evaluated_at: int,
    ) -> OwnerContributionAdmissionRecord:
        return self.authority.admit(
            candidate,
            issued_at=evaluated_at,
            expires_at=evaluated_at + self.admission_ttl_seconds,
        )


@dataclass(frozen=True, slots=True)
class ProductCompositionAssemblyRequest:
    """Product-owned inert inputs for one exact contribution compilation."""

    selection: PluginSelection
    owner_bindings: tuple[ProductContributionOwnerBinding, ...]
    mandatory_roots: tuple[str, ...]
    definitions: tuple[CapabilityDefinition, ...]
    select_optional_requirements: ProductOptionalRequirementSelector = field(
        default=lambda _preview: (),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.selection, PluginSelection):
            raise TypeError("Product composition assembly requires PluginSelection")
        bindings = tuple(self.owner_bindings)
        if any(
            not isinstance(item, ProductContributionOwnerBinding) for item in bindings
        ):
            raise TypeError("Product composition owner bindings are invalid")
        if len({item.owner_key for item in bindings}) != len(bindings):
            raise ValueError("Product composition owner bindings must be unique")
        mandatory_roots = tuple(self.mandatory_roots)
        definitions = tuple(self.definitions)
        if any(not isinstance(item, str) for item in mandatory_roots):
            raise TypeError("Product composition mandatory roots are invalid")
        if any(not isinstance(item, CapabilityDefinition) for item in definitions):
            raise TypeError("Product composition Definitions are invalid")
        if not callable(self.select_optional_requirements):
            raise TypeError("Product optional requirement selector must be callable")
        object.__setattr__(self, "owner_bindings", bindings)
        object.__setattr__(self, "mandatory_roots", mandatory_roots)
        object.__setattr__(self, "definitions", definitions)


def assemble_product_composition(
    request: ProductCompositionAssemblyRequest,
    *,
    evaluated_at: int,
) -> ProductCompositionCompilation:
    """Admit one finalized selection through exact owners, then compile once."""

    if not isinstance(request, ProductCompositionAssemblyRequest):
        raise TypeError("Product composition assembly request is invalid")
    if isinstance(evaluated_at, bool) or not isinstance(evaluated_at, int):
        raise TypeError("Product composition evaluation time must be an integer")
    if evaluated_at < 0:
        raise ValueError("Product composition evaluation time cannot be negative")

    selection = request.selection
    candidates = tuple(
        prepare_owner_contribution_candidate(selection, item)
        for item in selection.candidates
        if item.declaration.kind in _EXTERNAL_CONTRIBUTION_KINDS
    )
    bindings_by_key = {item.owner_key: item for item in request.owner_bindings}
    required_keys = {
        (item.owner_id, item.contribution_kind, item.product_id) for item in candidates
    }
    supplied_keys = set(bindings_by_key)
    if missing := required_keys - supplied_keys:
        raise ProductCompositionAssemblyError(
            "Product composition is missing an exact contribution owner.",
            code="product_contribution_owner_missing",
            owner_keys=tuple(missing),
        )
    if extra := supplied_keys - required_keys:
        raise ProductCompositionAssemblyError(
            "Product composition supplied an unused contribution owner.",
            code="product_contribution_owner_extra",
            owner_keys=tuple(extra),
        )

    admissions = tuple(
        bindings_by_key[
            (candidate.owner_id, candidate.contribution_kind, candidate.product_id)
        ].admit(candidate, evaluated_at=evaluated_at)
        for candidate in candidates
    )
    owner_snapshots = tuple(
        item.authority.snapshot() for item in request.owner_bindings
    )
    context = selection.plan.context
    authority_context = ProductCompositionAuthorityContext(
        product_id=context.product_id,
        scope_id=context.scope_id,
        product_policy_revision=context.policy_revision,
        evaluated_at=evaluated_at,
        owner_snapshots=owner_snapshots,
        trust_snapshots=selection.plan.source_trust_snapshots,
    )
    compiler = ProductCompositionCompiler()
    preview = compiler.preview_optional_choices(
        authority_context=authority_context,
        mandatory_roots=request.mandatory_roots,
        admissions=admissions,
        definitions=request.definitions,
    )
    optional_choices = tuple(request.select_optional_requirements(preview))
    return compiler.compile(
        authority_context=authority_context,
        mandatory_roots=request.mandatory_roots,
        admissions=admissions,
        definitions=request.definitions,
        optional_choices=optional_choices,
    )


__all__: list[str] = []
