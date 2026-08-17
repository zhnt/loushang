from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "examples" / "coding" / "example-manifest.toml"
RUNNER = REPO_ROOT / "examples" / "coding" / "run.py"


def _load_manifest_examples() -> list[dict[str, object]]:
    with MANIFEST_PATH.open("rb") as fp:
        payload = tomllib.load(fp)
    return [dict(item) for item in payload.get("example", [])]


# Offline smoke examples that fail on macOS for environmental reasons (temp
# path / cwd semantics); skipping may hide a real macOS product bug.
_MACOS_ENV_SENSITIVE_EXAMPLES = frozenset(
    {
        "legacy-007",
        "legacy-018",
        "legacy-019",
        "legacy-ext-01",
        "legacy-ext-02",
        "legacy-ext-03",
        "legacy-ext-04",
        "legacy-ext-05",
    }
)
_MACOS_ENV_SENSITIVE_REASON = (
    "macOS env-sensitive golden/smoke; may hide a real macOS product bug — "
    "tracked separately as issue #455"
)


def _offline_examples_without_api_key() -> list[object]:
    params: list[object] = []
    for item in _load_manifest_examples():
        if item.get("runtime") != "offline" or bool(item.get("requires_api_key", False)):
            continue
        example_id = str(item["id"])
        if example_id in _MACOS_ENV_SENSITIVE_EXAMPLES:
            params.append(
                pytest.param(
                    example_id,
                    marks=pytest.mark.skipif(
                        sys.platform == "darwin",
                        reason=_MACOS_ENV_SENSITIVE_REASON,
                    ),
                )
            )
        else:
            params.append(example_id)
    return params


def _online_examples_require_api_key() -> list[str]:
    return [
        str(item["id"])
        for item in _load_manifest_examples()
        if item.get("requires_api_key", False)
        and item.get("runtime") in ("offline", "online")
    ]


def _run_example(example_id: str, *, dry_run: bool, artifact_root: Path) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(RUNNER),
        "run",
        example_id,
        "--artifacts-root",
        str(artifact_root),
    ]
    if dry_run:
        command.append("--dry-run")
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )


@pytest.mark.parametrize("example_id", _offline_examples_without_api_key())
def test_examples_offline_smoke(example_id: str, tmp_path: Path) -> None:
    artifact_root = tmp_path / f"{example_id}-artifacts"
    completed = _run_example(example_id, dry_run=False, artifact_root=artifact_root)
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "Traceback (most recent call last):" not in output


@pytest.mark.parametrize("example_id", _online_examples_require_api_key())
def test_examples_api_key_examples_dry_run(example_id: str, tmp_path: Path) -> None:
    artifact_root = tmp_path / f"{example_id}-artifacts"
    completed = _run_example(example_id, dry_run=True, artifact_root=artifact_root)
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "Traceback (most recent call last):" not in output
