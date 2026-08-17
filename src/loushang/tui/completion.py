from __future__ import annotations

import inspect
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

from loushang.tui.completion_models import (
    CompletionApplication,
    CompletionItem,
    CompletionSuggestions,
)

_PATH_DELIMITERS = frozenset((" ", "\t", '"', "'", "="))
_STRONG_PATH_MATCH_SCORE = 60
_AUTO_FD_PATH = "auto"


@dataclass(slots=True)
class CompletionCancellationToken:
    cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str = "cancelled") -> None:
        if self.cancelled:
            return
        self.cancelled = True
        self.reason = reason


@dataclass(frozen=True, slots=True)
class CompletionContext:
    lines: tuple[str, ...]
    cursor_line: int
    cursor_col: int
    force: bool = False
    explicit: bool = False
    cancellation_token: CompletionCancellationToken = field(default_factory=CompletionCancellationToken)

    @property
    def cancelled(self) -> bool:
        return self.cancellation_token.cancelled


@dataclass(slots=True)
class CombinedCompletionProvider:
    providers: tuple[Any, ...] = ()
    _last_provider: Any | None = field(default=None, init=False, repr=False)

    def __init__(self, providers: Sequence[Any] = ()) -> None:
        self.providers = tuple(providers)
        self._last_provider = None

    def get_suggestions(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
        explicit: bool = False,
        cancellation_token: CompletionCancellationToken | None = None,
    ) -> CompletionSuggestions | None:
        self._last_provider = None
        context = CompletionContext(
            lines=lines,
            cursor_line=cursor_line,
            cursor_col=cursor_col,
            force=force,
            explicit=explicit,
            cancellation_token=cancellation_token or CompletionCancellationToken(),
        )
        for provider in self.providers:
            if context.cancelled:
                return None
            suggestions = get_completion_suggestions(provider, context)
            if suggestions is None:
                continue
            if not suggestions.items:
                if suggestions.exclusive:
                    self._last_provider = provider
                    return suggestions
                continue
            self._last_provider = provider
            return suggestions
        return None

    def apply_completion(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        item: CompletionItem,
        prefix: str,
    ) -> CompletionApplication:
        provider = self._last_provider
        if provider is not None:
            apply_completion = getattr(provider, "apply_completion", None)
            if callable(apply_completion):
                return apply_completion(lines, cursor_line, cursor_col, item, prefix)
        for provider in self.providers:
            apply_completion = getattr(provider, "apply_completion", None)
            if callable(apply_completion):
                return apply_completion(lines, cursor_line, cursor_col, item, prefix)
        return _replace_prefix(lines, cursor_line, cursor_col, item.value, prefix)


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: str
    label: str = ""
    description: str = ""
    argument_hint: str = ""
    argument_provider: Any | None = None
    argument_group: str = ""


@dataclass(frozen=True, slots=True)
class SlashCommandCompletionProvider:
    commands: tuple[SlashCommand, ...] = ()
    max_results: int = 50

    def __init__(self, commands: Sequence[SlashCommand] = (), *, max_results: int = 50) -> None:
        object.__setattr__(self, "commands", tuple(commands))
        object.__setattr__(self, "max_results", max_results)

    def complete(self, prefix: str) -> tuple[CompletionItem, ...]:
        suggestions = self.get_suggestions((prefix,), 0, len(prefix))
        if suggestions is None:
            return ()
        return tuple(suggestions.items)

    def get_suggestions(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
        cancellation_token: CompletionCancellationToken | None = None,
    ) -> CompletionSuggestions | None:
        if cancellation_token is not None and cancellation_token.cancelled:
            return None
        if cursor_line < 0 or cursor_line >= len(lines):
            return None
        slash_prefix = _slash_prefix_before_cursor(lines[cursor_line], cursor_col)
        if slash_prefix is None:
            return None
        command_name, argument_prefix = _split_slash_prefix(slash_prefix)
        if argument_prefix is None:
            items = self._command_items_for_prefix(slash_prefix)
            return CompletionSuggestions(prefix=slash_prefix, items=items, group="Commands", exclusive=True)

        command = self._command_by_name(command_name)
        if command is None or command.argument_provider is None:
            return CompletionSuggestions(prefix=slash_prefix, items=(), group="Commands", exclusive=True)
        argument_items = _complete_argument_provider(
            command.argument_provider,
            argument_prefix,
            force=force,
            cancellation_token=cancellation_token,
        )
        if not argument_items:
            return CompletionSuggestions(prefix=slash_prefix, items=(), group=command.argument_group or "Arguments", exclusive=True)
        command_value = _slash_command_value(command)
        items = tuple(
            _slash_argument_completion_item(command_value, argument_item)
            for argument_item in argument_items[: self.max_results]
        )
        return CompletionSuggestions(
            prefix=slash_prefix,
            items=items,
            group=command.argument_group or "Arguments",
            exclusive=True,
        )

    def apply_completion(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        item: CompletionItem,
        prefix: str,
    ) -> CompletionApplication:
        current_line = lines[cursor_line]
        before_prefix = current_line[: max(0, cursor_col - len(prefix))]
        after_cursor = current_line[cursor_col:]
        closing_quote = _slash_argument_closing_quote(prefix)
        if closing_quote is not None and item.value.endswith(closing_quote) and after_cursor.startswith(closing_quote):
            after_cursor = after_cursor[1:]
        suffix = " " if _is_bare_slash_command_value(item.value) else ""
        if suffix and after_cursor[:1].isspace():
            suffix = ""
        new_lines = list(lines)
        new_lines[cursor_line] = f"{before_prefix}{item.value}{suffix}{after_cursor}"
        cursor_offset = len(item.value)
        if item.label.endswith("/") and _ends_with_quote(item.value):
            cursor_offset -= 1
        return CompletionApplication(
            lines=tuple(new_lines),
            cursor_line=cursor_line,
            cursor_col=len(before_prefix) + cursor_offset + len(suffix),
        )

    def _command_items_for_prefix(self, prefix: str) -> tuple[CompletionItem, ...]:
        needle = prefix.lower()
        items: list[tuple[int, int, CompletionItem]] = []
        for index, command in enumerate(self.commands):
            value = _slash_command_value(command)
            label = command.label or value
            score = _completion_match_score(needle, value.lower(), label.lower())
            if score is None:
                continue
            items.append((-score, index, CompletionItem(value=value, label=label, description=_slash_command_description(command))))
        items.sort(key=lambda item: (item[0], item[1]))
        return tuple(item for _score, _index, item in items[: self.max_results])

    def _command_by_name(self, name: str) -> SlashCommand | None:
        normalized_name = _normalize_slash_command_name(name)
        for command in self.commands:
            if _normalize_slash_command_name(command.name) == normalized_name:
                return command
        return None


