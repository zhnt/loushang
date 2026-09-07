"""Explicit foreground stdio Coding application, separate from default routes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
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
from loushang.apphost.continuity import (
    HostedApplicationContinuityActivationV1,
    HostedApplicationContinuityRuntimeV1,
)
from loushang.apphost.foreground import HostedForegroundRuntimeV1
from loushang.appserver.framing import require_timeout
from loushang.appserver.protocol import AppServiceError, SessionScopeV1
from loushang.appserver.stdio import InheritedStdioTransportV1
from loushang.appservice.continuity import require_application_id
from loushang.appservice.continuity_file import JsonFileApplicationContinuityStoreV1
from loushang.harness.config.agent import SettingsManager
from loushang.harness.tools.core import ToolDefinition

from ..bootstrap import BootstrapServices, create_services
from ..control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from ..hosted_application import (
    CODING_HOSTED_APPLICATION_PROFILE_ID,
    CodingForegroundHostedApplicationRequestV1,
)
from ..hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedCandidateValidatorV1,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from ..hosted_continuity import (
    CodingHostedContinuityRequestV1,
    create_coding_hosted_continuity_attempt,
)
from ..hosted_session import CodingRealHostedSessionFactoryV1


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

    def describe(self) -> dict[str, object]:
        return {
            "profile": "foreground-stdio/v1",
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


class CodingHostedCommandV1:
    """Publish startup and shutdown ownership before acquiring the G13 lease.

    Model/transport and safe-tool overrides are trusted library test seams;
    the installed command never accepts remote factory/module selection.
    """

    def __init__(
        self,
        launch: CodingHostedLaunchV1,
        *,
        model: Model | ModelSelection | None = None,
        stream_fn: StreamFn | None = None,
        tools: list[ToolDefinition] | None = None,
        connection_timeout: float = 10.0,
        settlement_timeout: float = 60.0,
    ) -> None:
        require_timeout(connection_timeout)
        require_timeout(settlement_timeout)
        self._launch = launch
        self._connection_timeout = connection_timeout
        self._settlement_timeout = settlement_timeout
        generation = token_hex(16)
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
            sessions=CodingHostedSessionCatalogV1(launch.scopes),
            session_factory=CodingRealHostedSessionFactoryV1(
                services_factory=_services,
                model=model,
                stream_fn=stream_fn,
                tools=tools,
            ),
            shutdown_budget=AppHostShutdownBudgetV1(10.0, 5.0),
        )
        self._attempt = create_coding_hosted_continuity_attempt(
            CodingHostedContinuityRequestV1(
                activation=HostedApplicationContinuityActivationV1(),
                foreground=foreground,
                application_id=launch.application_id,
                owner_epoch=token_hex(16),
                store=JsonFileApplicationContinuityStoreV1(launch.application_root),
            )
        )
        self._application: HostedApplicationContinuityRuntimeV1 | None = None
        self._transport: InheritedStdioTransportV1 | None = None
        self._foreground: HostedForegroundRuntimeV1 | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._started = False
        self._closing = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    async def run(self, *, input_fd: int, output_fd: int) -> None:
        if self._started or self._closing:
            raise RuntimeError("hosted_command_closed")
        self._started = True
        try:
            self._application = await self._attempt.open()
            self._transport = InheritedStdioTransportV1(
                input_fd=input_fd, output_fd=output_fd
            )
            self._foreground = HostedForegroundRuntimeV1(
                self._application,
                self._transport,
                connection_timeout=self._connection_timeout,
                settlement_timeout=self._settlement_timeout,
            )
            await self._foreground.run()
        finally:
            await self.close()

    async def close(self) -> None:
        self._closing = True
        if self._settled:
            return
        task = self._close_task
        if task is None or (
            task.done() and (task.cancelled() or task.exception() is not None)
        ):
            task = asyncio.create_task(self._close_once())
            task.add_done_callback(_observe)
            self._close_task = task
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        if self._foreground is not None:
            await self._foreground.close()
        else:
            if self._application is not None:
                await self._application.close()
            else:
                await self._attempt.close()
            if self._transport is not None:
                await self._transport.close()
        self._settled = True


def _services(cwd: Path) -> BootstrapServices:
    return create_services(
        settings_manager=SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(cwd),
        )
    )


def _observe(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loushang-hosted",
        description="Explicit foreground Coding application over inherited stdio; EOF shuts it down.",
    )
    parser.add_argument(
        "--workspace", type=Path, required=True, help="trusted execution workspace"
    )
    parser.add_argument(
        "--application-root",
        type=Path,
        required=True,
        help="private continuity directory (parent must exist)",
    )
    parser.add_argument(
        "--application-id",
        default="coding.default",
        help="stable application key to recover",
    )
    parser.add_argument(
        "--cwd-sessions",
        type=Path,
        required=True,
        help="exact cwd canonical Session directory",
    )
    parser.add_argument(
        "--home-sessions",
        type=Path,
        required=True,
        help="exact user-global canonical Session directory",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="print path-free scope selectors without starting or writing state",
    )
    return parser


def parse_launch(
    argv: Sequence[str] | None = None,
) -> tuple[CodingHostedLaunchV1, bool]:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        launch = CodingHostedLaunchV1(
            workspace=args.workspace.expanduser().resolve(),
            application_root=args.application_root.expanduser().resolve(),
            application_id=args.application_id,
            cwd_sessions=args.cwd_sessions.expanduser().resolve(),
            home_sessions=args.home_sessions.expanduser().resolve(),
        )
    except (ValueError, OSError):
        parser.error("invalid hosted launch configuration")
    return launch, args.describe


def execute_hosted_command(command: CodingHostedCommandV1) -> int:
    """Process-only runner; an incomplete cleanup is a fatal nonzero exit.

    The outer parent retains terminate/reap authority. Avoid Runner.close's
    unbounded cancellation join only when our retained cleanup is incomplete;
    do not claim that an abrupt process exit completed application settlement.
    """
    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    runner = asyncio.Runner()
    status = 0
    with redirect_stdout(sys.stderr):
        try:
            runner.run(command.run(input_fd=input_fd, output_fd=output_fd))
        except KeyboardInterrupt:
            status = 130
            print("hosted_interrupted", file=sys.stderr)
        except AppServiceError as error:
            status = 1
            print(error.code.value, file=sys.stderr)
        except Exception:
            status = 1
            print("hosted_application_failed", file=sys.stderr)
        finally:
            if command.cleanup_pending:
                print("hosted_cleanup_incomplete", file=sys.stderr, flush=True)
                os._exit(status or 1)
            runner.close()
    return status


def main(argv: Sequence[str] | None = None) -> int:
    launch, describe = parse_launch(argv)
    if describe:
        print(json.dumps(launch.describe(), ensure_ascii=False, sort_keys=True))
        return 0
    try:
        command = CodingHostedCommandV1(launch)
    except Exception:
        print("hosted_configuration_unavailable", file=sys.stderr)
        return 1
    return execute_hosted_command(command)


if __name__ == "__main__":
    raise SystemExit(main())
