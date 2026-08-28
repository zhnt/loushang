"""Least-authority admission adapter for Plugin Continuity Providers."""

from __future__ import annotations

import hashlib
import hmac
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Protocol, TypeAlias, runtime_checkable

from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.continuity.composition import ContinuityProviderPack
from loushang.harness.continuity.provider import PreparedActivationLease
from loushang.harness.continuity.types import (
    ActivationDisposition,
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
    ProviderPage,
    ProviderPageItem,
    ProviderQuery,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginInstanceRevisionRef,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.runtime import (
    CONTINUITY_PROVIDER_PACKS_SLOT,
    RuntimeCapabilityImplementation,
    RuntimeCapabilitySelection,
    RuntimeProfileLayer,
    RuntimeProfileLayerGrant,
)

CONTINUITY_PLUGIN_PERMISSION = "continuity.provider"
CONTINUITY_PLUGIN_SCHEMA_VERSION = 1
CONTINUITY_JSONL_MEDIA_TYPE = "application/vnd.loushang.conversation+jsonl"
CONTINUITY_BUNDLE_MEDIA_TYPE = "application/vnd.loushang.session-bundle+zip"
MAX_CONTINUITY_ACTIVATION_BYTES = 64 * 1024 * 1024
MAX_CONTINUITY_PLUGIN_PROVIDERS = 32

_ACTIVATION_MEDIA_TYPES = frozenset(
    {CONTINUITY_JSONL_MEDIA_TYPE, CONTINUITY_BUNDLE_MEDIA_TYPE}
)


class ContinuityPluginAdmissionError(RuntimeError):
    """Stable fail-closed error from Plugin contribution admission or use."""

    def __init__(self, message: str, *, code: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ContinuityActivationPayload:
    """Bounded portable bytes prepared by a Plugin for Product import."""

    media_type: str
    data: bytes = field(repr=False)
    digest: str
    cwd_override: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported continuity activation payload version")
        if self.media_type not in _ACTIVATION_MEDIA_TYPES:
            raise ValueError("unsupported continuity activation media type")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("continuity activation data must be non-empty bytes")
        if len(self.data) > MAX_CONTINUITY_ACTIVATION_BYTES:
            raise ValueError("continuity activation payload exceeds the hard limit")
        if (
            not isinstance(self.digest, str)
            or len(self.digest) != 64
            or any(character not in "0123456789abcdef" for character in self.digest)
        ):
            raise ValueError("continuity activation digest must be SHA-256 hex")
        actual = hashlib.sha256(self.data).hexdigest()
        if not hmac.compare_digest(actual, self.digest):
            raise ValueError("continuity activation digest does not match its bytes")
        if self.cwd_override is not None and (
            not isinstance(self.cwd_override, str) or not self.cwd_override.strip()
        ):
            raise ValueError("continuity activation cwd override must be non-empty")

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        media_type: str,
        cwd_override: str | None = None,
    ) -> ContinuityActivationPayload:
        if not isinstance(data, bytes):
            raise TypeError("continuity activation data must be bytes")
        return cls(
            media_type=media_type,
            data=data,
            digest=hashlib.sha256(data).hexdigest(),
            cwd_override=cwd_override,
        )

    @property
    def byte_size(self) -> int:
        return len(self.data)

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "mediaType": self.media_type,
            "byteSize": self.byte_size,
            "digest": self.digest,
            "cwdOverride": self.cwd_override,
        }


@runtime_checkable
class PreparedContinuityImport(Protocol):
    """Plugin-owned, unpublished portable activation source."""

    @property
    def target(self) -> ContinuityTarget: ...

    @property
    def payload(self) -> ContinuityActivationPayload: ...

    async def abort(self) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class ContinuityImportProvider(Protocol):
    """Plugin-facing read-only Provider; mutation is deliberately absent."""

    @property
    def descriptor(self) -> ContinuityProviderDescriptor: ...

    async def query(self, request: ProviderQuery) -> ProviderPage: ...

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview: ...

    async def prepare_import(
        self,
        target: ContinuityTarget,
    ) -> PreparedContinuityImport: ...


@runtime_checkable
class ContinuityActivationBridge(Protocol):
    """Product-owned bridge from portable bytes to canonical Session lifecycle."""

    async def prepare(
        self,
        target: ContinuityTarget,
        payload: ContinuityActivationPayload,
        source: ContinuityProviderSourceDescriptor,
    ) -> PreparedActivationLease: ...


