from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Literal, TypeAlias

PromptArgumentParser: TypeAlias = Callable[[str], Sequence[str]]
PromptPlaceholderProbe: TypeAlias = Callable[[str], bool]
PromptTemplateSubstituter: TypeAlias = Callable[[str, Sequence[str]], str]
PromptArgumentAppender: TypeAlias = Callable[[str, str], str]

_PLACEHOLDER_PATTERN = re.compile(r"\$\{@:(\d+)(?::(\d+))?\}|\$ARGUMENTS|\$@|\$(\d+)")


@dataclass(frozen=True)
class PromptSection:
    """One product-supplied section in an ordered prepared prompt."""

    section_id: str
    text: str
    kind: str = "instruction"
    source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.section_id, str) or not self.section_id.strip():
            raise ValueError("prompt section id must be a non-empty string")
        if not isinstance(self.text, str):
            raise TypeError("prompt section text must be a string")
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("prompt section kind must be a non-empty string")
        if self.source is not None and not isinstance(self.source, str):
            raise TypeError("prompt section source must be a string or None")


@dataclass(frozen=True)
class PromptTraceEntry:
    section_id: str
    kind: str
    input_index: int
    output_index: int | None
    included: bool
    reason: Literal["empty"] | None = None


@dataclass(frozen=True)
class PreparedPrompt:
    text: str
    sections: tuple[PromptSection, ...] = ()
    trace: tuple[PromptTraceEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("prepared prompt text must be a string")
        object.__setattr__(
            self,
            "sections",
            _tuple_input(self.sections, name="prepared prompt sections"),
        )
        object.__setattr__(
            self,
            "trace",
            _tuple_input(self.trace, name="prepared prompt trace"),
        )


@dataclass(frozen=True)
class PromptSectionComposer:
    """A selectable, pure prompt-section composition implementation."""

    separator: str = "\n\n"
    strip_sections: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.separator, str):
            raise TypeError("prompt section separator must be a string")
        if type(self.strip_sections) is not bool:
            raise TypeError("prompt section strip_sections must be a bool")

    def compose(self, sections: Iterable[PromptSection]) -> PreparedPrompt:
        return compose_prompt_sections(
            sections,
            separator=self.separator,
            strip_sections=self.strip_sections,
        )


def compose_prompt_sections(
    sections: Iterable[PromptSection],
    *,
    separator: str = "\n\n",
    strip_sections: bool = True,
) -> PreparedPrompt:
    """Compose sections in caller order and retain a deterministic trace."""

    if isinstance(sections, str | bytes):
        raise TypeError("prompt sections must be an iterable of PromptSection values")
    if not isinstance(separator, str):
        raise TypeError("prompt section separator must be a string")

    included: list[PromptSection] = []
    trace: list[PromptTraceEntry] = []
    for input_index, section in enumerate(sections):
        if not isinstance(section, PromptSection):
            raise TypeError("prompt sections must contain PromptSection values")
        text = section.text.strip() if strip_sections else section.text
        if not text:
            trace.append(
                PromptTraceEntry(
                    section_id=section.section_id,
                    kind=section.kind,
                    input_index=input_index,
                    output_index=None,
                    included=False,
                    reason="empty",
                )
            )
            continue
        normalized = section if text == section.text else replace(section, text=text)
        output_index = len(included)
        included.append(normalized)
        trace.append(
            PromptTraceEntry(
                section_id=section.section_id,
                kind=section.kind,
                input_index=input_index,
                output_index=output_index,
                included=True,
            )
        )
    return PreparedPrompt(
        text=separator.join(section.text for section in included),
        sections=tuple(included),
        trace=tuple(trace),
    )


@dataclass(frozen=True)
class PromptTemplateExpander:
    """Injectable prompt-template argument parsing and expansion policy."""

    parse_arguments: PromptArgumentParser = lambda value: parse_prompt_template_args(
        value
    )
    has_placeholders: PromptPlaceholderProbe = lambda value: prompt_template_has_args(
        value
    )
    substitute: PromptTemplateSubstituter = lambda content, arguments: (
        substitute_prompt_template_args(content, arguments)
    )
    append_arguments: PromptArgumentAppender = lambda content, arguments: (
        append_prompt_arguments(content, arguments)
    )

    def expand(self, content: str, raw_arguments: str) -> str:
        if not raw_arguments:
            return content
        if not self.has_placeholders(content):
            return self.append_arguments(content, raw_arguments)
        parsed = self.parse_arguments(raw_arguments)
        if isinstance(parsed, str | bytes):
            raise TypeError("prompt argument parser must return a sequence of strings")
        arguments = tuple(parsed)
        if any(not isinstance(argument, str) for argument in arguments):
            raise TypeError("prompt arguments must be strings")
        return self.substitute(content, arguments)


DEFAULT_PROMPT_TEMPLATE_EXPANDER = PromptTemplateExpander()


def expand_prompt_template(
    content: str,
    raw_arguments: str,
    *,
    expander: PromptTemplateExpander = DEFAULT_PROMPT_TEMPLATE_EXPANDER,
) -> str:
    return expander.expand(content, raw_arguments)


def parse_prompt_template_args(args_string: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    in_quote: str | None = None

    for char in args_string:
        if in_quote is not None:
            if char == in_quote:
                in_quote = None
            else:
                current.append(char)
            continue
        if char in {"'", '"'}:
            in_quote = char
            continue
        if char in {" ", "\t"}:
            if current:
                args.append("".join(current))
                current = []
            continue
        current.append(char)

    if current:
        args.append("".join(current))
    return args


def prompt_template_has_args(content: str) -> bool:
    return _PLACEHOLDER_PATTERN.search(content) is not None


def substitute_prompt_template_args(content: str, args: Sequence[str]) -> str:
    all_args = " ".join(args)

    def replace_argument(match: re.Match[str]) -> str:
        positional = match.group(3)
        if positional is not None:
            index = int(positional) - 1
            return args[index] if 0 <= index < len(args) else ""

        slice_start = match.group(1)
        if slice_start is not None:
            start = max(0, int(slice_start) - 1)
            length = match.group(2)
            if length is not None:
                return " ".join(args[start : start + int(length)])
            return " ".join(args[start:])
        return all_args

    return _PLACEHOLDER_PATTERN.sub(replace_argument, content)


def append_prompt_arguments(content: str, arguments: str) -> str:
    if not arguments:
        return content
    return f"{content}\n\n{arguments}"


def _tuple_input(values: Iterable[object], *, name: str) -> tuple:
    if isinstance(values, str | bytes):
        raise TypeError(f"{name} must be an iterable, not a string")
    return tuple(values)


__all__ = [
    "DEFAULT_PROMPT_TEMPLATE_EXPANDER",
    "PreparedPrompt",
    "PromptArgumentAppender",
    "PromptArgumentParser",
    "PromptPlaceholderProbe",
    "PromptSectionComposer",
    "PromptSection",
    "PromptTemplateExpander",
    "PromptTemplateSubstituter",
    "PromptTraceEntry",
    "append_prompt_arguments",
    "compose_prompt_sections",
    "expand_prompt_template",
    "parse_prompt_template_args",
    "prompt_template_has_args",
    "substitute_prompt_template_args",
]
