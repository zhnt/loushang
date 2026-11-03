"""Public exports for loushang.tui.ui_parts.widgets."""

from __future__ import annotations

from importlib import import_module as _import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .button import Button as Button
    from .button import ButtonKind as ButtonKind
    from .button import IconButton as IconButton
    from .choice import Checkbox as Checkbox
    from .choice import Choice as Choice
    from .choice import RadioGroup as RadioGroup
    from .choice import Toggle as Toggle
    from .column_chooser import ColumnChooser as ColumnChooser
    from .column_chooser import ColumnChooserClose as ColumnChooserClose
    from .column_chooser import ColumnChooserColumn as ColumnChooserColumn
    from .column_chooser import ColumnChooserMove as ColumnChooserMove
    from .column_chooser import ColumnChooserSelect as ColumnChooserSelect
    from .column_chooser import ColumnChooserSort as ColumnChooserSort
    from .column_chooser import ColumnChooserToggle as ColumnChooserToggle
    from .column_chooser import ColumnChooserWidthChange as ColumnChooserWidthChange
    from .command_palette import CommandPaletteView as CommandPaletteView
    from .data_grid import CompactNumberFormatter as CompactNumberFormatter
    from .data_grid import DataGrid as DataGrid
    from .data_grid import DataGridAlign as DataGridAlign
    from .data_grid import DataGridCell as DataGridCell
    from .data_grid import DataGridCellKey as DataGridCellKey
    from .data_grid import DataGridColumn as DataGridColumn
    from .data_grid import DataGridCursorMode as DataGridCursorMode
    from .data_grid import DataGridEdit as DataGridEdit
    from .data_grid import DataGridEnterBehavior as DataGridEnterBehavior
    from .data_grid import DataGridFilterMode as DataGridFilterMode
    from .data_grid import DataGridFilterPredicate as DataGridFilterPredicate
    from .data_grid import DataGridFormatResult as DataGridFormatResult
    from .data_grid import DataGridFormatter as DataGridFormatter
    from .data_grid import DataGridParser as DataGridParser
    from .data_grid import DataGridRow as DataGridRow
    from .data_grid import DataGridRowView as DataGridRowView
    from .data_grid import DataGridSelect as DataGridSelect
    from .data_grid import DataGridSelectionChange as DataGridSelectionChange
    from .data_grid import DataGridSelectionMode as DataGridSelectionMode
    from .data_grid import DataGridSortDirection as DataGridSortDirection
    from .data_grid import DataGridThemeResolver as DataGridThemeResolver
    from .data_grid import DataGridValidator as DataGridValidator
    from .data_grid import DeltaFormatter as DeltaFormatter
    from .data_grid import NumberFormatter as NumberFormatter
    from .data_grid import PercentFormatter as PercentFormatter
    from .data_grid import TextFormatter as TextFormatter
    from .dialog import ConfirmDialog as ConfirmDialog
    from .dialog import Dialog as Dialog
    from .dialog import DialogAction as DialogAction
    from .directory_tree import DirectoryTree as DirectoryTree
    from .directory_tree import DirectoryTreeEntry as DirectoryTreeEntry
    from .directory_tree import DirectoryTreeEntryKind as DirectoryTreeEntryKind
    from .directory_tree import DirectoryTreeRealKind as DirectoryTreeRealKind
    from .directory_tree import DirectoryTreeSelect as DirectoryTreeSelect
    from .directory_tree import PathFilter as PathFilter
    from .directory_tree import PathSortKey as PathSortKey
    from .display import Badge as Badge
    from .display import BadgeKind as BadgeKind
    from .display import KeyValueItem as KeyValueItem
    from .display import KeyValueList as KeyValueList
    from .display import ProgressBar as ProgressBar
    from .display import StatusKind as StatusKind
    from .display import StatusPill as StatusPill
    from .field import TextField as TextField
    from .filter_bar import FilterApply as FilterApply
    from .filter_bar import FilterBar as FilterBar
    from .filter_bar import FilterBoundary as FilterBoundary
    from .filter_bar import FilterField as FilterField
    from .filter_bar import FilterFocusChange as FilterFocusChange
    from .form import Form as Form
    from .form import FormRow as FormRow
    from .form import FormValidationResult as FormValidationResult
    from .menu import Menu as Menu
    from .menu import MenuItem as MenuItem
    from .page_navigator import PageNavigation as PageNavigation
    from .page_navigator import PageNavigationError as PageNavigationError
    from .page_navigator import PageNavigator as PageNavigator
    from .page_scaffold import PageScaffold as PageScaffold
    from .page_scaffold import PageScaffoldContext as PageScaffoldContext
    from .page_scaffold import PageScaffoldFooter as PageScaffoldFooter
    from .question_dialog import QuestionDialog as QuestionDialog
    from .searchable_list import SearchableList as SearchableList
    from .searchable_list import SearchableListItem as SearchableListItem
    from .searchable_list import SearchableListSelect as SearchableListSelect
    from .selection import SelectList as SelectList
    from .spinner import Spinner as Spinner
    from .tab_group import TabGroup as TabGroup
    from .tab_group import TabPage as TabPage
    from .table import Table as Table
    from .table import TableAlign as TableAlign
    from .table import TableColumn as TableColumn
    from .table import TableRow as TableRow
    from .tabs import TabItem as TabItem
    from .tabs import Tabs as Tabs
    from .textarea import TextArea as TextArea
    from .toast import Toast as Toast
    from .toast import ToastKind as ToastKind
    from .toast import ToastStack as ToastStack
    from .toolbar import Toolbar as Toolbar
    from .toolbar import ToolbarAction as ToolbarAction
    from .tree import TreeNode as TreeNode
    from .tree import TreeView as TreeView


