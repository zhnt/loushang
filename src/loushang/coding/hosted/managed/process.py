"""Installed Coding entry for an AppHost managed child."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from pathlib import Path

from loushang.apphost.managed.bootstrap import (
    ManagedChildApplicationPreparation,
    ManagedChildBootstrapV1,
    run_managed_child_entry,
)
from loushang.apphost.managed.child import ManagedChildApplicationPortV1
from loushang.apphost.managed.invocation import (
    ManagedChildInvocationV1,
    build_managed_child_launch_request,
)
from loushang.hosting.contracts import ProcessLaunchRequest
from loushang.hosting.service_windows import WindowsServiceLaunchRequestV1

APPLICATION_ID = "coding.default"
ENDPOINT = "workspace"


def coding_managed_process_request(
    invocation: ManagedChildInvocationV1, descriptor: int, *, executable: str,
    environment: Mapping[str, str], session_root: Path | None = None,
) -> ProcessLaunchRequest | WindowsServiceLaunchRequestV1:
    return build_managed_child_launch_request(
        invocation,
        descriptor,
        product_id="coding",
        module="loushang.coding.hosted.managed.process",
        executable=executable,
        environment=environment,
        session_root=session_root,
        default_session_directory="data/sessions",
    )


def _load_application() -> ManagedChildApplicationPreparation:
    from loushang.coding.hosted.managed.local import (
        CodingManagedLocalCommandV1,
        create_coding_managed_local_launch,
    )

    def build(
        invocation: ManagedChildInvocationV1, session_root: Path,
        bootstrap: ManagedChildBootstrapV1, deadline: float,
    ) -> Callable[[], ManagedChildApplicationPortV1]:
        launch = create_coding_managed_local_launch(
            invocation, session_root=session_root, application_id=APPLICATION_ID,
            endpoint=ENDPOINT, session_discovery=True,
            store_state_root=Path(invocation.namespace.platform_home) / "state/session-stores",
            managed_mux=bootstrap.managed_mux_binding(application_id=APPLICATION_ID),
        )
        return partial(
            CodingManagedLocalCommandV1, launch,
            output_capture_factory=bootstrap.output_capture_factory(deadline=deadline),
        )

    return build


def main(argv: Sequence[str] | None = None) -> int:
    """Dedicated-process entry; never expose untrusted argument/exception text."""
    try:
        return run_managed_child_entry(
            sys.argv[1:] if argv is None else argv,
            product_id="coding",
            load_application=_load_application,
        )
    except Exception:
        print("managed_process_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["coding_managed_process_request"]
