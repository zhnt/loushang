from __future__ import annotations

from loushang.harness.context import (
    STANDARD_SUMMARY_RESOURCE_OPERATION_TAGS,
    SummaryProfile,
    SummarySection,
)

COMPACTION_SYSTEM_PROMPT = """Summarize the older conversation context for later continuation.

Preserve:
- the user's goal
- important constraints and decisions
- meaningful work already completed
- open questions and unresolved risks
"""

SUMMARIZATION_SYSTEM_PROMPT = """You are a context summarization assistant. Your task is to read a conversation between a user and an AI coding assistant, then produce a structured summary following the exact format specified.

Do NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary."""

SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

UPDATE_SUMMARIZATION_PROMPT = """The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

Use this EXACT format:

## Goal
[Preserve existing goals, add new ones if the task expanded]

## Constraints & Preferences
- [Preserve existing, add new ones discovered]

## Progress
### Done
- [x] [Include previously done items AND newly completed items]

### In Progress
- [ ] [Current work - update based on progress]

### Blocked
- [Current blockers - remove if resolved]

## Key Decisions
- **[Decision]**: [Brief rationale] (preserve all previous, add new)

## Next Steps
1. [Update based on current state]

## Critical Context
- [Preserve important context, add new if needed]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

TURN_PREFIX_SUMMARIZATION_PROMPT = """This is the PREFIX of a turn that was too large to keep. The SUFFIX (recent work) is retained.

Summarize the prefix to provide context for the retained suffix:

## Original Request
[What did the user ask for in this turn?]

## Early Progress
- [Key decisions and work done in the prefix]

## Context for Suffix
- [Information needed to understand the retained recent work]

Be concise. Focus on what's needed to understand the kept suffix."""

BRANCH_SUMMARY_PROMPT = """Create a structured summary of this conversation branch for context when returning later.

Use this EXACT format:

## Goal
[What was the user trying to accomplish in this branch?]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Work that was started but not finished]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [What should happen next to continue this work]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

_COMPACTION_SECTIONS = (
    SummarySection("Goal"),
    SummarySection("Constraints & Preferences"),
    SummarySection("Progress"),
    SummarySection("Key Decisions"),
    SummarySection("Next Steps"),
    SummarySection("Critical Context"),
)
_BRANCH_SECTIONS = _COMPACTION_SECTIONS[:-1]
_PLACEHOLDER_MARKERS = (
    "[what ",
    "[any ",
    '[or "(none)"',
    "[completed ",
    "[include previously ",
    "[current work",
    "[work that ",
    "[issues ",
    "[decision]",
    "[brief rationale]",
    "[ordered list",
    "[what should happen",
    "[update based",
    "[information needed",
    "[preserve ",
)

CODING_COMPACTION_SUMMARY_PROFILE = SummaryProfile(
    profile_id="coding.compaction",
    system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
    prompts={
        "initial": SUMMARIZATION_PROMPT,
        "update": UPDATE_SUMMARIZATION_PROMPT,
    },
    sections=_COMPACTION_SECTIONS,
    placeholder_markers=_PLACEHOLDER_MARKERS,
    resource_operation_tags=STANDARD_SUMMARY_RESOURCE_OPERATION_TAGS,
)

CODING_BRANCH_SUMMARY_PROFILE = SummaryProfile(
    profile_id="coding.branch",
    system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
    prompts={"branch": BRANCH_SUMMARY_PROMPT},
    sections=_BRANCH_SECTIONS,
    placeholder_markers=_PLACEHOLDER_MARKERS,
    resource_operation_tags=STANDARD_SUMMARY_RESOURCE_OPERATION_TAGS,
)

CODING_TURN_PREFIX_SUMMARY_PROFILE = SummaryProfile(
    profile_id="coding.turn-prefix",
    system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
    prompts={"turn-prefix": TURN_PREFIX_SUMMARIZATION_PROMPT},
    sections=(
        SummarySection("Original Request"),
        SummarySection("Early Progress"),
        SummarySection("Context for Suffix"),
    ),
    placeholder_markers=_PLACEHOLDER_MARKERS,
)


__all__ = [
    "BRANCH_SUMMARY_PROMPT",
    "CODING_BRANCH_SUMMARY_PROFILE",
    "CODING_COMPACTION_SUMMARY_PROFILE",
    "CODING_TURN_PREFIX_SUMMARY_PROFILE",
    "COMPACTION_SYSTEM_PROMPT",
    "SUMMARIZATION_PROMPT",
    "SUMMARIZATION_SYSTEM_PROMPT",
    "TURN_PREFIX_SUMMARIZATION_PROMPT",
    "UPDATE_SUMMARIZATION_PROMPT",
]