@dataclass(frozen=True, slots=True)
class ContinuityPluginProviderPack:
    providers: tuple[ContinuityImportProvider, ...]

    def __post_init__(self) -> None:
        providers = tuple(self.providers)
        if not providers:
            raise ValueError("Plugin continuity Provider pack must not be empty")
        if len(providers) > MAX_CONTINUITY_PLUGIN_PROVIDERS:
            raise ValueError("Plugin continuity Provider pack exceeds its limit")
        if any(not isinstance(item, ContinuityImportProvider) for item in providers):
            raise TypeError("Plugin continuity pack contains an invalid Provider")
        object.__setattr__(self, "providers", providers)


@dataclass(frozen=True, slots=True)
class ContinuityPluginProviderContext:
    """Narrow factory context with no Product runtime or filesystem authority."""

    product_id: str
    experience_id: str
    contribution_ref: PluginContributionRef
    instance_revision_ref: PluginInstanceRevisionRef
    binding_inputs: Mapping[str, JSONValue]
    allowed_actions: tuple[str, ...] = ("activate",)

    def __post_init__(self) -> None:
        _require_text(self.product_id, name="continuity Plugin Product id")
        _require_text(self.experience_id, name="continuity Plugin Experience id")
        if not isinstance(self.contribution_ref, PluginContributionRef):
            raise TypeError("continuity Plugin contribution ref is invalid")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("continuity Plugin instance revision ref is invalid")
        if self.contribution_ref.plugin_id != self.instance_revision_ref.plugin_id:
            raise ValueError("continuity Plugin contribution and Instance differ")
        object.__setattr__(
            self,
            "binding_inputs",
            require_json_mapping(
                dict(self.binding_inputs),
                name="continuity Plugin binding inputs",
            ),
        )


ContinuityPluginProviderFactory: TypeAlias = Callable[
    [ContinuityPluginProviderContext], ContinuityPluginProviderPack
]
ContinuityPluginProviderDisposer: TypeAlias = Callable[
    [ContinuityPluginProviderPack], None
]
PluginInstanceRevisionReader: TypeAlias = Callable[
    [str], PluginInstanceRevisionRef | None
]
PluginTrustSnapshotReader: TypeAlias = Callable[
    [str, str], PluginSourceTrustSnapshotV1 | None
]


