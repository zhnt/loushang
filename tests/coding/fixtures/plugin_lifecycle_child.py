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
    session = create_agent_session(
        session_manager=manager,
        model=_model(),
        services=create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        ),
    )
    assembly = session._coding_base_plugin_assembly
    assert assembly is not None
    lease = assembly.management_lease
    assert lease is not None
    child_state = {
        "familyId": lease.family.family_id,
        "sessionId": manager.get_header().conversation_id,
    }
    if args.mode == "crash_during_owner_publication":
        from loushang.coding._plugin_owner_generations import (
            CodingOwnerGenerationEvidenceLedger,
        )

        def crash_after_prepare(_self, *, family_id, receipts, **_kwargs):
            args.marker.write_text(
                json.dumps(
                    {
                        "familyId": family_id,
                        "receiptCount": len(receipts),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            os._exit(83)

        setattr(CodingOwnerGenerationEvidenceLedger, "publish", crash_after_prepare)
        _emit(child_state)
        await session.prepare_model_call_runtime()
        raise AssertionError("owner evidence publication crash hook did not exit")

    await session.prepare_model_call_runtime()
    _emit(child_state)
    threading.Event().wait()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("hold", "crash_during_owner_publication"),
    )
    parser.add_argument("loushang_home", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("marker", type=Path)
    asyncio.run(_run(parser.parse_args()), debug=False)


if __name__ == "__main__":
    main()
