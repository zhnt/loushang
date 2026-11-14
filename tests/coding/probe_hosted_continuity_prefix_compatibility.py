"""Explicit original G13 prefix observations; controlled ports, no native IO.

The 22 expected records were captured from the original Coding implementation;
this carrier only reads its lossless fixture. Original baseline: 9719df2ef.
Captured Coding prefix SHA256:
ddc819b94abdf17e3a69005499c556a1c0612b1c43c496bec6fef5c7292187ec.
The actual Code request instance
uses controlled foreground values populated without __post_init__, so request
validation and native storage/Kernel effects are outside these model cases.
The additional cached-open case reuses the existing real AppHost test composition.
Source/compiled-code provenance and capture history remain external evidence.
"""

import asyncio
import gzip
import inspect
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

import loushang.apphost.integrations._continuity_preparation as _continuity_owner
import loushang.coding.hosted_continuity as _coding_owner
from loushang.coding.workspace_catalog import CodingWorkspaceCatalog
from tests.apphost.test_continuity import _attempt, _Lease, _record

CASES = (
    "slots",
    "success",
    "load-failure",
    "acquire-locked",
    "acquire-corrupt",
    "acquire-base",
    "admit-failure",
    "runtime-constructor-failure",
    "resolver-failure",
    "child-request-failure",
    "child-factory-failure",
    "child-open-cleanup",
    "open-retry",
    "early-close",
    "factory-close-retry",
    "runtime-close-retry",
    "lease-close-retry",
    "concurrent-open",
    "close-open-reject-retry",
    "caller-cancel-open",
    "caller-cancel-close",
    "child-close-retry",
)
FIXTURE = Path(__file__).with_name("fixtures") / "hosted_continuity_prefix_v1.json.gz"


MOVED_NAMES = {
    "AppHostCatalogV1",
    "AppHostRuntimeV1",
    "HostedApplicationContinuityRequestV1",
    "create_hosted_application_continuity_attempt",
    "ApplicationContinuityError",
    "ApplicationContinuityErrorCodeV1",
}


class EffectOwnerProxy:
    """Retarget original test effect ports; undo restores the actual owners."""

    def __init__(self, coding, continuity):
        object.__setattr__(self, "_coding", coding)
        object.__setattr__(self, "_continuity", continuity)

    def owner(self, name):
        key = "_continuity" if name in MOVED_NAMES else "_coding"
        return object.__getattribute__(self, key)

    def __getattr__(self, name):
        return getattr(self.owner(name), name)

    def __setattr__(self, name, value):
        setattr(self.owner(name), name, value)

    def __delattr__(self, name):
        delattr(self.owner(name), name)


code = EffectOwnerProxy(_coding_owner, _continuity_owner)


def error_data(error, injected, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "args": list(error.args),
        "message": str(error),
        "code": getattr(error, "code", None),
        "injected_identity": next((k for k, e in injected.items() if error is e), None),
        "notes": list(getattr(error, "__notes__", ())),
        "suppress_context": error.__suppress_context__,
        "cause": error_data(error.__cause__, injected, seen),
        "context": error_data(error.__context__, injected, seen),
    }


