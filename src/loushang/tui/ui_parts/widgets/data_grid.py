from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal, TextIO, TypedDict, Unpack, cast

from loushang.tui.cell_width import (
    autowrap_safe_width,
    truncate_to_width,
    visible_width,
)
from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.keybindings import normalize_key_id
from loushang.tui.theme import ThemeResolver
from loushang.tui.ui_parts.widgets._inline_edit_buffer import InlineEditBuffer
from loushang.tui.ui_parts.widgets._utils import callback_result, style_text

DataGridAlign = Literal["left", "right", "center"]
DataGridCursorMode = Literal["row", "cell", "column", "none"]
DataGridSelectionMode = Literal["none", "single", "multi"]
DataGridEnterBehavior = Literal["activate", "edit"]
DataGridSortDirection = Literal["asc", "desc"]
DataGridFilterMode = Literal["contains", "prefix"]
DataGridCellKey = tuple[str, str]

DATA_GRID_SEPARATOR = "  "


class _DataGridOptions(TypedDict, total=False):
    active_row_key: str | None
    active_column_key: str | None
    cursor_mode: DataGridCursorMode
    selection_mode: DataGridSelectionMode
    show_header: bool
    show_row_labels: bool
    fixed_columns: int
    zebra_stripes: bool
    empty_text: str
    wrap_rows: bool
    wrap_columns: bool
    theme: ThemeResolver | None
    focused: bool


class _CsvReaderOptions(TypedDict, total=False):
    fieldnames: Sequence[str] | None
    restkey: str | None
    restval: str | None
    delimiter: str
    quotechar: str | None
    escapechar: str | None
    doublequote: bool
    skipinitialspace: bool
    lineterminator: str
    quoting: Literal[0, 1, 2, 3]
    strict: bool


__all__ = [
    "CompactNumberFormatter",
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
    "NumberFormatter",
    "PercentFormatter",
    "TextFormatter",
]


@dataclass(frozen=True, slots=True)
class DataGridFormatResult:
    text: str
    theme_token: str | None = None


DataGridFormatter = Callable[[object], str | DataGridFormatResult]
DataGridParser = Callable[[str], object]
DataGridValidator = Callable[[object], str | None]
DataGridThemeResolver = Callable[[object], str | None]


@dataclass(frozen=True, slots=True)
class DataGridRowView:
    key: str
    values: Mapping[str, object]
    label: str | None = None
    disabled: bool = False


DataGridFilterPredicate = Callable[[DataGridRowView], bool]


@dataclass(frozen=True, slots=True)
class DataGridColumn:
    key: str
    header: str
    width: int | None = None
    min_width: int = 1
    max_width: int | None = None
    align: DataGridAlign = "left"
    editable: bool = False
    enter_behavior: DataGridEnterBehavior = "activate"
    edit_next_column_key: str | None = None
    edit_accepts_unchanged: bool = True
    sortable: bool = True
    hidden: bool = False
    formatter: DataGridFormatter | None = None
    parser: DataGridParser | None = None
    validator: DataGridValidator | None = None
    searchable: bool = True
    theme_token: str | None = None
    theme_token_for_value: DataGridThemeResolver | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", str(self.key))
        object.__setattr__(self, "min_width", max(0, self.min_width))
        if self.width is not None:
            object.__setattr__(self, "width", max(0, self.width))
        if self.max_width is not None:
            object.__setattr__(self, "max_width", max(0, self.max_width))


@dataclass(frozen=True, slots=True)
class DataGridCell:
    value: object
    disabled: bool = False
    editable: bool | None = None
    theme_token: str | None = None


