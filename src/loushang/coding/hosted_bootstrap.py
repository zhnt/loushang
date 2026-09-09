"""Trusted Product bootstrap shared by the explicit G14 and G16 deployments.

The returned G13 attempt owns admission before effects. This module selects
installed Coding code, not a transport, process owner or installed command.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from secrets import token_hex

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostShutdownBudgetV1,
)
from loushang.apphost.application import HostedApplicationActivationV1
from loushang.apphost.continuity import HostedApplicationContinuityActivationV1
from loushang.appserver.protocol import SessionScopeV1
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appservice.continuity import require_application_id
from loushang.appservice.continuity_file import JsonFileApplicationContinuityStoreV1
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryBindingV1,
    HostedSessionDiscoveryScopeV1,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.tools.core import ToolDefinition

from .bootstrap import BootstrapServices, create_services
from .control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from .hosted_application import (
    CODING_HOSTED_APPLICATION_PROFILE_ID,
    CodingForegroundHostedApplicationRequestV1,
)
from .hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedCandidateValidatorV1,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from .hosted_continuity import (
    CodingHostedContinuityAttemptV1,
    CodingHostedContinuityRequestV1,
    create_coding_hosted_continuity_attempt,
)
from .hosted_session import CodingRealHostedSessionFactoryV1


@dataclass(frozen=True, slots=True)
class CodingHostedLaunchV1:
    """Trusted launch facts, never decoded from a client or continuity record."""

    workspace: Path = field(repr=False)
    application_root: Path = field(repr=False)
    application_id: str
    cwd_sessions: Path = field(repr=False)
    home_sessions: Path = field(repr=False)

    def __post_init__(self) -> None:
        require_application_id(self.application_id)
        for path in (
            self.workspace,
            self.application_root,
            self.cwd_sessions,
            self.home_sessions,
        ):
            if (
                not isinstance(path, Path)
                or not path.is_absolute()
                or path != path.resolve()
            ):
                raise ValueError("hosted paths must be explicitly canonical")
        if not self.workspace.is_dir() or not self.application_root.parent.is_dir():
            raise ValueError("hosted workspace and application parent must exist")
        roots = (self.application_root, self.cwd_sessions, self.home_sessions)
        if (
            any(
                left.is_relative_to(right)
                for left in roots
                for right in roots
                if left != right
            )
            or len(set(roots)) != 3
        ):
            raise ValueError("hosted application and Session roots must be separate")

    @property
    def scopes(self) -> tuple[CodingHostedScopeV1, ...]:
        return (
            CodingHostedScopeV1(SessionScopeV1.CWD, self.cwd_sessions, self.workspace),
            CodingHostedScopeV1(
                SessionScopeV1.USER_HOME, self.home_sessions, self.workspace
            ),
        )

    def describe(
        self, *, profile: AppConnectionProfileV1 = AppConnectionProfileV1.STDIO
    ) -> dict[str, object]:
        if type(profile) is not AppConnectionProfileV1:
            raise ValueError("invalid hosted connection profile")
        return {
            "profile": profile.value,
            "productId": "coding",
            "applicationId": self.application_id,
            "scopes": [
                {"scope": scope.scope.value, "scopeFingerprint": scope.fingerprint}
                for scope in self.scopes
            ],
        }


class _InstalledPin:
    def __init__(self, identity: AdmissionIdentityV1) -> None:
        self._identity = identity

    @property
    def identity(self) -> AdmissionIdentityV1:
        return self._identity

    async def close(self) -> None:
        # Imported, process-local installed code has no hot replacement path.
        return None


class _InstalledSource:
    def __init__(self, identity: AdmissionIdentityV1) -> None:
        self._identity = identity

    async def acquire_pin(self) -> _InstalledPin:
        return _InstalledPin(self._identity)


def create_coding_hosted_attempt(
    launch: CodingHostedLaunchV1,
    *,
    model: Model | ModelSelection | None = None,
    stream_fn: StreamFn | None = None,
    tools: list[ToolDefinition] | None = None,
    session_discovery: bool = False,
) -> CodingHostedContinuityAttemptV1:
    """Bind real Coding/G13 once; test seams never enter command-line input."""
    if type(session_discovery) is not bool:
        raise TypeError("invalid discovery activation")
    generation = token_hex(16)
    catalog = CodingHostedSessionCatalogV1(launch.scopes)
    admitted_scopes = tuple(HostedSessionDiscoveryScopeV1(
        "coding", scope.scope, scope.fingerprint,
    ) for scope in catalog.scopes)
    discovery = None if not session_discovery else HostedSessionDiscoveryBindingV1(
        generation, admitted_scopes, catalog,
    )
    product_version = hashlib.sha256(version("loushang").encode()).hexdigest()
    foreground = CodingForegroundHostedApplicationRequestV1(
        activation=HostedApplicationActivationV1(),
        generation_id=generation,
        product_version=product_version,
        compatibility_id=CODING_HOSTED_COMPATIBILITY_ID,
        product_admission_source=_InstalledSource(
            AdmissionIdentityV1(
                generation, AppHostAdmissionSubjectKind.PRODUCT, "coding"
            )
        ),
        profile_admission_source=_InstalledSource(
            AdmissionIdentityV1(
                generation,
                AppHostAdmissionSubjectKind.PROFILE,
                CODING_HOSTED_APPLICATION_PROFILE_ID,
            )
        ),
        candidate_validator=CodingHostedCandidateValidatorV1(),
        sessions=catalog,
        discovery=discovery,
        admitted_scopes=admitted_scopes,
        session_factory=CodingRealHostedSessionFactoryV1(
            services_factory=_services,
            model=model,
            stream_fn=stream_fn,
            tools=tools,
        ),
        shutdown_budget=AppHostShutdownBudgetV1(10.0, 5.0),
    )
    return create_coding_hosted_continuity_attempt(
        CodingHostedContinuityRequestV1(
            activation=HostedApplicationContinuityActivationV1(),
            foreground=foreground,
            application_id=launch.application_id,
            owner_epoch=token_hex(16),
            store=JsonFileApplicationContinuityStoreV1(launch.application_root),
        )
    )


def _services(cwd: Path) -> BootstrapServices:
    return create_services(
        settings_manager=SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(cwd),
        )
    )


__all__ = ["CodingHostedLaunchV1", "create_coding_hosted_attempt"]
