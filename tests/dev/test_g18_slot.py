from __future__ import annotations

import errno
import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/_g18_slot.py"
SPEC = importlib.util.spec_from_file_location("g18_slot", SCRIPT)
slots = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(slots)


def slot(tmp_path):
    if sys.platform != "linux":
        pytest.skip("Linux installation slot; not external-platform acceptance")
    return slots.InstallationSlot(tmp_path)


def provision(subject, side):
    def install(prefix):
        prefix.mkdir()
        (prefix / "marker").write_text(side)
        (prefix / "launcher").write_text(f"#!{prefix}/bin/python\n")
        (prefix / "__pycache__").mkdir()
        (prefix / "__pycache__/owned.pyc").write_bytes(side.encode())
        return prefix

    assert subject.provision(side, install) == subject.prefix


def test_fixed_prefix_and_variant_bytecode_survive_a_b_a_without_copy(tmp_path):
    subject = slot(tmp_path)
    for side in ("a", "b"):
        provision(subject, side)
    identities = subject.receipt["identities"]
    assert not subject.prefix.exists()
    for side in ("a", "b", "a"):

        def operation(prefix, *, side=side):
            assert prefix == subject.prefix and prefix.resolve() == prefix
            assert list(slots._identity(prefix)) == identities[side]
            assert (prefix / "marker").read_text() == side
            assert (prefix / "launcher").read_text() == f"#!{prefix}/bin/python\n"
            assert (prefix / "__pycache__/owned.pyc").read_bytes() == side.encode()
            assert not (subject.root / side).exists()
            return side

        assert subject.run(side, operation) == side
    assert subject.receipt["identities"] == identities


@pytest.mark.parametrize("during", ["provision", "run"])
def test_busy_guard_covers_installer_verification_and_measured_owner(tmp_path, during):
    subject = slot(tmp_path)
    if during == "run":
        for side in ("a", "b"):
            provision(subject, side)

    def operation(prefix):
        before = subject.receipt
        with pytest.raises(RuntimeError, match="pending"):
            subject.run("b", lambda _: pytest.fail("no overlapping owner"))
        with pytest.raises(RuntimeError, match="pending"):
            subject.provision("b", lambda _: pytest.fail("no overlapping installer"))
        assert subject.receipt == before
        if during == "provision":
            prefix.mkdir()

    getattr(subject, during)("a", operation)


@pytest.mark.parametrize("during", ["provision", "run"])
def test_failed_installer_or_execution_preserves_location_and_poison(tmp_path, during):
    subject = slot(tmp_path)
    if during == "run":
        for side in ("a", "b"):
            provision(subject, side)

    def operation(prefix):
        prefix.mkdir(exist_ok=True)
        (prefix / "failure").write_text("retained owned-process evidence")
        raise RuntimeError("owner failure")

    with pytest.raises(RuntimeError, match="owner failure"):
        getattr(subject, during)("a", operation)
    assert (subject.prefix / "failure").is_file()
    assert subject.receipt["failed"] is True
    for action in (subject.run, subject.provision):
        with pytest.raises(RuntimeError, match="failed"):
            action("b", lambda _: pytest.fail("must not execute"))


@pytest.mark.parametrize("target", ["active", "parked", "unexpected"])
def test_replaced_directory_identity_or_unknown_destination_is_rejected(
    tmp_path, target
):
    subject = slot(tmp_path)
    for side in ("a", "b"):
        provision(subject, side)
    subject.run("a", lambda _: None)
    path = subject.prefix if target == "active" else subject.root / "b"
    if target == "unexpected":
        (subject.root / "a").mkdir()
    else:
        path.rename(subject.root / "retained-original")
        path.mkdir()
    with pytest.raises(ValueError):
        subject.run("b", lambda _: pytest.fail("wrong identity must not execute"))
    assert subject.receipt["failed"]


def test_second_rename_failure_retains_both_parked_variants_without_fallback(
    tmp_path, monkeypatch
):
    subject = slot(tmp_path)
    for side in ("a", "b"):
        provision(subject, side)
    subject.run("a", lambda _: None)
    rename = os.rename

    def fail(source, destination):
        if source == subject.root / "b":
            raise OSError(errno.EXDEV, "simulated cross-device refusal")
        rename(source, destination)

    monkeypatch.setattr(os, "rename", fail)
    with pytest.raises(OSError):
        subject.run("b", lambda _: pytest.fail("incomplete activation"))
    assert not subject.prefix.exists()
    assert subject.receipt["active"] is None and subject.receipt["failed"]
    assert all(
        (subject.root / side / "marker").read_text() == side for side in ("a", "b")
    )


@pytest.mark.parametrize("system", ["Darwin", "Windows"])
def test_platform_guard_precedes_directory_creation(tmp_path, monkeypatch, system):
    monkeypatch.setattr(slots.platform, "system", lambda: system)
    with pytest.raises(ValueError, match="Linux installation slot only"):
        slots.InstallationSlot(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_interrupt_after_effective_rename_never_restarts_from_stale_receipt(
    tmp_path, monkeypatch
):
    subject = slot(tmp_path)
    for side in ("a", "b"):
        provision(subject, side)
    subject.run("a", lambda _: None)
    rename = os.rename

    def interrupted(source, destination):
        rename(source, destination)
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "rename", interrupted)
    with pytest.raises(KeyboardInterrupt):
        subject.run("b", lambda _: pytest.fail("interrupted activation"))
    assert not subject.prefix.exists()
    assert all((subject.root / side).is_dir() for side in ("a", "b"))
    assert subject.receipt["failed"]
    with pytest.raises(RuntimeError):
        subject.run(
            "a", lambda _: pytest.fail("no restart from stale last-known active")
        )