@dataclass(frozen=True, slots=True)
class PathCompletionProvider:
    base_path: str | Path = "."
    max_results: int = 50
    include_hidden: bool = True
    exclude_names: tuple[str, ...] = (".git",)
    recursive: bool = False
    max_scan_entries: int = 2_000
    respect_gitignore: bool = True
    fd_path: str | Path | None = _AUTO_FD_PATH
    fd_timeout_seconds: float = 0.25

    def get_suggestions(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
        cancellation_token: CompletionCancellationToken | None = None,
    ) -> CompletionSuggestions | None:
        if cancellation_token is not None and cancellation_token.cancelled:
            return None
        if cursor_line < 0 or cursor_line >= len(lines):
            return None
        current_line = lines[cursor_line]
        text_before_cursor = current_line[:cursor_col]
        prefix = _extract_at_prefix(text_before_cursor)
        if prefix is None:
            prefix = _extract_path_prefix(text_before_cursor, force=force)
        if prefix is None:
            return None
        if _is_initial_absolute_path_token(text_before_cursor, prefix):
            return None
        items = self._items_for_prefix(prefix, cancellation_token=cancellation_token)
        if not items:
            return None
        return CompletionSuggestions(prefix=prefix, items=items, group="Files")

    def apply_completion(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        item: CompletionItem,
        prefix: str,
    ) -> CompletionApplication:
        current_line = lines[cursor_line]
        before_prefix = current_line[: max(0, cursor_col - len(prefix))]
        after_cursor = current_line[cursor_col:]
        closing_quote = _closing_quote_for_prefix(prefix)
        if closing_quote is not None and item.value.endswith(closing_quote) and after_cursor.startswith(closing_quote):
            after_cursor = after_cursor[1:]
        is_directory = item.label.endswith("/")
        suffix = " " if prefix.startswith("@") and not is_directory else ""
        if suffix and after_cursor[:1].isspace():
            suffix = ""
        new_lines = list(lines)
        new_lines[cursor_line] = f"{before_prefix}{item.value}{suffix}{after_cursor}"
        cursor_offset = len(item.value)
        if is_directory and _ends_with_quote(item.value):
            cursor_offset -= 1
        return CompletionApplication(
            lines=tuple(new_lines),
            cursor_line=cursor_line,
            cursor_col=len(before_prefix) + cursor_offset + len(suffix),
        )

    def _items_for_prefix(
        self,
        prefix: str,
        *,
        cancellation_token: CompletionCancellationToken | None = None,
    ) -> tuple[CompletionItem, ...]:
        if cancellation_token is not None and cancellation_token.cancelled:
            return ()
        parsed = _parse_path_prefix(prefix)
        raw_prefix = _to_display_path(parsed.raw_prefix)
        if self.recursive:
            fd_items = self._fd_recursive_items_for_prefix(
                parsed,
                raw_prefix,
                cancellation_token=cancellation_token,
            )
            if fd_items is not None:
                return fd_items
            recursive_items = self._recursive_items_for_prefix(
                parsed,
                raw_prefix,
                cancellation_token=cancellation_token,
            )
            if recursive_items:
                return recursive_items
        search_dir, search_prefix, display_base = _split_search(raw_prefix, base_path=Path(self.base_path))
        try:
            entries = list(search_dir.iterdir())
        except OSError:
            return ()
        ignore_matcher = (
            _GitignoreMatcher.from_base_path(Path(self.base_path))
            if self.respect_gitignore
            else _GitignoreMatcher.empty(Path(self.base_path))
        )

        items: list[tuple[bool, str, CompletionItem]] = []
        for entry in entries:
            if cancellation_token is not None and cancellation_token.cancelled:
                return ()
            name = entry.name
            if name in self.exclude_names:
                continue
            if ignore_matcher.matches(entry, is_directory=entry.is_dir()):
                continue
            if not self.include_hidden and name.startswith("."):
                continue
            if search_prefix and not name.lower().startswith(search_prefix.lower()):
                continue
            is_directory = entry.is_dir()
            display_path = _join_display_path(display_base, name)
            if is_directory:
                display_path = f"{display_path}/"
            value = _build_completion_value(
                display_path,
                is_at_prefix=parsed.is_at_prefix,
                is_quoted_prefix=parsed.is_quoted_prefix,
                quote_char=parsed.quote_char,
            )
            label = f"{name}/" if is_directory else name
            items.append((is_directory, name.lower(), CompletionItem(value=value, label=label, description=display_path)))

        items.sort(key=lambda item: (not item[0], item[1]))
        return tuple(item for _is_directory, _name, item in items[: self.max_results])

    def _recursive_items_for_prefix(
        self,
        parsed: _ParsedPathPrefix,
        raw_prefix: str,
        *,
        cancellation_token: CompletionCancellationToken | None = None,
    ) -> tuple[CompletionItem, ...]:
        if cancellation_token is not None and cancellation_token.cancelled:
            return ()
        base_path = Path(self.base_path)
        search_root, query, display_base = _split_recursive_search(raw_prefix, base_path=base_path)
        try:
            search_root = search_root.resolve(strict=True)
        except OSError:
            return ()
        ignore_matcher = (
            _GitignoreMatcher.from_base_path(base_path) if self.respect_gitignore else _GitignoreMatcher.empty(base_path)
        )
        scored: list[tuple[int, bool, int, str, CompletionItem]] = []
        scanned = 0
        for entry in _iter_recursive_entries(
            search_root,
            include_hidden=self.include_hidden,
            exclude_names=self.exclude_names,
            ignore_matcher=ignore_matcher,
            max_entries=self.max_scan_entries,
        ):
            if cancellation_token is not None and cancellation_token.cancelled:
                return ()
            scanned += 1
            if scanned > self.max_scan_entries:
                break
            try:
                relative = entry.relative_to(search_root)
            except ValueError:
                continue
            relative_display = _to_display_path(relative.as_posix())
            is_directory = entry.is_dir()
            display_path = _join_display_path(display_base, relative_display)
            if is_directory:
                display_path = f"{display_path}/"
            score = _fuzzy_path_score(query, display_path, entry.name, is_directory=is_directory)
            if score <= 0:
                continue
            value = _build_completion_value(
                display_path,
                is_at_prefix=parsed.is_at_prefix,
                is_quoted_prefix=parsed.is_quoted_prefix,
                quote_char=parsed.quote_char,
            )
            label = f"{entry.name}/" if is_directory else entry.name
            scored.append(
                (
                    score,
                    is_directory,
                    len(display_path.rstrip("/")),
                    display_path.lower(),
                    CompletionItem(value=value, label=label, description=display_path),
                )
            )

        strong_scores = [score for score, _is_directory, _length, _path, _item in scored if score >= _STRONG_PATH_MATCH_SCORE]
        if strong_scores:
            scored = [
                item
                for item in scored
                if item[0] >= _STRONG_PATH_MATCH_SCORE
            ]
        scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
        return tuple(item for _score, _is_directory, _length, _path, item in scored[: self.max_results])

    def _fd_recursive_items_for_prefix(
        self,
        parsed: _ParsedPathPrefix,
        raw_prefix: str,
        *,
        cancellation_token: CompletionCancellationToken | None = None,
    ) -> tuple[CompletionItem, ...] | None:
        if not parsed.is_at_prefix:
            return None
        if cancellation_token is not None and cancellation_token.cancelled:
            return ()
        fd_executable = _resolve_fd_path(self.fd_path)
        if fd_executable is None:
            return None

        base_path = Path(self.base_path)
        search_root, query, display_base = _split_recursive_search(raw_prefix, base_path=base_path)
        try:
            search_root = search_root.resolve(strict=True)
        except OSError:
            return None

        args = _fd_command_args(
            fd_executable,
            base_dir=search_root,
            query=query,
            include_hidden=self.include_hidden,
            exclude_names=self.exclude_names,
            respect_gitignore=self.respect_gitignore,
            max_results=max(1, min(self.max_scan_entries, max(self.max_results * 5, self.max_results))),
        )
        lines = _run_fd_command(
            args,
            timeout_seconds=self.fd_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        if lines is None:
            return None
        if cancellation_token is not None and cancellation_token.cancelled:
            return ()

        ignore_matcher = (
            _GitignoreMatcher.from_base_path(base_path) if self.respect_gitignore else _GitignoreMatcher.empty(base_path)
        )
        return _fd_completion_items(
            lines,
            search_root=search_root,
            display_base=display_base,
            query=query,
            parsed=parsed,
            max_results=self.max_results,
            include_hidden=self.include_hidden,
            exclude_names=self.exclude_names,
            ignore_matcher=ignore_matcher,
        )


@dataclass(frozen=True, slots=True)
class _ParsedPathPrefix:
    raw_prefix: str
    is_at_prefix: bool
    is_quoted_prefix: bool
    quote_char: str = '"'


@dataclass(frozen=True, slots=True)
class _GitignoreRule:
    pattern: str
    negated: bool = False
    directory_only: bool = False
    anchored: bool = False
    basename_only: bool = False


@dataclass(frozen=True, slots=True)
class _GitignoreMatcher:
    base_path: Path
    rules: tuple[_GitignoreRule, ...]

    @classmethod
    def from_base_path(cls, base_path: Path) -> _GitignoreMatcher:
        resolved_base_path = _resolve_ignore_base_path(base_path)
        gitignore_path = base_path / ".gitignore"
        try:
            lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return cls(resolved_base_path, ())
        return cls(resolved_base_path, _parse_gitignore_rules(lines))

    @classmethod
    def empty(cls, base_path: Path) -> _GitignoreMatcher:
        return cls(_resolve_ignore_base_path(base_path), ())

    def matches(self, path: Path, *, is_directory: bool) -> bool:
        if not self.rules:
            return False
        relative = _relative_ignore_path(path, base_path=self.base_path)
        ignored = False
        for rule in self.rules:
            if _gitignore_rule_matches(rule, relative, is_directory=is_directory):
                ignored = not rule.negated
        return ignored


def get_completion_suggestions(provider: Any, context: CompletionContext) -> CompletionSuggestions | None:
    if context.cancelled:
        return None
    get_suggestions = getattr(provider, "get_suggestions", None)
    if callable(get_suggestions):
        if _call_accepts_context(get_suggestions):
            return get_suggestions(context)
        kwargs: dict[str, Any] = {"force": context.force}
        if _call_accepts_keyword(get_suggestions, "cancellation_token"):
            kwargs["cancellation_token"] = context.cancellation_token
        if _call_accepts_keyword(get_suggestions, "explicit"):
            kwargs["explicit"] = context.explicit
        return get_suggestions(context.lines, context.cursor_line, context.cursor_col, **kwargs)

    complete = getattr(provider, "complete", None)
    if not callable(complete) or context.cursor_line < 0 or context.cursor_line >= len(context.lines):
        return None
    prefix = _word_prefix(context.lines[context.cursor_line][: context.cursor_col])
    if not prefix:
        return None
    if _call_accepts_keyword(complete, "context"):
        items = tuple(complete(prefix, context=context))
    else:
        items = tuple(complete(prefix))
    if not items:
        return None
    return CompletionSuggestions(prefix=prefix, items=items)


def _replace_prefix(
    lines: tuple[str, ...],
    cursor_line: int,
    cursor_col: int,
    value: str,
    prefix: str,
) -> CompletionApplication:
    current_line = lines[cursor_line]
    before = current_line[: max(0, cursor_col - len(prefix))]
    after = current_line[cursor_col:]
    new_lines = list(lines)
    new_lines[cursor_line] = f"{before}{value}{after}"
    return CompletionApplication(lines=tuple(new_lines), cursor_line=cursor_line, cursor_col=len(before) + len(value))


def _slash_prefix_before_cursor(line: str, cursor_col: int) -> str | None:
    text_before_cursor = line[:cursor_col]
    stripped = text_before_cursor.lstrip()
    if not stripped.startswith("/"):
        return None
    return stripped


def _split_slash_prefix(prefix: str) -> tuple[str, str | None]:
    body = prefix[1:]
    for index, value in enumerate(body):
        if value.isspace():
            return body[:index], body[index + 1 :].lstrip()
    return body, None


def _complete_argument_provider(
    provider: Any,
    argument_prefix: str,
    *,
    force: bool,
    cancellation_token: CompletionCancellationToken | None = None,
) -> tuple[CompletionItem, ...]:
    if cancellation_token is not None and cancellation_token.cancelled:
        return ()
    items = getattr(provider, "items", None)
    if items is not None:
        return tuple(
            item
            for item in tuple(items)
            if _argument_completion_matches(item, argument_prefix)
        )
    get_suggestions = getattr(provider, "get_suggestions", None)
    if callable(get_suggestions):
        suggestions = get_completion_suggestions(
            provider,
            CompletionContext(
                lines=(argument_prefix,),
                cursor_line=0,
                cursor_col=len(argument_prefix),
                force=force,
                cancellation_token=cancellation_token or CompletionCancellationToken(),
            ),
        )
        if suggestions is not None and suggestions.items:
            return tuple(suggestions.items)
    complete = getattr(provider, "complete", None)
    if callable(complete):
        return tuple(complete(argument_prefix))
    return ()


def _call_accepts_context(call: Any) -> bool:
    try:
        parameters = tuple(inspect.signature(call).parameters.values())
    except (TypeError, ValueError):
        return False
    if not parameters:
        return False
    first = parameters[0]
    return (
        first.name in {"context", "request"}
        and first.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    )


def _call_accepts_keyword(call: Any, keyword: str) -> bool:
    try:
        parameters = tuple(inspect.signature(call).parameters.values())
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == keyword
        for parameter in parameters
    )


