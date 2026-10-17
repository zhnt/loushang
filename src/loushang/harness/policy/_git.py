"""Literal Git command recognition shared by all command dialects.

Recognition does not authorize an action. Policy still checks declared effects,
managed rules and Git's destructive/publication effects. Aliases, expansion and
arbitrary shell programs are deliberately outside this lexical recognizer.
"""

from __future__ import annotations

import shlex

from ._powershell import parse_simple_powershell_command
from .subjects import CommandPolicySubject

_BUILTINS = frozenset(
    "add am annotate apply archive bisect blame branch bundle cat-file "
    "check-attr check-ignore check-mailmap check-ref-format checkout "
    "checkout-index cherry cherry-pick clean clone column commit commit-graph "
    "commit-tree config count-objects describe diff diff-files diff-index "
    "diff-tree difftool fast-export fast-import fetch fetch-pack fmt-merge-msg "
    "for-each-ref format-patch fsck fsck-objects gc get-tar-commit-id grep "
    "hash-object help index-pack init init-db interpret-trailers log "
    "ls-files ls-remote ls-tree mailinfo mailsplit merge merge-file merge-tree "
    "merge-base mergetool mv name-rev notes prune pull push range-diff read-tree rebase "
    "mktag mktree pack-objects pack-refs patch-id reflog remote repack replace "
    "rerere reset restore revert rev-list rev-parse rm shortlog show show-branch "
    "show-index show-ref sparse-checkout stage stash status stripspace submodule "
    "switch symbolic-ref tag unpack-file unpack-objects update-index update-ref "
    "var verify-commit verify-pack verify-tag version whatchanged worktree write-tree".split()
)
_VALUE_OPTIONS = frozenset(
    {"-C", "-c", "--exec-path", "--git-dir", "--namespace", "--work-tree"}
)
_LITERAL_VALUE_OPTIONS = _VALUE_OPTIONS - {"-c", "--exec-path"}
_FLAG_OPTIONS = frozenset(
    {
        "--bare",
        "--no-pager",
        "--paginate",
        "--no-optional-locks",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
        "--no-replace-objects",
        "--no-lazy-fetch",
    }
)
_DATA_CONFIG_KEYS = frozenset(
    {
        "core.quotepath",
        "core.autocrlf",
        "core.eol",
        "core.filemode",
        "core.longpaths",
        "core.precomposeunicode",
        "safe.directory",
        "commit.gpgsign",
        "tag.gpgsign",
        "diff.mnemonicprefix",
    }
)


def git_operation(arguments: tuple[str, ...]) -> tuple[str | None, tuple[str, ...]]:
    """Locate a subcommand, including attached and repeated global options."""

    remaining = list(arguments)
    while remaining:
        value = remaining.pop(0)
        option, separator, _ = value.partition("=")
        if option in _VALUE_OPTIONS:
            if not separator:
                if not remaining:
                    return None, ()
                remaining.pop(0)
            continue
        if value.startswith(("-C", "-c")) and len(value) > 2:
            continue
        if value in {"--version", "-v"}:
            return "version", tuple(remaining)
        if value.startswith("-"):
            continue
        return value, tuple(remaining)
    return None, ()


def literal_git_commands(
    command: CommandPolicySubject,
) -> tuple[tuple[str, ...], ...] | None:
    """Recognize every command in a literal Git-only sequence, or none of it."""

    if not command.normalization_complete:
        return None
    groups: tuple[tuple[str, ...], ...]
    if command.shell_payload is None:
        groups = (command.direct_tokens,)
    else:
        scripts = _split_commands(command.shell_payload, command.dialect)
        if scripts is None:
            return None
        parsed: list[tuple[str, ...]] = []
        for script in scripts:
            if command.dialect == "powershell":
                explicit_call = script.startswith("&")
                tokens = parse_simple_powershell_command(
                    script[1:].lstrip() if explicit_call else script,
                    allow_quoted_command=explicit_call,
                )
            elif command.dialect == "cmd":
                tokens = _cmd_tokens(script)
            else:
                try:
                    tokens = tuple(shlex.split(script, posix=True))
                except ValueError:
                    return None
            if not tokens:
                return None
            parsed.append(tokens)
        groups = tuple(parsed)
    if not groups or not all(_is_literal_git(tokens) for tokens in groups):
        return None
    return tuple(tokens[1:] for tokens in groups)


