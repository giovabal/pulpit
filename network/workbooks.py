"""The finishing pass every workbook of an export goes through once the export is complete (``network.site``).

The writers (``network.tables``) lay each table out on its own sheet; :func:`finish` then makes the workbook
readable and self-describing, in one place:

* every table sheet gets a styled, frozen header row, filters on its columns, column widths fitted to the
  content and number formats chosen per column: shares as percentages, p- and q-values with three decimals,
  counts with thousands separators, ids plain, other decimals to the precision their smallest value needs;
* a first *About* sheet says what the workbook holds: the analysis and its scope, when and with what it was
  made, its method document, then each sheet and each column with its meaning (``network.data_dictionary``).

Idempotent: an existing *About* sheet is replaced, so running it again (``compare_analysis``) changes nothing.
"""

from __future__ import annotations

import math
from typing import Any

from network.data_dictionary import ABOUT_SHEET, column_key, describe_column, describe_sheet

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill(start_color="F3F2EE", end_color="F3F2EE", fill_type="solid")
HEADER_FONT = Font(bold=True)
HEADER_BORDER = Border(bottom=Side(style="thin", color="1C1917"))
TITLE_FONT = Font(bold=True, size=14)
SECTION_FONT = Font(bold=True, size=11)
LINK_FONT = Font(color="4338CA", underline="single")

MIN_WIDTH = 8
MAX_WIDTH = 60
# Rows sampled per column to fit its width and choose its number format.
SAMPLE_ROWS = 2000
# Most decimals a fractional column is shown with (the cell keeps its full precision).
MAX_DECIMALS = 6

INTEGER_FORMAT = "#,##0"
ID_FORMAT = "0"
SHARE_FORMAT = "0.0%"
# Three decimals, and "< 0.001" below that, as on the pages (the cell keeps its exact value).
P_FORMAT = '[<0.001]"< 0.001";0.000'
# Columns of the key/value sheets (one statistic per row): each cell is a different quantity, so each takes
# the format its own value needs instead of one format for the column.
PER_CELL_KEYS = frozenset({"value"})


def _is_share(key: str) -> bool:
    return "share" in key.split("_") or key.endswith(("_share", "_fraction")) or key in ("share", "fraction")


def _is_p(key: str) -> bool:
    """A p- or q-value column: ``p``, ``q``, ``level_p_hac``, ``p_ties``, ``dependent_to_dominant_q``…"""
    parts = key.split("_")
    return "p" in parts or "q" in parts


def _is_id(key: str) -> bool:
    return key == "id" or key.endswith("_id")


def _decimal_format(values: list[float]) -> str:
    """``#,##0.000`` with as many decimals as the column's smallest non-zero magnitude needs for 3 significant digits."""
    smallest = min((abs(v) for v in values if v), default=1.0)
    decimals = 2 if smallest >= 1 else min(MAX_DECIMALS, max(2, math.ceil(-math.log10(smallest)) + 2))
    return "#,##0." + "0" * decimals


def number_format(header: str, values: list[Any]) -> str | None:
    """The number format of a column, from its header and its (sampled) values; ``None`` keeps the default."""
    key = column_key(header)
    numbers = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
    if not numbers:
        return None
    if _is_id(key):
        return ID_FORMAT
    if _is_p(key):
        return P_FORMAT
    if _is_share(key) and all(0 <= v <= 1 for v in numbers):
        return SHARE_FORMAT
    if all(_is_whole(v) for v in numbers):
        return INTEGER_FORMAT
    return _decimal_format([float(v) for v in numbers])


def _is_whole(value: Any) -> bool:
    return isinstance(value, int) or float(value).is_integer()