def _slash_argument_completion_item(command_value: str, item: CompletionItem) -> CompletionItem:
    value = item.value if item.value.startswith(f"{command_value} ") else f"{command_value} {item.value}"
    return CompletionItem(value=value, label=item.display_label(), description=item.description)


def _argument_completion_matches(item: CompletionItem, argument_prefix: str) -> bool:
    argument = argument_prefix.lower().strip()
    if not argument:
        return True
    return _argument_matches_text(argument, item.value.lower()) or _argument_matches_text(
        argument,
        item.display_label().lower(),
    )


def _argument_matches_text(argument: str, text: str) -> bool:
    segments = [segment for segment in text.replace("/", " ").split() if segment]
    if any(segment.startswith(argument) for segment in segments):
        return True
    return len(argument) >= 3 and any(argument in segment for segment in segments)


def _slash_command_value(command: SlashCommand) -> str:
    return f"/{_normalize_slash_command_name(command.name)}"


def _slash_command_description(command: SlashCommand) -> str:
    if command.argument_hint and command.description:
        return f"{command.argument_hint} - {command.description}"
    return command.argument_hint or command.description


def _normalize_slash_command_name(name: str) -> str:
    return name.strip().removeprefix("/")


def _completion_match_score(needle: str, value: str, label: str) -> int | None:
    if not needle or needle == "/":
        return 300
    scores = (
        _candidate_match_score(needle, value),
        _candidate_match_score(needle, label),
        _candidate_match_score(_normalize_slash_command_name(needle), _normalize_slash_command_name(value)),
        _candidate_match_score(_normalize_slash_command_name(needle), _normalize_slash_command_name(label)),
    )
    return max((score for score in scores if score is not None), default=None)


