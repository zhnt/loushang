"""Explicit Coding launch facts and optional managed application preparation.

Construction discovers no defaults and starts no Product or deployment. The
returned application attempt retains admission before its explicit open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost.managed.contracts import ManagedContractError
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.apphost.managed.paths import (
    resolve_managed_admission_root,
    resolve_managed_paths,
)
from loushang.appserver.protocol import SessionScopeV1
from loushang.appservice.continuity import require_application_id
from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory

from .hosted_application import CODING_MANAGED_APPLICATION_PROFILE_ID
from .hosted_bootstrap import CodingHostedLaunchV1, _create_coding_attempt
from .hosted_catalog import CodingHostedScopeV1
from .hosted_continuity import CodingHostedContinuityAttemptV1
from .hosted_local import CodingLocalLaunchV1
from .hosted_session import CodingHostedProductRuntimeFactoryForSession
from .managed_catalog import CodingManagedSessionCatalogV1


@dataclass(frozen=True, slots=True)
class CodingManagedApplicationLaunchV1:
    """Explicit canonical Session launch, separate from legacy G16 roots."""

    workspace: Path = field(repr=False)
    application_root: Path = field(repr=False)
    application_id: str
    session_root: Path = field(repr=False)
    store_state_root: Path | None = field(default=None, repr=False, kw_only=True)

    def __post_init__(self) -> None:
        require_application_id(self.application_id)
        for path in (self.workspace, self.application_root, self.session_root):
            if not isinstance(path, Path) or not path.is_absolute() or path != path.resolve():
                raise ValueError("managed application requires canonical paths")
        if not self.workspace.is_dir() or not self.application_root.parent.is_dir():
            raise ValueError("managed workspace and application parent must exist")
        for data in (
            self.session_root, self.session_root.parent / "session-assets",
            self.session_root.parent / ".session-blob-writers",
        ):
            if self.application_root.is_relative_to(data) or data.is_relative_to(self.application_root):
                raise ValueError("managed application state must be separate from Session storage")
        if self.store_state_root is not None:
            state = self.store_state_root
            if (not state.is_absolute() or state != state.resolve()
                    or state.is_relative_to(self.session_root.parent)
                    or self.session_root.parent.is_relative_to(state)
                    or state.is_relative_to(self.application_root)
                    or self.application_root.is_relative_to(state)):
                raise ValueError("store admission state must be separate from writable application data")

    @property
    def scopes(self) -> tuple[CodingHostedScopeV1, ...]:
        return tuple(CodingHostedScopeV1(scope, self.session_root, self.workspace)
                     for scope in (SessionScopeV1.CWD, SessionScopeV1.USER_HOME))


def create_coding_managed_attempt(
    launch: CodingManagedApplicationLaunchV1, *, model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None, tools: list[ToolDefinition] | None = None,
    session_discovery: bool = False,
    managed_mux: ManagedMuxServiceBindingV1 | None = None,
    output_capture_factory: ExecCaptureFactory | None = None,
    package_product_runtime_factory_for_session: (
        CodingHostedProductRuntimeFactoryForSession | None
    ) = None,
) -> CodingHostedContinuityAttemptV1:
    """Prepare the owned Product application; no daemon/default-path effects."""
    if type(launch) is not CodingManagedApplicationLaunchV1 or type(session_discovery) is not bool:
        raise TypeError("invalid managed application launch")
    if managed_mux is not None and (type(managed_mux) is not ManagedMuxServiceBindingV1
                                    or managed_mux.application_id != launch.application_id):
        raise ValueError("managed Mux binding does not match application")
    catalog = CodingManagedSessionCatalogV1(session_root=launch.session_root, workspace=launch.workspace,
                                           store_state_root=launch.store_state_root)
    return _create_coding_attempt(
        application_root=launch.application_root, application_id=launch.application_id,
        catalog=catalog, generation=token_hex(16), model=model, stream_fn=stream_fn, tools=tools,
        session_discovery=session_discovery, owned_transcripts=True,
        profile_id=CODING_MANAGED_APPLICATION_PROFILE_ID, managed_selection=True,
        managed_mux=managed_mux,
        output_capture_factory=output_capture_factory,
        package_product_runtime_factory_for_session=(
            package_product_runtime_factory_for_session
        ),
    )


def create_coding_managed_launch(
    invocation: ManagedChildInvocationV1, *, application_id: str, endpoint: str,
    cwd_sessions: Path, home_sessions: Path, session_discovery: bool = False,
) -> CodingLocalLaunchV1:
    """Bind Coding to exactly the invocation workspace and managed layout.

    Session roots remain explicit and pass the existing G16 disjoint-root
    checks. They are not decoded from the neutral message or inferred from cwd;
    the canonical shared default catalog must be admitted separately before
    managed CLI activation. No factory or model selection comes from this value.
    """
    if type(invocation) is not ManagedChildInvocationV1 or invocation.service.product_id != "coding":
        raise ManagedContractError()
    paths = resolve_managed_paths(
        invocation.namespace, invocation.service, invocation.instance, runtime_root=invocation.runtime_root,
        temporary_override=invocation.temporary_override,
    )
    launch = CodingLocalLaunchV1(
        CodingHostedLaunchV1(
            Path(invocation.service.workspace), Path(paths.application), application_id,
            cwd_sessions, home_sessions,
        ),
        Path(paths.connection), endpoint, session_discovery=session_discovery,
    )
    # Deployment control and scratch are not Session catalogs, even where they
    # are siblings of (rather than nested in) the application/connection roots.
    for catalog in (cwd_sessions, home_sessions):
        for data in (catalog, catalog.parent / "session-assets", catalog.parent / ".session-blob-writers"):
            for managed in _managed_control_roots(invocation):
                if data.is_relative_to(managed) or managed.is_relative_to(data):
                    raise ManagedContractError()
    return launch


def _managed_control_roots(invocation: ManagedChildInvocationV1) -> tuple[Path, ...]:
    return (
        Path(invocation.namespace.platform_home) / "lmux",
        Path(invocation.runtime_root) / "lmux",
        Path(resolve_managed_admission_root(invocation.namespace)).parent,
        Path(invocation.namespace.platform_home) / "state/session-stores",
        *((Path(invocation.temporary_override) / "lmux",) if invocation.temporary_override is not None else ()),
    )


__all__ = ["CodingManagedApplicationLaunchV1", "create_coding_managed_attempt", "create_coding_managed_launch"]
