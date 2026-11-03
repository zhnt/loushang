"""Public exports for loushang.tui.ui_parts."""

from __future__ import annotations

from importlib import import_module as _import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .composer import BottomFrame as BottomFrame
    from .composer import Composer as Composer
    from .layout import RegionRenderable as RegionRenderable
    from .layout import ScreenLayout as ScreenLayout
    from .layout import ScreenRegion as ScreenRegion
    from .layout import ScreenRegionStack as ScreenRegionStack
    from .pending import PendingQueueView as PendingQueueView
    from .pending import PendingSection as PendingSection
    from .status import FooterField as FooterField
    from .status import FooterStatusLine as FooterStatusLine
    from .status import FooterView as FooterView
    from .status import StatusBar as StatusBar
    from .status import StatusField as StatusField
    from .status import WorkingLine as WorkingLine
    from .text_input import TextInput as TextInput
    from .welcome import LOUSHANG_BANNER_LOGO as LOUSHANG_BANNER_LOGO
    from .welcome import LOUSHANG_GUANQUE_TOWER_LOGO as LOUSHANG_GUANQUE_TOWER_LOGO
    from .welcome import LoushangWelcomePanel as LoushangWelcomePanel
    from .welcome import loushang_welcome_theme as loushang_welcome_theme
    from .widgets import Badge as Badge
    from .widgets import BadgeKind as BadgeKind
    from .widgets import Button as Button
    from .widgets import ButtonKind as ButtonKind
    from .widgets import Checkbox as Checkbox
    from .widgets import Choice as Choice
    from .widgets import ColumnChooser as ColumnChooser
    from .widgets import ColumnChooserClose as ColumnChooserClose
    from .widgets import ColumnChooserColumn as ColumnChooserColumn
    from .widgets import ColumnChooserMove as ColumnChooserMove
    from .widgets import ColumnChooserSelect as ColumnChooserSelect
    from .widgets import ColumnChooserSort as ColumnChooserSort
    from .widgets import ColumnChooserToggle as ColumnChooserToggle
    from .widgets import ColumnChooserWidthChange as ColumnChooserWidthChange
    from .widgets import CommandPaletteView as CommandPaletteView
    from .widgets import CompactNumberFormatter as CompactNumberFormatter
    from .widgets import ConfirmDialog as ConfirmDialog
    from .widgets import DataGrid as DataGrid
    from .widgets import DataGridAlign as DataGridAlign
    from .widgets import DataGridCell as DataGridCell
    from .widgets import DataGridCellKey as DataGridCellKey
    from .widgets import DataGridColumn as DataGridColumn
    from .widgets import DataGridCursorMode as DataGridCursorMode
    from .widgets import DataGridEdit as DataGridEdit
    from .widgets import DataGridEnterBehavior as DataGridEnterBehavior
    from .widgets import DataGridFilterMode as DataGridFilterMode
    from .widgets import DataGridFilterPredicate as DataGridFilterPredicate
    from .widgets import DataGridFormatResult as DataGridFormatResult
    from .widgets import DataGridFormatter as DataGridFormatter
    from .widgets import DataGridParser as DataGridParser
    from .widgets import DataGridRow as DataGridRow
    from .widgets import DataGridRowView as DataGridRowView
    from .widgets import DataGridSelect as DataGridSelect
    from .widgets import DataGridSelectionChange as DataGridSelectionChange
    from .widgets import DataGridSelectionMode as DataGridSelectionMode
    from .widgets import DataGridSortDirection as DataGridSortDirection
    from .widgets import DataGridThemeResolver as DataGridThemeResolver
    from .widgets import DataGridValidator as DataGridValidator
    from .widgets import DeltaFormatter as DeltaFormatter
    from .widgets import Dialog as Dialog
    from .widgets import DialogAction as DialogAction
    from .widgets import DirectoryTree as DirectoryTree
    from .widgets import DirectoryTreeEntry as DirectoryTreeEntry
    from .widgets import DirectoryTreeEntryKind as DirectoryTreeEntryKind
    from .widgets import DirectoryTreeRealKind as DirectoryTreeRealKind
    from .widgets import DirectoryTreeSelect as DirectoryTreeSelect
    from .widgets import FilterApply as FilterApply
    from .widgets import FilterBar as FilterBar
    from .widgets import FilterBoundary as FilterBoundary
    from .widgets import FilterField as FilterField
    from .widgets import FilterFocusChange as FilterFocusChange
    from .widgets import Form as Form
    from .widgets import FormRow as FormRow
    from .widgets import FormValidationResult as FormValidationResult
    from .widgets import IconButton as IconButton
    from .widgets import KeyValueItem as KeyValueItem
    from .widgets import KeyValueList as KeyValueList
    from .widgets import Menu as Menu
    from .widgets import MenuItem as MenuItem
    from .widgets import NumberFormatter as NumberFormatter
    from .widgets import PageNavigation as PageNavigation
    from .widgets import PageNavigationError as PageNavigationError
    from .widgets import PageNavigator as PageNavigator
    from .widgets import PageScaffold as PageScaffold
    from .widgets import PageScaffoldContext as PageScaffoldContext
    from .widgets import PageScaffoldFooter as PageScaffoldFooter
    from .widgets import PathFilter as PathFilter
    from .widgets import PathSortKey as PathSortKey
    from .widgets import PercentFormatter as PercentFormatter
    from .widgets import ProgressBar as ProgressBar
    from .widgets import QuestionDialog as QuestionDialog
    from .widgets import RadioGroup as RadioGroup
    from .widgets import SearchableList as SearchableList
    from .widgets import SearchableListItem as SearchableListItem
    from .widgets import SearchableListSelect as SearchableListSelect
    from .widgets import SelectList as SelectList
    from .widgets import Spinner as Spinner
    from .widgets import StatusKind as StatusKind
    from .widgets import StatusPill as StatusPill
    from .widgets import TabGroup as TabGroup
    from .widgets import TabItem as TabItem
    from .widgets import Table as Table
    from .widgets import TableAlign as TableAlign
    from .widgets import TableColumn as TableColumn
    from .widgets import TableRow as TableRow
    from .widgets import TabPage as TabPage
    from .widgets import Tabs as Tabs
    from .widgets import TextArea as TextArea
    from .widgets import TextField as TextField
    from .widgets import TextFormatter as TextFormatter
    from .widgets import Toast as Toast
    from .widgets import ToastKind as ToastKind
    from .widgets import ToastStack as ToastStack
    from .widgets import Toggle as Toggle
    from .widgets import Toolbar as Toolbar
    from .widgets import ToolbarAction as ToolbarAction
    from .widgets import TreeNode as TreeNode
    from .widgets import TreeView as TreeView