def _candidate_match_score(needle: str, candidate: str) -> int | None:
    if not needle:
        return 300
    if candidate.startswith(needle):
        return 300 - len(candidate)
    initialism = _initialism_match_score(needle, candidate)
    if initialism is not None:
        return initialism
    index = candidate.find(needle)
    if index >= 0:
        return 220 - index - len(candidate)
    positions = _subsequence_positions(needle, candidate)
    if positions is None:
        return None
    span = positions[-1] - positions[0] + 1
    gaps = span - len(needle)
    return 120 - gaps - len(candidate)


def _initialism_match_score(needle: str, candidate: str) -> int | None:
    initials = "".join(part[:1] for part in candidate.replace("/", "-").replace("_", "-").split("-") if part)
    if not initials or not initials.startswith(needle):
        return None
    return 260 - len(candidate)


def _subsequence_positions(needle: str, candidate: str) -> tuple[int, ...] | None:
    positions: list[int] = []
    start = 0
    for char in needle:
        index = candidate.find(char, start)
        if index < 0:
            return None
        positions.append(index)
        start = index + 1
    return tuple(positions)


def _is_bare_slash_command_value(value: str) -> bool:
    return value.startswith("/") and " " not in value


def _slash_argument_closing_quote(prefix: str) -> str | None:
    _command_name, argument_prefix = _split_slash_prefix(prefix)
    if argument_prefix is None:
        return None
    return _closing_quote_for_prefix(argument_prefix)


