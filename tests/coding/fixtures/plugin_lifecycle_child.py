from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
from pathlib import Path

from loushang.ai.model import Capabilities, Model
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.session_manager import SessionManager


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


async def _run(args: argparse.Namespace) -> None:
    os.environ["LOUSHANG_HOME"] = str(args.loushang_home)
    manager = await SessionManager.new(
        session_dir=args.session_dir,
        cwd=str(args.workspace),
        persist=True,
    )
    if args.mode == "product_crash_after_lease":
        from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
            PackageEpochRuntimeLeaseRegistry,
        )

        register = PackageEpochRuntimeLeaseRegistry.register

        def crash_after_register(self, *, runtime_id, runtime_protocol_epoch):
            handle = register(
                self,
                runtime_id=runtime_id,
                runtime_protocol_epoch=runtime_protocol_epoch,
            )
            payload = {
                "leaseId": handle.lease.lease_id,
                "runtimeId": runtime_id,
                "sessionId": manager.get_header().conversation_id,
            }
            args.marker.write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )
            _emit(payload)
            os._exit(83)

        PackageEpochRuntimeLeaseRegistry.register = crash_after_register
    session = create_agent_session(
        session_manager=manager,
        model=_model(),
        services=create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        ),
    )
    if args.mode == "product_hold":
        from importlib.metadata import version

        from loushang.coding._plugin_lifecycle import (
            resolve_coding_plugin_lifecycle_state_layout,
        )
        from loushang.coding.package_product_runtime import (
            CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            open_coding_fenced_product_application_owner,
        )

        await session.prepare_model_call_runtime()
        selected = session._coding_base_product_compilation
        assert selected is not None
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(args.workspace),
            workspace=args.workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            registry = owner.epoch_runtime.registry
            [lease] = registry.snapshot(store_id=registry.store_id).active_leases
            _emit(
                {
                    "leaseId": lease.lease_id,
                    "runtimeId": lease.runtime_id,
                    "sessionId": manager.get_header().conversation_id,
                    "selectedRevision": repr(
                        selected.selected_manifest.snapshot.package_revision
                    ),
                }
            )
        finally:
            owner.close()
        threading.Event().wait()

    raise AssertionError("Product crash hook did not exit after lease registration")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("product_hold", "product_crash_after_lease"),
    )
    parser.add_argument("loushang_home", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("marker", type=Path)
    asyncio.run(_run(parser.parse_args()), debug=False)


if __name__ == "__main__":
    main()