_EXPORT_GROUPS = {
    "loushang.tui.ui_parts.composer": ("BottomFrame Composer "),
    "loushang.tui.ui_parts.layout": (
        "RegionRenderable ScreenLayout ScreenRegion ScreenRegionStack "
    ),
    "loushang.tui.ui_parts.pending": ("PendingQueueView PendingSection "),
    "loushang.tui.ui_parts.status": (
        "FooterField FooterStatusLine FooterView StatusBar StatusField WorkingLine "
    ),
    "loushang.tui.ui_parts.text_input": ("TextInput "),
    "loushang.tui.ui_parts.welcome": (
        "LOUSHANG_BANNER_LOGO LOUSHANG_GUANQUE_TOWER_LOGO LoushangWelcomePanel "
        "loushang_welcome_theme "
    ),
    "loushang.tui.ui_parts.widgets": (
        "Badge BadgeKind Button ButtonKind Checkbox Choice ColumnChooser "
        "ColumnChooserClose ColumnChooserColumn ColumnChooserMove "
        "ColumnChooserSelect ColumnChooserSort ColumnChooserToggle "
        "ColumnChooserWidthChange CommandPaletteView CompactNumberFormatter "
        "ConfirmDialog DataGrid DataGridAlign DataGridCell DataGridCellKey "
        "DataGridColumn DataGridCursorMode DataGridEdit DataGridEnterBehavior "
        "DataGridFilterMode DataGridFilterPredicate DataGridFormatResult "
        "DataGridFormatter DataGridParser DataGridRow DataGridRowView DataGridSelect "
        "DataGridSelectionChange DataGridSelectionMode DataGridSortDirection "
        "DataGridThemeResolver DataGridValidator DeltaFormatter Dialog DialogAction "
        "DirectoryTree DirectoryTreeEntry DirectoryTreeEntryKind "
        "DirectoryTreeRealKind DirectoryTreeSelect FilterApply FilterBar "
        "FilterBoundary FilterField FilterFocusChange Form FormRow "
        "FormValidationResult IconButton KeyValueItem KeyValueList Menu MenuItem "
        "NumberFormatter PageNavigation PageNavigationError PageNavigator "
        "PageScaffold PageScaffoldContext PageScaffoldFooter PathFilter PathSortKey "
        "PercentFormatter ProgressBar QuestionDialog RadioGroup SearchableList "
        "SearchableListItem SearchableListSelect SelectList Spinner StatusKind "
        "StatusPill TabGroup TabItem Table TableAlign TableColumn TableRow TabPage "
        "Tabs TextArea TextField TextFormatter Toast ToastKind ToastStack Toggle "
        "Toolbar ToolbarAction TreeNode TreeView "
    ),
}
_EXPORT_MODULES = {
    name: owner for owner, names in _EXPORT_GROUPS.items() for name in names.split()
}


