"""Approval-gated, contained execution for digest-bound managed Skill actions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal, Protocol, cast

from loushang.harness.effects import (
    FilesystemEffect,
    NetworkEffect,
    PublicationEffect,
    ToolEffect,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle
from loushang.harness.resources.skill_actions import (
    ManagedSkillActionDeclaration,
    SkillActionCatalogSelection,
    SkillActionEffect,
    SkillActionRuntime,
)
from loushang.harness.tools.process_hosting import (
    _managed_process_launch_request,
)
from loushang.harness.workspace.process import AuthorizedProcessLauncher

_MAX_ACTION_OUTPUT_BYTES = 1_048_576


class ManagedSkillActionError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class _SkillActionSource(Protocol):
    source_kind: Literal["native", "package"]
    source_revision: str
    skill_content_digest: str

    @property
    def skill_root(self) -> Path: ...

    def read_script(self, relative_path: PurePosixPath) -> bytes: ...


@dataclass(frozen=True, slots=True)
class NativeSkillActionSource:
    """Catalog-captured native scripts, detached from later filesystem mutation."""

    source_revision: str
    skill_content_digest: str
    skill_root: Path
    scripts: Mapping[str, bytes] = field(repr=False)
    source_kind: Literal["native"] = "native"

    def __post_init__(self) -> None:
        _require_digest(self.source_revision, name="Native Skill source revision")
        _require_digest(self.skill_content_digest, name="Skill content digest")
        root = _absolute_directory(self.skill_root, name="Native Skill root")
        if not isinstance(self.scripts, Mapping):
            raise TypeError("Native Skill action scripts must be a mapping")
        scripts: dict[str, bytes] = {}
        for locator, body in self.scripts.items():
            path = canonical_plugin_relative_path(locator).as_posix()
            if not isinstance(body, bytes):
                raise TypeError("Native Skill action script bodies must be bytes")
            if path in scripts:
                raise ValueError("Native Skill action script locators must be unique")
            scripts[path] = body
        object.__setattr__(self, "skill_root", root)
        object.__setattr__(self, "scripts", MappingProxyType(scripts))

    def read_script(self, relative_path: PurePosixPath) -> bytes:
        try:
            return self.scripts[
                canonical_plugin_relative_path(relative_path).as_posix()
            ]
        except KeyError as exc:
            raise ManagedSkillActionError(
                "Native Skill action script is not in the captured source revision",
                code="skill_action_script_not_captured",
            ) from exc


@dataclass(frozen=True, slots=True)
class PackageSkillActionSource:
    """One admitted package revision and its exact Skill Resource identity."""

    source_revision: str
    skill_content_digest: str
    skill_root_locator: str
    package_content_digest: str
    revision_handle: VerifiedRevisionHandle = field(repr=False, compare=False)
    source_kind: Literal["package"] = "package"

    def __post_init__(self) -> None:
        _require_nonempty(self.source_revision, name="Package Skill source revision")
        _require_digest(self.skill_content_digest, name="Skill content digest")
        _require_digest(self.package_content_digest, name="Package content digest")
        if not isinstance(self.revision_handle, VerifiedRevisionHandle):
            raise TypeError("Package Skill action requires a verified revision handle")
        if self.revision_handle.closed:
            raise ValueError("Package Skill action revision handle must be live")
        if self.package_content_digest != self.revision_handle.content_digest:
            raise ValueError("Package Skill action revision digest does not match")
        root = canonical_plugin_relative_path(self.skill_root_locator)
        if self.revision_handle.entry_kind(root) != "directory":
            raise ValueError("Package Skill action root must be a revision directory")
        object.__setattr__(self, "skill_root_locator", root.as_posix())

    @property
    def skill_root(self) -> Path:
        return self.revision_handle.root / self.skill_root_locator

    def read_script(self, relative_path: PurePosixPath) -> bytes:
        self.revision_handle.verify()
        locator = PurePosixPath(
            self.skill_root_locator
        ) / canonical_plugin_relative_path(relative_path)
        with self.revision_handle.open_file(locator) as stream:
            return stream.read()


@dataclass(frozen=True, slots=True)
class ManagedSkillActionBinding:
    """Exact Catalog revision, action declaration, and source reader binding."""

    declaration: ManagedSkillActionDeclaration
    source_kind: Literal["native", "package"]
    source_revision: str
    skill_content_digest: str
    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    catalog_source_revision: str
    binding_fingerprint: str
    _source: _SkillActionSource = field(repr=False, compare=False)

    @classmethod
    def bind(
        cls,
        declaration: ManagedSkillActionDeclaration,
        *,
        selection: SkillActionCatalogSelection,
        source: NativeSkillActionSource | PackageSkillActionSource,
    ) -> ManagedSkillActionBinding:
        if not isinstance(declaration, ManagedSkillActionDeclaration):
            raise TypeError("Managed Skill action binding requires a declaration")
        if not isinstance(source, NativeSkillActionSource | PackageSkillActionSource):
            raise TypeError("Managed Skill action binding requires a supported source")
        if not isinstance(selection, SkillActionCatalogSelection):
            raise TypeError("Managed Skill action binding requires a Catalog selection")
        actual_revision = (
            source.package_content_digest
            if isinstance(source, PackageSkillActionSource)
            else source.source_revision
        )
        if (
            selection.source_kind != source.source_kind
            or selection.source_revision != actual_revision
            or selection.skill_content_digest != source.skill_content_digest
        ):
            raise ManagedSkillActionError(
                "Managed Skill action source does not match its Catalog selection",
                code="skill_action_catalog_selection_mismatch",
            )
        script = source.read_script(declaration.relative_script)
        _verify_script_digest(declaration, script)
        fingerprint = _fingerprint(
            {
                "action": declaration.to_dict(),
                "candidateFingerprint": selection.candidate_fingerprint,
                "catalogGeneration": selection.catalog_generation,
                "catalogSnapshotFingerprint": (
                    selection.catalog_snapshot_fingerprint
                ),
                "catalogSourceRevision": selection.source_revision,
                "domain": "loushang.managed-skill-action-binding/v1",
                "skillContentDigest": source.skill_content_digest,
                "sourceKind": source.source_kind,
                "sourceRevision": source.source_revision,
            }
        )
        return cls(
            declaration=declaration,
            source_kind=source.source_kind,
            source_revision=source.source_revision,
            skill_content_digest=source.skill_content_digest,
            catalog_generation=selection.catalog_generation,
            catalog_snapshot_fingerprint=(selection.catalog_snapshot_fingerprint),
            candidate_fingerprint=selection.candidate_fingerprint,
            catalog_source_revision=selection.source_revision,
            binding_fingerprint=fingerprint,
            _source=cast(_SkillActionSource, source),
        )

    @property
    def skill_root(self) -> Path:
        return self._source.skill_root

    def read_verified_script(self) -> bytes:
        script = self._source.read_script(self.declaration.relative_script)
        _verify_script_digest(self.declaration, script)
        expected = _fingerprint(
            {
                "action": self.declaration.to_dict(),
                "candidateFingerprint": self.candidate_fingerprint,
                "catalogGeneration": self.catalog_generation,
                "catalogSnapshotFingerprint": self.catalog_snapshot_fingerprint,
                "catalogSourceRevision": self.catalog_source_revision,
                "domain": "loushang.managed-skill-action-binding/v1",
                "skillContentDigest": self.skill_content_digest,
                "sourceKind": self.source_kind,
                "sourceRevision": self.source_revision,
            }
        )
        if expected != self.binding_fingerprint:
            raise ManagedSkillActionError(
                "Managed Skill action binding identity changed",
                code="skill_action_binding_changed",
            )
        return script


@dataclass(frozen=True, slots=True)
class SkillRuntimeBinding:
    """Host-selected exact executable for one declared runtime family."""

    runtime: SkillActionRuntime
    executable: Path
    executable_digest: str
    environment: tuple[tuple[str, str], ...] = ()

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
        return cls(
            runtime=runtime,
            executable=path,
            executable_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
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
            digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        except OSError as exc:
            raise ManagedSkillActionError(
                "Managed Skill runtime could not be revalidated",
                code="skill_action_runtime_changed",
            ) from exc
        if digest != self.executable_digest:
            raise ManagedSkillActionError(
                "Managed Skill runtime changed after binding",
                code="skill_action_runtime_changed",
            )


@dataclass(frozen=True, slots=True)
class ManagedSkillActionResult:
    return_code: int
    stdout: bytes
    stderr: bytes


async def execute_managed_skill_action(
    binding: ManagedSkillActionBinding,
    *,
    runtime: SkillRuntimeBinding,
    launcher: AuthorizedProcessLauncher,
    workspace_root: str | Path,
    correlation_id: str,
    signal: object | None = None,
) -> ManagedSkillActionResult:
    """Execute exact script bytes through mandatory Approval and containment."""

    if not isinstance(binding, ManagedSkillActionBinding):
        raise TypeError("Managed Skill execution requires an action binding")
    if not isinstance(runtime, SkillRuntimeBinding):
        raise TypeError("Managed Skill execution requires a runtime binding")
    if getattr(launcher, "approval_required", False) is not True:
        raise ManagedSkillActionError(
            "Managed Skill action launcher does not require Approval",
            code="skill_action_approval_not_required",
        )
    if getattr(launcher, "containment_requirement", None) != "required":
        raise ManagedSkillActionError(
            "Managed Skill action requires enforced containment",
            code="skill_action_containment_required",
        )
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
            "candidateFingerprint": binding.candidate_fingerprint,
            "catalogGeneration": binding.catalog_generation,
            "catalogSnapshotFingerprint": binding.catalog_snapshot_fingerprint,
            "catalogSourceRevision": binding.catalog_source_revision,
            "runtimeDigest": runtime.executable_digest,
            "scriptDigest": declaration.script_digest,
            "skillContentDigest": binding.skill_content_digest,
            "sourceKind": binding.source_kind,
            "sourceRevision": binding.source_revision,
        },
    )
    handle = await launcher.start(
        request,
        correlation_id=correlation_id,
        signal=signal,
    )
    try:
        await handle.write_stdin(script)
        await handle.close_stdin()
        stdout, stderr, exit_status = await asyncio.gather(
            handle.read_stdout(_MAX_ACTION_OUTPUT_BYTES),
            handle.read_stderr(_MAX_ACTION_OUTPUT_BYTES),
            handle.wait(),
        )
        return ManagedSkillActionResult(
            return_code=exit_status.return_code,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        await handle.close()


def _verify_script_digest(
    declaration: ManagedSkillActionDeclaration,
    body: bytes,
) -> None:
    if hashlib.sha256(body).hexdigest() != declaration.script_digest:
        raise ManagedSkillActionError(
            "Managed Skill action script does not match its declaration",
            code="skill_action_script_digest_mismatch",
        )


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


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ManagedSkillActionBinding",
    "ManagedSkillActionError",
    "ManagedSkillActionResult",
    "NativeSkillActionSource",
    "PackageSkillActionSource",
    "SkillRuntimeBinding",
    "execute_managed_skill_action",
]
