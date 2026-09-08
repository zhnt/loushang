#!/usr/bin/env python3
"""Run the exact G16 native terminal contract from an isolated local wheel."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = "docs/internals/architecture/appserver/detachable-local-workspace-g16-evidence-manifest.json"
_PROBE = """
import hashlib, importlib, json, sys, zipfile
from importlib.metadata import distribution
from pathlib import Path
from urllib.parse import urldefrag
prefix = Path(sys.prefix).resolve()
names = ('loushang.coding.cli.mux', 'loushang.harnesstui.mux.shell',
         'loushang.appserver.local', 'loushang.appservice.client_scope',
         'loushang.apphost.local', 'loushang.tui.ui_parts.text_pager')
assert all(Path(importlib.import_module(name).__file__).resolve().is_relative_to(prefix)
           for name in names), 'G16 import escaped isolated installation'
package = distribution('loushang')
direct = json.loads(package.read_text('direct_url.json') or '{}')
wheel = Path(sys.argv[2]).resolve(strict=True)
assert 'archive_info' in direct and urldefrag(direct.get('url', '')).url == wheel.as_uri(), 'G16 installation is not the selected wheel'
with wheel.open('rb') as artifact:
    assert hashlib.file_digest(artifact, 'sha256').hexdigest() == sys.argv[1], 'G16 wheel changed during installation'
# Installers need not retain an archive hash in direct_url.json. Compare the
# actual installed package bytes with the hashed wheel, not installer metadata.
with zipfile.ZipFile(wheel) as artifact:
    names = [name for name in artifact.namelist() if name.startswith('loushang/') and not name.endswith('/')]
    assert names, 'G16 wheel contains no package files'
    for name in names:
        installed = Path(package.locate_file(name)).resolve(strict=True)
        assert installed.is_relative_to(prefix), 'G16 package file escaped installation'
        assert installed.read_bytes() == artifact.read(name), 'G16 installed bytes differ from wheel'
print('G16 isolated wheel origins, digest and installed bytes verified', flush=True)
"""


def _run(
    argv: list[str], *, cwd: Path, environment: dict[str, str], timeout: int
) -> None:
    subprocess.run(argv, cwd=cwd, env=environment, check=True, timeout=timeout)


def _verify_wheel_source(wheel: Path) -> None:
    """Reject stale setuptools build output before creating an environment."""
    source = (_ROOT / "src").resolve(strict=True)
    expected = {
        path.relative_to(source).as_posix()
        for path in (source / "loushang").rglob("*.py")
    }
    with zipfile.ZipFile(wheel) as archive:
        names = [
            item.filename
            for item in archive.infolist()
            if item.filename.startswith("loushang/") and not item.is_dir()
        ]
        if (
            not expected
            or len(names) != len(set(names))
            or {name for name in names if name.endswith(".py")} != expected
        ):
            raise ValueError("G16 wheel modules differ from current source")
        for name in names:
            path = (source / name).resolve()
            if (
                not path.is_relative_to(source)
                or not path.is_file()
                or path.read_bytes() != archive.read(name)
            ):
                raise ValueError("G16 wheel package bytes differ from current source")
    print("G16 wheel/source package modules and bytes verified", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wheel", type=Path)
    source.add_argument("--wheel-dir", type=Path)
    parser.add_argument(
        "--platform", choices=("linux", "darwin", "win32"), required=True
    )
    args = parser.parse_args(argv)
    if args.platform != sys.platform:
        parser.error("evidence platform must match the executing native platform")
    if args.wheel_dir is not None:
        wheels = tuple(args.wheel_dir.resolve(strict=True).glob("loushang-*.whl"))
        if len(wheels) != 1:
            parser.error("wheel directory must contain exactly one Loushang wheel")
        wheel = wheels[0]
    else:
        wheel = args.wheel.resolve(strict=True)
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error("an existing built wheel is required")
    _verify_wheel_source(wheel)
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv is required")
    with wheel.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() not in {"pythonpath", "pythonhome", "virtual_env"}
    }
    environment["PYTHONNOUSERSITE"] = "1"
    environment["LOUSHANG_REQUIRED_TERMINAL_BACKEND"] = (
        "conpty" if os.name == "nt" else "posix-pty"
    )
    cache = _ROOT / ".uv-cache"
    cache.mkdir(exist_ok=True)
    report = Path(f".artifacts/g16-wheel-{sys.platform}.xml")
    artifacts = (_ROOT / report).parent
    artifacts.mkdir(exist_ok=True)
    # Keep private work beside, never inside, uv's managed cache. This avoids
    # /tmp quota pressure without reusing the editable developer environment.
    with tempfile.TemporaryDirectory(
        prefix="g16-installed-", dir=artifacts
    ) as temporary:
        root = Path(temporary)
        target = root / "venv"
        _run(
            [
                uv,
                "--cache-dir",
                str(cache),
                "venv",
                "--offline",
                "--python",
                sys.executable,
                str(target),
            ],
            cwd=root,
            environment=environment,
            timeout=60,
        )
        executable = target / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        _run(
            [
                uv,
                "--cache-dir",
                str(cache),
                "pip",
                "install",
                "--offline",
                "--link-mode=hardlink",
                "--python",
                str(executable),
                "loushang @ " + wheel.as_uri() + "#sha256=" + digest,
                "pytest>=8,<9",
            ],
            cwd=root,
            environment=environment,
            timeout=180,
        )
        _run(
            [str(executable), "-I", "-c", _PROBE, digest, str(wheel)],
            cwd=root,
            environment=environment,
            timeout=60,
        )
        _run(
            [
                str(executable),
                "-I",
                "-m",
                "pytest",
                "-c",
                str(_ROOT / "pyproject.toml"),
                "-o",
                f"pythonpath={_ROOT}",
                "--import-mode=importlib",
                str(_ROOT / "tests/coding/test_mux_installed_evidence.py"),
                f"--basetemp={root / 'test-temp'}",
                f"--junitxml={_ROOT / report}",
                "-q",
                "-m",
                "not live",
            ],
            cwd=root,
            environment=environment,
            timeout=600,
        )
        _run(
            [
                str(executable),
                "-I",
                str(_ROOT / "scripts/dev/verify_evidence_manifest.py"),
                _MANIFEST,
                f"G16-WHEEL-{sys.platform.upper()}",
                report.as_posix(),
            ],
            cwd=_ROOT,
            environment=environment,
            timeout=30,
        )
    print(
        f"G16 installed evidence passed: platform={sys.platform}, wheel-sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
