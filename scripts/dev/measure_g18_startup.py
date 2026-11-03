"""Linux-only, record-only installed import/help A/A or A/B (not ready or a gate).

No product imports in this parent. Build/install before invoking; all children
use fresh private app state, paired order, and installation-private bytecode.
Only the fixed read-only cases below are supported, not arbitrary host commands.
Exit zero means collection completed, not that the comparison verdict passed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import math
import os
import platform
import selectors
import stat
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "import-harness": ("import", "loushang.harness"),
    "import-coding": ("import", "loushang.coding"),
    "import-cli": ("import", "loushang.coding.cli.__main__"),
    "cli-help": ("loushang", "--help"),
    "cli-version": ("loushang", "--version"),
    "tui-help": ("loushang-tui", "--help"),
    "hosted-help": ("loushang-hosted", "--help"),
    "hosted-tui-help": ("loushang-hosted-tui", "--help"),
    "mux-help": ("loushang-mux", "--help"),
    "plugin-help": ("loushang-plugin", "--help"),
}
LIMIT = 256 * 1024


def verify_console_wrappers(package, prefix: Path) -> dict:
    """Bind uv-generated Linux wrappers to RECORD, this venv and wheel targets.

    Deliberately reject unknown installer templates rather than timing a wrapper
    whose execution contract we have not checked. This is not a general launcher.
    """
    import base64
    import hashlib
    import os
    from pathlib import Path

    files = {str(item): item for item in package.files or ()}
    wrappers = {}
    for entry in package.entry_points:
        if entry.group != "console_scripts":
            continue
        if Path(entry.name).name != entry.name:
            raise ValueError("invalid console entry name")
        path = prefix / "bin" / entry.name
        if (
            path.is_symlink()
            or (prefix / "bin").is_symlink()
            or not path.resolve().is_relative_to(prefix.resolve())
        ):
            raise ValueError("console wrapper escapes installation")
        record = next(
            (
                item
                for item in files.values()
                if Path(package.locate_file(item)).absolute() == path.absolute()
                or Path(package.locate_file(item)).resolve() == path.resolve()
            ),
            None,
        )
        if record is None or record.hash is None or record.hash.mode != "sha256":
            raise ValueError("console wrapper missing SHA256 RECORD")
        content = path.read_bytes()
        digest = hashlib.sha256(content).digest()
        if record.size != len(content) or record.hash.value != base64.urlsafe_b64encode(
            digest
        ).decode().rstrip("="):
            raise ValueError("console wrapper differs from RECORD")
        module, function = entry.value.split(":")
        expected = (
            f"#!{prefix / 'bin/python'}\n"
            "# -*- coding: utf-8 -*-\n"
            "import sys\n"
            f"from {module} import {function}\n"
            'if __name__ == "__main__":\n'
            '    if sys.argv[0].endswith("-script.pyw"):\n'
            "        sys.argv[0] = sys.argv[0][:-11]\n"
            '    elif sys.argv[0].endswith(".exe"):\n'
            "        sys.argv[0] = sys.argv[0][:-4]\n"
            f"    sys.exit({function}())\n"
        ).encode()
        if content != expected or not os.access(path, os.X_OK):
            raise ValueError("unsupported console wrapper interpreter or target")
        wrappers[entry.name] = {"sha256": digest.hex(), "target": entry.value}
    return wrappers


PROBE = (
    "from pathlib import Path\n"
    + inspect.getsource(verify_console_wrappers)
    + r"""
import hashlib, io, json, sys, zipfile
from importlib.metadata import distribution, distributions
from pathlib import Path
prefix, wheel = Path(sys.argv[1]), Path(sys.argv[2])
assert Path(sys.prefix) == prefix
assert Path(sys.executable).resolve() == (prefix/'bin/python').resolve()
package = distribution('loushang')
direct = json.loads(package.read_text('direct_url.json'))
assert 'archive_info' in direct and direct['url'] == wheel.as_uri()
wheel_bytes = wheel.read_bytes()
with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
    for name in archive.namelist():
        if name.startswith('loushang/') and not name.endswith('/'):
            installed = Path(package.locate_file(name)).resolve()
            assert installed.is_relative_to(prefix)
            assert installed.read_bytes() == archive.read(name)
    entry_file = next(name for name in archive.namelist()
                      if name.endswith('.dist-info/entry_points.txt'))
    assert package.read_text('entry_points.txt').encode() == archive.read(entry_file)
