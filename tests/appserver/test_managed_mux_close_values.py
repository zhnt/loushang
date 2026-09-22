from __future__ import annotations

from dataclasses import replace

import pytest


def request():
    from loushang.appserver.managed_mux_close import ManagedMuxCloseV1

    return ManagedMuxCloseV1("a" * 64, "b" * 32, "c" * 32, "d" * 32,
                             "dev", "mux-1", "private-close-authority")


@pytest.mark.parametrize("field,value", [
    ("service_id", "a" * 63), ("instance_id", True),
    ("operation_id", "bad"), ("creation_operation_id", "c" * 32),
    ("name", "../dev"), ("mux_space_id", "mux\n"), ("authority", ""),
])
def test_close_request_rejects_invalid_or_aliased_identity(field, value):
    with pytest.raises(ValueError):
        replace(request(), **{field: value})


def test_close_request_does_not_expose_authority_and_is_not_creation_request():
    from loushang.appserver.managed_mux import ManagedMuxCreateV1

    value = request()
    assert "private-close-authority" not in repr(value)
    assert not isinstance(value, ManagedMuxCreateV1)


def test_close_state_has_closed_phase_and_no_authority():
    from loushang.appserver.managed_mux_close import (
        ManagedMuxClosePhaseV1,
        ManagedMuxCloseStateV1,
    )

    pending = ManagedMuxCloseStateV1("c" * 32, "b" * 32, "d" * 32, "dev", "mux-1",
                                     ManagedMuxClosePhaseV1.CLEANUP_PENDING)
    closed = replace(pending, phase=ManagedMuxClosePhaseV1.CLOSED)
    assert closed.operation_id == pending.operation_id
    assert not hasattr(closed, "authority")
    for phase in ("closed", "stopped", None, True):
        with pytest.raises(ValueError):
            replace(pending, phase=phase)
    with pytest.raises(ValueError):
        replace(pending, creation_operation_id=pending.operation_id)