def _word_prefix(text_before_cursor: str) -> str:
    start = len(text_before_cursor)
    while start > 0 and not text_before_cursor[start - 1].isspace():
        start -= 1
    return text_before_cursor[start:]


def _extract_at_prefix(text_before_cursor: str) -> str | None:
    quoted_prefix = _extract_quoted_prefix(text_before_cursor)
    if quoted_prefix is not None and quoted_prefix.startswith('@"'):
        return quoted_prefix
    token_start = _last_delimiter_index(text_before_cursor) + 1
    if token_start < len(text_before_cursor) and text_before_cursor[token_start] == "@":
        return text_before_cursor[token_start:]
    return None


def _extract_path_prefix(text_before_cursor: str, *, force: bool) -> str | None:
    quoted_prefix = _extract_quoted_prefix(text_before_cursor)
    if quoted_prefix is not None:
        return quoted_prefix
    token_start = _last_delimiter_index(text_before_cursor) + 1
    path_prefix = text_before_cursor[token_start:]
    if force:
        return path_prefix
    if "/" in path_prefix or path_prefix.startswith(".") or path_prefix.startswith("~/") or path_prefix == "~":
        return path_prefix
    return None


def _is_initial_absolute_path_token(text_before_cursor: str, prefix: str) -> bool:
    if not prefix.startswith("/"):
        return False
    token_start = len(text_before_cursor) - len(prefix)
    return not text_before_cursor[:token_start].strip()


