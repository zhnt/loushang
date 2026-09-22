"""Explicit canonical Coding application on the existing local listener owner.

No service discovery, directory initialization, daemon spawn or CLI activation.
The managed child still owns durable handoff and every shutdown phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost.managed.contracts import ManagedContractError
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.apphost.managed.output_capture import ManagedOutputCaptureFactory
from loushang.apphost.managed.paths import resolve_managed_paths
from loushang.appserver.local_record import LocalConnectionRecordV1, LocalRecordScopeV1
from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from loushang.harness.tools.core import ToolDefinition

from .hosted_continuity import CodingHostedContinuityAttemptV1
from .hosted_local import CodingLocalCommandV1, _LocalLaunchFacts
from .managed_bootstrap import (
    CodingManagedApplicationLaunchV1,
    _managed_control_roots,
    create_coding_managed_attempt,
)


@dataclass(frozen=True, slots=True)
class CodingManagedLocalLaunchV1:
    application: CodingManagedApplicationLaunchV1
    connection_root: Path = field(repr=False)
    endpoint: str
    session_discovery: bool = field(default=False, kw_only=True)
    instance_id: str | None = field(default=None, kw_only=True)
    managed_mux: ManagedMuxServiceBindingV1 | None = field(default=None, repr=False, kw_only=True)

    def __post_init__(self) -> None:
        if self.managed_mux is not None and (type(self.managed_mux) is not ManagedMuxServiceBindingV1
                or self.managed_mux.application_id != self.application.application_id
                or self.managed_mux.instance_id != self.instance_id):
            raise ValueError("managed Mux binding must match launch identity")
        root = self.connection_root
        if (type(self.application) is not CodingManagedApplicationLaunchV1
                or type(self.session_discovery) is not bool or not isinstance(root, Path)
                or not root.is_absolute() or root != root.resolve()
                or not root.parent.is_dir() or self.application.workspace.is_relative_to(root)):
            raise ValueError("invalid managed connection root")
        for durable in (
            self.application.application_root, self.application.session_root,
            self.application.session_root.parent / "session-assets",
            self.application.session_root.parent / ".session-blob-writers",
        ):
            if root.is_relative_to(durable) or durable.is_relative_to(root):
                raise ValueError("managed connection and Session authority must be separate")
        state = self.application.store_state_root
        if state is not None and (root.is_relative_to(state) or state.is_relative_to(root)):
            raise ValueError("managed connection and store admission state must be separate")
        LocalConnectionRecordV1(
            endpoint=self.endpoint, application_id=self.application.application_id,
            product_id="coding", instance="0" * 32 if self.instance_id is None else self.instance_id,
            key=bytes(32), port=1, scopes=self.scopes,
        )

    @property
    def scopes(self) -> tuple[LocalRecordScopeV1, ...]:
        return tuple(LocalRecordScopeV1(scope.scope, scope.fingerprint) for scope in self.application.scopes)


class CodingManagedLocalCommandV1(CodingLocalCommandV1):
    """Select only the managed attempt; inherit the original lifetime intact."""

    def __init__(self, launch: CodingManagedLocalLaunchV1, *, model: Model | ModelSelection | None = None,
                 stream_fn: StreamFn | None = None, tools: list[ToolDefinition] | None = None,
                 startup_timeout: float = 30.0, settlement_timeout: float = 30.0,
                 output_capture_factory: ManagedOutputCaptureFactory | None = None) -> None:
        self._output_capture_factory = output_capture_factory
        super().__init__(launch, model=model, stream_fn=stream_fn, tools=tools,
                         startup_timeout=startup_timeout, settlement_timeout=settlement_timeout)

    @property
    def cleanup_pending(self) -> bool:
        return super().cleanup_pending or bool(self._output_capture_factory is not None
                                               and not self._output_capture_factory.settled)

    async def close(self, *, retry_timeout: float | None = None) -> None:
        await super().close(retry_timeout=retry_timeout)
        if self._output_capture_factory is not None:
            await self._output_capture_factory.close()

    def _validate_launch(self, launch: _LocalLaunchFacts) -> None:
        if type(launch) is not CodingManagedLocalLaunchV1:
            raise TypeError("managed local command requires exact admitted launch facts")

    def _connection_instance(self) -> str | None:
        assert type(self._launch) is CodingManagedLocalLaunchV1
        return self._launch.instance_id

    def _mux_management(self) -> bool:
        assert type(self._launch) is CodingManagedLocalLaunchV1
        return self._launch.managed_mux is not None

    def _create_attempt(
        self, launch: _LocalLaunchFacts, *, model: Model | ModelSelection | None,
        stream_fn: StreamFn | None, tools: list[ToolDefinition] | None,
    ) -> CodingHostedContinuityAttemptV1:
        assert type(launch) is CodingManagedLocalLaunchV1
        return create_coding_managed_attempt(
            launch.application, model=model, stream_fn=stream_fn, tools=tools,
            session_discovery=launch.session_discovery,
            managed_mux=launch.managed_mux,
            output_capture_factory=self._output_capture_factory,
        )


def create_coding_managed_local_launch(
    invocation: ManagedChildInvocationV1, *, session_root: Path,
    application_id: str, endpoint: str, session_discovery: bool = False,
    store_state_root: Path | None = None,
    managed_mux: ManagedMuxServiceBindingV1 | None = None,
) -> CodingManagedLocalLaunchV1:
    """Derive neutral deployment paths; keep canonical Session selection Coding-owned."""
    if type(invocation) is not ManagedChildInvocationV1 or invocation.service.product_id != "coding":
        raise ManagedContractError()
    if managed_mux is not None and (type(managed_mux) is not ManagedMuxServiceBindingV1
                                    or managed_mux.service_id != invocation.service.service_id
                                    or managed_mux.instance_id != invocation.instance.instance_id
                                    or managed_mux.application_id != application_id):
        raise ManagedContractError()
    paths = resolve_managed_paths(
        invocation.namespace, invocation.service, invocation.instance, runtime_root=invocation.runtime_root,
        temporary_override=invocation.temporary_override,
    )
    application = CodingManagedApplicationLaunchV1(
        Path(invocation.service.workspace), Path(paths.application), application_id, session_root,
        store_state_root=store_state_root,
    )
    state = application.store_state_root
    runtime = Path(invocation.runtime_root)
    if state is not None and (state.is_relative_to(runtime) or runtime.is_relative_to(state)):
        raise ManagedContractError()
    for data in (session_root, session_root.parent / "session-assets", session_root.parent / ".session-blob-writers"):
        for managed in _managed_control_roots(invocation):
            if data.is_relative_to(managed) or managed.is_relative_to(data):
                raise ManagedContractError()
    return CodingManagedLocalLaunchV1(
        application, Path(paths.connection), endpoint, session_discovery=session_discovery,
        instance_id=invocation.instance.instance_id,
        managed_mux=managed_mux,
    )


__all__ = ["CodingManagedLocalLaunchV1", "CodingManagedLocalCommandV1", "create_coding_managed_local_launch"]
