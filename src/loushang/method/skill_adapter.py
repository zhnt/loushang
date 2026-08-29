"""Compatibility import for the explicit legacy Skill adapter.

RCP5.3C keeps this forwarding surface so existing imports do not regain body
authority.  RCP5.5 owns final peer deletion.
"""

from loushang.method.legacy_skill_adapter import method_from_skill

__all__ = ["method_from_skill"]
