"""Eight required G17 families; Linux composed, other native observers pending."""

from __future__ import annotations

import json
import sys
from importlib.metadata import distribution
from pathlib import Path

import pytest

from loushang.appserver.protocol import SessionScopeV1
from tests.tui.terminal_process_support import selected_backend_name

from . import test_hosted_client_terminal as foreground
from . import test_hosted_entry_evidence as native
from . import test_hosted_legacy_evidence as legacy
from . import test_hosted_workflow_terminal as workflow


@pytest.mark.parametrize("case_id", [
    "G17-INSTALLED-ENTRY",
    "G17-INSTALLED-CWD",
    "G17-INSTALLED-HOME",
    "G17-INSTALLED-LOCAL",
    "G17-INSTALLED-LEGACY",
    "G17-PRODUCT-INTERACTION",
    "G17-NATIVE-START-CANCEL",
    "G17-NATIVE-FORCED-EXIT",
])
def test_G17_installed_evidence(case_id, tmp_path, record_testsuite_property, monkeypatch):
    from loushang.coding.cli import hosted_client
    from loushang.coding.ui import mode

    assert sys.platform == "linux", "complete Darwin/Windows observers are not composed yet"
    direct = json.loads(distribution("loushang").read_text("direct_url.json") or "{}")
    prefix = Path(sys.prefix).resolve()
    assert "archive_info" in direct and all(
        Path(module.__file__).resolve().is_relative_to(prefix)
        for module in (hosted_client, mode)
    ), "required G17 evidence must run from a wheel, not editable/source imports"
    record_testsuite_property("native_platform", sys.platform)
    record_testsuite_property("terminal_backend", selected_backend_name())
    record_testsuite_property("installation", "wheel")
    if case_id == "G17-INSTALLED-ENTRY":
        foreground.test_G17_TERMINAL_ENTRY_installed_help_ready_and_foreground_exit(
            tmp_path, record_testsuite_property,
        )
        native._run_observation(tmp_path, "real")
    elif case_id in {"G17-INSTALLED-CWD", "G17-INSTALLED-HOME"}:
        foreground.test_G17_TERMINAL_PICKER_resumes_canonical_history_and_recovers_on_relaunch(
            tmp_path, record_testsuite_property,
            SessionScopeV1.CWD if case_id.endswith("-CWD") else SessionScopeV1.USER_HOME,
        )
    elif case_id == "G17-INSTALLED-LOCAL":
        workflow.test_G17_TERMINAL_LOCAL_discovery_picker_detach_reattach_and_stop(
            tmp_path, record_testsuite_property,
        )
    elif case_id == "G17-INSTALLED-LEGACY":
        legacy.test_G17_TERMINAL_LEGACY_installed_profiles_and_embedded_startup(
            tmp_path, record_testsuite_property, monkeypatch,
        )
    elif case_id == "G17-PRODUCT-INTERACTION":
        workflow.test_G17_TERMINAL_PRODUCT_discovery_profile_keeps_turn_approval_and_interrupt(
            tmp_path, record_testsuite_property,
        )
    elif case_id == "G17-NATIVE-START-CANCEL":
        for case in ("start-cancel", "recovery-cancel"):
            root = tmp_path / case
            root.mkdir()
            native._run_observation(root, case, timeout=150)
    elif case_id == "G17-NATIVE-FORCED-EXIT":
        native._run_observation(tmp_path, "forced-exit")
    else:
        raise AssertionError("unexpected G17 required family")