@dataclass(frozen=True, slots=True)
class ContinuityPluginProviderContribution:
    """Product-admitted exact Plugin contribution projected into Runtime Profile."""

    product_id: str
    experience_id: str
    contribution_ref: PluginContributionRef
    instance_revision_ref: PluginInstanceRevisionRef
    trust_snapshot: PluginSourceTrustSnapshotV1
    implementation_version: int
    create: ContinuityPluginProviderFactory = field(repr=False, compare=False)
    current_instance_reader: PluginInstanceRevisionReader = field(
        repr=False,
        compare=False,
    )
    current_trust_reader: PluginTrustSnapshotReader = field(
        repr=False,
        compare=False,
    )
    dispose: ContinuityPluginProviderDisposer | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    binding_inputs: Mapping[str, JSONValue] = field(default_factory=dict)
    priority: int = 0

    def __post_init__(self) -> None:
        _require_text(self.product_id, name="continuity Plugin Product id")
        _require_text(self.experience_id, name="continuity Plugin Experience id")
        if not isinstance(self.contribution_ref, PluginContributionRef):
            raise TypeError("continuity Plugin contribution ref is invalid")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("continuity Plugin instance revision ref is invalid")
        if not isinstance(self.trust_snapshot, PluginSourceTrustSnapshotV1):
            raise TypeError("continuity Plugin trust snapshot is invalid")
        plugin_id = self.contribution_ref.plugin_id
        if (
            self.instance_revision_ref.plugin_id != plugin_id
            or self.trust_snapshot.plugin_id != plugin_id
        ):
            raise ValueError("continuity Plugin admission identities differ")
        if not self.trust_snapshot.trusted:
            raise ContinuityPluginAdmissionError(
                "Continuity Plugin source is not trusted.",
                code="continuity_plugin_source_untrusted",
            )
        if (
            isinstance(self.implementation_version, bool)
            or not isinstance(self.implementation_version, int)
            or self.implementation_version < 1
        ):
            raise ValueError("continuity Plugin implementation version must be positive")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("continuity Plugin priority must be an integer")
        if not callable(self.create):
            raise TypeError("continuity Plugin Provider factory must be callable")
        if not callable(self.current_instance_reader) or not callable(
            self.current_trust_reader
        ):
            raise TypeError("continuity Plugin admission requires authority readers")
        if self.dispose is not None and not callable(self.dispose):
            raise TypeError("continuity Plugin Provider disposer must be callable")
        object.__setattr__(
            self,
            "binding_inputs",
            require_json_mapping(
                dict(self.binding_inputs),
                name="continuity Plugin binding inputs",
            ),
        )

    @property
    def layer_id(self) -> str:
        revision = self.instance_revision_ref
        return (
            f"plugin:{revision.instance_id}:r{revision.revision}:"
            f"{self.contribution_ref.contribution_id}"
        )

    @property
    def implementation_id(self) -> str:
        return (
            f"plugin:{self.contribution_ref.plugin_id}:continuity:"
            f"{self.contribution_ref.contribution_id}"
        )

    def runtime_contribution(
        self,
        bridge: ContinuityActivationBridge,
    ) -> ContinuityPluginRuntimeContribution:
        if not isinstance(bridge, ContinuityActivationBridge):
            raise TypeError("continuity Plugin contribution requires an activation bridge")
        config: dict[str, JSONValue] = {
            "continuityPluginSchemaVersion": CONTINUITY_PLUGIN_SCHEMA_VERSION,
            "pluginId": self.contribution_ref.plugin_id,
            "contributionId": self.contribution_ref.contribution_id,
            "instanceId": self.instance_revision_ref.instance_id,
            "instanceRevision": self.instance_revision_ref.revision,
            "sourceTrustClass": self.trust_snapshot.source_trust_class,
            "sourceTrustPolicyRevision": (
                self.trust_snapshot.source_trust_policy_revision
            ),
        }
        selection = RuntimeCapabilitySelection(
            slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
            implementation=self.implementation_id,
            implementation_version=self.implementation_version,
            config=config,
            priority=self.priority,
        )

        def create_pack(_selection: object, _runtime: object) -> ContinuityProviderPack:
            self._require_current()
            context = ContinuityPluginProviderContext(
                product_id=self.product_id,
                experience_id=self.experience_id,
                contribution_ref=self.contribution_ref,
                instance_revision_ref=self.instance_revision_ref,
                binding_inputs=self.binding_inputs,
            )
            raw_pack = self.create(context)
            if inspect.isawaitable(raw_pack):
                raise TypeError("continuity Plugin Provider factory must be synchronous")
            if not isinstance(raw_pack, ContinuityPluginProviderPack):
                raise TypeError(
                    "continuity Plugin Provider factory returned an invalid pack"
                )
            try:
                self._require_current()
                wrappers = tuple(
                    _AdmittedPluginContinuityProvider(
                        inner=provider,
                        contribution=self,
                        bridge=bridge,
                    )
                    for provider in raw_pack.providers
                )
                self._require_current()
            except BaseException as exc:
                self._dispose_failed_pack(raw_pack, exc)
                raise
            return ContinuityProviderPack(providers=wrappers)

        def dispose_pack(value: object, _runtime: object) -> None:
            if self.dispose is None:
                return
            if not isinstance(value, ContinuityProviderPack):
                raise TypeError("continuity Plugin disposer received an invalid pack")
            providers: list[ContinuityImportProvider] = []
            for provider in value.providers:
                if not isinstance(provider, _AdmittedPluginContinuityProvider):
                    raise TypeError(
                        "continuity Plugin disposer cannot retire another pack"
                    )
                providers.append(provider.inner)
            result = self.dispose(ContinuityPluginProviderPack(tuple(providers)))
            if inspect.isawaitable(result):
                raise TypeError("continuity Plugin Provider disposer must be synchronous")

        return ContinuityPluginRuntimeContribution(
            layer=RuntimeProfileLayer(
                source="extension",
                layer_id=self.layer_id,
                priority=self.priority,
                selections=(selection,),
            ),
            grant=RuntimeProfileLayerGrant(
                source="extension",
                layer_id=self.layer_id,
                allowed_slots=frozenset({CONTINUITY_PROVIDER_PACKS_SLOT.key}),
                granted_permissions=frozenset({CONTINUITY_PLUGIN_PERMISSION}),
            ),
            implementation=RuntimeCapabilityImplementation(
                slot=CONTINUITY_PROVIDER_PACKS_SLOT.key,
                implementation=self.implementation_id,
                implementation_version=self.implementation_version,
                create=create_pack,
                dispose=dispose_pack if self.dispose is not None else None,
            ),
        )

    def _require_current(self) -> None:
        current_instance = self.current_instance_reader(
            self.contribution_ref.plugin_id
        )
        if current_instance != self.instance_revision_ref:
            raise ContinuityPluginAdmissionError(
                "Continuity Plugin Instance revision is stale.",
                code="continuity_plugin_instance_stale",
            )
        trust = self.current_trust_reader(
            self.contribution_ref.plugin_id,
            self.trust_snapshot.package_source_identity,
        )
        if trust != self.trust_snapshot or not trust.trusted:
            raise ContinuityPluginAdmissionError(
                "Continuity Plugin source trust is stale.",
                code="continuity_plugin_source_trust_stale",
            )

    def _dispose_failed_pack(
        self,
        pack: ContinuityPluginProviderPack,
        failure: BaseException,
    ) -> None:
        disposer = self.dispose
        if disposer is None:
            return
        try:
            result = disposer(pack)
            if inspect.isawaitable(result):
                raise TypeError(
                    "continuity Plugin Provider disposer must be synchronous"
                )
        except BaseException as cleanup_error:
            failure.add_note(
                "Continuity Plugin candidate cleanup failed: "
                f"{type(cleanup_error).__name__}"
            )


