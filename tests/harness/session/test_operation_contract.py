from __future__ import annotations

from loushang.harness.session import (
    SessionOperationAvailability,
    current_session_operation_resolver,
)
from tests.harness.session.operation_contract import (
    CurrentSessionSlot,
    SessionOperationContract,
)


class TestHarnessSessionOperationContract(SessionOperationContract):
    @staticmethod
    def resolver_factory(
        slot: CurrentSessionSlot,
        availability: SessionOperationAvailability | None,
    ):
        return current_session_operation_resolver(
            slot,
            availability=availability,
        )
