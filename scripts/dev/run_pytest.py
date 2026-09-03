"""Run pytest inside one leased, machine-local scratch namespace.

The wrapper is the repository-owned pytest composition edge.  It keeps test
scratch outside the checkout, gives concurrent invocations disjoint roots,
reclaims only provably inactive crash residue, and removes the current root on
normal exit.
"""

from __future__ import annotations

import errno
import os
import shlex
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path

import pytest

from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_scope import (
    RunLease,
    RuntimeScope,
    RuntimeSweepPolicy,
    resolve_runtime_scope,
)

_PYTEST_RUNTIME_NAMESPACE = "pytest-runs"
_PYTEST_BASETEMP_NAME = "basetemp"
_CAPACITY_RESERVATION_NAME = ".capacity-reservation"
_DEFAULT_MIN_FREE_BYTES = 64 * 1024 * 1024
_PYTEST_SWEEP_POLICY = RuntimeSweepPolicy(
    stale_after_seconds=0,
    max_inactive_runs=0,
    max_inactive_bytes=0,
)


class PytestScratchError(RuntimeError):
    """Stable refusal raised before pytest receives a scratch directory."""


def resolve_pytest_runtime_scope(
    *,
    environ: Mapping[str, str] | None = None,
    run_id: str | None = None,
) -> RuntimeScope:
    """Resolve a pytest-only lease namespace without filesystem effects."""

    paths = resolve_platform_paths(environ=environ)
    return resolve_runtime_scope(
        paths=paths,
        run_id=run_id,
        run_namespace=_PYTEST_RUNTIME_NAMESPACE,
    )


def run_pytest(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    pytest_main: Callable[[list[str]], int | pytest.ExitCode] = pytest.main,
) -> int:
    """Run pytest once and preserve its result across best-effort cleanup."""

    values = os.environ if environ is None else environ
    _reject_external_basetemp((*argv, *_environment_pytest_arguments(values)))
    minimum_free_bytes = _minimum_free_bytes(values)
    scope = resolve_pytest_runtime_scope(environ=values)
    try:
        lease = RunLease.acquire(scope, sweep_policy=_PYTEST_SWEEP_POLICY)
    except (OSError, ValueError) as error:
        raise PytestScratchError("cannot acquire pytest scratch ownership") from error

    result = int(pytest.ExitCode.INTERNAL_ERROR)
    try:
        _preflight_capacity(scope.run_dir, minimum_free_bytes)
        result = int(
            pytest_main(
                [
                    *argv,
                    f"--basetemp={scope.run_dir / _PYTEST_BASETEMP_NAME}",
                ]
            )
        )
        return result
    finally:
        lease.close()
        if scope.run_dir.exists():
            print(
                "warning: pytest scratch cleanup was incomplete; "
                "the next managed run will retry it",
                file=sys.stderr,
            )


def _reject_external_basetemp(argv: Sequence[str]) -> None:
    for argument in argv:
        if argument == "--basetemp" or argument.startswith("--basetemp="):
            raise PytestScratchError(
                "--basetemp is owned by scripts/dev/run_pytest.py"
            )


def _environment_pytest_arguments(environ: Mapping[str, str]) -> tuple[str, ...]:
    raw = environ.get("PYTEST_ADDOPTS", "")
    try:
        return tuple(shlex.split(raw))
    except ValueError as error:
        raise PytestScratchError("PYTEST_ADDOPTS is not valid shell syntax") from error


def _minimum_free_bytes(environ: Mapping[str, str]) -> int:
    raw = environ.get("LOUSHANG_PYTEST_MIN_FREE_BYTES")
    if raw is None:
        return _DEFAULT_MIN_FREE_BYTES
    try:
        value = int(raw)
    except ValueError as error:
        raise PytestScratchError(
            "LOUSHANG_PYTEST_MIN_FREE_BYTES must be a non-negative integer"
        ) from error
    if value < 0:
        raise PytestScratchError(
            "LOUSHANG_PYTEST_MIN_FREE_BYTES must be a non-negative integer"
        )
    return value


def _preflight_capacity(path: Path, minimum_free_bytes: int) -> None:
    try:
        available = shutil.disk_usage(path).free
    except OSError as error:
        raise PytestScratchError(
            "cannot inspect pytest scratch capacity"
        ) from error
    if available < minimum_free_bytes:
        raise PytestScratchError(
            "pytest scratch has insufficient free capacity "
            f"({available} available, {minimum_free_bytes} required)"
        )
    if minimum_free_bytes == 0 or not hasattr(os, "posix_fallocate"):
        return
    reservation = path / _CAPACITY_RESERVATION_NAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(reservation, flags, 0o600)
    except OSError as error:
        raise PytestScratchError(
            "cannot create pytest scratch capacity reservation"
        ) from error
    try:
        os.posix_fallocate(descriptor, 0, minimum_free_bytes)
    except OSError as error:
        if error.errno in {
            errno.EINVAL,
            errno.ENOSYS,
            getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
        }:
            return
        raise PytestScratchError(
            "pytest scratch quota cannot reserve the required capacity"
        ) from error
    finally:
        os.close(descriptor)
        with suppress(FileNotFoundError):
            reservation.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run_pytest(sys.argv[1:] if argv is None else argv)
    except PytestScratchError as error:
        print(f"pytest scratch refused: {error}", file=sys.stderr)
        return int(pytest.ExitCode.USAGE_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
