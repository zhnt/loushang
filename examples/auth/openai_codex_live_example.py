"""Call the Codex endpoint with an existing Codex CLI ChatGPT login."""

from __future__ import annotations

import asyncio
import json
import sys

import loushang.ai as ai

MODEL_REF = ("openai", "coding-responses", "gpt-5.5")
USER_PROMPT = (
    "Explain the architecture of this repository briefly."
)


def _status_payload(status: ai.auth.AuthStatus) -> dict[str, object]:
    return {
        "authenticated": status.authenticated,
        "auth_kind": status.auth_kind,
        "provider": status.provider,
        "source": status.source,
        "source_description": status.source_description,
        "experimental": status.experimental,
    }


def _print_status(status: ai.auth.AuthStatus) -> None:
    print("Authentication status:")
    print(json.dumps(_status_payload(status), indent=2, sort_keys=True))


def _print_authentication_required(
    error: ai.auth.AuthenticationRequiredError,
    status: ai.auth.AuthStatus,
) -> None:
    details = error.info.details
    reason = details.get("reason", "authentication_required")
    raw_actions = details.get("available_actions")
    actions = (
        raw_actions
        if isinstance(raw_actions, list)
        and all(isinstance(action, str) for action in raw_actions)
        else list(status.actions)
    )
    hint = status.source_recovery_hint or "Run codex login"

    print("Authentication required.")
    print(f"Reason: {reason}")
    print("Actions:")
    for action in actions:
        print(f"- {action}")
    print("Hint:")
    print(hint)


async def run() -> str | None:
    model = ai.get_model(*MODEL_REF)
    status = await ai.auth.status(model)
    _print_status(status)
    try:
        request_auth = await ai.auth.get_auth(model)
    except ai.auth.AuthenticationRequiredError as error:
        _print_authentication_required(error, status)
        return None

    print(f"Resolved authentication: {type(request_auth).__name__}")
    events = await ai.stream(
        model,
        {"messages": [{"role": "user", "content": USER_PROMPT}]},
        ai.CallOptions(reasoning=ai.ReasoningOptions(effort="low")),
        auth=request_auth,
    )
    message = await events.result()
    text = "".join(
        part.text for part in message.content if getattr(part, "type", None) == "text"
    ).strip()
    if not text:
        raise RuntimeError(message.error_message or "Model returned no text")
    print("Model response:")
    print(text)
    return text


def _error_report(error: Exception) -> dict[str, object]:
    if isinstance(error, ai.AIError):
        return {
            "httpStatus": error.info.status_code,
            "message": error.info.message,
        }
    status = getattr(error, "status_code", None)
    return {
        "httpStatus": status if isinstance(status, int) else None,
        "message": str(error),
    }


def main() -> None:
    try:
        result = asyncio.run(run())
    except Exception as error:
        print(json.dumps(_error_report(error), sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from error
    if result is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
