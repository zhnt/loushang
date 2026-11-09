"""Original GC decode/repair results; observations do not grant Store authority."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

FIXTURE = Path(__file__).with_name("fixtures") / "gc_snapshot_load_v1.json"


def _load_case(case, path):
    module = importlib.import_module(case["module"])
    owner = getattr(module, case["owner"])(path)
    if case["method"] == "_load_claims_unlocked":
        path = owner.claim_path
    raw = case["raw_before"]
    if raw is not None:
        path.write_bytes(raw.encode("utf-8"))
    arguments = {}
    if case["read_only"]:
        arguments["load_policy"] = replace(
            owner._load_policy, partial_tail="raise", create_lock=False
        )
    try:
        records = getattr(owner, case["method"])(**arguments)
        result = {"status": "returned", "records": [item.to_dict() for item in records]}
    except Exception as error:
        chain = []
        current = error
        while current is not None:
            chain.append({
                "type": type(current).__module__ + "." + type(current).__qualname__,
                "message": str(current).replace(str(path), "<JOURNAL>"),
                "code": getattr(current, "code", None),
            })
            current = current.__cause__
        result = {"status": "raised", "chain": chain}
    return {**result, "raw_after": path.read_bytes().decode("utf-8") if path.exists() else None}


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text())["cases"], ids=lambda c: c["id"])
def test_original_gc_snapshot_result(case, tmp_path):
    assert _load_case(case, tmp_path / "history.jsonl") == case["expected"]


@pytest.mark.parametrize("route", json.loads(FIXTURE.read_text())["valid_routes"], ids=lambda c: c["id"])
def test_gc_snapshot_does_not_reopen_after_decode(route, tmp_path, monkeypatch):
    """The same committed snapshot must supply schema and duplicate diagnostics."""
    opened = []
    original = Path.open

    def observe(path, mode="r", *args, **kwargs):
        if path.parent == tmp_path and "r" in mode:
            opened.append(path)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe)
    result = _load_case(route, tmp_path / "history.jsonl")
    assert result == route["expected"]
    # _load_case's final read of file aftermath accounts for the other read.
    assert len(opened) == 2