@dataclass(frozen=True, slots=True)
class ContinuityPluginRuntimeContribution:
    """Exact Runtime Profile inputs minted by one admitted contribution."""

    layer: RuntimeProfileLayer
    grant: RuntimeProfileLayerGrant
    implementation: RuntimeCapabilityImplementation


class _AdmittedPluginContinuityProvider:
    """Read-only, authority-revalidating adapter over one Plugin Provider."""

    def __init__(
        self,
        *,
        inner: ContinuityImportProvider,
        contribution: ContinuityPluginProviderContribution,
        bridge: ContinuityActivationBridge,
    ) -> None:
        if not isinstance(inner, ContinuityImportProvider):
            raise TypeError("continuity Plugin pack contains an invalid Provider")
        descriptor = inner.descriptor
        if not isinstance(descriptor, ContinuityProviderDescriptor):
            raise TypeError("continuity Plugin Provider descriptor is invalid")
        if descriptor.experience_id != contribution.experience_id:
            raise ContinuityPluginAdmissionError(
                "Continuity Plugin Provider belongs to another Experience.",
                code="continuity_plugin_experience_mismatch",
            )
        if descriptor.implementation_version != contribution.implementation_version:
            raise ContinuityPluginAdmissionError(
                "Continuity Plugin Provider implementation version differs.",
                code="continuity_plugin_implementation_version_mismatch",
            )
        self.inner = inner
        self._contribution = contribution
        self._bridge = bridge
        self._descriptor = replace(
            descriptor,
            supported_actions=("activate",),
        )

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return self._descriptor

    async def query(self, request: ProviderQuery) -> ProviderPage:
        self._contribution._require_current()
        page = await self.inner.query(request)
        self._contribution._require_current()
        if not isinstance(page, ProviderPage):
            raise TypeError("continuity Plugin Provider must return ProviderPage")
        return replace(
            page,
            items=tuple(
                ProviderPageItem(
                    summary=replace(item.summary, actions=("activate",)),
                    after_cursor=item.after_cursor,
                )
                for item in page.items
            ),
        )

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        self._contribution._require_current()
        preview = await self.inner.preview(target)
        self._contribution._require_current()
        if not isinstance(preview, ContinuityPreview):
            raise TypeError("continuity Plugin Provider must return ContinuityPreview")
        if preview.target != target:
            raise ValueError("continuity Plugin preview target differs")
        return preview

    async def prepare(self, target: ContinuityTarget) -> PreparedActivationLease:
        self._contribution._require_current()
        source_lease = await self.inner.prepare_import(target)
        if not isinstance(source_lease, PreparedContinuityImport):
            raise TypeError("continuity Plugin returned an invalid import lease")
        product_lease: PreparedActivationLease | None = None
        try:
            if source_lease.target != target:
                raise ValueError("continuity Plugin import lease target differs")
            payload = source_lease.payload
            if not isinstance(payload, ContinuityActivationPayload):
                raise TypeError("continuity Plugin import payload is invalid")
            self._contribution._require_current()
            product_lease = await self._bridge.prepare(
                target,
                payload,
                _plugin_source(self._descriptor.provider_id, self._contribution),
            )
            if not isinstance(product_lease, PreparedActivationLease):
                raise TypeError("continuity activation bridge returned an invalid lease")
            if product_lease.target != target:
                raise ValueError("continuity activation bridge lease target differs")
            self._contribution._require_current()
        except BaseException as exc:
            callbacks = (
                (source_lease.abort,)
                if product_lease is None
                else (product_lease.abort, source_lease.abort)
            )
            try:
                await _settle_leases(*callbacks)
            except BaseException as cleanup_error:
                exc.add_note(
                    "Continuity Plugin activation cleanup failed: "
                    f"{type(cleanup_error).__name__}"
                )
            raise
        return _BridgedActivationLease(
            target=target,
            source=source_lease,
            product=product_lease,
        )