__all__ = [
    "Badge",
    "BadgeKind",
    "BottomFrame",
    "Button",
    "ButtonKind",
    "Checkbox",
    "Choice",
    "ColumnChooser",
    "ColumnChooserClose",
    "ColumnChooserColumn",
    "ColumnChooserMove",
    "ColumnChooserSelect",
    "ColumnChooserSort",
    "ColumnChooserToggle",
    "ColumnChooserWidthChange",
    "CommandPaletteView",
    "CompactNumberFormatter",
    "Composer",
    "ConfirmDialog",
    "DataGrid",
    "DataGridAlign",
    "DataGridCell",
    "DataGridCellKey",
    "DataGridColumn",
    "DataGridCursorMode",
    "DataGridEdit",
    "DataGridEnterBehavior",
    "DataGridFilterMode",
    "DataGridFilterPredicate",
    "DataGridFormatResult",
    "DataGridFormatter",
    "DataGridParser",
    "DataGridRow",
    "DataGridRowView",
    "DataGridSelect",
    "DataGridSelectionChange",
    "DataGridSelectionMode",
    "DataGridSortDirection",
    "DataGridThemeResolver",
    "DataGridValidator",
    "DeltaFormatter",
    "Dialog",
    "DialogAction",
    "DirectoryTree",
    "DirectoryTreeEntry",
    "DirectoryTreeEntryKind",
    "DirectoryTreeRealKind",
    "DirectoryTreeSelect",
    "FilterApply",
    "FilterBar",
    "FilterBoundary",
    "FilterField",
    "FilterFocusChange",
    "FooterField",
    "FooterStatusLine",
    "FooterView",
    "Form",
    "FormRow",
    "FormValidationResult",
    "IconButton",
    "KeyValueItem",
    "KeyValueList",
    "Menu",
    "MenuItem",
    "NumberFormatter",
    "PageNavigation",
    "PageNavigationError",
    "PageNavigator",
    "PageScaffold",
    "PageScaffoldContext",
    "PageScaffoldFooter",
    "PathFilter",
    "PathSortKey",
    "PercentFormatter",
    "LOUSHANG_BANNER_LOGO",
    "LOUSHANG_GUANQUE_TOWER_LOGO",
    "LoushangWelcomePanel",
    "loushang_welcome_theme",
    "PendingQueueView",
    "PendingSection",
    "ProgressBar",
    "QuestionDialog",
    "RadioGroup",
    "RegionRenderable",
    "ScreenLayout",
    "ScreenRegion",
    "ScreenRegionStack",
    "SearchableList",
    "SearchableListItem",
    "SearchableListSelect",
    "SelectList",
    "Spinner",
    "StatusBar",
    "StatusField",
    "StatusKind",
    "StatusPill",
    "Table",
    "TableAlign",
    "TableColumn",
    "TableRow",
    "TabItem",
    "TabGroup",
    "TabPage",
    "Tabs",
    "TextArea",
    "TextField",
    "TextFormatter",
    "TextInput",
    "Toggle",
    "Toolbar",
    "ToolbarAction",
    "Toast",
    "ToastKind",
    "ToastStack",
    "TreeNode",
    "TreeView",
    "WorkingLine",
]


def __getattr__(name: str) -> Any:
    owner = _EXPORT_MODULES.get(name)
    if owner is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(owner), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
