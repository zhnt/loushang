"""Conservative lexical helpers for non-executing PowerShell policy analysis.

This is intentionally not a general PowerShell parser.  It recognizes only a
single direct command with literal arguments.  Scripts containing expansion,
control flow, pipelines, redirection, comments, splatting, or call operators
return ``None`` so callers can fail closed or defer to a real AST analyzer.
"""

from __future__ import annotations

_DYNAMIC_OR_CONTROL_CHARACTERS = frozenset("`$@;&|<>(){}[],#")


def parse_simple_powershell_command(script: str) -> tuple[str, ...] | None:
    """Return literal tokens for one simple command, otherwise ``None``."""

    if not isinstance(script, str) or not script.strip():
        return None
    if "\n" in script or "\r" in script:
        return None

    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    token_started = False
    command_was_quoted = False
    index = 0
    while index < len(script):
        character = script[index]
        if quote is not None:
            if character == "`" or (quote == '"' and character == "$"):
                return None
            if character == quote:
                if (
                    quote == "'"
                    and index + 1 < len(script)
                    and script[index + 1] == "'"
                ):
                    current.append("'")
                    index += 2
                    continue
                quote = None
            else:
                current.append(character)
            index += 1
            continue

        if character.isspace():
            if token_started:
                tokens.append("".join(current))
                current.clear()
                token_started = False
            index += 1
            continue
        if character in {"'", '"'}:
            if not tokens:
                command_was_quoted = True
            quote = character
            token_started = True
            index += 1
            continue
        if character in _DYNAMIC_OR_CONTROL_CHARACTERS:
            return None
        current.append(character)
        token_started = True
        index += 1

    if quote is not None:
        return None
    if token_started:
        tokens.append("".join(current))
    if not tokens or not tokens[0] or command_was_quoted:
        return None
    return tuple(tokens)


__all__ = ["parse_simple_powershell_command"]