def _is_literal_git(tokens: tuple[str, ...]) -> bool:
    if not tokens or tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold() not in {
        "git",
        "git.exe",
    }:
        return False
    arguments = list(tokens[1:])
    while arguments:
        value = arguments.pop(0)
        option, separator, operand = value.partition("=")
        if value.startswith(("-C", "-c")) and len(value) > 2:
            option, operand, separator = value[:2], value[2:], "="
        if option in _LITERAL_VALUE_OPTIONS | {"-c"}:
            if not separator:
                if not arguments:
                    return False
                operand = arguments.pop(0)
            if option == "-c":
                key, _, config_value = operand.partition("=")
                harmless_editor = key.lower() in {
                    "core.editor",
                    "sequence.editor",
                } and config_value in {"true", ":"}
                if not (
                    key.lower() in _DATA_CONFIG_KEYS
                    or key.lower().startswith(("color.", "advice."))
                    or harmless_editor
                ):
                    return False
            continue
        if value in _FLAG_OPTIONS:
            continue
        if value in {"--version", "-v"}:
            return not arguments
        return value in _BUILTINS
    return False


def _split_commands(script: str, dialect: str) -> tuple[str, ...] | None:
    """Split literal chains without interpreting quoted separators as syntax."""

    groups: list[str] = []
    quote: str | None = None
    start = index = 0
    while index < len(script):
        character = script[index]
        if dialect == "cmd" and character in "%!^":
            return None
        if dialect == "cmd" and quote and character in "\r\n":
            return None
        if (
            dialect == "cmd"
            and character == '"'
            and index
            and script[index - 1] == "\\"
        ):
            return None
        if quote:
            if dialect != "cmd" and quote == '"' and character in "`$":
                return None
            if character == quote:
                if (
                    dialect == "powershell"
                    and quote == "'"
                    and script[index : index + 2] == "''"
                ):
                    index += 2
                    continue
                quote = None
            elif dialect == "posix" and character == "\\" and quote == '"':
                index += 1
            index += 1
            continue
        if character == '"' or (character == "'" and dialect != "cmd"):
            quote = character
        elif character in "`$<>#(){}" or (
            dialect == "powershell" and character in "@[],"
        ):
            return None
        elif dialect == "posix" and character == "\\":
            index += 2
            continue
        elif (
            dialect == "powershell"
            and character == "&"
            and not script[start:index].strip()
        ):
            # A literal call operator before Git is not a command separator.
            index += 1
            continue
        elif character in ";&|\r\n":
            pair = script[index : index + 2]
            if (
                character in "&|"
                and pair not in {"&&", "||"}
                and character != "|"
                and not (dialect == "cmd" and character == "&")
            ):
                return None
            if character == ";" and dialect == "cmd":
                return None
            group = script[start:index].strip()
            if not group:
                if character not in "\r\n":
                    return None
            else:
                groups.append(group)
            index += 2 if pair in {"&&", "||", "\r\n"} else 1
            start = index
            continue
        index += 1
    if quote or script.rstrip().endswith(("&&", "||")):
        return None
    if script[start:].strip():
        groups.append(script[start:].strip())
    return tuple(groups) or None


def _cmd_tokens(script: str) -> tuple[str, ...] | None:
    # Cmd has double-quoted literals; backslashes and single quotes are data.
    tokens: list[str] = []
    current: list[str] = []
    quoted = started = False
    for character in script:
        if character == '"':
            quoted = not quoted
            started = True
        elif character.isspace() and not quoted:
            if started:
                tokens.append("".join(current))
                current.clear()
                started = False
        else:
            current.append(character)
            started = True
    if quoted:
        return None
    if started:
        tokens.append("".join(current))
    return tuple(tokens)
