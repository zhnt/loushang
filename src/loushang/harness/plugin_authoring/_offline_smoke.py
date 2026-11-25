"""Disposable Product state and evidence for offline authoring checks."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal

from loushang.harness.resources.packages._file_consumption import (
    borrowed_binary_stream,
    closing_descriptor,
)

if TYPE_CHECKING:
    from loushang.harness.transcript.product_session import ProductTranscriptSession


class _SelectionRefusal(RuntimeError):
    pass


class _UseRefusal(RuntimeError):
    pass


def capture_authoring_input(
    path: Path,
    *,
    maximum_bytes: int,
    invalid_input: str,
    changed_before_read: str,
    changed_during_read: str,
    require_visible_source: bool = False,
) -> bytes:
    """Capture one bounded regular file before opening a disposable workspace."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum_bytes:
        raise ValueError(invalid_input)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with (
        closing_descriptor(os.open(path, flags)) as descriptor,
        borrowed_binary_stream(descriptor, "rb") as stream,
    ):
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ) != (before.st_dev, before.st_ino, before.st_size):
            raise ValueError(changed_before_read)
        body = stream.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
    if (
        not 0 < len(body) <= maximum_bytes
        or _file_revision(opened) != _file_revision(after)
    ):
        raise ValueError(changed_during_read)
    if require_visible_source and (
        len(body) != before.st_size or path.stat().st_ino != before.st_ino
    ):
        raise ValueError(changed_during_read)
    return body


