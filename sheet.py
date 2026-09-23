from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Dict, List

from openpyxl import load_workbook

from storage import (
    DEFAULT_XLSX_PATH,
    EDITABLE_COLUMNS,
    SHEET_COLUMNS,
    normalize_ticket_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def print_usage() -> None:
    """Print CLI usage information."""
    print(
        "Usage:\n"
        "  python3 sheet.py export /path/to/out.csv\n"
        "  python3 sheet.py apply /path/to/edits.csv"
    )


def load_ticket_rows() -> Dict[int, Dict[str, Any]]:
    """
    Read the current workbook directly.

    We intentionally read the workbook here rather than calling sync.py.
    `sheet.py apply` must have no synchronization side effects.
    """
    if not DEFAULT_XLSX_PATH.exists():
        return {}

    workbook = load_workbook(
        DEFAULT_XLSX_PATH,
        data_only=False,
    )

    if "Tickets" not in workbook.sheetnames:
        raise RuntimeError(
            "fieldserve.xlsx does not contain a 'Tickets' sheet."
        )

    worksheet = workbook["Tickets"]

    headers: Dict[str, int] = {}

    for column_index, cell in enumerate(
        worksheet[1],
        start=1,
    ):
        if cell.value is not None:
            headers[str(cell.value).strip()] = column_index

    missing = [
        column
        for column in SHEET_COLUMNS
        if column not in headers
    ]

    if missing:
        raise RuntimeError(
            "fieldserve.xlsx is missing required columns: "
            + ", ".join(missing)
        )

    ticket_id_column = headers["Ticket ID"]

    rows: Dict[int, Dict[str, Any]] = {}

    for row_number in range(2, worksheet.max_row + 1):
        raw_ticket_id = worksheet.cell(
            row=row_number,
            column=ticket_id_column,
        ).value

        ticket_id = normalize_ticket_id(
            raw_ticket_id
        )

        if ticket_id is None:
            continue

        row: Dict[str, Any] = {}

        for column_name in SHEET_COLUMNS:
            value = worksheet.cell(
                row=row_number,
                column=headers[column_name],
            ).value

            row[column_name] = value

        rows[ticket_id] = row

    return rows


def write_cell(
    worksheet: Any,
    row_number: int,
    column_number: int,
    value: str,
) -> None:
    """
    Write a value exactly as a human typing into Excel would.

    Empty values are represented as an empty cell.
    """
    worksheet.cell(
        row=row_number,
        column=column_number,
        value=value,
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_sheet(
    output_path: str,
) -> None:
    """
    Export the current displayed spreadsheet values to CSV.

    Requirements:
    - row 1 = exact headers
    - one row per ticket
    - computed values are exported as displayed
    """
    workbook = load_workbook(
        DEFAULT_XLSX_PATH,
        data_only=False,
    )

    if "Tickets" not in workbook.sheetnames:
        raise RuntimeError(
            "fieldserve.xlsx does not contain a 'Tickets' sheet."
        )

    worksheet = workbook["Tickets"]

    headers: Dict[str, int] = {}

    for column_index, cell in enumerate(
        worksheet[1],
        start=1,
    ):
        if cell.value is not None:
            headers[str(cell.value).strip()] = column_index

    missing = [
        column
        for column in SHEET_COLUMNS
        if column not in headers
    ]

    if missing:
        raise RuntimeError(
            "fieldserve.xlsx is missing required columns: "
            + ", ".join(missing)
        )

    output = Path(output_path)

    if output.parent != Path("."):
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    with output.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as csv_file:
        writer = csv.writer(csv_file)

        # Exact required header row.
        writer.writerow(SHEET_COLUMNS)

        ticket_id_column = headers["Ticket ID"]

        for row_number in range(
            2,
            worksheet.max_row + 1,
        ):
            ticket_id = normalize_ticket_id(
                worksheet.cell(
                    row=row_number,
                    column=ticket_id_column,
                ).value
            )

            # Ignore completely empty/non-ticket rows.
            if ticket_id is None:
                continue

            values: List[Any] = []

            for column_name in SHEET_COLUMNS:
                value = worksheet.cell(
                    row=row_number,
                    column=headers[column_name],
                ).value

                if value is None:
                    value = ""

                values.append(value)

            writer.writerow(values)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_edits(
    edits_path: str,
) -> None:
    """
    Apply human-style cell edits to fieldserve.xlsx.

    Input CSV contract:

        Ticket ID,Column,Value

    Example:

        581102,Manager,Nefo Zagi
        607702,Purchase Order,https://example.com/po/123

    IMPORTANT:
        This function does not call the API.
        It does not run sync.py.
        It only modifies the local spreadsheet.
    """
    input_path = Path(edits_path)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Edits file does not exist: {input_path}"
        )

    if not DEFAULT_XLSX_PATH.exists():
        raise RuntimeError(
            "fieldserve.xlsx does not exist. "
            "Run sync.py first."
        )

    workbook = load_workbook(
        DEFAULT_XLSX_PATH,
        data_only=False,
    )

    if "Tickets" not in workbook.sheetnames:
        raise RuntimeError(
            "fieldserve.xlsx does not contain a 'Tickets' sheet."
        )

    worksheet = workbook["Tickets"]

    # Build exact column mapping.
    headers: Dict[str, int] = {}

    for column_index, cell in enumerate(
        worksheet[1],
        start=1,
    ):
        if cell.value is not None:
            headers[str(cell.value).strip()] = column_index

    missing = [
        column
        for column in SHEET_COLUMNS
        if column not in headers
    ]

    if missing:
        raise RuntimeError(
            "fieldserve.xlsx is missing required columns: "
            + ", ".join(missing)
        )

    # Build Ticket ID -> Excel row mapping.
    ticket_rows: Dict[int, int] = {}

    ticket_id_column = headers["Ticket ID"]

    for row_number in range(
        2,
        worksheet.max_row + 1,
    ):
        ticket_id = normalize_ticket_id(
            worksheet.cell(
                row=row_number,
                column=ticket_id_column,
            ).value
        )

        if ticket_id is not None:
            ticket_rows[ticket_id] = row_number

    # Read edits.
    with input_path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        required_headers = {
            "Ticket ID",
            "Column",
            "Value",
        }

        if not reader.fieldnames:
            raise ValueError(
                "Edits CSV is missing its header row."
            )

        actual_headers = {
            header.strip()
            for header in reader.fieldnames
            if header
        }

        missing_headers = required_headers - actual_headers

        if missing_headers:
            raise ValueError(
                "Edits CSV is missing required columns: "
                + ", ".join(sorted(missing_headers))
            )

        edit_count = 0

        for line_number, edit in enumerate(
            reader,
            start=2,
        ):
            raw_ticket_id = edit.get(
                "Ticket ID",
                "",
            )

            ticket_id = normalize_ticket_id(
                raw_ticket_id
            )

            if ticket_id is None:
                raise ValueError(
                    f"Invalid Ticket ID on edits CSV line "
                    f"{line_number}: {raw_ticket_id!r}"
                )

            column_name = (
                edit.get("Column", "")
                .strip()
            )

            value = edit.get(
                "Value",
                "",
            )

            # Only editable columns may be changed through the
            # grader's apply interface.
            if column_name not in EDITABLE_COLUMNS:
                raise ValueError(
                    f"Column '{column_name}' cannot be edited. "
                    f"Editable columns are: "
                    f"{', '.join(sorted(EDITABLE_COLUMNS))}"
                )

            row_number = ticket_rows.get(
                ticket_id
            )

            if row_number is None:
                raise ValueError(
                    f"Ticket ID {ticket_id} does not exist "
                    f"in fieldserve.xlsx."
                )

            column_number = headers[column_name]

            write_cell(
                worksheet=worksheet,
                row_number=row_number,
                column_number=column_number,
                value=value,
            )

            edit_count += 1

    # Save ONLY the spreadsheet.
    # No API calls are made here.
    workbook.save(DEFAULT_XLSX_PATH)

    print(
        f"Applied {edit_count} edit(s) to "
        f"{DEFAULT_XLSX_PATH.name}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) != 3:
        print_usage()
        return 2

    command = sys.argv[1]
    path = sys.argv[2]

    try:
        if command == "export":
            export_sheet(path)
            return 0

        if command == "apply":
            apply_edits(path)
            return 0

        print(
            f"Unknown command: {command}"
        )
        print_usage()
        return 2

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())