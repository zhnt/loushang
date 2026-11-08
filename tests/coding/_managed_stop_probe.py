"""Stage 1C observations and bounded fault injection in the real Host child."""
from __future__ import annotations

import asyncio
import json
from time import monotonic

from loushang.agent import synthetic_model_transport
from loushang.apphost.continuity import HostedApplicationContinuityRuntimeV1
from loushang.apphost.local import HostedLocalRuntimeV1
from loushang.apphost.runtime import AppHostRuntimeV1
from loushang.appservice.execution_registry import ExecutionRegistryV1
from loushang.appservice.runtime import _SessionOwner
from loushang.coding.hosted_application import (
    CodingForegroundProductFactoryV1,
    _LeasedCodingHostedBinding,
)
from loushang.coding.hosted_catalog import CodingHostedSessionCatalogV1
from loushang.coding.hosted_execution import CodingHostedExecutionSessionV1
from loushang.coding.hosted_session import CodingRealHostedSessionV1


def install(root, audit):
    mode = json.loads((root / "stop-scenario.json").read_text())["mode"]

    async def gate(name):
        deadline = monotonic() + 60
        while not (root / name).exists():
            assert monotonic() < deadline, name
            await asyncio.sleep(0.01)

    @synthetic_model_transport
    async def held(model, context, options=None):
        audit("model_entered")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            audit("model_cancelled")
            if mode == "timeout":
                await gate("release-failure")
            audit("model_settled")
            raise

    original_fence = HostedLocalRuntimeV1._fence

    def fence(self, reply):
        first = not self._closing
        original_fence(self, reply)
        if first:
            audit("local_fenced")

    HostedLocalRuntimeV1._fence = fence
    original_local_close = HostedLocalRuntimeV1._close_once

    async def close_local(self):
        # Keep the existing socket alive after the real admission fence so the
        # concurrent request receives an actual protocol rejection, not EOF.
        await gate("release-close")
        await original_local_close(self)
        audit("local_closed")

    HostedLocalRuntimeV1._close_once = close_local
    original_registry_fence = ExecutionRegistryV1.fence

    def registry_fence(self):
        original_registry_fence(self)
        audit("registry_fenced")

    ExecutionRegistryV1.fence = registry_fence
    original_interrupt = ExecutionRegistryV1.interrupt

    def interrupt(self, binding, execution_id):
        result = original_interrupt(self, binding, execution_id)
        audit("interrupt", session_id=binding.view.identity.session_id, execution_id=execution_id,
              requested=result.state.interrupt_requested)
        return result

    ExecutionRegistryV1.interrupt = interrupt
    original_finish = ExecutionRegistryV1._finish

    def finish(self, invocation, outcome):
        result = original_finish(self, invocation, outcome)
        audit("execution_terminal", session_id=invocation.record.identity.session_id,
              execution_id=invocation.record.state.execution_id, status=invocation.record.state.status.value,
              active_released=invocation.binding.active is None)
        return result

    ExecutionRegistryV1._finish = finish

    def observe(cls, method, label, *, identity=True):
        original = getattr(cls, method)

        async def observed(self, *args, **kwargs):
            fields = {"owner": id(self)}
            if identity:
                fields["session_id"] = self.identity.session_id
            if (label == "adapter" and mode == "failure"
                    and not (root / "release-failure").exists()
                    and self.identity.continuity_id == "stop-0"):
                # Fail one owner before release; others must still close.
                audit("injected_close_failure", **fields)
                raise RuntimeError("stage1c controlled adapter cleanup failure")
            audit(label + "_begin", **fields)
            result = await original(self, *args, **kwargs)
            audit(label + "_end", **fields)
            return result

        setattr(cls, method, observed)

    observe(_SessionOwner, "_close_port", "session_owner")
    observe(CodingHostedExecutionSessionV1, "_close_execution", "adapter")
    observe(_LeasedCodingHostedBinding, "_close_once", "lease_runtime")
    observe(CodingRealHostedSessionV1, "_close_once", "product")
    observe(CodingHostedSessionCatalogV1, "close", "catalog", identity=False)
    observe(CodingForegroundProductFactoryV1, "close", "product_factory", identity=False)
    # Observe actual AgentSession disposal and exact lease release separately.
    original_product_init = CodingRealHostedSessionV1.__init__

    def product_init(self, *args, **kwargs):
        original_product_init(self, *args, **kwargs)
        session_id = self.identity.session_id
        original_dispose = self._session.dispose

        async def dispose():
            audit("agent_dispose_begin", session_id=session_id)
            await original_dispose()
            audit("agent_dispose_end", session_id=session_id)

        self._session.dispose = dispose

    CodingRealHostedSessionV1.__init__ = product_init
    original_lease_init = _LeasedCodingHostedBinding.__init__

    def lease_init(self, *args, **kwargs):
        original_lease_init(self, *args, **kwargs)
        session_id = self.identity.session_id
        # Lease implementations may use slots; observe the class once below.
        lease_sessions[id(self._lease)] = session_id
        lease_class = type(self._lease)
        if lease_class in patched:
            return
        patched.add(lease_class)
        original_method = lease_class.close

        async def close(lease):
            identity = lease_sessions[id(lease)]
            audit("lease_begin", session_id=identity)
            await original_method(lease)
            audit("lease_end", session_id=identity)

        lease_class.close = close

    lease_sessions, patched = {}, set()
    _LeasedCodingHostedBinding.__init__ = lease_init
    original_shutdown = AppHostRuntimeV1.shutdown

    async def shutdown(self, *args, **kwargs):
        result = await original_shutdown(self, *args, **kwargs)
        audit("apphost_shutdown", completed=result.completed)
        return result

    AppHostRuntimeV1.shutdown = shutdown
    original_continuity_init = HostedApplicationContinuityRuntimeV1.__init__
    continuity_classes = set()

    def continuity_init(self, *args, **kwargs):
        original_continuity_init(self, *args, **kwargs)
        cls = type(self._lease)
        if cls not in continuity_classes:
            continuity_classes.add(cls)
            observe(cls, "close", "continuity_lease", identity=False)

    HostedApplicationContinuityRuntimeV1.__init__ = continuity_init
    original_continuity = HostedApplicationContinuityRuntimeV1._settle_once

    async def continuity(self, intent):
        report = await original_continuity(self, intent)
        audit("continuity_report", completed=report.completed, lease_released=report.lease_released)
        return report

    HostedApplicationContinuityRuntimeV1._settle_once = continuity
    return held