entries = {e.name: e.value for e in package.entry_points if e.group == 'console_scripts'}
print(json.dumps(dict(prefix=str(prefix), executable=sys.executable, python=sys.version,
    wheel_sha256=hashlib.sha256(wheel_bytes).hexdigest(), entries=entries,
    wrappers=verify_console_wrappers(package, prefix),
    dependencies=sorted((d.metadata['Name'],d.version) for d in distributions()))))
"""
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint_tree(root: Path) -> dict[str, str]:
    """Task-only input inventory, including empty directories but not atime."""
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError("controlled input root must be a real directory")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("non-regular controlled input")
        result[str(path.relative_to(root))] = (
            "directory" if path.is_dir() else digest(path)
        )
    return result


def private_environment(root: Path, prefix: Path, bytecode: Path) -> dict[str, str]:
    """Never mutate the parent environment; no inherited user/provider/Python data."""
    directories = {
        "HOME": "home",
        "USERPROFILE": "home",
        "LOUSHANG_HOME": "data",
        "LOUSHANG_RUNTIME_DIR": "runtime",
        "LOUSHANG_TMPDIR": "tmp",
        "TMPDIR": "tmp",
        "TMP": "tmp",
        "TEMP": "tmp",
        "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache",
        "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state",
        "XDG_RUNTIME_DIR": "runtime",
    }
    environment = {
        "PATH": f"{prefix / 'bin'}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TERM": "dumb",
        "COLUMNS": "80",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": str(bytecode),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    for name, directory in directories.items():
        path = root / directory
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        environment[name] = str(path)
    return environment


def _capture_in_observer(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float
) -> dict:
    """Measure only spawn-to-exit inside the retained Linux sample observer.

    The supervisor owns all descendants, including independent groups adopted by
    the observer. Any required descendant cleanup invalidates the whole sample.
    """
    import resource  # Linux-only collector; keep imports safe on other test platforms.

    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    child = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    output = {"stdout": bytearray(), "stderr": bytearray()}
    reason = None
    observed_exit = False
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", child.stdout), ("stderr", child.stderr)):
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = timeout - (time.perf_counter() - started)
                if remaining <= 0:
                    reason = "timeout"
                    break
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif sum(map(len, output.values())) + len(chunk) > LIMIT:
                        reason = "output_limit"
                        break
                    else:
                        output[key.data].extend(chunk)
                if reason:
                    break
        if not reason:
            # waitid observes without reaping: cleanup can still use the reserved PGID.
            deadline = started + timeout
            while (
                os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                is None
            ):
                if time.perf_counter() >= deadline:
                    reason = "timeout"
                    break
                time.sleep(0.001)
            observed_exit = reason is None
        elapsed = time.perf_counter() - started
    except BaseException as error:
        # Preserve partial output; the outer owner still settles live work.
        reason = f"{type(error).__name__}: {error}"
        elapsed = time.perf_counter() - started
    finally:
        # Only reap a normally observed root. Timeout/error leaves the live root
        # and every descendant to the existing retained owner, not a second
        # best-effort killer here. Its cleanup verdict invalidates the sample.
        if observed_exit:
            child.wait(timeout=10)
        child.stdout.close()
        child.stderr.close()
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "elapsed_seconds": elapsed,
        "child_user_seconds": usage_after.ru_utime - usage_before.ru_utime,
        "child_system_seconds": usage_after.ru_stime - usage_before.ru_stime,
        "exit_code": child.returncode,
        "failure": reason,
        **{k: bytes(v).decode("utf-8", "replace") for k, v in output.items()},
    }


def _observe_inert(request: Path, receipt: Path) -> None:
    # This runs ONLY inside _evidence_process's retained, start-gated Python
    # wrapper. Subreaping before the first measured Popen closes the root-exits-
    # before-tree-scan race; the existing supervisor owns cleanup and release.
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER, Linux only.
        raise OSError(ctypes.get_errno(), "cannot admit G18 sample observer")
    values = json.loads(request.read_text())
    result = _capture_in_observer(
        values["argv"],
        cwd=Path(values["cwd"]),
        env=values["env"],
        timeout=values["timeout"],
    )
    write_report(receipt, result)


def capture(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> dict:
    """Return a sample only after the existing owner proves physical settlement.

    Observer/site/receipt/reaper work is outside the measured spawn-to-exit wall
    and child CPU interval. No Product imports run in this parent or observer.
    """
    spec = importlib.util.spec_from_file_location(
        "g18_evidence_process", Path(__file__).with_name("_evidence_process.py")
    )
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    with tempfile.TemporaryDirectory(prefix="g18-inert-", dir=cwd) as private:
        root = Path(private)
        request, receipt = root / "request.json", root / "sample.json"
        write_report(request, dict(argv=argv, cwd=str(cwd), env=env, timeout=timeout))
        failed_cleanup = False
        try:
            owner.run_python(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "--_observe-inert",
                    str(request),
                    str(receipt),
                ],
                cwd=root,
                environment=env,
                timeout=timeout + 15,
            )
        except subprocess.CalledProcessError:
            # run_python raises only AFTER physical cleanup; a valid-looking
            # inner receipt cannot overrule its failed settlement verdict.
            if not receipt.is_file():
                raise
            failed_cleanup = True
        result = json.loads(receipt.read_text())
        if failed_cleanup:
            result["failure"] = result["failure"] or "observer_cleanup_required"
        return result


def output_matches(case: str, result: dict) -> bool:
    if result["failure"] or result["exit_code"] != 0 or result["stderr"]:
        return False
    output = result["stdout"]
    if case.startswith("import-"):
        return output == ""
    if case == "cli-version":
        return output.strip() == "0.1.0"
    if case in {"cli-help", "tui-help"}:
        return (
            "loushang" in output.lower() and "--help" in output and "--model" in output
        )
    return f"usage: {CASES[case][0]} " in output and "--help" in output


def summarize(values: list[float]) -> dict:
    ordered = sorted(values)
    median = statistics.median(values)
    return {
        "n": len(values),
        "median_seconds": median,
        "min_seconds": ordered[0],
        "max_seconds": ordered[-1],
        "p95_seconds": ordered[math.ceil(0.95 * len(values)) - 1],
        "mad_fraction": statistics.median(abs(x - median) for x in values) / median,
    }


def write_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def record_attempt(report: dict, path: Path, attempt: dict, operation) -> dict:
    """Publish identity before launch so a missing receipt cannot erase it."""
    sample = {**attempt, "status": "running", "valid": False}
    report["samples"].append(sample)
    write_report(path, report)
    try:
        sample.update(operation())
        sample["valid"] = output_matches(sample["case"], sample)
        sample["status"] = "complete" if sample["valid"] else "failed"
    except BaseException as error:
        sample.update(
            status="failed", valid=False, failure=f"{type(error).__name__}: {error}"
        )
        raise
    finally:
        sample["load_after"] = os.getloadavg()
        write_report(path, report)
    return sample


def verify_install(prefix: Path, wheel: Path, scratch: Path) -> dict:
    result = capture(
        [str(prefix / "bin/python"), "-I", "-c", PROBE, str(prefix), str(wheel)],
        cwd=scratch,
        env=private_environment(scratch, prefix, scratch / "pyc"),
        timeout=60,
    )
    if result["failure"] or result["exit_code"] or result["stderr"]:
        raise ValueError(f"invalid installation: {result}")
    return json.loads(result["stdout"])


def verify_pinned_install(prefix, wheel, scratch, expected_hash):
    if digest(wheel) != expected_hash:
        raise ValueError("wheel differs from source receipt before installation check")
    receipt = verify_install(prefix, wheel, scratch)
    if receipt["wheel_sha256"] != expected_hash or digest(wheel) != expected_hash:
        raise ValueError("wheel differs from source receipt during installation check")
    return receipt


def check_source_wheel(wheel: Path) -> None:
    # Reuse existing exact source/packaged-byte validation, without product imports.
    spec = importlib.util.spec_from_file_location(
        "g18_wheel_check", Path(__file__).with_name("run_g17_installed_evidence.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._verify_wheel_source(wheel)


def add_source_arguments(parser):
    parser.add_argument(
        "--wheel", type=Path, help="same wheel for both A/A installations"
    )
    parser.add_argument("--wheel-a", type=Path)
    parser.add_argument("--wheel-b", type=Path)
    parser.add_argument(
        "--source-a", default="HEAD", help="immutable source resolved before sampling"
    )
    parser.add_argument(
        "--source-b", default="HEAD", help="immutable source resolved before sampling"
    )


def provenance_module():
    spec = importlib.util.spec_from_file_location(
        "g18_provenance", Path(__file__).with_name("_g18_provenance.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def comparison_module():
    spec = importlib.util.spec_from_file_location(
        "g18_comparison", Path(__file__).with_name("_g18_comparison.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_pair(args, parser):
    if args.wheel is not None:
        if args.wheel_a is not None or args.wheel_b is not None:
            parser.error("use --wheel or both --wheel-a/--wheel-b")
        wheels = {side: args.wheel.resolve(strict=True) for side in ("a", "b")}
    elif args.wheel_a is not None and args.wheel_b is not None:
        wheels = {
            "a": args.wheel_a.resolve(strict=True),
            "b": args.wheel_b.resolve(strict=True),
        }
    else:
        parser.error("use --wheel or both --wheel-a/--wheel-b")
    provenance = provenance_module()
    provenance.require_clean_product(ROOT)
    sources = {
        side: provenance.verify_wheel_at_commit(ROOT, wheels[side], revision)
        for side, revision in (("a", args.source_a), ("b", args.source_b))
    }
    for field in ("lock_sha256", "project_sha256", "package_paths_sha256"):
        if sources["a"][field] != sources["b"][field]:
            raise ValueError(f"paired source contract differs: {field}")
    return wheels, sources


def existing_scratch_parent(value: str) -> Path:
    """Resolve an existing parent without creating or changing user directories."""
    try:
        parent = Path(value).resolve(strict=True)
        if not parent.is_dir():
            raise ValueError("not a directory")
    except (OSError, RuntimeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            f"scratch parent must be an existing directory: {value}"
        ) from error
    return parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-a", type=Path, required=True)
    parser.add_argument("--install-b", type=Path, required=True)
    add_source_arguments(parser)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scratch-parent",
        type=existing_scratch_parent,
        default=Path("/tmp"),
        help="existing parent for fresh task-owned temporary directories (default: /tmp)",
    )
    parser.add_argument("--pairs-per-block", type=int, default=10)
    parser.add_argument("--blocks", type=int, default=2)
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("only native Linux collection is implemented")
    if args.pairs_per_block < 1 or args.blocks < 1:
        parser.error("positive blocks and pairs required")
    prefixes = {
        k: p.absolute() for k, p in (("a", args.install_a), ("b", args.install_b))
    }
    if prefixes["a"].resolve() == prefixes["b"].resolve():
        parser.error("independent installations required")
    wheels, sources = source_pair(args, parser)
    mode = (
        "aa" if sources["a"]["wheel_sha256"] == sources["b"]["wheel_sha256"] else "ab"
    )
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    scratch = Path(
        tempfile.mkdtemp(prefix="loushang-g18-baseline-", dir=args.scratch_parent)
    )
    report = {
        "schema_version": 2,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "comparison": {"verdict": "not-evaluated", "reason": "collection incomplete"},
        "scope": f"linux-installed-inert-startup-{mode}",
        "source_receipts": sources,
        "helpers_before": provenance_module().helper_manifest(ROOT),
        "provenance_support_sha256": digest(
            Path(__file__).with_name("_g18_provenance.py")
        ),
        "source_commit": sources["b"]["commit"],
        "product_tree_clean": True,
        "lock_sha256": sources["b"]["lock_sha256"],
        "runner_sha256": digest(Path(__file__)),
        "wheel_sha256": {
            side: source["wheel_sha256"] for side, source in sources.items()
        },
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "load_before": os.getloadavg(),
        "scratch": str(scratch),
        "scratch_parent": str(args.scratch_parent),
        "scratch_device": scratch.stat().st_dev,
        "cases": CASES,
        "blocks": args.blocks,
        "pairs_per_block": args.pairs_per_block,
        "condition": "fresh process; private warm bytecode; empty per-sample app state; non-TTY; OS page cache uncontrolled",
        "samples": [],
        "summary": {},
        "installations": {},
    }
    path = output / "report.json"
    write_report(path, report)
    try:
        for side, prefix in prefixes.items():
            root = scratch / f"identity-{side}"
            root.mkdir()
            report["installations"][side] = verify_pinned_install(
                prefix, wheels[side], root, sources[side]["wheel_sha256"]
            )
        left, right = report["installations"].values()
        for key in ("python", "dependencies", "entries"):
            if left[key] != right[key]:
                raise ValueError(f"paired installation contract differs: {key}")
        if (
            not {v[0] for v in CASES.values() if v[0] != "import"}
            <= left["entries"].keys()
        ):
            raise ValueError("required installed entries missing")
        for block in range(args.blocks):
            # One explicit warmup per case/install/block. Never discarded retries.
            for pair in range(-1, args.pairs_per_block):
                order = ("a", "b") if (pair + block) % 2 == 0 else ("b", "a")
                names = list(CASES)
                if block % 2:
                    names.reverse()
                for case in names:
                    for side in order:
                        root = scratch / f"b{block}-p{pair}-{case}-{side}"
                        root.mkdir(mode=0o700)
                        prefix = prefixes[side]
                        pyc = output / f"bytecode-{side}"
                        environment = private_environment(root, prefix, pyc)
                        executable, argument = CASES[case]
                        if executable == "import":
                            command = [
                                str(prefix / "bin/python"),
                                "-I",
                                "-X",
                                f"pycache_prefix={pyc}",
                                "-c",
                                f"import {argument}",
                            ]
                        else:
                            command = [str(prefix / "bin" / executable), argument]
                        attempt = dict(
                            case=case,
                            block=block,
                            pair=pair,
                            side=side,
                            warmup=pair == -1,
                            argv=command,
                            cwd=str(root),
                        )
                        result = record_attempt(
                            report,
                            path,
                            attempt,
                            partial(
                                capture, command, cwd=root, env=environment, timeout=60
                            ),
                        )
                        if not result["valid"]:
                            raise ValueError(
                                f"case failed: {case}; partial evidence: {path}"
                            )
                print(
                    f"block {block + 1}/{args.blocks} pair {pair + 1}/{args.pairs_per_block}; load={os.getloadavg()[0]:.2f}",
                    flush=True,
                )
        for case in CASES:
            report["summary"][case] = {
                f"block-{block}-{side}": summarize(
                    [
                        s["elapsed_seconds"]
                        for s in report["samples"]
                        if s["case"] == case
                        and s["block"] == block
                        and s["side"] == side
                        and not s["warmup"]
                    ]
                )
                for block in range(args.blocks)
                for side in prefixes
            }
        if {side: digest(wheel) for side, wheel in wheels.items()} != report[
            "wheel_sha256"
        ]:
            raise ValueError("wheel changed during measurement")
        for side, prefix in prefixes.items():
            root = scratch / f"final-identity-{side}"
            root.mkdir()
            if (
                verify_pinned_install(
                    prefix, wheels[side], root, sources[side]["wheel_sha256"]
                )
                != report["installations"][side]
            ):
                raise ValueError("installation changed during measurement")
        report["helpers_after"] = provenance_module().helper_manifest(ROOT)
        if report["helpers_after"] != report["helpers_before"]:
            raise ValueError("trusted helper inputs changed during measurement")
        if args.blocks >= 2 and args.blocks * args.pairs_per_block >= 20:
            comparison = comparison_module()
            results = {
                case: comparison.compare_case(
                    report["samples"],
                    case=case,
                    phase=mode,
                    blocks=args.blocks,
                    pairs_per_block=args.pairs_per_block,
                )
                for case in CASES
            }
            verdicts = {result["verdict"] for result in results.values()}
            report["comparison"] = dict(
                phase=mode,
                cases=results,
                verdict=next(
                    verdict
                    for verdict in (
                        "regression",
                        "inconclusive",
                        "target-not-met",
                        "pass",
                    )
                    if verdict in verdicts
                ),
            )
        else:
            report["comparison"]["reason"] = (
                "declared preflight lacks two blocks and twenty pairs"
            )
        report["status"] = "complete-record-only"
    except BaseException as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["load_after"] = os.getloadavg()
        write_report(path, report)
        print(f"evidence: {path}; task-owned scratch retained: {scratch}", flush=True)
        print(f"advisory comparison: {report['comparison']['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--_observe-inert":
        _observe_inert(Path(sys.argv[2]), Path(sys.argv[3]))
        raise SystemExit(0)
    raise SystemExit(main())
