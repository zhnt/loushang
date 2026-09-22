import asyncio

import pytest

from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1

from ._lmux_admission_diagnostic import AdmissionTrace, observe_binding


@pytest.mark.parametrize("fault", [None, "prepare", "acquire", "check", "close", "cancel"])
@pytest.mark.parametrize("broken_sink", [False, True])
def test_diagnostic_never_loses_owner_or_replaces_original_failure(fault, broken_sink):
    events, records = [], []
    failure = asyncio.CancelledError() if fault == "cancel" else ValueError("private request details")
    request, previous = object(), object()

    class Owner:
        async def acquire(self):
            events.append("acquire")
            if fault in {"acquire", "cancel"}:
                raise failure

        def check_creation(self, value):
            assert value is previous
            events.append("check")
            if fault == "check":
                raise failure

        async def close(self):
            events.append("close")
            if fault == "close":
                raise failure

    owner = Owner()

    def prepare(value):
        assert value is request
        events.append("prepare")
        if fault == "prepare":
            raise failure
        return owner

    def emit(phase, **fields):
        if broken_sink:
            raise OSError("trace disk failed")
        records.append((phase, fields))

    trace = AdmissionTrace(emit)
    binding = ManagedMuxServiceBindingV1("coding.default", "a" * 64, "b" * 32, prepare)
    observed = observe_binding(binding, trace)
    assert (observed.application_id, observed.service_id, observed.instance_id, observed.closing) == (
        binding.application_id, binding.service_id, binding.instance_id, binding.closing,
    )
    if fault == "prepare":
        with pytest.raises(ValueError) as caught:
            observed.prepare(request)
        assert caught.value is failure and events == ["prepare"]
    else:
        proxy = observed.prepare(request)
        assert proxy.owner is owner

        async def run():
            try:
                await proxy.acquire()
                proxy.check_creation(previous)
            except BaseException as error:
                assert fault in {"acquire", "check", "cancel"} and error is failure
            finally:
                # Caller retains the original debt semantics: every close is
                # delegated, even after an earlier close failure or success.
                for _ in range(2):
                    try:
                        await proxy.close()
                    except BaseException as error:
                        assert fault == "close" and error is failure

        asyncio.run(run())
        assert events.count("prepare") == 1 and events.count("close") == 2
    assert trace.disabled is broken_sink
    assert "private request details" not in repr(records)
    if not broken_sink and fault is not None:
        assert any(phase.endswith("_fail") for phase, fields in records)