def _extract_quoted_prefix(text_before_cursor: str) -> str | None:
    quote = _unclosed_quote(text_before_cursor)
    if quote is None:
        return None
    quote_start, _quote_char = quote
    if quote_start > 0 and text_before_cursor[quote_start - 1] == "@":
        token_start = quote_start - 1
        if not _is_token_start(text_before_cursor, token_start):
            return None
        return text_before_cursor[token_start:]
    if not _is_token_start(text_before_cursor, quote_start):
        return None
    return text_before_cursor[quote_start:]


def _unclosed_quote(text: str) -> tuple[int, str] | None:
    quote_char: str | None = None
    quote_start = -1
    for index, value in enumerate(text):
        if value not in {'"', "'"}:
            continue
        if quote_char is None:
            quote_char = value
            quote_start = index
            continue
        if value == quote_char:
            quote_char = None
            quote_start = -1
    if quote_char is None:
        return None
    return quote_start, quote_char


def _last_delimiter_index(text: str) -> int:
    for index in range(len(text) - 1, -1, -1):
        if text[index] in _PATH_DELIMITERS:
            return index
    return -1


def _is_token_start(text: str, index: int) -> bool:
    return index == 0 or text[index - 1] in _PATH_DELIMITERS


def _parse_path_prefix(prefix: str) -> _ParsedPathPrefix:
    if prefix.startswith('@"'):
        return _ParsedPathPrefix(raw_prefix=prefix[2:], is_at_prefix=True, is_quoted_prefix=True, quote_char='"')
    if prefix.startswith("@'"):
        return _ParsedPathPrefix(raw_prefix=prefix[2:], is_at_prefix=True, is_quoted_prefix=True, quote_char="'")
    if prefix.startswith('"'):
        return _ParsedPathPrefix(raw_prefix=prefix[1:], is_at_prefix=False, is_quoted_prefix=True, quote_char='"')
    if prefix.startswith("'"):
        return _ParsedPathPrefix(raw_prefix=prefix[1:], is_at_prefix=False, is_quoted_prefix=True, quote_char="'")
    if prefix.startswith("@"):
        return _ParsedPathPrefix(raw_prefix=prefix[1:], is_at_prefix=True, is_quoted_prefix=False)
    return _ParsedPathPrefix(raw_prefix=prefix, is_at_prefix=False, is_quoted_prefix=False)


def _split_search(raw_prefix: str, *, base_path: Path) -> tuple[Path, str, str]:
    if raw_prefix in {"", ".", "./"}:
        return base_path, "", "./" if raw_prefix.startswith(".") else ""
    if raw_prefix in {"~", "~/"}:
        return Path.home(), "", "~/"
    if raw_prefix == "/":
        return Path("/"), "", "/"
    if raw_prefix.endswith("/"):
        return _resolve_search_dir(raw_prefix, base_path=base_path), "", raw_prefix

    slash_index = raw_prefix.rfind("/")
    if slash_index >= 0:
        display_base = raw_prefix[: slash_index + 1]
        search_prefix = raw_prefix[slash_index + 1 :]
        search_dir = _resolve_search_dir(display_base, base_path=base_path)
        return search_dir, search_prefix, display_base
    return base_path, raw_prefix, ""


def _split_recursive_search(raw_prefix: str, *, base_path: Path) -> tuple[Path, str, str]:
    if raw_prefix.startswith("~/"):
        raw_without_home = raw_prefix[2:]
        slash_index = raw_without_home.rfind("/")
        if slash_index >= 0:
            display_base = f"~/{raw_without_home[: slash_index + 1]}"
            return Path.home() / raw_without_home[: slash_index + 1], raw_without_home[slash_index + 1 :], display_base
        return Path.home(), raw_without_home, "~/"
    if raw_prefix.startswith("/"):
        slash_index = raw_prefix.rfind("/")
        if slash_index > 0:
            display_base = raw_prefix[: slash_index + 1]
            return Path(display_base), raw_prefix[slash_index + 1 :], display_base
        return Path("/"), raw_prefix.lstrip("/"), "/"
    slash_index = raw_prefix.rfind("/")
    if slash_index >= 0:
        display_base = raw_prefix[: slash_index + 1]
        return _resolve_search_dir(display_base, base_path=base_path), raw_prefix[slash_index + 1 :], display_base
    return base_path, raw_prefix, ""


def _resolve_search_dir(raw_dir: str, *, base_path: Path) -> Path:
    if raw_dir in {"", ".", "./"}:
        return base_path
    if raw_dir == "~" or raw_dir == "~/":
        return Path.home()
    if raw_dir.startswith("~/"):
        return Path.home() / raw_dir[2:]
    candidate = Path(raw_dir)
    if candidate.is_absolute():
        return candidate
    return base_path / candidate


