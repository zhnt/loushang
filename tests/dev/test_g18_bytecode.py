from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

DEV = Path(__file__).resolve().parents[2] / "scripts/dev"


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEV / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


slots = load("_g18_slot")
bytecode = load("_g18_bytecode")
inert = load("measure_g18_startup")
MODULE_CACHE = f"lib/__pycache__/module.{sys.implementation.cache_tag}.pyc"


def setup(tmp_path):
    if sys.platform != "linux":
        pytest.skip("Linux slot-bound cache policy")
    slot = slots.InstallationSlot(tmp_path)
    for side in ("a", "b"):

        def install(prefix, *, side=side):
            (prefix / "lib/__pycache__").mkdir(parents=True)
            (prefix / "bin").mkdir()
            (prefix / "bin/python").symlink_to(Path(sys._base_executable))
            (prefix / "bin/python3").symlink_to("python")
            (
                prefix / f"bin/python{sys.version_info.major}.{sys.version_info.minor}"
            ).symlink_to("python")
            (prefix / "lib64").symlink_to("lib")
            (prefix / MODULE_CACHE).write_bytes(side.encode())
            (prefix / "lib/module.py").write_text("preserve source")

        slot.provision(side, install)
    policy = bytecode.BytecodePolicy(slot, tmp_path)
    for side in ("a", "b"):
        (policy.external(side) / "stdlib.pyc").write_bytes(f"external {side}".encode())
    return slot, policy


def test_absent_clears_only_active_installed_and_matching_external_bytecode(tmp_path):
    slot, policy = setup(tmp_path)
    subject = tmp_path / "recovery-state"
    subject.mkdir()
    (subject / "seed.pyc").write_bytes(b"seed-preserved")
    (tmp_path / "base.pyc").write_bytes(b"base-interpreter-cache")
    parked = bytecode.inventory(slot.root / "b", installation=True)
    other = bytecode.inventory(policy.external("b"))

    def operation(prefix):
        receipt = policy.prepare("a", "absent")
        assert receipt["before"]["installed"] and receipt["before"]["external"]
        assert receipt["ready"] == {"installed": {}, "external": {}}
        assert (prefix / "lib/module.py").read_text() == "preserve source"
        assert (prefix / "bin/python").is_symlink()
        assert bytecode.inventory(slot.root / "b", installation=True) == parked
        assert bytecode.inventory(policy.external("b")) == other

    slot.run("a", operation)
    assert (subject / "seed.pyc").read_bytes() == b"seed-preserved"
    assert (tmp_path / "base.pyc").read_bytes() == b"base-interpreter-cache"


def test_warm_inspection_never_removes_bytes_and_next_absent_reclears_postverify_cache(
    tmp_path,
):
    slot, policy = setup(tmp_path)

    def warm(prefix):
        before = policy.inspect("a")
        receipt = policy.prepare("a", "warm")
        assert receipt["before"] == receipt["ready"] == before
        policy.prepare("a", "absent")
        # A source/postverification process may write site.pyc after the sample.
        (prefix / MODULE_CACHE).write_bytes(b"postverify")
        (policy.external("a") / "after.pyc").write_bytes(b"postverify")

    slot.run("a", warm)
    slot.run("b", lambda _: policy.prepare("b", "warm"))
    cleared = slot.run("a", lambda _: policy.prepare("a", "absent"))
    assert set(cleared["before"]["installed"]) == {MODULE_CACHE}
    assert set(cleared["before"]["external"]) == {"after.pyc"}
    assert not any(cleared["ready"].values())


@pytest.mark.parametrize(
    "fault",
    [
        "idle",
        "wrong-side",
        "external-symlink",
        "installed-symlink",
        "unknown-external-file",
        "external-replaced",
        "installed-replaced",
    ],
)
def test_unowned_or_unknown_cache_scope_is_rejected_before_deletion(tmp_path, fault):
    slot, policy = setup(tmp_path)
    marker = policy.external("a") / "stdlib.pyc"
    if fault == "idle":
        with pytest.raises(RuntimeError):
            policy.prepare("a", "absent")
    else:

        def operation(prefix):
            if fault == "external-symlink":
                (policy.external("a") / "escape").symlink_to(tmp_path)
            elif fault == "installed-symlink":
                (prefix / "lib/escape").symlink_to(tmp_path)
            elif fault == "unknown-external-file":
                (policy.external("a") / "receipt.json").write_text("must not delete")
            elif fault == "external-replaced":
                policy.external("a").rename(tmp_path / "retained-external")
                policy.external("a").mkdir()
            elif fault == "installed-replaced":
                prefix.rename(tmp_path / "retained-installation")
                prefix.mkdir()
            policy.prepare("b" if fault == "wrong-side" else "a", "absent")

        with pytest.raises((ValueError, RuntimeError)):
            slot.run("a", operation)
        assert slot.receipt["failed"]
    retained = (
        tmp_path / "retained-external/stdlib.pyc"
        if fault == "external-replaced"
        else marker
    )
    assert retained.read_bytes() == b"external a"