def cell_format(value: Any) -> str | None:
    """The format of one cell of a key/value column: a count stays a count, a fraction gets its own decimals."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return INTEGER_FORMAT if _is_whole(value) else _decimal_format([float(value)])


def _display_length(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, float):
        return min(len(f"{value:,.4f}"), 14)
    return len(str(value))


def format_table_sheet(ws: Any) -> None:
    """Header style, frozen header, filters, widths and number formats of a sheet holding one table."""
    if ws.max_row < 1 or ws.max_column < 1:
        return
    headers = [cell.value for cell in ws[1]]
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.border = HEADER_BORDER
        cell.alignment = Alignment(vertical="bottom")
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions
    # Sampled evenly down the sheet: with a timeline the first rows are all of one period ("All periods"),
    # whose magnitudes need not be the other periods'.
    stride = max(1, (ws.max_row - 1) // SAMPLE_ROWS)
    sample_rows = range(2, ws.max_row + 1, stride)
    for index, header in enumerate(headers, start=1):
        values = [ws.cell(row=row, column=index).value for row in sample_rows]
        per_cell = column_key(str(header or "")) in PER_CELL_KEYS
        fmt = None if per_cell else number_format(str(header or ""), values)
        if fmt or per_cell:
            for (cell,) in ws.iter_rows(min_row=2, min_col=index, max_col=index):
                if isinstance(cell.value, int | float) and not isinstance(cell.value, bool):
                    cell.number_format = cell_format(cell.value) if per_cell else fmt
        width = max([_display_length(header) + 3, *(_display_length(v) + 1 for v in values)])
        ws.column_dimensions[get_column_letter(index)].width = max(MIN_WIDTH, min(MAX_WIDTH, width))


def _about_sheet(wb: Any, name: str, about: dict[str, Any]) -> None:
    if ABOUT_SHEET in wb.sheetnames:
        del wb[ABOUT_SHEET]
    ws = wb.create_sheet(ABOUT_SHEET, 0)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 90
    ws.append([about.get("title") or name])
    ws["A1"].font = TITLE_FONT
    if about.get("description"):
        ws.append([about["description"]])
    ws.append([])
    for label, value in about.get("facts", []):
        ws.append([label, value])
        ws.cell(row=ws.max_row, column=1).font = HEADER_FONT
    for label, url in (("Method", about.get("method_url")), ("Data dictionary", about.get("dictionary_url"))):
        if url:
            ws.append([label, url])
            ws.cell(row=ws.max_row, column=1).font = HEADER_FONT
            link = ws.cell(row=ws.max_row, column=2)
            link.hyperlink = url
            link.font = LINK_FONT
    ws.append([])
    ws.append(["Reading the tables"])
    ws.cell(row=ws.max_row, column=1).font = SECTION_FONT
    ws.append(
        [
            "Each sheet holds one table, with filters on its header row. A table given for every period of the "
            "timeline opens with a Period column, “All periods” being the whole range; a table without that column "
            "covers the whole range only. Columns named as shares are shown as percentages of the 0–1 fractions "
            "the cells hold, p- and q-values with three decimals; every cell keeps its exact value. An empty cell "
            "is a value that does not exist for that row, not a zero."
        ]
    )
    ws.cell(row=ws.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=ws.max_row, start_column=1, end_row=ws.max_row, end_column=3)
    ws.row_dimensions[ws.max_row].height = 45
    ws.append([])
    ws.append(["Sheet", "Column", "Meaning"])
    for cell in ws[ws.max_row]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.border = HEADER_BORDER
    for sheet in wb.worksheets:
        if sheet.title == ABOUT_SHEET:
            continue
        ws.append([sheet.title, "", describe_sheet(name, sheet.title)])
        ws.cell(row=ws.max_row, column=1).font = HEADER_FONT
        ws.cell(row=ws.max_row, column=3).alignment = Alignment(wrap_text=True, vertical="top")
        headers = [c.value for c in sheet[1] if c.value is not None]
        for position, header in enumerate(headers):
            # The position lets a matrix sheet be read by layout (label, categories, total), whatever its title.
            meaning = describe_column(str(header), name, sheet.title, position=position, count=len(headers))
            ws.append(["", str(header), meaning])
            ws.cell(row=ws.max_row, column=3).alignment = Alignment(wrap_text=True, vertical="top")


def finish(path: str, name: str, about: dict[str, Any]) -> None:
    """Format every table sheet of the workbook at *path* and give it its *About* sheet.

    *about*: ``title``, ``description``, ``facts`` (``[(label, value)]``), ``method_url``, ``dictionary_url``.
    """
    wb = openpyxl.load_workbook(path)
    for ws in wb.worksheets:
        if ws.title != ABOUT_SHEET:
            format_table_sheet(ws)
    _about_sheet(wb, name, about)
    wb.active = 0
    wb.save(path)
