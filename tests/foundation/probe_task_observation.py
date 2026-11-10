"""Explicit frozen Task-observation comparisons; no default pytest route."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
from contextlib import suppress
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "task_observations_v1.json"
FROZEN = json.loads(FIXTURE.read_text())
POOL = FROZEN["pool"]


class FalseError(Exception):
    def __bool__(self):
        return False


class LoggedTask(asyncio.Task):
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.reject = False
        super().__init__(*args, **kwargs)

    def done(self):
        self.calls.append("done")
        return super().done()

    def cancelled(self):
        self.calls.append("cancelled")
        return super().cancelled()

    def exception(self):
        self.calls.append("exception")
        if self.reject:
            raise LookupError("exception observer rejected")
        return super().exception()


def _lookup(row):
    name = row["path"].removeprefix("src/").removesuffix(".py").replace("/", ".")
    module = importlib.import_module(name)
    root = Path(
        os.environ.get(
            "LOUSHANG_TASK_SOURCE_ROOT", str(Path(__file__).resolve().parents[2])
        )
    ).resolve()
    assert Path(module.__file__).resolve() == (root / row["path"]).resolve()
    owner = module
    if row["scope"]:
        owner = getattr(module, row["scope"])
        assert type(inspect.getattr_static(owner, row["name"])) is staticmethod
        assert getattr(object.__new__(owner), row["name"]) is getattr(
            owner, row["name"]
        )
    return getattr(owner, row["name"])


async def _observe(callback, case):
    error = FalseError("falsy") if case == "falsy_failure" else ValueError("failed")
    gate = asyncio.Event()

    async def operation():
        if case in {"pending", "cancelled"}:
            await gate.wait()
        if case in {"failure", "falsy_failure", "observer_raises"}:
            raise error
        return False if case == "false_result" else 7

    task = LoggedTask(operation())
    try:
        await asyncio.sleep(0)
        if case == "cancelled":
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        task.reject = case == "observer_raises"
        before = task._log_traceback
        task.calls.clear()
        try:
            result = callback(task=task)
            outcome = {"return_type": type(result).__name__, "return": result}
        except BaseException as caught:
            outcome = {"raised": type(caught).__name__, "message": str(caught)}
        outcome.update(
            calls=list(task.calls),
            unobserved_before=before,
            unobserved_after=task._log_traceback,
        )
        return outcome
    finally:
        task.reject = False
        if not asyncio.Task.done(task):
            task.cancel()
        with suppress(BaseException):
            await task


CASES = [
    "pending",
    "cancelled",
    "success",
    "false_result",
    "failure",
    "falsy_failure",
    "observer_raises",
]


@pytest.mark.parametrize(
    "row", POOL, ids=lambda row: row["path"] + ":" + (row["scope"] or "") + row["name"]
)
def test_frozen_original_task_observations(row):
    expected = FROZEN["observations"]
    callback = _lookup(row)

    async def scenario():
        actual = {case: await _observe(callback, case) for case in CASES}
        assert actual == expected[row["kind"]]

    asyncio.run(scenario())
