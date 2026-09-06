"""Excel timetable parser for the IILM vacant classroom finder."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openpyxl


# Excel teaching-period columns.
# Column G is lunch and is intentionally skipped.
PERIOD_COLUMNS = {
    4: 1,   # 9:00 - 10:15
    5: 2,   # 10:20 - 11:35
    6: 3,   # 11:40 - 12:55
    8: 4,   # 1:40 - 2:55
    9: 5,   # 3:00 - 4:15
    10: 6,  # 4:20 - 5:35
}


DAY_MAP = {
    "mon": "monday",
    "monday": "monday",
    "tue": "tuesday",
    "tues": "tuesday",
    "tuesday": "tuesday",
    "wed": "wednesday",
    "wednesday": "wednesday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "thursday": "thursday",
    "fri": "friday",
    "friday": "friday",
    "sat": "saturday",
    "saturday": "saturday",
    "sun": "sunday",
    "sunday": "sunday",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""

    return " ".join(str(value).split())


def _canonical_room(room: str) -> str:
    room = _clean(room).strip(" .:-")

    aliases = {
        "foundation block 90": "Foundation Block 90",
        "biochemistry lab": "Biochemistry Lab",
        "bio chemistry lab": "Biochemistry Lab",
        "genetic engg lab": "Genetic Engineering Lab",
        "genetic engg. lab": "Genetic Engineering Lab",
        "genetic engineering lab": "Genetic Engineering Lab",
        "food technology lab": "Food Technology Lab",
    }

    return aliases.get(
        room.lower(),
        room,
    )


def _room_from_header(sheet) -> str:
    """
    Read the default room from the sheet header.

    Example:
        BBA, Semester - I (Section-A), Room No: -206

    Returns:
        206
    """

    for row in range(1, 5):
        for col in range(1, 10):

            value = _clean(
                sheet.cell(
                    row=row,
                    column=col,
                ).value
            )

            if not value:
                continue

            # Capture ONLY the room number/name immediately
            # following "Room No".
            #
            # This deliberately stops before any later text.
            match = re.search(
                r"Room\s*No\s*[:\-]*\s*([A-Za-z0-9]+)",
                value,
                re.IGNORECASE,
            )

            if match:
                room = match.group(1)

                return _canonical_room(
                    room
                )

    return ""


def _section_from_header(sheet) -> str:
    """Get the BBA section from the sheet title/header."""

    for row in range(1, 5):
        for col in range(1, 10):

            value = _clean(
                sheet.cell(
                    row=row,
                    column=col,
                ).value
            )

            if not value:
                continue

            match = re.search(
                r"Section\s*[-:]?\s*([A-Za-z0-9]+)",
                value,
                re.IGNORECASE,
            )

            if match:
                return match.group(1)

    return sheet.title


def _room_override(
    note: str,
    default_room: str,
) -> str:
    """
    Handle notes such as:

        BE-1 in 303

    The room after 'in' becomes the actual classroom.
    """

    note = _clean(note)

    if not note:
        return default_room

    match = re.search(
        r"\bin\s+([A-Za-z0-9]+)",
        note,
        re.IGNORECASE,
    )

    if match:
        room = match.group(1).strip()

        return _canonical_room(
            room
        )

    return default_room


def parse_excel_file(
    path: str | Path,
) -> list[dict]:
    """
    Parse a BBA Excel timetable into normalized room records.
    """

    path = Path(path)

    workbook = openpyxl.load_workbook(
        path,
        data_only=True,
    )

    records: list[dict] = []

    for sheet in workbook.worksheets:

        default_room = _room_from_header(
            sheet
        )

        section = _section_from_header(
            sheet
        )

        if not default_room:
            continue

        # Timetable data begins around row 4.
        for row in range(
            4,
            sheet.max_row + 1,
        ):

            day_value = _clean(
                sheet.cell(
                    row=row,
                    column=2,
                ).value
            )

            if not day_value:
                continue

            day = DAY_MAP.get(
                day_value.lower()
            )

            if not day:
                continue

            for (
                column,
                period,
            ) in PERIOD_COLUMNS.items():

                subject = _clean(
                    sheet.cell(
                        row=row,
                        column=column,
                    ).value
                )

                # Empty timetable cell means
                # the default room is free.
                if not subject:
                    continue

                # Column K contains notes,
                # including room changes.
                note = _clean(
                    sheet.cell(
                        row=row,
                        column=11,
                    ).value
                )

                room = _room_override(
                    note,
                    default_room,
                )

                if not room:
                    continue

                records.append(
                    {
                        "day": day,
                        "period": period,
                        "room": room,
                        "section": section,
                        "source": path.name,
                        "sheet": sheet.title,
                        "subject": subject,
                    }
                )

    # Remove exact duplicates.
    unique = {}

    for record in records:

        key = (
            record["day"],
            record["period"],
            record["room"],
            record["section"],
            record["source"],
            record["sheet"],
        )

        unique[key] = record

    return sorted(
        unique.values(),
        key=lambda record: (
            record["day"],
            record["period"],
            record["room"],
            record["section"],
            record["sheet"],
        ),
    )
