"""Trusted real Coding composition for the explicit detachable local profile."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost.continuity import HostedApplicationContinuityRuntimeV1
from loushang.apphost.local import (
    HostedLocalRuntimeV1,
    _LocalApplicationStartup,
)
from loushang.apphost.local import (
    _failed as _failed,
)
from loushang.apphost.local import (
    _LocalLaunchFacts as _LocalLaunchFacts,
)
from loushang.apphost.local import (
    _spawn as _spawn,
)
from loushang.apphost.local import (
    _wait as _wait_shared,
)
from loushang.appserver.framing import require_timeout
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalConnectionRecordV1,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.harness.tools.core import ToolDefinition

from .hosted_bootstrap import (
    CodingHostedLaunchV1,
    create_coding_hosted_attempt,
    prepare_coding_hosted_session_roots,
)
from .hosted_continuity import CodingHostedContinuityAttemptV1
from .hosted_session import CodingHostedProductRuntimeFactoryForSession


@dataclass(frozen=True, slots=True)
class CodingLocalLaunchV1:
    application: CodingHostedLaunchV1
    connection_root: Path = field(repr=False)
    endpoint: str
    session_discovery: bool = field(default=False, kw_only=True)

    def __post_init__(self) -> None:
        if type(self.session_discovery) is not bool:
            raise TypeError("invalid discovery activation")
        root = self.connection_root
        if (
            type(self.application) is not CodingHostedLaunchV1
            or not isinstance(root, Path)
            or not root.is_absolute()
            or root != root.resolve()
            or not root.parent.is_dir()
            or self.application.workspace.is_relative_to(root)
        ):
            raise ValueError("invalid private connection root")
        for canonical in (
            self.application.application_root,
            self.application.cwd_sessions,
            self.application.home_sessions,
        ):
            if root.is_relative_to(canonical) or canonical.is_relative_to(root):
                raise ValueError("connection and durable roots must be separate")
        # Reuse the closed record's identity validation, without creating IO.
        LocalConnectionRecordV1(
            endpoint=self.endpoint,
            application_id=self.application.application_id,
            product_id="coding",
            instance="0" * 32,
            key=bytes(32),
            port=1,
            scopes=self.scopes,
        )

    @property
    def scopes(self) -> tuple[LocalRecordScopeV1, ...]:
        return tuple(
            LocalRecordScopeV1(scope.scope, scope.fingerprint)
            for scope in self.application.scopes
        )

    def describe(self) -> dict[str, object]:
        return {
            **self.application.describe(
                profile=(
                    AppConnectionProfileV1.LOCAL_DISCOVERY
                    if self.session_discovery
                    else AppConnectionProfileV1.LOCAL
                )
            ),
            "endpoint": self.endpoint,
        }


class CodingLocalCommandV1(_LocalApplicationStartup):
    """Own startup until the ready AppHost deployment adopts the application.

    Before handoff, retain the G13 attempt and any late application. Afterwards
    AppHost is the only application-stop owner; this wrapper must not reset its
    budget, close the application separately, or stop it on client EOF.
    """

    def __init__(
        self,
        launch: _LocalLaunchFacts,
        *,
        model: Model | ModelSelection | None = None,
        stream_fn: StreamFn | None = None,
        tools: list[ToolDefinition] | None = None,
        startup_timeout: float = 30.0,
        settlement_timeout: float = 30.0,
        package_product_runtime_factory_for_session: (
            CodingHostedProductRuntimeFactoryForSession | None
        ) = None,
    ) -> None:
        self._validate_launch(launch)
        for timeout in (startup_timeout, settlement_timeout):
            _require_budget(timeout)
        self._launch = launch
        self._package_product_runtime_factory_for_session = (
            package_product_runtime_factory_for_session
        )
        self._directory = LocalConnectionDirectoryV1(launch.connection_root)
        self._attempt = self._create_attempt(
            launch, model=model, stream_fn=stream_fn, tools=tools
        )
        self._application: HostedApplicationContinuityRuntimeV1 | None = None
        self._local: HostedLocalRuntimeV1 | None = None
        self._startup_timeout, self._timeout = startup_timeout, settlement_timeout
        self._start_task: asyncio.Task[None] | None = None
        self._activate_task: asyncio.Task[None] | None = None
        self._startup_deadline: float | None = None
        self._prepared = False
        self._one_step = False
        self._close_task: asyncio.Task[None] | None = None
        self._phases: dict[str, asyncio.Task[None]] = {}
        self._deadline: float | None = None
        self._closing = False
        self._settled = False

    def _validate_launch(self, launch: _LocalLaunchFacts) -> None:
        if type(launch) is not CodingLocalLaunchV1:
            raise TypeError("local command requires admitted launch facts")

    def _connection_instance(self) -> str | None:
        return None

    def _mux_management(self) -> bool:
        return False

    def _session_execution(self) -> bool:
        return True

    def _prepare_session_roots(self) -> None:
        assert type(self._launch) is CodingLocalLaunchV1
        prepare_coding_hosted_session_roots(self._launch.application)

    def _create_attempt(
        self,
        launch: _LocalLaunchFacts,
        *,
        model: Model | ModelSelection | None,
        stream_fn: StreamFn | None,
        tools: list[ToolDefinition] | None,
    ) -> CodingHostedContinuityAttemptV1:
        assert type(launch) is CodingLocalLaunchV1
        return create_coding_hosted_attempt(
            launch.application,
            model=model,
            stream_fn=stream_fn,
            tools=tools,
            session_discovery=launch.session_discovery,
            owned_transcripts=True,
            package_product_runtime_factory_for_session=(
                self._package_product_runtime_factory_for_session
            ),
        )

    def _check_retry_budget(self, value: float) -> None:
        _require_budget(value)

    _startup_error_prefix = "coding_local"

    def _prepare_unavailable(self) -> bool:
        return self._closing or self._start_task is not None

    def _startup_accepting(self) -> bool:
        return self._local is not None and self._local.accepting


def _require_budget(value: float) -> None:
    require_timeout(value)
    if value > 30:
        raise ValueError("Coding local budget exceeds profile bound")


async def _wait(
    task: asyncio.Task[None], deadline: float, *, ignore_failure: bool = False
) -> None:
    await _wait_shared(
        task, deadline, ignore_failure=ignore_failure, error_prefix="coding_local"
    )


__all__ = ["CodingLocalLaunchV1", "CodingLocalCommandV1"]
