"""Profile-driven transcript presentation for conversation screens."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Protocol, TypeVar

from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_frame import (
    ScreenFrameCopy,
    ScreenFramePresentation,
)
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
    ErrorRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)

ContextT = TypeVar("ContextT", bound=Hashable)
ContextT_contra = TypeVar("ContextT_contra", bound=Hashable, contravariant=True)


class TranscriptRecordProjector(Protocol[ContextT_contra]):
    """Project one record using product-prepared presentation context."""

    def __call__(
        self,
        record: DisplayRecord,
        *,
        context: ContextT_contra,
    ) -> DisplayRecord: ...


class TranscriptRecordWidth(Protocol):
    """Choose the record render width without owning terminal layout."""

    def __call__(self, record: DisplayRecord, *, width: int) -> int: ...


class TranscriptLineStyler(Protocol):
    """Apply product-selected styling to one presentation-ready line."""

    def __call__(
        self,
        line: str,
        record: DisplayRecord,
        *,
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> str: ...


class WelcomePanelFactory(Protocol):
    """Build the product's startup panel from neutral screen state."""

    def __call__(
        self,
        state: ScreenConversationState,
        *,
        theme: ThemeResolver | None,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class ConversationTranscriptCopy:
    """Product-owned glyphs and rails applied to neutral transcript lines."""

    user_prompt_prefix: str
    assistant_prefix: str
    error_prefix: str
    context_compaction_prefix: str
    tool_success_prefix: str
    tool_error_prefix: str
    worked_divider: str
    tool_command_prefix: str
    tool_first_output_prefix: str
    tool_continuation_prefix: str


@dataclass(frozen=True, slots=True)
class ConversationTranscriptPresentationProfile(Generic[ContextT]):
    """Immutable product policy consumed by the shared presentation owner."""

    copy: ConversationTranscriptCopy
    project_record: TranscriptRecordProjector[ContextT]
    record_render_width: TranscriptRecordWidth
    style_line: TranscriptLineStyler


@dataclass(slots=True)
class ProfiledConversationTranscriptPresentation(Generic[ContextT]):
    """Implement ``TranscriptPresentation`` without owning product policy.

    The profile is allocated once with the product binding. ``context`` is the
    only mutable value and also serves as the render-cache token, preserving
    cached record and streaming-segment behavior when product context changes.
    """

    profile: ConversationTranscriptPresentationProfile[ContextT]
    context: ContextT

    @property
    def cache_token(self) -> ContextT:
        return self.context

    def project_record(self, record: DisplayRecord) -> DisplayRecord:
        return self.profile.project_record(record, context=self.context)

    def record_render_width(
        self,
        record: DisplayRecord,
        *,
        width: int,
    ) -> int:
        return self.profile.record_render_width(record, width=width)

    def present_lines(
        self,
        lines: tuple[str, ...],
        record: DisplayRecord,
        *,
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> tuple[str, ...]:
        if not isinstance(record, ToolExecutionRecord):
            return tuple(
                self._present_line(
                    line,
                    record,
                    theme=theme,
                    capabilities=capabilities,
                )
                for line in lines
            )

        rendered: list[str] = []
        output_started = False
        for line in lines:
            if line.startswith("- Ran ") or line.startswith("! Ran "):
                presented = line
            elif line.startswith("  $ "):
                presented = self.profile.copy.tool_command_prefix + line[2:]
            elif line.startswith("  "):
                presented = (
                    self.profile.copy.tool_first_output_prefix
                    if not output_started
                    else self.profile.copy.tool_continuation_prefix
                ) + line[2:]
                output_started = True
            else:
                presented = line
            rendered.append(
                self._present_line(
                    presented,
                    record,
                    theme=theme,
                    capabilities=capabilities,
                )
            )
        return tuple(rendered)

    def _present_line(
        self,
        line: str,
        record: DisplayRecord,
        *,
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> str:
        copy = self.profile.copy
        if isinstance(record, UserPromptRecord) and line.startswith("> "):
            line = copy.user_prompt_prefix + line[2:]
        elif isinstance(record, AssistantMessageRecord) and line.startswith("* "):
            line = copy.assistant_prefix + line[2:]
        elif isinstance(record, ErrorRecord) and line.startswith("! Error: "):
            line = copy.error_prefix + line[len("! Error: ") :]
        elif isinstance(record, ContextCompactionRecord) and line.startswith("* "):
            line = copy.context_compaction_prefix + line[2:]
        elif isinstance(record, ToolExecutionRecord):
            if line.startswith("- Ran "):
                line = copy.tool_success_prefix + line[len("- Ran ") :]
            elif line.startswith("! Ran "):
                line = copy.tool_error_prefix + line[len("! Ran ") :]
        elif isinstance(record, WorkedDividerRecord) and line.startswith(
            "- Worked for "
        ):
            line = line.replace("-", copy.worked_divider)
        return self.profile.style_line(
            line,
            record,
            theme=theme,
            capabilities=capabilities,
        )


@dataclass(frozen=True, slots=True)
class ScreenConversationPresentationProfile(Generic[ContextT]):
    """Bind transcript, frame, and welcome presentation to a screen shell."""

    transcript: ConversationTranscriptPresentationProfile[ContextT]
    transcript_context: Callable[[ScreenConversationState], ContextT]
    frame_copy: ScreenFrameCopy
    welcome_panel: WelcomePanelFactory


class ProfiledScreenConversationApp(ScreenConversationApp):
    """Reusable screen app binding driven by one immutable product profile."""

    screen_presentation_profile: ClassVar[ScreenConversationPresentationProfile[Any]]
    _transcript_presentation: ProfiledConversationTranscriptPresentation[Any]

    def _create_transcript_presentation(
        self,
    ) -> ProfiledConversationTranscriptPresentation[Any]:
        profile = self.screen_presentation_profile
        return ProfiledConversationTranscriptPresentation(
            profile=profile.transcript,
            context=profile.transcript_context(self.state),
        )

    def _create_frame_presentation(self) -> ScreenFramePresentation:
        return ScreenFramePresentation(self.screen_presentation_profile.frame_copy)

    def _prepare_transcript_presentation(self) -> None:
        profile = self.screen_presentation_profile
        self._transcript_presentation.context = profile.transcript_context(self.state)

    def startup_welcome_panel(self) -> Any:
        return self.screen_presentation_profile.welcome_panel(
            self.state,
            theme=self.welcome_theme,
        )


__all__ = [
    "ConversationTranscriptCopy",
    "ConversationTranscriptPresentationProfile",
    "ProfiledConversationTranscriptPresentation",
    "ProfiledScreenConversationApp",
    "ScreenConversationPresentationProfile",
    "TranscriptLineStyler",
    "TranscriptRecordProjector",
    "TranscriptRecordWidth",
    "WelcomePanelFactory",
]
