"""Real local Coding application with only its model/tool response scripted."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _hosted_product_child import _preview_tool, scripted_stream

from loushang.ai.model import Capabilities, Model
from loushang.coding.cli.mux import _execute, _parser
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1
from loushang.coding.hosted_local import CodingLocalCommandV1, CodingLocalLaunchV1

if __name__ == "__main__":
    args = _parser().parse_args()
    launch = CodingLocalLaunchV1(
        CodingHostedLaunchV1(
            args.workspace.resolve(),
            args.application_root.resolve(),
            args.application_id,
            args.cwd_sessions.resolve(),
            args.home_sessions.resolve(),
        ),
        Path(args.connection_root).resolve(),
        args.endpoint,
        session_discovery=args.session_discovery,
    )
    command = CodingLocalCommandV1(
        launch,
        stream_fn=scripted_stream,
        tools=[_preview_tool()],
        model=Model(
            id="faux-model",
            name="Faux",
            provider="faux",
            endpoint="anthropic-messages",
            capabilities=Capabilities(
                input=("text",), context_window=128000, max_tokens=4096
            ),
        ),
    )
    output = sys.stdout
    raise SystemExit(
        _execute(
            lambda: command.run(
                ready=lambda: print(
                    json.dumps({"status": "ready", **launch.describe()}),
                    file=output,
                    flush=True,
                )
            ),
            lambda: command.cleanup_pending,
        )
    )
