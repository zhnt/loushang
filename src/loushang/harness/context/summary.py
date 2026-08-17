from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TAG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class SummarySection:
    heading: str
    required: bool = True

    def __post_init__(self) -> None:
        if not self.heading.strip():
            raise ValueError("summary section heading must not be empty")


@dataclass(frozen=True)
class SummaryResourceOperationTag:
    """Maps a summary XML block tag to a product-neutral resource operation."""

    operation: str
    tag: str

    def __post_init__(self) -> None:
        operation = self.operation.strip()
        if not operation:
            raise ValueError("summary resource operation must not be empty")
        if not _TAG_RE.fullmatch(self.tag):
            raise ValueError(f"invalid summary resource operation tag: {self.tag!r}")
        object.__setattr__(self, "operation", operation)


STANDARD_SUMMARY_RESOURCE_OPERATION_TAGS = (
    SummaryResourceOperationTag(operation="read", tag="read-files"),
    SummaryResourceOperationTag(operation="modified", tag="modified-files"),
)


@dataclass(frozen=True)
class SummaryProfile:
    profile_id: str
    system_prompt: str
    prompts: Mapping[str, str]
    sections: tuple[SummarySection, ...] = ()
    placeholder_markers: tuple[str, ...] = ()
    ignored_block_tags: tuple[str, ...] = ()
    resource_operation_tags: tuple[SummaryResourceOperationTag, ...] = ()
    content_tag: str = "conversation"
    previous_summary_tag: str = "previous-summary"
    custom_instruction_label: str = "Additional focus"

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("summary profile id must not be empty")
        prompts = dict(self.prompts)
        if not prompts:
            raise ValueError("summary profile must define at least one prompt")
        if any(
            not mode.strip() or not prompt.strip() for mode, prompt in prompts.items()
        ):
            raise ValueError("summary profile modes and prompts must not be empty")
        headings = [_normalize_heading(section.heading) for section in self.sections]
        if len(headings) != len(set(headings)):
            raise ValueError("summary profile section headings must be unique")
        if any(
            not isinstance(resource_tag, SummaryResourceOperationTag)
            for resource_tag in self.resource_operation_tags
        ):
            raise TypeError(
                "summary profile resource operation tags must be "
                "SummaryResourceOperationTag values"
            )
        for tag in (
            self.content_tag,
            self.previous_summary_tag,
            *self.ignored_block_tags,
            *(resource_tag.tag for resource_tag in self.resource_operation_tags),
        ):
            if not _TAG_RE.fullmatch(tag):
                raise ValueError(f"invalid summary block tag: {tag!r}")
        resource_tag_names = tuple(
            resource_tag.tag for resource_tag in self.resource_operation_tags
        )
        if len(resource_tag_names) != len(set(resource_tag_names)):
            raise ValueError("summary resource operation tags must be unique")
        object.__setattr__(self, "prompts", prompts)
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(
            self,
            "placeholder_markers",
            tuple(marker.lower() for marker in self.placeholder_markers),
        )
        object.__setattr__(self, "ignored_block_tags", tuple(self.ignored_block_tags))
        object.__setattr__(
            self,
            "resource_operation_tags",
            tuple(self.resource_operation_tags),
        )

    def prompt(self, mode: str) -> str:
        try:
            return self.prompts[mode]
        except KeyError as exc:
            raise KeyError(
                f"Summary profile {self.profile_id!r} has no mode {mode!r}"
            ) from exc


@dataclass(frozen=True)
class SummaryPrompt:
    profile_id: str
    mode: str
    system_prompt: str
    user_prompt: str


@dataclass(frozen=True)
class SummaryValidationReport:
    profile_id: str
    missing_sections: tuple[str, ...] = ()
    empty_sections: tuple[str, ...] = ()
    placeholder_sections: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (
            self.missing_sections or self.empty_sections or self.placeholder_sections
        )