@dataclass(frozen=True, slots=True)
class DataGridRow:
    key: str
    cells: Mapping[str, object | DataGridCell] | list[object | DataGridCell] | tuple[object | DataGridCell, ...]
    label: str | None = None
    disabled: bool = False
    pinned: Literal["top", "bottom"] | None = None
    theme_token: str | None = None
    on_select: Callable[[], object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", str(self.key))


@dataclass(frozen=True, slots=True)
class DataGridSelect:
    row_key: str | None
    column_key: str | None
    value: object | None
    cursor_mode: DataGridCursorMode


@dataclass(frozen=True, slots=True)
class DataGridSelectionChange:
    selected_rows: frozenset[str]
    selected_cells: frozenset[DataGridCellKey]


@dataclass(frozen=True, slots=True)
class DataGridEdit:
    row_key: str
    column_key: str
    old_value: object | None
    new_value: object


@dataclass(frozen=True, slots=True)
class TextFormatter:
    none_text: str = ""

    def __call__(self, value: object) -> str:
        return self.none_text if value is None else str(value)


@dataclass(frozen=True, slots=True)
class NumberFormatter:
    precision: int | None = None
    thousands: bool = False
    sign: bool = False
    none_text: str = ""
    invalid_text: str = ""

    def __call__(self, value: object) -> str:
        decimal = _decimal_from_value(value)
        if decimal is None:
            return self.none_text if value is None else self.invalid_text
        return _format_decimal(decimal, precision=self.precision, thousands=self.thousands, sign=self.sign)


@dataclass(frozen=True, slots=True)
class PercentFormatter:
    precision: int = 2
    scale: float = 100.0
    sign: bool = False
    none_text: str = ""
    invalid_text: str = ""

    def __call__(self, value: object) -> str:
        decimal = _decimal_from_value(value)
        if decimal is None:
            return self.none_text if value is None else self.invalid_text
        scaled = decimal * Decimal(str(self.scale))
        text = _format_decimal(scaled, precision=self.precision, thousands=False, sign=self.sign)
        return f"{text}%"


@dataclass(frozen=True, slots=True)
class DeltaFormatter:
    precision: int = 2
    sign: bool = True
    zero_sign: bool = False
    none_text: str = ""
    invalid_text: str = ""

    def __call__(self, value: object) -> str:
        decimal = _decimal_from_value(value)
        if decimal is None:
            return self.none_text if value is None else self.invalid_text
        text = _format_decimal(decimal, precision=self.precision, thousands=False, sign=self.sign)
        if self.zero_sign and decimal == 0 and not text.startswith(("+", "-")):
            return f"+{text}"
        return text


@dataclass(frozen=True, slots=True)
class CompactNumberFormatter:
    precision: int = 1
    sign: bool = False
    none_text: str = ""
    invalid_text: str = ""

    def __call__(self, value: object) -> str:
        decimal = _decimal_from_value(value)
        if decimal is None:
            return self.none_text if value is None else self.invalid_text
        return _format_compact_decimal(decimal, precision=self.precision, sign=self.sign)


@dataclass(frozen=True, slots=True)
class _FormattedCell:
    text: str
    theme_token: str | None = None


@dataclass(frozen=True, slots=True)
class _NormalizedCell:
    value: object
    disabled: bool = False
    editable: bool | None = None
    theme_token: str | None = None


@dataclass(frozen=True, slots=True)
class _NormalizedRow:
    key: str
    cells: dict[str, _NormalizedCell]
    label: str | None
    disabled: bool
    pinned: Literal["top", "bottom"] | None
    theme_token: str | None
    on_select: Callable[[], object] | None
    insertion_order: int


@dataclass(init=False, slots=True)
class DataGrid:
    columns: Sequence[DataGridColumn]
    rows: Sequence[DataGridRow | Mapping[str, object] | list[object] | tuple[object, ...]]
    cursor_mode: DataGridCursorMode
    selection_mode: DataGridSelectionMode
    show_header: bool
    show_row_labels: bool
    fixed_columns: int
    zebra_stripes: bool
    empty_text: str
    wrap_rows: bool
    wrap_columns: bool
    theme: ThemeResolver | None
    focused: bool
    editing_error: str | None = field(default=None, init=False)
    _columns: tuple[DataGridColumn, ...] = field(default=(), init=False, repr=False)
    _rows: tuple[_NormalizedRow, ...] = field(default=(), init=False, repr=False)
    _active_row_key: str | None = field(default=None, init=False, repr=False)
    _active_column_key: str | None = field(default=None, init=False, repr=False)
    _selected_row_keys: frozenset[str] = field(default_factory=frozenset, init=False, repr=False)
    _selected_cell_keys: frozenset[DataGridCellKey] = field(default_factory=frozenset, init=False, repr=False)
    _sort_state: tuple[str, DataGridSortDirection] | None = field(default=None, init=False, repr=False)
    _filter_query: str = field(default="", init=False, repr=False)
    _filter_query_columns: tuple[str, ...] | None = field(default=None, init=False, repr=False)
    _filter_mode: DataGridFilterMode = field(default="contains", init=False, repr=False)
    _filter_case_sensitive: bool = field(default=False, init=False, repr=False)
    _filter_predicate: DataGridFilterPredicate | None = field(default=None, init=False, repr=False)
    _body_rows_cache: tuple[_NormalizedRow, ...] | None = field(default=None, init=False, repr=False)
    _pinned_top_rows_cache: tuple[_NormalizedRow, ...] | None = field(default=None, init=False, repr=False)
    _pinned_bottom_rows_cache: tuple[_NormalizedRow, ...] | None = field(default=None, init=False, repr=False)
    _view_body_rows_cache: tuple[_NormalizedRow, ...] | None = field(default=None, init=False, repr=False)
    _view_row_keys_cache: tuple[str, ...] | None = field(default=None, init=False, repr=False)
    _next_generated_index: int = field(default=0, init=False, repr=False)
    _first_visible_row_index: int = field(default=0, init=False, repr=False)
    _editing_cell_key: DataGridCellKey | None = field(default=None, init=False, repr=False)
    _edit_buffer: InlineEditBuffer | None = field(default=None, init=False, repr=False)

    def __init__(
        self,
        columns: Sequence[DataGridColumn],
        rows: Sequence[DataGridRow | Mapping[str, object] | list[object] | tuple[object, ...]],
        active_row_key: str | None = None,
        active_column_key: str | None = None,
        cursor_mode: DataGridCursorMode = "row",
        selection_mode: DataGridSelectionMode = "single",
        show_header: bool = True,
        show_row_labels: bool = False,
        fixed_columns: int = 0,
        zebra_stripes: bool = False,
        empty_text: str = "No rows",
        wrap_rows: bool = True,
        wrap_columns: bool = False,
        theme: ThemeResolver | None = None,
        focused: bool = False,
    ) -> None:
        self.columns = tuple(columns)
        self.rows = tuple(rows)
        self.cursor_mode = cursor_mode
        self.selection_mode = selection_mode
        self.show_header = show_header
        self.show_row_labels = show_row_labels
        self.fixed_columns = max(0, fixed_columns)
        self.zebra_stripes = zebra_stripes
        self.empty_text = empty_text
        self.wrap_rows = wrap_rows
        self.wrap_columns = wrap_columns
        self.theme = theme
        self.focused = focused
        self.editing_error = None
        self._selected_row_keys = frozenset()
        self._selected_cell_keys = frozenset()
        self._sort_state = None
        self._filter_query = ""
        self._filter_query_columns = None
        self._filter_mode = "contains"
        self._filter_case_sensitive = False
        self._filter_predicate = None
        self._body_rows_cache = None
        self._pinned_top_rows_cache = None
        self._pinned_bottom_rows_cache = None
        self._view_body_rows_cache = None
        self._view_row_keys_cache = None
        self._next_generated_index = 0
        self._first_visible_row_index = 0
        self._editing_cell_key = None
        self._edit_buffer = None
        self._columns = _normalize_columns(self.columns)
        self._rows = self._normalize_rows(self.rows)
        self._active_row_key = self._repair_row_key(active_row_key)
        self._active_column_key = self._repair_column_key(active_column_key)
        if self.cursor_mode == "cell":
            self._repair_active_cell()

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, object]],
        *,
        columns: Sequence[DataGridColumn] | None = None,
        row_key_field: str | None = None,
        **grid_options: Unpack[_DataGridOptions],
    ) -> DataGrid:
        normalized_records = _normalize_adapter_records(records)
        grid_columns = tuple(columns) if columns is not None else _columns_from_records(normalized_records)
        rows = _rows_from_records(normalized_records, row_key_field=row_key_field)
        return cls(grid_columns, rows, **grid_options)

    @classmethod
    def from_json(
        cls,
        data: str | bytes | bytearray | Sequence[Mapping[str, object]] | Mapping[str, object],
        *,
        records_key: str = "records",
        columns: Sequence[DataGridColumn] | None = None,
        row_key_field: str | None = None,
        **grid_options: Unpack[_DataGridOptions],
    ) -> DataGrid:
        payload = _json_payload(data)
        records = _records_from_json_payload(payload, records_key=records_key)
        return cls.from_records(records, columns=columns, row_key_field=row_key_field, **grid_options)

    @classmethod
    def from_csv(
        cls,
        data: str | TextIO,
        *,
        columns: Sequence[DataGridColumn] | None = None,
        row_key_field: str | None = None,
        dialect: str = "excel",
        csv_options: Mapping[str, object] | None = None,
        **grid_options: Unpack[_DataGridOptions],
    ) -> DataGrid:
        records, header_columns = _records_from_csv(data, dialect=dialect, csv_options=csv_options)
        return cls.from_records(
            records,
            columns=columns if columns is not None else header_columns,
            row_key_field=row_key_field,
            **grid_options,
        )

    @property
    def row_keys(self) -> tuple[str, ...]:
        return tuple(row.key for row in self._rows)

    @property
    def active_row_key(self) -> str | None:
        return self._active_row_key

    @property
    def active_column_key(self) -> str | None:
        return self._active_column_key

    @property
    def selected_row_keys(self) -> frozenset[str]:
        return self._selected_row_keys

    @property
    def selected_cell_keys(self) -> frozenset[DataGridCellKey]:
        return self._selected_cell_keys

    @property
    def sort_state(self) -> tuple[str, DataGridSortDirection] | None:
        return self._sort_state

    @property
    def filter_query(self) -> str:
        return self._filter_query

    @property
    def filter_query_columns(self) -> tuple[str, ...] | None:
        return self._filter_query_columns

    @property
    def filter_mode(self) -> DataGridFilterMode:
        return self._filter_mode

    @property
    def filter_case_sensitive(self) -> bool:
        return self._filter_case_sensitive

    @property
    def has_filter(self) -> bool:
        return bool(self._filter_query) or self._filter_predicate is not None

    @property
    def view_row_keys(self) -> tuple[str, ...]:
        if self._view_row_keys_cache is None:
            self._view_row_keys_cache = tuple(row.key for row in self._view_body_rows())
        return self._view_row_keys_cache

    @property
    def filtered_row_count(self) -> int:
        return len(self._view_body_rows())

    @property
    def total_body_row_count(self) -> int:
        return len(self._body_rows())

    @property
    def editing_cell_key(self) -> DataGridCellKey | None:
        return self._editing_cell_key

    def cell_value(self, row_key: str, column_key: str) -> object | None:
        row = self._row_by_key(row_key)
        if row is None:
            return None
        cell = row.cells.get(column_key)
        return None if cell is None else cell.value

    def cell_disabled(self, row_key: str, column_key: str) -> bool:
        row = self._row_by_key(row_key)
        if row is None:
            return False
        cell = row.cells.get(column_key)
        return False if cell is None else cell.disabled

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False
        self.cancel_edit()

    def handle_input(self, event: object) -> object:
        if self._editing_cell_key is not None:
            return self._handle_editing_input(event)
        if getattr(event, "kind", "") == "text" and getattr(event, "text", "") == " ":
            return None if self.cursor_mode == "none" else self._handle_selection_input()
        if self._should_text_start_edit(event):
            started = self.start_edit(str(self._active_row_key), str(self._active_column_key))
            if not started:
                return None
            return self._handle_editing_input(event)
        if getattr(event, "kind", "") != "key":
            return None
        if self.cursor_mode == "none":
            return None
        key = normalize_key_id(getattr(event, "key", ""))
        if key in {"ctrl+f", "ctrl-f"}:
            key = "pageDown"
        elif key in {"ctrl+b", "ctrl-b"}:
            key = "pageUp"
        if key == "enter":
            if self._should_enter_start_edit():
                return self.start_edit(str(self._active_row_key), str(self._active_column_key))
            return self._activate()
        if key == "space":
            return self._handle_selection_input()
        if key == "e" and self.cursor_mode == "cell" and self._active_row_key and self._active_column_key:
            return self.start_edit(str(self._active_row_key), str(self._active_column_key))
        if self.cursor_mode == "row":
            return self._handle_row_navigation(key)
        if self.cursor_mode == "cell":
            return self._handle_cell_navigation(key)
        if self.cursor_mode == "column":
            return self._handle_column_navigation(key)
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        height = max(0, constraints.max_height)
        if height == 0:
            return RenderResult.from_lines([], constraints=constraints)
        label_width = self._row_label_width(target_width)
        render_columns = self._render_columns(target_width, label_width)
        if not render_columns:
            empty = truncate_to_width(self.empty_text, max_width=target_width, ellipsis="")
            return RenderResult.from_lines(
                [RenderLine(style_text(empty, self.theme, "widget.dataGrid.empty"))],
                constraints=constraints,
            )

        widths = _column_widths(render_columns, _grid_target_width(target_width, label_width))
        cell_starts = _cell_start_columns(render_columns, widths, label_width)
        lines: list[RenderLine] = []
        cursor: CursorDeclaration | None = None
        if self.show_header and len(lines) < height:
            headers = tuple(self._header_text(column) for column in render_columns)
            header_tokens = tuple(self._header_theme_tokens(column) for column in render_columns)
            header_text = _grid_line(
                headers,
                render_columns,
                widths,
                target_width,
                label_width=label_width,
                theme=self.theme,
                cell_token_sets=header_tokens,
            )
            if self.focused and self.cursor_mode == "column" and self._active_column_key in cell_starts:
                cursor = CursorDeclaration(row=len(lines), column=cell_starts[str(self._active_column_key)])
            lines.append(RenderLine(header_text))

        top_rows = self._pinned_top_rows()
        body_rows = self._view_body_rows()
        bottom_rows = self._pinned_bottom_rows()
        reserved_for_pinned = len(top_rows) + len(bottom_rows)
        body_budget = max(0, height - len(lines) - reserved_for_pinned)
        self._ensure_active_body_visible(body_rows, body_budget)
        visible_body_rows = body_rows[self._first_visible_row_index : self._first_visible_row_index + body_budget]

        for row in top_rows:
            if len(lines) >= height:
                break
            lines.append(RenderLine(self._row_line(row, render_columns, widths, target_width, label_width=label_width)))

        if visible_body_rows:
            for row in visible_body_rows:
                if len(lines) >= height:
                    break
                line_index = len(lines)
                row_is_active = row.key == self._active_row_key and row.pinned is None and not row.disabled
                if (
                    self.focused
                    and row_is_active
                    and self.cursor_mode in {"row", "cell"}
                    and cursor is None
                ):
                    cursor_column = 0
                    if self.cursor_mode == "cell" and self._active_column_key in cell_starts:
                        cursor_column = self._active_cell_cursor_column(
                            row,
                            render_columns,
                            widths,
                            cell_starts,
                        )
                    cursor = CursorDeclaration(row=line_index, column=cursor_column)
                lines.append(RenderLine(self._row_line(row, render_columns, widths, target_width, label_width=label_width)))
        elif len(lines) < height:
            lines.append(self._empty_row_line(render_columns, widths, target_width, label_width=label_width))

        for row in bottom_rows:
            if len(lines) >= height:
                break
            lines.append(RenderLine(self._row_line(row, render_columns, widths, target_width, label_width=label_width)))

        return RenderResult.from_lines(lines[:height], constraints=constraints, cursor=cursor)

    def _normalize_rows(
        self,
        rows: Sequence[DataGridRow | Mapping[str, object] | list[object] | tuple[object, ...]],
    ) -> tuple[_NormalizedRow, ...]:
        explicit_keys = {str(row.key) for row in rows if isinstance(row, DataGridRow)}
        used_keys: set[str] = set()
        normalized: list[_NormalizedRow] = []
        for insertion_order, row in enumerate(rows):
            normalized_row = self._normalize_row(row, explicit_keys, used_keys, insertion_order)
            if normalized_row.key in used_keys:
                raise ValueError(f"duplicate row key: {normalized_row.key!r}")
            used_keys.add(normalized_row.key)
            normalized.append(normalized_row)
        return tuple(normalized)

    def _normalize_row(
        self,
        row: DataGridRow | Mapping[str, object] | list[object] | tuple[object, ...],
        explicit_keys: set[str],
        used_keys: set[str],
        insertion_order: int,
    ) -> _NormalizedRow:
        if isinstance(row, DataGridRow):
            key = row.key
            cells_source = row.cells
            label = row.label
            disabled = row.disabled
            pinned = row.pinned
            theme_token = row.theme_token
            on_select = row.on_select
        else:
            key = self._next_generated_key(explicit_keys | used_keys)
            cells_source = row
            label = None
            disabled = False
            pinned = None
            theme_token = None
            on_select = None
        cells = _cells_from_source(cells_source, self._columns)
        return _NormalizedRow(
            key=key,
            cells=cells,
            label=label,
            disabled=disabled,
            pinned=pinned,
            theme_token=theme_token,
            on_select=on_select,
            insertion_order=insertion_order,
        )

    def _next_generated_key(self, blocked_keys: set[str]) -> str:
        while True:
            key = f"row-{self._next_generated_index}"
            self._next_generated_index += 1
            if key not in blocked_keys:
                return key

    def _row_by_key(self, key: str) -> _NormalizedRow | None:
        for row in self._rows:
            if row.key == key:
                return row
        return None

    def _body_rows(self) -> tuple[_NormalizedRow, ...]:
        if self._body_rows_cache is None:
            self._body_rows_cache = tuple(row for row in self._rows if row.pinned is None)
        return self._body_rows_cache

    def _pinned_top_rows(self) -> tuple[_NormalizedRow, ...]:
        if self._pinned_top_rows_cache is None:
            self._pinned_top_rows_cache = tuple(row for row in self._rows if row.pinned == "top")
        return self._pinned_top_rows_cache

    def _pinned_bottom_rows(self) -> tuple[_NormalizedRow, ...]:
        if self._pinned_bottom_rows_cache is None:
            self._pinned_bottom_rows_cache = tuple(row for row in self._rows if row.pinned == "bottom")
        return self._pinned_bottom_rows_cache

    def _view_body_rows(self) -> tuple[_NormalizedRow, ...]:
        if self._view_body_rows_cache is None:
            body_rows = self._body_rows()
            self._view_body_rows_cache = (
                tuple(row for row in body_rows if self._row_matches_filters(row))
                if self.has_filter
                else body_rows
            )
        return self._view_body_rows_cache

    def _invalidate_row_caches(self) -> None:
        self._body_rows_cache = None
        self._pinned_top_rows_cache = None
        self._pinned_bottom_rows_cache = None
        self._invalidate_view_cache()

    def _invalidate_view_cache(self) -> None:
        self._view_body_rows_cache = None
        self._view_row_keys_cache = None

    def _accepted_query_columns(self, columns: Sequence[str]) -> tuple[str, ...]:
        accepted: list[str] = []
        seen: set[str] = set()
        for key in columns:
            column = self._column_by_key(str(key))
            if column is None or column.hidden or not column.searchable or column.key in seen:
                continue
            accepted.append(column.key)
            seen.add(column.key)
        return tuple(accepted)

    def _repair_filter_query_columns(self) -> None:
        if self._filter_query_columns is None:
            return
        self._filter_query_columns = self._accepted_query_columns(self._filter_query_columns)

    def _query_columns(self) -> tuple[DataGridColumn, ...]:
        if self._filter_query_columns is not None:
            keys = set(self._filter_query_columns)
            return tuple(
                column
                for column in self._columns
                if column.key in keys and not column.hidden and column.searchable
            )
        return tuple(column for column in self._visible_columns() if column.searchable)

    def _row_view(self, row: _NormalizedRow) -> DataGridRowView:
        values = {key: cell.value for key, cell in row.cells.items()}
        return DataGridRowView(row.key, MappingProxyType(values), row.label, row.disabled)

    def _row_matches_filters(self, row: _NormalizedRow) -> bool:
        if self._filter_query and not self._row_matches_query(row):
            return False
        if self._filter_predicate is not None and not self._filter_predicate(self._row_view(row)):
            return False
        return True

    def _row_matches_query(self, row: _NormalizedRow) -> bool:
        columns = self._query_columns()
        if not columns:
            return False
        needle = self._filter_query if self._filter_case_sensitive else self._filter_query.casefold()
        for column in columns:
            value = row.cells[column.key].value
            cell_text = "" if value is None else str(value)
            haystack = cell_text if self._filter_case_sensitive else cell_text.casefold()
            if self._filter_mode == "prefix" and haystack.startswith(needle):
                return True
            if self._filter_mode == "contains" and needle in haystack:
                return True
        return False

    def _repair_state_after_view_change(self) -> None:
        self._invalidate_view_cache()
        if self._editing_cell_key is not None and self._editing_cell_key[0] not in self.view_row_keys:
            self.cancel_edit()
        self._active_row_key = self._repair_row_key(self._active_row_key)
        self._active_column_key = self._repair_column_key(self._active_column_key)
        if self.cursor_mode == "cell":
            self._repair_active_cell()
        body_rows = self._view_body_rows()
        if not body_rows:
            self._first_visible_row_index = 0
        else:
            self._first_visible_row_index = max(
                0,
                min(self._first_visible_row_index, max(0, len(body_rows) - 1)),
            )

    def _column_by_key(self, key: str) -> DataGridColumn | None:
        for column in self._columns:
            if column.key == key:
                return column
        return None

    def _active_row(self) -> _NormalizedRow | None:
        if self._active_row_key is None:
            return None
        row = self._row_by_key(self._active_row_key)
        if row is None or row.disabled or row.pinned is not None or row.key not in self.view_row_keys:
            return None
        return row

    def _visible_columns(self) -> tuple[DataGridColumn, ...]:
        return tuple(column for column in self._columns if not column.hidden)

    def _row_label_width(self, target_width: int) -> int:
        if not self.show_row_labels:
            return 0
        labels = tuple(row.label or row.key for row in self._rows)
        if not labels:
            return 0
        max_label = max(visible_width(label) for label in labels)
        return max(0, min(max_label, max(0, target_width - 4)))

    def _render_columns(self, target_width: int, label_width: int) -> tuple[DataGridColumn, ...]:
        visible_columns = self._visible_columns()
        if not visible_columns:
            return ()
        grid_width = max(0, _grid_target_width(target_width, label_width) - 2)
        if _preferred_occupied_width(visible_columns) <= grid_width:
            return visible_columns

        fixed_count = min(self.fixed_columns, len(visible_columns))
        fixed_columns = visible_columns[:fixed_count]
        scroll_columns = visible_columns[fixed_count:]
        if not scroll_columns:
            return fixed_columns

        scroll_keys = tuple(column.key for column in scroll_columns)
        start = scroll_keys.index(str(self._active_column_key)) if self._active_column_key in scroll_keys else 0
        selected = [*fixed_columns, scroll_columns[start]]
        for column in scroll_columns[start + 1 :]:
            candidate = (*selected, column)
            if _preferred_occupied_width(candidate) > grid_width:
                break
            selected.append(column)
        return tuple(selected)

    def _enabled_rows(self) -> tuple[_NormalizedRow, ...]:
        return tuple(row for row in self._view_body_rows() if not row.disabled)

    def _empty_row_line(
        self,
        columns: Sequence[DataGridColumn],
        widths: Sequence[int],
        target_width: int,
        *,
        label_width: int,
    ) -> RenderLine:
        empty_cells = (self.empty_text,) + tuple("" for _ in columns[1:])
        text = _grid_line(empty_cells, columns, widths, target_width, label_width=label_width)
        return RenderLine(style_text(text, self.theme, "widget.dataGrid.empty"))

    def _enabled_row_keys(self) -> tuple[str, ...]:
        return tuple(row.key for row in self._enabled_rows())

    def _visible_column_keys(self) -> tuple[str, ...]:
        return tuple(column.key for column in self._visible_columns())

    def _header_text(self, column: DataGridColumn) -> str:
        if self._sort_state is None or self._sort_state[0] != column.key:
            return column.header
        marker = "^" if self._sort_state[1] == "asc" else "v"
        return f"{column.header} {marker}"

    def _header_theme_tokens(self, column: DataGridColumn) -> tuple[str | None, ...]:
        sorted_column = self._sort_state is not None and self._sort_state[0] == column.key
        focused_column = self.focused and self.cursor_mode == "column" and self._active_column_key == column.key
        if sorted_column and focused_column:
            return ("widget.dataGrid.header", "widget.dataGrid.sortHeader", "widget.dataGrid.focusSortHeader")
        if sorted_column:
            return ("widget.dataGrid.header", "widget.dataGrid.sortHeader")
        if focused_column:
            return ("widget.dataGrid.header", "widget.dataGrid.focusColumn")
        return ("widget.dataGrid.header",)

    def _repair_row_key(self, preferred: str | None) -> str | None:
        enabled = self._enabled_rows()
        enabled_keys = {row.key for row in enabled}
        if preferred is not None and str(preferred) in enabled_keys:
            return str(preferred)
        return None if not enabled else enabled[0].key

    def _repair_column_key(self, preferred: str | None) -> str | None:
        visible = self._visible_columns()
        visible_keys = {column.key for column in visible}
        if preferred is not None and str(preferred) in visible_keys:
            return str(preferred)
        return None if not visible else visible[0].key

    def _handle_row_navigation(self, key: str) -> bool | None:
        if key == "up":
            return self._move_active_row(-1, wrap=self.wrap_rows)
        if key == "down":
            return self._move_active_row(1, wrap=self.wrap_rows)
        if key == "home":
            return self._jump_active_row(first=True)
        if key == "end":
            return self._jump_active_row(first=False)
        if key == "pageUp":
            return self._move_active_row(-5, wrap=False)
        if key == "pageDown":
            return self._move_active_row(5, wrap=False)
        if key in {"left", "right"}:
            return False if self._enabled_rows() else None
        return None

    def _handle_cell_navigation(self, key: str) -> bool | None:
        if key == "left":
            return self._move_active_cell_column(-1)
        if key == "right":
            return self._move_active_cell_column(1)
        if key == "up":
            return self._move_active_cell_row(-1, wrap=self.wrap_rows)
        if key == "down":
            return self._move_active_cell_row(1, wrap=self.wrap_rows)
        if key == "home":
            return self._jump_active_cell_column(first=True)
        if key == "end":
            return self._jump_active_cell_column(first=False)
        if key == "pageUp":
            return self._move_active_cell_row(-5, wrap=False)
        if key == "pageDown":
            return self._move_active_cell_row(5, wrap=False)
        return None

    def _handle_column_navigation(self, key: str) -> bool | None:
        if key == "left":
            return self._move_active_column(-1)
        if key == "right":
            return self._move_active_column(1)
        if key == "home":
            return self._jump_active_column(first=True)
        if key == "end":
            return self._jump_active_column(first=False)
        if key in {"up", "down", "pageUp", "pageDown"}:
            return False if self._visible_columns() else None
        return None

    def _should_enter_start_edit(self) -> bool:
        if self.cursor_mode != "cell" or self._active_row_key is None or self._active_column_key is None:
            return False
        column = self._column_by_key(self._active_column_key)
        if column is None or column.enter_behavior != "edit":
            return False
        return self._is_editable_cell(self._active_row_key, self._active_column_key)

    def start_edit(self, row_key: str, column_key: str) -> bool:
        row = self._row_by_key(row_key)
        column = self._column_by_key(column_key)
        self.cursor_mode = "cell"
        if row is not None:
            self._active_row_key = row.key
        if column is not None and not column.hidden:
            self._active_column_key = column.key
        if row is None or column is None or column.hidden or not self._is_editable_cell(row.key, column.key):
            self.cancel_edit()
            return False
        cell = row.cells[column.key]
        self._editing_cell_key = (row.key, column.key)
        self._edit_buffer = InlineEditBuffer.from_value(cell.value)
        self.editing_error = None
        return True

    def cancel_edit(self) -> bool:
        if self._editing_cell_key is None and self.editing_error is None:
            return False
        self._editing_cell_key = None
        self._edit_buffer = None
        self.editing_error = None
        return True

    def activate_cell(self, row_key: str, column_key: str) -> bool:
        row = self._row_by_key(row_key)
        column = self._column_by_key(column_key)
        if row is None or column is None or not self._is_enabled_cell(row.key, column.key):
            return False
        self.cancel_edit()
        self.cursor_mode = "cell"
        self._active_row_key = row.key
        self._active_column_key = column.key
        return True

    def activate_row(self, row_key: str) -> bool:
        row = self._row_by_key(row_key)
        if row is None or row.disabled or row.pinned is not None or row.key not in self.view_row_keys:
            return False
        was_editing = self._editing_cell_key is not None or self.editing_error is not None
        self.cancel_edit()
        changed = row.key != self._active_row_key
        self._active_row_key = row.key
        if self.cursor_mode == "cell":
            next_column = self._nearest_enabled_column_in_row(row, self._active_column_key)
            if next_column is None:
                changed = self._repair_active_cell() or changed
            else:
                changed = next_column != self._active_column_key or changed
                self._active_column_key = next_column
        return changed or was_editing

    def commit_edit(self) -> DataGridEdit | None:
        if self._editing_cell_key is None:
            return None
        row_key, column_key = self._editing_cell_key
        row = self._row_by_key(row_key)
        column = self._column_by_key(column_key)
        if row is None or column is None:
            self.cancel_edit()
            return None
        old_value = row.cells[column_key].value
        edit_text = "" if self._edit_buffer is None else self._edit_buffer.text
        try:
            new_value = column.parser(edit_text) if column.parser is not None else edit_text
        except Exception as exc:
            self.editing_error = str(exc) or exc.__class__.__name__
            return None
        if column.validator is not None:
            error = column.validator(new_value)
            if error is not None:
                self.editing_error = error
                return None
        if not column.edit_accepts_unchanged and new_value == old_value:
            self.cancel_edit()
            return None
        self._set_cell_value(row_key, column_key, new_value)
        result = DataGridEdit(row_key=row_key, column_key=column_key, old_value=old_value, new_value=new_value)
        self.cancel_edit()
        if column.edit_next_column_key is not None:
            self.start_edit(row_key, column.edit_next_column_key)
        return result

    def _handle_editing_input(self, event: object) -> object:
        buffer = self._edit_buffer
        if buffer is None:
            return None
        kind = getattr(event, "kind", "")
        if kind in {"text", "paste"}:
            text = getattr(event, "text", "")
            buffer.insert_text(text)
            self.editing_error = None
            return True
        if kind != "key":
            return None
        key = normalize_key_id(getattr(event, "key", ""))
        if key == "enter":
            return self.commit_edit()
        if key == "escape":
            return self.cancel_edit()
        if key in {"up", "down", "pageUp", "pageDown"}:
            return False
        if key == "left":
            return buffer.move_left()
        if key == "right":
            return buffer.move_right()
        if key == "home":
            return buffer.move_home()
        if key == "end":
            return buffer.move_end()
        if key in {"tab", "shift+tab"}:
            return self._commit_and_move_edit(-1 if key == "shift+tab" else 1)
        if key == "backspace":
            buffer.delete_backward()
            self.editing_error = None
            return True
        if key == "delete":
            buffer.delete_forward()
            self.editing_error = None
            return True
        return None

    def _should_text_start_edit(self, event: object) -> bool:
        kind = getattr(event, "kind", "")
        if kind not in {"text", "paste"} or self.cursor_mode != "cell":
            return False
        text = getattr(event, "text", "")
        return (
            bool(text)
            and self._active_row_key is not None
            and self._active_column_key is not None
            and self._is_editable_cell(self._active_row_key, self._active_column_key)
        )

    def _commit_and_move_edit(self, delta: int) -> object:
        previous = self._editing_cell_key
        result = self.commit_edit()
        if result is None:
            return None
        if self._editing_cell_key is None and previous is not None:
            self._start_adjacent_edit(previous, delta)
        return result

    def _start_adjacent_edit(self, previous: DataGridCellKey, delta: int) -> bool:
        editable = self._editable_cell_keys()
        if previous not in editable:
            return False
        position = editable.index(previous) + delta
        if position < 0 or position >= len(editable):
            return False
        row_key, column_key = editable[position]
        return self.start_edit(row_key, column_key)

    def _is_editable_cell(self, row_key: str, column_key: str) -> bool:
        if not self._is_enabled_cell(row_key, column_key):
            return False
        row = self._row_by_key(row_key)
        column = self._column_by_key(column_key)
        if row is None or column is None:
            return False
        cell = row.cells[column_key]
        return column.editable if cell.editable is None else cell.editable

    def _set_cell_value(self, row_key: str, column_key: str, value: object) -> None:
        row = self._row_by_key(row_key)
        if row is None or column_key not in row.cells:
            return
        cell = row.cells[column_key]
        row.cells[column_key] = _NormalizedCell(
            value=value,
            disabled=cell.disabled,
            editable=cell.editable,
            theme_token=cell.theme_token,
        )
        self._invalidate_row_caches()

    def _activate(self) -> object:
        if self.cursor_mode == "row":
            row = self._active_row()
            if row is None:
                return None
            if row.on_select is not None:
                return callback_result(row.on_select())
            return DataGridSelect(row_key=row.key, column_key=None, value=None, cursor_mode="row")
        if self.cursor_mode == "cell":
            if not self._is_enabled_cell(self._active_row_key, self._active_column_key):
                return None
            row_key = str(self._active_row_key)
            column_key = str(self._active_column_key)
            return DataGridSelect(
                row_key=row_key,
                column_key=column_key,
                value=self.cell_value(row_key, column_key),
                cursor_mode="cell",
            )
        if self.cursor_mode == "column":
            if self._active_column_key not in self._visible_column_keys():
                return None
            return DataGridSelect(row_key=None, column_key=self._active_column_key, value=None, cursor_mode="column")
        return None

    def _handle_selection_input(self) -> object:
        if self.selection_mode == "none":
            return self._activate()
        changed = False
        if self.cursor_mode == "row":
            changed = self.toggle_row(str(self._active_row_key)) if self._active_row_key is not None else False
        elif self.cursor_mode == "cell":
            if self._active_row_key is not None and self._active_column_key is not None:
                changed = self.toggle_cell(str(self._active_row_key), str(self._active_column_key))
        elif self.cursor_mode == "column":
            if self.selection_mode == "single":
                return False
            changed = self._toggle_active_column_cells()
        if not changed:
            return False if self.selection_mode in {"single", "multi"} else None
        return DataGridSelectionChange(self._selected_row_keys, self._selected_cell_keys)

    def select_row(self, row_key: str) -> bool:
        if self.selection_mode == "none":
            return False
        row = self._row_by_key(row_key)
        if row is None or row.disabled or row.pinned is not None or row.key not in self.view_row_keys:
            return False
        if self.selection_mode == "single":
            next_rows = frozenset({row.key})
            if next_rows == self._selected_row_keys and not self._selected_cell_keys:
                return False
            self._selected_row_keys = next_rows
            self._selected_cell_keys = frozenset()
            return True
        if row.key in self._selected_row_keys:
            return False
        self._selected_row_keys = frozenset((*self._selected_row_keys, row.key))
        return True

    def toggle_row(self, row_key: str) -> bool:
        row = self._row_by_key(row_key)
        if (
            row is None
            or row.disabled
            or row.pinned is not None
            or row.key not in self.view_row_keys
            or self.selection_mode == "none"
        ):
            return False
        if self.selection_mode == "single":
            return self.select_row(row_key)
        selected = set(self._selected_row_keys)
        if row.key in selected:
            selected.remove(row.key)
        else:
            selected.add(row.key)
        next_rows = frozenset(selected)
        if next_rows == self._selected_row_keys:
            return False
        self._selected_row_keys = next_rows
        return True

    def select_cell(self, row_key: str, column_key: str) -> bool:
        if self.selection_mode == "none" or not self._is_enabled_cell(row_key, column_key):
            return False
        cell_key = (row_key, column_key)
        if self.selection_mode == "single":
            next_cells = frozenset({cell_key})
            if next_cells == self._selected_cell_keys and not self._selected_row_keys:
                return False
            self._selected_cell_keys = next_cells
            self._selected_row_keys = frozenset()
            return True
        if cell_key in self._selected_cell_keys:
            return False
        self._selected_cell_keys = frozenset((*self._selected_cell_keys, cell_key))
        return True

    def toggle_cell(self, row_key: str, column_key: str) -> bool:
        if self.selection_mode == "none" or not self._is_enabled_cell(row_key, column_key):
            return False
        if self.selection_mode == "single":
            return self.select_cell(row_key, column_key)
        selected = set(self._selected_cell_keys)
        cell_key = (row_key, column_key)
        if cell_key in selected:
            selected.remove(cell_key)
        else:
            selected.add(cell_key)
        next_cells = frozenset(selected)
        if next_cells == self._selected_cell_keys:
            return False
        self._selected_cell_keys = next_cells
        return True

    def select_all(self) -> bool:
        if self.selection_mode != "multi":
            return False
        if self.cursor_mode == "row":
            next_rows = frozenset(row.key for row in self._enabled_rows())
            if next_rows == self._selected_row_keys:
                return False
            self._selected_row_keys = next_rows
            return True
        next_cells = frozenset(self._enabled_cell_keys())
        if next_cells == self._selected_cell_keys:
            return False
        self._selected_cell_keys = next_cells
        return True

    def clear_selection(self) -> bool:
        if not self._selected_row_keys and not self._selected_cell_keys:
            return False
        self._selected_row_keys = frozenset()
        self._selected_cell_keys = frozenset()
        return True

    def set_filter_query(
        self,
        query: str,
        *,
        columns: Sequence[str] | None = None,
        mode: DataGridFilterMode = "contains",
        case_sensitive: bool = False,
    ) -> bool:
        if mode not in {"contains", "prefix"}:
            return False
        old_keys = self.view_row_keys
        old_state = (
            self._filter_query,
            self._filter_query_columns,
            self._filter_mode,
            self._filter_case_sensitive,
        )
        effective_query = str(query).strip()
        accepted_columns = None if columns is None else self._accepted_query_columns(columns)
        if not effective_query:
            accepted_columns = None
            mode = "contains"
            case_sensitive = False
        self._filter_query = effective_query
        self._filter_query_columns = accepted_columns
        self._filter_mode = mode
        self._filter_case_sensitive = bool(case_sensitive)
        self._repair_state_after_view_change()
        return old_state != (
            self._filter_query,
            self._filter_query_columns,
            self._filter_mode,
            self._filter_case_sensitive,
        ) or old_keys != self.view_row_keys

    def set_filter_predicate(self, predicate: DataGridFilterPredicate | None) -> bool:
        old_keys = self.view_row_keys
        old_predicate = self._filter_predicate
        self._filter_predicate = predicate
        self._repair_state_after_view_change()
        return old_predicate is not predicate or old_keys != self.view_row_keys

    def clear_filter(self) -> bool:
        old_keys = self.view_row_keys
        had_filter = self.has_filter
        self._filter_query = ""
        self._filter_query_columns = None
        self._filter_mode = "contains"
        self._filter_case_sensitive = False
        self._filter_predicate = None
        self._repair_state_after_view_change()
        return had_filter or old_keys != self.view_row_keys

    def cycle_sort(self, column_key: str | None = None) -> bool:
        key = column_key if column_key is not None else self._active_column_key
        if key is None:
            return False
        column = self._column_by_key(str(key))
        if column is None or column.hidden or not column.sortable:
            return False
        if self._sort_state is None or self._sort_state[0] != column.key:
            return self.sort_by(column.key, "asc")
        if self._sort_state[1] == "asc":
            return self.sort_by(column.key, "desc")
        return self.clear_sort()

    def sort_by(self, column_key: str, direction: DataGridSortDirection = "asc") -> bool:
        column = self._column_by_key(column_key)
        if column is None or column.hidden or not column.sortable or direction not in {"asc", "desc"}:
            return False
        self._sort_state = (column.key, direction)
        self._apply_sort_state()
        self._repair_state_after_data_change()
        return True

    def clear_sort(self) -> bool:
        if self._sort_state is None:
            return False
        self._sort_state = None
        self._rows = tuple(sorted(self._rows, key=lambda row: row.insertion_order))
        self._repair_state_after_data_change()
        return True

    def add_row(
        self,
        row: DataGridRow | Mapping[str, object] | list[object] | tuple[object, ...],
        *,
        index: int | None = None,
        activate: bool = False,
        edit_column_key: str | None = None,
    ) -> str:
        used_keys = set(self.row_keys)
        explicit_keys = {str(row.key)} if isinstance(row, DataGridRow) else set()
        insertion_order = (max((existing.insertion_order for existing in self._rows), default=-1) + 1)
        normalized = self._normalize_row(row, explicit_keys, used_keys, insertion_order)
        if normalized.key in used_keys:
            raise ValueError(f"duplicate row key: {normalized.key!r}")
        rows = list(self._rows)
        if index is None:
            rows.append(normalized)
        else:
            rows.insert(max(0, min(index, len(rows))), normalized)
        self._rows = tuple(rows)
        if activate:
            self._active_row_key = normalized.key
        self._repair_state_after_data_change()
        if activate and edit_column_key is not None:
            self.start_edit(normalized.key, edit_column_key)
        return normalized.key

    def replace_rows(
        self,
        rows: Sequence[DataGridRow | Mapping[str, object] | list[object] | tuple[object, ...]],
    ) -> None:
        self.rows = tuple(rows)
        self._rows = self._normalize_rows(self.rows)
        self._apply_sort_state()
        self._repair_state_after_data_change()

    def remove_row(self, row_key: str) -> bool:
        if row_key not in self.row_keys:
            return False
        self._rows = tuple(row for row in self._rows if row.key != row_key)
        if self._editing_cell_key is not None and self._editing_cell_key[0] == row_key:
            self.cancel_edit()
        self._repair_state_after_data_change()
        return True

    def add_column(self, column: DataGridColumn, *, index: int | None = None, default: object | DataGridCell = "") -> bool:
        if self._column_by_key(column.key) is not None:
            return False
        columns = list(self._columns)
        if index is None:
            columns.append(column)
        else:
            columns.insert(max(0, min(index, len(columns))), column)
        self._columns = tuple(columns)
        self.columns = self._columns
        default_cell = _normalize_cell(default)
        for row in self._rows:
            row.cells[column.key] = default_cell
        self._repair_state_after_data_change()
        return True

    def remove_column(self, column_key: str) -> bool:
        if self._column_by_key(column_key) is None:
            return False
        if self._sort_state is not None and self._sort_state[0] == column_key:
            self._sort_state = None
        self._columns = tuple(column for column in self._columns if column.key != column_key)
        self.columns = self._columns
        for row in self._rows:
            row.cells.pop(column_key, None)
        self._selected_cell_keys = frozenset(
            cell_key for cell_key in self._selected_cell_keys if cell_key[1] != column_key
        )
        if self._editing_cell_key is not None and self._editing_cell_key[1] == column_key:
            self.cancel_edit()
        self._repair_filter_query_columns()
        self._repair_state_after_data_change()
        return True

    def set_column_hidden(self, column_key: str, hidden: bool = True) -> bool:
        column = self._column_by_key(column_key)
        if column is None or column.hidden == hidden:
            return False
        if hidden and self._sort_state is not None and self._sort_state[0] == column.key:
            self._sort_state = None
        self._columns = tuple(replace(item, hidden=hidden) if item.key == column.key else item for item in self._columns)
        self.columns = self._columns
        if hidden and self._editing_cell_key is not None and self._editing_cell_key[1] == column.key:
            self.cancel_edit()
        self._repair_filter_query_columns()
        self._repair_state_after_data_change()
        return True

    def toggle_column(self, column_key: str) -> bool:
        column = self._column_by_key(column_key)
        if column is None:
            return False
        return self.set_column_hidden(column.key, not column.hidden)

    def move_column(
        self,
        column_key: str,
        *,
        index: int | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> bool:
        requested_targets = sum(target is not None for target in (index, before, after))
        if requested_targets != 1:
            return False
        current = list(self._columns)
        keys = [column.key for column in current]
        if column_key not in keys:
            return False
        current_index = keys.index(column_key)
        column = current.pop(current_index)
        remaining_keys = [item.key for item in current]

        if index is not None:
            insert_at = max(0, min(index, len(current)))
        elif before is not None:
            if before == column_key or before not in remaining_keys:
                return False
            insert_at = remaining_keys.index(before)
        else:
            if after == column_key or after not in remaining_keys:
                return False
            insert_at = remaining_keys.index(str(after)) + 1

        current.insert(insert_at, column)
        next_columns = tuple(current)
        if next_columns == self._columns:
            return False
        self._columns = next_columns
        self.columns = self._columns
        self._repair_state_after_data_change()
        return True

    def set_column_width(self, column_key: str, width: int | None) -> bool:
        column = self._column_by_key(column_key)
        if column is None:
            return False
        next_width = None if width is None else max(0, width)
        if column.width == next_width:
            return False
        self._columns = tuple(replace(item, width=next_width) if item.key == column.key else item for item in self._columns)
        self.columns = self._columns
        self._repair_state_after_data_change()
        return True

    def update_cell(self, row_key: str, column_key: str, value: object | DataGridCell) -> bool:
        row = self._row_by_key(row_key)
        if row is None or self._column_by_key(column_key) is None:
            return False
        row.cells[column_key] = _normalize_cell(value)
        if self._editing_cell_key == (row_key, column_key):
            self.cancel_edit()
        self._repair_state_after_data_change()
        return True

    def clear(self) -> None:
        self._rows = ()
        self.rows = ()
        self._selected_row_keys = frozenset()
        self._selected_cell_keys = frozenset()
        self._sort_state = None
        self._active_row_key = None
        self._active_column_key = self._repair_column_key(self._active_column_key)
        self._first_visible_row_index = 0
        self.cancel_edit()
        self._invalidate_row_caches()

    def _toggle_active_column_cells(self) -> bool:
        if self._active_column_key is None:
            return False
        column_cells = frozenset(self._enabled_cell_keys_for_column(self._active_column_key))
        if not column_cells:
            return False
        selected = set(self._selected_cell_keys)
        if column_cells.issubset(selected):
            selected.difference_update(column_cells)
        else:
            selected.update(column_cells)
        next_cells = frozenset(selected)
        if next_cells == self._selected_cell_keys:
            return False
        self._selected_cell_keys = next_cells
        return True

    def _enabled_cell_keys(self) -> tuple[DataGridCellKey, ...]:
        result: list[DataGridCellKey] = []
        for row in self._enabled_rows():
            for column in self._enabled_columns_for_row(row):
                result.append((row.key, column.key))
        return tuple(result)

    def _enabled_cell_keys_for_column(self, column_key: str) -> tuple[DataGridCellKey, ...]:
        if column_key not in self._visible_column_keys():
            return ()
        result: list[DataGridCellKey] = []
        for row in self._enabled_rows():
            if self._is_enabled_cell(row.key, column_key):
                result.append((row.key, column_key))
        return tuple(result)

    def _source_enabled_rows(self) -> tuple[_NormalizedRow, ...]:
        return tuple(row for row in self._body_rows() if not row.disabled)

    def _source_enabled_cell_keys(self) -> tuple[DataGridCellKey, ...]:
        result: list[DataGridCellKey] = []
        for row in self._source_enabled_rows():
            for column in self._enabled_columns_for_row(row):
                result.append((row.key, column.key))
        return tuple(result)

    def _editable_cell_keys(self) -> tuple[DataGridCellKey, ...]:
        result: list[DataGridCellKey] = []
        for row in self._enabled_rows():
            for column in self._visible_columns():
                if self._is_editable_cell(row.key, column.key):
                    result.append((row.key, column.key))
        return tuple(result)

    def _apply_sort_state(self) -> None:
        if self._sort_state is None:
            return
        column_key, direction = self._sort_state
        top_rows = tuple(row for row in self._rows if row.pinned == "top")
        body_rows = tuple(row for row in self._rows if row.pinned is None)
        bottom_rows = tuple(row for row in self._rows if row.pinned == "bottom")
        reverse = direction == "desc"
        sorted_body = tuple(sorted(body_rows, key=lambda row: _sortable_value(row.cells[column_key].value), reverse=reverse))
        self._rows = (*top_rows, *sorted_body, *bottom_rows)

    def _repair_state_after_data_change(self) -> None:
        self._invalidate_row_caches()
        self._repair_state_after_view_change()
        enabled_rows = {row.key for row in self._source_enabled_rows()}
        enabled_cells = set(self._source_enabled_cell_keys())
        self._selected_row_keys = frozenset(key for key in self._selected_row_keys if key in enabled_rows)
        self._selected_cell_keys = frozenset(key for key in self._selected_cell_keys if key in enabled_cells)

    def _move_active_row(self, delta: int, *, wrap: bool) -> bool | None:
        enabled = self._enabled_row_keys()
        if not enabled:
            return None
        if self._active_row_key not in enabled:
            self._active_row_key = enabled[0]
            return True
        position = enabled.index(self._active_row_key)
        next_position = position + delta
        if wrap:
            next_position %= len(enabled)
        elif next_position < 0 or next_position >= len(enabled):
            return False
        else:
            next_position = max(0, min(next_position, len(enabled) - 1))
        next_key = enabled[next_position]
        if next_key == self._active_row_key:
            return False
        self._active_row_key = next_key
        return True

    def _jump_active_row(self, *, first: bool) -> bool | None:
        enabled = self._enabled_row_keys()
        if not enabled:
            return None
        next_key = enabled[0] if first else enabled[-1]
        if next_key == self._active_row_key:
            return False
        self._active_row_key = next_key
        return True

    def _move_active_column(self, delta: int) -> bool | None:
        columns = self._visible_column_keys()
        if not columns:
            return None
        if self._active_column_key not in columns:
            self._active_column_key = columns[0]
            return True
        position = columns.index(self._active_column_key)
        next_position = position + delta
        if self.wrap_columns:
            next_position %= len(columns)
        elif next_position < 0 or next_position >= len(columns):
            return False
        next_key = columns[next_position]
        if next_key == self._active_column_key:
            return False
        self._active_column_key = next_key
        return True

    def _jump_active_column(self, *, first: bool) -> bool | None:
        columns = self._visible_column_keys()
        if not columns:
            return None
        next_key = columns[0] if first else columns[-1]
        if next_key == self._active_column_key:
            return False
        self._active_column_key = next_key
        return True

    def _repair_active_cell(self) -> bool:
        if self._is_enabled_cell(self._active_row_key, self._active_column_key):
            return False
        first_cell = self._first_enabled_cell()
        if first_cell is None:
            return False
        row_key, column_key = first_cell
        changed = (row_key, column_key) != (self._active_row_key, self._active_column_key)
        self._active_row_key = row_key
        self._active_column_key = column_key
        return changed

    def _first_enabled_cell(self) -> DataGridCellKey | None:
        for row in self._enabled_rows():
            columns = self._enabled_columns_for_row(row)
            if columns:
                return row.key, columns[0].key
        return None

    def _is_enabled_cell(self, row_key: str | None, column_key: str | None) -> bool:
        if row_key is None or column_key is None:
            return False
        row = self._row_by_key(row_key)
        if row is None or row.disabled or row.pinned is not None or row.key not in self.view_row_keys:
            return False
        if column_key not in self._visible_column_keys():
            return False
        cell = row.cells.get(column_key)
        return cell is not None and not cell.disabled

    def _enabled_rows_with_cells(self) -> tuple[_NormalizedRow, ...]:
        return tuple(row for row in self._enabled_rows() if self._enabled_columns_for_row(row))

    def _enabled_columns_for_row(self, row: _NormalizedRow) -> tuple[DataGridColumn, ...]:
        if row.disabled or row.pinned is not None:
            return ()
        return tuple(
            column
            for column in self._visible_columns()
            if (cell := row.cells.get(column.key)) is not None and not cell.disabled
        )

    def _move_active_cell_column(self, delta: int) -> bool | None:
        repair_result = self._ensure_active_cell_for_navigation()
        if repair_result is not False:
            return repair_result
        row = self._row_by_key(str(self._active_row_key))
        if row is None:
            return None
        columns = tuple(column.key for column in self._enabled_columns_for_row(row))
        if not columns:
            return None
        if self._active_column_key not in columns:
            self._active_column_key = columns[0]
            return True
        position = columns.index(self._active_column_key)
        next_position = position + delta
        if self.wrap_columns:
            next_position %= len(columns)
        elif next_position < 0 or next_position >= len(columns):
            return False
        next_key = columns[next_position]
        if next_key == self._active_column_key:
            return False
        self._active_column_key = next_key
        return True

    def _move_active_cell_row(self, delta: int, *, wrap: bool) -> bool | None:
        repair_result = self._ensure_active_cell_for_navigation()
        if repair_result is not False:
            return repair_result
        rows = self._enabled_rows_with_cells()
        if not rows:
            return None
        row_keys = tuple(row.key for row in rows)
        if self._active_row_key not in row_keys:
            first = rows[0]
            self._active_row_key = first.key
            self._active_column_key = self._enabled_columns_for_row(first)[0].key
            return True
        position = row_keys.index(str(self._active_row_key))
        next_position = position + delta
        if wrap:
            next_position %= len(rows)
        elif next_position < 0 or next_position >= len(rows):
            return False
        else:
            next_position = max(0, min(next_position, len(rows) - 1))
        target_row = rows[next_position]
        target_column = self._nearest_enabled_column_in_row(target_row, self._active_column_key)
        if target_column is None:
            return False
        next_state = (target_row.key, target_column)
        if next_state == (self._active_row_key, self._active_column_key):
            return False
        self._active_row_key, self._active_column_key = next_state
        return True

    def _jump_active_cell_column(self, *, first: bool) -> bool | None:
        repair_result = self._ensure_active_cell_for_navigation()
        if repair_result is not False:
            return repair_result
        row = self._row_by_key(str(self._active_row_key))
        if row is None:
            return None
        columns = tuple(column.key for column in self._enabled_columns_for_row(row))
        if not columns:
            return None
        next_key = columns[0] if first else columns[-1]
        if next_key == self._active_column_key:
            return False
        self._active_column_key = next_key
        return True

    def _ensure_active_cell_for_navigation(self) -> bool | None:
        if self._is_enabled_cell(self._active_row_key, self._active_column_key):
            return False
        return True if self._repair_active_cell() else None

    def _nearest_enabled_column_in_row(self, row: _NormalizedRow, preferred: str | None) -> str | None:
        columns = tuple(column.key for column in self._enabled_columns_for_row(row))
        if not columns:
            return None
        if preferred in columns:
            return str(preferred)
        visible_keys = self._visible_column_keys()
        preferred_index = visible_keys.index(preferred) if preferred in visible_keys else 0
        for column_key in visible_keys[preferred_index + 1 :]:
            if column_key in columns:
                return column_key
        for column_key in reversed(visible_keys[:preferred_index]):
            if column_key in columns:
                return column_key
        return columns[0]

    def _ensure_active_body_visible(self, body_rows: Sequence[_NormalizedRow], height: int) -> None:
        if height <= 0 or not body_rows or self._active_row_key is None:
            self._first_visible_row_index = 0
            return
        index_by_key = {row.key: index for index, row in enumerate(body_rows)}
        active_index = index_by_key.get(self._active_row_key)
        if active_index is None:
            self._first_visible_row_index = max(0, min(self._first_visible_row_index, max(0, len(body_rows) - height)))
            return
        if active_index < self._first_visible_row_index:
            self._first_visible_row_index = active_index
        elif active_index >= self._first_visible_row_index + height:
            self._first_visible_row_index = active_index - height + 1
        max_first = max(0, len(body_rows) - height)
        self._first_visible_row_index = max(0, min(self._first_visible_row_index, max_first))

    def _row_line(
        self,
        row: _NormalizedRow,
        columns: Sequence[DataGridColumn],
        widths: Sequence[int],
        target_width: int,
        *,
        label_width: int,
    ) -> str:
        values: list[str] = []
        cell_token_sets: list[tuple[str | None, ...]] = []
        active_row = self.focused and row.key == self._active_row_key and row.pinned is None and not row.disabled
        for column, width in zip(columns, widths, strict=True):
            cell = row.cells[column.key]
            if self._editing_cell_key == (row.key, column.key):
                edit_text = "" if self._edit_buffer is None else self._edit_buffer.text
                formatted = _FormattedCell(_edit_cell_display_text(edit_text, width), "widget.dataGrid.editing")
            else:
                formatted = _format_grid_cell(cell.value, column)
            values.append(formatted.text)
            cell_token_sets.append(self._cell_theme_tokens(row, column, cell, formatted, active_row=active_row))
        focus_row = active_row and self.cursor_mode in {"row", "cell"}
        prefix = "> " if focus_row else "  "
        label = row.label or row.key if self.show_row_labels else ""
        text = _grid_line(
            tuple(values),
            columns,
            widths,
            target_width,
            prefix=prefix,
            label=label,
            label_width=label_width,
            theme=self.theme,
            cell_token_sets=tuple(cell_token_sets),
        )
        row_token = (
            "widget.dataGrid.disabled"
            if row.disabled
            else "widget.dataGrid.focusRow"
            if focus_row
            else "widget.dataGrid.row"
        )
        return style_text(text, self.theme, row_token, row.theme_token)

    def _cell_theme_tokens(
        self,
        row: _NormalizedRow,
        column: DataGridColumn,
        cell: _NormalizedCell,
        formatted: _FormattedCell,
        *,
        active_row: bool,
    ) -> tuple[str | None, ...]:
        if row.disabled:
            return ()
        if self._editing_cell_key == (row.key, column.key):
            return ("widget.dataGrid.editing",)
        active_cell = active_row and self.cursor_mode == "cell" and self._active_column_key == column.key
        editable = self._is_editable_cell(row.key, column.key)
        interaction_token = (
            "widget.dataGrid.focusEditable"
            if active_cell and editable
            else "widget.dataGrid.editable"
            if editable
            else "widget.dataGrid.focusCell"
            if active_cell
            else None
        )
        return (formatted.theme_token, column.theme_token, cell.theme_token, interaction_token)

    def _active_cell_cursor_column(
        self,
        row: _NormalizedRow,
        columns: Sequence[DataGridColumn],
        widths: Sequence[int],
        cell_starts: Mapping[str, int],
    ) -> int:
        column_key = str(self._active_column_key)
        start = cell_starts.get(column_key, 0)
        for column, width in zip(columns, widths, strict=True):
            if column.key != column_key or width <= 0:
                continue
            cell = row.cells[column.key]
            if self._editing_cell_key == (row.key, column.key):
                edit_text = "" if self._edit_buffer is None else self._edit_buffer.text_before_cursor()
                return start + min(width, visible_width(edit_text))
            text = _format_grid_cell(cell.value, column).text
            return start + _cell_content_offset(text, width, column.align)
        return start


def _normalize_adapter_records(records: Iterable[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    if isinstance(records, (str, bytes)):
        raise TypeError("DataGrid records must contain mappings")
    normalized: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("DataGrid records must contain mappings")
        normalized.append(_string_key_record(record))
    return tuple(normalized)


def _string_key_record(record: Mapping[Any, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in record.items():
        text_key = str(key)
        if text_key in result:
            raise ValueError(f"duplicate record key after string conversion: {text_key!r}")
        result[text_key] = value
    return result


def _columns_from_records(records: Sequence[Mapping[str, object]]) -> tuple[DataGridColumn, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return tuple(_column_from_key(key) for key in keys)


def _column_from_key(key: str) -> DataGridColumn:
    return DataGridColumn(key, _header_from_key(key))


def _header_from_key(key: str) -> str:
    words = str(key).replace("_", " ").replace("-", " ").split()
    return " ".join(word[:1].upper() + word[1:] for word in words) if words else str(key)


def _rows_from_records(
    records: Sequence[Mapping[str, object]],
    *,
    row_key_field: str | None,
) -> tuple[DataGridRow | Mapping[str, object], ...]:
    if row_key_field is None:
        return tuple(records)
    rows: list[DataGridRow] = []
    key_field = str(row_key_field)
    for index, record in enumerate(records):
        if key_field not in record:
            raise ValueError(f"row_key_field {key_field!r} is missing from record {index}")
        rows.append(DataGridRow(str(record[key_field]), record))
    return tuple(rows)


def _json_payload(
    data: str | bytes | bytearray | Sequence[Mapping[str, object]] | Mapping[str, object],
) -> object:
    if isinstance(data, (str, bytes, bytearray)):
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON data: {exc.msg}") from exc
    return data


def _records_from_json_payload(payload: object, *, records_key: str) -> Sequence[Mapping[str, object]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        if records_key not in payload:
            raise ValueError(f"JSON object must contain a {records_key!r} records key")
        records = payload[records_key]
        if not isinstance(records, list):
            raise TypeError(f"JSON {records_key!r} value must be a list of records")
        return records
    raise TypeError("JSON data must be a list of records or an object containing records")


def _records_from_csv(
    data: str | TextIO,
    *,
    dialect: str,
    csv_options: Mapping[str, object] | None,
) -> tuple[tuple[Mapping[str, object], ...], tuple[DataGridColumn, ...]]:
    stream = io.StringIO(data) if isinstance(data, str) else data
    if not hasattr(stream, "read"):
        raise TypeError("CSV data must be a string or text stream")
    reader_options = cast(_CsvReaderOptions, dict(csv_options or {}))
    reader = csv.DictReader(stream, dialect=dialect, **reader_options)
    if not reader.fieldnames:
        raise ValueError("CSV input must include a header row")
    fieldnames = tuple(str(field) for field in reader.fieldnames)
    if any(not field for field in fieldnames):
        raise ValueError("CSV header names must be non-empty")
    records: list[Mapping[str, object]] = []
    for row in reader:
        if None in row:
            raise ValueError("CSV row has more fields than the header")
        records.append({str(key): "" if value is None else value for key, value in row.items()})
    return tuple(records), tuple(_column_from_key(field) for field in fieldnames)


def _normalize_columns(columns: Sequence[DataGridColumn]) -> tuple[DataGridColumn, ...]:
    normalized = tuple(columns)
    seen: set[str] = set()
    for column in normalized:
        if column.key in seen:
            raise ValueError(f"duplicate column key: {column.key!r}")
        seen.add(column.key)
    return normalized


def _cells_from_source(
    source: Mapping[str, object | DataGridCell] | list[object | DataGridCell] | tuple[object | DataGridCell, ...],
    columns: Sequence[DataGridColumn],
) -> dict[str, _NormalizedCell]:
    if isinstance(source, Mapping):
        return {
            column.key: _normalize_cell(source.get(column.key, ""))
            for column in columns
        }
    if isinstance(source, (str, bytes)):
        raise TypeError("DataGrid row cells must be a mapping, list, tuple, or DataGridRow")
    if isinstance(source, (list, tuple)):
        return {
            column.key: _normalize_cell(source[index] if index < len(source) else "")
            for index, column in enumerate(columns)
        }
    raise TypeError("DataGrid row cells must be a mapping, list, tuple, or DataGridRow")


def _normalize_cell(value: object | DataGridCell) -> _NormalizedCell:
    if isinstance(value, DataGridCell):
        return _NormalizedCell(
            value=value.value,
            disabled=value.disabled,
            editable=value.editable,
            theme_token=value.theme_token,
        )
    return _NormalizedCell(value=value)


def _format_grid_cell(value: object, column: DataGridColumn) -> _FormattedCell:
    if column.formatter is not None:
        formatted = column.formatter(value)
    else:
        formatted = TextFormatter()(value)
    if isinstance(formatted, DataGridFormatResult):
        return _FormattedCell(formatted.text, formatted.theme_token)
    theme_token = column.theme_token_for_value(value) if column.theme_token_for_value is not None else None
    return _FormattedCell(str(formatted), theme_token)


def _decimal_from_value(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, float) and not isfinite(value):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return decimal if decimal.is_finite() else None


def _format_decimal(
    value: Decimal,
    *,
    precision: int | None,
    thousands: bool,
    sign: bool,
) -> str:
    prefix = ""
    if value < 0:
        prefix = "-"
    elif sign and value > 0:
        prefix = "+"
    magnitude = abs(value)
    if precision is None:
        text = format(magnitude.normalize(), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if thousands:
            whole, dot, fraction = text.partition(".")
            whole = f"{int(whole):,}" if whole else "0"
            text = f"{whole}{dot}{fraction}" if dot else whole
        return f"{prefix}{text}"

    places = Decimal("1").scaleb(-max(0, precision))
    quantized = magnitude.quantize(places, rounding=ROUND_HALF_UP)
    grouping = "," if thousands else ""
    text = format(quantized, f"{grouping}.{max(0, precision)}f")
    return f"{prefix}{text}"


def _format_compact_decimal(value: Decimal, *, precision: int, sign: bool) -> str:
    prefix = ""
    if value < 0:
        prefix = "-"
    elif sign and value > 0:
        prefix = "+"
    magnitude = abs(value)
    thresholds = (
        (Decimal("1000000000000"), "T"),
        (Decimal("1000000000"), "B"),
        (Decimal("1000000"), "M"),
        (Decimal("1000"), "K"),
    )
    for threshold, suffix in thresholds:
        if magnitude >= threshold:
            compact = magnitude / threshold
            return f"{prefix}{_format_decimal_trimmed(compact, precision)}{suffix}"
    return f"{prefix}{_format_decimal_trimmed(magnitude, precision)}"


def _format_decimal_trimmed(value: Decimal, precision: int) -> str:
    places = Decimal("1").scaleb(-max(0, precision))
    quantized = value.quantize(places, rounding=ROUND_HALF_UP)
    text = format(quantized, f".{max(0, precision)}f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _sortable_value(value: object) -> tuple[int, object]:
    if value is None:
        return (1, "")
    if isinstance(value, (int, float, Decimal)):
        return (0, Decimal(str(value)))
    return (0, str(value))


def _column_widths(columns: Sequence[DataGridColumn], target_width: int) -> tuple[int, ...]:
    if not columns or target_width <= 0:
        return tuple(0 for _ in columns)
    prefix_width = min(2, target_width)
    grid_width = max(0, target_width - prefix_width)
    if grid_width == 0:
        return tuple(0 for _ in columns)

    widths: list[int] = []
    flexible_indices: list[int] = []
    for index, column in enumerate(columns):
        if column.width is None:
            widths.append(column.min_width)
            flexible_indices.append(index)
        else:
            widths.append(max(column.width, column.min_width))

    remaining = grid_width - _occupied_grid_width(widths)
    if remaining > 0 and flexible_indices:
        expandable = list(flexible_indices)
        while remaining > 0 and expandable:
            next_expandable: list[int] = []
            for index in expandable:
                if remaining <= 0:
                    break
                column = columns[index]
                if column.max_width is not None and widths[index] >= column.max_width:
                    continue
                widths[index] += 1
                remaining -= 1
                next_expandable.append(index)
            expandable = next_expandable
    if _occupied_grid_width(widths) > grid_width:
        widths = _shrink_widths_to_fit(widths, grid_width)
    return tuple(widths)


def _occupied_grid_width(widths: Sequence[int]) -> int:
    visible_count = sum(1 for width in widths if width > 0)
    separator_width = max(0, visible_count - 1) * len(DATA_GRID_SEPARATOR)
    return sum(max(0, width) for width in widths) + separator_width


def _shrink_widths_to_fit(widths: Sequence[int], grid_width: int) -> list[int]:
    result = [max(0, width) for width in widths]
    overflow = _occupied_grid_width(result) - max(0, grid_width)
    while overflow > 0 and any(width > 0 for width in result):
        for index in range(len(result) - 1, -1, -1):
            if result[index] <= 0:
                continue
            reduction = min(result[index], overflow)
            result[index] -= reduction
            overflow = _occupied_grid_width(result) - max(0, grid_width)
            if overflow <= 0:
                break
    return result


def _grid_target_width(target_width: int, label_width: int) -> int:
    label_extra = label_width + len(DATA_GRID_SEPARATOR) if label_width > 0 else 0
    return max(0, target_width - label_extra)


def _preferred_width(column: DataGridColumn) -> int:
    if column.width is not None:
        return max(column.width, column.min_width)
    return column.min_width


def _preferred_occupied_width(columns: Sequence[DataGridColumn]) -> int:
    widths = tuple(_preferred_width(column) for column in columns)
    return _occupied_grid_width(widths)


def _cell_start_columns(
    columns: Sequence[DataGridColumn],
    widths: Sequence[int],
    label_width: int,
) -> dict[str, int]:
    offset = 2
    if label_width > 0:
        offset += label_width + len(DATA_GRID_SEPARATOR)
    starts: dict[str, int] = {}
    visible = [(column, width) for column, width in zip(columns, widths, strict=True) if width > 0]
    for index, (column, width) in enumerate(visible):
        starts[column.key] = offset
        offset += width
        if index < len(visible) - 1:
            offset += len(DATA_GRID_SEPARATOR)
    return starts


def _grid_line(
    cells: Sequence[str],
    columns: Sequence[DataGridColumn],
    widths: Sequence[int],
    target_width: int,
    *,
    prefix: str = "  ",
    label: str = "",
    label_width: int = 0,
    theme: ThemeResolver | None = None,
    cell_token_sets: Sequence[Sequence[str | None]] = (),
) -> str:
    rendered: list[str] = []
    visible_cells = [
        (index, cell, width, column)
        for index, (cell, width, column) in enumerate(zip(cells, widths, columns, strict=True))
        if width > 0
    ]
    for offset, (index, cell, width, column) in enumerate(visible_cells):
        rendered_cell = _format_cell_text(cell, width, column.align, pad_right=offset < len(visible_cells) - 1)
        if index < len(cell_token_sets):
            rendered_cell = style_text(rendered_cell, theme, *cell_token_sets[index])
        rendered.append(rendered_cell)
    prefix_text = truncate_to_width(prefix, max_width=2, ellipsis="")
    label_text = ""
    if label_width > 0:
        label_text = _format_cell_text(label, label_width, "left")
        if rendered:
            label_text = f"{label_text}{DATA_GRID_SEPARATOR}"
    text = f"{prefix_text}{label_text}{DATA_GRID_SEPARATOR.join(rendered)}"
    return truncate_to_width(text, max_width=target_width, ellipsis="")


def _format_cell_text(text: str, width: int, align: DataGridAlign, *, pad_right: bool = True) -> str:
    if width <= 0:
        return ""
    clipped = truncate_to_width(text, max_width=width, ellipsis="")
    padding_width = max(0, width - visible_width(clipped))
    if align == "right":
        return f"{' ' * padding_width}{clipped}"
    if align == "center":
        left = padding_width // 2
        right = padding_width - left
        return f"{' ' * left}{clipped}{' ' * right}" if pad_right else f"{' ' * left}{clipped}"
    return f"{clipped}{' ' * padding_width}" if pad_right else clipped


def _edit_cell_display_text(text: str, width: int) -> str:
    if width <= 0:
        return ""
    clipped = truncate_to_width(text, max_width=width, ellipsis="")
    return f"{clipped}{' ' * max(0, width - visible_width(clipped))}"


def _cell_content_offset(text: str, width: int, align: DataGridAlign) -> int:
    clipped = truncate_to_width(text, max_width=width, ellipsis="")
    padding_width = max(0, width - visible_width(clipped))
    if align == "right":
        return padding_width
    if align == "center":
        return padding_width // 2
    return 0
