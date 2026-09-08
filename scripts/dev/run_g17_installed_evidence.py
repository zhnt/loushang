#!/usr/bin/env python3
"""Run the exact G17 native terminal contract from an isolated local wheel."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from contextlib import contextmanager, suppress
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = "docs/internals/architecture/apphost/hosted-session-workflow-g17-evidence-manifest.json"
_SMOKE_NAMES = {
    "test_G17_TERMINAL_LOCAL_discovery_picker_detach_reattach_and_stop",
    "test_G17_TERMINAL_LEGACY_local_picker_unavailable_keeps_existing_commands",
    "test_G17_TERMINAL_PRODUCT_discovery_profile_keeps_turn_approval_and_interrupt",
    "test_G17_TERMINAL_PICKER_resumes_canonical_history_and_recovers_on_relaunch[cwd]",
    "test_G17_TERMINAL_PICKER_resumes_canonical_history_and_recovers_on_relaunch[user_home]",
}


def _verify_smoke(report: Path) -> None:
    suites = ET.parse(report).getroot().findall("testsuite")
    cases = [case for suite in suites for case in suite.findall("testcase")]
    if len(cases) != len(_SMOKE_NAMES):
        raise ValueError("G17 smoke needs exactly five selected cases")
    if {case.get("name") for case in cases} != _SMOKE_NAMES:
        raise ValueError("G17 smoke case names differ")
    if any(case.find(tag) is not None for case in cases for tag in (
        "skipped", "failure", "error"
    )):
        raise ValueError("G17 smoke cannot skip or fail")


_PROBE = """
import hashlib, importlib, json, sys, zipfile
from importlib.metadata import distribution
from pathlib import Path
from urllib.parse import urldefrag
prefix = Path(sys.prefix).resolve()
names = ('loushang.coding.cli.hosted_client', 'loushang.apphost.launcher',
         'loushang.coding.cli.mux', 'loushang.harnesstui.mux.shell',
         'loushang.appserver.local', 'loushang.appservice.client_scope',
         'loushang.apphost.local', 'loushang.tui.ui_parts.text_pager')
assert all(Path(importlib.import_module(name).__file__).resolve().is_relative_to(prefix)
           for name in names), 'G17 import escaped isolated installation'
package = distribution('loushang')
direct = json.loads(package.read_text('direct_url.json') or '{}')
wheel = Path(sys.argv[2]).resolve(strict=True)
assert 'archive_info' in direct and urldefrag(direct.get('url', '')).url == wheel.as_uri(), 'G17 installation is not the selected wheel'
with wheel.open('rb') as artifact:
    assert hashlib.file_digest(artifact, 'sha256').hexdigest() == sys.argv[1], 'G17 wheel changed during installation'
# Installers need not retain an archive hash in direct_url.json. Compare the
# actual installed package bytes with the hashed wheel, not installer metadata.
with zipfile.ZipFile(wheel) as artifact:
    names = [name for name in artifact.namelist() if name.startswith('loushang/') and not name.endswith('/')]
    assert names, 'G17 wheel contains no package files'
    for name in names:
        installed = Path(package.locate_file(name)).resolve(strict=True)
        assert installed.is_relative_to(prefix), 'G17 package file escaped installation'
        assert installed.read_bytes() == artifact.read(name), 'G17 installed bytes differ from wheel'