def _parse_gitignore_rules(lines: Sequence[str]) -> tuple[_GitignoreRule, ...]:
    rules: list[_GitignoreRule] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:].strip()
            if not line:
                continue
        directory_only = line.endswith("/")
        if directory_only:
            line = line.rstrip("/")
        anchored = line.startswith("/")
        if anchored:
            line = line.lstrip("/")
        if not line:
            continue
        basename_only = "/" not in line
        rules.append(
            _GitignoreRule(
                pattern=_to_display_path(line),
                negated=negated,
                directory_only=directory_only,
                anchored=anchored,
                basename_only=basename_only,
            )
        )
    return tuple(rules)


def _resolve_ignore_base_path(base_path: Path) -> Path:
    try:
        return base_path.resolve(strict=False)
    except OSError:
        return base_path


def _relative_ignore_path(path: Path, *, base_path: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(base_path)
    except (OSError, ValueError):
        try:
            relative = path.relative_to(base_path)
        except ValueError:
            return _to_display_path(path.as_posix().lstrip("/"))
    return _to_display_path(relative.as_posix())


def _gitignore_rule_matches(rule: _GitignoreRule, relative: str, *, is_directory: bool) -> bool:
    if rule.basename_only:
        return _basename_rule_matches(rule, relative, is_directory=is_directory)
    if rule.anchored:
        return _path_rule_matches(rule, relative)
    return _path_rule_matches(rule, relative) or fnmatch(relative, f"*/{rule.pattern}")


def _basename_rule_matches(rule: _GitignoreRule, relative: str, *, is_directory: bool) -> bool:
    segments = [segment for segment in relative.split("/") if segment]
    for index, segment in enumerate(segments):
        if not fnmatch(segment, rule.pattern):
            continue
        if not rule.directory_only:
            return True
        is_last_segment = index == len(segments) - 1
        if not is_last_segment or is_directory:
            return True
    return False


def _path_rule_matches(rule: _GitignoreRule, relative: str) -> bool:
    pattern = rule.pattern
    return fnmatch(relative, pattern) or relative.startswith(f"{pattern}/")


def _join_display_path(display_base: str, name: str) -> str:
    if not display_base:
        return name
    if display_base == "/":
        return f"/{name}"
    return f"{display_base}{name}"


def _iter_recursive_entries(
    root: Path,
    *,
    include_hidden: bool,
    exclude_names: tuple[str, ...],
    ignore_matcher: _GitignoreMatcher,
    max_entries: int,
) -> tuple[Path, ...]:
    entries: list[Path] = []
    stack = [root]
    while stack and len(entries) < max_entries:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))
        except OSError:
            continue
        for child in reversed(children):
            if len(entries) >= max_entries:
                break
            if child.name in exclude_names:
                continue
            child_is_dir = child.is_dir()
            if ignore_matcher.matches(child, is_directory=child_is_dir):
                continue
            if not include_hidden and child.name.startswith("."):
                continue
            entries.append(child)
            if child_is_dir:
                stack.append(child)
    return tuple(entries)


def _resolve_fd_path(fd_path: str | Path | None) -> str | None:
    if fd_path is None:
        return None
    value = str(fd_path)
    if value == _AUTO_FD_PATH:
        return shutil.which("fd") or shutil.which("fdfind")
    path = Path(value)
    if path.is_absolute() or path.parent != Path("."):
        return value if path.exists() else None
    return shutil.which(value)


def _fd_command_args(
    fd_executable: str,
    *,
    base_dir: Path,
    query: str,
    include_hidden: bool,
    exclude_names: tuple[str, ...],
    respect_gitignore: bool,
    max_results: int,
) -> list[str]:
    args = [
        fd_executable,
        "--base-directory",
        str(base_dir),
        "--max-results",
        str(max_results),
        "--type",
        "f",
        "--type",
        "d",
        "--follow",
        "--color",
        "never",
    ]
    if include_hidden:
        args.append("--hidden")
    if not respect_gitignore:
        args.append("--no-ignore")
    for name in exclude_names:
        args.extend(["--exclude", name, "--exclude", f"{name}/*", "--exclude", f"{name}/**"])
    if query:
        args.append(_fd_path_query(query))
    return args


def _fd_path_query(query: str) -> str:
    normalized = _to_display_path(query).strip("/")
    if not normalized:
        return ""
    segments = [re.escape(segment) for segment in normalized.split("/") if segment]
    return r"[\\/]".join(segments)


def _run_fd_command(
    args: list[str],
    *,
    timeout_seconds: float,
    cancellation_token: CompletionCancellationToken | None,
) -> tuple[str, ...] | None:
    if cancellation_token is not None and cancellation_token.cancelled:
        return ()
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except OSError:
        return None

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while process.poll() is None:
        if cancellation_token is not None and cancellation_token.cancelled:
            _kill_process(process)
            return ()
        if time.monotonic() >= deadline:
            _kill_process(process)
            return None
        time.sleep(0.005)

    stdout, _stderr = process.communicate()
    if process.returncode != 0:
        return None
    return tuple(line.strip() for line in stdout.splitlines() if line.strip())


