"""Product-neutral views over an already discovered resource bundle."""

from __future__ import annotations

from dataclasses import dataclass, replace

from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)

CONTEXT_PROMPT_KINDS = frozenset({"agents_md", "claude_md"})


class ResourceActivation:
    """Expose active resources without owning discovery or Product wording."""

    def __init__(self, bundle: ResourceBundle | None) -> None:
        if bundle is not None and not isinstance(bundle, ResourceBundle):
            raise TypeError(
                "resource activation bundle must be a ResourceBundle or None"
            )
        self._bundle = bundle

    @property
    def bundle(self) -> ResourceBundle | None:
        return self._bundle

    def context_prompts(self) -> tuple[PromptFragmentDescriptor, ...]:
        if self._bundle is None:
            return ()
        return tuple(
            descriptor
            for descriptor in self._bundle.prompt_descriptors
            if descriptor.prompt_kind in CONTEXT_PROMPT_KINDS
            and descriptor.enabled
            and descriptor.text.strip()
        )

    def prompt_fragments(self) -> tuple[str, ...]:
        if self._bundle is None:
            return ()
        if not self._bundle.prompt_descriptors:
            return tuple(
                fragment.strip()
                for fragment in self._bundle.prompt_fragments
                if isinstance(fragment, str) and fragment.strip()
            )

        fragments: list[str] = []
        seen: set[tuple[str, str]] = set()
        for descriptor in self._bundle.prompt_descriptors:
            if descriptor.prompt_kind in CONTEXT_PROMPT_KINDS or not descriptor.enabled:
                continue
            text = descriptor.text.strip()
            if not text:
                continue
            key = (descriptor.source_path.as_posix(), text)
            if key in seen:
                continue
            seen.add(key)
            fragments.append(text)
        return tuple(fragments)

    def active_skills(self) -> tuple[SkillDescriptor, ...]:
        if self._bundle is None:
            return ()
        return tuple(skill for skill in self._bundle.skills if skill.enabled)

    def model_visible_skills(self) -> tuple[SkillDescriptor, ...]:
        return tuple(
            skill
            for skill in self.active_skills()
            if not skill.disable_model_invocation
            and isinstance(skill.description, str)
            and skill.description.strip()
        )

    def find_prompt(self, name: str) -> PromptFragmentDescriptor | None:
        if self._bundle is None:
            return None
        return next(
            (
                prompt
                for prompt in self._bundle.prompts
                if name in {prompt.name, prompt.canonical_name, prompt.id}
            ),
            None,
        )

    def find_skill(self, name: str) -> SkillDescriptor | None:
        return next(
            (
                skill
                for skill in self.active_skills()
                if name in {skill.name, skill.canonical_name, skill.id}
            ),
            None,
        )


@dataclass(frozen=True)
class ResourceActivationRuntime:
    """Default sealed resource-runtime implementation for a Product Session."""

    def activate(self, bundle: ResourceBundle | None) -> ResourceActivation:
        return ResourceActivation(bundle)


@dataclass(frozen=True)
class SkillActivationRuntime:
    """Default product-neutral skill activation policy."""

    def apply(
        self,
        bundle: ResourceBundle,
        disabled_skills: tuple[str, ...] | list[str],
    ) -> ResourceBundle:
        return apply_disabled_skills(bundle, disabled_skills)


def apply_disabled_skills(
    bundle: ResourceBundle,
    disabled_skills: tuple[str, ...] | list[str],
) -> ResourceBundle:
    """Return a bundle with matching skills inactive, preserving all facts."""

    if not isinstance(bundle, ResourceBundle):
        raise TypeError("resource bundle must be a ResourceBundle")
    disabled = frozenset(value for value in disabled_skills if value)
    if not disabled:
        return bundle
    return replace(
        bundle,
        skills=[
            replace(skill, enabled=False)
            if _skill_matches_disabled_selector(skill, disabled)
            else skill
            for skill in bundle.skills
        ],
    )


def _skill_matches_disabled_selector(
    skill: SkillDescriptor,
    selectors: frozenset[str],
) -> bool:
    return bool(
        selectors
        & {
            skill.name,
            skill.id or "",
            skill.canonical_name or "",
            skill.source_path.as_posix(),
        }
    )


__all__ = [
    "CONTEXT_PROMPT_KINDS",
    "ResourceActivation",
    "ResourceActivationRuntime",
    "SkillActivationRuntime",
    "apply_disabled_skills",
]