_EXPORT_GROUPS = {
    "loushang.tui.ui_parts.widgets.button": ("Button ButtonKind IconButton "),
    "loushang.tui.ui_parts.widgets.choice": ("Checkbox Choice RadioGroup Toggle "),
    "loushang.tui.ui_parts.widgets.column_chooser": (
        "ColumnChooser ColumnChooserClose ColumnChooserColumn ColumnChooserMove "
        "ColumnChooserSelect ColumnChooserSort ColumnChooserToggle "
        "ColumnChooserWidthChange "
    ),
    "loushang.tui.ui_parts.widgets.command_palette": ("CommandPaletteView "),
    "loushang.tui.ui_parts.widgets.data_grid": (
        "CompactNumberFormatter DataGrid DataGridAlign DataGridCell DataGridCellKey "
        "DataGridColumn DataGridCursorMode DataGridEdit DataGridEnterBehavior "
        "DataGridFilterMode DataGridFilterPredicate DataGridFormatResult "
        "DataGridFormatter DataGridParser DataGridRow DataGridRowView DataGridSelect "
        "DataGridSelectionChange DataGridSelectionMode DataGridSortDirection "
        "DataGridThemeResolver DataGridValidator DeltaFormatter NumberFormatter "
        "PercentFormatter TextFormatter "
    ),
    "loushang.tui.ui_parts.widgets.dialog": ("ConfirmDialog Dialog DialogAction "),
    "loushang.tui.ui_parts.widgets.directory_tree": (
        "DirectoryTree DirectoryTreeEntry DirectoryTreeEntryKind "
        "DirectoryTreeRealKind DirectoryTreeSelect PathFilter PathSortKey "
    ),
    "loushang.tui.ui_parts.widgets.display": (
        "Badge BadgeKind KeyValueItem KeyValueList ProgressBar StatusKind StatusPill "
    ),
    "loushang.tui.ui_parts.widgets.field": ("TextField "),
    "loushang.tui.ui_parts.widgets.filter_bar": (
        "FilterApply FilterBar FilterBoundary FilterField FilterFocusChange "
    ),
    "loushang.tui.ui_parts.widgets.form": ("Form FormRow FormValidationResult "),
    "loushang.tui.ui_parts.widgets.menu": ("Menu MenuItem "),
    "loushang.tui.ui_parts.widgets.page_navigator": (
        "PageNavigation PageNavigationError PageNavigator "
    ),
    "loushang.tui.ui_parts.widgets.page_scaffold": (
        "PageScaffold PageScaffoldContext PageScaffoldFooter "
    ),
    "loushang.tui.ui_parts.widgets.question_dialog": ("QuestionDialog "),
    "loushang.tui.ui_parts.widgets.searchable_list": (
        "SearchableList SearchableListItem SearchableListSelect "
    ),
    "loushang.tui.ui_parts.widgets.selection": ("SelectList "),
    "loushang.tui.ui_parts.widgets.spinner": ("Spinner "),
    "loushang.tui.ui_parts.widgets.tab_group": ("TabGroup TabPage "),
    "loushang.tui.ui_parts.widgets.table": ("Table TableAlign TableColumn TableRow "),
    "loushang.tui.ui_parts.widgets.tabs": ("TabItem Tabs "),
    "loushang.tui.ui_parts.widgets.textarea": ("TextArea "),
    "loushang.tui.ui_parts.widgets.toast": ("Toast ToastKind ToastStack "),
    "loushang.tui.ui_parts.widgets.toolbar": ("Toolbar ToolbarAction "),
    "loushang.tui.ui_parts.widgets.tree": ("TreeNode TreeView "),
}
_EXPORT_MODULES = {
    name: owner for owner, names in _EXPORT_GROUPS.items() for name in names.split()
}


__all__ = [
    "Button",
    "ButtonKind",
    "Badge",
    "BadgeKind",
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
    "ProgressBar",
    "QuestionDialog",
    "RadioGroup",
    "SearchableList",
    "SearchableListItem",
    "SearchableListSelect",
    "SelectList",
    "Spinner",
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
    "Toggle",
    "Toolbar",
    "ToolbarAction",
    "Toast",
    "ToastKind",
    "ToastStack",
    "TreeNode",
    "TreeView",
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
