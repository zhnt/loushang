"""Approval-gated, contained execution for digest-bound managed Skill actions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loushang.harness.effects import (
    FilesystemEffect,
    NetworkEffect,
    PublicationEffect,
    ToolEffect,
)
from loushang.harness.resources.skill_actions import (
    CatalogManagedSkillAction,
    ManagedSkillActionDeclaration,
    SkillActionEffect,
    SkillActionRuntime,
)
from loushang.harness.tools.process_hosting import (
    ScopeBoundProcessLauncher,
    _managed_process_launch_request,
)
from loushang.harness.workspace.process._sealed_executable import (
    SealedProcessExecutableUnavailable,
    _BoundProcessDirectory,
    _capture_bound_process_directory,
    _capture_sealed_process_executable,
    _SealedProcessExecutable,
    _stable_process_executable_digest,
)

_MAX_ACTION_OUTPUT_BYTES = 1_048_576
_ACTION_OUTPUT_CHUNK_BYTES = 64 * 1024


class ManagedSkillActionError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True, init=False)
class ManagedSkillActionBinding:
    """Tool-layer view of Resource-owner-minted Catalog action evidence."""

    declaration: ManagedSkillActionDeclaration
    source_kind: Literal["native", "package"]
    source_revision: str
    skill_content_digest: str
    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    catalog_source_revision: str
    action_document_digest: str
    binding_fingerprint: str
    _catalog_action: CatalogManagedSkillAction = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("Managed Skill bindings require Catalog-owner evidence")

    @classmethod
    def bind(
        cls,
        catalog_action: CatalogManagedSkillAction,
    ) -> ManagedSkillActionBinding:
        if not isinstance(catalog_action, CatalogManagedSkillAction):
            raise TypeError("Managed Skill action requires Catalog-owner evidence")
        catalog_action.verify()
        selection = catalog_action.selection
        binding = object.__new__(cls)
        for name, value in (
            ("declaration", catalog_action.declaration),
            ("source_kind", selection.source_kind),
            ("source_revision", selection.source_revision),
            ("skill_content_digest", selection.skill_content_digest),
            ("catalog_generation", selection.catalog_generation),
            (
                "catalog_snapshot_fingerprint",
                selection.catalog_snapshot_fingerprint,
            ),
            ("candidate_fingerprint", selection.candidate_fingerprint),
            ("catalog_source_revision", selection.source_revision),
            ("action_document_digest", catalog_action.action_document_digest),
            ("binding_fingerprint", catalog_action.binding_source_fingerprint),
            ("_catalog_action", catalog_action),
        ):
            object.__setattr__(binding, name, value)
        binding._validate()
        return binding

    def _validate(self) -> None:
        self._catalog_action.verify()
        selection = self._catalog_action.selection
        expected = (
            self._catalog_action.declaration,
            selection.source_kind,
            selection.source_revision,
            selection.skill_content_digest,
            selection.catalog_generation,
            selection.catalog_snapshot_fingerprint,
            selection.candidate_fingerprint,
            selection.source_revision,
            self._catalog_action.action_document_digest,
            self._catalog_action.binding_source_fingerprint,
        )
        actual = (
            self.declaration,
            self.source_kind,
            self.source_revision,
            self.skill_content_digest,
            self.catalog_generation,
            self.catalog_snapshot_fingerprint,
            self.candidate_fingerprint,
            self.catalog_source_revision,
            self.action_document_digest,
            self.binding_fingerprint,
        )
        if actual != expected:
            raise ManagedSkillActionError(
                "Managed Skill action binding identity changed",
                code="skill_action_binding_changed",
            )

    @property
    def skill_root(self) -> Path:
        return self._catalog_action.skill_root

    def read_verified_script(self) -> bytes:
        self._validate()
        return self._catalog_action.read_script()

    def _skill_root_identity(self) -> tuple[int, int]:
        self._validate()
        return self._catalog_action._skill_root_identity


@dataclass(frozen=True, slots=True)
class SkillRuntimeBinding:
    """Host-selected exact executable for one declared runtime family."""

    runtime: SkillActionRuntime
    executable: Path
    executable_digest: str
    environment: tuple[tuple[str, str], ...] = field(default=(), repr=False)

    @classmethod
    def capture(
        cls,
        *,
        runtime: SkillActionRuntime,
        executable: str | Path,
        environment: tuple[tuple[str, str], ...] = (),
    ) -> SkillRuntimeBinding:
        path = Path(executable).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("Skill runtime executable must be a regular file")
        try:
            digest, _ = _stable_process_executable_digest(path)
        except (OSError, SealedProcessExecutableUnavailable) as exc:
            raise ValueError(
                "Skill runtime executable must be a bounded stable regular file"
            ) from exc
        return cls(
            runtime=runtime,
            executable=path,
            executable_digest=digest,
            environment=environment,
        )

    def __post_init__(self) -> None:
        if self.runtime not in {"posix", "python"}:
            raise ValueError("Unsupported Skill runtime binding")
        executable = Path(self.executable).expanduser().resolve(strict=True)
        if not executable.is_file():
            raise ValueError("Skill runtime executable must be a regular file")
        _require_digest(self.executable_digest, name="Skill runtime digest")
        environment = _environment_tuple(self.environment)
        object.__setattr__(self, "executable", executable)
        object.__setattr__(self, "environment", environment)

    def verify(self) -> None:
        try:
            digest, _ = _stable_process_executable_digest(self.executable)
        except (OSError, SealedProcessExecutableUnavailable) as exc:
            raise ManagedSkillActionError(
                "Managed Skill runtime could not be revalidated",
                code="skill_action_runtime_changed",
            ) from exc
        if digest != self.executable_digest:
            raise ManagedSkillActionError(
                "Managed Skill runtime changed after binding",
                code="skill_action_runtime_changed",
            )

    def _capture_sealed_executable(self) -> _SealedProcessExecutable:
        try:
            return _capture_sealed_process_executable(
                self.executable,
                expected_digest=self.executable_digest,
            )
        except (OSError, SealedProcessExecutableUnavailable) as exc:
            raise ManagedSkillActionError(
                "Managed Skill runtime could not be sealed",
                code="skill_action_runtime_unsealable",
            ) from exc


@dataclass(frozen=True, slots=True)
class ManagedSkillActionResult:
    return_code: int
    stdout: bytes
    stderr: bytes


async def execute_managed_skill_action(
    binding: ManagedSkillActionBinding,
    *,
    runtime: SkillRuntimeBinding,
    launcher: ScopeBoundProcessLauncher,
    workspace_root: str | Path,
    correlation_id: str,
    signal: object | None = None,
) -> ManagedSkillActionResult:
    """Execute exact script bytes through mandatory Approval and containment."""

    if not isinstance(binding, ManagedSkillActionBinding):
        raise TypeError("Managed Skill execution requires an action binding")
    binding._validate()
    if not isinstance(runtime, SkillRuntimeBinding):
        raise TypeError("Managed Skill execution requires a runtime binding")
    if type(launcher) is not ScopeBoundProcessLauncher:
        raise TypeError("Managed Skill execution requires the Process owner launcher")
    launcher._verify_managed_start_authority()
    declaration = binding.declaration
    if runtime.runtime != declaration.runtime:
        raise ManagedSkillActionError(
            "Managed Skill action runtime does not match its declaration",
            code="skill_action_runtime_mismatch",
        )
    runtime.verify()
    script = binding.read_verified_script()
    workspace = _absolute_directory(workspace_root, name="Skill workspace root")
    cwd = binding.skill_root if declaration.cwd_policy == "skill" else workspace
    effective_environment = _merge_environment(
        runtime.environment,
        declaration.environment,
    )
    command = (
        str(runtime.executable),
        *(("-",) if declaration.runtime == "python" else ("-s", "--")),
        *declaration.argv,
    )
    sealed_executable = runtime._capture_sealed_executable()
    bound_cwd: _BoundProcessDirectory | None = None
    try:
        if declaration.cwd_policy == "skill":
            try:
                bound_cwd = _capture_bound_process_directory(
                    binding.skill_root,
                    expected_identity=binding._skill_root_identity(),
                )
            except (OSError, SealedProcessExecutableUnavailable) as exc:
                raise ManagedSkillActionError(
                    "Managed Skill cwd could not be bound",
                    code="skill_action_cwd_unsealable",
                ) from exc

        def validate_start_evidence() -> None:
            sealed_executable.verify()
            if bound_cwd is not None:
                bound_cwd.verify()
            binding._validate()

        request = _managed_process_launch_request(
            command=command,
            cwd=str(cwd),
            effective_environment=effective_environment,
            declared_effects=tuple(
                _tool_effect(
                    effect, skill_root=binding.skill_root, workspace_root=workspace
                )
                for effect in declaration.effects
            ),
            authorization_metadata={
                "actionBindingFingerprint": binding.binding_fingerprint,
                "actionId": declaration.action_id,
                "actionDocumentDigest": binding.action_document_digest,
                "candidateFingerprint": binding.candidate_fingerprint,
                "catalogGeneration": binding.catalog_generation,
                "catalogSnapshotFingerprint": binding.catalog_snapshot_fingerprint,
                "catalogSourceRevision": binding.catalog_source_revision,
                "cwdDevice": bound_cwd.device if bound_cwd is not None else None,
                "cwdInode": bound_cwd.inode if bound_cwd is not None else None,
                "runtimeDigest": runtime.executable_digest,
                "runtimeSize": sealed_executable.size,
                "scriptDigest": declaration.script_digest,
                "skillContentDigest": binding.skill_content_digest,
                "sourceKind": binding.source_kind,
                "sourceRevision": binding.source_revision,
            },
            pre_start_validator=validate_start_evidence,
            sealed_executable=sealed_executable,
            bound_cwd_directory=bound_cwd,
        )
        handle = await launcher._start_managed(
            request,
            correlation_id=correlation_id,
            signal=signal,
        )
    except BaseException:
        if bound_cwd is not None:
            bound_cwd.close()
        sealed_executable.close()
        raise
    try:
        stdout_task = asyncio.create_task(
            _drain_action_output(handle.read_stdout, stream="stdout"),
            name="managed-skill-action-stdout",
        )
        stderr_task = asyncio.create_task(
            _drain_action_output(handle.read_stderr, stream="stderr"),
            name="managed-skill-action-stderr",
        )
        writer_task = asyncio.create_task(
            _write_action_input(handle, script),
            name="managed-skill-action-stdin",
        )
        wait_task = asyncio.create_task(
            handle.wait(),
            name="managed-skill-action-wait",
        )
        tasks = (writer_task, stdout_task, stderr_task, wait_task)
        try:
            _, stdout, stderr, exit_status = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await handle.terminate()
            raise
        return ManagedSkillActionResult(
            return_code=exit_status.return_code,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        try:
            await handle.close()
        finally:
            if bound_cwd is not None:
                bound_cwd.close()
            sealed_executable.close()


async def _write_action_input(handle: object, script: bytes) -> None:
    write_stdin = getattr(handle, "write_stdin", None)
    close_stdin = getattr(handle, "close_stdin", None)
    if not callable(write_stdin) or not callable(close_stdin):
        raise TypeError("Managed Skill process handle has no stdin owner")
    try:
        await write_stdin(script)
    finally:
        await close_stdin()


async def _drain_action_output(
    reader: Callable[[int], Awaitable[bytes]],
    *,
    stream: Literal["stderr", "stdout"],
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await reader(_ACTION_OUTPUT_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > _MAX_ACTION_OUTPUT_BYTES:
            raise ManagedSkillActionError(
                f"Managed Skill action {stream} exceeds the byte limit",
                code="skill_action_output_limit_exceeded",
            )
        chunks.append(chunk)


def _tool_effect(
    effect: SkillActionEffect,
    *,
    skill_root: Path,
    workspace_root: Path,
) -> ToolEffect:
    if effect.kind.startswith("filesystem."):
        operation = effect.kind.partition(".")[2]
        path = skill_root if effect.target == "skill" else workspace_root
        return FilesystemEffect(operation=operation, paths=(str(path),))  # type: ignore[arg-type]
    if effect.kind == "network.request":
        return NetworkEffect(target=effect.target, mutation=False)
    if effect.kind == "network.mutate":
        return NetworkEffect(target=effect.target, mutation=True)
    return PublicationEffect(target=effect.target)


def _merge_environment(
    runtime: tuple[tuple[str, str], ...],
    declared: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    values = dict(runtime)
    overlap = set(values).intersection(name for name, _ in declared)
    if overlap:
        raise ManagedSkillActionError(
            "Managed Skill action environment overrides a runtime-owned name",
            code="skill_action_environment_conflict",
        )
    values.update(declared)
    return tuple(sorted(values.items()))


def _environment_tuple(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, str):
        raise TypeError("Skill runtime environment must contain string pairs")
    try:
        items: tuple[object, ...] = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError("Skill runtime environment must contain string pairs") from exc
    result: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, str):
            raise TypeError("Skill runtime environment must contain string pairs")
        try:
            pair: tuple[object, ...] = tuple(item)  # type: ignore[arg-type]
        except TypeError as exc:
            raise TypeError(
                "Skill runtime environment must contain string pairs"
            ) from exc
        if (
            len(pair) != 2
            or not isinstance(pair[0], str)
            or not pair[0]
            or not isinstance(pair[1], str)
        ):
            raise ValueError("Skill runtime environment entry is invalid")
        result.append((pair[0], pair[1]))
    names = tuple(name for name, _ in result)
    if names != tuple(sorted(names)) or len(names) != len(set(names)):
        raise ValueError("Skill runtime environment must be sorted and unique")
    return tuple(result)


def _absolute_directory(value: str | Path, *, name: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"{name} must be a directory")
    return resolved


def _require_digest(value: object, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


__all__ = [
    "ManagedSkillActionBinding",
    "ManagedSkillActionError",
    "ManagedSkillActionResult",
    "SkillRuntimeBinding",
    "execute_managed_skill_action",
]
