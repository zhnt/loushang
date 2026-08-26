"""Legacy import adapter for source-neutral Resource descriptor parsing."""

from loushang.harness.resources._descriptor_parsing import (
    _prompt_descriptor_from_text,
    _skill_descriptor_from_text,
)

__all__ = ["_prompt_descriptor_from_text", "_skill_descriptor_from_text"]
