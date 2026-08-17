from __future__ import annotations

from types import SimpleNamespace

import pytest

from loushang.coding.ui.product_binding import (
    build_coding_session_operation_resolver,
)
from loushang.harness.session import SessionOperationAvailability
from tests.harness.session.operation_contract import (
    ContractControl,
    CurrentSessionSlot,
    SessionOperationContract,
)


class TestCodingSessionOperationContract(SessionOperationContract):
    @staticmethod
    def resolver_factory(
        slot: CurrentSessionSlot,
        availability: SessionOperationAvailability | None,
    ):
        return build_coding_session_operation_resolver(
            session=slot.current_session,
            runtime=slot,
            availability=availability,
        )


def test_coding_fixed_session_mode_does_not_require_a_runtime() -> None:
    control = ContractControl()
    resolve = build_coding_session_operation_resolver(
        session=SimpleNamespace(session_control=control),
    )

    assert resolve().session_id == "contract-session"


def test_coding_dynamic_mode_never_falls_back_to_the_seed_session() -> None:
    seed = SimpleNamespace(session_control=ContractControl())
    runtime = SimpleNamespace(
        get_current_session=lambda: None,
        current_session=seed,
    )
    resolve = build_coding_session_operation_resolver(
        session=seed,
        runtime=runtime,
    )

    with pytest.raises(RuntimeError, match="requires an active session"):
        resolve()
