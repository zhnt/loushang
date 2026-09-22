from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.apphost.managed.paths import resolve_managed_admission_root
from loushang.coding.managed_bootstrap import create_coding_managed_launch

from ..apphost.test_managed_bootstrap import deployment as deployment


def invocation(deployment, tmp_path):
    namespace, service, _, state, _ = deployment
    return ManagedChildInvocationV1(namespace, service, state.handoff.instance,
                                    state.handoff.attempt_id, str(tmp_path / "runtime"))


def test_coding_launch_binds_exact_workspace_layout_and_explicit_session_roots(deployment, tmp_path):
    value = invocation(deployment, tmp_path)
    launch = create_coding_managed_launch(
        value, application_id="coding.default", endpoint="workspace",
        cwd_sessions=tmp_path / "cwd-sessions", home_sessions=tmp_path / "home-sessions",
        session_discovery=True,
    )
    assert launch.application.workspace == Path(value.service.workspace)
    assert launch.application.application_root == Path(deployment[4].application)
    assert launch.connection_root == Path(deployment[4].connection)
    assert launch.application.cwd_sessions == tmp_path / "cwd-sessions"
    assert launch.application.home_sessions == tmp_path / "home-sessions"
    assert launch.session_discovery
    assert not launch.application.cwd_sessions.exists()
    assert not launch.application.home_sessions.exists()


def test_other_product_is_rejected_before_any_path_admission(deployment, tmp_path, monkeypatch):
    value = invocation(deployment, tmp_path)
    service = ManagedServiceKeyV1("work", value.service.workspace)
    other = ManagedChildInvocationV1(value.namespace, service, ManagedInstanceRefV1(
        value.namespace.namespace_key, service.service_id, value.instance.instance_id,
    ), value.attempt_id, value.runtime_root)

    def forbidden(*args, **kwargs):
        raise AssertionError("wrong Product cannot perform path admission")

    monkeypatch.setattr(Path, "resolve", forbidden)
    for candidate in (None, other):
        with pytest.raises(ManagedContractError):
            create_coding_managed_launch(candidate, application_id="coding.default", endpoint="workspace",
                                        cwd_sessions=tmp_path / "cwd", home_sessions=tmp_path / "home")


@pytest.mark.parametrize("mode", [
    "same", "nested", "application", "connection", "relative", "registry", "lifecycle", "logs", "temporary",
    "runtime_control", "platform_parent", "runtime_parent",
])
def test_explicit_session_roots_cannot_bypass_existing_disjoint_admission(deployment, tmp_path, mode):
    cwd, home = tmp_path / "cwd-sessions", tmp_path / "home-sessions"
    if mode == "same":
        home = cwd
    elif mode == "nested":
        home = cwd / "nested"
    elif mode == "application":
        cwd = Path(deployment[4].application)
    elif mode == "connection":
        cwd = Path(deployment[4].connection)
    elif mode == "relative":
        cwd = Path("relative")
    elif mode == "platform_parent":
        cwd = tmp_path / "platform"
    elif mode == "runtime_parent":
        cwd = tmp_path / "runtime"
    else:
        cwd = Path(getattr(deployment[4], mode))
    with pytest.raises(ValueError):
        create_coding_managed_launch(invocation(deployment, tmp_path), application_id="coding.default",
                                    endpoint="workspace", cwd_sessions=cwd, home_sessions=home)


@pytest.mark.parametrize("relationship", ["equal", "ancestor", "descendant"])
def test_explicit_legacy_catalog_cannot_overlap_admission(deployment, tmp_path, relationship):
    value = invocation(deployment, tmp_path)
    root = Path(resolve_managed_admission_root(value.namespace))
    selected = {"equal": root, "ancestor": root.parent.parent, "descendant": root / "sessions"}[relationship]
    with pytest.raises(ManagedContractError):
        create_coding_managed_launch(
            value, application_id="coding.default", endpoint="workspace",
            cwd_sessions=selected, home_sessions=tmp_path / "other-sessions",
        )


def test_explicit_scratch_is_not_a_session_root(deployment, tmp_path):
    value = replace(invocation(deployment, tmp_path), temporary_override=str(tmp_path / "scratch"))
    with pytest.raises(ManagedContractError):
        create_coding_managed_launch(value, application_id="coding.default", endpoint="workspace",
                                    cwd_sessions=tmp_path / "scratch/lmux/sessions", home_sessions=tmp_path / "home")