async def observe(case, monkeypatch):
    trace, injected, faults = [], {}, {}
    open_entered, open_release = asyncio.Event(), asyncio.Event()
    shutdown_entered, shutdown_release = asyncio.Event(), asyncio.Event()
    block_open = case in {
        "concurrent-open",
        "close-open-reject-retry",
        "caller-cancel-open",
        "caller-cancel-close",
    }
    block_shutdown = case == "caller-cancel-close"
    child_open_count = 0
    shutdown_count = 0

    def event(name, *values):
        trace.append([name, *values])
        errors = faults.get(name, [])
        if errors:
            raise errors.pop(0)

    def fault(stage, kind=OSError):
        error = kind(stage)
        error.add_note("original-controlled")
        injected[stage] = error
        faults[stage] = [error]

    if case == "load-failure":
        fault("load")
    if case in {"admit-failure", "factory-close-retry", "lease-close-retry"}:
        fault("admit")
    if case == "runtime-constructor-failure":
        fault("runtime.construct")
    if case in {"resolver-failure", "runtime-close-retry"}:
        fault("resolver.construct")
    if case == "child-request-failure":
        fault("child.request")
    if case == "child-factory-failure":
        fault("child.construct")
    if case in {"child-open-cleanup", "open-retry", "child-close-retry"}:
        fault("child.open")
    if case == "factory-close-retry":
        fault("factory.close", KeyboardInterrupt)
    if case == "runtime-close-retry":
        fault("runtime.close", asyncio.CancelledError)
    if case == "lease-close-retry":
        fault("lease.close", KeyboardInterrupt)
    if case == "child-close-retry":
        fault("child.close", asyncio.CancelledError)

    class Lease:
        async def close(self):
            event("lease.close")

    lease = Lease()

    class Store:
        async def acquire(self, **kwargs):
            event(
                "acquire", list(kwargs), kwargs["application_id"], kwargs["owner_epoch"]
            )
            if case in {"acquire-locked", "acquire-corrupt"}:
                tag = "LOCKED" if case == "acquire-locked" else "CORRUPT"
                error = code.ApplicationContinuityError(
                    getattr(code.ApplicationContinuityErrorCodeV1, tag)
                )
                error.add_note("original-store")
                injected["acquire"] = error
                raise error
            if case == "acquire-base":
                error = KeyboardInterrupt("acquire")
                injected["acquire"] = error
                raise error
            return lease

    class Factory:
        def __init__(self, session_factory, *, session_owner):
            event(
                "factory.construct",
                session_factory == "session-factory",
                session_owner == "session-owner",
            )

        async def close(self):
            event("factory.close")

    class Catalog:
        @classmethod
        async def admit(cls, value):
            event(
                "admit", value.generation_id, len(value.products), len(value.profiles)
            )
            return catalog

        async def close(self):
            event("catalog.close")

    catalog = Catalog()

    class Runtime:
        def __init__(self, passed_catalog, sessions):
            event("runtime.construct", passed_catalog is catalog, sessions is workspace)

        async def close(self):
            event("runtime.close")

    class ChildRuntime:
        async def shutdown(self):
            nonlocal shutdown_count
            shutdown_count += 1
            event("shutdown", shutdown_count)
            shutdown_entered.set()
            if block_shutdown:
                await shutdown_release.wait()
            if case == "close-open-reject-retry" and shutdown_count == 1:
                return NS(completed=False)
            await lease.close()
            return NS(completed=True)

    child_runtime = ChildRuntime()

    class Child:
        async def open(self):
            nonlocal child_open_count
            child_open_count += 1
            event("child.open")
            open_entered.set()
            if block_open:
                await open_release.wait()
            return child_runtime

        async def close(self):
            event("child.close")
            await lease.close()

    child = Child()
    workspace = object.__new__(CodingWorkspaceCatalog)

    async def load(self):
        assert self is workspace
        event("load")

    def registrations(request, product_factory):
        event(
            "registrations", request is foreground, isinstance(product_factory, Factory)
        )
        return "product", "profile"

    def resolver(**kwargs):
        event(
            "resolver.construct",
            list(kwargs),
            kwargs["runtime"] is attempt._runtime,
            kwargs["sessions"] is workspace,
            kwargs["profile_id"],
        )
        return "resolver"

    def application(request, **kwargs):
        event(
            "application.request",
            request is foreground,
            list(kwargs),
            kwargs["resolver"],
        )
        return "application-request"

    def child_request(**kwargs):
        event(
            "child.request",
            list(kwargs),
            kwargs["continuity_lease"] is lease,
            kwargs["application"],
            kwargs["application_id"],
            kwargs["owner_epoch"],
            kwargs["phase_timeout_seconds"],
        )
        return NS(**kwargs)

    def construct_child(request):
        event("child.construct", request.continuity_lease is lease)
        return child

    monkeypatch.setattr(code, "CodingForegroundProductFactoryV1", Factory)
    monkeypatch.setattr(code, "AppHostCatalogInputV1", lambda **fields: NS(**fields))
    monkeypatch.setattr(code, "AppHostCatalogV1", Catalog)
    monkeypatch.setattr(code, "AppHostRuntimeV1", Runtime)
    monkeypatch.setattr(code, "CodingAppHostHostedSessionResolverV1", resolver)
    monkeypatch.setattr(code, "_coding_hosted_registrations", registrations)
    monkeypatch.setattr(code, "_coding_hosted_application_request", application)
    monkeypatch.setattr(code, "HostedApplicationContinuityRequestV1", child_request)
    monkeypatch.setattr(
        code, "create_hosted_application_continuity_attempt", construct_child
    )
    monkeypatch.setattr(CodingWorkspaceCatalog, "load", load)
    foreground = NS(
        session_factory="session-factory",
        session_owner="session-owner",
        sessions=workspace,
        generation_id="generation",
        profile_id="profile",
        operation_id_factory="operation-factory",
        admitted_scopes=("scope",),
        execution=None,
        managed_selection="selection",
    )
    request = object.__new__(code.CodingHostedContinuityRequestV1)
    for key, value in dict(
        activation="activation",
        foreground=foreground,
        application_id="application",
        owner_epoch="epoch",
        store=Store(),
        phase_timeout_seconds=2.0,
    ).items():
        object.__setattr__(request, key, value)
    attempt = code.CodingHostedContinuityAttemptV1(request)
    outcomes = []

    async def call(name, operation):
        try:
            value = await operation
        except BaseException as error:
            outcomes.append([name, {"error": error_data(error, injected)}])
        else:
            outcomes.append(
                [
                    name,
                    {"runtime_identity": value is child_runtime}
                    if value is not None
                    else None,
                ]
            )

    if case == "slots":
        return {
            "trace": trace,
            "slots": list(type(attempt).__slots__),
            "has_dict": hasattr(attempt, "__dict__"),
            "signatures": {
                name: str(inspect.signature(getattr(type(attempt), name)))
                for name in ("__init__", "open", "close")
            },
            "cleanup_pending": attempt.cleanup_pending,
        }
    if case == "early-close":
        await call("close", attempt.close())
        await call("open", attempt.open())
    elif case == "concurrent-open":
        one = asyncio.create_task(attempt.open())
        await open_entered.wait()
        original_task = attempt._open_task
        two = asyncio.create_task(attempt.open())
        await asyncio.sleep(0)
        event("same.open.task", original_task is attempt._open_task)
        open_release.set()
        await call("first", one)
        await call("second", two)
        await call("close", attempt.close())
    elif case == "close-open-reject-retry":
        opening = asyncio.create_task(attempt.open())
        await open_entered.wait()
        closing = asyncio.create_task(attempt.close())
        await asyncio.sleep(0)
        open_release.set()
        await call("open", opening)
        await call("first.close", closing)
        await call("retry.close", attempt.close())
    elif case == "caller-cancel-open":
        opening = asyncio.create_task(attempt.open())
        await open_entered.wait()
        original_task = attempt._open_task
        opening.cancel("original-caller")
        await asyncio.sleep(0)
        open_release.set()
        await call("cancelled.open", opening)
        event("underlying.open.cancelled", original_task.cancelled())
        await call("retry.open", attempt.open())
        event("same.open.task", original_task is attempt._open_task)
        await call("close", attempt.close())
    elif case == "caller-cancel-close":
        opening = asyncio.create_task(attempt.open())
        await open_entered.wait()
        closing = asyncio.create_task(attempt.close())
        await asyncio.sleep(0)
        open_release.set()
        await shutdown_entered.wait()
        closing.cancel("original-caller")
        await asyncio.sleep(0)
        shutdown_release.set()
        await call("rejected.open", opening)
        await call("cancelled.close", closing)
        await call("retry.close", attempt.close())
    else:
        await call("open", attempt.open())
        if case in {"success", "open-retry"}:
            await call("retry.open", attempt.open())
        await call("close", attempt.close())
        if case in {
            "factory-close-retry",
            "runtime-close-retry",
            "lease-close-retry",
            "child-close-retry",
        }:
            await call("retry.close", attempt.close())
    # Reachability and public ownership invariants independent of expected output.
    assert all(not errors for errors in faults.values()), faults
    if case in {"success", "open-retry", "concurrent-open", "caller-cancel-open"}:
        assert any(value == {"runtime_identity": True} for _, value in outcomes)
    if case != "early-close":
        assert trace[0][0] == "factory.construct"
    if case in {"concurrent-open", "caller-cancel-open"}:
        assert child_open_count == 1
    if case == "open-retry":
        assert child_open_count == 2
        assert sum(row[0] == "acquire" for row in trace) == 1
    if case == "close-open-reject-retry":
        assert shutdown_count == 2
    if case == "caller-cancel-close":
        assert shutdown_count == 1
    if case not in {"success", "open-retry", "concurrent-open", "caller-cancel-open"}:
        assert attempt.cleanup_pending is False
    return {
        "trace": trace,
        "outcomes": outcomes,
        "cleanup_pending": attempt.cleanup_pending,
    }


@pytest.mark.parametrize("case", CASES)
def test_old_prefix(case, monkeypatch):
    observed = json.loads(json.dumps(asyncio.run(observe(case, monkeypatch))))
    expected = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert observed == expected[case]


def test_existing_inner_attempt_reuses_published_runtime():
    async def observe():
        events = []
        lease = _Lease(events, _record())
        attempt, resolver = _attempt(events, lease)
        runtime = await attempt.open()
        try:
            assert await attempt.open() is runtime
            assert attempt.cleanup_pending is False
            assert len(resolver.requests) == 1
        finally:
            report = await runtime.shutdown()
        assert report.completed is True
        assert events == ["service", "apphost", "product", "lease"]
        await attempt.close()

    asyncio.run(observe())