def _kill_process(process: subprocess.Popen[str]) -> None:
    try:
        process.kill()
        process.communicate(timeout=0.1)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _fd_completion_items(
    lines: tuple[str, ...],
    *,
    search_root: Path,
    display_base: str,
    query: str,
    parsed: _ParsedPathPrefix,
    max_results: int,
    include_hidden: bool,
    exclude_names: tuple[str, ...],
    ignore_matcher: _GitignoreMatcher,
) -> tuple[CompletionItem, ...]:
    scored: list[tuple[int, bool, int, str, CompletionItem]] = []
    for line in lines:
        relative_path = _to_display_path(line).removeprefix("./")
        has_trailing_separator = relative_path.endswith("/")
        relative_path = relative_path.rstrip("/")
        if not relative_path:
            continue
        if _path_has_excluded_segment(relative_path, exclude_names):
            continue
        if not include_hidden and _path_has_hidden_segment(relative_path):
            continue

        entry_path = search_root / relative_path
        is_directory = has_trailing_separator or entry_path.is_dir()
        if ignore_matcher.matches(entry_path, is_directory=is_directory):
            continue

        display_path = _join_display_path(display_base, relative_path)
        if is_directory:
            display_path = f"{display_path}/"
        name = PurePosixPath(relative_path).name
        score = _fuzzy_path_score(query, display_path, name, is_directory=is_directory)
        if score <= 0:
            continue
        value = _build_completion_value(
            display_path,
            is_at_prefix=parsed.is_at_prefix,
            is_quoted_prefix=parsed.is_quoted_prefix,
            quote_char=parsed.quote_char,
        )
        label = f"{name}/" if is_directory else name
        scored.append(
            (
                score,
                is_directory,
                len(display_path.rstrip("/")),
                display_path.lower(),
                CompletionItem(value=value, label=label, description=display_path),
            )
        )

    strong_scores = [score for score, _is_directory, _length, _path, _item in scored if score >= _STRONG_PATH_MATCH_SCORE]
    if strong_scores:
        scored = [item for item in scored if item[0] >= _STRONG_PATH_MATCH_SCORE]
    scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    return tuple(item for _score, _is_directory, _length, _path, item in scored[:max_results])


def _path_has_excluded_segment(path: str, exclude_names: tuple[str, ...]) -> bool:
    excluded = set(exclude_names)
    return any(segment in excluded for segment in path.split("/") if segment)


def _path_has_hidden_segment(path: str) -> bool:
    return any(segment.startswith(".") for segment in path.split("/") if segment)


def _fuzzy_path_score(query: str, display_path: str, name: str, *, is_directory: bool) -> int:
    normalized_query = query.lower().strip()
    normalized_path = display_path.lower()
    normalized_name = name.lower()
    if not normalized_query:
        score = 10
    elif normalized_name == normalized_query:
        score = 110
    elif not is_directory and _file_stem(normalized_name) == normalized_query:
        score = 105
    elif normalized_name.startswith(normalized_query):
        score = 100
    elif normalized_path.startswith(normalized_query):
        score = 80
    elif normalized_query in normalized_path:
        score = 60
    elif _is_subsequence(normalized_query, normalized_path):
        score = 30
    else:
        return 0
    return max(1, score - 10) if is_directory else score


def _file_stem(name: str) -> str:
    if "." not in name:
        return name
    return name.rsplit(".", 1)[0]


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    iterator = iter(haystack)
    return all(char in iterator for char in needle)


def _build_completion_value(path: str, *, is_at_prefix: bool, is_quoted_prefix: bool, quote_char: str = '"') -> str:
    needs_quotes = is_quoted_prefix or " " in path
    prefix = "@" if is_at_prefix else ""
    if not needs_quotes:
        return f"{prefix}{path}"
    quote = quote_char if is_quoted_prefix and quote_char in {'"', "'"} else '"'
    return f"{prefix}{quote}{path}{quote}"


def _is_quoted_prefix(prefix: str) -> bool:
    return prefix.startswith(('"', "'", '@"', "@'"))


def _closing_quote_for_prefix(prefix: str) -> str | None:
    if prefix.startswith('@"') or prefix.startswith('"'):
        return '"'
    if prefix.startswith("@'") or prefix.startswith("'"):
        return "'"
    return None


def _ends_with_quote(value: str) -> bool:
    return value.endswith('"') or value.endswith("'")


def _to_display_path(value: str) -> str:
    return value.replace("\\", "/")


__all__ = [
    "CombinedCompletionProvider",
    "CompletionCancellationToken",
    "CompletionContext",
    "PathCompletionProvider",
    "SlashCommand",
    "SlashCommandCompletionProvider",
    "get_completion_suggestions",
]
