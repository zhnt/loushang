from __future__ import annotations

from loushang.tui.settings import SettingsListPage

__all__ = ["ConfigSettingsPage"]


# Compatibility name for the product-neutral settings list page.  Keep this a
# direct alias so callers see one class identity across TUI, Harnesstui, and
# product adapters.
ConfigSettingsPage = SettingsListPage