def build_summary_prompt(
    profile: SummaryProfile,
    content: str,
    *,
    mode: str,
    previous_summary: str | None = None,
    custom_instructions: str | None = None,
    prompt_override: str | None = None,
) -> SummaryPrompt:
    instructions = profile.prompt(mode) if prompt_override is None else prompt_override
    return SummaryPrompt(
        profile_id=profile.profile_id,
        mode=mode,
        system_prompt=profile.system_prompt,
        user_prompt=compose_summary_prompt(
            content=content,
            instructions=instructions,
            previous_summary=previous_summary,
            custom_instructions=custom_instructions,
            content_tag=profile.content_tag,
            previous_summary_tag=profile.previous_summary_tag,
            custom_instruction_label=profile.custom_instruction_label,
        ),
    )


def compose_summary_prompt(
    *,
    content: str,
    instructions: str,
    previous_summary: str | None = None,
    custom_instructions: str | None = None,
    content_tag: str = "conversation",
    previous_summary_tag: str = "previous-summary",
    custom_instruction_label: str = "Additional focus",
) -> str:
    for tag in (content_tag, previous_summary_tag):
        if not _TAG_RE.fullmatch(tag):
            raise ValueError(f"invalid summary block tag: {tag!r}")

    prompt = instructions
    if custom_instructions:
        prompt = f"{prompt}\n\n{custom_instruction_label}: {custom_instructions}"

    blocks = [f"<{content_tag}>\n{content}\n</{content_tag}>"]
    if previous_summary:
        blocks.append(
            f"<{previous_summary_tag}>\n{previous_summary}\n</{previous_summary_tag}>"
        )
    return "\n\n".join((*blocks, prompt))


def validate_summary(
    summary: str | None,
    profile: SummaryProfile,
) -> SummaryValidationReport:
    sections = _section_contents(
        summary or "",
        ignored_block_tags=(
            *profile.ignored_block_tags,
            *(resource_tag.tag for resource_tag in profile.resource_operation_tags),
        ),
    )
    required_sections = tuple(
        section.heading for section in profile.sections if section.required
    )
    missing = tuple(
        heading
        for heading in required_sections
        if _normalize_heading(heading) not in sections
    )
    empty = tuple(
        heading
        for heading in required_sections
        if _normalize_heading(heading) in sections
        and not sections[_normalize_heading(heading)].strip()
    )
    placeholders = tuple(
        heading
        for heading in required_sections
        if _normalize_heading(heading) in sections
        and _has_placeholder_content(
            sections[_normalize_heading(heading)],
            profile.placeholder_markers,
        )
    )
    return SummaryValidationReport(
        profile_id=profile.profile_id,
        missing_sections=missing,
        empty_sections=empty,
        placeholder_sections=placeholders,
    )


def _section_contents(
    summary: str,
    *,
    ignored_block_tags: tuple[str, ...],
) -> dict[str, str]:
    text = _strip_ignored_blocks(summary, ignored_block_tags)
    matches = list(_SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = _normalize_heading(match.group(1))
        sections.setdefault(heading, text[start:end].strip())
    return sections


def _strip_ignored_blocks(summary: str, tags: tuple[str, ...]) -> str:
    if not tags:
        return summary
    alternatives = "|".join(re.escape(tag) for tag in tags)
    block_re = re.compile(
        rf"\n*<(?P<tag>{alternatives})>.*?</(?P=tag)>\s*",
        re.DOTALL,
    )
    return block_re.sub("\n", summary)


def _normalize_heading(heading: str) -> str:
    return " ".join(heading.strip().lower().split())


def _has_placeholder_content(content: str, markers: tuple[str, ...]) -> bool:
    lower = content.lower()
    return any(marker in lower for marker in markers)


__all__ = [
    "STANDARD_SUMMARY_RESOURCE_OPERATION_TAGS",
    "SummaryProfile",
    "SummaryPrompt",
    "SummaryResourceOperationTag",
    "SummarySection",
    "SummaryValidationReport",
    "build_summary_prompt",
    "compose_summary_prompt",
    "validate_summary",
]