print('G17 isolated wheel origins, digest and installed bytes verified', flush=True)
"""


def _run(
    argv: list[str], *, cwd: Path, environment: dict[str, str], timeout: int
) -> None:
    if argv[1:4] == ["-I", "-m", "pytest"]:
        path = Path(__file__).with_name("_evidence_process.py")
        spec = importlib.util.spec_from_file_location("_evidence_process", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("evidence supervisor missing")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.run_pytest(argv, cwd=cwd, environment=environment, timeout=timeout)
        return
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
            raise ValueError("G17 wheel modules differ from current source")
        for name in names:
            path = (source / name).resolve()
            if (
                not path.is_relative_to(source)
                or not path.is_file()
                or path.read_bytes() != archive.read(name)
            ):
                raise ValueError("G17 wheel package bytes differ from current source")
    print("G17 wheel/source package modules and bytes verified", flush=True)


@contextmanager
def _workspace(artifacts):
    root = Path(tempfile.mkdtemp(prefix="g17-installed-", dir=artifacts))
    try:
        yield root
    except BaseException:
        # Supervised tests have settled before returning here. Retain failed
        # state for diagnosis instead of erasing a cold-start failure's inputs.
        with suppress(OSError, ValueError):
            print(f"G17 failed installation retained: {root}", file=sys.stderr, flush=True)
        raise
    else:
        _remove_workspace(root)


def _remove_workspace(root):
    metadata = root.lstat()
    if (
        not root.name.startswith("g17-installed-")
        or not stat.S_ISDIR(metadata.st_mode)
        or getattr(metadata, "st_reparse_tag", 0)
    ):
        raise ValueError("not an allocated G17 installation directory")

    def retry(function, raw, error):
        path = Path(raw)
        if path != root and root not in path.parents:
            raise error[1]
        for candidate in (path.parent, path):
            if candidate != root and root not in candidate.parents:
                continue
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_reparse_tag", 0):
                continue
            if os.name == "posix" and metadata.st_uid != os.getuid():
                raise error[1]
            if stat.S_ISDIR(metadata.st_mode):
                candidate.chmod(metadata.st_mode | 0o700, follow_symlinks=os.name != "posix")
            elif os.name == "nt" and stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                # Windows readonly attributes can block unlink. Never change
                # metadata of a hardlinked wheel/cache file to make it removable.
                candidate.chmod(metadata.st_mode | 0o600)
        function(raw)

    shutil.rmtree(root, onerror=retry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wheel", type=Path)
    source.add_argument("--wheel-dir", type=Path)
    parser.add_argument(
        "--platform", choices=("linux", "darwin", "win32"), required=True
    )
    parser.add_argument("--smoke", action="store_true", help="run a separate partial preflight, never release acceptance")
    args = parser.parse_args(argv)
    if not args.smoke and not (_ROOT / "tests/coding/test_hosted_installed_evidence.py").is_file():
        parser.error("the complete G17 installed case selector is not implemented yet")
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
    report = Path(f".artifacts/g17-wheel-{'smoke-' if args.smoke else ''}{sys.platform}.xml")
    artifacts = (_ROOT / report).parent
    artifacts.mkdir(exist_ok=True)
    # Keep private work beside, never inside, uv's managed cache. This avoids
    # /tmp quota pressure without reusing the editable developer environment.
    with _workspace(artifacts) as root:
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
        # A locked sync caches artifacts, not necessarily registry index
        # responses. Reuse the lock rather than resolving dependencies offline
        # against index metadata that only a warm developer cache may contain.
        _run(
            [
                uv,
                "--cache-dir",
                str(cache),
                "sync",
                "--offline",
                "--locked",
                "--extra",
                "dev",
                "--no-install-project",
                "--no-editable",
                "--project",
                str(_ROOT),
                "--python",
                sys.executable,
                "--link-mode=hardlink",
            ],
            cwd=root,
            environment={**environment, "UV_PROJECT_ENVIRONMENT": str(target)},
            timeout=180,
        )
        _run(
            [
                uv,
                "--cache-dir",
                str(cache),
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--link-mode=hardlink",
                "--python",
                str(executable),
                "loushang @ " + wheel.as_uri() + "#sha256=" + digest,
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
                *(
                    [
                        str(_ROOT / "tests/coding/test_hosted_workflow_terminal.py"),
                        str(_ROOT / "tests/coding/test_hosted_client_terminal.py"),
                        "-k", "LOCAL or LEGACY or PICKER or PRODUCT",
                    ]
                    if args.smoke else
                    [str(_ROOT / "tests/coding/test_hosted_installed_evidence.py")]
                ),
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
        if args.smoke:
            _verify_smoke(_ROOT / report)
        else:
            _run(
                [
                    str(executable),
                    "-I",
                    str(_ROOT / "scripts/dev/verify_evidence_manifest.py"),
                    _MANIFEST,
                    f"G17-WHEEL-{sys.platform.upper()}",
                    report.as_posix(),
                ],
                cwd=_ROOT,
                environment=environment,
                timeout=30,
            )
    print(
        f"G17 {'partial smoke (NOT release acceptance)' if args.smoke else 'installed evidence'} "
        f"passed: platform={sys.platform}, wheel-sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
