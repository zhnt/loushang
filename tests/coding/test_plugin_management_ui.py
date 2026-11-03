from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from loushang.coding.package_product_repair import CodingPackageRepairResultV1
from loushang.coding.package_product_repair_ui import (
    execute_coding_package_repair_ui_command,
)
from loushang.coding.plugin_management_ui import (
    execute_coding_plugin_management_ui_command,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredCommandRepairError,
)


@dataclass
class _CommandClient:
    desired_state: str = "installed_enabled"
    layout: object = field(
        default_factory=lambda: SimpleNamespace(scope_id="workspace:test")
    )
    submissions: list[dict[str, object]] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)

    def snapshot(
        self, *, correlation_id: str, plugin_ids: tuple[str, ...] = ()
    ) -> dict[str, object]:
        assert correlation_id
        assert plugin_ids == ("reviewpack",)
        return {
            "ownerRevisions": {"desiredState": 7},
            "installations": [
                {
                    "installationKey": {"pluginId": "reviewpack"},
                    "desiredState": self.desired_state,
                }
            ],
        }

    def submit_desired(self, **kwargs: object) -> dict[str, object]:
        self.submissions.append(kwargs)
        operation_id = kwargs["operation_id"]
        return {
            "operation": {
                "command": {"mutation": {"operationId": operation_id}},
                "status": "terminal",
                "result": {"disposition": "succeeded", "errorCode": None},
            }
        }

    def repair_own_desired_operation(
        self, operation_id: str, *, correlation_id: str
    ) -> dict[str, object]:
        assert correlation_id
        self.repairs.append(operation_id)
        return {"disposition": "unknown", "result": None}


def test_tui_desired_command_uses_one_owner_revision_and_replayable_identity() -> None:
    client = _CommandClient()

    def open_client(_workspace: str | Path) -> _CommandClient:
        return client

    first = execute_coding_plugin_management_ui_command(
        Path("/tmp/workspace"), "/plugins disable reviewpack", open_client=open_client
    )
    repeated = execute_coding_plugin_management_ui_command(
        Path("/tmp/workspace"), "/plugins disable reviewpack", open_client=open_client
    )

    assert first.error_message is None
    assert "new Session required" in (first.status_message or "")
    assert client.submissions[0]["expected_inventory_revision"] == 7
    assert client.submissions[0]["action"] == "disable"
    assert client.submissions[0]["plugin_id"] == "reviewpack"
    assert client.submissions[0]["operation_id"] == client.submissions[1]["operation_id"]
    assert repeated.status_message == first.status_message


def test_tui_desired_command_refuses_already_selected_or_invalid_intent() -> None:
    client = _CommandClient(desired_state="installed_disabled")
    opens: list[str] = []

    def open_client(_workspace: str | Path) -> _CommandClient:
        opens.append("opened")
        return client

    already = execute_coding_plugin_management_ui_command(
        "/tmp/workspace", "/plugins disable reviewpack", open_client=open_client
    )
    invalid = execute_coding_plugin_management_ui_command(
        "/tmp/workspace", "/plugins install reviewpack", open_client=open_client
    )

    assert "already installed_disabled" in (already.status_message or "")
    assert client.submissions == []
    assert invalid.error_message is not None
    assert opens == ["opened"]


def test_tui_desired_command_surfaces_stale_cas_without_hidden_retry() -> None:
    class ConflictingClient(_CommandClient):
        def submit_desired(self, **kwargs: object) -> dict[str, object]:
            self.submissions.append(kwargs)
            return {
                "operation": {
                    "command": {
                        "mutation": {"operationId": kwargs["operation_id"]}
                    },
                    "status": "terminal",
                    "result": {
                        "disposition": "failed",
                        "errorCode": "plugin_inventory_revision_conflict",
                    },
                }
            }

    client = ConflictingClient()
    result = execute_coding_plugin_management_ui_command(
        "/tmp/workspace", "/plugins disable reviewpack",
        open_client=lambda _workspace: client,
    )

    assert "plugin_inventory_revision_conflict" in (result.error_message or "")
    assert len(client.submissions) == 1


def test_tui_repair_uses_its_own_operation_authority_and_redacts_failure() -> None:
    client = _CommandClient()
    unknown = execute_coding_plugin_management_ui_command(
        "/tmp/workspace", "/plugins repair tui-operation:unknown",
        open_client=lambda _workspace: client,
    )
    assert unknown.status_message == "Plugin operation unknown: tui-operation:unknown"
    assert client.repairs == ["tui-operation:unknown"]

    def foreign(_workspace: str | Path) -> _CommandClient:
        raise PluginDesiredCommandRepairError(
            "private owner information",
            code="plugin_management_repair_foreign_operation",
        )

    refused = execute_coding_plugin_management_ui_command(
        "/tmp/workspace", "/plugins repair tui-operation:foreign",
        open_client=foreign,
    )
    assert refused.error_message == (
        "Plugin command failed: plugin_management_repair_foreign_operation"
    )
    assert "private owner information" not in (refused.error_message or "")


def test_tui_package_repair_requires_explicit_action_and_reports_commit() -> None:
    calls: list[tuple[str, str]] = []

    class Client:
        def perform(self, action: str, operation_id: str) -> CodingPackageRepairResultV1:
            calls.append((action, operation_id))
            return CodingPackageRepairResultV1(
                operation_id=operation_id,
                phase="committed",
                disposition="committed",
                decision_id="decision:one",
            )

    def open_client(_workspace: str | Path) -> Client:
        return Client()
    invalid = execute_coding_package_repair_ui_command(
        "/tmp/workspace", "/plugins repair-package retryable package:one",
        open_client=open_client,  # type: ignore[arg-type]
    )
    committed = execute_coding_package_repair_ui_command(
        "/tmp/workspace", "/plugins repair-package repair-retryable package:one",
        open_client=open_client,  # type: ignore[arg-type]
    )
    assert invalid.error_message is not None
    assert calls == [("repair-retryable", "package:one")]
    assert committed.error_message is None
    assert "new Session required" in (committed.status_message or "")


def test_tui_package_repair_redacts_owner_error() -> None:
    def private(_workspace: str | Path) -> object:
        raise RuntimeError("private Source path")

    result = execute_coding_package_repair_ui_command(
        "/tmp/workspace", "/plugins repair-package repair-retryable package:one",
        open_client=private,  # type: ignore[arg-type]
    )
    assert result.error_message == "Package repair refused: package_repair_unavailable"
    assert "private Source path" not in (result.error_message or "")
