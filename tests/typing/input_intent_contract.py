from typing import Literal

from loushang.tui.input import InputIntent, InputIntentKind, _prompt_input_intent

SubmitIntentKind = Literal["submit"]

adapter_intent: InputIntent[str] = InputIntent(
    kind="example_plugin.openArtifact",
)
compatibility_kind: InputIntentKind = "example_plugin.openArtifact"
narrow_intent: InputIntent[SubmitIntentKind] = InputIntent(kind="submit")
broad_intent: InputIntent[str] = narrow_intent

invalid_prompt = _prompt_input_intent("example_plugin.openArtifact")  # type: ignore[arg-type]
invalid_narrow: InputIntent[SubmitIntentKind] = broad_intent  # type: ignore[assignment]
wrong_literal: InputIntent[SubmitIntentKind] = InputIntent(kind="prompt_cancel")  # type: ignore[arg-type]