def _file_revision(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


@contextmanager
def hold_authoring_home(path: Path) -> Iterator[None]:
    previous = os.environ.get("LOUSHANG_HOME")
    path.mkdir(mode=0o700)
    os.environ["LOUSHANG_HOME"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LOUSHANG_HOME", None)
        else:
            os.environ["LOUSHANG_HOME"] = previous


def record_product_smoke_failure(
    report: dict[str, object],
    stage: str,
    code: str,
    detail: str | None = None,
    scratch_root: Path | None = None,
) -> dict[str, object]:
    report["failedStage"] = stage
    report["errorCode"] = code
    if stage in {"product_admission", "product_selection", "product_use"}:
        key = {
            "product_admission": "productAdmission",
            "product_selection": "productSelection",
            "product_use": "productUse",
        }[stage]
        report[key] = "failed"
    if detail:
        report["detail"] = (
            detail.replace(str(scratch_root), "<disposable-workspace>")
            if scratch_root is not None
            else detail
        )[:1000]
    return report


@contextmanager
def hold_authoring_wheel(
    path: str | Path, report: dict[str, object], *, native_worker: bool,
) -> Iterator[tuple[Path, Path, Path] | None]:
    """Capture one author Wheel and own its isolated environment through cleanup."""
    try:
        source = Path(path)
        body = capture_authoring_input(
            source,
            maximum_bytes=2 * 1024 * 1024,
            invalid_input="Wheel must be a regular file within 2 MiB",
            changed_before_read="Wheel changed before capture",
            changed_during_read="Wheel changed during capture",
        )
    except (OSError, ValueError) as exc:
        record_product_smoke_failure(report, "artifact", "wheel_capture_refused", str(exc))
        yield None
        return
    report["artifactSha256"] = sha256(body).hexdigest()
    prefix = "loushang-worker-author-smoke-" if native_worker else "loushang-author-smoke-"
    with TemporaryDirectory(prefix=prefix) as scratch:
        root = Path(scratch)
        if native_worker:
            # Native Package admission requires resolved on-disk paths.
            root = root.resolve(strict=True)
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        if native_worker:
            workspace = workspace.resolve(strict=True)
            artifact_dir = root
        else:
            artifact_dir = root / "artifact"
            artifact_dir.mkdir(mode=0o700)
        captured = artifact_dir / source.name
        captured.write_bytes(body)
        with hold_authoring_home(root / "home"):
            yield root, workspace, captured


def smoke_data_plugin_use(
    report: dict[str, object],
    *,
    root: Path,
    wheel: Path,
    plugin_id: str,
    run_cli: Callable[[tuple[str, ...]], str | None],
    prove_resource_use: Callable[[], None],
    after_enable: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Prove the standard Package install and enable before checking resource use."""
    refusal = run_cli(("--install-package", str(wheel), "--package-scope", "project"))
    if refusal is not None:
        return record_product_smoke_failure(
            report, "product_admission", "product_install_refused", refusal, root
        )
    report["productAdmission"] = "passed"
    refusal = run_cli(("--enable-plugin", plugin_id))
    if refusal is not None:
        return record_product_smoke_failure(
            report, "product_selection", "product_enable_refused", refusal, root
        )
    if after_enable is not None:
        after_enable()
    try:
        prove_resource_use()
    except _SelectionRefusal as exc:
        stage, code, detail = "product_selection", "resource_not_selected", str(exc)
    except _UseRefusal as exc:
        report["productSelection"] = "passed"
        stage, code, detail = "product_use", "resource_use_unproven", str(exc)
    except Exception as exc:
        stage, code, detail = "product_selection", "resource_selection_unproven", str(exc)
    else:
        report.update(productSelection="passed", productUse="passed", status="passed")
        return report
    return record_product_smoke_failure(report, stage, code, detail, root)


def prove_prepared_authoring_resource_use(
    transcript: ProductTranscriptSession, *, invocation: str, expected_body: str,
) -> None:
    """Check both the logical input and prepared request after the offline turn."""
    snapshots = [
        entry for entry in transcript.get_entries() if entry.kind == "model.input.prepared"
    ]
    if len(snapshots) != 1:
        raise RuntimeError("new Session did not persist exactly one prepared model input")
    snapshot_id = getattr(snapshots[0].payload, "snapshot_id", None)
    if not isinstance(snapshot_id, str):
        raise RuntimeError("prepared model input has no snapshot ID")
    rebuilt = transcript.rebuild_model_input(snapshot_id)
    for surface in (rebuilt.logical_input, rebuilt.prepared_payload):
        user_text = tuple(_user_message_text(surface))
        if not any(expected_body in text for text in user_text):
            raise RuntimeError("selected Resource body is absent from prepared user message")
        if any(invocation in text for text in user_text):
            raise RuntimeError("raw slash invocation remained in prepared user message")


def _user_message_text(logical_input: object) -> Iterator[str]:
    if not isinstance(logical_input, dict):
        return
    messages = logical_input.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    value = part.get("text")
                    if isinstance(value, str):
                        yield value


def smoke_worker_candidate_selection(
    report: dict[str, object],
    *,
    root: Path,
    command_prefix: tuple[str, ...],
    wheel: Path,
    plugin_id: str,
    contribution_id: str,
    owner_id: str,
    native_platform: Literal["linux-x86_64", "windows-amd64"],
) -> dict[str, object]:
    """Exercise native candidate admission and read-back in an authoring workspace."""

    def command(action: str, *arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            (*command_prefix, action, *arguments),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip()[-1000:] or "Worker command refused")
        result = json.loads(completed.stdout)
        if not isinstance(result, dict):
            raise ValueError("Worker command returned an invalid Product result")
        return result

    linux = native_platform == "linux-x86_64"
    failure_stage = "product_admission"
    try:
        capture = command(
            "candidate-capture",
            "--wheel",
            str(wheel),
            "--contribution-id",
            contribution_id,
            "--owner-id",
            owner_id,
            *(("--native-platform", native_platform) if linux else ()),
        )
        binding = capture["workerCandidateBinding"]
        if not isinstance(binding, dict) or binding.get("pluginId") != plugin_id:
            raise ValueError("Captured Worker identity differs from request")
        digest = binding["artifactDigest"]
        if digest != report["artifactSha256"]:
            raise ValueError("Captured Worker differs from the author Wheel")
        candidate = ("--plugin-id", plugin_id, "--artifact-digest", digest)
        installed = command(
            "candidate-install", *candidate, "--operation-id", "author-smoke-install"
        )
        report["productAdmission"] = "passed"
        failure_stage = "product_selection"
        install_result = installed["candidateInstall"]
        if not isinstance(install_result, dict):
            raise ValueError("Product install result is unavailable")
        revision = install_result["inventoryRevision"]
        if type(revision) is not int:
            raise ValueError("Product inventory revision is unavailable")
        command(
            "candidate-enable",
            *candidate,
            "--operation-id",
            "author-smoke-enable",
            "--expected-inventory-revision",
            str(revision),
        )
        status = command(
            "candidate-status" if linux else "candidate-selection", "--plugin-id", plugin_id
        )
        selection = status["candidateSelection"]
        if not isinstance(selection, dict) or selection.get("stage") != "observed_in_read":
            raise ValueError("Selected Worker was not observed in Product")
        if linux:
            selected = (
                status.get("snapshotStatus") == "partial_evidence"
                and status.get("candidateOptInAlignment") == "not_allowed"
            )
        else:
            selected = (
                selection.get("pluginId") == plugin_id
                and selection.get("artifactDigest") == digest
                and status.get("productUse") == "not_checked"
            )
        if not selected:
            raise ValueError("Selected Worker was not observed in Product")
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        code = (
            "worker_candidate_admission_refused"
            if failure_stage == "product_admission"
            else "worker_candidate_selection_refused"
        )
        return record_product_smoke_failure(report, failure_stage, code, str(exc), root)
    report["productSelection"] = "passed"
    report["selectedPluginVersion"] = selection["pluginVersion"]
    report["status"] = "passed"
    return report