def test_failed_unlink_never_claims_absence_and_poison_stops_next_variant(
    tmp_path, monkeypatch
):
    slot, policy = setup(tmp_path)
    original = Path.unlink

    def fail(path, *args, **kwargs):
        if path.suffix == ".pyc":
            raise PermissionError("simulated cache removal refusal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(PermissionError):
        slot.run("a", lambda _: policy.prepare("a", "absent"))
    with pytest.raises(RuntimeError):
        slot.run("b", lambda _: pytest.fail("must not start next variant"))


def test_inventory_reports_portable_bytecode_without_touching_sources(tmp_path):
    (tmp_path / "source.py").write_text("source")
    (tmp_path / "source.pyc").write_bytes(b"compiled")
    assert set(bytecode.inventory(tmp_path, installation=True)) == {"source.pyc"}
    with pytest.raises(ValueError, match="foreign"):
        bytecode.inventory(tmp_path)


@pytest.mark.parametrize("layout", ["legacy", "orphan-cache", "symlink-source"])
def test_sourceless_installed_bytecode_is_code_not_a_removable_cache(
    tmp_path, monkeypatch, layout
):
    import py_compile

    slot, policy = setup(tmp_path)
    removed = []
    original_unlink = Path.unlink

    def operation(prefix):
        source = prefix / "lib/only.py"
        source.write_text("value = 7\n")
        compiled = prefix / (
            f"lib/__pycache__/only.{sys.implementation.cache_tag}.pyc"
            if layout == "orphan-cache"
            else "lib/only.pyc"
        )
        py_compile.compile(str(source), cfile=str(compiled), doraise=True)
        source.unlink()
        if layout == "symlink-source":
            external = tmp_path / "external.py"
            external.write_text("value = 7\n")
            source.symlink_to(external)

        def observe(path, *args, **kwargs):
            removed.append(path)
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", observe)
        policy.prepare("a", "absent")

    with pytest.raises(ValueError):
        slot.run("a", operation)
    assert removed == []  # Reject the inventory before deleting any valid cache.
    assert (policy.external("a") / "stdlib.pyc").read_bytes() == b"external a"
    assert slot.receipt["failed"]


def test_real_isolated_python_uses_cleared_adjacent_not_external_cache(tmp_path):
    if sys.platform != "linux":
        pytest.skip("Linux retained Python/slot cache witness")
    import shutil

    uv = shutil.which("uv")
    assert uv is not None
    slot = slots.InstallationSlot(tmp_path)
    control = tmp_path / "control"
    control.mkdir()
    environment = inert.private_environment(
        control / "environment", Path(sys.prefix), control / "pyc"
    )
    for side in ("a", "b"):

        def install(prefix):
            result = inert.capture(
                [
                    uv,
                    "--no-config",
                    "--offline",
                    "venv",
                    "--python",
                    sys.executable,
                    str(prefix),
                ],
                cwd=control,
                env=environment,
                timeout=30,
            )
            assert result["exit_code"] == 0 and result["failure"] is None, result
            site = (
                prefix
                / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
            )
            (site / "g18_cache_witness.py").write_text("value = 42\n")

        slot.provision(side, install)
    policy = bytecode.BytecodePolicy(slot, tmp_path)

    def operation(prefix):
        env = {**environment, "PYTHONPYCACHEPREFIX": str(policy.external("a"))}
        argv = [
            str(prefix / "bin/python"),
            "-I",
            "-c",
            "import g18_cache_witness; assert g18_cache_witness.value == 42",
        ]
        for _ in range(2):
            ready = policy.prepare("a", "absent")
            assert not any(ready["ready"].values())
            # There is deliberately no Python-based verification here.
            result = inert.capture(argv, cwd=control, env=env, timeout=30)
            assert result["exit_code"] == 0 and result["failure"] is None, result
            after = policy.inspect("a")
            assert any("g18_cache_witness" in name for name in after["installed"])
            assert after["external"] == {}  # -I ignores PYTHONPYCACHEPREFIX.

    slot.run("a", operation)