class _BridgedActivationLease:
    def __init__(
        self,
        *,
        target: ContinuityTarget,
        source: PreparedContinuityImport,
        product: PreparedActivationLease,
    ) -> None:
        self._target = target
        self._source = source
        self._product = product
        self._consumed = False
        self._closed = False

    @property
    def target(self) -> ContinuityTarget:
        return self._target

    @property
    def disposition(self) -> ActivationDisposition:
        return self._product.disposition

    @property
    def consumed(self) -> bool:
        return self._consumed

    async def consume(self) -> object:
        if self._closed or self._consumed:
            raise RuntimeError("continuity Plugin activation lease is already settled")
        self._consumed = True
        try:
            result = await self._product.consume()
        except BaseException as exc:
            self._closed = True
            try:
                await _settle_leases(self._product.close, self._source.close)
            except BaseException as cleanup_error:
                exc.add_note(
                    "Continuity Plugin activation cleanup failed: "
                    f"{type(cleanup_error).__name__}"
                )
            raise
        self._closed = True
        await _settle_leases(self._product.close, self._source.close)
        return result

    async def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        await _settle_leases(self._product.abort, self._source.abort)

    async def close(self) -> None:
        await self.abort()


async def _settle_leases(*callbacks: Callable[[], object]) -> None:
    first_error: BaseException | None = None
    for callback in callbacks:
        try:
            result = callback()
            if inspect.isawaitable(result):
                await result
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def _plugin_source(
    provider_id: str,
    contribution: ContinuityPluginProviderContribution,
) -> ContinuityProviderSourceDescriptor:
    return ContinuityProviderSourceDescriptor(
        provider_id=provider_id,
        source="plugin",
        source_id=contribution.layer_id,
        implementation=contribution.implementation_id,
        implementation_version=contribution.implementation_version,
        plugin_id=contribution.contribution_ref.plugin_id,
        contribution_id=contribution.contribution_ref.contribution_id,
        instance_id=contribution.instance_revision_ref.instance_id,
        instance_revision=contribution.instance_revision_ref.revision,
        source_trust_class=contribution.trust_snapshot.source_trust_class,
        source_trust_policy_revision=(
            contribution.trust_snapshot.source_trust_policy_revision
        ),
    )


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


__all__ = [
    "CONTINUITY_BUNDLE_MEDIA_TYPE",
    "CONTINUITY_JSONL_MEDIA_TYPE",
    "CONTINUITY_PLUGIN_PERMISSION",
    "ContinuityActivationBridge",
    "ContinuityActivationPayload",
    "ContinuityImportProvider",
    "ContinuityPluginAdmissionError",
    "ContinuityPluginProviderContext",
    "ContinuityPluginProviderContribution",
    "ContinuityPluginProviderPack",
    "ContinuityPluginRuntimeContribution",
    "PreparedContinuityImport",
]
